#!/usr/bin/env python3
"""
scan-secrets.py

Secret scanner for generated CI/CD pipeline YAML.
Integrates trufflehog-style and detect-secrets-style heuristics
to block embedded credentials in pipeline output.

Usage:
  python scan-secrets.py --file ./.github/workflows/ci.yml
  python scan-secrets.py --file ./.github/workflows/ci.yml --remediate --output ./.github/workflows/ci-clean.yml
  python scan-secrets.py --stdin --format json < pipeline.yml
  python scan-secrets.py --directory ./.github/workflows/

Exit codes:
  0 — No secrets detected
  1 — Secrets detected (blocking)
  2 — Invalid arguments or unreadable file
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Secret detection patterns
# ---------------------------------------------------------------------------

SECRET_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # AWS Access Key ID
    (
        "AWS Access Key ID",
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ),
    # AWS Secret Access Key (generic long base64-ish strings assigned to env vars)
    (
        "AWS Secret Access Key",
        re.compile(r"['\"]?aws_secret_access_key['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"),
    ),
    # Generic API keys assigned to variables
    (
        "Generic API Key",
        re.compile(
            r"['\"]?(?:api[_\-\s]?key|apikey|api[_\-\s]?token|auth[_\-\s]?token)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?",
            re.IGNORECASE,
        ),
    ),
    # Private keys (RSA, EC, DSA, OPENSSH, PGP)
    (
        "Private Key",
        re.compile(
            r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
            re.IGNORECASE,
        ),
    ),
    # GitHub Personal Access Token (classic or fine-grained prefixes)
    (
        "GitHub Token",
        re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"),
    ),
    # GitLab Personal Access Token
    (
        "GitLab Token",
        re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),
    ),
    # Slack Token
    (
        "Slack Token",
        re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}(-[A-Za-z0-9]{24})?"),
    ),
    # Slack Webhook
    (
        "Slack Webhook",
        re.compile(r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]{8}/B[a-zA-Z0-9_]{8,}/[a-zA-Z0-9_]{24}"),
    ),
    # Generic password assignments
    (
        "Password Assignment",
        re.compile(
            r"['\"]?(?:password|passwd|pwd)['\"]?\s*[:=]\s*['\"]?([^\s'\"]{8,})['\"]?",
            re.IGNORECASE,
        ),
    ),
    # Bearer token in headers or env
    (
        "Bearer Token",
        re.compile(
            r"['\"]?[Bb]earer\s+['\"]?([A-Za-z0-9_\-\.]{20,})['\"]?",
        ),
    ),
    # Generic high-entropy secret-like strings in env values
    (
        "High-Entropy Secret",
        re.compile(
            r"(?:SECRET|TOKEN|KEY|PASSWORD|CREDENTIAL)\s*=\s*['\"]?([A-Za-z0-9+/=]{20,})['\"]?",
            re.IGNORECASE,
        ),
    ),
    # Base64 blobs that look like secrets after certain keywords
    (
        "Base64 Secret Blob",
        re.compile(
            r"['\"]?(?:secret|token|key|credential)['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9+/]{40,}={0,2})['\"]?",
            re.IGNORECASE,
        ),
    ),
    # JWT tokens (three base64url segments)
    (
        "JWT Token",
        re.compile(r"eyJ[A-Za-z0-9_\-]*\.eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*"),
    ),
    # Docker registry auth
    (
        "Docker Registry Auth",
        re.compile(
            r"['\"]?docker[_\-\s]?auth['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9+/]{20,}={0,2})['\"]?",
            re.IGNORECASE,
        ),
    ),
    # Kubernetes service account token
    (
        "Kubernetes SA Token",
        re.compile(r"eyJ[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*\.[A-Za-z0-9_\-]*"),
    ),
    # NPM token
    (
        "NPM Token",
        re.compile(r"npm_[A-Za-z0-9]{36}"),
    ),
    # PyPI API token
    (
        "PyPI Token",
        re.compile(r"pypi-[A-Za-z0-9_\-]{26,}"),
    ),
]

# Keywords that indicate a value is actually a safe placeholder / template
SAFE_PLACEHOLDER_PATTERNS: List[re.Pattern] = [
    re.compile(r"\$\{\{?\s*secrets\."),        # ${{ secrets.XXX }}
    re.compile(r"\$\{\{?\s*env\."),              # ${{ env.XXX }}
    re.compile(r"\$\{\{?\s*vars\."),             # ${{ vars.XXX }}
    re.compile(r"\$\{?[A-Z_]+\}?"),             # ${VAR_NAME} or $VAR_NAME
    re.compile(r"\$\w+"),                        # $var shell variable
    re.compile(r"<\s*[\w\-]+\s*>"),             # <placeholder>
    re.compile(r"\{\{\s*[\w\-]+\s*\}\}"),      # {{ placeholder }}
    re.compile(r"placeholder", re.IGNORECASE),
    re.compile(r"YOUR_", re.IGNORECASE),
    re.compile(r"INSERT_", re.IGNORECASE),
    re.compile(r"CHANGEME", re.IGNORECASE),
    re.compile(r"EXAMPLE", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Core scanning logic
# ---------------------------------------------------------------------------

def is_placeholder(value: str) -> bool:
    """Return True if the value is a recognized safe placeholder."""
    for pat in SAFE_PLACEHOLDER_PATTERNS:
        if pat.search(value):
            return True
    return False


def scan_text(text: str, file_label: str = "<stdin>") -> List[Dict]:
    """Scan text for secrets. Return a list of findings."""
    findings: List[Dict] = []
    lines = text.splitlines()

    for line_no, line in enumerate(lines, start=1):
        for name, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                matched_text = match.group(0)
                # If the entire match is a placeholder, skip
                if is_placeholder(matched_text):
                    continue
                # Also try to extract capture group 1 if present and check it
                try:
                    captured = match.group(1)
                    if captured and is_placeholder(captured):
                        continue
                except IndexError:
                    pass

                # Additional entropy / heuristic filter for generic matches
                if name in ("Generic API Key", "High-Entropy Secret", "Base64 Secret Blob"):
                    # Skip if looks like a short word or common non-secret
                    if len(matched_text) < 20:
                        continue
                    # Skip hex color codes or UUID-like strings without enough entropy variety
                    if re.fullmatch(r"[0-9a-f\-]+", matched_text, re.IGNORECASE):
                        continue

                findings.append(
                    {
                        "file": file_label,
                        "line": line_no,
                        "type": name,
                        "match": matched_text,
                        "line_text": line.rstrip(),
                    }
                )

    return findings


def remediate_text(text: str) -> Tuple[str, List[Dict]]:
    """
    Replace detected secrets with environment-variable placeholders.
    Returns (cleaned_text, list_of_replacements).
    """
    replacements: List[Dict] = []
    cleaned = text
    seen_spans: set = set()

    # We do a single pass per pattern type, replacing with a unique placeholder
    for name, pattern in SECRET_PATTERNS:
        counter = 1
        for match in pattern.finditer(cleaned):
            start, end = match.span()
            # Skip overlaps
            if any(start < e and end > s for s, e in seen_spans):
                continue
            matched_text = match.group(0)
            if is_placeholder(matched_text):
                continue
            try:
                captured = match.group(1)
                if captured and is_placeholder(captured):
                    continue
            except IndexError:
                pass

            placeholder = f"${{{{ secrets.DETECTED_{name.upper().replace(' ', '_')}_{counter} }}}}"
            cleaned = cleaned[:start] + placeholder + cleaned[end:]
            replacements.append(
                {
                    "type": name,
                    "original": matched_text,
                    "placeholder": placeholder,
                    "position": start,
                }
            )
            seen_spans.add((start, start + len(placeholder)))
            counter += 1
            # Re-scan because string length changed
            # For simplicity we break after one replace per pattern and re-run outer logic
            # but here we just continue with updated string; however regex iterators become invalid.
            # To keep it simple, we restart scanning on the new string after each replacement.
            return remediate_text(cleaned)

    return cleaned, replacements


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scan generated CI/CD YAML for embedded secrets")
    parser.add_argument("--file", "-f", help="Path to YAML file to scan")
    parser.add_argument("--directory", "-d", help="Directory of YAML files to scan recursively")
    parser.add_argument("--stdin", action="store_true", help="Read YAML from stdin")
    parser.add_argument("--remediate", action="store_true", help="Auto-replace secrets with placeholders")
    parser.add_argument("--output", "-o", help="Output path for remediated file (requires --remediate)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--strict", action="store_true", default=True, help="Treat findings as blocking (default true)")
    args = parser.parse_args()

    if not any([args.file, args.directory, args.stdin]):
        parser.print_help()
        sys.exit(2)

    if args.remediate and not args.output and not args.stdin and not args.file:
        print("ERROR: --remediate requires --output or --file (writes to --output).", file=sys.stderr)
        sys.exit(2)

    all_findings: List[Dict] = []
    files_scanned: List[str] = []

    if args.stdin:
        text = sys.stdin.read()
        files_scanned.append("<stdin>")
        findings = scan_text(text, "<stdin>")
        all_findings.extend(findings)
        if args.remediate:
            cleaned, replacements = remediate_text(text)
            if args.output:
                Path(args.output).write_text(cleaned, encoding="utf-8")
                print(f"Remediated output written to {args.output}")
            else:
                print(cleaned)
            if replacements and args.format == "text":
                print(f"\nRemediated {len(replacements)} secret(s) in <stdin>:")
                for r in replacements:
                    print(f"  [{r['type']}] replaced with {r['placeholder']}")

    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            sys.exit(2)
        text = path.read_text(encoding="utf-8")
        files_scanned.append(str(path))
        findings = scan_text(text, str(path))
        all_findings.extend(findings)
        if args.remediate:
            cleaned, replacements = remediate_text(text)
            out_path = Path(args.output) if args.output else path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(cleaned, encoding="utf-8")
            print(f"Remediated output written to {out_path}")
            if replacements and args.format == "text":
                print(f"\nRemediated {len(replacements)} secret(s) in {path}:")
                for r in replacements:
                    print(f"  [{r['type']}] replaced with {r['placeholder']}")

    elif args.directory:
        dir_path = Path(args.directory)
        if not dir_path.is_dir():
            print(f"ERROR: Not a directory: {dir_path}", file=sys.stderr)
            sys.exit(2)
        for yaml_file in (
            sorted(dir_path.rglob("*.yml"))
            + sorted(dir_path.rglob("*.yaml"))
            + sorted(dir_path.rglob("Jenkinsfile*"))
            + sorted(dir_path.rglob("*.groovy"))
        ):
            text = yaml_file.read_text(encoding="utf-8")
            files_scanned.append(str(yaml_file))
            findings = scan_text(text, str(yaml_file))
            all_findings.extend(findings)

    # Output findings
    if args.format == "json":
        print(json.dumps(all_findings, indent=2))
    else:
        if all_findings:
            print(f"\n{'=' * 60}")
            print(f"SECRET SCAN RESULTS: {len(all_findings)} finding(s) in {len(files_scanned)} file(s)")
            print(f"{'=' * 60}")
            for f in all_findings:
                print(f"\n  File : {f['file']}")
                print(f"  Line : {f['line']}")
                print(f"  Type : {f['type']}")
                print(f"  Match: {f['match']}")
                print(f"  Text : {f['line_text'].strip()}")
        else:
            print(f"No secrets detected in {len(files_scanned)} file(s).")

    if args.strict and all_findings:
        print("\nBLOCKED: Secrets detected in generated pipeline output. Generation aborted.", file=sys.stderr)
        print("ACTION: Use platform-native secret stores (GitHub Secrets, GitLab CI/CD Variables, Jenkins Credentials).", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
