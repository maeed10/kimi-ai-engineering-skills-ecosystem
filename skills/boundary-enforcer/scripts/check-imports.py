#!/usr/bin/env python3
"""
check-imports.py - Validate domain boundary compliance across a codebase.

Usage:
    python check-imports.py <repo_path> [options]

Options:
    --plan FILE          Path to PLAN.md (default: <repo>/PLAN.md)
    --agents FILE        Path to AGENTS.md (default: <repo>/AGENTS.md)
    --fix-suggest        Propose ACL / interface fixes for violations
    --format FMT         Output: table, json (default: table)
    --language LANG      Only check files of this language
    --verbose            Show parsing progress
    --help               Show this help message and exit

Safety: This script performs read-only analysis. It never modifies source code.
All output goes to stdout or the specified report file.

Exit Codes:
    0 - All boundaries respected (compliant)
    1 - Boundary violations found
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# File extensions by language
EXT_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}

# Import patterns per language
IMPORT_PATTERNS = {
    "python": [
        re.compile(r"^\s*import\s+(\S+)"),
        re.compile(r"^\s*from\s+(\S+)\s+import"),
    ],
    "javascript": [
        re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        re.compile(r"import\s*['\"]([^'\"]+)['\"]"),
    ],
    "typescript": [
        re.compile(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
        re.compile(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"),
        re.compile(r"import\s*['\"]([^'\"]+)['\"]"),
        re.compile(r"import\s+type\s+.*?\s+from\s+['\"]([^'\"]+)['\"]"),
    ],
    "java": [
        re.compile(r"^\s*import\s+([^;]+);"),
    ],
    "go": [
        re.compile(r'^\s*import\s+(?:\(\s*)?["\']([^"\']+)["\']'),
    ],
    "rust": [
        re.compile(r"^\s*use\s+([^;]+);"),
        re.compile(r"^\s*extern\s+crate\s+(\w+)"),
    ],
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Domain:
    """A bounded context / domain."""
    name: str
    paths: list[str]  # path prefixes that belong to this domain
    allowed_imports: list[str] = field(default_factory=list)  # domains this one can import from
    description: str = ""


@dataclass
class ImportStatement:
    source_file: str
    source_domain: str
    target: str
    target_domain: str
    line: int
    language: str
    is_external: bool = False  # e.g., npm/pip packages


@dataclass
class Violation:
    severity: str  # "error" | "warning"
    type: str      # "forbidden_import" | "circular_dependency" | "layer_violation"
    message: str
    source_file: str
    source_domain: str
    target: str
    target_domain: str
    line: int
    suggestion: str = ""


@dataclass
class BoundaryReport:
    domains: list[Domain] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    imports_analyzed: int = 0
    files_analyzed: int = 0
    external_imports: int = 0
    circular_chains: list[list[str]] = field(default_factory=list)
    compliant: bool = True


# ---------------------------------------------------------------------------
# Domain parsing from PLAN.md / AGENTS.md
# ---------------------------------------------------------------------------

def parse_domain_definitions(plan_path: Optional[Path], agents_path: Optional[Path]) -> list[Domain]:
    """Parse bounded context definitions from PLAN.md and/or AGENTS.md.

    Looks for sections like:

    ## Domains

    ### UserService
    - Path: src/user-service/
    - Can import: [shared, notifications]

    ### Payments
    - Path: src/payments/
    - Can import: [shared]

    Or markdown tables:
    | Domain | Path | Allowed Imports |
    |--------|------|-----------------|
    | user   | src/user/ | shared,utils |
    """
    domains: list[Domain] = []
    seen_names: set[str] = set()

    for path in [plan_path, agents_path]:
        if path is None or not path.exists():
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue

        # Pattern 1: ### DomainName followed by bullet list
        domain_blocks = re.finditer(
            r"#{2,4}\s+([^\n]+)\n([\s\S]*?)(?=\n#{2,4}\s|\Z)",
            content
        )
        for block in domain_blocks:
            name = block.group(1).strip()
            body = block.group(2)

            # Skip non-domain sections
            skip_keywords = ["overview", "introduction", "getting started", "architecture",
                           "context", "summary", "dependencies", "tools", "setup", "install"]
            if any(kw in name.lower() for kw in skip_keywords):
                # But check if body has path patterns
                if "path" not in body.lower() and "domain" not in name.lower():
                    continue

            paths: list[str] = []
            allowed: list[str] = []
            description = ""

            # Extract paths
            path_matches = re.findall(r"[\-*]\s*(?:[Pp]ath|[Ll]ocation|[Ss]ource):?\s*[`']?([^`\n]+)[`']?", body)
            paths.extend(p.strip().strip("/`'") for p in path_matches)

            # Also look for inline path mentions like `src/domain/`
            inline_paths = re.findall(r"`([^`]+/)`", body)
            paths.extend(p.strip() for p in inline_paths)

            # Extract allowed imports
            allowed_matches = re.findall(
                r"[\-*]\s*(?:[Cc]an import|[Aa]llowed imports?|[Dd]epends on|[Ii]mports):?\s*\[?([^\n\]]+)\]?",
                body
            )
            for am in allowed_matches:
                for item in re.split(r"[,;]", am):
                    item = item.strip().strip("[]'`\"")
                    if item and item.lower() not in ("none", "n/a"):
                        allowed.append(item)

            # Extract description
            desc_lines = [l.strip() for l in body.splitlines() if l.strip() and not l.strip().startswith("-") and not l.strip().startswith("*")]
            if desc_lines:
                description = desc_lines[0][:200]

            # Only add if we found meaningful path data
            if paths or ("domain" in name.lower() and paths):
                domain_name = re.sub(r"[^\w]", "_", name).strip("_").lower()
                if domain_name in seen_names:
                    # Merge with existing
                    for d in domains:
                        if d.name == domain_name:
                            d.paths.extend(paths)
                            d.allowed_imports.extend(allowed)
                            break
                else:
                    seen_names.add(domain_name)
                    domains.append(Domain(
                        name=domain_name,
                        paths=sorted(set(paths)),
                        allowed_imports=sorted(set(allowed)),
                        description=description,
                    ))

        # Pattern 2: Markdown tables with Domain/Path columns
        table_matches = re.finditer(
            r"\|\s*Domain\s*\|\s*Path\s*\|\s*[^|]*\|\n\|[-\s|]+\|\n((?:\|[^\n]+\|\n?)+)",
            content, re.IGNORECASE
        )
        for table_match in table_matches:
            rows = table_match.group(1).strip().split("\n")
            for row in rows:
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if len(cells) >= 2:
                    name = re.sub(r"[^\w]", "_", cells[0]).strip("_").lower()
                    paths_raw = cells[1]
                    allowed_raw = cells[2] if len(cells) > 2 else ""

                    if name in seen_names:
                        continue

                    seen_names.add(name)
                    paths = [p.strip() for p in re.split(r"[,;]", paths_raw) if p.strip()]
                    allowed = [a.strip() for a in re.split(r"[,;]", allowed_raw) if a.strip()]

                    domains.append(Domain(
                        name=name,
                        paths=paths,
                        allowed_imports=allowed,
                    ))

    return domains


def infer_domains_from_structure(repo_path: Path) -> list[Domain]:
    """Infer domain boundaries from common directory structures if no PLAN.md exists."""
    domains: list[Domain] = []

    # Common domain directory patterns
    domain_patterns = [
        "src/*", "lib/*", "app/*", "services/*",
        "domains/*", "modules/*", "packages/*",
        "domain/*", "contexts/*", "bounded_contexts/*",
    ]

    for pattern in domain_patterns:
        base = pattern.split("/*")[0]
        base_path = repo_path / base
        if base_path.exists() and base_path.is_dir():
            for subdir in sorted(base_path.iterdir()):
                if subdir.is_dir() and not subdir.name.startswith("."):
                    domains.append(Domain(
                        name=subdir.name.lower(),
                        paths=[f"{base}/{subdir.name}/"],
                        allowed_imports=[],
                    ))

    return domains


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

def extract_imports(file_path: Path, repo_path: Path, language: str) -> list[ImportStatement]:
    """Extract all import statements from a source file."""
    imports: list[ImportStatement] = []
    rel_path = str(file_path.relative_to(repo_path))

    patterns = IMPORT_PATTERNS.get(language, [])
    if not patterns:
        return imports

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return imports

    for line_num, line in enumerate(lines, 1):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                target = match.group(1).strip()
                # Filter out stdlib/external packages (heuristic)
                is_external = _is_external_package(target, language)
                imports.append(ImportStatement(
                    source_file=rel_path,
                    source_domain="",  # filled later
                    target=target,
                    target_domain="",  # filled later
                    line=line_num,
                    language=language,
                    is_external=is_external,
                ))
                break  # only capture first match per line

    return imports


def _is_external_package(import_path: str, language: str) -> bool:
    """Heuristic: determine if an import is an external package (stdlib/npm/pip/etc)."""
    if import_path.startswith(".") or import_path.startswith("/"):
        return False
    if import_path.startswith("@/") or import_path.startswith("~/"):
        return False

    stdlib_modules = {
        "python": {"os", "sys", "json", "re", "collections", "pathlib", "typing",
                   "datetime", "time", "math", "random", "hashlib", "subprocess",
                   "argparse", "csv", "sqlite3", "unittest", "itertools", "functools"},
        "javascript": {"react", "react-dom", "fs", "path", "http", "url", "crypto",
                       "stream", "events", "util", "os"},
        "java": {"java.", "javax.", "sun.", "com.sun.", "org.xml.", "org.w3c."},
        "go": {"fmt", "os", "io", "strings", "strconv", "time", "net/http",
               "encoding/json", "path/filepath", "crypto/sha256", "sync"},
        "rust": {"std::", "core::", "alloc::", "serde", "tokio", "async_trait",
                 "clap", "anyhow", "thiserror"},
    }

    std = stdlib_modules.get(language, set())
    first_part = import_path.split(".")[0].split("/")[0].split("::")[0]

    if first_part in std:
        return True
    if any(import_path.startswith(s) for s in std if len(s) > 2):
        return True

    # Heuristic: single-component imports in JS/TS are often npm packages
    if language in ("javascript", "typescript"):
        if "/" not in import_path and not import_path.startswith("."):
            return True

    # Heuristic: 3+ dot-separated components in Python often external
    if language == "python" and import_path.count(".") >= 2:
        return True

    return False


# ---------------------------------------------------------------------------
# Domain assignment
# ---------------------------------------------------------------------------

def assign_domain(file_path: str, domains: list[Domain]) -> str:
    """Determine which domain a file belongs to based on path."""
    for domain in domains:
        for prefix in domain.paths:
            # Normalize prefix
            p = prefix.strip("/")
            fp = file_path.lstrip("/")
            if p in fp or fp.startswith(p):
                return domain.name

    # Check common structural patterns
    parts = file_path.split("/")
    for part in parts:
        for domain in domains:
            if part.lower() == domain.name.lower():
                return domain.name

    return "unknown"


def is_import_allowed(source_domain: str, target_domain: str, domains: list[Domain]) -> bool:
    """Check if source_domain is allowed to import from target_domain."""
    if source_domain == target_domain:
        return True
    if source_domain == "unknown" or target_domain == "unknown":
        return True  # can't enforce what we can't classify

    domain_map = {d.name: d for d in domains}
    source = domain_map.get(source_domain)
    if source is None:
        return True

    # Check explicit allowed imports
    allowed = [a.lower() for a in source.allowed_imports]
    if target_domain.lower() in allowed:
        return True

    # Check if target_domain matches any path-based domain name
    for d in domains:
        if d.name.lower() == target_domain.lower():
            return d.name.lower() in allowed

    return False


# ---------------------------------------------------------------------------
# Circular dependency detection
# ---------------------------------------------------------------------------

def find_circular_dependencies(imports: list[ImportStatement]) -> list[list[str]]:
    """Find circular dependency chains between domains."""
    # Build domain-level dependency graph
    graph: dict[str, set[str]] = defaultdict(set)

    for imp in imports:
        if imp.is_external or not imp.source_domain or not imp.target_domain:
            continue
        if imp.source_domain != imp.target_domain and imp.target_domain != "unknown":
            graph[imp.source_domain].add(imp.target_domain)

    # Find cycles using DFS
    cycles: list[list[str]] = []
    visited: set[str] = set()

    def dfs(node: str, path: list[str], path_set: set[str]) -> None:
        if node in path_set:
            # Found cycle
            cycle_start = path.index(node)
            cycle = path[cycle_start:] + [node]
            # Normalize cycle (start from smallest element)
            min_idx = cycle.index(min(cycle[:-1]))
            normalized = cycle[min_idx:-1] + cycle[:min_idx]
            if normalized not in cycles:
                cycles.append(normalized)
            return

        if node in visited:
            return

        path.append(node)
        path_set.add(node)

        for neighbor in graph.get(node, set()):
            dfs(neighbor, path, path_set)

        path.pop()
        path_set.remove(node)
        visited.add(node)

    for node in list(graph.keys()):
        dfs(node, [], set())

    return cycles


# ---------------------------------------------------------------------------
# Suggestion engine
# ---------------------------------------------------------------------------

def generate_suggestion(violation: Violation, domains: list[Domain]) -> str:
    """Generate a suggested fix for a boundary violation."""
    domain_map = {d.name: d for d in domains}

    if violation.type == "forbidden_import":
        source = domain_map.get(violation.source_domain)
        target = domain_map.get(violation.target_domain)

        if source and target:
            return (
                f"Create an Anti-Corruption Layer (ACL) in {violation.source_domain} "
                f"that interfaces with {violation.target_domain}. "
                f"Define a port/interface in {violation.source_domain} "
                f"and implement an adapter in an infrastructure layer. "
                f"Alternatively, add '{violation.target_domain}' to "
                f"the allowed_imports list for {violation.source_domain} "
                f"in PLAN.md if this coupling is intentional."
            )
        return f"Review import: consider adding ACL or updating domain configuration"

    elif violation.type == "circular_dependency":
        return (
            f"Break the circular dependency by: (1) extracting shared logic into "
            f"a third 'shared' or 'common' domain, (2) using events/async "
            f"messaging instead of direct calls, or (3) applying the Dependency "
            f"Inversion Principle — define interfaces in the dependent domain."
        )

    elif violation.type == "layer_violation":
        return (
            f"Consider restructuring to follow declared layer boundaries. "
            f"Upper layers should not depend on lower layer internals."
        )

    return "Review and refactor to maintain domain boundaries"


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def print_report(report: BoundaryReport, format_type: str) -> None:
    """Print the boundary compliance report."""
    if format_type == "json":
        data = {
            "compliant": report.compliant and len(report.violations) == 0,
            "domains": [{"name": d.name, "paths": d.paths, "allowed_imports": d.allowed_imports}
                        for d in report.domains],
            "imports_analyzed": report.imports_analyzed,
            "files_analyzed": report.files_analyzed,
            "external_imports": report.external_imports,
            "violations": [asdict(v) for v in report.violations],
            "circular_chains": [list(c) for c in report.circular_chains],
        }
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    # Table format
    print("\n" + "=" * 60)
    print("Boundary Compliance Report")
    print("=" * 60)

    print(f"\n--- Domains ({len(report.domains)}) ---")
    if report.domains:
        for d in report.domains:
            allowed = ", ".join(d.allowed_imports) if d.allowed_imports else "(none specified)"
            print(f"  {d.name}")
            print(f"    Paths:   {d.paths}")
            print(f"    Allowed: {allowed}")
    else:
        print("  No domain definitions found. Run with --verbose to see inferred structure.")

    print(f"\n--- Analysis ---")
    print(f"  Files analyzed:   {report.files_analyzed}")
    print(f"  Imports analyzed: {report.imports_analyzed}")
    print(f"  External imports: {report.external_imports}")

    if report.circular_chains:
        print(f"\n--- Circular Dependencies ({len(report.circular_chains)}) ---")
        for chain in report.circular_chains:
            print(f"  {' -> '.join(chain)} -> {chain[0]}")

    errors = [v for v in report.violations if v.severity == "error"]
    warnings = [v for v in report.violations if v.severity == "warning"]

    print(f"\n--- Violations ---")
    print(f"  Errors:   {len(errors)}")
    print(f"  Warnings: {len(warnings)}")

    if errors:
        print(f"\n  --- Errors ---")
        for v in errors[:20]:
            print(f"    [{v.type}] {v.source_file}:{v.line}")
            print(f"      {v.source_domain} -> {v.target_domain} ({v.target})")
            if v.suggestion:
                print(f"      Fix: {v.suggestion[:120]}")

    if warnings:
        print(f"\n  --- Warnings ---")
        for v in warnings[:10]:
            print(f"    [{v.type}] {v.source_file}:{v.line}")
            print(f"      {v.message}")

    print("\n" + "=" * 60)
    if not errors and not warnings:
        print("Result: COMPLIANT - No boundary violations detected")
    elif not errors:
        print("Result: WARNING - Non-critical boundary concerns found")
    else:
        print(f"Result: VIOLATIONS - {len(errors)} error(s) found")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate domain boundary compliance across a codebase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Safety: This script performs read-only analysis. "
            "It never modifies source code. All output goes to stdout."
        ),
    )
    parser.add_argument("repo_path", help="Path to the repository root")
    parser.add_argument("--plan", help="Path to PLAN.md (default: <repo>/PLAN.md)")
    parser.add_argument("--agents", help="Path to AGENTS.md (default: <repo>/AGENTS.md)")
    parser.add_argument("--fix-suggest", action="store_true",
                        help="Propose ACL / interface fixes for violations")
    parser.add_argument("--format", choices=["table", "json"], default="table",
                        help="Output format (default: table)")
    parser.add_argument("--language", choices=list(IMPORT_PATTERNS.keys()),
                        help="Only check files of this language")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show parsing progress")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0")

    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.is_dir():
        print(f"Error: Not a directory: {repo_path}", file=sys.stderr)
        return 1

    # Resolve PLAN.md and AGENTS.md paths
    plan_path = Path(args.plan) if args.plan else repo_path / "PLAN.md"
    agents_path = Path(args.agents) if args.agents else repo_path / "AGENTS.md"

    # Parse domain definitions
    domains = parse_domain_definitions(
        plan_path if plan_path.exists() else None,
        agents_path if agents_path.exists() else None,
    )

    if not domains:
        if args.verbose:
            print("No PLAN.md or AGENTS.md found. Inferring domains from directory structure...")
        domains = infer_domains_from_structure(repo_path)

    if not domains:
        print("Error: No domain definitions found and could not infer from structure.", file=sys.stderr)
        print("Create a PLAN.md with domain definitions or use --plan/--agents.", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Found {len(domains)} domain(s):")
        for d in domains:
            print(f"  {d.name}: paths={d.paths}, allowed={d.allowed_imports}")

    # Discover source files
    source_files: list[tuple[Path, str]] = []
    gitignore_patterns = _read_gitignore(repo_path)

    for root, dirs, files in os.walk(repo_path):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if not _is_ignored(str(Path(root) / d), gitignore_patterns)]

        for fname in files:
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(repo_path))
            if _is_ignored(rel, gitignore_patterns):
                continue

            ext = fpath.suffix.lower()
            lang = EXT_MAP.get(ext)
            if lang is None:
                continue
            if args.language and lang != args.language:
                continue
            source_files.append((fpath, lang))

    if not source_files:
        print("No source files found to analyze.")
        return 0

    if args.verbose:
        print(f"Discovered {len(source_files)} source files to analyze")

    # Extract all imports
    all_imports: list[ImportStatement] = []
    for fpath, lang in source_files:
        imports = extract_imports(fpath, repo_path, lang)
        all_imports.extend(imports)

    # Assign domains to imports
    for imp in all_imports:
        imp.source_domain = assign_domain(imp.source_file, domains)
        # For target, try to determine domain from import path
        imp.target_domain = assign_domain(imp.target.replace(".", "/"), domains)

    external = sum(1 for i in all_imports if i.is_external)

    report = BoundaryReport(
        domains=domains,
        imports_analyzed=len(all_imports),
        files_analyzed=len(source_files),
        external_imports=external,
    )

    # Check for forbidden imports
    for imp in all_imports:
        if imp.is_external or imp.source_domain == "unknown":
            continue

        # Determine target domain more precisely
        target_domain = imp.target_domain
        if target_domain == "unknown":
            # Try to extract domain from import path
            for domain in domains:
                for prefix in domain.paths:
                    clean_prefix = prefix.strip("/").replace("/", ".")
                    if clean_prefix and imp.target.startswith(clean_prefix):
                        target_domain = domain.name
                        break
                if target_domain != "unknown":
                    break

        imp.target_domain = target_domain

        if target_domain == "unknown":
            continue

        if not is_import_allowed(imp.source_domain, imp.target_domain, domains):
            violation = Violation(
                severity="error",
                type="forbidden_import",
                message=(
                    f"File in domain '{imp.source_domain}' imports from "
                    f"'{imp.target}' which resolves to domain '{imp.target_domain}'"
                ),
                source_file=imp.source_file,
                source_domain=imp.source_domain,
                target=imp.target,
                target_domain=target_domain,
                line=imp.line,
            )
            if args.fix_suggest:
                violation.suggestion = generate_suggestion(violation, domains)
            report.violations.append(violation)

    # Detect circular dependencies
    report.circular_chains = find_circular_dependencies(all_imports)
    for chain in report.circular_chains:
        report.violations.append(Violation(
            severity="error",
            type="circular_dependency",
            message=f"Circular dependency detected: {' -> '.join(chain)}",
            source_file="",
            source_domain=chain[0],
            target="",
            target_domain=chain[-1],
            line=0,
            suggestion=generate_suggestion(
                Violation("error", "circular_dependency", "", "", chain[0], "", chain[-1], 0),
                domains
            ) if args.fix_suggest else "",
        ))

    # Print report
    print_report(report, args.format)

    return 0 if not any(v.severity == "error" for v in report.violations) else 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_gitignore(repo_root: Path) -> list[str]:
    """Read .gitignore patterns."""
    gitignore = repo_root / ".gitignore"
    patterns = [".git/", "node_modules/", "__pycache__/", ".venv/", "venv/",
                "target/", ".brownfield/", ".codetester/", "dist/", "build/"]
    if gitignore.exists():
        try:
            with open(gitignore, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line.strip("/"))
        except OSError:
            pass
    return patterns


def _is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a path is ignored."""
    for pat in patterns:
        pat = pat.strip("/")
        if pat in rel_path.split("/"):
            return True
        if rel_path.endswith("/" + pat) or rel_path.startswith(pat + "/"):
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
