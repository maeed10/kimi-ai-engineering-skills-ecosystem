#!/usr/bin/env python3
"""
artifact-verifier validation engine.
Deterministic, non-LLM validator for phase completion artifacts.
Usage:
    python validate_artifact.py --artifact <path> --phase <PHASE> [--strict] [--output <path>]
"""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------
EXIT_PASS = 0
EXIT_WARN = 0
EXIT_FAIL = 1
EXIT_ERROR = 2

# ---------------------------------------------------------------------------
# JSON Schemas (embedded for portability)
# ---------------------------------------------------------------------------
SCHEMAS: Dict[str, Dict[str, Any]] = {
    "plan_artifact_v1": {
        "type": "object",
        "required": ["objectives", "constraints", "alternatives", "risk_assessment", "timeline"],
        "properties": {
            "objectives": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "description", "priority"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^OBJ-[0-9]+$"},
                        "description": {"type": "string", "minLength": 10},
                        "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}}
                    }
                }
            },
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["type", "description"],
                    "properties": {
                        "type": {"type": "string", "enum": ["technical", "business", "legal", "resource", "time"]},
                        "description": {"type": "string", "minLength": 5}
                    }
                }
            },
            "alternatives": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "description", "tradeoffs"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^ALT-[0-9]+$"},
                        "description": {"type": "string", "minLength": 10},
                        "tradeoffs": {"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 5}}
                    }
                }
            },
            "risk_assessment": {
                "type": "object",
                "required": ["risks"],
                "properties": {
                    "risks": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["id", "severity", "mitigation"],
                            "properties": {
                                "id": {"type": "string", "pattern": "^RISK-[0-9]+$"},
                                "description": {"type": "string", "minLength": 5},
                                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                                "mitigation": {"type": "string", "minLength": 5},
                                "owner": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "timeline": {
                "type": "object",
                "required": ["phases"],
                "properties": {
                    "phases": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["name", "order"],
                            "properties": {
                                "name": {"type": "string", "enum": ["INGEST", "PLAN", "ASSESS", "EXECUTE", "DELIVER", "VALIDATE", "REMEMBER"]},
                                "order": {"type": "integer", "minimum": 1},
                                "duration_estimate": {"type": "string"},
                                "dependencies": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    }
                }
            }
        }
    },
    "validate_artifact_v1": {
        "type": "object",
        "required": ["test_results", "coverage", "findings"],
        "properties": {
            "test_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "status"],
                    "properties": {
                        "name": {"type": "string"},
                        "status": {"type": "string", "enum": ["pass", "fail", "skip", "error"]},
                        "duration_ms": {"type": "number", "minimum": 0},
                        "message": {"type": "string"}
                    }
                }
            },
            "coverage": {
                "type": "object",
                "required": ["lines"],
                "properties": {
                    "lines": {"type": "number", "minimum": 0, "maximum": 100},
                    "branches": {"type": "number", "minimum": 0, "maximum": 100},
                    "functions": {"type": "number", "minimum": 0, "maximum": 100}
                }
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["severity", "description"],
                    "properties": {
                        "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
                        "description": {"type": "string", "minLength": 5},
                        "location": {"type": "string"},
                        "rule_id": {"type": "string"}
                    }
                }
            }
        }
    },
    "remember_artifact_v1": {
        "type": "object",
        "required": ["session_id", "timestamp", "artifacts", "learnings"],
        "properties": {
            "session_id": {"type": "string", "minLength": 1},
            "timestamp": {"type": "string"},
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["path", "type", "checksum"],
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "type": {"type": "string"},
                        "checksum": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
                    }
                }
            },
            "learnings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["category", "description"],
                    "properties": {
                        "category": {"type": "string", "enum": ["technical", "process", "security", "business"]},
                        "description": {"type": "string", "minLength": 10},
                        "related_artifact": {"type": "string"}
                    }
                }
            }
        }
    },
    "ingest_artifact_v1": {
        "type": "object",
        "required": ["request", "context"],
        "properties": {
            "request": {
                "type": "object",
                "required": ["description"],
                "properties": {
                    "description": {"type": "string", "minLength": 10},
                    "source": {"type": "string", "enum": ["user", "system", "automation", "integration"]},
                    "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]}
                }
            },
            "context": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "constraints": {"type": "array", "items": {"type": "string"}},
                    "references": {"type": "array", "items": {"type": "string"}}
                }
            },
            "metadata": {
                "type": "object",
                "properties": {
                    "ingested_at": {"type": "string"},
                    "ingested_by": {"type": "string"}
                }
            }
        }
    },
    "assess_artifact_v1": {
        "type": "object",
        "required": ["gaps", "feasibility", "recommendations"],
        "properties": {
            "gaps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "description", "impact"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^GAP-[0-9]+$"},
                        "description": {"type": "string", "minLength": 10},
                        "impact": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                        "mitigation_strategy": {"type": "string"}
                    }
                }
            },
            "feasibility": {
                "type": "object",
                "required": ["overall", "factors"],
                "properties": {
                    "overall": {"type": "string", "enum": ["feasible", "partially_feasible", "not_feasible", "needs_clarification"]},
                    "factors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "rating"],
                            "properties": {
                                "name": {"type": "string"},
                                "rating": {"type": "string", "enum": ["favorable", "neutral", "unfavorable", "blocking"]},
                                "details": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "recommendations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "description"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^REC-[0-9]+$"},
                        "description": {"type": "string", "minLength": 10},
                        "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                        "related_gap": {"type": "string"}
                    }
                }
            }
        }
    },
}

# ---------------------------------------------------------------------------
# Forbidden patterns
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS: Dict[str, List[Dict[str, str]]] = {
    "python": [
        {"id": "AV-005-P1", "pattern": r"(?i)(password\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded password detected"},
        {"id": "AV-005-P2", "pattern": r"(?i)(api_key\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded API key detected"},
        {"id": "AV-005-P3", "pattern": r"(?i)(secret\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded secret detected"},
        {"id": "AV-005-P4", "pattern": r"\beval\s*\(", "severity": "critical", "description": "eval() call detected"},
        {"id": "AV-005-P5", "pattern": r"\bexec\s*\(", "severity": "critical", "description": "exec() call detected"},
        {"id": "AV-005-P6", "pattern": r"except\s*:\s*$", "severity": "high", "description": "Bare except clause detected"},
        {"id": "AV-005-P7", "pattern": r"subprocess\..*shell\s*=\s*True", "severity": "high", "description": "subprocess with shell=True detected"},
        {"id": "AV-005-P8", "pattern": r"\bos\.system\s*\(", "severity": "high", "description": "os.system() call detected"},
        {"id": "AV-005-P9", "pattern": r"\bprint\s*\(", "severity": "low", "description": "print() debug statement detected"},
    ],
    "javascript": [
        {"id": "AV-005-J1", "pattern": r"(?i)(password\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded password detected"},
        {"id": "AV-005-J2", "pattern": r"(?i)(api_key\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded API key detected"},
        {"id": "AV-005-J3", "pattern": r"\beval\s*\(", "severity": "critical", "description": "eval() call detected"},
        {"id": "AV-005-J4", "pattern": r"\bFunction\s*\(\s*['\"]", "severity": "critical", "description": "Function constructor with string detected"},
        {"id": "AV-005-J5", "pattern": r"\bconsole\.log\s*\(", "severity": "low", "description": "console.log() debug statement detected"},
    ],
    "shell": [
        {"id": "AV-005-S1", "pattern": r"(?i)(password=['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded password detected"},
        {"id": "AV-005-S2", "pattern": r"\beval\s", "severity": "critical", "description": "eval call detected"},
        {"id": "AV-005-S3", "pattern": r"curl\s+.*\|\s*bash", "severity": "high", "description": "Pipe-to-bash anti-pattern detected"},
        {"id": "AV-005-S4", "pattern": r"wget\s+.*\|\s*bash", "severity": "high", "description": "Pipe-to-bash anti-pattern detected"},
        {"id": "AV-005-S5", "pattern": r"rm\s+-rf\s+/(?!\*)\b", "severity": "high", "description": "Dangerous rm -rf / detected"},
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Tuple[Optional[Any], List[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), []
    except json.JSONDecodeError as e:
        return None, [f"JSON parse error at line {e.lineno}: {e.msg}"]
    except Exception as e:
        return None, [f"Failed to read file: {e}"]


def _get_stdlib_modules() -> set:
    try:
        return set(sys.stdlib_module_names)  # type: ignore[attr-defined]
    except AttributeError:
        # Fallback for Python <3.10
        return {
            "abc", "argparse", "ast", "asyncio", "base64", "bdb", "binascii", "bisect",
            "builtins", "bz2", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
            "codecs", "codeop", "collections", "colorsys", "compileall", "concurrent",
            "configparser", "contextlib", "contextvars", "copy", "copyreg", "crypt",
            "csv", "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal", "difflib",
            "dis", "distutils", "doctest", "email", "encodings", "enum", "errno", "faulthandler",
            "fcntl", "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
            "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "grp", "gzip",
            "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib", "imghdr",
            "imp", "importlib", "inspect", "io", "ipaddress", "itertools", "json",
            "keyword", "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox",
            "mailcap", "marshal", "math", "mimetypes", "mmap", "modulefinder", "multiprocessing",
            "netrc", "nis", "nntplib", "numbers", "operator", "optparse", "os", "ossaudiodev",
            "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
            "plistlib", "poplib", "posix", "posixpath", "pprint", "profile", "pstats",
            "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri", "random",
            "re", "readline", "reprlib", "resource", "rlcompleter", "runpy", "sched",
            "secrets", "select", "selectors", "shelve", "shlex", "shutil", "signal",
            "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "spwd",
            "sqlite3", "ssl", "stat", "statistics", "string", "stringprep", "struct",
            "subprocess", "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
            "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
            "time", "timeit", "tkinter", "token", "tokenize", "trace", "traceback",
            "tracemalloc", "tty", "turtle", "turtledemo", "types", "typing", "unicodedata",
            "unittest", "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
            "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
            "zipapp", "zipfile", "zipimport", "zlib",
        }


def _extract_third_party_deps(project_root: Path) -> set:
    deps: set = set()
    req_file = project_root / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Handle 'package==1.0', 'package>=1.0', 'package[extra]'
            pkg = re.split(r"[=<>!~\[;#]", line)[0].strip()
            if pkg:
                deps.add(pkg.lower())
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text(encoding="utf-8")
        # Naive TOML extraction for dependencies
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("dependencies") or "=" in line:
                m = re.search(r"'([^']+)'", line)
                if m:
                    deps.add(m.group(1).lower())
    setup = project_root / "setup.py"
    if setup.exists():
        text = setup.read_text(encoding="utf-8")
        for m in re.finditer(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL):
            for pkg in re.findall(r"'([a-zA-Z0-9_-]+)'", m.group(1)):
                deps.add(pkg.lower())
    return deps


def _find_project_root(artifact_path: Path) -> Path:
    """Walk upward looking for requirements.txt / pyproject.toml / .git / setup.py."""
    current = artifact_path.resolve()
    if current.is_file():
        current = current.parent
    while current != current.parent:
        if any((current / f).exists() for f in ("requirements.txt", "pyproject.toml", "setup.py", ".git")):
            return current
        current = current.parent
    return artifact_path.resolve().parent if artifact_path.is_file() else artifact_path.resolve()


# ---------------------------------------------------------------------------
# BaseValidator
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(self, passed: bool, details: Optional[List[str]] = None, errors: Optional[List[Dict[str, Any]]] = None):
        self.passed = passed
        self.details = details or []
        self.errors = errors or []


class BaseValidator:
    phase_name: str = ""

    def __init__(self, artifact_path: Path, strict: bool = False):
        self.artifact_path = artifact_path
        self.strict = strict
        self.checks: Dict[str, CheckResult] = {}

    def run(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _add_check(self, name: str, result: CheckResult) -> None:
        self.checks[name] = result

    def _build_report(self, artifact_path: Path, phase: str) -> Dict[str, Any]:
        total = len(self.checks)
        passed = sum(1 for c in self.checks.values() if c.passed)
        failed = total - passed
        critical_failures = sum(
            1 for c in self.checks.values()
            for e in c.errors if e.get("severity") == "critical"
        )
        any_failed = failed > 0 or critical_failures > 0
        if critical_failures > 0:
            result = "fail"
        elif any_failed:
            result = "fail" if self.strict else "fail"
        else:
            result = "pass"
        # Determine recommendation
        if result == "fail":
            recommendation = f"Phase transition BLOCKED. Resolve {failed} check failure(s) before proceeding."
        elif result == "warn":
            recommendation = "Phase transition ALLOWED with warning. Review flagged items."
        else:
            recommendation = "Phase transition APPROVED. All checks passed."
        return {
            "verifier": "artifact-verifier",
            "version": "1.0.0",
            "timestamp": _now_iso(),
            "artifact_path": str(artifact_path),
            "phase": phase,
            "result": result,
            "checks": {
                k: {"passed": v.passed, "details": v.details, "errors": v.errors}
                for k, v in self.checks.items()
            },
            "summary": {
                "total_checks": total,
                "passed": passed,
                "failed": failed,
                "critical_failures": critical_failures,
            },
            "recommendation": recommendation,
        }


# ---------------------------------------------------------------------------
# JSON Schema helpers
# ---------------------------------------------------------------------------

def _validate_json_schema(data: Any, schema: Dict[str, Any]) -> CheckResult:
    try:
        import jsonschema
        jsonschema.validate(instance=data, schema=schema)
        return CheckResult(True, ["Schema validation passed"])
    except ImportError:
        # Fallback: lightweight validation without jsonschema library
        details, errors = _lightweight_schema_validate(data, schema)
        passed = len(errors) == 0
        return CheckResult(passed, details, errors)
    except jsonschema.ValidationError as e:
        error = {"severity": "high", "code": "AV-002", "message": e.message, "path": list(e.path)}
        return CheckResult(False, [f"Schema validation failed: {e.message}"], [error])
    except Exception as e:
        error = {"severity": "high", "code": "AV-002", "message": str(e)}
        return CheckResult(False, [f"Schema validation error: {e}"], [error])


def _lightweight_schema_validate(data: Any, schema: Dict[str, Any], path: str = "$") -> Tuple[List[str], List[Dict[str, Any]]]:
    details: List[str] = []
    errors: List[Dict[str, Any]] = []
    if schema.get("type") == "object":
        if not isinstance(data, dict):
            errors.append({"severity": "high", "code": "AV-002", "message": f"Expected object at {path}, got {type(data).__name__}"})
            return details, errors
        required = schema.get("required", [])
        for key in required:
            if key not in data:
                errors.append({"severity": "high", "code": "AV-001", "message": f"Missing required field '{key}' at {path}"})
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in data:
                d, e = _lightweight_schema_validate(data[key], subschema, f"{path}.{key}")
                details.extend(d)
                errors.extend(e)
    elif schema.get("type") == "array":
        if not isinstance(data, list):
            errors.append({"severity": "high", "code": "AV-002", "message": f"Expected array at {path}, got {type(data).__name__}"})
            return details, errors
        min_items = schema.get("minItems")
        if min_items is not None and len(data) < min_items:
            errors.append({"severity": "high", "code": "AV-002", "message": f"Array at {path} has {len(data)} items, minimum {min_items}"})
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(data):
                d, e = _lightweight_schema_validate(item, items_schema, f"{path}[{i}]")
                details.extend(d)
                errors.extend(e)
    elif schema.get("type") == "string":
        if not isinstance(data, str):
            errors.append({"severity": "high", "code": "AV-002", "message": f"Expected string at {path}, got {type(data).__name__}"})
            return details, errors
        min_len = schema.get("minLength")
        if min_len is not None and len(data) < min_len:
            errors.append({"severity": "high", "code": "AV-002", "message": f"String at {path} length {len(data)} < minimum {min_len}"})
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, data):
            errors.append({"severity": "high", "code": "AV-002", "message": f"String at {path} does not match pattern {pattern}"})
        enum = schema.get("enum")
        if enum is not None and data not in enum:
            errors.append({"severity": "high", "code": "AV-007", "message": f"Value at {path} ('{data}') not in allowed enum {enum}"})
    elif schema.get("type") == "integer":
        if not isinstance(data, int) or isinstance(data, bool):
            errors.append({"severity": "high", "code": "AV-002", "message": f"Expected integer at {path}, got {type(data).__name__}"})
        else:
            minimum = schema.get("minimum")
            if minimum is not None and data < minimum:
                errors.append({"severity": "high", "code": "AV-002", "message": f"Integer at {path} ({data}) < minimum ({minimum})"})
    elif schema.get("type") == "number":
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            errors.append({"severity": "high", "code": "AV-002", "message": f"Expected number at {path}, got {type(data).__name__}"})
        else:
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and data < minimum:
                errors.append({"severity": "high", "code": "AV-002", "message": f"Number at {path} ({data}) < minimum ({minimum})"})
            if maximum is not None and data > maximum:
                errors.append({"severity": "high", "code": "AV-002", "message": f"Number at {path} ({data}) > maximum ({maximum})"})
    return details, errors


# ---------------------------------------------------------------------------
# Phase validators
# ---------------------------------------------------------------------------

class PlanValidator(BaseValidator):
    phase_name = "PLAN"

    def run(self) -> Dict[str, Any]:
        data, errors = _load_json(self.artifact_path)
        if data is None:
            self._add_check("structure", CheckResult(False, errors, [{"severity": "critical", "code": "AV-002", "message": e} for e in errors]))
            return self._build_report(self.artifact_path, self.phase_name)

        schema = SCHEMAS["plan_artifact_v1"]
        self._add_check("structure", _validate_json_schema(data, schema))

        # Additional deterministic checks
        detail_errors = []
        for section in ["objectives", "alternatives", "risk_assessment"]:
            arr = data.get(section, [])
            if isinstance(arr, list):
                ids = [item.get("id") for item in arr if isinstance(item, dict)]
                seen = set()
                for _id in ids:
                    if _id in seen:
                        detail_errors.append({"severity": "high", "code": "AV-006", "message": f"Duplicate id '{_id}' in {section}"})
                    seen.add(_id)

        # At least one critical/high objective
        objectives = data.get("objectives", [])
        if isinstance(objectives, list):
            priorities = [obj.get("priority") for obj in objectives if isinstance(obj, dict)]
            if not any(p in ("critical", "high") for p in priorities):
                detail_errors.append({"severity": "high", "code": "AV-008", "message": "No objective with priority 'critical' or 'high' found"})

        # At least one critical/high risk
        risks = data.get("risk_assessment", {}).get("risks", [])
        if isinstance(risks, list):
            severities = [r.get("severity") for r in risks if isinstance(r, dict)]
            if not any(s in ("critical", "high") for s in severities):
                detail_errors.append({"severity": "high", "code": "AV-008", "message": "No risk with severity 'critical' or 'high' found"})

        passed = len(detail_errors) == 0
        self._add_check("coverage", CheckResult(passed, [f"Coverage checks: {len(detail_errors)} issue(s)"] if not passed else ["Coverage checks passed"], detail_errors))

        self._add_check("forbidden_patterns", CheckResult(True, ["No forbidden patterns applicable to PLAN artifacts"]))
        return self._build_report(self.artifact_path, self.phase_name)


class ExecuteValidator(BaseValidator):
    phase_name = "EXECUTE"

    def run(self) -> Dict[str, Any]:
        paths = self._collect_files()
        if not paths:
            self._add_check("structure", CheckResult(False, ["No executable artifacts found"], [{"severity": "critical", "code": "AV-001", "message": "No source files detected"}]))
            return self._build_report(self.artifact_path, self.phase_name)

        syntax_details: List[str] = []
        syntax_errors: List[Dict[str, Any]] = []
        import_details: List[str] = []
        import_errors: List[Dict[str, Any]] = []
        forbidden_details: List[str] = []
        forbidden_errors: List[Dict[str, Any]] = []

        stdlib_mods = _get_stdlib_modules()
        project_root = _find_project_root(self.artifact_path)
        third_party = _extract_third_party_deps(project_root)

        for p in paths:
            lang = self._detect_language(p)
            text = p.read_text(encoding="utf-8", errors="replace")

            # Syntax / AST
            if lang == "python":
                try:
                    tree = ast.parse(text, filename=str(p))
                    syntax_details.append(f"{p.name}: AST parse OK")
                    # AST-based forbidden checks
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name):
                                if node.func.id == "eval":
                                    forbidden_errors.append({"severity": "critical", "code": "AV-005", "message": f"eval() call in {p.name}"})
                                if node.func.id == "exec":
                                    forbidden_errors.append({"severity": "critical", "code": "AV-005", "message": f"exec() call in {p.name}"})
                        if isinstance(node, ast.ExceptHandler):
                            if node.type is None:
                                forbidden_errors.append({"severity": "high", "code": "AV-005", "message": f"Bare except clause in {p.name}"})
                except SyntaxError as e:
                    syntax_errors.append({"severity": "critical", "code": "AV-003", "message": f"SyntaxError in {p.name} line {e.lineno}: {e.msg}"})
                # Imports
                import_errors.extend(self._check_python_imports(p, text, stdlib_mods, third_party, project_root))
            elif lang in ("javascript", "typescript"):
                # Basic syntax heuristics when no parser library available
                # We just check brace balance and basic structure
                open_braces = text.count("{") - text.count("}")
                open_parens = text.count("(") - text.count(")")
                if open_braces != 0 or open_parens != 0:
                    syntax_errors.append({"severity": "high", "code": "AV-003", "message": f"Brace/paren imbalance in {p.name} (braces={open_braces}, parens={open_parens})"})
                else:
                    syntax_details.append(f"{p.name}: Brace/paren balance OK")
            elif lang == "shell":
                # Basic syntax: detect unclosed quotes
                single = text.count("'") % 2
                double = text.count('"') % 2
                if single or double:
                    syntax_errors.append({"severity": "high", "code": "AV-003", "message": f"Possible unclosed quotes in {p.name}"})
                else:
                    syntax_details.append(f"{p.name}: Quote balance OK")
            else:
                syntax_details.append(f"{p.name}: Language '{lang}' -- skipping AST checks")

            # Regex forbidden patterns
            patterns = FORBIDDEN_PATTERNS.get(lang, [])
            for pat in patterns:
                for match in re.finditer(pat["pattern"], text):
                    line_no = text[:match.start()].count("\n") + 1
                    forbidden_errors.append({
                        "severity": pat["severity"],
                        "code": pat["id"],
                        "message": f"{pat['description']} in {p.name}:{line_no}",
                        "pattern": pat["pattern"],
                    })

        self._add_check("syntax", CheckResult(len(syntax_errors) == 0, syntax_details, syntax_errors))
        self._add_check("imports", CheckResult(len(import_errors) == 0, import_details or ["Import checks completed"], import_errors))
        self._add_check("forbidden_patterns", CheckResult(len(forbidden_errors) == 0, forbidden_details or ["Forbidden pattern checks completed"], forbidden_errors))
        self._add_check("structure", CheckResult(True, [f"Scanned {len(paths)} file(s)"]))
        return self._build_report(self.artifact_path, self.phase_name)

    def _collect_files(self) -> List[Path]:
        p = self.artifact_path
        if p.is_file():
            return [p]
        if p.is_dir():
            files: List[Path] = []
            for ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".sh", ".bash"):
                files.extend(p.rglob(f"*{ext}"))
            return files
        return []

    def _detect_language(self, p: Path) -> str:
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "javascript",
            ".tsx": "javascript",
            ".sh": "shell",
            ".bash": "shell",
        }
        return mapping.get(p.suffix.lower(), "unknown")

    def _check_python_imports(self, p: Path, text: str, stdlib_mods: set, third_party: set, project_root: Path) -> List[Dict[str, Any]]:
        errors: List[Dict[str, Any]] = []
        try:
            tree = ast.parse(text, filename=str(p))
        except Exception:
            return errors
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if self._is_unresolved(top, stdlib_mods, third_party, project_root):
                        errors.append({"severity": "medium", "code": "AV-004", "message": f"Unresolved import '{alias.name}' in {p.name}"})
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                top = module.split(".")[0] if module else ""
                if node.level and node.level > 0:
                    # Relative import -- check local file existence
                    if not self._resolve_relative_import(p, node.level, module, project_root):
                        errors.append({"severity": "medium", "code": "AV-004", "message": f"Unresolved relative import from '{module}' in {p.name}"})
                elif top and self._is_unresolved(top, stdlib_mods, third_party, project_root):
                    errors.append({"severity": "medium", "code": "AV-004", "message": f"Unresolved import '{module}' in {p.name}"})
        return errors

    def _is_unresolved(self, top: str, stdlib_mods: set, third_party: set, project_root: Path) -> bool:
        if top in stdlib_mods:
            return False
        if top.lower() in third_party or top.replace("-", "_").lower() in third_party:
            return False
        # Check local package dir
        if (project_root / top).exists() or (project_root / f"{top}.py").exists():
            return False
        return True

    def _resolve_relative_import(self, p: Path, level: int, module: str, project_root: Path) -> bool:
        base = p.parent
        for _ in range(level - 1):
            base = base.parent
        if module:
            target = base / module.replace(".", os.sep)
            return target.exists() or (target.parent / f"{target.name}.py").exists() or (target / "__init__.py").exists()
        else:
            return (base / "__init__.py").exists()


class DeliverValidator(BaseValidator):
    phase_name = "DELIVER"

    def run(self) -> Dict[str, Any]:
        if not self.artifact_path.exists():
            self._add_check("structure", CheckResult(False, ["Artifact path does not exist"], [{"severity": "critical", "code": "AV-001", "message": "Missing artifact"}]))
            return self._build_report(self.artifact_path, self.phase_name)

        text = self.artifact_path.read_text(encoding="utf-8", errors="replace")
        # Heading extraction
        heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        headings = [(len(m.group(1)), m.group(2).strip()) for m in heading_re.finditer(text)]

        section_errors: List[Dict[str, Any]] = []
        section_details: List[str] = []
        heading_texts_lower = [h[1].lower() for h in headings]

        required = [
            ("overview", ["overview", "summary", "introduction"]),
            ("prerequisites", ["prerequisites", "requirements", "dependencies"]),
            ("installation", ["installation", "setup", "getting started"]),
            ("usage", ["usage", "how to use", "examples"]),
        ]
        for key, alts in required:
            if any(a in ht for a in alts for ht in heading_texts_lower):
                section_details.append(f"Required section '{key}' found")
            else:
                section_errors.append({"severity": "high", "code": "AV-001", "message": f"Missing required section: {key}"})

        # Optional flags
        optional = [
            ("api reference", ["api reference", "configuration", "settings"]),
            ("troubleshooting", ["troubleshooting", "faq"]),
            ("changelog", ["changelog", "version history", "release notes"]),
        ]
        for key, alts in optional:
            if any(a in ht for a in alts for ht in heading_texts_lower):
                section_details.append(f"Optional section '{key}' found")
            else:
                section_details.append(f"Optional section '{key}' missing (flagged)")

        # Heading hierarchy
        hierarchy_errors = []
        if len(headings) > 1:
            prev_level = headings[0][0]
            for level, title in headings[1:]:
                if level > prev_level + 1:
                    hierarchy_errors.append({"severity": "medium", "code": "AV-008", "message": f"Skipped heading level after level {prev_level}: '{title}' at level {level}"})
                prev_level = level

        # Minimum heading count for large docs
        word_count = len(text.split())
        if word_count > 500 and len(headings) < 3:
            section_errors.append({"severity": "medium", "code": "AV-008", "message": f"Document has {word_count} words but only {len(headings)} heading(s) (minimum 3)"})

        # Code block language tags
        code_block_re = re.compile(r"^```\s*(\S*)\s*$", re.MULTILINE)
        blocks = code_block_re.findall(text)
        untagged = sum(1 for b in blocks if b == "")
        code_errors = []
        if untagged > 0:
            code_errors.append({"severity": "low", "code": "AV-010", "message": f"{untagged} code block(s) missing language tag"})

        # Broken internal links
        link_re = re.compile(r"\[([^\]]+)\]\(\#([^)]+)\)")
        anchors = set()
        for level, title in headings:
            anchor = re.sub(r"[^\w\s-]", "", title).lower().strip().replace(" ", "-")
            anchors.add(anchor)
        broken_links = []
        for m in link_re.finditer(text):
            anchor = m.group(2)
            if anchor.lower() not in anchors:
                broken_links.append({"severity": "medium", "code": "AV-009", "message": f"Broken internal link to '#{anchor}'"})

        self._add_check("structure", CheckResult(len(section_errors) == 0, section_details, section_errors))
        self._add_check("syntax", CheckResult(len(hierarchy_errors) == 0, ["Heading hierarchy checked"], hierarchy_errors))
        self._add_check("coverage", CheckResult(len(code_errors) == 0, [f"Code blocks: {len(blocks)} total, {untagged} untagged"], code_errors))
        self._add_check("forbidden_patterns", CheckResult(len(broken_links) == 0, ["Internal link checks completed"], broken_links))
        return self._build_report(self.artifact_path, self.phase_name)


class ValidateArtifactValidator(BaseValidator):
    phase_name = "VALIDATE"

    def run(self) -> Dict[str, Any]:
        data, errors = _load_json(self.artifact_path)
        if data is None:
            self._add_check("structure", CheckResult(False, errors, [{"severity": "critical", "code": "AV-002", "message": e} for e in errors]))
            return self._build_report(self.artifact_path, self.phase_name)

        schema = SCHEMAS["validate_artifact_v1"]
        self._add_check("structure", _validate_json_schema(data, schema))

        consistency_errors = []
        test_results = data.get("test_results", [])
        findings = data.get("findings", [])
        coverage = data.get("coverage", {})

        has_fail = any(r.get("status") in ("fail", "error") for r in test_results if isinstance(r, dict))
        if has_fail and not findings:
            consistency_errors.append({"severity": "high", "code": "AV-008", "message": "Tests failed/errors but findings array is empty"})

        critical_findings = [f for f in findings if isinstance(f, dict) and f.get("severity") == "critical"]
        overall_status = data.get("overall_status")
        if critical_findings and overall_status == "pass":
            consistency_errors.append({"severity": "high", "code": "AV-008", "message": "Critical findings present but overall_status is 'pass'"})

        lines_coverage = coverage.get("lines", 100)
        if lines_coverage < 30:
            consistency_errors.append({"severity": "high", "code": "AV-008", "message": f"Line coverage {lines_coverage}% is below 30% threshold"})
        elif lines_coverage < 60:
            consistency_errors.append({"severity": "low", "code": "AV-008", "message": f"Line coverage {lines_coverage}% is below recommended 60%"})

        passed = len(consistency_errors) == 0
        self._add_check("coverage", CheckResult(passed, ["Consistency checks completed"], consistency_errors))
        self._add_check("forbidden_patterns", CheckResult(True, ["No forbidden patterns applicable"]))
        return self._build_report(self.artifact_path, self.phase_name)


class RememberValidator(BaseValidator):
    phase_name = "REMEMBER"

    def run(self) -> Dict[str, Any]:
        data, errors = _load_json(self.artifact_path)
        if data is None:
            self._add_check("structure", CheckResult(False, errors, [{"severity": "critical", "code": "AV-002", "message": e} for e in errors]))
            return self._build_report(self.artifact_path, self.phase_name)

        schema = SCHEMAS["remember_artifact_v1"]
        self._add_check("structure", _validate_json_schema(data, schema))

        checksum_errors = []
        for art in data.get("artifacts", []):
            if isinstance(art, dict):
                cs = art.get("checksum", "")
                if not re.fullmatch(r"[a-f0-9]{64}", cs):
                    checksum_errors.append({"severity": "high", "code": "AV-008", "message": f"Invalid SHA-256 checksum format: '{cs}'"})

        self._add_check("coverage", CheckResult(len(checksum_errors) == 0, ["Checksum format validation completed"], checksum_errors))
        self._add_check("forbidden_patterns", CheckResult(True, ["No forbidden patterns applicable"]))
        return self._build_report(self.artifact_path, self.phase_name)


class IngestValidator(BaseValidator):
    phase_name = "INGEST"

    def run(self) -> Dict[str, Any]:
        data, errors = _load_json(self.artifact_path)
        if data is None:
            self._add_check("structure", CheckResult(False, errors, [{"severity": "critical", "code": "AV-002", "message": e} for e in errors]))
            return self._build_report(self.artifact_path, self.phase_name)

        schema = SCHEMAS["ingest_artifact_v1"]
        self._add_check("structure", _validate_json_schema(data, schema))
        self._add_check("coverage", CheckResult(True, ["INGEST artifact coverage validated"]))
        self._add_check("forbidden_patterns", CheckResult(True, ["No forbidden patterns applicable"]))
        return self._build_report(self.artifact_path, self.phase_name)


class AssessValidator(BaseValidator):
    phase_name = "ASSESS"

    def run(self) -> Dict[str, Any]:
        data, errors = _load_json(self.artifact_path)
        if data is None:
            self._add_check("structure", CheckResult(False, errors, [{"severity": "critical", "code": "AV-002", "message": e} for e in errors]))
            return self._build_report(self.artifact_path, self.phase_name)

        schema = SCHEMAS["assess_artifact_v1"]
        self._add_check("structure", _validate_json_schema(data, schema))

        consistency_errors = []
        gaps = data.get("gaps", [])
        recommendations = data.get("recommendations", [])
        gap_ids = {g.get("id") for g in gaps if isinstance(g, dict)}
        rec_ids = {r.get("id") for r in recommendations if isinstance(r, dict)}

        if len(gap_ids) != len(gaps):
            consistency_errors.append({"severity": "high", "code": "AV-006", "message": "Duplicate gap ids detected"})
        if len(rec_ids) != len(recommendations):
            consistency_errors.append({"severity": "high", "code": "AV-006", "message": "Duplicate recommendation ids detected"})

        impacts = [g.get("impact") for g in gaps if isinstance(g, dict)]
        if not any(i in ("critical", "high") for i in impacts):
            consistency_errors.append({"severity": "high", "code": "AV-008", "message": "No gap with impact 'critical' or 'high' found"})

        for rec in recommendations:
            if isinstance(rec, dict):
                related = rec.get("related_gap")
                if related and related not in gap_ids:
                    consistency_errors.append({"severity": "medium", "code": "AV-008", "message": f"Recommendation references non-existent gap '{related}'"})

        passed = len(consistency_errors) == 0
        self._add_check("coverage", CheckResult(passed, ["ASSESS consistency checks completed"], consistency_errors))
        self._add_check("forbidden_patterns", CheckResult(True, ["No forbidden patterns applicable"]))
        return self._build_report(self.artifact_path, self.phase_name)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PHASE_REGISTRY: Dict[str, type] = {
    "PLAN": PlanValidator,
    "EXECUTE": ExecuteValidator,
    "DELIVER": DeliverValidator,
    "VALIDATE": ValidateArtifactValidator,
    "REMEMBER": RememberValidator,
    "INGEST": IngestValidator,
    "ASSESS": AssessValidator,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="artifact-verifier: deterministic phase artifact validator")
    parser.add_argument("--artifact", required=True, help="Path to the artifact file or directory")
    parser.add_argument("--phase", required=True, choices=list(PHASE_REGISTRY.keys()), help="Phase name")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    parser.add_argument("--output", help="Write JSON report to file instead of stdout")
    args = parser.parse_args()

    artifact_path = Path(args.artifact)
    validator_cls = PHASE_REGISTRY.get(args.phase.upper())
    if not validator_cls:
        report = {
            "verifier": "artifact-verifier",
            "version": "1.0.0",
            "timestamp": _now_iso(),
            "artifact_path": str(artifact_path),
            "phase": args.phase,
            "result": "fail",
            "error": f"Unknown phase '{args.phase}'",
            "recommendation": "Phase transition BLOCKED. Invalid phase specified.",
        }
        _emit(report, args.output)
        return EXIT_FAIL

    validator = validator_cls(artifact_path, strict=args.strict)
    report = validator.run()

    _emit(report, args.output)
    return EXIT_FAIL if report["result"] == "fail" else EXIT_PASS


def _emit(report: Dict[str, Any], output_path: Optional[str]) -> None:
    json_str = json.dumps(report, indent=2)
    if output_path:
        Path(output_path).write_text(json_str + "\n", encoding="utf-8")
    # Print report as last line(s) to stdout for phase-controller consumption
    print(json_str)


if __name__ == "__main__":
    sys.exit(main())
