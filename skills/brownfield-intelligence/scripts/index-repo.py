#!/usr/bin/env python3
"""
index-repo.py - Build a Brownfield Intelligence SQLite database from a codebase.

Usage:
    python index-repo.py <repo_path> [options]

Options:
    --incremental    Compare file hashes, only re-parse changed files
    --language LANG  Limit indexing to one language (python, javascript, java, go, rust, typescript)
    --verbose        Show detailed parsing progress
    --help           Show this help message and exit

Safety: This script is read-only on source code. It creates a .brownfield/
subdirectory inside the repo containing graph.db and indexing logs.
No source files are ever modified.

Exit Codes:
    0 - Indexing completed successfully
    1 - Fatal error or unparseable files (with error report)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BROWNFIELD_DIR = ".brownfield"
DB_NAME = "graph.db"

# File extension to language mapping
EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
}

# Tree-sitter language module names
TS_LANGUAGE_MODULES = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "java": "tree_sitter_java",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
}

# S-expression queries per language
QUERIES: dict[str, dict[str, str]] = {
    "python": {
        "function": """
            (function_definition name: (identifier) @name) @func
            (method_definition name: (property_identifier) @name) @func
        """,
        "class": "(class_definition name: (identifier) @name) @cls",
        "import": """
            (import_statement name: (dotted_name) @name) @imp
            (import_from_statement module_name: (dotted_name) @name) @imp
            (import_from_statement module_name: (relative_import) @name) @imp
        """,
        "call": """
            (call function: (identifier) @name) @call
            (call function: (attribute attribute: (identifier) @name)) @call
        """,
    },
    "javascript": {
        "function": """
            (function_declaration name: (identifier) @name) @func
            (arrow_function) @func
            (method_definition name: (property_identifier) @name) @func
        """,
        "class": "(class_declaration name: (identifier) @name) @cls",
        "import": """
            (import_statement source: (string) @name) @imp
            (import_statement (import_clause (named_imports (import_specifier name: (identifier) @name)))) @imp
        """,
        "call": "(call_expression function: (identifier) @name) @call",
    },
    "typescript": {
        "function": """
            (function_declaration name: (identifier) @name) @func
            (arrow_function) @func
            (method_definition name: (property_identifier) @name) @func
        """,
        "class": """
            (class_declaration name: (type_identifier) @name) @cls
            (interface_declaration name: (type_identifier) @name) @cls
        """,
        "import": """
            (import_statement source: (string) @name) @imp
            (import_statement (import_clause (named_imports (import_specifier name: (identifier) @name)))) @imp
        """,
        "call": "(call_expression function: (identifier) @name) @call",
    },
    "java": {
        "function": """
            (method_declaration name: (identifier) @name) @func
            (constructor_declaration name: (identifier) @name) @func
        """,
        "class": """
            (class_declaration name: (identifier) @name) @cls
            (interface_declaration name: (identifier) @name) @cls
        """,
        "import": "(import_declaration (scoped_identifier) @name) @imp",
        "call": "(method_invocation name: (identifier) @name) @call",
    },
    "go": {
        "function": """
            (function_declaration name: (identifier) @name) @func
            (method_declaration name: (field_identifier) @name) @func
        """,
        "class": "(type_declaration (type_spec name: (type_identifier) @name)) @cls",
        "import": """
            (import_spec path: (interpreted_string_literal) @name) @imp
        """,
        "call": "(call_expression function: (identifier) @name) @call",
    },
    "rust": {
        "function": """
            (function_item name: (identifier) @name) @func
            (method_call name: (field_identifier) @name) @func
        """,
        "class": """
            (struct_item name: (type_identifier) @name) @cls
            (enum_item name: (type_identifier) @name) @cls
            (trait_item name: (type_identifier) @name) @cls
            (impl_item type: (type_identifier) @name) @cls
        """,
        "import": """
            (use_declaration (scoped_use_list) @name) @imp
            (use_declaration (identifier) @name) @imp
        """,
        "call": "(call_expression function: (identifier) @name) @call",
    },
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    file_path: str
    language: str
    symbols: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    api_endpoints: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class IndexingReport:
    total_files: int = 0
    parsed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    total_symbols: int = 0
    total_dependencies: int = 0
    total_api_endpoints: int = 0
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def count_sloc(text: str) -> int:
    """Count source lines of code (non-blank, non-comment lines)."""
    lines = text.splitlines()
    count = 0
    in_block_comment = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        if "/*" in stripped and "*/" not in stripped:
            in_block_comment = True
            continue
        if "*/" in stripped:
            in_block_comment = False
            continue
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if not in_block_comment:
            count += 1
    return count


def get_git_hash(path: str) -> Optional[str]:
    """Get git hash for a file if inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "hash-object", "--", path],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=os.path.dirname(path) or ".",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def read_gitignore(repo_root: Path) -> list[str]:
    """Read .gitignore patterns if present."""
    gitignore = repo_root / ".gitignore"
    patterns = [".git/", ".brownfield/", "node_modules/", "__pycache__/", "*.pyc", ".venv/", "venv/", ".tox/", "dist/", "build/", ".egg-info/", ".mypy_cache/", ".pytest_cache/", ".idea/", ".vscode/", "target/", ".cargo/"]
    if gitignore.exists():
        try:
            with open(gitignore, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except OSError:
            pass
    return patterns


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any gitignore pattern."""
    for pat in patterns:
        pat = pat.strip("/")
        if pat in rel_path.split("/"):
            return True
        if rel_path.endswith(pat) or rel_path.startswith(pat):
            return True
        if "/" + pat + "/" in "/" + rel_path + "/":
            return True
    return False


# ---------------------------------------------------------------------------
# Tree-sitter integration
# ---------------------------------------------------------------------------

def get_tree_sitter_parser(language: str):
    """Get a tree-sitter parser for a language. Returns None if not available."""
    try:
        import tree_sitter
        from tree_sitter import Language, Parser

        module_name = TS_LANGUAGE_MODULES.get(language)
        if not module_name:
            return None

        try:
            mod = __import__(module_name)
            lang = Language(mod.language())
            try:
                parser = Parser(lang)
            except TypeError:
                parser = Parser()
                parser.set_language(lang)
            return parser
        except (ImportError, AttributeError):
            return None
    except ImportError:
        return None


def parse_file(file_path: Path, language: str) -> ParseResult:
    """Parse a single source file using tree-sitter."""
    result = ParseResult(
        file_path=str(file_path),
        language=language,
    )

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError as exc:
        result.errors.append(f"Cannot read file: {exc}")
        return result

    # Basic metrics (always computed)
    lines = source.splitlines()
    result.metrics = {
        "total_lines": len(lines),
        "sloc": count_sloc(source),
        "bytes": len(source.encode("utf-8")),
        "sha256": sha256_file(file_path),
    }

    # Try tree-sitter parsing
    parser = get_tree_sitter_parser(language)
    if parser is None:
        result.errors.append(f"Tree-sitter parser not available for {language}")
        # Fall back to regex-based import extraction
        _regex_extract(source, result, language)
        return result

    try:
        tree = parser.parse(source.encode("utf-8"))
    except Exception as exc:
        result.errors.append(f"Tree-sitter parse error: {exc}")
        _regex_extract(source, result, language)
        return result

    queries = QUERIES.get(language, {})
    if not queries:
        result.errors.append(f"No queries defined for {language}")
        return result

    try:
        import tree_sitter
        from tree_sitter import Query
        lang = parser.language

        for category, query_str in queries.items():
            if not query_str.strip():
                continue
            try:
                query = Query(lang, query_str)
                captures = query.captures(tree.root_node)
                for node, capture_name in captures:
                    if node.text is None:
                        continue
                    name = node.text.decode("utf-8") if isinstance(node.text, bytes) else str(node.text)
                    line = node.start_point[0] + 1

                    if category == "function":
                        result.symbols.append({
                            "name": name,
                            "type": "function",
                            "line_start": line,
                            "line_end": node.end_point[0] + 1,
                        })
                    elif category == "class":
                        result.symbols.append({
                            "name": name,
                            "type": "class",
                            "line_start": line,
                            "line_end": node.end_point[0] + 1,
                        })
                    elif category == "import":
                        dep_name = name.strip("'\"")
                        result.dependencies.append({
                            "name": dep_name,
                            "line": line,
                            "type": "import",
                        })
                    elif category == "call":
                        result.dependencies.append({
                            "name": name,
                            "line": line,
                            "type": "call",
                        })
            except Exception as exc:
                result.errors.append(f"Query error in {category}: {exc}")

    except ImportError:
        result.errors.append("tree-sitter Query API not available, using fallback")
        _regex_extract(source, result, language)
        return result

    # API endpoint detection
    result.api_endpoints = _detect_api_endpoints(source, language)

    return result


def _regex_extract(source: str, result: ParseResult, language: str) -> None:
    """Fallback regex-based extraction when tree-sitter is unavailable."""
    lines = source.splitlines()

    # Function detection via regex
    func_patterns = {
        "python": re.compile(r"^\s*def\s+(\w+)") ,
        "javascript": re.compile(r"^\s*(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\s*[\(\=])"),
        "typescript": re.compile(r"^\s*(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\s*[\(\=])"),
        "java": re.compile(r"^\s*(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\("),
        "go": re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)"),
        "rust": re.compile(r"^\s*fn\s+(\w+)"),
    }
    func_pat = func_patterns.get(language)
    if func_pat:
        for i, line in enumerate(lines):
            m = func_pat.search(line)
            if m:
                name = m.group(1) or m.group(2)
                if name:
                    result.symbols.append({
                        "name": name,
                        "type": "function",
                        "line_start": i + 1,
                        "line_end": i + 1,
                    })

    # Class detection via regex
    class_patterns = {
        "python": re.compile(r"^\s*class\s+(\w+)"),
        "javascript": re.compile(r"^\s*class\s+(\w+)"),
        "typescript": re.compile(r"^\s*(?:class|interface)\s+(\w+)"),
        "java": re.compile(r"^\s*(?:public\s+)?(?:class|interface)\s+(\w+)"),
        "go": re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface)"),
        "rust": re.compile(r"^\s*(?:struct|enum|trait|impl)\s+(?:<.*?>)?(\w+)"),
    }
    class_pat = class_patterns.get(language)
    if class_pat:
        for i, line in enumerate(lines):
            m = class_pat.search(line)
            if m:
                result.symbols.append({
                    "name": m.group(1),
                    "type": "class",
                    "line_start": i + 1,
                    "line_end": i + 1,
                })

    # Import detection via regex
    import_patterns = {
        "python": re.compile(r"^\s*(?:import\s+(\S+)|from\s+(\S+)\s+import)"),
        "javascript": re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
        "typescript": re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
        "java": re.compile(r"^\s*import\s+([^;]+);"),
        "go": re.compile(r'^\s*import\s+(?:\(\s*)?["\']([^"\']+)["\']'),
        "rust": re.compile(r"^\s*use\s+([^;]+);"),
    }
    imp_pat = import_patterns.get(language)
    if imp_pat:
        for i, line in enumerate(lines):
            m = imp_pat.search(line)
            if m:
                name = m.group(1) or m.group(2)
                if name:
                    result.dependencies.append({
                        "name": name,
                        "line": i + 1,
                        "type": "import",
                    })

    result.metrics["extraction_method"] = "regex_fallback"


def _detect_api_endpoints(source: str, language: str) -> list[dict]:
    """Detect API endpoint definitions using language-specific patterns."""
    endpoints = []
    lines = source.splitlines()

    # Python Flask/FastAPI/Django patterns
    if language == "python":
        route_patterns = [
            re.compile(r"@(app\.)?(route|get|post|put|delete|patch|api\.route)\s*\(\s*['\"]([^'\"]+)['\"]"),
            re.compile(r"@(router\.)?(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]"),
            re.compile(r"@(?:app|router|blueprint)\.\w+\s*\(\s*['\"]([^'\"]+)['\"]"),
        ]
        for i, line in enumerate(lines):
            for pat in route_patterns:
                m = pat.search(line)
                if m:
                    path = m.group(3) or m.group(1)
                    method = "GET"  # default
                    if "post" in line.lower():
                        method = "POST"
                    elif "put" in line.lower():
                        method = "PUT"
                    elif "delete" in line.lower():
                        method = "DELETE"
                    elif "patch" in line.lower():
                        method = "PATCH"
                    endpoints.append({
                        "path": path,
                        "method": method,
                        "line": i + 1,
                        "framework": "python_web",
                    })
                    break

    # JavaScript/TypeScript Express/Fastify/FastAPI patterns
    elif language in ("javascript", "typescript"):
        route_patterns = [
            re.compile(r"\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]"),
            re.compile(r"@(Get|Post|Put|Delete|Patch)\s*\(\s*['\"]([^'\"]+)['\"]"),
            re.compile(r"@(Get|Post|Put|Delete|Patch)\s*\([^)]*\)\s*$"),
        ]
        for i, line in enumerate(lines):
            for pat in route_patterns:
                m = pat.search(line)
                if m:
                    method = m.group(1).upper() if m.group(1) else "GET"
                    path = m.group(2) if len(m.groups()) > 1 and m.group(2) else "/"
                    endpoints.append({
                        "path": path,
                        "method": method,
                        "line": i + 1,
                        "framework": "js_web",
                    })
                    break

    # Java Spring patterns
    elif language == "java":
        route_patterns = [
            re.compile(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*\(\s*['\"]([^'\"]+)['\"]"),
        ]
        method_map = {
            "GetMapping": "GET",
            "PostMapping": "POST",
            "PutMapping": "PUT",
            "DeleteMapping": "DELETE",
            "PatchMapping": "PATCH",
            "RequestMapping": "ANY",
        }
        for i, line in enumerate(lines):
            for pat in route_patterns:
                m = pat.search(line)
                if m:
                    mapping = m.group(1)
                    path = m.group(2)
                    endpoints.append({
                        "path": path,
                        "method": method_map.get(mapping, "ANY"),
                        "line": i + 1,
                        "framework": "spring",
                    })
                    break

    # Go Gin/Echo/Fiber patterns
    elif language == "go":
        route_patterns = [
            re.compile(r"\.(GET|POST|PUT|DELETE|PATCH|Group)\s*\(\s*\"([^\"]+)\""),
            re.compile(r"\.(Handle(Func)?)\s*\(\s*\"([^\"]+)\""),
        ]
        for i, line in enumerate(lines):
            for pat in route_patterns:
                m = pat.search(line)
                if m:
                    method = m.group(1).upper() if m.group(1) else "ANY"
                    path = m.group(2) or m.group(3) or "/"
                    endpoints.append({
                        "path": path,
                        "method": method if method in ("GET", "POST", "PUT", "DELETE", "PATCH") else "ANY",
                        "line": i + 1,
                        "framework": "go_web",
                    })
                    break

    return endpoints


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def init_database(db_path: Path) -> sqlite3.Connection:
    """Initialize the SQLite database with the 6-table schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # files: file metadata
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            language TEXT,
            total_lines INTEGER,
            sloc INTEGER,
            bytes INTEGER,
            sha256 TEXT,
            last_modified REAL
        )
    """)

    # symbols: named entities
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            type TEXT,
            line_start INTEGER,
            line_end INTEGER
        )
    """)

    # dependencies: cross-file relationships
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            target_name TEXT,
            line INTEGER,
            dep_type TEXT
        )
    """)

    # api_endpoints: HTTP route definitions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            path TEXT,
            method TEXT,
            line INTEGER,
            framework TEXT
        )
    """)

    # file_metrics: complexity and size
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
            cyclomatic_complexity INTEGER DEFAULT 0,
            function_count INTEGER DEFAULT 0,
            class_count INTEGER DEFAULT 0,
            import_count INTEGER DEFAULT 0,
            avg_function_length REAL DEFAULT 0.0
        )
    """)

    # code_fts: FTS5 for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
            path, content,
            tokenize='porter'
        )
    """)

    # Indexing
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deps_source ON dependencies(source_file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_file ON api_endpoints(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_api_path ON api_endpoints(path)")

    conn.commit()
    return conn


def compute_cyclomatic_complexity(source: str, language: str) -> int:
    """Estimate cyclomatic complexity via branch keyword counting."""
    branch_keywords = {
        "python": ["if", "elif", "for", "while", "except", "with", "and", "or", "lambda"],
        "javascript": ["if", "for", "while", "catch", "&&", "||", "?.", "switch", "case"],
        "typescript": ["if", "for", "while", "catch", "&&", "||", "?.", "switch", "case"],
        "java": ["if", "for", "while", "catch", "&&", "||", "switch", "case", "?"],
        "go": ["if", "for", "switch", "case", "&&", "||", "select"],
        "rust": ["if", "for", "while", "match", "&&", "||", "?"],
    }
    keywords = branch_keywords.get(language, ["if", "for", "while"])
    count = 1  # base complexity
    for kw in keywords:
        count += source.count(kw)
    return min(count, 999)  # cap for sanity


def store_file(conn: sqlite3.Connection, repo_root: Path, file_path: Path,
               result: ParseResult, verbose: bool) -> int:
    """Store a single file's data in the database. Returns the file_id."""
    rel_path = str(file_path.relative_to(repo_root))

    # Insert or replace file record
    cursor = conn.execute(
        """INSERT OR REPLACE INTO files (path, language, total_lines, sloc, bytes, sha256, last_modified)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (rel_path, result.language, result.metrics.get("total_lines", 0),
         result.metrics.get("sloc", 0), result.metrics.get("bytes", 0),
         result.metrics.get("sha256", ""), time.time())
    )
    file_id = cursor.lastrowid

    # Clear old data for this file
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM dependencies WHERE source_file_id = ?", (file_id,))
    conn.execute("DELETE FROM api_endpoints WHERE file_id = ?", (file_id,))
    conn.execute("DELETE FROM file_metrics WHERE file_id = ?", (file_id,))

    # Insert symbols
    for sym in result.symbols:
        conn.execute(
            """INSERT INTO symbols (file_id, name, type, line_start, line_end)
               VALUES (?, ?, ?, ?, ?)""",
            (file_id, sym["name"], sym["type"], sym.get("line_start"), sym.get("line_end"))
        )

    # Insert dependencies
    for dep in result.dependencies:
        conn.execute(
            """INSERT INTO dependencies (source_file_id, target_name, line, dep_type)
               VALUES (?, ?, ?, ?)""",
            (file_id, dep["name"], dep.get("line"), dep.get("type", "import"))
        )

    # Insert API endpoints
    for ep in result.api_endpoints:
        conn.execute(
            """INSERT INTO api_endpoints (file_id, path, method, line, framework)
               VALUES (?, ?, ?, ?, ?)""",
            (file_id, ep["path"], ep["method"], ep.get("line"), ep.get("framework"))
        )

    # Compute and store metrics
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
    except OSError:
        source = ""

    cc = compute_cyclomatic_complexity(source, result.language)
    func_count = sum(1 for s in result.symbols if s["type"] == "function")
    class_count = sum(1 for s in result.symbols if s["type"] == "class")
    import_count = sum(1 for d in result.dependencies if d["type"] == "import")
    avg_func_len = 0.0
    if func_count > 0:
        total_len = sum(
            (s.get("line_end", 0) - s.get("line_start", 0) + 1)
            for s in result.symbols if s["type"] == "function"
        )
        avg_func_len = total_len / func_count

    conn.execute(
        """INSERT INTO file_metrics (file_id, cyclomatic_complexity, function_count,
           class_count, import_count, avg_function_length)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, cc, func_count, class_count, import_count, round(avg_func_len, 1))
    )

    # Update FTS index
    conn.execute("DELETE FROM code_fts WHERE path = ?", (rel_path,))
    conn.execute(
        "INSERT INTO code_fts (path, content) VALUES (?, ?)",
        (rel_path, source[:100000])  # cap FTS content
    )

    return file_id


# ---------------------------------------------------------------------------
# Incremental indexing
# ---------------------------------------------------------------------------

def get_stored_hashes(conn: sqlite3.Connection) -> dict[str, str]:
    """Get map of file path -> sha256 from the database."""
    cursor = conn.execute("SELECT path, sha256 FROM files WHERE sha256 IS NOT NULL")
    return {row[0]: row[1] for row in cursor.fetchall()}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def discover_files(repo_root: Path, language_filter: Optional[str], patterns: list[str]) -> list[tuple[Path, str]]:
    """Discover all parseable source files. Returns list of (path, language)."""
    files: list[tuple[Path, str]] = []
    for root, dirs, filenames in os.walk(repo_root):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if not is_ignored(str(Path(root) / d), patterns)]

        for fname in filenames:
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(repo_root))
            if is_ignored(rel, patterns):
                continue

            ext = fpath.suffix.lower()
            lang = EXT_TO_LANG.get(ext)
            if lang is None:
                continue
            if language_filter and lang != language_filter:
                continue
            files.append((fpath, lang))

    return sorted(files, key=lambda x: str(x[0]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Brownfield Intelligence SQLite database from a codebase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: This script is read-only on source code. It creates a "
            f"{BROWNFIELD_DIR}/ subdirectory with the database. No source files are modified."
        ),
    )
    parser.add_argument("repo_path", help="Path to the repository root")
    parser.add_argument("--incremental", action="store_true",
                        help="Only re-parse changed files (via SHA256 comparison)")
    parser.add_argument("--language", choices=list(TS_LANGUAGE_MODULES.keys()),
                        help="Limit indexing to a single language")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed parsing progress")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = parser.parse_args()

    repo_root = Path(args.repo_path).resolve()
    if not repo_root.is_dir():
        print(f"Error: Not a directory: {repo_root}", file=sys.stderr)
        return 1

    # Setup output directory
    bf_dir = repo_root / BROWNFIELD_DIR
    bf_dir.mkdir(exist_ok=True)
    db_path = bf_dir / DB_NAME

    # Initialize database
    conn = init_database(db_path)

    # Read ignore patterns
    patterns = read_gitignore(repo_root)

    # Discover files
    all_files = discover_files(repo_root, args.language, patterns)
    if not all_files:
        print("No parseable files found.")
        return 0

    # For incremental mode, check stored hashes
    stored_hashes: dict[str, str] = {}
    if args.incremental:
        stored_hashes = get_stored_hashes(conn)

    report = IndexingReport(total_files=len(all_files))
    start_time = time.time()

    # Process files
    for idx, (fpath, lang) in enumerate(all_files, 1):
        rel_path = str(fpath.relative_to(repo_root))

        # Check incremental skip
        if args.incremental:
            current_hash = sha256_file(fpath)
            if stored_hashes.get(rel_path) == current_hash:
                report.skipped_files += 1
                continue

        if args.verbose:
            print(f"[{idx}/{len(all_files)}] Parsing {rel_path} ({lang})")

        result = parse_file(fpath, lang)

        if result.errors:
            report.failed_files += 1
            for err in result.errors:
                report.errors.append(f"{rel_path}: {err}")
            if args.verbose:
                for err in result.errors:
                    print(f"  WARN: {err}")
        else:
            report.parsed_files += 1

        # Store results regardless (metrics are always available)
        try:
            store_file(conn, repo_root, fpath, result, args.verbose)
            conn.commit()
        except sqlite3.Error as exc:
            report.errors.append(f"{rel_path}: DB error: {exc}")
            if args.verbose:
                print(f"  DB ERROR: {exc}")

        report.total_symbols += len(result.symbols)
        report.total_dependencies += len(result.dependencies)
        report.total_api_endpoints += len(result.api_endpoints)

    report.elapsed_seconds = time.time() - start_time
    conn.close()

    # Print report
    print("\n" + "=" * 60)
    print("Brownfield Intelligence Indexing Report")
    print("=" * 60)
    print(f"  Repository:       {repo_root}")
    print(f"  Database:         {db_path}")
    print(f"  Language filter:  {args.language or 'all'}")
    print(f"  Incremental:      {args.incremental}")
    print()
    print(f"  Total files:      {report.total_files}")
    print(f"  Parsed:           {report.parsed_files}")
    print(f"  Failed:           {report.failed_files}")
    print(f"  Skipped:          {report.skipped_files}")
    print(f"  Total symbols:    {report.total_symbols}")
    print(f"  Dependencies:     {report.total_dependencies}")
    print(f"  API endpoints:    {report.total_api_endpoints}")
    print(f"  Time:             {report.elapsed_seconds:.2f}s")
    if report.errors:
        print(f"\n  Errors/Warnings:  {len(report.errors)}")
        for err in report.errors[:20]:
            print(f"    - {err}")
        if len(report.errors) > 20:
            print(f"    ... and {len(report.errors) - 20} more")
    print("=" * 60)

    # Write report JSON
    report_path = bf_dir / "indexing-report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_files": report.total_files,
            "parsed_files": report.parsed_files,
            "failed_files": report.failed_files,
            "skipped_files": report.skipped_files,
            "total_symbols": report.total_symbols,
            "total_dependencies": report.total_dependencies,
            "total_api_endpoints": report.total_api_endpoints,
            "elapsed_seconds": report.elapsed_seconds,
            "errors": report.errors,
        }, f, indent=2)

    return 0 if report.failed_files == 0 or report.parsed_files > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
