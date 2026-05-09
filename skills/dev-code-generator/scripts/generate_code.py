#!/usr/bin/env python3
"""
generate_code.py — Codebase context analyzer and scaffold generator.

Analyzes a project directory to detect language, framework, and coding style,
then generates production-quality scaffold code from built-in templates.

Usage:
    python generate_code.py --dir ./my-project --template fastapi_crud --entity User --output stdout
    python generate_code.py --dir ./my-project --template jwt_middleware --language python --output file
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────
# Detection Maps
# ──────────────────────────────────────────────────────────────

LANGUAGE_EXTENSIONS = {
    "python": {".py"},
    "javascript": {".js", ".mjs", ".cjs"},
    "typescript": {".ts", ".tsx", ".mts", ".cts"},
    "go": {".go"},
    "rust": {".rs"},
    "java": {".java"},
    "csharp": {".cs"},
    "ruby": {".rb"},
}

FRAMEWORK_MARKERS = {
    "python": {
        "fastapi": ["fastapi", "starlette"],
        "django": ["django", "djangorestframework"],
        "flask": ["flask"],
    },
    "javascript": {
        "express": ["express"],
        "nextjs": ["next"],
        "react": ["react"],
    },
    "typescript": {
        "nestjs": ["@nestjs/core"],
        "express": ["express"],
        "nextjs": ["next"],
        "react": ["react"],
    },
    "go": {
        "gin": ["gin-gonic/gin"],
        "echo": ["labstack/echo"],
        "fiber": ["gofiber/fiber"],
    },
    "rust": {
        "axum": ["axum"],
        "actix": ["actix-web"],
        "rocket": ["rocket"],
    },
    "java": {
        "spring": ["org.springframework"],
    },
    "csharp": {
        "aspnet": ["Microsoft.AspNetCore"],
    },
    "ruby": {
        "rails": ["rails"],
        "sinatra": ["sinatra"],
    },
}

PACKAGE_FILES = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
    "javascript": ["package.json"],
    "typescript": ["package.json", "tsconfig.json"],
    "go": ["go.mod"],
    "rust": ["Cargo.toml"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "csharp": [".csproj", ".sln"],
    "ruby": ["Gemfile"],
}


# ──────────────────────────────────────────────────────────────
# Data Classes
# ──────────────────────────────────────────────────────────────

@dataclass
class ProjectContext:
    language: str | None = None
    framework: str | None = None
    package_manager: str | None = None
    style: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "framework": self.framework,
            "package_manager": self.package_manager,
            "style": self.style,
        }


@dataclass
class CodeTemplate:
    name: str
    language: str
    framework: str | None
    generate: Any  # callable accepting (ctx, params) -> dict[str, str]


# ──────────────────────────────────────────────────────────────
# Detection Functions
# ──────────────────────────────────────────────────────────────

def detect_language(directory: Path) -> str | None:
    """Detect dominant language by file extension counts."""
    counts: dict[str, int] = {lang: 0 for lang in LANGUAGE_EXTENSIONS}
    for root, _dirs, files in os.walk(directory):
        # Ignore common dependency / build dirs
        if any(part.startswith(("node_modules", ".git", "vendor", "target", "__pycache__", ".venv", "build", "dist")) for part in Path(root).parts):
            continue
        for f in files:
            ext = Path(f).suffix.lower()
            for lang, exts in LANGUAGE_EXTENSIONS.items():
                if ext in exts:
                    counts[lang] += 1
    if not any(counts.values()):
        return None
    return max(counts, key=counts.get)


def detect_framework(directory: Path, language: str | None) -> str | None:
    """Detect framework from package files and source imports."""
    if language is None:
        return None

    markers = FRAMEWORK_MARKERS.get(language, {})
    if not markers:
        return None

    # 1. Check package files
    package_files = PACKAGE_FILES.get(language, [])
    for pf in package_files:
        for path in directory.rglob(pf):
            content = path.read_text(encoding="utf-8", errors="ignore").lower()
            for fw, keywords in markers.items():
                if any(kw.lower() in content for kw in keywords):
                    return fw

    # 2. Check imports in up to 20 source files
    exts = LANGUAGE_EXTENSIONS.get(language, set())
    checked = 0
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in exts:
            if any(part.startswith(("node_modules", ".git", "vendor", "target", "__pycache__")) for part in path.parts):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore").lower()
                for fw, keywords in markers.items():
                    if any(kw.lower() in content for kw in keywords):
                        return fw
            except Exception:
                pass
            checked += 1
            if checked >= 20:
                break
    return None


def detect_package_manager(directory: Path, language: str | None) -> str | None:
    """Detect package / dependency manager from lock / manifest files."""
    if language is None:
        return None
    mapping = {
        "python": [("poetry.lock", "poetry"), ("Pipfile.lock", "pipenv"), ("requirements.txt", "pip"), ("setup.py", "setuptools"), ("pyproject.toml", "poetry/hatch")],
        "javascript": [("package-lock.json", "npm"), ("yarn.lock", "yarn"), ("pnpm-lock.yaml", "pnpm")],
        "typescript": [("package-lock.json", "npm"), ("yarn.lock", "yarn"), ("pnpm-lock.yaml", "pnpm")],
        "go": [("go.mod", "go mod")],
        "rust": [("Cargo.lock", "cargo")],
        "java": [("pom.xml", "maven"), ("build.gradle", "gradle")],
        "csharp": [(".csproj", "nuget/dotnet")],
        "ruby": [("Gemfile.lock", "bundler")],
    }
    for filename, manager in mapping.get(language, []):
        if any(directory.rglob(filename)):
            return manager
    return None


def infer_style(directory: Path, language: str | None) -> dict[str, Any]:
    """Read a few existing files to infer naming conventions and quote style."""
    style: dict[str, Any] = {
        "naming_functions": "unknown",
        "naming_classes": "unknown",
        "naming_variables": "unknown",
        "quote_preference": "unknown",
        "import_style": "unknown",
        "indent": "unknown",
        "async_preference": "unknown",
    }
    if language is None:
        return style

    exts = LANGUAGE_EXTENSIONS.get(language, set())
    samples: list[str] = []
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in exts and not any(part.startswith(("node_modules", ".git", "vendor", "target", "__pycache__", ".venv")) for part in path.parts):
            try:
                samples.append(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
            if len(samples) >= 5:
                break

    if not samples:
        return style

    combined = "\n".join(samples)

    # Indent detection
    spaces = len(re.findall(r"\n( +)[^ ]", combined))
    tabs = len(re.findall(r"\n\t", combined))
    style["indent"] = "spaces(4)" if spaces > tabs else "tabs" if tabs > 0 else "spaces(4)"

    # Quote preference
    single = combined.count("'")
    double = combined.count('"')
    style["quote_preference"] = "single" if single > double * 1.2 else "double" if double > single * 1.2 else "mixed"

    # Naming conventions
    snake_funcs = len(re.findall(r"\ndef [a-z_][a-z0-9_]*\(", combined)) + len(re.findall(r"\bfunction [a-z_][a-z0-9_]*\(", combined))
    camel_funcs = len(re.findall(r"\bfunction [a-z][a-zA-Z0-9]*\(", combined)) + len(re.findall(r"\bfunc [a-z][a-zA-Z0-9]*\(", combined))
    pascal_classes = len(re.findall(r"\bclass [A-Z][a-zA-Z0-9]*", combined)) + len(re.findall(r"\btype [A-Z][a-zA-Z0-9]* struct", combined))

    style["naming_functions"] = "snake_case" if snake_funcs > camel_funcs else "camelCase" if camel_funcs > 0 else "unknown"
    style["naming_classes"] = "PascalCase" if pascal_classes > 0 else "unknown"
    style["naming_variables"] = "snake_case" if snake_funcs > camel_funcs else "camelCase" if camel_funcs > 0 else "unknown"

    # Async preference
    async_count = combined.count("async def") + combined.count("async function") + combined.count("async fn")
    sync_count = len(re.findall(r"\bdef [a-z_][a-z0-9_]*\(", combined)) + len(re.findall(r"\bfunction [a-z_][a-z0-9_]*\(", combined))
    style["async_preference"] = "async" if async_count > 0 and async_count >= sync_count * 0.3 else "sync"

    # Import style (Python / JS specific)
    if language == "python":
        style["import_style"] = "from x import y" if "from " in combined else "import x"
    elif language in ("javascript", "typescript"):
        style["import_style"] = "ESM import/export" if "import {" in combined or "export const" in combined else "CommonJS require"
    elif language == "go":
        style["import_style"] = "import blocks"
    elif language == "rust":
        style["import_style"] = "use crate:: / std::"
    else:
        style["import_style"] = "standard"

    return style


def analyze_project(directory: Path) -> ProjectContext:
    """Full project context detection pipeline."""
    lang = detect_language(directory)
    fw = detect_framework(directory, lang)
    pm = detect_package_manager(directory, lang)
    style = infer_style(directory, lang)
    return ProjectContext(language=lang, framework=fw, package_manager=pm, style=style)


# ──────────────────────────────────────────────────────────────
# Template Generators
# ──────────────────────────────────────────────────────────────

def _indent(level: int, size: int = 4) -> str:
    return " " * (level * size)


def _pascal(name: str) -> str:
    return "".join(word.capitalize() for word in name.split("_"))


def _snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# ── FastAPI CRUD ────────────────────────────────────────────
def _gen_fastapi_crud(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    entity = params.get("entity", "Item")
    entity_snake = _snake(entity)
    entity_plural = params.get("plural", f"{entity_snake}s")
    fields = params.get("fields", [{"name": "name", "type": "str", "required": True}])
    base_route = params.get("base_route", f"/api/v1/{entity_plural}")

    field_defs = "\n".join(
        f"    {f['name']}: {f.get('type', 'str')}{' | None' if not f.get('required', True) else ''}"
        for f in fields
    )
    schema_fields = "\n".join(
        f"    {f['name']}: {f.get('type', 'str')} = Field(..., description=\"{f['name']}\")"
        if f.get("required", True)
        else f"    {f['name']}: {f.get('type', 'str')} | None = Field(None, description=\"{f['name']}\")"
        for f in fields
    )

    files = {}
    files[f"schemas/{entity_snake}.py"] = f"""from pydantic import BaseModel, Field


class {entity}Base(BaseModel):
{schema_fields}


class {entity}Create({entity}Base):
    pass


class {entity}Update({entity}Base):
    pass


class {entity}InDB({entity}Base):
    id: int

    class Config:
        from_attributes = True
"""

    files[f"services/{entity_snake}_service.py"] = f"""from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..models import {entity}
from ..schemas.{entity_snake} import {entity}Create, {entity}Update, {entity}InDB


class {entity}Service:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> List[{entity}InDB]:
        result = await self.db.execute(select({entity}))
        return [{entity}InDB.model_validate(u) for u in result.scalars().all()]

    async def get_by_id(self, {entity_snake}_id: int) -> {entity}InDB | None:
        result = await self.db.execute(select({entity}).where({entity}.id == {entity_snake}_id))
        obj = result.scalar_one_or_none()
        return {entity}InDB.model_validate(obj) if obj else None

    async def create(self, data: {entity}Create) -> {entity}InDB:
        obj = {entity}(**data.model_dump())
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return {entity}InDB.model_validate(obj)

    async def update(self, {entity_snake}_id: int, data: {entity}Update) -> {entity}InDB | None:
        obj = await self.get_by_id({entity_snake}_id)
        if not obj:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await self.db.commit()
        await self.db.refresh(obj)
        return {entity}InDB.model_validate(obj)

    async def delete(self, {entity_snake}_id: int) -> bool:
        obj = await self.get_by_id({entity_snake}_id)
        if not obj:
            return False
        await self.db.delete(obj)
        await self.db.commit()
        return True
"""

    files[f"routes/{entity_plural}_router.py"] = f"""from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..dependencies import get_db
from ..schemas.{entity_snake} import {entity}Create, {entity}Update, {entity}InDB
from ..services.{entity_snake}_service import {entity}Service

router = APIRouter(prefix="{base_route}", tags=["{entity_plural}"])


@router.get("/", response_model=List[{entity}InDB])
async def list_{entity_plural}(db: AsyncSession = Depends(get_db)):
    service = {entity}Service(db)
    return await service.get_all()


@router.get("/{{{entity_snake}_id}}", response_model={entity}InDB)
async def get_{entity_snake}({entity_snake}_id: int, db: AsyncSession = Depends(get_db)):
    service = {entity}Service(db)
    obj = await service.get_by_id({entity_snake}_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{entity} not found")
    return obj


@router.post("/", response_model={entity}InDB, status_code=status.HTTP_201_CREATED)
async def create_{entity_snake}(data: {entity}Create, db: AsyncSession = Depends(get_db)):
    service = {entity}Service(db)
    return await service.create(data)


@router.patch("/{{{entity_snake}_id}}", response_model={entity}InDB)
async def update_{entity_snake}({entity_snake}_id: int, data: {entity}Update, db: AsyncSession = Depends(get_db)):
    service = {entity}Service(db)
    obj = await service.update({entity_snake}_id, data)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{entity} not found")
    return obj


@router.delete("/{{{entity_snake}_id}}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_{entity_snake}({entity_snake}_id: int, db: AsyncSession = Depends(get_db)):
    service = {entity}Service(db)
    deleted = await service.delete({entity_snake}_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{entity} not found")
"""

    files[f"tests/test_{entity_plural}.py"] = f"""import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_{entity_snake}(client: AsyncClient):
    response = await client.post("{base_route}/", json={{
        {', '.join(f'"{f["name"]}": "test_{f["name"]}"' for f in fields)}
    }})
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None


@pytest.mark.asyncio
async def test_list_{entity_plural}(client: AsyncClient):
    response = await client.get("{base_route}/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_{entity_snake}_not_found(client: AsyncClient):
    response = await client.get("{base_route}/99999")
    assert response.status_code == 404
"""

    return files


# ── Express CRUD ────────────────────────────────────────────
def _gen_express_crud(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    entity = params.get("entity", "Item")
    entity_snake = _snake(entity)
    entity_plural = params.get("plural", f"{entity_snake}s")
    base_route = params.get("base_route", f"/api/v1/{entity_plural}")
    fields = params.get("fields", [{"name": "name", "type": "string", "required": True}])

    zod_fields = "\n".join(
        f"  {f['name']}: z.{f.get('zod_type', 'string')()}(),"
        for f in fields
    )

    files = {}
    files[f"src/routes/{entity_plural}.ts"] = f"""import {{ Router }} from 'express';
import {{ {entity}Controller }} from '../controllers/{entity_snake}.controller';

const router = Router();
const controller = new {entity}Controller();

router.get('/', controller.list);
router.get('/:id', controller.getById);
router.post('/', controller.create);
router.patch('/:id', controller.update);
router.delete('/:id', controller.remove);

export default router;
"""

    files[f"src/controllers/{entity_snake}.controller.ts"] = f"""import {{ Request, Response, NextFunction }} from 'express';
import {{ {entity}Service }} from '../services/{entity_snake}.service';

export class {entity}Controller {{
  private service = new {entity}Service();

  list = async (req: Request, res: Response, next: NextFunction) => {{
    try {{
      const items = await this.service.list();
      res.json(items);
    }} catch (err) {{
      next(err);
    }}
  }};

  getById = async (req: Request, res: Response, next: NextFunction) => {{
    try {{
      const item = await this.service.getById(req.params.id);
      if (!item) {{
        res.status(404).json({{ message: '{entity} not found' }});
        return;
      }}
      res.json(item);
    }} catch (err) {{
      next(err);
    }}
  }};

  create = async (req: Request, res: Response, next: NextFunction) => {{
    try {{
      const item = await this.service.create(req.body);
      res.status(201).json(item);
    }} catch (err) {{
      next(err);
    }}
  }};

  update = async (req: Request, res: Response, next: NextFunction) => {{
    try {{
      const item = await this.service.update(req.params.id, req.body);
      if (!item) {{
        res.status(404).json({{ message: '{entity} not found' }});
        return;
      }}
      res.json(item);
    }} catch (err) {{
      next(err);
    }}
  }};

  remove = async (req: Request, res: Response, next: NextFunction) => {{
    try {{
      await this.service.remove(req.params.id);
      res.status(204).send();
    }} catch (err) {{
      next(err);
    }}
  }};
}}
"""

    files[f"src/services/{entity_snake}.service.ts"] = f"""import {{ PrismaClient }} from '@prisma/client';

const prisma = new PrismaClient();

export class {entity}Service {{
  async list() {{
    return prisma.{entity_snake}.findMany();
  }}

  async getById(id: string) {{
    return prisma.{entity_snake}.findUnique({{ where: {{ id }} }});
  }}

  async create(data: any) {{
    return prisma.{entity_snake}.create({{ data }});
  }}

  async update(id: string, data: any) {{
    return prisma.{entity_snake}.update({{ where: {{ id }}, data }});
  }}

  async remove(id: string) {{
    return prisma.{entity_snake}.delete({{ where: {{ id }} }});
  }}
}}
"""

    files[f"src/validators/{entity_snake}.schema.ts"] = f"""import {{ z }} from 'zod';

export const create{entity}Schema = z.object({{
{zod_fields}
}});

export const update{entity}Schema = create{entity}Schema.partial();
"""

    return files


# ── Go Gin CRUD ────────────────────────────────────────────
def _gen_go_gin_crud(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    entity = params.get("entity", "Item")
    entity_snake = _snake(entity)
    entity_plural = params.get("plural", f"{entity_snake}s")
    base_route = params.get("base_route", f"/api/v1/{entity_plural}")
    fields = params.get("fields", [{"name": "Name", "type": "string", "required": True}])

    struct_fields = "\n".join(
        f"\t{f['name']} {f.get('type', 'string')} `json:\"{_snake(f['name'])}\"{' validate:\"required\"' if f.get('required') else ''}`"
        for f in fields
    )

    files = {}
    files[f"dto/{entity_snake}.go"] = f"""package dto

type Create{entity} struct {{
{struct_fields}
}}

type Update{entity} struct {{
{struct_fields}
}}
"""

    files[f"handlers/{entity_snake}_handler.go"] = f"""package handlers

import (
    "net/http"
    "strconv"

    "github.com/gin-gonic/gin"
    "yourmodule/internal/dto"
    "yourmodule/internal/services"
)

type {entity}Handler struct {{
    svc services.{entity}Service
}}

func New{entity}Handler(svc services.{entity}Service) *{entity}Handler {{
    return &{entity}Handler{{svc: svc}}
}}

func (h *{entity}Handler) List(c *gin.Context) {{
    items, err := h.svc.List(c.Request.Context())
    if err != nil {{
        c.JSON(http.StatusInternalServerError, gin.H{{"error": err.Error()}})
        return
    }}
    c.JSON(http.StatusOK, items)
}}

func (h *{entity}Handler) GetByID(c *gin.Context) {{
    id, err := strconv.Atoi(c.Param("id"))
    if err != nil {{
        c.JSON(http.StatusBadRequest, gin.H{{"error": "invalid id"}})
        return
    }}
    item, err := h.svc.GetByID(c.Request.Context(), id)
    if err != nil {{
        c.JSON(http.StatusNotFound, gin.H{{"error": "not found"}})
        return
    }}
    c.JSON(http.StatusOK, item)
}}

func (h *{entity}Handler) Create(c *gin.Context) {{
    var req dto.Create{entity}
    if err := c.ShouldBindJSON(&req); err != nil {{
        c.JSON(http.StatusBadRequest, gin.H{{"error": err.Error()}})
        return
    }}
    item, err := h.svc.Create(c.Request.Context(), req)
    if err != nil {{
        c.JSON(http.StatusInternalServerError, gin.H{{"error": err.Error()}})
        return
    }}
    c.JSON(http.StatusCreated, item)
}}

func (h *{entity}Handler) Update(c *gin.Context) {{
    id, _ := strconv.Atoi(c.Param("id"))
    var req dto.Update{entity}
    if err := c.ShouldBindJSON(&req); err != nil {{
        c.JSON(http.StatusBadRequest, gin.H{{"error": err.Error()}})
        return
    }}
    item, err := h.svc.Update(c.Request.Context(), id, req)
    if err != nil {{
        c.JSON(http.StatusNotFound, gin.H{{"error": "not found"}})
        return
    }}
    c.JSON(http.StatusOK, item)
}}

func (h *{entity}Handler) Delete(c *gin.Context) {{
    id, _ := strconv.Atoi(c.Param("id"))
    if err := h.svc.Delete(c.Request.Context(), id); err != nil {{
        c.JSON(http.StatusNotFound, gin.H{{"error": "not found"}})
        return
    }}
    c.Status(http.StatusNoContent)
}}
"""

    files[f"services/{entity_snake}_service.go"] = f"""package services

import (
    "context"
    "yourmodule/internal/dto"
    "yourmodule/internal/models"
)

type {entity}Service struct {{}}

func New{entity}Service() *{entity}Service {{
    return &{entity}Service{{}}
}}

func (s *{entity}Service) List(ctx context.Context) ([]models.{entity}, error) {{
    // TODO: implement database query
    return nil, nil
}}

func (s *{entity}Service) GetByID(ctx context.Context, id int) (*models.{entity}, error) {{
    // TODO: implement database query
    return nil, nil
}}

func (s *{entity}Service) Create(ctx context.Context, req dto.Create{entity}) (*models.{entity}, error) {{
    // TODO: implement database insert
    return nil, nil
}}

func (s *{entity}Service) Update(ctx context.Context, id int, req dto.Update{entity}) (*models.{entity}, error) {{
    // TODO: implement database update
    return nil, nil
}}

func (s *{entity}Service) Delete(ctx context.Context, id int) error {{
    // TODO: implement database delete
    return nil
}}
"""

    files[f"routes/{entity_plural}_routes.go"] = f"""package routes

import (
    "github.com/gin-gonic/gin"
    "yourmodule/internal/handlers"
    "yourmodule/internal/services"
)

func Register{entity}Routes(r *gin.Engine) {{
    svc := services.New{entity}Service()
    h := handlers.New{entity}Handler(svc)
    g := r.Group("{base_route}")
    {{
        g.GET("/", h.List)
        g.GET("/:id", h.GetByID)
        g.POST("/", h.Create)
        g.PUT("/:id", h.Update)
        g.DELETE("/:id", h.Delete)
    }}
}}
"""

    return files


# ── Spring Boot CRUD ─────────────────────────────────────────
def _gen_spring_crud(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    entity = params.get("entity", "Item")
    entity_snake = _snake(entity)
    entity_plural = params.get("plural", f"{entity_snake}s")
    base_route = params.get("base_route", f"/api/v1/{entity_plural}")
    package_name = params.get("package", "com.example.demo")
    fields = params.get("fields", [{"name": "name", "type": "String", "required": True}])

    field_decls = "\n".join(
        f"    private {f.get('type', 'String')} {f['name']};"
        for f in fields
    )
    record_fields = ", ".join(
        f"{f.get('type', 'String')} {f['name']}"
        for f in fields
    )

    files = {}
    files[f"src/main/java/{package_name.replace('.', '/')}/entity/{entity}.java"] = f"""package {package_name}.entity;

import jakarta.persistence.*;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "{entity_plural}")
public class {entity} {{
    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;
{field_decls}
    @Column(updatable = false)
    private Instant createdAt = Instant.now();
    private Instant updatedAt = Instant.now();

    // Getters and setters omitted for brevity
}}
"""

    files[f"src/main/java/{package_name.replace('.', '/')}/dto/{entity}Dto.java"] = f"""package {package_name}.dto;

import jakarta.validation.constraints.NotBlank;
import java.util.UUID;

public record {entity}Dto(
    UUID id,
{chr(10).join(f'    @NotBlank {f.get("type", "String")} {f["name"]},' for f in fields)}
    Instant createdAt
) {{}}
"""

    files[f"src/main/java/{package_name.replace('.', '/')}/repository/{entity}Repository.java"] = f"""package {package_name}.repository;

import {package_name}.entity.{entity};
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.UUID;

public interface {entity}Repository extends JpaRepository<{entity}, UUID> {{
}}
"""

    files[f"src/main/java/{package_name.replace('.', '/')}/service/{entity}Service.java"] = f"""package {package_name}.service;

import {package_name}.dto.{entity}Dto;
import {package_name}.entity.{entity};
import {package_name}.repository.{entity}Repository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;
import java.util.UUID;

@Service
@Transactional
public class {entity}Service {{
    private final {entity}Repository repo;

    public {entity}Service({entity}Repository repo) {{
        this.repo = repo;
    }}

    public List<{entity}Dto> findAll() {{
        return repo.findAll().stream()
            .map(this::toDto)
            .toList();
    }}

    public {entity}Dto findById(UUID id) {{
        return repo.findById(id)
            .map(this::toDto)
            .orElseThrow(() -> new RuntimeException("Not found"));
    }}

    public {entity}Dto create({entity}Dto dto) {{
        var entity = new {entity}();
        // map fields
        return toDto(repo.save(entity));
    }}

    public {entity}Dto update(UUID id, {entity}Dto dto) {{
        var entity = repo.findById(id).orElseThrow(() -> new RuntimeException("Not found"));
        // map fields
        return toDto(repo.save(entity));
    }}

    public void delete(UUID id) {{
        repo.deleteById(id);
    }}

    private {entity}Dto toDto({entity} e) {{
        return new {entity}Dto(e.getId(), /* fields */, e.getCreatedAt());
    }}
}}
"""

    files[f"src/main/java/{package_name.replace('.', '/')}/controller/{entity}Controller.java"] = f"""package {package_name}.controller;

import {package_name}.dto.{entity}Dto;
import {package_name}.service.{entity}Service;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("{base_route}")
public class {entity}Controller {{
    private final {entity}Service service;

    public {entity}Controller({entity}Service service) {{
        this.service = service;
    }}

    @GetMapping
    public List<{entity}Dto> list() {{
        return service.findAll();
    }}

    @GetMapping("/{{id}}")
    public {entity}Dto getById(@PathVariable UUID id) {{
        return service.findById(id);
    }}

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public {entity}Dto create(@Valid @RequestBody {entity}Dto dto) {{
        return service.create(dto);
    }}

    @PutMapping("/{{id}}")
    public {entity}Dto update(@PathVariable UUID id, @Valid @RequestBody {entity}Dto dto) {{
        return service.update(id, dto);
    }}

    @DeleteMapping("/{{id}}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID id) {{
        service.delete(id);
    }}
}}
"""

    return files


# ── JWT Middleware Templates ────────────────────────────────
def _gen_jwt_middleware(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    lang = params.get("language", ctx.language or "python")
    files = {}

    if lang == "python":
        files["middleware/jwt_auth.py"] = """from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
import os

SECURITY_BEARER = HTTPBearer()
SECRET_KEY = os.environ["JWT_SECRET"]
ALGORITHM = "HS256"


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(SECURITY_BEARER),
) -> dict:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload
"""

    elif lang in ("javascript", "typescript"):
        files["middleware/jwtAuth.ts"] = """import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';

const SECRET = process.env.JWT_SECRET;
if (!SECRET) throw new Error('JWT_SECRET environment variable is required');

export interface AuthenticatedRequest extends Request {
  user?: jwt.JwtPayload | string;
}

export function jwtAuth(req: AuthenticatedRequest, res: Response, next: NextFunction) {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith('Bearer ')) {
    res.status(401).json({ message: 'Missing token' });
    return;
  }
  const token = authHeader.split(' ')[1];
  try {
    req.user = jwt.verify(token, SECRET);
    next();
  } catch {
    res.status(401).json({ message: 'Invalid token' });
  }
}
"""

    elif lang == "go":
        files["middleware/jwt.go"] = """package middleware

import (
    "net/http"
    "strings"

    "github.com/gin-gonic/gin"
    "github.com/golang-jwt/jwt/v5"
)

var jwtSecret []byte

func init() {
    s := os.Getenv("JWT_SECRET")
    if s == "" {
        panic("JWT_SECRET environment variable is required")
    }
    jwtSecret = []byte(s)
}

func JWTMiddleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        authHeader := c.GetHeader("Authorization")
        tokenString := strings.TrimPrefix(authHeader, "Bearer ")
        token, err := jwt.Parse(tokenString, func(token *jwt.Token) (interface{}, error) {
            return jwtSecret, nil
        })
        if err != nil || !token.Valid {
            c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "unauthorized"})
            return
        }
        c.Set("user", token.Claims)
        c.Next()
    }
}

func getenv(key, fallback string) string {
    if v := os.Getenv(key); v != "" {
        return v
    }
    return fallback
}
"""

    elif lang == "rust":
        files["src/middleware/jwt.rs"] = """use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::Response,
};
use jsonwebtoken::{decode, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub exp: usize,
}

pub async fn auth_middleware<B>(
    State(state): State<Arc<AppState>>,
    mut req: Request<B>,
    next: Next<B>,
) -> Result<Response, StatusCode> {
    let auth = req
        .headers()
        .get("authorization")
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "));
    let token = auth.ok_or(StatusCode::UNAUTHORIZED)?;
    let decoding = DecodingKey::from_secret(state.jwt_secret.as_bytes());
    let claims = decode::<Claims>(token, &decoding, &Validation::default())
        .map_err(|_| StatusCode::UNAUTHORIZED)?;
    req.extensions_mut().insert(claims.claims);
    Ok(next.run(req).await)
}
"""

    return files


# ── Health Check ────────────────────────────────────────────
def _gen_health_check(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    lang = params.get("language", ctx.language or "python")
    files = {}
    body = '{"status":"healthy","version":"1.0.0","uptime":"TODO"}'

    if lang == "python":
        files["routes/health.py"] = f"""from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    return {body}
"""
    elif lang in ("javascript", "typescript"):
        files["routes/health.ts"] = f"""import {{ Router, Request, Response }} from 'express';

const router = Router();

router.get('/health', (_req: Request, res: Response) => {{
    res.json({body});
}});

export default router;
"""
    elif lang == "go":
        files["handlers/health.go"] = f"""package handlers

import (
    "net/http"
    "github.com/gin-gonic/gin"
)

func HealthCheck(c *gin.Context) {{
    c.JSON(http.StatusOK, {body})
}}
"""
    elif lang == "java":
        files["controller/HealthController.java"] = f"""package com.example.health;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import java.util.Map;

@RestController
public class HealthController {{
    @GetMapping("/health")
    public Map<String, String> health() {{
        return Map.of("status", "healthy", "version", "1.0.0");
    }}
}}
"""
    elif lang == "csharp":
        files["Controllers/HealthController.cs"] = f"""using Microsoft.AspNetCore.Mvc;

namespace Health.Controllers;

[ApiController]
[Route("[controller]")]
public class HealthController : ControllerBase {{
    [HttpGet]
    public IActionResult Get() {{
        return Ok(new {{ status = "healthy", version = "1.0.0" }});
    }}
}}
"""
    elif lang == "ruby":
        files["app/controllers/health_controller.rb"] = f"""class HealthController < ApplicationController
  def index
    render json: {body}
  end
end
"""
    return files


# ── CLI Tool ────────────────────────────────────────────────
def _gen_cli_tool(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    lang = params.get("language", ctx.language or "python")
    cmd_name = params.get("cmd", "mytool")
    files = {}

    if lang == "python":
        files[f"{cmd_name}/main.py"] = f"""import typer
from rich.console import Console

app = typer.Typer()
console = Console()

@app.command()
def hello(name: str = typer.Argument("world", help="Name to greet")):
    console.print(f"Hello, {{name}}!")

if __name__ == "__main__":
    app()
"""
    elif lang == "go":
        files["cmd/main.go"] = f"""package main

import (
    "fmt"
    "os"

    "github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{{
    Use:   "{cmd_name}",
    Short: "A brief description of your application",
    Run: func(cmd *cobra.Command, args []string) {{
        fmt.Println("Hello from {cmd_name}")
    }},
}}

func main() {{
    if err := rootCmd.Execute(); err != nil {{
        fmt.Fprintln(os.Stderr, err)
        os.Exit(1)
    }}
}}
"""
    elif lang == "rust":
        files["src/main.rs"] = f"""use clap::{{Parser, Subcommand}};

#[derive(Parser)]
#[command(name = "{cmd_name}")]
struct Cli {{
    #[command(subcommand)]
    command: Commands,
}}

#[derive(Subcommand)]
enum Commands {{
    Hello {{ name: Option<String> }},
}}

fn main() {{
    let cli = Cli::parse();
    match cli.command {{
        Commands::Hello {{ name }} => {{
            println!("Hello, {{}}!", name.unwrap_or_else(|| "world".into()));
        }}
    }}
}}
"""
    elif lang == "ruby":
        files[f"bin/{cmd_name}"] = f"""#!/usr/bin/env ruby
require 'thor'

class {cmd_name.capitalize} < Thor
  desc "hello NAME", "Say hello to NAME"
  def hello(name = "world")
    puts "Hello, #{{name}}!"
  end
end

{cmd_name.capitalize}.start(ARGV)
"""
    return files


# ── Test Scaffold ───────────────────────────────────────────
def _gen_test_scaffold(ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    lang = params.get("language", ctx.language or "python")
    target = params.get("target", "MyService")
    files = {}

    if lang == "python":
        files[f"tests/test_{_snake(target)}.py"] = f"""import pytest
from unittest.mock import AsyncMock

from src.{_snake(target)} import {target}


@pytest.fixture
def service():
    return {target}(repo=AsyncMock())


@pytest.mark.asyncio
async def test_{_snake(target)}_success(service):
    # Arrange
    service.repo.get.return_value = {{"id": 1}}
    # Act
    result = await service.process()
    # Assert
    assert result is not None
    service.repo.get.assert_awaited_once()
"""
    elif lang in ("javascript", "typescript"):
        files[f"src/{target}.test.ts"] = f"""import {{ {target} }} from './{target}';

describe('{target}', () => {{
  let instance: {target};

  beforeEach(() => {{
    instance = new {target}();
  }});

  it('should process correctly', () => {{
    const result = instance.process();
    expect(result).toBeDefined();
  }});
}});
"""
    elif lang == "go":
        files[f"{target.lower()}_test.go"] = f"""package main

import "testing"

func Test{target}_Process(t *testing.T) {{
    svc := New{target}()
    result, err := svc.Process()
    if err != nil {{
        t.Fatalf("unexpected error: %v", err)
    }}
    if result == "" {{
        t.Fatal("expected non-empty result")
    }}
}}
"""
    elif lang == "rust":
        files[f"tests/{target.lower()}_test.rs"] = f"""use mycrate::{target};

#[tokio::test]
async fn test_{target.lower()}_success() {{
    let svc = {target}::new();
    let result = svc.process().await;
    assert!(result.is_ok());
}}
"""
    elif lang == "java":
        files[f"src/test/java/{target}Test.java"] = f"""package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class {target}Test {{
    @Test
    void shouldProcessSuccessfully() {{
        var svc = new {target}();
        var result = svc.process();
        assertNotNull(result);
    }}
}}
"""
    elif lang == "csharp":
        files[f"Tests/{target}Tests.cs"] = f"""using Xunit;

public class {target}Tests {{
    [Fact]
    public void Should_Process_Successfully() {{
        var svc = new {target}();
        var result = svc.Process();
        Assert.NotNull(result);
    }}
}}
"""
    elif lang == "ruby":
        files[f"spec/{target.downcase}_spec.rb"] = f"""require 'rspec'
require_relative '../lib/{target.downcase}'

RSpec.describe {target} do
  let(:svc) {{ described_class.new }}

  it 'processes successfully' do
    result = svc.process
    expect(result).not_to be_nil
  end
end
"""
    return files


# ──────────────────────────────────────────────────────────────
# Template Registry
# ──────────────────────────────────────────────────────────────

TEMPLATES: dict[str, dict[str, Any]] = {
    "fastapi_crud": {
        "languages": ["python"],
        "frameworks": ["fastapi"],
        "generator": _gen_fastapi_crud,
    },
    "express_crud": {
        "languages": ["javascript", "typescript"],
        "frameworks": ["express"],
        "generator": _gen_express_crud,
    },
    "go_gin_crud": {
        "languages": ["go"],
        "frameworks": ["gin", "echo", "fiber"],
        "generator": _gen_go_gin_crud,
    },
    "spring_crud": {
        "languages": ["java"],
        "frameworks": ["spring"],
        "generator": _gen_spring_crud,
    },
    "jwt_middleware": {
        "languages": ["python", "javascript", "typescript", "go", "rust"],
        "frameworks": [],
        "generator": _gen_jwt_middleware,
    },
    "health_check": {
        "languages": ["python", "javascript", "typescript", "go", "java", "csharp", "ruby"],
        "frameworks": [],
        "generator": _gen_health_check,
    },
    "cli_tool": {
        "languages": ["python", "go", "rust", "ruby"],
        "frameworks": [],
        "generator": _gen_cli_tool,
    },
    "test_scaffold": {
        "languages": ["python", "javascript", "typescript", "go", "rust", "java", "csharp", "ruby"],
        "frameworks": [],
        "generator": _gen_test_scaffold,
    },
}


def list_templates() -> None:
    print("Available templates:")
    for name, meta in TEMPLATES.items():
        langs = ", ".join(meta["languages"])
        fws = ", ".join(meta["frameworks"]) if meta["frameworks"] else "any"
        print(f"  {name:20}  languages=[{langs}]  frameworks=[{fws}]")


def run_template(template_name: str, ctx: ProjectContext, params: dict[str, Any]) -> dict[str, str]:
    meta = TEMPLATES.get(template_name)
    if not meta:
        raise ValueError(f"Unknown template: {template_name}. Run --list-templates to see options.")
    generator = meta["generator"]
    return generator(ctx, params)


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Intelligent code generator for developer workflows.")
    p.add_argument("--dir", type=Path, default=Path("."), help="Project directory to analyze")
    p.add_argument("--template", type=str, help="Template name to generate")
    p.add_argument("--entity", type=str, default="Item", help="Entity name for CRUD templates")
    p.add_argument("--plural", type=str, default=None, help="Plural form of entity")
    p.add_argument("--language", type=str, default=None, help="Override detected language")
    p.add_argument("--framework", type=str, default=None, help="Override detected framework")
    p.add_argument("--output", choices=["stdout", "file"], default="stdout", help="Output mode")
    p.add_argument("--list-templates", action="store_true", help="List available templates and exit")
    p.add_argument("--json-params", type=str, default="{}", help='Extra template params as JSON, e.g., {"fields":[{"name":"email","type":"str"}]}')
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_templates:
        list_templates()
        return 0

    if not args.template:
        print("Error: --template is required (or use --list-templates)", file=sys.stderr)
        return 1

    # Analyze project
    ctx = analyze_project(args.dir)
    if args.language:
        ctx.language = args.language
    if args.framework:
        ctx.framework = args.framework

    print(f"Detected context: {json.dumps(ctx.to_dict(), indent=2)}", file=sys.stderr)

    # Build params
    params: dict[str, Any] = {
        "entity": args.entity,
        "plural": args.plural or f"{_snake(args.entity)}s",
    }
    try:
        extra = json.loads(args.json_params)
        params.update(extra)
    except json.JSONDecodeError as exc:
        print(f"Invalid --json-params: {exc}", file=sys.stderr)
        return 1

    # Generate
    try:
        files = run_template(args.template, ctx, params)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Output
    if args.output == "stdout":
        for path, content in files.items():
            print(f"===== {path} =====")
            print(content)
    else:
        for path, content in files.items():
            out_path = args.dir / path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
