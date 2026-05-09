#!/usr/bin/env python3
"""Refactoring Engine — generate AST-based refactoring plans."""

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze a codebase and generate an AST-based refactoring plan."
    )
    parser.add_argument("--repo", required=True, help="Path to the codebase")
    parser.add_argument("--pattern", required=True, help="Target pattern to search (e.g., function name, import)")
    parser.add_argument("--target", help="Replacement target (optional)")
    parser.add_argument("--language", default="python", choices=["python", "js"], help="Language")
    parser.add_argument("--output", help="Path to write JSON plan")
    return parser.parse_args()


def find_python_matches(repo: str, pattern: str, target: str | None) -> list[dict[str, Any]]:
    """Find occurrences of a pattern in Python files using AST."""
    matches = []
    for root, _dirs, filenames in os.walk(repo):
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, repo).replace("\\", "/")
            try:
                source = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source)
            except SyntaxError:
                continue
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == pattern:
                    matches.append({
                        "file": rel,
                        "line": node.lineno,
                        "type": "function_def",
                        "name": node.name,
                        "suggestion": f"Refactor function '{node.name}'" if not target else f"Rename to '{target}'",
                    })
                elif isinstance(node, ast.ClassDef) and node.name == pattern:
                    matches.append({
                        "file": rel,
                        "line": node.lineno,
                        "type": "class_def",
                        "name": node.name,
                        "suggestion": f"Refactor class '{node.name}'" if not target else f"Rename to '{target}'",
                    })
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == pattern or (alias.asname and alias.asname == pattern):
                            matches.append({
                                "file": rel,
                                "line": node.lineno,
                                "type": "import",
                                "name": alias.name,
                                "suggestion": f"Update import of '{alias.name}'",
                            })
                elif isinstance(node, ast.ImportFrom):
                    if node.module == pattern:
                        matches.append({
                            "file": rel,
                            "line": node.lineno,
                            "type": "import_from",
                            "name": node.module,
                            "suggestion": f"Update import from '{node.module}'",
                        })
                    for alias in node.names:
                        if alias.name == pattern:
                            matches.append({
                                "file": rel,
                                "line": node.lineno,
                                "type": "import_from_symbol",
                                "name": alias.name,
                                "suggestion": f"Update symbol '{alias.name}'",
                            })
                elif isinstance(node, ast.Attribute) and node.attr == pattern:
                    matches.append({
                        "file": rel,
                        "line": getattr(node, "lineno", 0),
                        "type": "attribute_access",
                        "name": node.attr,
                        "suggestion": f"Refactor usage of '{node.attr}'",
                    })
                elif isinstance(node, ast.Name) and node.id == pattern:
                    matches.append({
                        "file": rel,
                        "line": getattr(node, "lineno", 0),
                        "type": "name_reference",
                        "name": node.id,
                        "suggestion": f"Refactor reference to '{node.id}'",
                    })
    return matches


def find_js_matches(repo: str, pattern: str, target: str | None) -> list[dict[str, Any]]:
    """Find occurrences of a pattern in JS/TS files using basic regex."""
    matches = []
    for root, _dirs, filenames in os.walk(repo):
        for fname in filenames:
            if not fname.endswith((".js", ".ts", ".jsx", ".tsx")):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, repo).replace("\\", "/")
            try:
                source = Path(fpath).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            regex_patterns = [
                (rf"\bfunction\s+{re.escape(pattern)}\b", "function_def"),
                (rf"\bclass\s+{re.escape(pattern)}\b", "class_def"),
                (rf"\b{re.escape(pattern)}\s*[=:]\s*function\b", "function_expression"),
                (rf"\bimport\s+.*?\bfrom\s+['\"]{re.escape(pattern)}['\"]", "import"),
                (rf"\brequire\s*\(\s*['\"]{re.escape(pattern)}['\"]\s*\)", "require"),
                (rf"\b{re.escape(pattern)}\b", "reference"),
            ]
            for pat, typ in regex_patterns:
                for m in re.finditer(pat, source):
                    line = source[:m.start()].count("\n") + 1
                    suggestion = f"Refactor {typ} '{pattern}'" if not target else f"Replace with '{target}'"
                    matches.append({
                        "file": rel,
                        "line": line,
                        "type": typ,
                        "name": pattern,
                        "suggestion": suggestion,
                    })
    seen = set()
    unique = []
    for m in matches:
        key = (m["file"], m["line"], m["type"])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def generate_refactoring_plan(matches: list[dict[str, Any]], language: str) -> dict[str, Any]:
    """Generate a refactoring plan from matched occurrences."""
    files_affected = sorted({m["file"] for m in matches})
    change_types = {}
    for m in matches:
        change_types[m["type"]] = change_types.get(m["type"], 0) + 1

    batches = []
    batch_size = 50
    for i in range(0, len(files_affected), batch_size):
        batches.append(files_affected[i:i + batch_size])

    return {
        "language": language,
        "total_matches": len(matches),
        "files_affected": files_affected,
        "affected_file_count": len(files_affected),
        "change_type_breakdown": change_types,
        "matches": matches,
        "batches": batches,
        "batch_count": len(batches),
        "validation_pyramid": [
            "compilation / type checking",
            "unit tests",
            "linting & formatting",
            "static analysis",
            "integration tests",
        ],
        "rollback_plan": {
            "strategy": "Atomic commits with git tags per batch",
            "commands": [
                "git checkout -b refactor-batch-{n}",
                "git add .",
                "git commit -m 'refactor: batch {n} transformation'",
                "git tag rollback-batch-{n}",
            ],
        },
    }


def main() -> int:
    """Main entry point."""
    args = parse_args()

    repo_path = Path(args.repo)
    if not repo_path.exists():
        print(json.dumps({"success": False, "error": f"Repo not found: {args.repo}"}), file=sys.stderr)
        return 1

    if args.language == "python":
        matches = find_python_matches(args.repo, args.pattern, args.target)
    else:
        matches = find_js_matches(args.repo, args.pattern, args.target)

    plan = generate_refactoring_plan(matches, args.language)
    plan["success"] = True
    plan["pattern"] = args.pattern
    plan["target"] = args.target

    if args.output:
        Path(args.output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
