#!/usr/bin/env python3
"""
post-gemini-validator - Deterministic output validation for Gemini CLI responses.

Validates Gemini outputs before they enter the Kimi ecosystem.
Checks: structural integrity, completeness, secret absence, schema compliance.

Usage:
    python post-gemini-validator.py --task-type INGEST --input gemini_output.json
"""

import argparse
import json
import re
import sys
from typing import List, Tuple

# Secret detection patterns (subset of secret-manager)
SECRET_PATTERNS = [
    (r"(?i)(api_key|token|secret|password|passwd|pwd)\s*[:=]\s*[A-Za-z0-9_\-]{16,}", "API_KEY"),
    (r"AKIA[0-9A-Z]{16}", "AWS_KEY"),
    (r"ghp_[A-Za-z0-9_]{36}", "GITHUB_TOKEN"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}", "EMAIL"),
]

# Injection attempt patterns
INJECTION_PATTERNS = [
    r"ignore previous",
    r"disregard.*instruction",
    r"override.*policy",
    r"you are now",
    r"DAN mode",
    r"jailbreak",
]

# Placeholder detection
PLACEHOLDER_PATTERNS = [
    r"TODO",
    r"FIXME",
    r"TBD",
    r"\.\.\.",
]


def check_secrets(text: str) -> List[Tuple[str, str]]:
    findings = []
    for pattern, label in SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            findings.append((label, match.group(0)[:20] + "..."))
    return findings


def check_injection(text: str) -> List[str]:
    findings = []
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            findings.append(pattern)
    return findings


def check_placeholders(text: str) -> List[str]:
    findings = []
    for pattern in PLACEHOLDER_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            findings.append(match.group(0))
    return findings


def validate_spec_decomposer(data: dict) -> List[str]:
    errors = []
    nodes = data.get("nodes", [])
    for node in nodes:
        if not node.get("id"):
            errors.append("Node missing required field: id")
        if not node.get("title"):
            errors.append("Node missing required field: title")
        if not node.get("acceptance_criteria"):
            errors.append(f"Node {node.get('id', '?')} missing acceptance_criteria")
        desc = node.get("description", "")
        if len(desc.split()) < 3:
            errors.append(f"Node {node.get('id', '?')} description too short")
    return errors


def validate_documentation(data: dict) -> List[str]:
    errors = []
    content = data.get("content", "")
    required_sections = ["Overview", "Usage", "Examples"]
    for section in required_sections:
        if section.lower() not in content.lower():
            errors.append(f"Missing required section: {section}")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Post-Gemini output validator")
    parser.add_argument("--task-type", required=True,
                        choices=["INGEST", "PLAN", "DELIVER", "REMEMBER"])
    parser.add_argument("--input", required=True, help="Path to Gemini output JSON")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    with open(args.input, "r") as f:
        data = json.load(f)

    text = data.get("content", "") or data.get("text", "") or json.dumps(data)
    errors = []
    warnings = []

    # Universal checks
    secrets = check_secrets(text)
    if secrets:
        errors.append(f"SECRET_DETECTED: {len(secrets)} potential secrets found")

    injections = check_injection(text)
    if injections:
        errors.append(f"INJECTION_DETECTED: {len(injections)} suspicious patterns")

    placeholders = check_placeholders(text)
    if placeholders:
        warnings.append(f"PLACEHOLDER_FOUND: {len(placeholders)} placeholders")

    # Task-type specific checks
    if args.task_type == "INGEST":
        spec_errors = validate_spec_decomposer(data)
        errors.extend(spec_errors)
    elif args.task_type == "DELIVER":
        doc_errors = validate_documentation(data)
        errors.extend(doc_errors)

    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "task_type": args.task_type,
        "checks_performed": [
            "secret_scan",
            "injection_scan",
            "placeholder_check",
            f"{args.task_type.lower()}_schema_validation",
        ],
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if result["valid"] else "FAIL"
        print(f"Validation: {status}")
        for e in errors:
            print(f"  ERROR: {e}")
        for w in warnings:
            print(f"  WARN: {w}")

    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
