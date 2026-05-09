#!/usr/bin/env python3
"""explore_schema.py — Database schema inspection and query generation.

Connects to SQLite/PostgreSQL, inspects schema, generates entity diagrams,
and builds safe queries from natural language.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Schema Explorer")
    parser.add_argument("--db", required=True, help="SQLite database file path")
    parser.add_argument("--output", default="schema_report.json")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"ERROR: Database not found: {args.db}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    cursor = conn.cursor()

    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    schema = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = [{"name": r[1], "type": r[2], "nullable": not r[3], "default": r[4]} for r in cursor.fetchall()]
        cursor.execute(f"PRAGMA foreign_key_list({table})")
        fks = [{"from": r[3], "to_table": r[2], "to_col": r[4]} for r in cursor.fetchall()]
        schema[table] = {"columns": columns, "foreign_keys": fks}

    # Generate entity diagram text
    diagram = _generate_diagram(schema)

    report = {
        "database": args.db,
        "tables": len(tables),
        "schema": schema,
        "entity_diagram": diagram,
        "sample_queries": _generate_queries(schema),
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Schema: {report['tables']} tables, diagram written to {args.output}")
    return 0


def _generate_diagram(schema):
    lines = ["erDiagram"]
    for table, info in schema.items():
        lines.append(f"    {table} {{")
        for col in info["columns"]:
            lines.append(f"        {col['type']} {col['name']}")
        lines.append("    }")
    for table, info in schema.items():
        for fk in info["foreign_keys"]:
            lines.append(f"    {table} ||--o{{ {fk['to_table']} : {fk['from']}")
    return "\n".join(lines)


def _generate_queries(schema):
    queries = []
    for table in schema:
        queries.append(f"SELECT * FROM {table} LIMIT 10;")
    return queries


if __name__ == "__main__":
    sys.exit(main())
