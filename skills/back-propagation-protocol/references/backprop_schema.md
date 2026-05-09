# Back-Propagation Artifact Schema

JSON schema for the structured artifact produced by the 4-layer Back-Propagation Protocol. This artifact carries failure context from VALIDATE back to PLAN (or intermediate phases) without losing traceability.

## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://kimi.skills/back-propagation-protocol/artifact",
  "title": "Back-Propagation Artifact",
  "description": "Structured failure feedback artifact for backward pipeline transitions",
  "type": "object",
  "required": ["schema_version", "artifact_id", "source", "analysis", "authorization", "context_bundle", "lifecycle"],
  "properties": {
    "schema_version": {
      "type": "string",
      "const": "1.0.0",
      "description": "Schema version for backward compatibility"
    },
    "artifact_id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique identifier for this back-propagation artifact (distinct from failure_id)"
    },
    "source": {
      "type": "object",
      "required": ["failure_id", "source_phase", "source_skill", "severity", "category", "artifact_hash", "message", "raw_output", "timestamp", "retry_count"],
      "properties": {
        "failure_id": {
          "type": "string",
          "format": "uuid",
          "description": "Unique identifier for the originating failure (L1 output)"
        },
        "source_phase": {
          "type": "string",
          "enum": ["VALIDATE", "EXECUTE", "INTEGRATE"],
          "description": "Pipeline phase where the failure was detected"
        },
        "source_skill": {
          "type": "string",
          "description": "Skill name that raised the failure (e.g., security-auditor, resilience-tester)"
        },
        "severity": {
          "type": "string",
          "enum": ["critical", "high", "medium", "low", "info"],
          "description": "Normalized failure severity"
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
            "environment_error"
          ],
          "description": "Taxonomy classification for the failure"
        },
        "artifact_hash": {
          "type": "string",
          "pattern": "^[a-f0-9]{64}$",
          "description": "BLAKE3 hash (64 hex chars) of the artifact that failed validation"
        },
        "message": {
          "type": "string",
          "minLength": 1,
          "maxLength": 4096,
          "description": "Human-readable failure summary"
        },
        "raw_output": {
          "type": "string",
          "maxLength": 65536,
          "description": "Full diagnostic output, truncated to 64KB"
        },
        "timestamp": {
          "type": "string",
          "format": "date-time",
          "description": "ISO-8601 timestamp when the failure was detected"
        },
        "retry_count": {
          "type": "integer",
          "minimum": 0,
          "description": "Number of retry attempts already exhausted"
        },
        "cvss_score": {
          "type": "number",
          "minimum": 0,
          "maximum": 10,
          "description": "Optional CVSS score for security_vulnerability category"
        },
        "affects_public_api": {
          "type": "boolean",
          "description": "Optional flag for breaking_change category"
        }
      }
    },
    "analysis": {
      "type": "object",
      "required": ["impact_radius", "affected_nodes", "impact_depth", "recommended_target_phase", "recommendation_rationale", "estimated_rework_scope", "risk_of_cascade_failure"],
      "properties": {
        "impact_radius": {
          "type": "integer",
          "minimum": 0,
          "description": "Count of downstream artifacts affected by this failure"
        },
        "affected_nodes": {
          "type": "array",
          "items": { "type": "string" },
          "description": "List of affected artifact identifiers from dependency graph"
        },
        "impact_depth": {
          "type": "integer",
          "minimum": 0,
          "description": "Longest dependency chain from failure point to leaf artifact"
        },
        "recommended_target_phase": {
          "type": "string",
          "enum": ["PLAN", "EXECUTE", "VALIDATE"],
          "description": "Optimal re-entry phase determined by blast-radius-calculator"
        },
        "recommendation_rationale": {
          "type": "string",
          "minLength": 1,
          "description": "Human-readable justification for target phase selection"
        },
        "estimated_rework_scope": {
          "type": "string",
          "enum": ["single_artifact", "module_scope", "system_scope", "architectural"],
          "description": "Scope of required changes"
        },
        "risk_of_cascade_failure": {
          "type": "string",
          "enum": ["none", "low", "medium", "high", "certain"],
          "description": "Probability that fixing this failure will introduce new failures"
        },
        "dependency_paths": {
          "type": "array",
          "items": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Single dependency path from failure root to affected leaf"
          },
          "description": "Optional: specific dependency paths through the graph"
        }
      }
    },
    "authorization": {
      "type": "object",
      "required": ["authorization_status", "gating_rules", "approved_by", "approval_timestamp"],
      "properties": {
        "authorization_status": {
          "type": "string",
          "enum": ["approved", "denied", "pending_hitl", "escalated"],
          "description": "Current status of the backward transition request"
        },
        "gating_rules": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["rule_id", "constraint_type", "constraint_value"],
            "properties": {
              "rule_id": {
                "type": "string",
                "description": "Unique identifier for the gating rule"
              },
              "constraint_type": {
                "type": "string",
                "enum": ["max_scope", "required_reviewers", "forbidden_patterns", "mandatory_tests", "timeout_limit"],
                "description": "Type of constraint to apply"
              },
              "constraint_value": {
                "type": "string",
                "description": "Constraint value (interpreted per constraint_type)"
              },
              "origin": {
                "type": "string",
                "enum": ["auto", "hitl", "policy_engine"],
                "description": "Source of the gating rule"
              }
            }
          },
          "description": "Constraints applied to the transition and target phase execution"
        },
        "approved_by": {
          "type": ["string", "null"],
          "description": "Operator identifier or 'auto'; null if pending"
        },
        "approval_timestamp": {
          "type": ["string", "null"],
          "format": "date-time",
          "description": "ISO-8601 timestamp of approval; null if pending"
        },
        "escalation_target": {
          "type": ["string", "null"],
          "description": "If escalated, the role/team responsible for resolution"
        }
      }
    },
    "context_bundle": {
      "type": "object",
      "required": ["system_message", "skill_constraints", "scope_map"],
      "properties": {
        "system_message": {
          "type": "string",
          "description": "Rendered system message for target phase injection (L4 output)"
        },
        "skill_constraints": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["skill_name", "constraints"],
            "properties": {
              "skill_name": { "type": "string" },
              "constraints": {
                "type": "array",
                "items": { "type": "string" }
              }
            }
          },
          "description": "Per-skill constraint mappings derived from gating_rules"
        },
        "scope_map": {
          "type": "object",
          "required": ["full_context_nodes", "summary_only_nodes"],
          "properties": {
            "full_context_nodes": {
              "type": "array",
              "items": { "type": "string" },
              "description": "Nodes that receive full failure context"
            },
            "summary_only_nodes": {
              "type": "array",
              "items": { "type": "string" },
              "description": "Nodes that receive summary context only"
            }
          }
        },
        "priority_level": {
          "type": "integer",
          "minimum": 0,
          "maximum": 0,
          "const": 0,
          "description": "Context priority level (always 0 = highest)"
        }
      }
    },
    "lifecycle": {
      "type": "object",
      "required": ["created_at", "current_state", "execution_trace_ref"],
      "properties": {
        "created_at": {
          "type": "string",
          "format": "date-time",
          "description": "Timestamp when the artifact was created"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time",
          "description": "Timestamp of last modification"
        },
        "current_state": {
          "type": "string",
          "enum": ["draft", "analyzing", "pending_authorization", "authorized", "injected", "resolved", "archived", "terminal_denied"],
          "description": "Current lifecycle state of the artifact"
        },
        "resolved_at": {
          "type": ["string", "null"],
          "format": "date-time",
          "description": "Timestamp when the failure was resolved; null if unresolved"
        },
        "execution_trace_ref": {
          "type": "string",
          "description": "Reference to the execution trace log entry for this artifact"
        },
        "previous_failure_ids": {
          "type": "array",
          "items": { "type": "string", "format": "uuid" },
          "description": "Chain of related failure IDs from previous back-propagation cycles"
        }
      }
    }
  }
}
```

## Field Constraints Summary

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `schema_version` | string | yes | const `"1.0.0"` |
| `artifact_id` | UUID | yes | unique per artifact |
| `source.failure_id` | UUID | yes | unique per failure |
| `source.source_phase` | enum | yes | `VALIDATE`, `EXECUTE`, `INTEGRATE` |
| `source.severity` | enum | yes | `critical`, `high`, `medium`, `low`, `info` |
| `source.category` | enum | yes | 8-category taxonomy |
| `source.artifact_hash` | string | yes | 64-char hex BLAKE3 |
| `source.raw_output` | string | yes | max 65536 chars |
| `source.retry_count` | integer | yes | >= 0 |
| `analysis.impact_radius` | integer | yes | >= 0 |
| `analysis.impact_depth` | integer | yes | >= 0 |
| `analysis.recommended_target_phase` | enum | yes | `PLAN`, `EXECUTE`, `VALIDATE` |
| `analysis.estimated_rework_scope` | enum | yes | 4-level scope |
| `analysis.risk_of_cascade_failure` | enum | yes | 5-level risk |
| `authorization.authorization_status` | enum | yes | 4 states |
| `authorization.gating_rules` | array | yes | may be empty |
| `context_bundle.system_message` | string | yes | L4 rendered output |
| `context_bundle.priority_level` | integer | yes | const `0` |
| `lifecycle.current_state` | enum | yes | 8 lifecycle states |
| `lifecycle.execution_trace_ref` | string | yes | trace log pointer |

## Lifecycle State Machine

```
draft
  |
  v
analyzing (L2 complete)
  |
  v
pending_authorization (L3 waiting)
  |
  +--> approved --> authorized --> injected (L4 complete)
  |                                    |
  |                                    v
  |                               resolved (failure fixed)
  |                                    |
  |                                    v
  |                               archived (retained for audit)
  |
  +--> denied --> terminal_denied (pipeline halted)
  |
  +--> escalated --> pending_authorization (external approval)
```

## Example Minimal Artifact

```json
{
  "schema_version": "1.0.0",
  "artifact_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "source": {
    "failure_id": "f1e2d3c4-b5a6-7890-fedc-ba0987654321",
    "source_phase": "VALIDATE",
    "source_skill": "security-auditor",
    "severity": "critical",
    "category": "security_vulnerability",
    "artifact_hash": "af1349b9c2f98f2f7c3e4b5d6a7f8e9d0c1b2a3f4e5d6c7b8a9f0e1d2c3b4a5f6e7d8",
    "message": "SQL injection vulnerability detected in user authentication endpoint",
    "raw_output": "[scanner output truncated]",
    "timestamp": "2024-01-15T09:23:17Z",
    "retry_count": 0,
    "cvss_score": 9.8
  },
  "analysis": {
    "impact_radius": 12,
    "affected_nodes": ["auth-service", "user-api", "session-manager", "audit-log"],
    "impact_depth": 3,
    "recommended_target_phase": "PLAN",
    "recommendation_rationale": "Architectural redesign required: input validation must be moved to API gateway layer",
    "estimated_rework_scope": "architectural",
    "risk_of_cascade_failure": "medium"
  },
  "authorization": {
    "authorization_status": "approved",
    "gating_rules": [
      {
        "rule_id": "sec-review-required",
        "constraint_type": "required_reviewers",
        "constraint_value": "security-lead",
        "origin": "policy_engine"
      }
    ],
    "approved_by": "auto",
    "approval_timestamp": "2024-01-15T09:23:45Z",
    "escalation_target": null
  },
  "context_bundle": {
    "system_message": "[BACK-PROPAGATION CONTEXT] Failure ID: f1e2d3c4... Severity: critical...",
    "skill_constraints": [
      {
        "skill_name": "plan-architecture",
        "constraints": ["required_reviewers:security-lead"]
      }
    ],
    "scope_map": {
      "full_context_nodes": ["auth-service", "user-api", "session-manager", "audit-log"],
      "summary_only_nodes": ["notification-service", "metrics-collector"]
    },
    "priority_level": 0
  },
  "lifecycle": {
    "created_at": "2024-01-15T09:23:17Z",
    "updated_at": "2024-01-15T09:23:45Z",
    "current_state": "injected",
    "resolved_at": null,
    "execution_trace_ref": "trace://pipeline-42/validate-fail-17",
    "previous_failure_ids": []
  }
}
```