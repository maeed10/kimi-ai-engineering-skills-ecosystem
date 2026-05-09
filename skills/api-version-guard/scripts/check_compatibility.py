#!/usr/bin/env python3
"""
OpenAPI Compatibility Checker

Compares two OpenAPI specifications and classifies changes as breaking or non-breaking.
Requires: openapi-diff (npm install -g @openapitools/openapi-diff-cli)

Usage:
    python check_compatibility.py --old old-spec.yaml --new new-spec.yaml --output report.json
    python check_compatibility.py --old old-spec.yaml --new new-spec.yaml --markdown report.md

Exit codes:
    0 - No changes or only non-breaking changes
    1 - Breaking changes detected
    2 - Tool/runtime error
"""

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChangeType(Enum):
    BREAKING = "breaking"
    NON_BREAKING = "nonBreaking"
    UNKNOWN = "unknown"


@dataclass
class Change:
    type: str  # e.g., "EndpointRemoved", "RequestParameterAdded"
    scope: str  # "endpoint", "request", "response", "schema", "security"
    path: str  # affected path/location
    description: str
    severity: str
    change_type: str  # "breaking" or "nonBreaking"
    migration_hint: str = ""


@dataclass
class CompatibilityReport:
    old_spec: str
    new_spec: str
    status: str  # "BREAKING", "NON_BREAKING", "NO_CHANGE", "ERROR"
    breaking: list[Change] = field(default_factory=list)
    non_breaking: list[Change] = field(default_factory=list)
    unknown: list[Change] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Classification rules: map openapi-diff change type → classification
# ---------------------------------------------------------------------------

BREAKING_RULES: dict[str, tuple[Severity, str]] = {
    # Endpoint changes
    "EndpointRemoved": (Severity.CRITICAL, "Endpoint was removed"),
    "EndpointMethodChanged": (Severity.CRITICAL, "HTTP method changed"),
    # Request changes
    "RequestParameterRequiredIncreased": (Severity.HIGH, "Parameter became required"),
    "RequestParameterRemoved": (Severity.MEDIUM, "Request parameter removed"),
    "RequestParameterTypeChanged": (Severity.CRITICAL, "Parameter type changed"),
    "RequestParameterFormatChanged": (Severity.HIGH, "Parameter format changed"),
    "RequestBodyRequiredFieldAdded": (Severity.CRITICAL, "Required field added to request body"),
    "RequestBodyFieldTypeChanged": (Severity.CRITICAL, "Request body field type changed"),
    "RequestBodyFieldRemoved": (Severity.MEDIUM, "Request body field removed"),
    "RequestBodyAdditionalPropertiesReduced": (Severity.HIGH, "additionalProperties set to false"),
    # Response changes
    "ResponseSuccessStatusCodeRemoved": (Severity.CRITICAL, "Success status code removed"),
    "ResponseBodyFieldRemoved": (Severity.CRITICAL, "Response field removed"),
    "ResponseBodyFieldTypeChanged": (Severity.CRITICAL, "Response field type changed"),
    "ResponseContentTypeChanged": (Severity.HIGH, "Response Content-Type changed"),
    "ResponseStatusCodeChanged": (Severity.MEDIUM, "Response status code changed"),
    # Security changes
    "SecurityAdded": (Severity.CRITICAL, "Authentication requirement added"),
    "SecuritySchemeChanged": (Severity.CRITICAL, "Security scheme changed"),
    "SecurityScopeAdded": (Severity.HIGH, "Required security scope added"),
}

NON_BREAKING_RULES: dict[str, tuple[Severity, str]] = {
    # Endpoint changes
    "EndpointAdded": (Severity.LOW, "New endpoint added"),
    "EndpointMethodAdded": (Severity.LOW, "New HTTP method added to path"),
    # Request changes
    "RequestParameterAdded": (Severity.LOW, "Optional request parameter added"),
    "RequestParameterRequiredDecreased": (Severity.LOW, "Parameter no longer required"),
    "RequestBodyFieldAdded": (Severity.LOW, "Optional field added to request body"),
    "RequestBodyRequiredFieldRemoved": (Severity.LOW, "Required field removed from request body"),
    "RequestBodyAdditionalPropertiesIncreased": (Severity.LOW, "additionalProperties relaxed"),
    # Response changes
    "ResponseStatusCodeAdded": (Severity.LOW, "New response status code added"),
    "ResponseBodyFieldAdded": (Severity.LOW, "Response field added"),
    # Schema/doc changes
    "SchemaDescriptionChanged": (Severity.LOW, "Schema description changed"),
    "SchemaAdded": (Severity.LOW, "New schema component added"),
}


def classify_change(change_type: str) -> tuple[ChangeType, Severity, str]:
    """Classify a raw openapi-diff change type."""
    if change_type in BREAKING_RULES:
        severity, description = BREAKING_RULES[change_type]
        return ChangeType.BREAKING, severity, description
    if change_type in NON_BREAKING_RULES:
        severity, description = NON_BREAKING_RULES[change_type]
        return ChangeType.NON_BREAKING, severity, description
    return ChangeType.UNKNOWN, Severity.MEDIUM, f"Unclassified change: {change_type}"


def run_openapi_diff(old_spec: str, new_spec: str) -> dict[str, Any]:
    """Run openapi-diff CLI and return parsed JSON output."""
    cmd = [
        "openapi-diff",
        "--old", old_spec,
        "--new", new_spec,
        "--type", "json",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # openapi-diff exits 0 even when differences found; exit 1 on error
    if result.returncode != 0 and not result.stdout.strip():
        print(f"openapi-diff failed: {result.stderr}", file=sys.stderr)
        sys.exit(2)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"Failed to parse openapi-diff output: {exc}", file=sys.stderr)
        print(f"Raw output: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(2)


def parse_raw_diff(raw: dict[str, Any], old_spec: str, new_spec: str) -> CompatibilityReport:
    """Convert raw openapi-diff JSON into a structured CompatibilityReport."""
    report = CompatibilityReport(
        old_spec=old_spec,
        new_spec=new_spec,
        status="NO_CHANGE",
    )

    # openapi-diff JSON structure: { "newEndpoints": [], "missingEndpoints": [],
    # "changedOperations": [ { "pathUrl": "...", "method": "...",
    #   "changedFields": { "...": [ { "declaration": ..., "scope": ..., "type": ... } ] } } ] }

    for key in ("newEndpoints", "missingEndpoints", "changedOperations"):
        for item in raw.get(key, []):
            path_url = item.get("pathUrl", "unknown")
            method = item.get("method", "").upper()
            location = f"{method} {path_url}" if method else path_url

            if key == "newEndpoints":
                report.non_breaking.append(Change(
                    type="EndpointAdded",
                    scope="endpoint",
                    path=location,
                    description="New endpoint was added",
                    severity="low",
                    change_type="nonBreaking",
                    migration_hint="No action required for existing consumers.",
                ))
                continue

            if key == "missingEndpoints":
                report.breaking.append(Change(
                    type="EndpointRemoved",
                    scope="endpoint",
                    path=location,
                    description="Endpoint was removed",
                    severity="critical",
                    change_type="breaking",
                    migration_hint=f"Replace with alternative endpoint or restore {location}.",
                ))
                continue

            # changedOperations
            changed_fields = item.get("changedFields", {})
            for field_name, changes in changed_fields.items():
                for change_entry in changes:
                    raw_type = change_entry.get("type", "UnknownChange")
                    scope = change_entry.get("scope", field_name)
                    change_type, severity, desc = classify_change(raw_type)

                    ch = Change(
                        type=raw_type,
                        scope=scope,
                        path=location,
                        description=desc,
                        severity=severity.value,
                        change_type=change_type.value,
                        migration_hint=_migration_hint(raw_type, location, field_name),
                    )

                    if change_type == ChangeType.BREAKING:
                        report.breaking.append(ch)
                    elif change_type == ChangeType.NON_BREAKING:
                        report.non_breaking.append(ch)
                    else:
                        report.unknown.append(ch)

    # Determine overall status
    if report.breaking:
        report.status = "BREAKING"
    elif report.non_breaking:
        report.status = "NON_BREAKING"
    else:
        report.status = "NO_CHANGE"

    report.summary = (
        f"{len(report.breaking)} breaking, "
        f"{len(report.non_breaking)} non-breaking, "
        f"{len(report.unknown)} unknown changes"
    )

    return report


def _migration_hint(change_type: str, location: str, field: str) -> str:
    """Generate a human-readable migration hint for a change."""
    hints = {
        "EndpointRemoved": f"Restore {location} or provide a replacement endpoint.",
        "EndpointMethodChanged": f"Update client to use the new HTTP method for {location}.",
        "RequestParameterRequiredIncreased": f"Add the now-required parameter '{field}' to requests.",
        "RequestParameterTypeChanged": f"Update parameter '{field}' to match the new type.",
        "RequestBodyRequiredFieldAdded": f"Include the new required field '{field}' in request payloads.",
        "RequestBodyFieldTypeChanged": f"Update '{field}' values to match the new type.",
        "ResponseSuccessStatusCodeRemoved": f"Update client to handle the new success status code.",
        "ResponseBodyFieldRemoved": f"Remove dependency on '{field}' from response parsing.",
        "ResponseBodyFieldTypeChanged": f"Update deserialization for '{field}' to handle new type.",
        "SecurityAdded": f"Add authentication to requests targeting {location}.",
        "EndpointAdded": f"New endpoint available — no migration needed.",
        "ResponseBodyFieldAdded": f"New field '{field}' available — clients can opt-in.",
    }
    return hints.get(change_type, f"Review {change_type} at {location}.")


def report_to_json(report: CompatibilityReport) -> str:
    """Serialize report to JSON string."""
    return json.dumps(asdict(report), indent=2, default=str)


def report_to_markdown(report: CompatibilityReport) -> str:
    """Render report as Markdown."""
    lines = [
        "# API Compatibility Report",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Base Spec** | `{report.old_spec}` |",
        f"| **New Spec** | `{report.new_spec}` |",
        f"| **Status** | `{report.status}` |",
        f"| **Summary** | {report.summary} |",
        "",
        "## Breaking Changes",
        "",
    ]

    if report.breaking:
        lines.append("| # | Type | Path | Description | Severity | Migration |")
        lines.append("|---|------|------|-------------|----------|-----------|")
        for i, ch in enumerate(report.breaking, 1):
            lines.append(
                f"| {i} | `{ch.type}` | {ch.path} | {ch.description} | "
                f"{ch.severity} | {ch.migration_hint} |"
            )
    else:
        lines.append("*No breaking changes detected.*")

    lines.extend(["", "## Non-Breaking Changes", ""])

    if report.non_breaking:
        lines.append("| # | Type | Path | Description |")
        lines.append("|---|------|------|-------------|")
        for i, ch in enumerate(report.non_breaking, 1):
            lines.append(f"| {i} | `{ch.type}` | {ch.path} | {ch.description} |")
    else:
        lines.append("*No non-breaking changes detected.*")

    if report.unknown:
        lines.extend(["", "## Unclassified Changes (Manual Review Required)", ""])
        lines.append("| # | Type | Path | Description |")
        lines.append("|---|------|------|-------------|")
        for i, ch in enumerate(report.unknown, 1):
            lines.append(f"| {i} | `{ch.type}` | {ch.path} | {ch.description} |")

    lines.extend(["", "---", "", "*Generated by api-version-guard*"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAPI compatibility checker")
    parser.add_argument("--old", required=True, help="Path to previous OpenAPI spec")
    parser.add_argument("--new", required=True, help="Path to current OpenAPI spec")
    parser.add_argument("--output", help="Output JSON report path")
    parser.add_argument("--markdown", help="Output Markdown report path")
    parser.add_argument(
        "--fail-on-unknown",
        action="store_true",
        help="Treat unclassified changes as breaking",
    )
    args = parser.parse_args()

    if not Path(args.old).exists():
        print(f"Old spec not found: {args.old}", file=sys.stderr)
        return 2
    if not Path(args.new).exists():
        print(f"New spec not found: {args.new}", file=sys.stderr)
        return 2

    raw = run_openapi_diff(args.old, args.new)
    report = parse_raw_diff(raw, args.old, args.new)

    # Optionally treat unknown changes as breaking
    if args.fail_on_unknown and report.unknown:
        report.status = "BREAKING"
        for ch in report.unknown:
            ch.change_type = "breaking"
            report.breaking.append(ch)
        report.unknown.clear()

    # Output
    json_report = report_to_json(report)
    if args.output:
        Path(args.output).write_text(json_report)
        print(f"JSON report written to {args.output}")

    if args.markdown:
        md_report = report_to_markdown(report)
        Path(args.markdown).write_text(md_report)
        print(f"Markdown report written to {args.markdown}")

    if not args.output and not args.markdown:
        print(json_report)

    print(f"\nStatus: {report.status} ({report.summary})")

    return 1 if report.status == "BREAKING" else 0


if __name__ == "__main__":
    sys.exit(main())
