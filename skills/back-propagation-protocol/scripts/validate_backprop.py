#!/usr/bin/env python3
"""
Back-Propagation Artifact Schema Validator

Validates a back-propagation artifact JSON file against the protocol schema.
Returns exit code 0 on valid, 1 on validation errors.

Usage:
    python validate_backprop.py <artifact.json>
    cat artifact.json | python validate_backprop.py -

Dependencies: jsonschema (pip install jsonschema)
"""

import json
import sys
from pathlib import Path

# Embedded schema to avoid external file dependencies
SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "schema_version",
        "artifact_id",
        "source",
        "analysis",
        "authorization",
        "context_bundle",
        "lifecycle",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": "1.0.0"},
        "artifact_id": {"type": "string", "format": "uuid"},
        "source": {
            "type": "object",
            "required": [
                "failure_id",
                "source_phase",
                "source_skill",
                "severity",
                "category",
                "artifact_hash",
                "message",
                "raw_output",
                "timestamp",
                "retry_count",
            ],
            "properties": {
                "failure_id": {"type": "string", "format": "uuid"},
                "source_phase": {
                    "type": "string",
                    "enum": ["VALIDATE", "EXECUTE", "INTEGRATE"],
                },
                "source_skill": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "info"],
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "contract_violation",
                        "performance_regression",
                        "security_vulnerability",
                        "architectural_mismatch",
                        "resource_exhaustion",
                        "flaky_test",
                        "breaking_change",
                        "environment_error",
                    ],
                },
                "artifact_hash": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
                "message": {"type": "string", "minLength": 1, "maxLength": 4096},
                "raw_output": {"type": "string", "maxLength": 65536},
                "timestamp": {"type": "string", "format": "date-time"},
                "retry_count": {"type": "integer", "minimum": 0},
                "cvss_score": {"type": "number", "minimum": 0, "maximum": 10},
                "affects_public_api": {"type": "boolean"},
            },
        },
        "analysis": {
            "type": "object",
            "required": [
                "impact_radius",
                "affected_nodes",
                "impact_depth",
                "recommended_target_phase",
                "recommendation_rationale",
                "estimated_rework_scope",
                "risk_of_cascade_failure",
            ],
            "properties": {
                "impact_radius": {"type": "integer", "minimum": 0},
                "affected_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "impact_depth": {"type": "integer", "minimum": 0},
                "recommended_target_phase": {
                    "type": "string",
                    "enum": ["PLAN", "EXECUTE", "VALIDATE"],
                },
                "recommendation_rationale": {"type": "string", "minLength": 1},
                "estimated_rework_scope": {
                    "type": "string",
                    "enum": ["single_artifact", "module_scope", "system_scope", "architectural"],
                },
                "risk_of_cascade_failure": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high", "certain"],
                },
                "dependency_paths": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "authorization": {
            "type": "object",
            "required": [
                "authorization_status",
                "gating_rules",
                "approved_by",
                "approval_timestamp",
            ],
            "properties": {
                "authorization_status": {
                    "type": "string",
                    "enum": ["approved", "denied", "pending_hitl", "escalated"],
                },
                "gating_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["rule_id", "constraint_type", "constraint_value"],
                        "properties": {
                            "rule_id": {"type": "string"},
                            "constraint_type": {
                                "type": "string",
                                "enum": [
                                    "max_scope",
                                    "required_reviewers",
                                    "forbidden_patterns",
                                    "mandatory_tests",
                                    "timeout_limit",
                                ],
                            },
                            "constraint_value": {"type": "string"},
                            "origin": {
                                "type": "string",
                                "enum": ["auto", "hitl", "policy_engine"],
                            },
                        },
                    },
                },
                "approved_by": {"type": ["string", "null"]},
                "approval_timestamp": {"type": ["string", "null"], "format": "date-time"},
                "escalation_target": {"type": ["string", "null"]},
            },
        },
        "context_bundle": {
            "type": "object",
            "required": ["system_message", "skill_constraints", "scope_map"],
            "properties": {
                "system_message": {"type": "string"},
                "skill_constraints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["skill_name", "constraints"],
                        "properties": {
                            "skill_name": {"type": "string"},
                            "constraints": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                    },
                },
                "scope_map": {
                    "type": "object",
                    "required": ["full_context_nodes", "summary_only_nodes"],
                    "properties": {
                        "full_context_nodes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "summary_only_nodes": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "priority_level": {"type": "integer", "const": 0},
            },
        },
        "lifecycle": {
            "type": "object",
            "required": ["created_at", "current_state", "execution_trace_ref"],
            "properties": {
                "created_at": {"type": "string", "format": "date-time"},
                "updated_at": {"type": "string", "format": "date-time"},
                "current_state": {
                    "type": "string",
                    "enum": [
                        "draft",
                        "analyzing",
                        "pending_authorization",
                        "authorized",
                        "injected",
                        "resolved",
                        "archived",
                        "terminal_denied",
                    ],
                },
                "resolved_at": {"type": ["string", "null"], "format": "date-time"},
                "execution_trace_ref": {"type": "string"},
                "previous_failure_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                },
            },
        },
    },
}


def load_json_input(source: str) -> dict:
    """Load JSON from file path or stdin."""
    if source == "-":
        return json.load(sys.stdin)
    path = Path(source)
    if not path.exists():
        print(f"ERROR: File not found: {source}", file=sys.stderr)
        sys.exit(1)
    return json.loads(path.read_text())


def validate_artifact(data: dict) -> list:
    """Validate artifact against schema. Returns list of error strings."""
    try:
        from jsonschema import Draft7Validator, FormatChecker
    except ImportError:
        print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
        sys.exit(1)

    validator = Draft7Validator(SCHEMA, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors]


def check_business_rules(data: dict) -> list:
    """Apply protocol-level business rules beyond JSON schema. Returns list of error strings."""
    errors = []
    source = data.get("source", {})
    auth = data.get("authorization", {})
    lifecycle = data.get("lifecycle", {})

    # Rule: critical security vulns require HITL or escalation
    if source.get("category") == "security_vulnerability" and source.get("severity") == "critical":
        if auth.get("authorization_status") not in ("pending_hitl", "escalated", "approved"):
            errors.append(
                "business_rule: critical security_vulnerability requires approved, pending_hitl, or escalated status"
            )

    # Rule: denied authorization must be terminal
    if auth.get("authorization_status") == "denied" and lifecycle.get("current_state") != "terminal_denied":
        errors.append("business_rule: denied authorization must have lifecycle.state='terminal_denied'")

    # Rule: approved must have approved_by and timestamp
    if auth.get("authorization_status") == "approved":
        if not auth.get("approved_by"):
            errors.append("business_rule: approved status requires approved_by value")
        if not auth.get("approval_timestamp"):
            errors.append("business_rule: approved status requires approval_timestamp")

    # Rule: impact_radius must match affected_nodes length
    analysis = data.get("analysis", {})
    impact_radius = analysis.get("impact_radius", 0)
    affected_nodes = analysis.get("affected_nodes", [])
    if impact_radius != len(affected_nodes):
        errors.append(
            f"business_rule: impact_radius ({impact_radius}) != len(affected_nodes) ({len(affected_nodes)})"
        )

    # Rule: retry_count should be consistent with previous_failure_ids chain length
    prev_ids = lifecycle.get("previous_failure_ids", [])
    retry_count = source.get("retry_count", 0)
    if retry_count > 0 and len(prev_ids) == 0:
        errors.append("business_rule: retry_count > 0 should have previous_failure_ids chain")

    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python validate_backprop.py <artifact.json>\n       cat artifact.json | python validate_backprop.py -", file=sys.stderr)
        return 1

    try:
        data = load_json_input(sys.argv[1])
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}", file=sys.stderr)
        return 1

    schema_errors = validate_artifact(data)
    business_errors = check_business_rules(data)
    all_errors = schema_errors + business_errors

    if all_errors:
        print(f"VALIDATION FAILED: {len(all_errors)} error(s)")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("VALID: Back-propagation artifact passes all schema and business rule checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
