#!/usr/bin/env python3
"""
generate_openapi.py — Generate and validate OpenAPI 3.1 specs.

Modes:
  requirements   Generate an OpenAPI 3.1 spec from a requirements description or structured JSON.
  fastapi        Extract OpenAPI JSON from a FastAPI application file.
  spring         Import / convert an existing SpringDoc or Swagger 2.0 spec to OpenAPI 3.1.
  tsoa           Generate an OpenAPI stub from tsoa controller/routes files.
  validate       Validate an existing OpenAPI YAML/JSON file.

Examples:
  python generate_openapi.py requirements --from-description "A task management API with CRUD endpoints" --output openapi.yaml
  python generate_openapi.py fastapi --app tasks.main:app --output openapi.yaml
  python generate_openapi.py spring --input api-docs.json --output openapi.yaml
  python generate_openapi.py validate --input openapi.yaml
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# YAML helpers (no external deps required)
# ---------------------------------------------------------------------------

class _YamlWriter:
    """Minimal YAML emitter for OpenAPI-sized documents."""

    def __init__(self):
        self.indent_str = "  "

    def _escape(self, s: str) -> str:
        if s is None:
            return "null"
        if isinstance(s, bool):
            return "true" if s else "false"
        if isinstance(s, (int, float)):
            return str(s)
        need_quote = False
        if not s:
            need_quote = True
        elif s.startswith(("{", "[", "'", '"', "|", ">", "*", "&", "!", "%", "@", "`", "#")):
            need_quote = True
        elif ": " in s or " #" in s or s.startswith("#"):
            need_quote = True
            need_quote = True
        elif s in ("true", "false", "null", "yes", "no", "on", "off"):
            need_quote = True
        elif re.search(r"[\n\r]", s):
            return self._literal_block(s)
        if need_quote:
            return json.dumps(s)
        return s

    def _literal_block(self, s: str) -> str:
        lines = s.splitlines()
        return "|-\n" + "\n".join("  " + line for line in lines)

    def _dump(self, obj: Any, indent: int = 0) -> str:
        prefix = self.indent_str * indent
        if obj is None:
            return "null"
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if isinstance(obj, (int, float)):
            return str(obj)
        if isinstance(obj, str):
            return prefix + self._escape(obj)
        if isinstance(obj, list):
            if not obj:
                return "[]"
            lines = []
            for item in obj:
                if isinstance(item, dict):
                    # Inline single-key dicts for compactness or block for readability
                    lines.append(prefix + "- " + self._dump(item, indent + 1).lstrip())
                else:
                    lines.append(prefix + "- " + self._dump(item, 0))
            return "\n".join(lines)
        if isinstance(obj, dict):
            if not obj:
                return "{}"
            lines = []
            for k, v in obj.items():
                key = prefix + self._escape(str(k)) + ":"
                if isinstance(v, dict):
                    if not v:
                        lines.append(key + " {}")
                    else:
                        lines.append(key)
                        lines.append(self._dump(v, indent + 1))
                elif isinstance(v, list):
                    if not v:
                        lines.append(key + " []")
                    else:
                        lines.append(key)
                        lines.append(self._dump(v, indent + 1))
                else:
                    lines.append(key + " " + self._dump(v, 0))
            return "\n".join(lines)
        return str(obj)

    def dumps(self, obj: Any) -> str:
        return self._dump(obj, 0)


def _write_spec(data: dict, output_path: Path, fmt: str = "yaml") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        output_path.write_text(_YamlWriter().dumps(data) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# OpenAPI 3.1 boilerplate
# ---------------------------------------------------------------------------

def _make_openapi_skeleton(title: str, version: str, description: str = "") -> dict:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version,
            "description": description,
        },
        "paths": {},
        "components": {
            "schemas": {},
            "parameters": {},
            "responses": {},
            "securitySchemes": {},
        },
    }


def _error_schema() -> dict:
    return {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["code", "message", "request_id"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "request_id": {"type": "string"},
                    "details": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    }


def _paginated_wrapper(item_schema_ref: str) -> dict:
    return {
        "type": "object",
        "required": ["data", "pagination"],
        "properties": {
            "data": {
                "type": "array",
                "items": {"$ref": item_schema_ref},
            },
            "pagination": {
                "type": "object",
                "required": ["offset", "limit", "total", "has_more"],
                "properties": {
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "total": {"type": "integer"},
                    "has_more": {"type": "boolean"},
                },
            },
        },
    }


def _cursor_paginated_wrapper(item_schema_ref: str) -> dict:
    return {
        "type": "object",
        "required": ["data", "pagination"],
        "properties": {
            "data": {
                "type": "array",
                "items": {"$ref": item_schema_ref},
            },
            "pagination": {
                "type": "object",
                "required": ["has_more"],
                "properties": {
                    "next_cursor": {"type": "string", "nullable": True},
                    "prev_cursor": {"type": "string", "nullable": True},
                    "has_more": {"type": "boolean"},
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Requirements -> OpenAI (heuristic generation)
# ---------------------------------------------------------------------------

def _extract_entities(description: str) -> list:
    """Naive entity extraction from a requirements sentence."""
    entities = []
    # Look for plural nouns after common keywords
    patterns = [
        re.compile(r"([a-z]+)\s+manag(?:ement|ing)", re.IGNORECASE),
        re.compile(r"([a-z]+)\s+CRUD", re.IGNORECASE),
        re.compile(r"([a-z]+)\s+API", re.IGNORECASE),
    ]
    for pat in patterns:
        for m in pat.finditer(description):
            candidate = m.group(1).lower()
            if len(candidate) > 2:
                entities.append(candidate)
    # Fallback: find capitalized plural words
    for m in re.finditer(r"\b([A-Z][a-z]+)s\b", description):
        entities.append(m.group(1).lower() + "s")
    return list(dict.fromkeys(entities)) or ["resources"]


def generate_from_description(description: str, title: str | None = None, version: str = "1.0.0") -> dict:
    """Generate a starter OpenAPI 3.1 spec from a natural language description."""
    entities = _extract_entities(description)
    primary = entities[0]
    singular = primary.rstrip("s")
    spec = _make_openapi_skeleton(
        title=title or f"{singular.title()} Service API",
        version=version,
        description=description,
    )

    # Common reusable parameters
    spec["components"]["parameters"]["PageLimit"] = {
        "name": "limit",
        "in": "query",
        "schema": {"type": "integer", "default": 20, "maximum": 100},
    }
    spec["components"]["parameters"]["PageOffset"] = {
        "name": "offset",
        "in": "query",
        "schema": {"type": "integer", "default": 0, "minimum": 0},
    }
    spec["components"]["parameters"]["PageCursor"] = {
        "name": "cursor",
        "in": "query",
        "schema": {"type": "string"},
    }

    # Schemas
    spec["components"]["schemas"][singular.title()] = {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
    }
    spec["components"]["schemas"][f"{singular.title()}Create"] = {
        "type": "object",
        "required": ["name"],
        "properties": {
            "name": {"type": "string"},
        },
    }
    spec["components"]["schemas"][f"{singular.title()}Update"] = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
        },
    }
    spec["components"]["schemas"]["PaginatedList"] = _paginated_wrapper(f"#/components/schemas/{singular.title()}")
    spec["components"]["schemas"]["CursorPaginatedList"] = _cursor_paginated_wrapper(f"#/components/schemas/{singular.title()}")
    spec["components"]["schemas"]["Error"] = _error_schema()

    # Paths
    base = f"/{primary}"
    item = f"/{primary}/{{id}}"

    spec["paths"][base] = {
        "get": {
            "operationId": f"list{singular.title()}s",
            "parameters": [
                {"$ref": "#/components/parameters/PageLimit"},
                {"$ref": "#/components/parameters/PageOffset"},
            ],
            "responses": {
                "200": {
                    "description": f"Paginated list of {primary}",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/PaginatedList"}
                        }
                    },
                },
                "400": {"$ref": "#/components/responses/BadRequest"},
            },
        },
        "post": {
            "operationId": f"create{singular.title()}",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{singular.title()}Create"}
                    }
                },
            },
            "responses": {
                "201": {
                    "description": f"{singular.title()} created",
                    "headers": {
                        "Location": {
                            "description": f"URL of the created {singular}",
                            "schema": {"type": "string"},
                        }
                    },
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{singular.title()}"}
                        }
                    },
                },
                "409": {"$ref": "#/components/responses/Conflict"},
                "422": {"$ref": "#/components/responses/Unprocessable"},
            },
        },
    }

    spec["paths"][item] = {
        "get": {
            "operationId": f"get{singular.title()}",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "200": {
                    "description": f"A single {singular}",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{singular.title()}"}
                        }
                    },
                },
                "404": {"$ref": "#/components/responses/NotFound"},
            },
        },
        "patch": {
            "operationId": f"update{singular.title()}",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": f"#/components/schemas/{singular.title()}Update"}
                    }
                },
            },
            "responses": {
                "200": {
                    "description": f"{singular.title()} updated",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{singular.title()}"}
                        }
                    },
                },
                "404": {"$ref": "#/components/responses/NotFound"},
                "409": {"$ref": "#/components/responses/Conflict"},
            },
        },
        "delete": {
            "operationId": f"delete{singular.title()}",
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "responses": {
                "204": {"description": f"{singular.title()} deleted"},
                "404": {"$ref": "#/components/responses/NotFound"},
            },
        },
    }

    # Common responses
    spec["components"]["responses"]["BadRequest"] = {
        "description": "Bad request",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    spec["components"]["responses"]["NotFound"] = {
        "description": "Not found",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    spec["components"]["responses"]["Conflict"] = {
        "description": "Conflict",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    spec["components"]["responses"]["Unprocessable"] = {
        "description": "Validation error",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }

    return spec


def generate_from_json(requirements_path: Path) -> dict:
    """Generate an OpenAPI spec from a structured JSON requirements file."""
    data = json.loads(requirements_path.read_text(encoding="utf-8"))
    title = data.get("title", "Generated API")
    version = data.get("version", "1.0.0")
    description = data.get("description", "")
    resources = data.get("resources", [])
    auth = data.get("auth", {})

    spec = _make_openapi_skeleton(title, version, description)

    # Auth
    if auth.get("type") == "bearer":
        spec["components"]["securitySchemes"]["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    elif auth.get("type") == "apiKey":
        spec["components"]["securitySchemes"]["apiKeyAuth"] = {
            "type": "apiKey",
            "in": auth.get("in", "header"),
            "name": auth.get("name", "X-API-Key"),
        }

    spec["components"]["schemas"]["Error"] = _error_schema()
    spec["components"]["parameters"]["PageLimit"] = {
        "name": "limit",
        "in": "query",
        "schema": {"type": "integer", "default": 20, "maximum": 100},
    }
    spec["components"]["parameters"]["PageOffset"] = {
        "name": "offset",
        "in": "query",
        "schema": {"type": "integer", "default": 0, "minimum": 0},
    }
    spec["components"]["parameters"]["PageCursor"] = {
        "name": "cursor",
        "in": "query",
        "schema": {"type": "string"},
    }

    for resource in resources:
        name = resource["name"]
        singular = resource.get("singular", name.rstrip("s"))
        fields = resource.get("fields", {})
        required = resource.get("required", ["id"])
        ops = resource.get("operations", ["list", "create", "get", "update", "delete"])
        pagination = resource.get("pagination", "offset")

        schema = {"type": "object", "required": required, "properties": {}}
        for fname, fdef in fields.items():
            if isinstance(fdef, str):
                schema["properties"][fname] = {"type": fdef}
            else:
                schema["properties"][fname] = fdef
        spec["components"]["schemas"][singular.title()] = schema

        create_schema = {"type": "object", "properties": {}}
        update_schema = {"type": "object", "properties": {}}
        for fname, fdef in fields.items():
            if fname == "id":
                continue
            if isinstance(fdef, str):
                create_schema["properties"][fname] = {"type": fdef}
                update_schema["properties"][fname] = {"type": fdef}
            else:
                create_schema["properties"][fname] = fdef
                update_schema["properties"][fname] = fdef
        if resource.get("create_required"):
            create_schema["required"] = resource["create_required"]
        spec["components"]["schemas"][f"{singular.title()}Create"] = create_schema
        spec["components"]["schemas"][f"{singular.title()}Update"] = update_schema

        if pagination == "cursor":
            list_schema_ref = "CursorPaginatedList"
            if "CursorPaginatedList" not in spec["components"]["schemas"]:
                spec["components"]["schemas"]["CursorPaginatedList"] = _cursor_paginated_wrapper(f"#/components/schemas/{singular.title()}")
        else:
            list_schema_ref = "PaginatedList"
            if "PaginatedList" not in spec["components"]["schemas"]:
                spec["components"]["schemas"]["PaginatedList"] = _paginated_wrapper(f"#/components/schemas/{singular.title()}")

        base = f"/{name}"
        item = f"/{name}/{{id}}"

        if "list" in ops:
            params = [{"$ref": "#/components/parameters/PageLimit"}]
            if pagination == "offset":
                params.append({"$ref": "#/components/parameters/PageOffset"})
            else:
                params.append({"$ref": "#/components/parameters/PageCursor"})
            for f, fdef in resource.get("filters", {}).items():
                param = {"name": f, "in": "query", "schema": {"type": "string"}}
                if isinstance(fdef, dict):
                    param.update(fdef)
                params.append(param)
            spec["paths"][base] = spec["paths"].get(base, {})
            spec["paths"][base]["get"] = {
                "operationId": f"list{singular.title()}s",
                "parameters": params,
                "responses": {
                    "200": {
                        "description": f"Paginated list of {name}",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{list_schema_ref}"}
                            }
                        },
                    },
                    "400": {"$ref": "#/components/responses/BadRequest"},
                },
            }

        if "create" in ops:
            spec["paths"][base] = spec["paths"].get(base, {})
            spec["paths"][base]["post"] = {
                "operationId": f"create{singular.title()}",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{singular.title()}Create"}
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": f"{singular.title()} created",
                        "headers": {
                            "Location": {
                                "description": f"URL of the created {singular}",
                                "schema": {"type": "string"},
                            }
                        },
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{singular.title()}"}
                            }
                        },
                    },
                    "409": {"$ref": "#/components/responses/Conflict"},
                    "422": {"$ref": "#/components/responses/Unprocessable"},
                },
            }

        if "get" in ops:
            spec["paths"][item] = spec["paths"].get(item, {})
            spec["paths"][item]["get"] = {
                "operationId": f"get{singular.title()}",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": f"A single {singular}",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{singular.title()}"}
                            }
                        },
                    },
                    "404": {"$ref": "#/components/responses/NotFound"},
                },
            }

        if "update" in ops:
            spec["paths"][item] = spec["paths"].get(item, {})
            spec["paths"][item]["patch"] = {
                "operationId": f"update{singular.title()}",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/merge-patch+json": {
                            "schema": {"$ref": f"#/components/schemas/{singular.title()}Update"}
                        },
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{singular.title()}Update"}
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": f"{singular.title()} updated",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{singular.title()}"}
                            }
                        },
                    },
                    "404": {"$ref": "#/components/responses/NotFound"},
                    "409": {"$ref": "#/components/responses/Conflict"},
                },
            }

        if "delete" in ops:
            spec["paths"][item] = spec["paths"].get(item, {})
            spec["paths"][item]["delete"] = {
                "operationId": f"delete{singular.title()}",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "204": {"description": f"{singular.title()} deleted"},
                    "404": {"$ref": "#/components/responses/NotFound"},
                },
            }

    # Ensure common responses exist
    for code, desc in (
        ("BadRequest", "Bad request"),
        ("NotFound", "Not found"),
        ("Conflict", "Conflict"),
        ("Unprocessable", "Validation error"),
    ):
        if code not in spec["components"]["responses"]:
            spec["components"]["responses"][code] = {
                "description": desc,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
            }

    return spec


# ---------------------------------------------------------------------------
# FastAPI extraction
# ---------------------------------------------------------------------------

def extract_fastapi(app_path: str) -> dict:
    """Import a FastAPI app and return its OpenAPI dict.

    app_path format: module.submodule:variable
    Example: tasks.main:app
    """
    import importlib.util

    if ":" not in app_path:
        raise ValueError("app_path must be 'module:variable' (e.g., tasks.main:app)")
    module_path, var_name = app_path.split(":", 1)
    file_path = Path(module_path.replace(".", "/") + ".py")
    if not file_path.exists():
        # Try resolving relative to cwd / PYTHONPATH
        for root in sys.path:
            candidate = Path(root) / module_path.replace(".", "/") / "__init__.py"
            if candidate.exists():
                file_path = candidate
                break
            candidate = Path(root) / (module_path.replace(".", "/") + ".py")
            if candidate.exists():
                file_path = candidate
                break

    if not file_path.exists():
        raise FileNotFoundError(f"Could not find module for {module_path}")

    spec = importlib.util.spec_from_file_location(module_path, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_path] = module
    spec.loader.exec_module(module)
    app = getattr(module, var_name)
    openapi = getattr(app, "openapi", lambda: None)()
    if openapi is None:
        raise RuntimeError("FastAPI app did not produce an OpenAPI schema. Ensure the app is initialized.")
    # Convert to 3.1 if needed (FastAPI usually emits 3.1 by default in recent versions)
    openapi["openapi"] = "3.1.0"
    return openapi


# ---------------------------------------------------------------------------
# Spring / Swagger conversion to OpenAPI 3.1
# ---------------------------------------------------------------------------

def convert_spring_to_openapi31(input_path: Path) -> dict:
    """Upgrade a Swagger 2.0 or OpenAPI 3.0 spec to OpenAPI 3.1."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    version = data.get("openapi", data.get("swagger", "2.0"))
    if version.startswith("3.1"):
        return data

    if version.startswith("2.0"):
        # Minimal 2.0 -> 3.1 conversion (not exhaustive, but sufficient for SpringDoc output)
        data["openapi"] = "3.1.0"
        if "swagger" in data:
            del data["swagger"]
        info = data.pop("info", {})
        base_path = data.pop("basePath", "")
        schemes = data.pop("schemes", ["https"])
        host = data.pop("host", "localhost")
        servers = [{"url": f"{schemes[0]}://{host}{base_path}"}]
        data["info"] = info
        data["servers"] = servers
        paths = data.pop("paths", {})
        definitions = data.pop("definitions", {})
        data["paths"] = paths
        data["components"] = {"schemas": definitions, "securitySchemes": {}}
        # Convert securityDefinitions
        sec_defs = data.pop("securityDefinitions", {})
        for k, v in sec_defs.items():
            if v.get("type") == "basic":
                data["components"]["securitySchemes"][k] = {"type": "http", "scheme": "basic"}
            elif v.get("type") == "apiKey":
                data["components"]["securitySchemes"][k] = {
                    "type": "apiKey",
                    "in": v.get("in", "header"),
                    "name": v.get("name", "X-API-Key"),
                }
            elif v.get("type") == "oauth2":
                data["components"]["securitySchemes"][k] = {
                    "type": "oauth2",
                    "flows": {},
                }
        # Convert responses referencing definitions
        for path_item in paths.values():
            for op in path_item.values():
                if not isinstance(op, dict):
                    continue
                if "produces" in op:
                    del op["produces"]
                if "consumes" in op:
                    del op["consumes"]
                responses = op.get("responses", {})
                for code, resp in responses.items():
                    if "schema" in resp:
                        schema = resp.pop("schema")
                        resp["content"] = {"application/json": {"schema": schema}}
                    # Convert headers
                    if "headers" in resp:
                        for hname, hdef in resp["headers"].items():
                            if "type" in hdef:
                                htype = hdef.pop("type")
                                hdef["schema"] = {"type": htype}
        # Update $ref pointers
        def _fix_refs(obj: Any) -> Any:
            if isinstance(obj, dict):
                if obj.get("$ref", "").startswith("#/definitions/"):
                    obj["$ref"] = obj["$ref"].replace("#/definitions/", "#/components/schemas/")
                return {k: _fix_refs(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_fix_refs(i) for i in obj]
            return obj
        data = _fix_refs(data)
        return data

    if version.startswith("3.0"):
        data["openapi"] = "3.1.0"
        # 3.0 -> 3.1 is mostly compatible; minor changes only
        def _remove_nullable(obj: Any) -> Any:
            if isinstance(obj, dict):
                if "nullable" in obj and "type" in obj:
                    if obj["nullable"]:
                        obj["type"] = [obj["type"], "null"]
                    del obj["nullable"]
                return {k: _remove_nullable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_remove_nullable(i) for i in obj]
            return obj
        data = _remove_nullable(data)
        return data

    raise ValueError(f"Unsupported spec version: {version}")


# ---------------------------------------------------------------------------
# tsoa extraction (stub generation from TS decorators)
# ---------------------------------------------------------------------------

def extract_tsoa(controllers_dir: Path) -> dict:
    """Naive extraction of tsoa routes from TypeScript controller files.

    Scans for @Route, @Get, @Post, @Patch, @Delete, @Put decorators and
    builds an OpenAPI 3.1 skeleton. This is a best-effort parser for
    unannotated controller files; the official tsoa `generate-spec` command
    is preferred when available.
    """
    spec = _make_openapi_skeleton(
        title="Generated from tsoa controllers",
        version="1.0.0",
        description="Auto-generated OpenAPI 3.1 from tsoa controller scan.",
    )
    spec["components"]["schemas"]["Error"] = _error_schema()
    spec["components"]["responses"]["BadRequest"] = {
        "description": "Bad request",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    spec["components"]["responses"]["NotFound"] = {
        "description": "Not found",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }
    spec["components"]["responses"]["Unprocessable"] = {
        "description": "Validation error",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    }

    route_prefix = ""
    for ts_file in controllers_dir.rglob("*.ts"):
        text = ts_file.read_text(encoding="utf-8")
        for m in re.finditer(r'@Route\("([^"]+)"\)', text):
            route_prefix = m.group(1)
        for m in re.finditer(r'@(Get|Post|Put|Patch|Delete)\("([^"]*)"(?:.*\n)*?\s*(?:public|private|protected)?\s*(?:async\s+)?(\w+)\s*\(', text):
            method = m.group(1).lower()
            subpath = m.group(2)
            operation_id = m.group(3)
            path = (route_prefix + "/" + subpath).replace("//", "/")
            if path not in spec["paths"]:
                spec["paths"][path] = {}
            spec["paths"][path][method] = {
                "operationId": operation_id,
                "responses": {
                    "200": {"description": "Success"},
                    "400": {"$ref": "#/components/responses/BadRequest"},
                },
            }
    return spec


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_spec(input_path: Path) -> list[str]:
    """Perform structural validation of an OpenAPI 3.1 spec.

    Returns a list of error strings. Empty list means no obvious issues found.
    """
    errors: list[str] = []
    text = input_path.read_text(encoding="utf-8")
    if input_path.suffix in (".yaml", ".yml"):
        # Minimal YAML -> dict parsing (no PyYAML dependency)
        try:
            import yaml
            data = yaml.safe_load(text)
        except ImportError:
            errors.append("PyYAML not installed; cannot validate YAML. Install with: pip install pyyaml")
            return errors
        except Exception as e:
            errors.append(f"YAML parse error: {e}")
            return errors
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")
            return errors

    if not isinstance(data, dict):
        errors.append("Top-level value must be an object.")
        return errors

    version = data.get("openapi", "")
    if not version.startswith("3.1"):
        errors.append(f"Expected openapi: 3.1.x, found: {version}")

    info = data.get("info")
    if not isinstance(info, dict):
        errors.append("Missing 'info' object.")
    else:
        if not info.get("title"):
            errors.append("info.title is required.")
        if not info.get("version"):
            errors.append("info.version is required.")

    paths = data.get("paths")
    if not isinstance(paths, dict) or not paths:
        errors.append("Missing or empty 'paths' object.")
    else:
        for path, item in paths.items():
            if not path.startswith("/"):
                errors.append(f"Path must start with /: {path}")
            if not isinstance(item, dict):
                errors.append(f"Path item must be an object: {path}")
                continue
            for method, op in item.items():
                if method not in (
                    "get", "post", "put", "patch", "delete", "head", "options", "trace",
                    "parameters", "summary", "description", "servers",
                ):
                    continue
                if not isinstance(op, dict):
                    continue
                if not op.get("operationId"):
                    errors.append(f"Missing operationId for {method.upper()} {path}")
                if "responses" not in op:
                    errors.append(f"Missing responses for {method.upper()} {path}")
                else:
                    for code, resp in op["responses"].items():
                        code_str = str(code)
                        if not re.match(r"^[1-5]\d{2}$|^default$", code_str):
                            errors.append(f"Invalid response code '{code_str}' for {method.upper()} {path}")
                        if isinstance(resp, dict) and "content" in resp:
                            for ct, media in resp["content"].items():
                                if ct.startswith("application/json"):
                                    if "schema" not in media:
                                        errors.append(f"JSON response missing schema for {method.upper()} {path} {code_str}")

    components = data.get("components", {})
    schemas = components.get("schemas", {})
    for name, schema in schemas.items():
        if isinstance(schema, dict):
            if "type" in schema and schema["type"] not in (
                "string", "integer", "number", "boolean", "array", "object", "null"
            ):
                errors.append(f"Invalid schema type '{schema['type']}' in components.schemas.{name}")

    # Check for broken $ref pointers
    refs = re.findall(r'"\$ref":\s*"([^"]+)"', json.dumps(data))
    for ref in refs:
        if not ref.startswith("#/"):
            errors.append(f"External or invalid $ref found: {ref}")
            continue
        parts = ref.lstrip("#/").split("/")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                errors.append(f"Broken $ref: {ref}")
                break

    return errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate and validate OpenAPI 3.1 specs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # requirements
    req_parser = subparsers.add_parser("requirements", help="Generate from requirements")
    req_parser.add_argument("--from-description", type=str, help="Natural language description")
    req_parser.add_argument("--from-json", type=Path, help="Path to structured JSON requirements file")
    req_parser.add_argument("--title", type=str, default=None)
    req_parser.add_argument("--version", type=str, default="1.0.0")
    req_parser.add_argument("--output", type=Path, required=True)
    req_parser.add_argument("--format", choices=["yaml", "json"], default="yaml")

    # fastapi
    fa_parser = subparsers.add_parser("fastapi", help="Extract from FastAPI app")
    fa_parser.add_argument("--app", type=str, required=True, help="module:variable (e.g., main:app)")
    fa_parser.add_argument("--output", type=Path, required=True)
    fa_parser.add_argument("--format", choices=["yaml", "json"], default="yaml")

    # spring
    sp_parser = subparsers.add_parser("spring", help="Convert Swagger/SpringDoc to OpenAPI 3.1")
    sp_parser.add_argument("--input", type=Path, required=True)
    sp_parser.add_argument("--output", type=Path, required=True)
    sp_parser.add_argument("--format", choices=["yaml", "json"], default="yaml")

    # tsoa
    ts_parser = subparsers.add_parser("tsoa", help="Extract from tsoa controllers")
    ts_parser.add_argument("--controllers-dir", type=Path, required=True)
    ts_parser.add_argument("--output", type=Path, required=True)
    ts_parser.add_argument("--format", choices=["yaml", "json"], default="yaml")

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate an existing spec")
    val_parser.add_argument("--input", type=Path, required=True)

    args = parser.parse_args(argv)

    if args.command == "requirements":
        if args.from_description:
            spec = generate_from_description(args.from_description, title=args.title, version=args.version)
        elif args.from_json:
            spec = generate_from_json(args.from_json)
        else:
            print("error: --from-description or --from-json required", file=sys.stderr)
            return 1
        _write_spec(spec, args.output, args.format)
        print(f"Written: {args.output}")

    elif args.command == "fastapi":
        try:
            spec = extract_fastapi(args.app)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        _write_spec(spec, args.output, args.format)
        print(f"Written: {args.output}")

    elif args.command == "spring":
        try:
            spec = convert_spring_to_openapi31(args.input)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        _write_spec(spec, args.output, args.format)
        print(f"Written: {args.output}")

    elif args.command == "tsoa":
        if not args.controllers_dir.exists():
            print(f"error: directory not found: {args.controllers_dir}", file=sys.stderr)
            return 1
        spec = extract_tsoa(args.controllers_dir)
        _write_spec(spec, args.output, args.format)
        print(f"Written: {args.output}")

    elif args.command == "validate":
        errors = validate_spec(args.input)
        if errors:
            print(f"Validation failed for {args.input}:")
            for err in errors:
                print(f"  - {err}")
            return 1
        else:
            print(f"Validation passed for {args.input}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
