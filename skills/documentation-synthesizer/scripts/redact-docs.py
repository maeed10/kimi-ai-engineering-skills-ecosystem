#!/usr/bin/env python3
"""
redact-docs.py — Documentation Secret Scanner & Redactor

Scans generated .md files for secret patterns (AWS keys, GitHub tokens,
database passwords, generic API keys). Uses git-secrets / truffleHog-style
patterns for detection. Reports findings with file paths and line numbers.
Auto-redacts with [REDACTED] placeholder.

Never modifies files without reporting what was changed.
Requires --confirm for actual writes; default mode is report-only.

Usage:
    python redact-docs.py --path docs/ --report
    python redact-docs.py --path docs/ --confirm
    python redact-docs.py --path README.md --json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Set


class Finding(NamedTuple):
    file_path: str
    line_number: int
    column_start: int
    column_end: int
    match_text: str
    pattern_name: str
    replacement: str


# ── Secret Detection Patterns (git-secrets / truffleHog inspired) ──────────────

PATTERNS: Dict[str, re.Pattern] = {
    "AWS_ACCESS_KEY_ID": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "AWS_SECRET_KEY": re.compile(
        r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*["
        r"']?[A-Za-z0-9/+=]{40}["']?"
    ),
    "GITHUB_TOKEN": re.compile(
        r"\bghp_[A-Za-z0-9_]{36}\b|\bgithub_pat_[A-Za-z0-9_]{22}_[A-Za-z0-9_]{59}\b"
    ),
    "DATABASE_PASSWORD": re.compile(
        r"(?i)(?:db[_-]?password|database[_-]?password|db[_-]?pass|mysql[_-]?password|"
        r"postgres[_-]?password|mongo[_-]?password)\s*[:=]\s*["
        r"']?[^\s\"'\']{8,}["']?"
    ),
    "GENERIC_API_KEY": re.compile(
        r"(?i)(?:api[_-]?key|apikey|token|secret|passwd|pwd|auth[_-]?token)\s*[:=]\s*["
        r"']?[A-Za-z0-9_\-+/=]{16,}["']?"
    ),
    "PRIVATE_KEY": re.compile(
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    ),
    "CONNECTION_STRING": re.compile(
        r"(?i)(?:mongodb|mysql|postgres|postgresql|redis)://[^:]+:[^@]+@"
    ),
    "SLACK_TOKEN": re.compile(
        r"\bxox[baprs]-[0-9]{10,13}-[0-9]{10,13}(?:-[a-zA-Z0-9]{24})?\b"
    ),
    "SENDGRID_KEY": re.compile(r"\bSG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}\b"),
    "STRIPE_KEY": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b"),
    "JWT_SECRET": re.compile(
        r"(?i)(?:jwt[_-]?secret|jwt[_-]?key|jwt[_-]?token)\s*[:=]\s*["
        r"']?[A-Za-z0-9_\-+/=]{16,}["']?"
    ),
}

# Patterns that should be allowed (placeholders / examples)
ALLOWLIST: Set[str] = {
    "YOUR_API_KEY",
    "YOUR-API-KEY",
    "EXAMPLE_TOKEN",
    "example@domain.com",
    "user@example.com",
    "test@localhost",
    "password123",
    "changeme",
    "placeholder",
    "xxxxxxxx",
    "XXXXXXX",
    "<your-token-here>",
}


def is_allowlisted(match_text: str) -> bool:
    """Check if the match is a known safe placeholder."""
    normalized = match_text.strip("\"'").upper()
    for allowed in ALLOWLIST:
        if allowed.upper() in normalized or normalized in allowed.upper():
            return True
    return False


def scan_line(
    line: str, line_number: int, file_path: str
) -> List[Finding]:
    """Scan a single line for all secret patterns."""
    findings: List[Finding] = []

    for pattern_name, pattern in PATTERNS.items():
        for match in pattern.finditer(line):
            match_text = match.group(0)

            if is_allowlisted(match_text):
                continue

            finding = Finding(
                file_path=file_path,
                line_number=line_number,
                column_start=match.start(),
                column_end=match.end(),
                match_text=match_text,
                pattern_name=pattern_name,
                replacement="[REDACTED]",
            )
            findings.append(finding)

    # Deduplicate overlapping findings (keep the longer match)
    findings.sort(key=lambda f: (f.column_start, -(f.column_end - f.column_start)))
    deduped: List[Finding] = []
    for f in findings:
        if not any(
            existing.column_start <= f.column_start < existing.column_end
            or existing.column_start < f.column_end <= existing.column_end
            for existing in deduped
        ):
            deduped.append(f)

    return deduped


def redact_line(line: str, findings: List[Finding]) -> str:
    """Apply redactions to a line, right-to-left to preserve indices."""
    result = line
    for f in sorted(findings, key=lambda x: x.column_start, reverse=True):
        result = (
            result[: f.column_start] + f.replacement + result[f.column_end :]
        )
    return result


def scan_file(file_path: Path, report_only: bool = True) -> Tuple[int, List[Finding]]:
    """
    Scan a single markdown file.
    Returns (files_modified, findings).
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0, []

    lines = content.splitlines(keepends=True)
    modified = False
    new_lines: List[str] = []
    all_findings: List[Finding] = []

    for line_number, line in enumerate(lines, start=1):
        findings = scan_line(line, line_number, str(file_path))
        if findings:
            all_findings.extend(findings)
            if not report_only:
                line = redact_line(line, findings)
                modified = True
        new_lines.append(line)

    if modified and not report_only:
        temp_path = file_path.with_suffix(".md.tmp")
        temp_path.write_text("".join(new_lines), encoding="utf-8")
        temp_path.replace(file_path)
        return 1, all_findings

    return 0, all_findings


def scan_docs(path: Path, report_only: bool = True) -> Dict:
    """
    Scan markdown files under path (file or directory).
    Returns a structured report dict.
    """
    findings: List[Finding] = []
    files_scanned = 0
    files_modified = 0
    files_with_issues = 0

    targets: List[Path] = []
    if path.is_file():
        targets = [path]
    elif path.is_dir():
        targets = list(path.rglob("*.md"))
    else:
        raise ValueError(f"Path is not a file or directory: {path}")

    for md_file in targets:
        files_scanned += 1
        modified, file_findings = scan_file(md_file, report_only=report_only)
        if file_findings:
            files_with_issues += 1
            findings.extend(file_findings)
        files_modified += modified

    return {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "scan_path": str(path.resolve()),
        "files_scanned": files_scanned,
        "files_with_issues": files_with_issues,
        "files_modified": files_modified,
        "total_findings": len(findings),
        "report_only": report_only,
        "findings": [
            {
                "file": f.file_path,
                "line": f.line_number,
                "column_start": f.column_start,
                "column_end": f.column_end,
                "match": f.match_text,
                "type": f.pattern_name,
                "replacement": f.replacement,
            }
            for f in findings
        ],
    }


def print_report(report: Dict) -> None:
    """Print human-readable report to stdout."""
    print("=" * 60)
    print("DOCUMENTATION SECRET SCAN REPORT")
    print("=" * 60)
    print(f"Timestamp:      {report['scan_timestamp']}")
    print(f"Scan path:      {report['scan_path']}")
    print(f"Files scanned:  {report['files_scanned']}")
    print(f"Files flagged:  {report['files_with_issues']}")
    print(f"Total findings: {report['total_findings']}")
    print(f"Mode:           {'REPORT-ONLY' if report['report_only'] else 'REDACT'}")
    print("-" * 60)

    if not report["findings"]:
        print("No secrets detected in documentation.")
        print("=" * 60)
        return

    by_file: Dict[str, List[Dict]] = {}
    for f in report["findings"]:
        by_file.setdefault(f["file"], []).append(f)

    for file_path, file_findings in sorted(by_file.items()):
        print(f"\n  {file_path}")
        for f in file_findings:
            preview = f["match"]
            if len(preview) > 50:
                preview = preview[:47] + "..."
            print(
                f"    Line {f['line']:>4}  [{f['type']:<18}]  {preview}"
            )
            print(f"      → Replace with: {f['replacement']}")

    print("\n" + "=" * 60)
    if report["report_only"]:
        print("Run with --confirm to apply redactions.")
        print("BLOCK COMMIT until findings are resolved.")
    else:
        print(f"Redactions applied: {report['files_modified']} file(s) modified.")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan documentation for secrets and optionally redact."
    )
    parser.add_argument(
        "--path", required=True, help="Path to documentation file or directory"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        default=True,
        help="Report findings without modifying files (default)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm redaction: modify files in place",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit report as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    target_path = Path(args.path)
    if not target_path.exists():
        print(f"Error: path does not exist: {target_path}", file=sys.stderr)
        return 1

    report_only = not args.confirm
    report = scan_docs(target_path, report_only=report_only)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    # Exit code: 0 = clean, 1 = findings detected (CI block)
    return 1 if report["total_findings"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
