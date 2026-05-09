#!/usr/bin/env python3
"""
query-db.py - Query a Brownfield Intelligence SQLite database.

Usage:
    python query-db.py <repo_path> [options]

Options:
    --dependents FILE    Find all files that depend on the given file
    --orphans            Find symbols with no incoming references
    --endpoints          List all API endpoints
    --metrics            Show top-10 most complex files
    --language LANG      Filter results by language (python, javascript, etc.)
    --format FMT         Output format: table (default), json, csv
    --help               Show this help message and exit

Safety: This script performs read-only queries on the SQLite database.
It never modifies source code or the database.

Exit Codes:
    0 - Query executed successfully
    1 - Database not found or query error
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BROWNFIELD_DIR = ".brownfield"
DB_NAME = "graph.db"

# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def open_db(repo_root: Path) -> sqlite3.Connection:
    """Open the SQLite database in read-only mode if possible."""
    db_path = repo_root / BROWNFIELD_DIR / DB_NAME
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    # Try read-only mode first
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        # Fall back to normal mode (WAL may prevent ro mode)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict."""
    return {key: row[key] for key in row.keys()}


# ---------------------------------------------------------------------------
# Query implementations
# ---------------------------------------------------------------------------

def query_dependents(conn: sqlite3.Connection, file_path: str, language: Optional[str]) -> list[dict]:
    """Find all files that depend on (import/call into) the given file."""
    # Resolve file to file_id
    cursor = conn.execute("SELECT id, path FROM files WHERE path = ?", (file_path,))
    row = cursor.fetchone()
    if row is None:
        # Try basename match
        cursor = conn.execute("SELECT id, path FROM files WHERE path LIKE ?", (f"%{file_path}",))
        row = cursor.fetchone()
        if row is None:
            # Try any substring match
            cursor = conn.execute("SELECT id, path FROM files WHERE path LIKE ?", (f"%{file_path}%",))
            row = cursor.fetchone()
            if row is None:
                return []

    file_id = row["id"]
    resolved_path = row["path"]

    # Get all symbol names from this file
    cursor = conn.execute("SELECT name FROM symbols WHERE file_id = ?", (file_id,))
    symbol_names = [r["name"] for r in cursor.fetchall()]

    # Also add the file basename as a potential import target
    basename = Path(resolved_path).stem
    if basename not in symbol_names:
        symbol_names.append(basename)

    if not symbol_names:
        return []

    # Find files that have dependencies matching these names
    placeholders = ",".join("?" * len(symbol_names))
    sql = f"""
        SELECT DISTINCT f.path, f.language, d.target_name, d.dep_type, d.line
        FROM dependencies d
        JOIN files f ON d.source_file_id = f.id
        WHERE d.target_name IN ({placeholders})
    """
    params = list(symbol_names)

    if language:
        sql += " AND f.language = ?"
        params.append(language)

    sql += " ORDER BY f.path, d.line"

    cursor = conn.execute(sql, params)
    results = [row_to_dict(r) for r in cursor.fetchall()]

    # Add resolved target info to each result
    for r in results:
        r["target_file"] = resolved_path

    return results


def query_orphans(conn: sqlite3.Connection, language: Optional[str]) -> list[dict]:
    """Find symbols that have no incoming references (dependencies pointing to them)."""
    sql = """
        SELECT f.path, s.name, s.type, s.line_start, s.line_end
        FROM symbols s
        JOIN files f ON s.file_id = f.id
        WHERE s.name NOT IN (
            SELECT DISTINCT d.target_name
            FROM dependencies d
        )
    """
    params = []
    if language:
        sql += " AND f.language = ?"
        params.append(language)

    sql += " ORDER BY f.path, s.type, s.name"

    cursor = conn.execute(sql, params)
    return [row_to_dict(r) for r in cursor.fetchall()]


def query_endpoints(conn: sqlite3.Connection, language: Optional[str]) -> list[dict]:
    """List all API endpoints."""
    sql = """
        SELECT f.path, f.language, e.path AS endpoint_path, e.method, e.line, e.framework
        FROM api_endpoints e
        JOIN files f ON e.file_id = f.id
    """
    params = []
    if language:
        sql += " WHERE f.language = ?"
        params.append(language)

    sql += " ORDER BY f.path, e.method, e.path"

    cursor = conn.execute(sql, params)
    return [row_to_dict(r) for r in cursor.fetchall()]


def query_metrics(conn: sqlite3.Connection, language: Optional[str], limit: int = 10) -> list[dict]:
    """Show top-N most complex files by cyclomatic complexity."""
    sql = """
        SELECT f.path, f.language, f.sloc, m.cyclomatic_complexity,
               m.function_count, m.class_count, m.import_count, m.avg_function_length
        FROM file_metrics m
        JOIN files f ON m.file_id = f.id
    """
    params = []
    conditions = []
    if language:
        conditions.append("f.language = ?")
        params.append(language)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += " ORDER BY m.cyclomatic_complexity DESC, f.sloc DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(sql, params)
    return [row_to_dict(r) for r in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def print_table(headers: list[str], rows: list[list[str]]) -> None:
    """Print a simple text table."""
    if not rows:
        print("  (no results)")
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    # Print header
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    print(sep)
    header_row = "| " + " | ".join(
        h.ljust(w) for h, w in zip(headers, widths)
    ) + " |"
    print(header_row)
    print(sep)

    # Print rows
    for row in rows:
        print("| " + " | ".join(
            str(c).ljust(w) for c, w in zip(row, widths)
        ) + " |")
    print(sep)
    print(f"  {len(rows)} row(s)")


def print_json(data: list[dict]) -> None:
    """Print results as JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def print_csv(headers: list[str], rows: list[list[str]]) -> None:
    """Print results as CSV."""
    writer = csv.writer(sys.stdout)
    writer.writerow(headers)
    writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query a Brownfield Intelligence SQLite database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: This script performs read-only queries. "
            "It never modifies source code or the database."
        ),
    )
    parser.add_argument("repo_path", help="Path to the repository root (containing .brownfield/)")
    parser.add_argument("--dependents", metavar="FILE",
                        help="Find all files depending on FILE")
    parser.add_argument("--orphans", action="store_true",
                        help="Find symbols with no references")
    parser.add_argument("--endpoints", action="store_true",
                        help="List all API endpoints")
    parser.add_argument("--metrics", action="store_true",
                        help="Show top-10 complexity metrics")
    parser.add_argument("--language", choices=["python", "javascript", "typescript", "java", "go", "rust"],
                        help="Filter by language")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table",
                        help="Output format (default: table)")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = parser.parse_args()

    repo_root = Path(args.repo_path).resolve()
    if not repo_root.is_dir():
        print(f"Error: Not a directory: {repo_root}", file=sys.stderr)
        return 1

    try:
        conn = open_db(repo_root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Validate at least one query option is specified
    if not any([args.dependents, args.orphans, args.endpoints, args.metrics]):
        print("Error: No query specified. Use one of: --dependents, --orphans, --endpoints, --metrics", file=sys.stderr)
        parser.print_help(sys.stderr)
        return 1

    exit_code = 0

    try:
        if args.dependents:
            results = query_dependents(conn, args.dependents, args.language)
            print(f"\n=== Dependents of '{args.dependents}' ===")
            if args.format == "json":
                print_json(results)
            elif args.format == "csv":
                if results:
                    headers = ["path", "language", "target_name", "dep_type", "line", "target_file"]
                    rows = [[str(r.get(h, "")) for h in headers] for r in results]
                    print_csv(headers, rows)
            else:
                headers = ["Source File", "Lang", "Target", "Type", "Line"]
                rows = [[r["path"], r["language"], r["target_name"], r["dep_type"], str(r["line"])] for r in results]
                print_table(headers, rows)
            if not results:
                print("  No dependents found (file may not be indexed or not referenced).")

        if args.orphans:
            results = query_orphans(conn, args.language)
            print(f"\n=== Orphaned Symbols ===")
            if args.format == "json":
                print_json(results)
            elif args.format == "csv":
                if results:
                    headers = ["path", "name", "type", "line_start", "line_end"]
                    rows = [[str(r.get(h, "")) for h in headers] for r in results]
                    print_csv(headers, rows)
            else:
                headers = ["File", "Symbol", "Type", "Line"]
                rows = [[r["path"], r["name"], r["type"], f"{r['line_start']}-{r['line_end']}"] for r in results]
                print_table(headers, rows)

        if args.endpoints:
            results = query_endpoints(conn, args.language)
            print(f"\n=== API Endpoints ===")
            if args.format == "json":
                print_json(results)
            elif args.format == "csv":
                if results:
                    headers = ["path", "language", "endpoint_path", "method", "line", "framework"]
                    rows = [[str(r.get(h, "")) for h in headers] for r in results]
                    print_csv(headers, rows)
            else:
                headers = ["File", "Lang", "Path", "Method", "Line", "Framework"]
                rows = [[r["path"], r["language"], r["endpoint_path"], r["method"], str(r["line"]), r["framework"]] for r in results]
                print_table(headers, rows)
            if not results:
                print("  No API endpoints found (may need to index with index-repo.py first).")

        if args.metrics:
            results = query_metrics(conn, args.language)
            print(f"\n=== Top Files by Cyclomatic Complexity ===")
            if args.format == "json":
                print_json(results)
            elif args.format == "csv":
                if results:
                    headers = ["path", "language", "sloc", "cyclomatic_complexity",
                               "function_count", "class_count", "import_count", "avg_function_length"]
                    rows = [[str(r.get(h, "")) for h in headers] for r in results]
                    print_csv(headers, rows)
            else:
                headers = ["File", "Lang", "SLOC", "Complexity", "Functions", "Classes", "Imports", "Avg Func Len"]
                rows = [[r["path"], r["language"], str(r["sloc"]), str(r["cyclomatic_complexity"]),
                         str(r["function_count"]), str(r["class_count"]), str(r["import_count"]),
                         str(r["avg_function_length"])] for r in results]
                print_table(headers, rows)

    except sqlite3.Error as exc:
        print(f"Error: Database query failed: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        conn.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
