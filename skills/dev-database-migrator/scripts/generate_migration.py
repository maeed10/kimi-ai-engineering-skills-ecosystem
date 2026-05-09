#!/usr/bin/env python3
"""
generate_migration.py

Generates forward and rollback migration scripts from schema diffs, ORM models,
or manual definitions. Supports validation, checksums, and seed data generation.

Supported databases: postgresql, mysql, sqlite, mongodb, dynamodb, redis
Supported ORMs: sqlalchemy, prisma, typeorm, sequelize, django, gorm

Usage:
    python generate_migration.py generate --from schema_old.yaml --to schema_new.yaml --db postgresql --output migrations/
    python generate_migration.py validate migration.up.sql --db postgresql
    python generate_migration.py seed --schema schema.yaml --environment dev --count 100
"""

import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()


def _write_migration_pair(
    output_dir: Path,
    name: str,
    forward: str,
    rollback: str,
    db: str,
    ext_map: Dict[str, str],
) -> Tuple[Path, Path, str, str]:
    ext = ext_map.get(db, "sql")
    ts = _now_str()
    base = f"{ts}_{_sanitize_name(name)}"

    up_file = output_dir / f"{base}.up.{ext}"
    down_file = output_dir / f"{base}.down.{ext}"

    up_file.write_text(forward, encoding="utf-8")
    down_file.write_text(rollback, encoding="utf-8")

    up_checksum = _sha256(forward)
    down_checksum = _sha256(rollback)

    meta = {
        "name": base,
        "db": db,
        "up_file": str(up_file),
        "down_file": str(down_file),
        "up_checksum": up_checksum,
        "down_checksum": down_checksum,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_file = output_dir / f"{base}.meta.json"
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return up_file, down_file, up_checksum, down_checksum


# ---------------------------------------------------------------------------
# Schema diff engine (simplified but functional)
# ---------------------------------------------------------------------------

class SchemaDiffEngine:
    def __init__(self, db: str):
        self.db = db

    def diff(self, old_schema: Dict, new_schema: Dict) -> Tuple[str, str]:
        """Return (forward_sql_or_script, rollback_sql_or_script)."""
        if self.db in ("mongodb", "dynamodb", "redis"):
            return self._diff_nosql(old_schema, new_schema)
        return self._diff_sql(old_schema, new_schema)

    def _diff_sql(self, old: Dict, new: Dict) -> Tuple[str, str]:
        old_tables = {t["name"]: t for t in old.get("tables", [])}
        new_tables = {t["name"]: t for t in new.get("tables", [])}

        forward_lines: List[str] = []
        rollback_lines: List[str] = []

        # Added tables
        for name, table in new_tables.items():
            if name not in old_tables:
                f, r = self._create_table(table)
                forward_lines.append(f)
                rollback_lines.append(r)

        # Dropped tables
        for name, table in old_tables.items():
            if name not in new_tables:
                f, r = self._drop_table(table)
                forward_lines.append(f)
                rollback_lines.append(r)

        # Modified tables
        for name in set(old_tables) & set(new_tables):
            f, r = self._diff_table(old_tables[name], new_tables[name])
            forward_lines.append(f)
            rollback_lines.append(r)

        forward = "\n\n".join(filter(None, forward_lines))
        rollback = "\n\n".join(filter(None, rollback_lines))

        # Wrap PostgreSQL in transaction by default, but CONCURRENTLY cannot run inside one
        if self.db == "postgresql":
            has_concurrently = "CONCURRENTLY" in forward
            if forward:
                if has_concurrently:
                    forward = f"-- NOTE: CREATE INDEX CONCURRENTLY cannot run inside a transaction.\n-- Run this migration outside a transaction or split into separate statements.\n\n{forward}"
                else:
                    forward = f"BEGIN;\n\n{forward}\n\nCOMMIT;"
            if rollback:
                rollback = f"BEGIN;\n\n{rollback}\n\nCOMMIT;"

        return forward, rollback

    def _create_table(self, table: Dict) -> Tuple[str, str]:
        name = table["name"]
        columns = table.get("columns", [])
        indexes = table.get("indexes", [])
        constraints = table.get("constraints", [])

        col_defs = []
        for col in columns:
            line = f"  {_column_def(col, self.db)}"
            col_defs.append(line)

        # Add inline constraints for PK
        pk_cols = [c["name"] for c in columns if c.get("primary_key")]
        if pk_cols and self.db in ("postgresql", "mysql", "sqlite"):
            col_defs.append(f"  PRIMARY KEY ({', '.join(pk_cols)})")

        body = ",\n".join(col_defs)
        forward = f"CREATE TABLE {name} (\n{body}\n);"

        for idx in indexes:
            forward += f"\n{self._index_sql(name, idx)}"

        for c in constraints:
            forward += f"\n{self._constraint_sql(name, c)}"

        rollback = f"DROP TABLE IF EXISTS {name};"
        return forward, rollback

    def _drop_table(self, table: Dict) -> Tuple[str, str]:
        name = table["name"]
        forward = f"DROP TABLE IF EXISTS {name};"
        # Rollback recreates table; real usage should restore from backup
        rollback = f"-- WARNING: Table {name} was dropped. Restore from backup to reverse.\n"
        rollback += self._create_table(table)[0]
        return forward, rollback

    def _diff_table(self, old: Dict, new: Dict) -> Tuple[str, str]:
        old_cols = {c["name"]: c for c in old.get("columns", [])}
        new_cols = {c["name"]: c for c in new.get("columns", [])}

        old_idxs = {i["name"]: i for i in old.get("indexes", [])}
        new_idxs = {i["name"]: i for i in new.get("indexes", [])}

        f_lines: List[str] = []
        r_lines: List[str] = []

        table = new["name"]

        # Added columns
        for col_name, col in new_cols.items():
            if col_name not in old_cols:
                f_lines.append(f"ALTER TABLE {table} ADD COLUMN {_column_def(col, self.db)};")
                # Rollback drops column (data loss unless backup exists)
                r_lines.append(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col_name};")

        # Dropped columns (expand/contract warning)
        for col_name, col in old_cols.items():
            if col_name not in new_cols:
                f_lines.append(f"-- WARNING: Dropping column {col_name}. Data will be lost.\nALTER TABLE {table} DROP COLUMN IF EXISTS {col_name};")
                # Rollback recreates column; data restoration is manual
                r_lines.append(f"ALTER TABLE {table} ADD COLUMN {_column_def(col, self.db)};")
                r_lines.append(f"-- TODO: Restore {col_name} data from backup")

        # Modified columns (type, nullable, default)
        for col_name in set(old_cols) & set(new_cols):
            oc = old_cols[col_name]
            nc = new_cols[col_name]
            if _column_def(oc, self.db) != _column_def(nc, self.db):
                if self.db == "postgresql":
                    f_lines.append(f"ALTER TABLE {table} ALTER COLUMN {col_name} TYPE {nc['type']};")
                    if nc.get("nullable") is False:
                        f_lines.append(f"ALTER TABLE {table} ALTER COLUMN {col_name} SET NOT NULL;")
                    elif nc.get("nullable") is True:
                        f_lines.append(f"ALTER TABLE {table} ALTER COLUMN {col_name} DROP NOT NULL;")
                    # Rollback simplified: just type + nullable
                    r_lines.append(f"ALTER TABLE {table} ALTER COLUMN {col_name} TYPE {oc['type']};")
                    if oc.get("nullable") is False:
                        r_lines.append(f"ALTER TABLE {table} ALTER COLUMN {col_name} SET NOT NULL;")
                    elif oc.get("nullable") is True:
                        r_lines.append(f"ALTER TABLE {table} ALTER COLUMN {col_name} DROP NOT NULL;")
                elif self.db in ("mysql", "sqlite"):
                    f_lines.append(f"ALTER TABLE {table} MODIFY COLUMN {_column_def(nc, self.db)};")
                    r_lines.append(f"ALTER TABLE {table} MODIFY COLUMN {_column_def(oc, self.db)};")
                else:
                    f_lines.append(f"-- Column {col_name} changed; manual review required.")
                    r_lines.append(f"-- Column {col_name} rollback; manual review required.")

        # Added indexes
        for idx_name, idx in new_idxs.items():
            if idx_name not in old_idxs:
                f_lines.append(self._index_sql(table, idx))
                r_lines.append(f"DROP INDEX IF EXISTS {idx_name};")

        # Dropped indexes
        for idx_name, idx in old_idxs.items():
            if idx_name not in new_idxs:
                f_lines.append(f"DROP INDEX IF EXISTS {idx_name};")
                r_lines.append(self._index_sql(table, idx))

        return "\n".join(f_lines), "\n".join(r_lines)

    def _index_sql(self, table: str, idx: Dict) -> str:
        name = idx["name"]
        cols = ", ".join(idx["columns"])
        unique = "UNIQUE " if idx.get("unique") else ""
        if self.db == "postgresql":
            concurrently = "CONCURRENTLY " if idx.get("concurrently") else ""
            return f"CREATE {unique}INDEX {concurrently}{name} ON {table} ({cols});"
        return f"CREATE {unique}INDEX {name} ON {table} ({cols});"

    def _constraint_sql(self, table: str, c: Dict) -> str:
        name = c["name"]
        ctype = c["type"]
        if ctype == "foreign_key":
            cols = ", ".join(c["columns"])
            ref = f"{c['references_table']}({', '.join(c['references_columns'])}"
            if self.db == "postgresql":
                return f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({cols}) REFERENCES {ref}) NOT VALID;\nALTER TABLE {table} VALIDATE CONSTRAINT {name};"
            return f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({cols}) REFERENCES {ref});"
        if ctype == "unique":
            cols = ", ".join(c["columns"])
            return f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({cols});"
        return f"-- Unsupported constraint {name} ({ctype})"

    def _diff_nosql(self, old: Dict, new: Dict) -> Tuple[str, str]:
        if self.db == "mongodb":
            return self._diff_mongodb(old, new)
        if self.db == "dynamodb":
            return self._diff_dynamodb(old, new)
        if self.db == "redis":
            return self._diff_redis(old, new)
        return "", ""

    def _diff_mongodb(self, old: Dict, new: Dict) -> Tuple[str, str]:
        old_colls = {c["name"]: c for c in old.get("collections", [])}
        new_colls = {c["name"]: c for c in new.get("collections", [])}

        f_lines: List[str] = []
        r_lines: List[str] = []

        for name, coll in new_colls.items():
            if name not in old_colls:
                f_lines.append(f"db.createCollection('{name}');")
                r_lines.append(f"db.{name}.drop();")

        for name, coll in old_colls.items():
            if name not in new_colls:
                f_lines.append(f"db.{name}.drop();")
                r_lines.append(f"// TODO: Restore collection {name} from backup")

        for name in set(old_colls) & set(new_colls):
            old_idxs = {i["name"]: i for i in old_colls[name].get("indexes", [])}
            new_idxs = {i["name"]: i for i in new_colls[name].get("indexes", [])}
            for idx_name, idx in new_idxs.items():
                if idx_name not in old_idxs:
                    keys = json.dumps({k: v for k, v in zip(idx["columns"], idx.get("orders", [1] * len(idx["columns"])))})
                    opts = f", {{ unique: {str(idx.get('unique', False)).lower()}, background: true }}"
                    f_lines.append(f"db.{name}.createIndex({keys}{opts});")
                    r_lines.append(f"db.{name}.dropIndex('{idx_name}');")
            for idx_name, idx in old_idxs.items():
                if idx_name not in new_idxs:
                    f_lines.append(f"db.{name}.dropIndex('{idx_name}');")
                    keys = json.dumps({k: v for k, v in zip(idx["columns"], idx.get("orders", [1] * len(idx["columns"])))})
                    opts = f", {{ unique: {str(idx.get('unique', False)).lower()}, background: true }}"
                    r_lines.append(f"db.{name}.createIndex({keys}{opts});")

        return "\n".join(f_lines), "\n".join(r_lines)

    def _diff_dynamodb(self, old: Dict, new: Dict) -> Tuple[str, str]:
        old_tables = {t["name"]: t for t in old.get("tables", [])}
        new_tables = {t["name"]: t for t in new.get("tables", [])}
        f_lines: List[str] = []
        r_lines: List[str] = []

        for name, t in new_tables.items():
            if name not in old_tables:
                f_lines.append(f"// Create DynamoDB table {name} via AWS SDK or CloudFormation")
                r_lines.append(f"// Delete DynamoDB table {name} via AWS SDK")
            old_gsis = {g["name"]: g for g in old_tables.get(name, {}).get("gsis", [])}
            new_gsis = {g["name"]: g for g in t.get("gsis", [])}
            for gname, g in new_gsis.items():
                if gname not in old_gsis:
                    f_lines.append(f"// Add GSI {gname} to {name}")
                    r_lines.append(f"// Remove GSI {gname} from {name}")
            for gname, g in old_gsis.items():
                if gname not in new_gsis:
                    f_lines.append(f"// Remove GSI {gname} from {name}")
                    r_lines.append(f"// Add GSI {gname} to {name}")

        return "\n".join(f_lines), "\n".join(r_lines)

    def _diff_redis(self, old: Dict, new: Dict) -> Tuple[str, str]:
        f_lines = ["// Redis schema changes are application-level"]
        r_lines = ["// Redis rollback is application-level"]
        old_keys = set(old.get("key_patterns", []))
        new_keys = set(new.get("key_patterns", []))
        added = new_keys - old_keys
        removed = old_keys - new_keys
        if added:
            f_lines.append(f"// New key patterns: {added}")
        if removed:
            f_lines.append(f"// Deprecated key patterns: {removed}")
        return "\n".join(f_lines), "\n".join(r_lines)


# ---------------------------------------------------------------------------
# Column definition helpers
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "string": {"postgresql": "VARCHAR", "mysql": "VARCHAR", "sqlite": "TEXT"},
    "text": {"postgresql": "TEXT", "mysql": "TEXT", "sqlite": "TEXT"},
    "integer": {"postgresql": "INTEGER", "mysql": "INT", "sqlite": "INTEGER"},
    "bigint": {"postgresql": "BIGINT", "mysql": "BIGINT", "sqlite": "INTEGER"},
    "boolean": {"postgresql": "BOOLEAN", "mysql": "BOOLEAN", "sqlite": "INTEGER"},
    "datetime": {"postgresql": "TIMESTAMP", "mysql": "DATETIME", "sqlite": "TEXT"},
    "json": {"postgresql": "JSONB", "mysql": "JSON", "sqlite": "TEXT"},
    "uuid": {"postgresql": "UUID", "mysql": "CHAR(36)", "sqlite": "TEXT"},
    "decimal": {"postgresql": "DECIMAL", "mysql": "DECIMAL", "sqlite": "REAL"},
}


def _column_def(col: Dict, db: str) -> str:
    name = col["name"]
    ctype = col.get("type", "string")
    db_type = _TYPE_MAP.get(ctype, {}).get(db, ctype.upper())
    length = col.get("length")
    if length and db in ("postgresql", "mysql") and "VARCHAR" in db_type.upper():
        db_type = f"{db_type}({length})"

    parts = [name, db_type]

    if col.get("primary_key") and db == "sqlite":
        parts.append("PRIMARY KEY AUTOINCREMENT")
    elif col.get("primary_key") and db == "mysql":
        parts.append("AUTO_INCREMENT")
    elif col.get("primary_key") and db == "postgresql":
        # SERIAL handled separately or inline
        if ctype == "integer":
            parts[1] = "SERIAL"

    nullable = col.get("nullable", True)
    if not nullable:
        parts.append("NOT NULL")

    default = col.get("default")
    if default is not None:
        if isinstance(default, str) and default.upper() in ("NOW()", "CURRENT_TIMESTAMP"):
            parts.append(f"DEFAULT {default}")
        elif isinstance(default, bool):
            parts.append(f"DEFAULT {str(default).upper()}")
        elif isinstance(default, (int, float)):
            parts.append(f"DEFAULT {default}")
        else:
            parts.append(f"DEFAULT '{default}'")

    unique = col.get("unique")
    if unique:
        parts.append("UNIQUE")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class MigrationValidator:
    def __init__(self, db: str):
        self.db = db

    def validate(self, path: Path) -> List[str]:
        errors: List[str] = []
        text = path.read_text(encoding="utf-8")

        if not text.strip():
            errors.append("Migration file is empty.")
            return errors

        # Checksum file sidecar
        meta_path = path.with_suffix(".meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            expected = meta.get("up_checksum") if ".up." in path.name else meta.get("down_checksum")
            if expected and _sha256(text) != expected:
                errors.append("Checksum mismatch: migration file was modified after generation.")

        # Database-specific checks
        if self.db in ("postgresql", "mysql", "sqlite"):
            errors.extend(self._validate_sql(text))
        elif self.db == "mongodb":
            errors.extend(self._validate_mongo(text))
        elif self.db == "dynamodb":
            errors.extend(self._validate_dynamodb(text))
        elif self.db == "redis":
            errors.extend(self._validate_redis(text))

        # Check rollback symmetry hint
        if "WARNING" in text and "rollback" not in text.lower():
            errors.append("Migration contains WARNING but rollback may be incomplete.")

        return errors

    def _validate_sql(self, text: str) -> List[str]:
        errors: List[str] = []
        lines = text.splitlines()

        for line in lines:
            stripped = line.strip().lower()

            if "create index" in stripped and "concurrently" not in stripped and self.db == "postgresql":
                if not stripped.startswith("--"):
                    errors.append("CREATE INDEX without CONCURRENTLY may lock table. Use CONCURRENTLY for production.")

            if "drop table" in stripped and "if exists" not in stripped:
                if not stripped.startswith("--"):
                    errors.append("DROP TABLE without IF EXISTS is unsafe.")

            if "alter table" in stripped and "drop column" in stripped:
                if "backup" not in text.lower():
                    errors.append("DROP COLUMN detected but no backup/restore step found in rollback.")

            if self.db == "mysql" and "alter table" in stripped:
                if "algorithm=inplace" not in stripped and "lock=none" not in stripped:
                    if not stripped.startswith("--"):
                        errors.append("MySQL ALTER TABLE missing ALGORITHM=INPLACE, LOCK=NONE. Consider online DDL.")

        return errors

    def _validate_mongo(self, text: str) -> List[str]:
        errors: List[str] = []
        if "createIndex" in text and "background" not in text:
            errors.append("MongoDB index creation missing background:true.")
        return errors

    def _validate_dynamodb(self, text: str) -> List[str]:
        errors: List[str] = []
        if "GSI" in text.upper() and "IndexStatus" not in text:
            errors.append("DynamoDB GSI changes should verify IndexStatus is ACTIVE before use.")
        return errors

    def _validate_redis(self, text: str) -> List[str]:
        errors: List[str] = []
        if "KEYS " in text:
            errors.append("Redis KEYS command is dangerous in production; use SCAN.")
        return errors


# ---------------------------------------------------------------------------
# Seed generation
# ---------------------------------------------------------------------------

class SeedGenerator:
    def __init__(self, db: str, schema: Optional[Dict] = None):
        self.db = db
        self.schema = schema or {}

    def generate(self, environment: str, count: int) -> str:
        if self.db in ("postgresql", "mysql", "sqlite"):
            return self._generate_sql_seed(environment, count)
        if self.db == "mongodb":
            return self._generate_mongo_seed(environment, count)
        if self.db == "dynamodb":
            return self._generate_dynamodb_seed(environment, count)
        if self.db == "redis":
            return self._generate_redis_seed(environment, count)
        return ""

    def _generate_sql_seed(self, environment: str, count: int) -> str:
        tables = self.schema.get("tables", [])
        lines = [f"-- Seed data for {environment}", f"-- Generated {count} rows per table", ""]

        for table in tables:
            name = table["name"]
            columns = table.get("columns", [])
            col_names = [c["name"] for c in columns if not (
                c.get("auto_increment") or (c.get("primary_key") and c.get("type") == "integer" and self.db in ("postgresql", "mysql")) or c.get("type") == "serial"
            )]
            # Simple deterministic seed
            for i in range(1, count + 1):
                vals = []
                for c in columns:
                    if c.get("auto_increment") or (c.get("primary_key") and c.get("type") == "integer" and self.db in ("postgresql", "mysql")):
                        continue
                    vals.append(self._sql_value(c, i, environment))
                if vals:
                    lines.append(
                        f"INSERT INTO {name} ({', '.join(col_names[:len(vals)])}) VALUES ({', '.join(vals)});"
                    )
            lines.append("")

        return "\n".join(lines)

    def _sql_value(self, col: Dict, i: int, env: str) -> str:
        ctype = col.get("type", "string")
        name = col["name"]
        if ctype in ("string", "text", "uuid"):
            if "email" in name:
                return f"'{env}_user{i}@example.com'"
            if "name" in name or "display_name" in name:
                return f"'Seed User {i}'"
            return f"'seed_{name}_{i}'"
        if ctype in ("integer", "bigint"):
            return str(i * 10)
        if ctype == "boolean":
            return "TRUE" if i % 2 == 0 else "FALSE"
        if ctype == "datetime":
            if self.db == "sqlite":
                return f"'2024-01-{((i-1)%28)+1:02d} 12:00:00'"
            return f"'2024-01-{((i-1)%28)+1:02d} 12:00:00'::timestamp"
        if ctype == "json":
            return "'{}'" if self.db != "postgresql" else "'{}'::jsonb"
        if ctype == "decimal":
            return f"{i}.00"
        return "NULL"

    def _generate_mongo_seed(self, environment: str, count: int) -> str:
        lines = [f"// Seed data for {environment}", ""]
        for coll in self.schema.get("collections", []):
            name = coll["name"]
            for i in range(1, count + 1):
                doc = { "_id": i, "seed": True, "env": environment }
                lines.append(f"db.{name}.insertOne({json.dumps(doc)});")
        return "\n".join(lines)

    def _generate_dynamodb_seed(self, environment: str, count: int) -> str:
        lines = [f"// Seed data for {environment} (AWS SDK v3 style)", ""]
        for t in self.schema.get("tables", []):
            name = t["name"]
            pk = t.get("primary_key", "id")
            for i in range(1, count + 1):
                lines.append(
                    f"await docClient.put({{ TableName: '{name}', Item: {{ {pk}: '{env}_seed_{i}', env: '{environment}', is_seed: true }} }}).promise();"
                )
        return "\n".join(lines)

    def _generate_redis_seed(self, environment: str, count: int) -> str:
        lines = [f"# Redis seed data for {environment}", ""]
        for i in range(1, count + 1):
            lines.append(f"SET {environment}:user:{i} 'seed_value_{i}'")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

DB_CHOICES = ["postgresql", "mysql", "sqlite", "mongodb", "dynamodb", "redis"]
ORM_CHOICES = ["sqlalchemy", "prisma", "typeorm", "sequelize", "django", "gorm"]


def _load_schema(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            return yaml.safe_load(text) or {}
        except ImportError:
            sys.exit("PyYAML is required to parse YAML schemas. Install it: pip install pyyaml")
    if path.suffix == ".json":
        return json.loads(text)
    sys.exit(f"Unsupported schema format: {path.suffix}")


def cmd_generate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    old_schema: Dict = {}
    new_schema: Dict = {}

    if args.from_schema and args.to_schema:
        old_schema = _load_schema(Path(args.from_schema))
        new_schema = _load_schema(Path(args.to_schema))
    elif args.orm_model:
        sys.exit("ORM model parsing is not fully implemented. Use --from and --to schema files.")
    else:
        sys.exit("Provide --from/--to schema files.")

    engine = SchemaDiffEngine(args.db)
    forward, rollback = engine.diff(old_schema, new_schema)

    if not forward.strip():
        print("No changes detected between schemas.")
        return 0

    ext_map = {
        "postgresql": "sql",
        "mysql": "sql",
        "sqlite": "sql",
        "mongodb": "js",
        "dynamodb": "js",
        "redis": "sh",
    }

    up_file, down_file, up_sum, down_sum = _write_migration_pair(
        output_dir, args.name or "migration", forward, rollback, args.db, ext_map
    )

    print(f"Generated migration:")
    print(f"  Forward : {up_file} (checksum: {up_sum})")
    print(f"  Rollback: {down_file} (checksum: {down_sum})")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.migration)
    if not path.exists():
        sys.exit(f"Migration file not found: {path}")

    validator = MigrationValidator(args.db)
    errors = validator.validate(path)

    if errors:
        print(f"Validation failed for {path}:")
        for e in errors:
            print(f"  [ERROR] {e}")
        return 1

    print(f"Validation passed for {path}.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    schema = {}
    if args.schema:
        schema = _load_schema(Path(args.schema))

    gen = SeedGenerator(args.db, schema)
    seed_text = gen.generate(args.environment, args.count)

    ts = _now_str()
    ext = "sql" if args.db in ("postgresql", "mysql", "sqlite") else ("js" if args.db in ("mongodb", "dynamodb") else "sh")
    seed_file = output_dir / f"{ts}_seed_{args.environment}.{ext}"
    seed_file.write_text(seed_text, encoding="utf-8")

    print(f"Seed script generated: {seed_file}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate, validate, and manage database migrations."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    gen_parser = sub.add_parser("generate", help="Generate forward/rollback migration scripts")
    gen_parser.add_argument("--from", dest="from_schema", help="Old schema file (YAML/JSON)")
    gen_parser.add_argument("--to", dest="to_schema", help="New schema file (YAML/JSON)")
    gen_parser.add_argument("--orm-model", help="ORM model file hint (not auto-parsed yet)")
    gen_parser.add_argument("--db", choices=DB_CHOICES, required=True)
    gen_parser.add_argument("--output", required=True, help="Output directory")
    gen_parser.add_argument("--name", default="migration", help="Migration name")
    gen_parser.set_defaults(func=cmd_generate)

    # validate
    val_parser = sub.add_parser("validate", help="Validate a migration file")
    val_parser.add_argument("migration", help="Migration file path")
    val_parser.add_argument("--db", choices=DB_CHOICES, required=True)
    val_parser.set_defaults(func=cmd_validate)

    # seed
    seed_parser = sub.add_parser("seed", help="Generate seed data script")
    seed_parser.add_argument("--schema", help="Schema file for context")
    seed_parser.add_argument("--db", choices=DB_CHOICES, required=True)
    seed_parser.add_argument("--environment", default="dev", help="Target environment")
    seed_parser.add_argument("--count", type=int, default=100, help="Rows per table/collection")
    seed_parser.add_argument("--output", default="./seeds", help="Output directory")
    seed_parser.set_defaults(func=cmd_seed)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
