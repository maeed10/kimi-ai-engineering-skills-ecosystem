#!/usr/bin/env python3
"""
scrub_output.py — scan and redact secrets from tool output.

Usage:
    python scrub_output.py < input.txt
    python scrub_output.py --input-file output.log --audit-log /var/log/secret_audit.jsonl
    python scrub_output.py --policy-yaml /etc/gateway/scrubber_rules.yaml

Exit codes:
    0 — no secrets found
    1 — secrets were redacted (stdout contains [REDACTED:...] markers)
    2 — high-entropy secret detected (alert level)
    3 — usage / configuration error
"""

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, NamedTuple, Optional, TextIO, Tuple


class MatchResult(NamedTuple):
    start: int
    end: int
    secret_type: str
    matched_text: str
    severity: str  # "redact" | "flag" | "alert"


# ---------------------------------------------------------------------------
# Default regex rules (override via --policy-yaml)
# ---------------------------------------------------------------------------
DEFAULT_RULES: List[Dict[str, str]] = [
    {"name": "github_token", "pattern": r"gh[pousr]_[A-Za-z0-9_]{36,251}", "multiline": "false"},
    {"name": "aws_access_key", "pattern": r"AKIA[0-9A-Z]{16}", "multiline": "false"},
    {
        "name": "aws_secret_key",
        "pattern": r"(?i)aws(.{0,20})?[^0-9A-Za-z/+=]{0,1}[0-9A-Za-z/+=]{40}[^0-9A-Za-z/+=]{0,1}",
        "multiline": "false",
    },
    {
        "name": "api_key_literal",
        "pattern": r"(?i)(api[_-]?key|apikey|api[_-]?secret)[\s]*[=:]+[\s]*[\"']?[a-zA-Z0-9_\-]{16,128}[\"']?",
        "multiline": "false",
    },
    {"name": "private_key", "pattern": r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?-----END (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "multiline": "true"},
    {"name": "bearer_token", "pattern": r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{20,}", "multiline": "false"},
    {"name": "url_with_creds", "pattern": r"[a-zA-Z][a-zA-Z0-9+\-.]*://[^:]+:[^@]+@[^/]+/", "multiline": "false"},
]

# ---------------------------------------------------------------------------
# Entropy thresholds
# ---------------------------------------------------------------------------
ENTROPY_RULES = [
    {"min_length": 32, "max_length": 48, "min_entropy": 4.5, "action": "flag"},
    {"min_length": 48, "max_length": 64, "min_entropy": 5.0, "action": "redact"},
    {"min_length": 64, "max_length": None, "min_entropy": 5.5, "action": "alert"},
]

# Simple dictionary of common English words to skip (lowercase)
COMMON_WORDS = {
    "password", "secret", "token", "key", "admin", "root", "user", "login",
    "default", "example", "test", "sample", "dummy", "placeholder",
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def shannon_entropy(s: str) -> float:
    """Return Shannon entropy in bits per character."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def is_repeating_pattern(s: str) -> bool:
    """Return True if string is a trivial repeating pattern (e.g., 'ababab' or 'aaaa')."""
    if len(set(s)) == 1:
        return True
    if len(s) >= 4:
        for period in range(1, min(5, len(s) // 2 + 1)):
            if s[:period] * (len(s) // period) == s[: len(s) // period * period]:
                return True
    return False


def is_uuid(s: str) -> bool:
    """Return True if string looks like a UUID v4."""
    return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", s))


def check_entropy(text: str) -> List[MatchResult]:
    """Find high-entropy substrings that may be encoded secrets."""
    matches: List[MatchResult] = []
    # Tokenize on non-alphanumeric boundaries to find candidate strings
    for token in re.finditer(r"[A-Za-z0-9+/=_~!@#$%^&*\-]{16,}", text):
        candidate = token.group(0)
        if candidate.lower() in COMMON_WORDS:
            continue
        if is_repeating_pattern(candidate):
            continue
        if is_uuid(candidate):
            continue

        ent = shannon_entropy(candidate)
        for rule in ENTROPY_RULES:
            min_len = rule["min_length"]
            max_len = rule.get("max_length")
            if len(candidate) < min_len:
                continue
            if max_len is not None and len(candidate) > max_len:
                continue
            if ent >= rule["min_entropy"]:
                matches.append(
                    MatchResult(
                        start=token.start(),
                        end=token.end(),
                        secret_type="high_entropy",
                        matched_text=candidate,
                        severity=rule["action"],
                    )
                )
                break
    return matches


def compile_rules(rules: List[Dict[str, str]]) -> List[Tuple[str, re.Pattern]]:
    """Compile regex rules into (name, compiled_pattern) pairs."""
    compiled = []
    for rule in rules:
        flags = re.IGNORECASE
        if rule.get("multiline", "false").lower() == "true":
            flags |= re.DOTALL
        try:
            compiled.append((rule["name"], re.compile(rule["pattern"], flags)))
        except re.error as exc:
            print(f"ERROR: Invalid regex in rule '{rule.get('name', '?')}': {exc}", file=sys.stderr)
            sys.exit(3)
    return compiled


def scan_text(text: str, compiled_rules: List[Tuple[str, re.Pattern]]) -> List[MatchResult]:
    """Run regex + entropy scan on text and return all matches."""
    all_matches: List[MatchResult] = []

    # Regex pass
    for name, pattern in compiled_rules:
        for m in pattern.finditer(text):
            all_matches.append(
                MatchResult(
                    start=m.start(),
                    end=m.end(),
                    secret_type=name,
                    matched_text=m.group(0),
                    severity="redact",
                )
            )

    # Entropy pass
    all_matches.extend(check_entropy(text))

    # Sort by start position; longer matches win at same start
    all_matches.sort(key=lambda x: (x.start, -(x.end - x.start)))

    # De-duplicate overlapping matches (keep earliest, longest)
    filtered: List[MatchResult] = []
    last_end = -1
    for match in all_matches:
        if match.start >= last_end:
            filtered.append(match)
            last_end = match.end

    return filtered


def redact_text(text: str, matches: List[MatchResult]) -> str:
    """Replace matched secret substrings with [REDACTED:type]."""
    buf = []
    pos = 0
    for match in matches:
        buf.append(text[pos : match.start])
        buf.append(f"[REDACTED:{match.secret_type}]")
        pos = match.end
    buf.append(text[pos:])
    return "".join(buf)


def write_audit_event(
    stream: Optional[TextIO],
    timestamp: str,
    secret_type: str,
    severity: str,
    channel: str,
    redaction_count: int,
) -> None:
    """Append a JSONL audit event if stream is provided."""
    if stream is None:
        return
    event = {
        "ts": timestamp,
        "secret_type": secret_type,
        "severity": severity,
        "channel": channel,
        "redaction_count": redaction_count,
    }
    stream.write(json.dumps(event) + "\n")
    stream.flush()


def load_policy_yaml(path: str) -> Tuple[List[Dict[str, str]], List[Dict]]:
    """Load rules from a YAML policy file. Returns (regex_rules, entropy_rules)."""
    try:
        import yaml
    except ImportError:
        print("ERROR: PyYAML is required to load --policy-yaml.", file=sys.stderr)
        sys.exit(3)

    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    regex_rules = doc.get("scrubber", {}).get("regex_rules", DEFAULT_RULES)
    entropy_rules = doc.get("scrubber", {}).get("entropy_rules", ENTROPY_RULES)
    return regex_rules, entropy_rules


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Scan and redact secrets from tool output.")
    parser.add_argument("--input-file", "-i", help="File to read (default: stdin)")
    parser.add_argument("--output-file", "-o", help="File to write redacted output (default: stdout)")
    parser.add_argument("--audit-log", "-a", help="JSONL audit log path")
    parser.add_argument("--policy-yaml", "-p", help="YAML policy file overriding built-in rules")
    parser.add_argument("--channel", "-c", default="unknown", help="Output channel name (stdout/stderr/tool_arg)")
    args = parser.parse_args()

    regex_rules = DEFAULT_RULES
    global ENTROPY_RULES
    if args.policy_yaml:
        regex_rules, loaded_entropy = load_policy_yaml(args.policy_yaml)
        ENTROPY_RULES = loaded_entropy

    compiled = compile_rules(regex_rules)

    # Read input
    if args.input_file:
        with open(args.input_file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    # Scan
    matches = scan_text(text, compiled)

    if not matches:
        # No secrets found — pass through unchanged
        out_stream = open(args.output_file, "w", encoding="utf-8") if args.output_file else sys.stdout
        out_stream.write(text)
        if args.output_file:
            out_stream.close()
        return 0

    # Redact
    redacted = redact_text(text, matches)

    # Determine exit severity
    severities = {m.severity for m in matches}
    exit_code = 1
    if "alert" in severities:
        exit_code = 2

    # Write redacted output
    out_stream = open(args.output_file, "w", encoding="utf-8") if args.output_file else sys.stdout
    out_stream.write(redacted)
    if args.output_file:
        out_stream.close()

    # Audit logging
    audit_stream: Optional[TextIO] = None
    if args.audit_log:
        audit_stream = open(args.audit_log, "a", encoding="utf-8")

    ts = datetime.now(timezone.utc).isoformat()
    severity_counts: Dict[str, int] = {}
    for m in matches:
        severity_counts[m.secret_type] = severity_counts.get(m.secret_type, 0) + 1
    for secret_type, count in severity_counts.items():
        sev = next(m.severity for m in matches if m.secret_type == secret_type)
        write_audit_event(audit_stream, ts, secret_type, sev, args.channel, count)

    if audit_stream:
        audit_stream.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
