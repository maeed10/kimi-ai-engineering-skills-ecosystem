#!/usr/bin/env python3
"""
sanitize-vault.py — Privacy Sanitization Protocol for Obsidian Vaults

Scans all .md files in a vault for PII patterns (SSN, credit cards, emails,
API keys, tokens, connection strings). Reports findings with file paths and
line numbers. Auto-redacts with [REDACTED_<TYPE>] placeholders.

NEVER modifies files without reporting what was changed.
Requires --confirm for actual writes; default mode is report-only.

Usage:
    python sanitize-vault.py --vault /path/to/vault --report
    python sanitize-vault.py --vault /path/to/vault --confirm
    python sanitize-vault.py --vault /path/to/vault --full-audit
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple


class Finding(NamedTuple):
    file_path: str
    line_number: int
    column_start: int
    column_end: int
    match_text: str
    pattern_name: str
    replacement: str


# ── Detection Patterns ───────────────────────────────────────────────────────

PATTERNS: Dict[str, re.Pattern] = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b"),
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),
    "AWS_ACCESS_KEY_ID": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(
        r"\bghp_[A-Za-z0-9_]{36}\b|\bgithub_pat_[A-Za-z0-9_]{22}_[A-Za-z0-9_]{59}\b"
    ),
    "GENERIC_API_KEY": re.compile(
        r"(?i)(?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*["
        r"']?[A-Za-z0-9_\-]{16,}["']?"
    ),
    "AWS_SECRET_KEY": re.compile(
        r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*["
        r"']?[A-Za-z0-9/+=]{40}["']?"
    ),
    "CONNECTION_STRING": re.compile(
        r"(?i)(?:mongodb|mysql|postgres|redis|postgresql)://[^\s\"]+"
    ),
}


def luhn_check(digits: str) -> bool:
    """Validate a sequence of digits using the Luhn algorithm."""
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def is_credit_card(match_text: str) -> bool:
    """Check if a digit sequence is a valid credit card number."""
    digits = re.sub(r"\D", "", match_text)
    if not (13 <= len(digits) <= 19):
        return False
    # Quick prefix checks for major cards
    prefixes = [
        ("4",),  # Visa
        ("51", "52", "53", "54", "55"),  # Mastercard
        ("34", "37"),  # Amex
        ("6011",),  # Discover
        ("65",),
    ]
    valid_prefix = any(
        digits.startswith(p) for group in prefixes for p in group
    )
    if not valid_prefix:
        return False
    return luhn_check(digits)


def scan_line(
    line: str, line_number: int, file_path: str
) -> List[Finding]:
    """Scan a single line for all configured patterns."""
    findings: List[Finding] = []

    for pattern_name, pattern in PATTERNS.items():
        for match in pattern.finditer(line):
            match_text = match.group(0)

            # Credit-card check for digit-heavy matches
            if pattern_name == "GENERIC_API_KEY":
                digit_core = re.sub(r"\D", "", match_text)
                if 13 <= len(digit_core) <= 19 and is_credit_card(match_text):
                    # Let the dedicated credit-card logic handle it
                    continue

            if pattern_name == "CONNECTION_STRING":
                # Check for embedded credentials in connection string
                if "://" in match_text:
                    # e.g., postgres://user:PASSWORD@host
                    pass  # Always flag connection strings with creds

            finding = Finding(
                file_path=file_path,
                line_number=line_number,
                column_start=match.start(),
                column_end=match.end(),
                match_text=match_text,
                pattern_name=pattern_name,
                replacement=f"[REDACTED_{pattern_name}]",
            )
            findings.append(finding)

    # Dedicated credit-card scan (separate from regex patterns to avoid false positives)
    cc_pattern = re.compile(r"\b(?:\d{4}[- ]?){3,4}\d{1,4}\b|\b\d{13,19}\b")
    for match in cc_pattern.finditer(line):
        match_text = match.group(0)
        if is_credit_card(match_text):
            finding = Finding(
                file_path=file_path,
                line_number=line_number,
                column_start=match.start(),
                column_end=match.end(),
                match_text=match_text,
                pattern_name="CREDIT_CARD",
                replacement="[REDACTED_CREDIT_CARD]",
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
        # Atomic write: temp file then rename
        temp_path = file_path.with_suffix(".md.tmp")
        temp_path.write_text("".join(new_lines), encoding="utf-8")
        temp_path.replace(file_path)
        return 1, all_findings

    return 0, all_findings


def scan_vault(vault_path: Path, report_only: bool = True) -> Dict:
    """
    Scan all .md files under vault_path.
    Returns a structured report dict.
    """
    findings: List[Finding] = []
    files_scanned = 0
    files_modified = 0
    files_with_issues = 0

    for md_file in vault_path.rglob("*.md"):
        files_scanned += 1
        modified, file_findings = scan_file(md_file, report_only=report_only)
        if file_findings:
            files_with_issues += 1
            findings.extend(file_findings)
        files_modified += modified

    return {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "vault_path": str(vault_path.resolve()),
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
    print("VAULT SANITIZATION REPORT")
    print("=" * 60)
    print(f"Timestamp:     {report['scan_timestamp']}")
    print(f"Vault path:    {report['vault_path']}")
    print(f"Files scanned: {report['files_scanned']}")
    print(f"Files flagged: {report['files_with_issues']}")
    print(f"Total findings: {report['total_findings']}")
    print(f"Mode:          {'REPORT-ONLY' if report['report_only'] else 'REDACT'}")
    print("-" * 60)

    if not report["findings"]:
        print("No sensitive data detected.")
        return

    # Group by file
    by_file: Dict[str, List[Dict]] = {}
    for f in report["findings"]:
        by_file.setdefault(f["file"], []).append(f)

    for file_path, file_findings in sorted(by_file.items()):
        print(f"\n  {file_path}")
        for f in file_findings:
            preview = f["match"]
            if len(preview) > 40:
                preview = preview[:37] + "..."
            print(
                f"    Line {f['line']:>4}, Col {f['column_start']:>3}-{f['column_end']:<3}  "
                f"[{f['type']:<15}]  {preview}"
            )
            print(f"      → Replace with: {f['replacement']}")

    print("\n" + "=" * 60)
    if report["report_only"]:
        print("Run with --confirm to apply redactions.")
    else:
        print(f"Redactions applied: {report['files_modified']} file(s) modified.")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan Obsidian vault for PII/secrets and optionally redact."
    )
    parser.add_argument(
        "--vault", required=True, help="Path to the Obsidian vault directory"
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
        "--full-audit",
        action="store_true",
        help="Include full audit metadata in JSON output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit report as JSON instead of human-readable text",
    )
    args = parser.parse_args()

    vault_path = Path(args.vault)
    if not vault_path.is_dir():
        print(f"Error: not a directory: {vault_path}", file=sys.stderr)
        return 1

    report_only = not args.confirm
    report = scan_vault(vault_path, report_only=report_only)

    if args.json or args.full_audit:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)

    # Exit code: 0 = clean, 1 = findings detected (for CI integration)
    return 1 if report["total_findings"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
