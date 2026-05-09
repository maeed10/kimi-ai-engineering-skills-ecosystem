#!/usr/bin/env python3
"""
review_pr.py — Analyze a PR diff file and emit structured review comments.

Usage:
    python review_pr.py --diff pr.diff --format json > review_comments.json
    python review_pr.py --diff pr.diff --format markdown
    git diff main...HEAD | python review_pr.py --format markdown

The script performs static heuristic analysis on diff hunks to flag likely
security, performance, correctness, and style issues. It does NOT replace
human review; it accelerates it by surfacing patterns worth checking.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Iterator


class Severity(Enum):
    INFO = "info"
    SUGGESTION = "suggestion"
    CONCERN = "concern"
    BLOCKING = "blocking"


class Category(Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    CORRECTNESS = "correctness"
    STYLE = "style"
    MAINTAINABILITY = "maintainability"


@dataclass
class HunkLine:
    lineno: int | None
    content: str
    is_added: bool = False
    is_removed: bool = False


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[HunkLine] = field(default_factory=list)


@dataclass
class FileDiff:
    old_path: str | None
    new_path: str | None
    is_new: bool = False
    is_deleted: bool = False
    hunks: list[Hunk] = field(default_factory=list)


@dataclass
class Comment:
    category: Category
    severity: Severity
    message: str
    file: str
    line: int | None = None
    rule_id: str = ""


def parse_diff(text: str) -> list[FileDiff]:
    """Parse unified diff output into structured FileDiff objects."""
    files: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None
    new_lineno: int | None = None

    # Regexes
    file_header = re.compile(r"^diff --git a/(.+) b/(.+)$")
    new_file = re.compile(r"^new file mode ")
    deleted_file = re.compile(r"^deleted file mode ")
    hunk_header = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")

        if m := file_header.match(line):
            current_file = FileDiff(old_path=m.group(1), new_path=m.group(2))
            files.append(current_file)
            current_hunk = None
            new_lineno = None
            continue

        if current_file is None:
            continue

        if new_file.match(line):
            current_file.is_new = True
            continue
        if deleted_file.match(line):
            current_file.is_deleted = True
            continue

        if m := hunk_header.match(line):
            old_start = int(m.group(1))
            new_start = int(m.group(2))
            current_hunk = Hunk(
                old_start=old_start,
                old_count=0,
                new_start=new_start,
                new_count=0,
            )
            current_file.hunks.append(current_hunk)
            new_lineno = new_start
            continue

        if current_hunk is None or new_lineno is None:
            continue

        if line.startswith("+"):
            current_hunk.lines.append(
                HunkLine(lineno=new_lineno, content=line[1:], is_added=True)
            )
            new_lineno += 1
        elif line.startswith("-"):
            current_hunk.lines.append(
                HunkLine(lineno=None, content=line[1:], is_removed=True)
            )
        elif line.startswith(" "):
            current_hunk.lines.append(
                HunkLine(lineno=new_lineno, content=line[1:])
            )
            new_lineno += 1
        # "\\ No newline at end of file" and empty diff lines ignored

    return files


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

RULES: list[dict] = [
    {
        "id": "SEC-001",
        "category": Category.SECURITY,
        "severity": Severity.BLOCKING,
        "name": "hardcoded_secret",
        "pattern": re.compile(
            r"(?i)(password|passwd|pwd|secret|token|api_key|apikey|auth)\s*[=:]\s*['\"][^'\"]{4,}['\"]"
        ),
        "message": "Possible hardcoded secret or credential. Move to environment variables or a vault.",
        "extensions": (".py", ".js", ".ts", ".java", ".go", ".rb", ".sh", ".yml", ".yaml", ".json", ".tf", ".hcl"),
    },
    {
        "id": "SEC-002",
        "category": Category.SECURITY,
        "severity": Severity.CONCERN,
        "name": "sql_injection_risk",
        "pattern": re.compile(r"(?i)(execute|query|raw|exec)\s*\(.*%s.*\)|f['\"].*SELECT.*FROM.*\{.*\}"),
        "message": "Possible SQL injection vector. Use parameterized queries or an ORM.",
        "extensions": (".py", ".js", ".ts", ".java", ".go", ".rb", ".php"),
    },
    {
        "id": "SEC-003",
        "category": Category.SECURITY,
        "severity": Severity.BLOCKING,
        "name": "eval_usage",
        "pattern": re.compile(r"(?i)\beval\s*\(|new\s+Function\s*\(|exec\s*\("),
        "message": "Dangerous dynamic code execution. Avoid eval/exec; use safer alternatives.",
        "extensions": (".py", ".js", ".ts", ".rb", ".sh"),
    },
    {
        "id": "SEC-004",
        "category": Category.SECURITY,
        "severity": Severity.CONCERN,
        "name": "insecure_random",
        "pattern": re.compile(r"(?i)\bMath\.random\s*\(\s*\)|\brandom\.random\s*\(\s*\)"),
        "message": "Insecure randomness detected. Use crypto.getRandomValues or secrets module for security contexts.",
        "extensions": (".py", ".js", ".ts"),
    },
    {
        "id": "PERF-001",
        "category": Category.PERFORMANCE,
        "severity": Severity.SUGGESTION,
        "name": "nested_loop",
        "pattern": re.compile(r"^\s*for\s+.*:\s*$"),
        "context": re.compile(r"^\s*for\s+.*:\s*$"),
        "message": "Nested loop detected in diff. Verify time complexity and consider optimization if dataset may grow.",
        "extensions": (".py", ".js", ".ts", ".java", ".go", ".rb", ".c", ".cpp"),
        "needs_context": True,
    },
    {
        "id": "PERF-002",
        "category": Category.PERFORMANCE,
        "severity": Severity.CONCERN,
        "name": "n_plus_one",
        "pattern": re.compile(r"(?i)for\s+.*in\s+.*:\s*\n.*\.(get|fetch|find|query|select|where|filter)"),
        "message": "Possible N+1 query pattern. Use eager loading, batch fetching, or a dataloader.",
        "extensions": (".py", ".js", ".ts", ".java", ".go", ".rb", ".php"),
    },
    {
        "id": "CORR-001",
        "category": Category.CORRECTNESS,
        "severity": Severity.CONCERN,
        "name": "bare_except",
        "pattern": re.compile(r"^\s*except\s*:\s*$"),
        "message": "Bare except catches KeyboardInterrupt and SystemExit. Catch specific exceptions.",
        "extensions": (".py",),
    },
    {
        "id": "CORR-002",
        "category": Category.CORRECTNESS,
        "severity": Severity.CONCERN,
        "name": "missing_await",
        "pattern": re.compile(r"(?<!await\s)(\b[a-zA-Z_]\w*\b)\s*\(.*\)(?!\s*\.)"),
        "message": "Possible missing await on async function call. Verify return type.",
        "extensions": (".js", ".ts"),
    },
    {
        "id": "CORR-003",
        "category": Category.CORRECTNESS,
        "severity": Severity.SUGGESTION,
        "name": "null_comparison",
        "pattern": re.compile(r"==\s*null|!=\s*null"),
        "message": "Use === null / !== null to avoid type coercion bugs.",
        "extensions": (".js", ".ts"),
    },
    {
        "id": "CORR-004",
        "category": Category.CORRECTNESS,
        "severity": Severity.SUGGESTION,
        "name": "loose_equality",
        "pattern": re.compile(r"==\s+|!=\s+"),
        "message": "Loose equality detected. Prefer strict equality (=== / !==).",
        "extensions": (".js", ".ts"),
    },
    {
        "id": "CORR-005",
        "category": Category.CORRECTNESS,
        "severity": Severity.CONCERN,
        "name": "unhandled_promise",
        "pattern": re.compile(r"^\s*(?!.*await\s).*\.(then|catch|finally)\s*\("),
        "message": "Promise chain without await or return may be a floating promise.",
        "extensions": (".js", ".ts"),
    },
    {
        "id": "STYLE-001",
        "category": Category.STYLE,
        "severity": Severity.INFO,
        "name": "todo_without_ticket",
        "pattern": re.compile(r"(?i)#\s*TODO[^#]*$|//\s*TODO[^/]*$|\*\s*TODO[^*]*$"),
        "message": "TODO without a tracked ticket may be forgotten. Link to an issue tracker ID.",
        "extensions": (".py", ".js", ".ts", ".java", ".go", ".rb", ".c", ".cpp", ".rs"),
    },
    {
        "id": "STYLE-002",
        "category": Category.STYLE,
        "severity": Severity.INFO,
        "name": "console_log",
        "pattern": re.compile(r"console\.(log|warn|error|debug)\s*\("),
        "message": "Console logging statement added. Remove or replace with a structured logger before merging.",
        "extensions": (".js", ".ts"),
    },
    {
        "id": "STYLE-003",
        "category": Category.STYLE,
        "severity": Severity.INFO,
        "name": "print_debug",
        "pattern": re.compile(r"\bprint\s*\("),
        "message": "Print statement added. Use a logging framework for production code.",
        "extensions": (".py",),
    },
    {
        "id": "MAINT-002",
        "category": Category.MAINTAINABILITY,
        "severity": Severity.SUGGESTION,
        "name": "magic_number",
        "pattern": re.compile(r"\b\d{2,}\b|\b0[xX][0-9a-fA-F]+\b"),
        "message": "Magic number detected. Extract into a named constant for clarity.",
        "extensions": (".py", ".js", ".ts", ".java", ".go", ".rb", ".rs", ".c", ".cpp"),
    },
]


def _file_ext(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).suffix.lower()


def analyze_file(file_diff: FileDiff) -> Iterator[Comment]:
    ext = _file_ext(file_diff.new_path or file_diff.old_path)

    # Large hunk heuristic
    for hunk in file_diff.hunks:
        added_count = sum(1 for l in hunk.lines if l.is_added)
        if added_count > 50:
            yield Comment(
                category=Category.MAINTAINABILITY,
                severity=Severity.SUGGESTION,
                message="Hunk exceeds 50 added lines. Consider breaking the change into smaller, reviewable commits.",
                file=file_diff.new_path or "unknown",
                line=hunk.new_start,
                rule_id="MAINT-001",
            )

    for rule in RULES:
        if rule.get("extensions") and ext not in rule["extensions"]:
            continue

        # For rules that need multi-line context (e.g., nested loops)
        if rule.get("needs_context"):
            _yield_context_rule(file_diff, rule)
            continue

        for hunk in file_diff.hunks:
            for hunk_line in hunk.lines:
                if not hunk_line.is_added:
                    continue
                if rule["pattern"].search(hunk_line.content):
                    yield Comment(
                        category=rule["category"],
                        severity=rule["severity"],
                        message=rule["message"],
                        file=file_diff.new_path or "unknown",
                        line=hunk_line.lineno,
                        rule_id=rule["id"],
                    )


def _yield_context_rule(file_diff: FileDiff, rule: dict) -> Iterator[Comment]:
    """Simple nested-loop detection: two 'for' lines within 4 lines of each other."""
    ext = _file_ext(file_diff.new_path)
    if ext not in rule.get("extensions", ()):
        return
    for hunk in file_diff.hunks:
        added_lines = [l for l in hunk.lines if l.is_added]
        for i, line in enumerate(added_lines):
            if not line.content.strip().startswith("for"):
                continue
            # look ahead a few lines for another 'for'
            for j in range(i + 1, min(i + 5, len(added_lines))):
                if added_lines[j].content.strip().startswith("for"):
                    yield Comment(
                        category=rule["category"],
                        severity=rule["severity"],
                        message=rule["message"],
                        file=file_diff.new_path or "unknown",
                        line=line.lineno,
                        rule_id=rule["id"],
                    )
                    break


def analyze(diff_text: str) -> list[Comment]:
    files = parse_diff(diff_text)
    comments: list[Comment] = []
    for f in files:
        comments.extend(analyze_file(f))
    return comments


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def format_json(comments: list[Comment]) -> str:
    out = [
        {
            "category": c.category.value,
            "severity": c.severity.value,
            "message": c.message,
            "file": c.file,
            "line": c.line,
            "rule_id": c.rule_id,
        }
        for c in comments
    ]
    return json.dumps(out, indent=2)


def format_markdown(comments: list[Comment]) -> str:
    if not comments:
        return "_No automated concerns detected. Human review still required._"

    lines = ["## Automated PR Review Summary\n"]
    lines.append(f"**Total flagged items:** {len(comments)}\n")

    severity_order = [Severity.BLOCKING, Severity.CONCERN, Severity.SUGGESTION, Severity.INFO]
    by_severity: dict[Severity, list[Comment]] = {s: [] for s in severity_order}
    for c in comments:
        by_severity.setdefault(c.severity, []).append(c)

    for sev in severity_order:
        items = by_severity.get(sev, [])
        if not items:
            continue
        lines.append(f"\n### {sev.value.upper()} ({len(items)})\n")
        for c in items:
            loc = f"{c.file}:{c.line}" if c.line else c.file
            lines.append(f"- **{c.rule_id}** — {loc}")
            lines.append(f"  - {c.message}")
            lines.append("")

    lines.append("---\n")
    lines.append(
        "_This is an automated heuristic scan. It may produce false positives. "
        "Always apply human judgment before acting on suggestions._"
    )
    return "\n".join(lines)


def format_terminal(comments: list[Comment]) -> str:
    if not comments:
        return "No automated concerns detected.\n"
    lines = []
    for c in comments:
        loc = f"{c.file}:{c.line}" if c.line else c.file
        lines.append(f"[{c.severity.value.upper()}] {c.rule_id} {loc}\n  {c.message}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analyze a PR diff and emit structured review comments."
    )
    p.add_argument(
        "--diff",
        type=argparse.FileType("r", encoding="utf-8"),
        default=sys.stdin,
        help="Path to diff file (default: stdin)",
    )
    p.add_argument(
        "--format",
        choices=["json", "markdown", "terminal"],
        default="terminal",
        help="Output format",
    )
    p.add_argument(
        "--severity-at-least",
        choices=["info", "suggestion", "concern", "blocking"],
        default="info",
        help="Only emit comments at or above this severity",
    )
    p.add_argument(
        "--categories",
        nargs="+",
        choices=["security", "performance", "correctness", "style", "maintainability"],
        default=None,
        help="Filter to specific categories",
    )
    p.add_argument(
        "--exit-with-severity",
        choices=["blocking", "concern"],
        default=None,
        help="Exit non-zero if any comment meets or exceeds this severity",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    diff_text = args.diff.read()
    comments = analyze(diff_text)

    # Filter by severity
    severity_rank = {
        "info": 0,
        "suggestion": 1,
        "concern": 2,
        "blocking": 3,
    }
    min_rank = severity_rank[args.severity_at_least]
    comments = [c for c in comments if severity_rank[c.severity.value] >= min_rank]

    # Filter by category
    if args.categories:
        allowed = set(args.categories)
        comments = [c for c in comments if c.category.value in allowed]

    # Deduplicate exact same message on same file/line
    seen: set[tuple[str, str, int | None, str]] = set()
    deduped: list[Comment] = []
    for c in comments:
        key = (c.file, c.message, c.line, c.rule_id)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    comments = deduped

    # Output
    if args.format == "json":
        print(format_json(comments))
    elif args.format == "markdown":
        print(format_markdown(comments))
    else:
        print(format_terminal(comments))

    # Exit code handling
    if args.exit_with_severity:
        threshold = severity_rank[args.exit_with_severity]
        if any(severity_rank[c.severity.value] >= threshold for c in comments):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
