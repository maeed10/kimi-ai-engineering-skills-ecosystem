#!/usr/bin/env python3
"""
validate_transition.py

Standalone script for validating a proposed phase transition offline.

Validates:
  1. Phase transition graph (e.g., PLAN -> EXECUTE is allowed)
  2. Artifact JSON structure against the versioned schema for the target phase
  3. Artifact SHA-256 hash matches the canonical JSON body
  4. Schema-specific validator rules (pure Python implementations)

Usage:
  python validate_transition.py \\
    --current-phase PLAN \\
    --proposed-phase EXECUTE \\
    --artifact artifact.json \\
    --artifact-hash sha256:abc123... \\
    --mission-id mission-42

Exit codes:
  0  Transition is valid
  1  Invalid transition (graph violation)
  2  Artifact validation failed (schema or rules)
  3  Hash mismatch
  4  CLI usage error
  5  Internal error
"""

import argparse
import hashlib
import json
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Phase Graph
# ---------------------------------------------------------------------------

PHASE_ORDER = ["INIT", "PLAN", "EXECUTE", "VERIFY", "REPORT", "ARCHIVE", "CLOSED"]

PHASE_TRANSITIONS: dict[str, str] = {
    "INIT": "PLAN",
    "PLAN": "EXECUTE",
    "EXECUTE": "VERIFY",
    "VERIFY": "REPORT",
    "REPORT": "ARCHIVE",
    "ARCHIVE": "CLOSED",
}

# Artifact type expected for each target phase
TARGET_ARTIFACT_SCHEMA: dict[str, str] = {
    "PLAN": "mission_brief/v1",
    "EXECUTE": "plan_spec/v1",
    "VERIFY": "execute_log/v1",
    "REPORT": "verify_results/v1",
    "ARCHIVE": "report_digest/v1",
    "CLOSED": "archive_bundle/v1",
}

# Closure certificate is stored but does not enable further transition
CLOSURE_SCHEMA_ID = "closure_certificate/v1"


# ---------------------------------------------------------------------------
# Canonical JSON & Hashing
# ---------------------------------------------------------------------------

def canonical_json(value: Any) -> str:
    """Return compact JSON with sorted keys for deterministic hashing."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def compute_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_artifact_hash(artifact: dict, expected_hash: str) -> tuple[bool, str, str]:
    """Return (ok, expected_prefix, computed). expected_hash may omit 'sha256:' prefix."""
    expected = expected_hash.removeprefix("sha256:")
    canonical = canonical_json(artifact)
    computed = compute_sha256(canonical)
    ok = computed.lower() == expected.lower()
    return ok, expected_hash, f"sha256:{computed}"


# ---------------------------------------------------------------------------
# Schema Validation Primitives
# ---------------------------------------------------------------------------

class ValidationError:
    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"[{self.path}] {self.message}"


ValidatorFn = Callable[[Any, str, Any], list[ValidationError]]


def check_required(obj: Any, path: str, schema: dict, errors: list[ValidationError]) -> None:
    required = schema.get("required", [])
    if not isinstance(obj, dict):
        errors.append(ValidationError(path, f"expected object, got {type(obj).__name__}"))
        return
    for key in required:
        if key not in obj:
            errors.append(ValidationError(path, f"missing required property: {key}"))


def check_type(value: Any, path: str, t: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if t == "object":
        if not isinstance(value, dict):
            errors.append(ValidationError(path, f"expected object, got {type(value).__name__}"))
    elif t == "array":
        if not isinstance(value, list):
            errors.append(ValidationError(path, f"expected array, got {type(value).__name__}"))
    elif t == "string":
        if not isinstance(value, str):
            errors.append(ValidationError(path, f"expected string, got {type(value).__name__}"))
    elif t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(ValidationError(path, f"expected integer, got {type(value).__name__}"))
    elif t == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(ValidationError(path, f"expected number, got {type(value).__name__}"))
    elif t == "boolean":
        if not isinstance(value, bool):
            errors.append(ValidationError(path, f"expected boolean, got {type(value).__name__}"))
    return errors


def check_string_constraints(value: str, path: str, prop_schema: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if "minLength" in prop_schema and len(value) < prop_schema["minLength"]:
        errors.append(ValidationError(path, f"minLength {prop_schema['minLength']}, got {len(value)}"))
    if "maxLength" in prop_schema and len(value) > prop_schema["maxLength"]:
        errors.append(ValidationError(path, f"maxLength {prop_schema['maxLength']}, got {len(value)}"))
    if "pattern" in prop_schema:
        if not re.match(prop_schema["pattern"], value):
            errors.append(ValidationError(path, f"pattern '{prop_schema['pattern']}' not matched"))
    if "format" in prop_schema:
        fmt = prop_schema["format"]
        if fmt == "email":
            if "@" not in value or "." not in value.split("@")[-1]:
                errors.append(ValidationError(path, f"invalid email format: {value}"))
        elif fmt == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(ValidationError(path, f"invalid date-time: {value}"))
        elif fmt == "uri":
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
                errors.append(ValidationError(path, f"invalid URI: {value}"))
    if "const" in prop_schema and value != prop_schema["const"]:
        errors.append(ValidationError(path, f"expected const '{prop_schema['const']}', got '{value}'"))
    if "enum" in prop_schema and value not in prop_schema["enum"]:
        errors.append(ValidationError(path, f"expected one of {prop_schema['enum']}, got '{value}'"))
    return errors


def check_number_constraints(value: float, path: str, prop_schema: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if "minimum" in prop_schema and value < prop_schema["minimum"]:
        errors.append(ValidationError(path, f"minimum {prop_schema['minimum']}, got {value}"))
    if "maximum" in prop_schema and value > prop_schema["maximum"]:
        errors.append(ValidationError(path, f"maximum {prop_schema['maximum']}, got {value}"))
    return errors


def check_array_constraints(value: list, path: str, prop_schema: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if "minItems" in prop_schema and len(value) < prop_schema["minItems"]:
        errors.append(ValidationError(path, f"minItems {prop_schema['minItems']}, got {len(value)}"))
    if "maxItems" in prop_schema and len(value) > prop_schema["maxItems"]:
        errors.append(ValidationError(path, f"maxItems {prop_schema['maxItems']}, got {len(value)}"))
    if "items" in prop_schema:
        for i, item in enumerate(value):
            errors.extend(validate_value(item, f"{path}[{i}]", prop_schema["items"]))
    return errors


def validate_value(value: Any, path: str, schema: dict) -> list[ValidationError]:
    errors: list[ValidationError] = []

    if schema is True:
        return errors
    if schema is False:
        return [ValidationError(path, "value not allowed here")]

    if not isinstance(schema, dict):
        return errors

    if "type" in schema:
        errors.extend(check_type(value, path, schema["type"]))

    if isinstance(value, str):
        errors.extend(check_string_constraints(value, path, schema))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        errors.extend(check_number_constraints(value, path, schema))
    elif isinstance(value, list):
        errors.extend(check_array_constraints(value, path, schema))
    elif isinstance(value, dict):
        check_required(value, path, schema, errors)
        if "properties" in schema:
            for key, prop_schema in schema["properties"].items():
                if key in value:
                    errors.extend(validate_value(value[key], f"{path}.{key}" if path else key, prop_schema))
        if "additionalProperties" in schema:
            ap = schema["additionalProperties"]
            known = set(schema.get("properties", {}).keys())
            for key in value:
                if key not in known:
                    if ap is False:
                        errors.append(ValidationError(path, f"additional property not allowed: {key}"))
                    elif isinstance(ap, dict):
                        errors.extend(validate_value(value[key], f"{path}.{key}" if path else key, ap))
    return errors


# ---------------------------------------------------------------------------
# Schema Definitions (simplified inline for offline use)
# ---------------------------------------------------------------------------

MISSION_BRIEF_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "objectives", "stakeholders", "constraints"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "mission_brief/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "title": {"type": "string", "minLength": 1, "maxLength": 256},
        "description": {"type": "string", "maxLength": 4096},
        "objectives": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "items": {
                "type": "object",
                "required": ["id", "statement", "priority"],
                "properties": {
                    "id": {"type": "string", "pattern": "^OBJ-[0-9]+$"},
                    "statement": {"type": "string", "minLength": 1, "maxLength": 512},
                    "priority": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "success_criteria": {"type": "string", "maxLength": 512}
                }
            }
        },
        "stakeholders": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["role", "contact"],
                "properties": {
                    "role": {"type": "string", "minLength": 1, "maxLength": 128},
                    "contact": {"type": "string", "format": "email"},
                    "responsibility": {"type": "string", "maxLength": 512}
                }
            }
        },
        "constraints": {
            "type": "object",
            "required": ["budget_hours", "deadline"],
            "properties": {
                "budget_hours": {"type": "number", "minimum": 0},
                "deadline": {"type": "string", "format": "date-time"},
                "regulatory": {"type": "array", "items": {"type": "string"}},
                "tools": {"type": "array", "items": {"type": "string"}}
            }
        },
        "tags": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[a-z0-9_-]+$", "maxLength": 32},
            "maxItems": 16
        }
    },
    "additionalProperties": False
}

PLAN_SPEC_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "tasks", "milestones", "risk_assessment"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "plan_spec/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "summary": {"type": "string", "maxLength": 1024},
        "tasks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 256,
            "items": {
                "type": "object",
                "required": ["id", "title", "owner", "estimated_hours", "status"],
                "properties": {
                    "id": {"type": "string", "pattern": "^TASK-[0-9]+$"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 256},
                    "description": {"type": "string", "maxLength": 2048},
                    "owner": {"type": "string", "format": "email"},
                    "estimated_hours": {"type": "number", "minimum": 0.25},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "blocked", "completed", "cancelled"]},
                    "dependencies": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "^TASK-[0-9]+$"},
                        "maxItems": 32
                    },
                    "deliverables": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 256},
                        "maxItems": 16
                    }
                }
            }
        },
        "milestones": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "name", "target_date", "exit_criteria"],
                "properties": {
                    "id": {"type": "string", "pattern": "^MS-[0-9]+$"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 128},
                    "target_date": {"type": "string", "format": "date-time"},
                    "exit_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1, "maxLength": 512}
                    },
                    "gating": {"type": "boolean", "default": False}
                }
            }
        },
        "risk_assessment": {
            "type": "object",
            "required": ["risks"],
            "properties": {
                "risks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "description", "probability", "impact", "mitigation"],
                        "properties": {
                            "id": {"type": "string", "pattern": "^RISK-[0-9]+$"},
                            "description": {"type": "string", "minLength": 1, "maxLength": 512},
                            "probability": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                            "impact": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                            "mitigation": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "owner": {"type": "string", "format": "email"}
                        }
                    }
                },
                "overall_risk_score": {"type": "string", "enum": ["low", "medium", "high", "critical"]}
            }
        },
        "resource_plan": {
            "type": "object",
            "properties": {
                "personnel": {"type": "array", "items": {"type": "string", "format": "email"}},
                "tools": {"type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 128}},
                "budget_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["category", "amount", "currency"],
                        "properties": {
                            "category": {"type": "string", "minLength": 1, "maxLength": 64},
                            "amount": {"type": "number", "minimum": 0},
                            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"}
                        }
                    }
                }
            }
        }
    },
    "additionalProperties": False
}

EXECUTE_LOG_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "task_executions", "decisions_log", "actual_hours"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "execute_log/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "started_at": {"type": "string", "format": "date-time"},
        "completed_at": {"type": "string", "format": "date-time"},
        "task_executions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["task_id", "status", "actual_hours"],
                "properties": {
                    "task_id": {"type": "string", "pattern": "^TASK-[0-9]+$"},
                    "status": {"type": "string", "enum": ["completed", "partial", "blocked", "cancelled", "deferred"]},
                    "actual_hours": {"type": "number", "minimum": 0},
                    "started_at": {"type": "string", "format": "date-time"},
                    "completed_at": {"type": "string", "format": "date-time"},
                    "outputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "uri"],
                            "properties": {
                                "type": {"type": "string", "enum": ["file", "url", "document", "data", "code"]},
                                "uri": {"type": "string", "format": "uri", "maxLength": 2048},
                                "checksum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                                "description": {"type": "string", "maxLength": 512}
                            }
                        }
                    },
                    "blockers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["reason"],
                            "properties": {
                                "reason": {"type": "string", "minLength": 1, "maxLength": 512},
                                "escalated_to": {"type": "string", "format": "email"},
                                "resolution": {"type": "string", "maxLength": 1024}
                            }
                        }
                    }
                }
            }
        },
        "decisions_log": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["timestamp", "context", "decision", "rationale", "decider"],
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "context": {"type": "string", "minLength": 1, "maxLength": 256},
                    "decision": {"type": "string", "minLength": 1, "maxLength": 512},
                    "rationale": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "decider": {"type": "string", "format": "email"},
                    "alternatives_considered": {"type": "array", "items": {"type": "string", "maxLength": 512}},
                    "reversible": {"type": "boolean", "default": True}
                }
            }
        },
        "actual_hours": {"type": "number", "minimum": 0},
        "budget_variance": {
            "type": "object",
            "properties": {
                "hours_delta": {"type": "number"},
                "reason": {"type": "string", "maxLength": 1024},
                "approved": {"type": "boolean"}
            }
        },
        "quality_gates_passed": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 128}
        }
    },
    "additionalProperties": False
}

VERIFY_RESULTS_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "verification_methods", "findings", "overall_status"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "verify_results/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "verification_methods": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["method", "performed_by", "completed_at", "result"],
                "properties": {
                    "method": {"type": "string", "enum": ["automated_test", "peer_review", "audit", "inspection", "simulation", "static_analysis"]},
                    "performed_by": {"type": "string", "format": "email"},
                    "completed_at": {"type": "string", "format": "date-time"},
                    "result": {"type": "string", "enum": ["pass", "fail", "conditional_pass", "inconclusive"]},
                    "scope": {"type": "string", "maxLength": 512},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "uri"],
                            "properties": {
                                "type": {"type": "string", "enum": ["log", "report", "screenshot", "dataset", "certificate"]},
                                "uri": {"type": "string", "format": "uri", "maxLength": 2048},
                                "checksum": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
                            }
                        }
                    }
                }
            }
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "severity", "description", "status"],
                "properties": {
                    "id": {"type": "string", "pattern": "^FIND-[0-9]+$"},
                    "severity": {"type": "string", "enum": ["blocker", "critical", "major", "minor", "info"]},
                    "description": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "status": {"type": "string", "enum": ["open", "mitigated", "accepted", "false_positive", "resolved"]},
                    "linked_task": {"type": "string", "pattern": "^TASK-[0-9]+$"},
                    "remediation": {"type": "string", "maxLength": 2048},
                    "verifier": {"type": "string", "format": "email"}
                }
            }
        },
        "overall_status": {
            "type": "object",
            "required": ["verdict", "rationale"],
            "properties": {
                "verdict": {"type": "string", "enum": ["approved", "rejected", "approved_with_exceptions", "deferred"]},
                "rationale": {"type": "string", "minLength": 1, "maxLength": 2048},
                "approved_by": {"type": "string", "format": "email"},
                "approved_at": {"type": "string", "format": "date-time"},
                "exceptions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["finding_id", "exception_rationale"],
                        "properties": {
                            "finding_id": {"type": "string", "pattern": "^FIND-[0-9]+$"},
                            "exception_rationale": {"type": "string", "minLength": 1, "maxLength": 1024},
                            "risk_accepted_by": {"type": "string", "format": "email"},
                            "expires_at": {"type": "string", "format": "date-time"}
                        }
                    }
                }
            }
        },
        "compliance_checklist": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["requirement", "satisfied"],
                "properties": {
                    "requirement": {"type": "string", "minLength": 1, "maxLength": 256},
                    "satisfied": {"type": "boolean"},
                    "evidence_uri": {"type": "string", "format": "uri", "maxLength": 2048},
                    "notes": {"type": "string", "maxLength": 1024}
                }
            }
        }
    },
    "additionalProperties": False
}

REPORT_DIGEST_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "outcomes", "report_uris", "lessons_learned"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "report_digest/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "outcomes": {
            "type": "object",
            "required": ["objective_results"],
            "properties": {
                "summary": {"type": "string", "maxLength": 2048},
                "objective_results": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["objective_id", "achieved"],
                        "properties": {
                            "objective_id": {"type": "string", "pattern": "^OBJ-[0-9]+$"},
                            "achieved": {"type": "boolean"},
                            "evidence": {"type": "string", "maxLength": 1024},
                            "notes": {"type": "string", "maxLength": 1024}
                        }
                    }
                },
                "kpi_snapshot": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "required": ["value", "unit"],
                        "properties": {
                            "value": {"type": "number"},
                            "unit": {"type": "string", "maxLength": 32},
                            "target": {"type": "number"},
                            "delta_pct": {"type": "number"}
                        }
                    }
                }
            }
        },
        "report_uris": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["format", "uri"],
                "properties": {
                    "format": {"type": "string", "enum": ["pdf", "html", "markdown", "json", "docx"]},
                    "uri": {"type": "string", "format": "uri", "maxLength": 2048},
                    "checksum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                    "size_bytes": {"type": "integer", "minimum": 0}
                }
            }
        },
        "lessons_learned": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["category", "observation"],
                "properties": {
                    "category": {"type": "string", "enum": ["process", "technical", "communication", "tooling", "planning"]},
                    "observation": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "recommendation": {"type": "string", "maxLength": 1024},
                    "actionable": {"type": "boolean", "default": True}
                }
            }
        },
        "stakeholder_acknowledgments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["stakeholder_email", "acknowledged_at"],
                "properties": {
                    "stakeholder_email": {"type": "string", "format": "email"},
                    "acknowledged_at": {"type": "string", "format": "date-time"},
                    "comments": {"type": "string", "maxLength": 1024}
                }
            }
        },
        "handoff_notes": {"type": "string", "maxLength": 4096}
    },
    "additionalProperties": False
}

ARCHIVE_BUNDLE_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "archive_manifest", "retention_policy", "storage_confirmation"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "archive_bundle/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "archive_manifest": {
            "type": "object",
            "required": ["artifacts"],
            "properties": {
                "archive_id": {"type": "string", "pattern": "^ARCH-[0-9a-z_-]+$", "maxLength": 64},
                "artifacts": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["phase", "artifact_type", "uri", "checksum"],
                        "properties": {
                            "phase": {"type": "string", "enum": ["INIT", "PLAN", "EXECUTE", "VERIFY", "REPORT", "ARCHIVE"]},
                            "artifact_type": {"type": "string", "maxLength": 64},
                            "uri": {"type": "string", "format": "uri", "maxLength": 2048},
                            "checksum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                            "size_bytes": {"type": "integer", "minimum": 0},
                            "encrypted": {"type": "boolean", "default": False},
                            "encryption_key_id": {"type": "string", "maxLength": 128}
                        }
                    }
                },
                "index_uri": {"type": "string", "format": "uri", "maxLength": 2048},
                "total_size_bytes": {"type": "integer", "minimum": 0}
            }
        },
        "retention_policy": {
            "type": "object",
            "required": ["duration_years", "classification"],
            "properties": {
                "duration_years": {"type": "integer", "minimum": 1, "maximum": 100},
                "classification": {"type": "string", "enum": ["public", "internal", "confidential", "restricted"]},
                "access_controls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["role", "permission"],
                        "properties": {
                            "role": {"type": "string", "minLength": 1, "maxLength": 64},
                            "permission": {"type": "string", "enum": ["read", "admin", "none"]},
                            "conditions": {"type": "string", "maxLength": 512}
                        }
                    }
                },
                "destruction_procedure": {"type": "string", "maxLength": 2048},
                "legal_hold": {"type": "boolean", "default": False}
            }
        },
        "storage_confirmation": {
            "type": "object",
            "required": ["provider", "location", "confirmed_at", "confirmation_id"],
            "properties": {
                "provider": {"type": "string", "minLength": 1, "maxLength": 128},
                "location": {"type": "string", "minLength": 1, "maxLength": 256},
                "confirmed_at": {"type": "string", "format": "date-time"},
                "confirmation_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "replica_locations": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 256},
                    "maxItems": 8
                },
                "integrity_verification": {
                    "type": "object",
                    "required": ["method", "result"],
                    "properties": {
                        "method": {"type": "string", "enum": ["checksum_reconcile", "merkle_verify", "signed_manifest"]},
                        "result": {"type": "string", "enum": ["pass", "fail"]},
                        "details": {"type": "string", "maxLength": 1024}
                    }
                }
            }
        },
        "metadata": {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string", "maxLength": 64}, "maxItems": 32},
                "searchable_text": {"type": "string", "maxLength": 4096},
                "related_missions": {"type": "array", "items": {"type": "string", "pattern": "^[a-z0-9_-]+$", "maxLength": 64}, "maxItems": 16}
            }
        }
    },
    "additionalProperties": False
}

CLOSURE_CERTIFICATE_SCHEMA = {
    "type": "object",
    "required": ["mission_id", "schema_id", "version", "generated_at", "closure_type", "final_attestations"],
    "properties": {
        "mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64},
        "schema_id": {"type": "string", "const": "closure_certificate/v1"},
        "version": {"type": "string", "const": "v1"},
        "generated_at": {"type": "string", "format": "date-time"},
        "closure_type": {"type": "string", "enum": ["successful", "terminated", "cancelled", "merged", "superseded"]},
        "closure_reason": {"type": "string", "minLength": 1, "maxLength": 2048},
        "final_attestations": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["role", "attestor_email", "attested_at", "statement"],
                "properties": {
                    "role": {"type": "string", "minLength": 1, "maxLength": 128},
                    "attestor_email": {"type": "string", "format": "email"},
                    "attested_at": {"type": "string", "format": "date-time"},
                    "statement": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "signature": {
                        "type": "object",
                        "required": ["type", "value"],
                        "properties": {
                            "type": {"type": "string", "enum": ["ed25519", "gpg", "x509"]},
                            "value": {"type": "string", "minLength": 64, "maxLength": 512},
                            "public_key_fingerprint": {"type": "string", "maxLength": 64}
                        }
                    }
                }
            }
        },
        "post_closure_obligations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["obligation", "due_date", "owner"],
                "properties": {
                    "obligation": {"type": "string", "minLength": 1, "maxLength": 512},
                    "due_date": {"type": "string", "format": "date-time"},
                    "owner": {"type": "string", "format": "email"},
                    "tracking_id": {"type": "string", "maxLength": 64}
                }
            }
        },
        "successor_mission_id": {"type": "string", "pattern": "^[a-z0-9_-]+$", "maxLength": 64},
        "final_merkle_root": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"},
        "final_phase": {"type": "string", "const": "CLOSED"}
    },
    "additionalProperties": False
}

SCHEMA_REGISTRY: dict[str, dict] = {
    "mission_brief/v1": MISSION_BRIEF_SCHEMA,
    "plan_spec/v1": PLAN_SPEC_SCHEMA,
    "execute_log/v1": EXECUTE_LOG_SCHEMA,
    "verify_results/v1": VERIFY_RESULTS_SCHEMA,
    "report_digest/v1": REPORT_DIGEST_SCHEMA,
    "archive_bundle/v1": ARCHIVE_BUNDLE_SCHEMA,
    "closure_certificate/v1": CLOSURE_CERTIFICATE_SCHEMA,
}


# ---------------------------------------------------------------------------
# Schema-Specific Validator Rules
# ---------------------------------------------------------------------------

def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_mission_brief(artifact: dict) -> list[str]:
    errors: list[str] = []
    try:
        gen = _dt(artifact["generated_at"])
        dl = _dt(artifact["constraints"]["deadline"])
        if dl <= gen:
            errors.append("constraints.deadline must be strictly after generated_at")
    except Exception as e:
        errors.append(f"date parse error in mission_brief: {e}")
    obj_ids = [o["id"] for o in artifact.get("objectives", [])]
    if len(obj_ids) != len(set(obj_ids)):
        errors.append("objectives ids must be unique")
    domains = [s["contact"].split("@")[-1] for s in artifact.get("stakeholders", []) if "@" in s.get("contact", "")]
    if len(domains) != len(set(domains)):
        errors.append("stakeholder contact domains must be unique")
    return errors


def validate_plan_spec(artifact: dict) -> list[str]:
    errors: list[str] = []
    tasks = artifact.get("tasks", [])
    task_ids = {t["id"] for t in tasks}
    # DAG check
    graph: dict[str, list[str]] = {t["id"]: t.get("dependencies", []) for t in tasks}
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def has_cycle(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if has_cycle(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.remove(node)
        return False

    for t in tasks:
        if t["id"] not in visited:
            if has_cycle(t["id"]):
                errors.append("task dependencies contain a cycle")
                break
    # All deps exist
    for t in tasks:
        for dep in t.get("dependencies", []):
            if dep not in task_ids:
                errors.append(f"task {t['id']} dependency {dep} does not exist")
    # Milestone dates
    try:
        gen = _dt(artifact["generated_at"])
        for ms in artifact.get("milestones", []):
            if _dt(ms["target_date"]) < gen:
                errors.append(f"milestone {ms['id']} target_date must be >= generated_at")
    except Exception as e:
        errors.append(f"date parse error in plan_spec: {e}")
    return errors


def validate_execute_log(artifact: dict) -> list[str]:
    errors: list[str] = []
    executions = artifact.get("task_executions", [])
    total = sum(e.get("actual_hours", 0) for e in executions)
    if abs(total - artifact.get("actual_hours", 0)) > 0.01:
        errors.append(f"actual_hours {artifact.get('actual_hours')} does not sum of task executions ({total})")
    for e in executions:
        if e.get("status") == "completed":
            if e.get("actual_hours", 0) <= 0:
                errors.append(f"task {e['task_id']} completed but actual_hours is zero")
            if not e.get("completed_at"):
                errors.append(f"task {e['task_id']} completed but missing completed_at")
        if e.get("status") == "blocked" and not e.get("blockers"):
            errors.append(f"task {e['task_id']} blocked but no blockers provided")
        try:
            if e.get("started_at") and e.get("completed_at"):
                if _dt(e["completed_at"]) < _dt(e["started_at"]):
                    errors.append(f"task {e['task_id']} completed_at < started_at")
        except Exception as ex:
            errors.append(f"date parse error for task {e['task_id']}: {ex}")
    return errors


def validate_verify_results(artifact: dict) -> list[str]:
    errors: list[str] = []
    verdict = artifact.get("overall_status", {}).get("verdict")
    if verdict not in ("approved", "approved_with_exceptions"):
        errors.append(f"verdict must be approved or approved_with_exceptions to allow transition, got {verdict}")
    findings = {f["id"]: f for f in artifact.get("findings", [])}
    for f in artifact.get("findings", []):
        if f.get("severity") == "blocker" and f.get("status") == "open":
            errors.append(f"blocker finding {f['id']} is still open")
    for exc in artifact.get("overall_status", {}).get("exceptions", []):
        if exc.get("finding_id") not in findings:
            errors.append(f"exception references unknown finding {exc['finding_id']}")
    try:
        approved_at = artifact.get("overall_status", {}).get("approved_at")
        if approved_at:
            approved_dt = _dt(approved_at)
            for vm in artifact.get("verification_methods", []):
                if _dt(vm["completed_at"]) > approved_dt:
                    errors.append(f"verification method {vm['method']} completed after approval")
    except Exception as e:
        errors.append(f"date parse error in verify_results: {e}")
    if verdict == "approved_with_exceptions" and not artifact.get("overall_status", {}).get("exceptions"):
        errors.append("approved_with_exceptions requires at least one exception")
    return errors


def validate_report_digest(artifact: dict) -> list[str]:
    errors: list[str] = []
    reports = artifact.get("report_uris", [])
    if not any(r.get("checksum") and r.get("size_bytes") is not None for r in reports):
        errors.append("at least one report_uris entry must have checksum and size_bytes")
    categories = {ll["category"] for ll in artifact.get("lessons_learned", [])}
    for required in ("process", "technical", "communication"):
        if required not in categories:
            errors.append(f"lessons_learned must include at least one {required} category")
    return errors


def validate_archive_bundle(artifact: dict) -> list[str]:
    errors: list[str] = []
    artifacts = artifact.get("archive_manifest", {}).get("artifacts", [])
    pairs = [(a["phase"], a["artifact_type"]) for a in artifacts]
    if len(pairs) != len(set(pairs)):
        errors.append("archive_manifest artifacts must have unique (phase, artifact_type) pairs")
    total = sum(a.get("size_bytes", 0) for a in artifacts)
    declared = artifact.get("archive_manifest", {}).get("total_size_bytes")
    if declared is not None and declared < total * 0.99:
        errors.append(f"total_size_bytes {declared} < sum of artifacts {total} (within 1% tolerance)")
    if artifact.get("retention_policy", {}).get("legal_hold") and artifact.get("retention_policy", {}).get("duration_years", 0) < 7:
        errors.append("legal_hold requires retention duration_years >= 7")
    iv = artifact.get("storage_confirmation", {}).get("integrity_verification", {})
    if iv.get("result") != "pass":
        errors.append("storage_confirmation.integrity_verification.result must be pass")
    try:
        if _dt(artifact["storage_confirmation"]["confirmed_at"]) < _dt(artifact["generated_at"]):
            errors.append("storage_confirmation.confirmed_at must be >= generated_at")
    except Exception as e:
        errors.append(f"date parse error in archive_bundle: {e}")
    return errors


def validate_closure_certificate(artifact: dict) -> list[str]:
    errors: list[str] = []
    attestations = artifact.get("final_attestations", [])
    roles = {a["role"] for a in attestations}
    required_roles = {"mission_lead", "quality_assurance", "stakeholder_representative"}
    missing = required_roles - roles
    if missing:
        errors.append(f"final_attestations missing required roles: {missing}")
    if artifact.get("closure_type") in ("merged", "superseded") and not artifact.get("successor_mission_id"):
        errors.append(f"closure_type {artifact['closure_type']} requires successor_mission_id")
    try:
        for obl in artifact.get("post_closure_obligations", []):
            if _dt(obl["due_date"]) < _dt(artifact["generated_at"]):
                errors.append(f"post_closure_obligations due_date must be >= generated_at")
    except Exception as e:
        errors.append(f"date parse error in closure_certificate: {e}")
    if artifact.get("final_phase") != "CLOSED":
        errors.append("final_phase must be CLOSED")
    return errors


VALIDATOR_REGISTRY: dict[str, Callable[[dict], list[str]]] = {
    "mission_brief/v1": validate_mission_brief,
    "plan_spec/v1": validate_plan_spec,
    "execute_log/v1": validate_execute_log,
    "verify_results/v1": validate_verify_results,
    "report_digest/v1": validate_report_digest,
    "archive_bundle/v1": validate_archive_bundle,
    "closure_certificate/v1": validate_closure_certificate,
}


# ---------------------------------------------------------------------------
# Core Validation Orchestrator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TransitionResult:
    ok: bool
    current_phase: str
    proposed_phase: str
    mission_id: str
    schema_id: Optional[str]
    hash_ok: Optional[bool]
    hash_expected: Optional[str]
    hash_computed: Optional[str]
    schema_errors: list[str]
    validator_errors: list[str]
    transition_errors: list[str]
    hash_errors: list[str]

    def to_json(self) -> str:
        return json.dumps({
            "ok": self.ok,
            "current_phase": self.current_phase,
            "proposed_phase": self.proposed_phase,
            "mission_id": self.mission_id,
            "schema_id": self.schema_id,
            "hash_ok": self.hash_ok,
            "hash_expected": self.hash_expected,
            "hash_computed": self.hash_computed,
            "schema_errors": self.schema_errors,
            "validator_errors": self.validator_errors,
            "transition_errors": self.transition_errors,
            "hash_errors": self.hash_errors,
        }, indent=2)


def validate_transition(
    current_phase: str,
    proposed_phase: str,
    artifact: dict,
    artifact_hash: Optional[str],
    mission_id: str,
) -> TransitionResult:
    schema_id: Optional[str] = None
    schema_errors: list[str] = []
    validator_errors: list[str] = []
    transition_errors: list[str] = []
    hash_errors: list[str] = []
    hash_ok: Optional[bool] = None
    hash_expected: Optional[str] = None
    hash_computed: Optional[str] = None

    # 1. Transition graph
    expected_next = PHASE_TRANSITIONS.get(current_phase)
    if expected_next is None:
        transition_errors.append(f"current phase '{current_phase}' is terminal; no transitions allowed")
    elif proposed_phase != expected_next:
        transition_errors.append(
            f"transition from {current_phase} to {proposed_phase} is not allowed; expected next phase: {expected_next}"
        )

    # 2. Schema lookup
    if proposed_phase in TARGET_ARTIFACT_SCHEMA:
        schema_id = TARGET_ARTIFACT_SCHEMA[proposed_phase]
    elif proposed_phase == "CLOSED":
        schema_id = CLOSURE_SCHEMA_ID
    else:
        transition_errors.append(f"no artifact schema registered for target phase {proposed_phase}")

    # 3. Schema validation
    if schema_id:
        schema = SCHEMA_REGISTRY.get(schema_id)
        if schema is None:
            schema_errors.append(f"schema '{schema_id}' not found in registry")
        else:
            raw_errors = validate_value(artifact, "", schema)
            schema_errors = [str(e) for e in raw_errors]
            # Mission ID consistency
            if artifact.get("mission_id") != mission_id:
                schema_errors.append(f"mission_id mismatch: artifact has '{artifact.get('mission_id')}', expected '{mission_id}'")
            # Schema ID consistency
            if artifact.get("schema_id") != schema_id:
                schema_errors.append(f"schema_id mismatch: artifact has '{artifact.get('schema_id')}', expected '{schema_id}'")

            # Custom validator
            validator = VALIDATOR_REGISTRY.get(schema_id)
            if validator:
                validator_errors = validator(artifact)
            else:
                validator_errors.append(f"validator for '{schema_id}' not found")

    # 4. Hash verification
    if artifact_hash:
        hash_ok, hash_expected, hash_computed = verify_artifact_hash(artifact, artifact_hash)
        if not hash_ok:
            hash_errors.append(f"artifact hash mismatch: expected {hash_expected}, computed {hash_computed}")

    ok = (
        not transition_errors
        and not schema_errors
        and not validator_errors
        and not hash_errors
        and (hash_ok is None or hash_ok)
    )

    return TransitionResult(
        ok=ok,
        current_phase=current_phase,
        proposed_phase=proposed_phase,
        mission_id=mission_id,
        schema_id=schema_id,
        hash_ok=hash_ok,
        hash_expected=hash_expected,
        hash_computed=hash_computed,
        schema_errors=schema_errors,
        validator_errors=validator_errors,
        transition_errors=transition_errors,
        hash_errors=hash_errors,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a proposed phase transition offline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python validate_transition.py --current-phase PLAN --proposed-phase EXECUTE \\
      --artifact plan.json --artifact-hash sha256:abc... --mission-id mission-42
        """,
    )
    parser.add_argument("--current-phase", required=True, choices=PHASE_ORDER + ["CLOSED"])
    parser.add_argument("--proposed-phase", required=True, choices=PHASE_ORDER + ["CLOSED"])
    parser.add_argument("--artifact", required=True, type=Path, help="Path to artifact JSON file")
    parser.add_argument("--artifact-hash", default=None, help="Expected SHA-256 hash (with or without sha256: prefix)")
    parser.add_argument("--mission-id", required=True, help="Mission identifier")
    parser.add_argument("--json", action="store_true", help="Emit JSON output only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if not args.artifact.exists():
        print(f"ERROR: artifact file not found: {args.artifact}", file=sys.stderr)
        return 4

    try:
        with args.artifact.open("r", encoding="utf-8") as f:
            artifact = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: failed to parse artifact JSON: {e}", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"ERROR: reading artifact: {e}", file=sys.stderr)
        return 5

    result = validate_transition(
        current_phase=args.current_phase,
        proposed_phase=args.proposed_phase,
        artifact=artifact,
        artifact_hash=args.artifact_hash,
        mission_id=args.mission_id,
    )

    if args.json:
        print(result.to_json())
    else:
        print(f"Transition: {result.current_phase} -> {result.proposed_phase}")
        print(f"Mission ID: {result.mission_id}")
        print(f"Schema ID:  {result.schema_id}")
        if result.hash_expected:
            print(f"Hash:       expected={result.hash_expected} computed={result.hash_computed} match={result.hash_ok}")
        print(f"Result:     {'PASS' if result.ok else 'FAIL'}")
        if result.transition_errors:
            print("\nTransition errors:")
            for e in result.transition_errors:
                print(f"  - {e}")
        if result.hash_errors:
            print("\nHash errors:")
            for e in result.hash_errors:
                print(f"  - {e}")
        if result.schema_errors:
            print("\nSchema errors:")
            for e in result.schema_errors:
                print(f"  - {e}")
        if result.validator_errors:
            print("\nValidator errors:")
            for e in result.validator_errors:
                print(f"  - {e}")

    if result.transition_errors:
        return 1
    if result.hash_errors:
        return 3
    if result.schema_errors or result.validator_errors:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
