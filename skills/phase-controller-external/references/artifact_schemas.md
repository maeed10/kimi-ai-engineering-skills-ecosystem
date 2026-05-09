# Artifact Schema Registry

## Overview

Every phase in the mission lifecycle requires a completion artifact before the phase controller allows transition to the next phase. This document defines versioned JSON Schema definitions and deterministic validator contracts for all artifacts.

**Schema ID format:** `{artifact_type}/{version}`  
**Example:** `plan_spec/v1`

## Schema Versioning Rules

1. **Immutable:** once published, a schema version never changes.
2. **Required fields:** every schema includes `$schema`, `schema_id`, `version`, `mission_id`, and `generated_at`.
3. **Canonical hash:** artifact JSON is canonicalized (sorted keys, no whitespace) before SHA-256 hashing.
4. **Validator purity:** validator functions are deterministic, side-effect-free, and depend only on artifact content.

---

## 1. `mission_brief/v1` — INIT Phase Entry Artifact

Required to transition from `INIT` to `PLAN`.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "mission_brief/v1",
  "title": "Mission Brief",
  "description": "Initial mission definition and objectives",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "objectives", "stakeholders", "constraints"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "mission_brief/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "title": { "type": "string", "minLength": 1, "maxLength": 256 },
    "description": { "type": "string", "maxLength": 4096 },
    "objectives": {
      "type": "array",
      "minItems": 1,
      "maxItems": 32,
      "items": {
        "type": "object",
        "required": ["id", "statement", "priority"],
        "properties": {
          "id": { "type": "string", "pattern": "^OBJ-[0-9]+$" },
          "statement": { "type": "string", "minLength": 1, "maxLength": 512 },
          "priority": { "type": "string", "enum": ["critical", "high", "medium", "low"] },
          "success_criteria": { "type": "string", "maxLength": 512 }
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
          "role": { "type": "string", "minLength": 1, "maxLength": 128 },
          "contact": { "type": "string", "format": "email" },
          "responsibility": { "type": "string", "maxLength": 512 }
        }
      }
    },
    "constraints": {
      "type": "object",
      "required": ["budget_hours", "deadline"],
      "properties": {
        "budget_hours": { "type": "number", "minimum": 0 },
        "deadline": { "type": "string", "format": "date-time" },
        "regulatory": { "type": "array", "items": { "type": "string" } },
        "tools": { "type": "array", "items": { "type": "string" } }
      }
    },
    "tags": {
      "type": "array",
      "items": { "type": "string", "pattern": "^[a-z0-9_-]+$", "maxLength": 32 },
      "maxItems": 16
    }
  },
  "additionalProperties": false
}
```

### Validator Contract

Beyond JSON Schema, the validator must enforce:

- `deadline` must be strictly after `generated_at`
- `budget_hours` must be a finite, non-NaN number
- `objectives` `id` values must be unique within the array
- `stakeholders` `contact` emails must have unique domains (no duplicate organizations)

---

## 2. `plan_spec/v1` — PLAN Phase Completion Artifact

Required to transition from `PLAN` to `EXECUTE`.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "plan_spec/v1",
  "title": "Plan Specification",
  "description": "Detailed execution plan with tasks, dependencies, and risk assessment",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "tasks", "milestones", "risk_assessment"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "plan_spec/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "summary": { "type": "string", "maxLength": 1024 },
    "tasks": {
      "type": "array",
      "minItems": 1,
      "maxItems": 256,
      "items": {
        "type": "object",
        "required": ["id", "title", "owner", "estimated_hours", "status"],
        "properties": {
          "id": { "type": "string", "pattern": "^TASK-[0-9]+$" },
          "title": { "type": "string", "minLength": 1, "maxLength": 256 },
          "description": { "type": "string", "maxLength": 2048 },
          "owner": { "type": "string", "format": "email" },
          "estimated_hours": { "type": "number", "minimum": 0.25 },
          "status": { "type": "string", "enum": ["pending", "in_progress", "blocked", "completed", "cancelled"] },
          "dependencies": {
            "type": "array",
            "items": { "type": "string", "pattern": "^TASK-[0-9]+$" },
            "maxItems": 32
          },
          "deliverables": {
            "type": "array",
            "items": { "type": "string", "minLength": 1, "maxLength": 256 },
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
          "id": { "type": "string", "pattern": "^MS-[0-9]+$" },
          "name": { "type": "string", "minLength": 1, "maxLength": 128 },
          "target_date": { "type": "string", "format": "date-time" },
          "exit_criteria": {
            "type": "array",
            "minItems": 1,
            "items": { "type": "string", "minLength": 1, "maxLength": 512 }
          },
          "gating": { "type": "boolean", "default": false }
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
              "id": { "type": "string", "pattern": "^RISK-[0-9]+$" },
              "description": { "type": "string", "minLength": 1, "maxLength": 512 },
              "probability": { "type": "string", "enum": ["low", "medium", "high", "critical"] },
              "impact": { "type": "string", "enum": ["low", "medium", "high", "critical"] },
              "mitigation": { "type": "string", "minLength": 1, "maxLength": 1024 },
              "owner": { "type": "string", "format": "email" }
            }
          }
        },
        "overall_risk_score": {
          "type": "string",
          "enum": ["low", "medium", "high", "critical"]
        }
      }
    },
    "resource_plan": {
      "type": "object",
      "properties": {
        "personnel": { "type": "array", "items": { "type": "string", "format": "email" } },
        "tools": { "type": "array", "items": { "type": "string", "minLength": 1, "maxLength": 128 } },
        "budget_items": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["category", "amount", "currency"],
            "properties": {
              "category": { "type": "string", "minLength": 1, "maxLength": 64 },
              "amount": { "type": "number", "minimum": 0 },
              "currency": { "type": "string", "pattern": "^[A-Z]{3}$" }
            }
          }
        }
      }
    }
  },
  "additionalProperties": false
}
```

### Validator Contract

- Task dependency graph must be a DAG (no cycles)
- Every dependency reference must match an existing task `id`
- Total `estimated_hours` across all tasks must not exceed `mission_brief` `constraints.budget_hours`
- Every milestone `target_date` must be >= `generated_at`
- Risk `probability` and `impact` combinations must map logically to `overall_risk_score`
- All `owner` emails must appear in `mission_brief` `stakeholders` or `resource_plan` `personnel`

---

## 3. `execute_log/v1` — EXECUTE Phase Completion Artifact

Required to transition from `EXECUTE` to `VERIFY`.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "execute_log/v1",
  "title": "Execution Log",
  "description": "Record of task execution, actuals, deviations, and decisions",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "task_executions", "decisions_log", "actual_hours"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "execute_log/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "started_at": { "type": "string", "format": "date-time" },
    "completed_at": { "type": "string", "format": "date-time" },
    "task_executions": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["task_id", "status", "actual_hours"],
        "properties": {
          "task_id": { "type": "string", "pattern": "^TASK-[0-9]+$" },
          "status": { "type": "string", "enum": ["completed", "partial", "blocked", "cancelled", "deferred"] },
          "actual_hours": { "type": "number", "minimum": 0 },
          "started_at": { "type": "string", "format": "date-time" },
          "completed_at": { "type": "string", "format": "date-time" },
          "outputs": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["type", "uri"],
              "properties": {
                "type": { "type": "string", "enum": ["file", "url", "document", "data", "code"] },
                "uri": { "type": "string", "format": "uri", "maxLength": 2048 },
                "checksum": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
                "description": { "type": "string", "maxLength": 512 }
              }
            }
          },
          "blockers": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["reason"],
              "properties": {
                "reason": { "type": "string", "minLength": 1, "maxLength": 512 },
                "escalated_to": { "type": "string", "format": "email" },
                "resolution": { "type": "string", "maxLength": 1024 }
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
          "timestamp": { "type": "string", "format": "date-time" },
          "context": { "type": "string", "minLength": 1, "maxLength": 256 },
          "decision": { "type": "string", "minLength": 1, "maxLength": 512 },
          "rationale": { "type": "string", "minLength": 1, "maxLength": 2048 },
          "decider": { "type": "string", "format": "email" },
          "alternatives_considered": { "type": "array", "items": { "type": "string", "maxLength": 512 } },
          "reversible": { "type": "boolean", "default": true }
        }
      }
    },
    "actual_hours": { "type": "number", "minimum": 0 },
    "budget_variance": {
      "type": "object",
      "properties": {
        "hours_delta": { "type": "number" },
        "reason": { "type": "string", "maxLength": 1024 },
        "approved": { "type": "boolean" }
      }
    },
    "quality_gates_passed": {
      "type": "array",
      "items": { "type": "string", "minLength": 1, "maxLength": 128 }
    }
  },
  "additionalProperties": false
}
```

### Validator Contract

- Every `task_id` must reference a task from the `plan_spec`
- `completed_at` >= `started_at` for every completed task
- Sum of `actual_hours` across tasks must equal top-level `actual_hours` (within 0.01 tolerance)
- Every decision `timestamp` must be between `started_at` and `completed_at`
- If `status` is `completed`, `actual_hours` must be > 0 and `completed_at` must be present
- If `status` is `blocked`, at least one blocker must be provided with `reason`
- `budget_variance.approved` must be `true` if `hours_delta` > 10% of planned budget

---

## 4. `verify_results/v1` — VERIFY Phase Completion Artifact

Required to transition from `VERIFY` to `REPORT`.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "verify_results/v1",
  "title": "Verification Results",
  "description": "Quality assurance, testing, review, and sign-off records",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "verification_methods", "findings", "overall_status"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "verify_results/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "verification_methods": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["method", "performed_by", "completed_at", "result"],
        "properties": {
          "method": { "type": "string", "enum": ["automated_test", "peer_review", "audit", "inspection", "simulation", "static_analysis"] },
          "performed_by": { "type": "string", "format": "email" },
          "completed_at": { "type": "string", "format": "date-time" },
          "result": { "type": "string", "enum": ["pass", "fail", "conditional_pass", "inconclusive"] },
          "scope": { "type": "string", "maxLength": 512 },
          "evidence": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["type", "uri"],
              "properties": {
                "type": { "type": "string", "enum": ["log", "report", "screenshot", "dataset", "certificate"] },
                "uri": { "type": "string", "format": "uri", "maxLength": 2048 },
                "checksum": { "type": "string", "pattern": "^[a-f0-9]{64}$" }
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
          "id": { "type": "string", "pattern": "^FIND-[0-9]+$" },
          "severity": { "type": "string", "enum": ["blocker", "critical", "major", "minor", "info"] },
          "description": { "type": "string", "minLength": 1, "maxLength": 1024 },
          "status": { "type": "string", "enum": ["open", "mitigated", "accepted", "false_positive", "resolved"] },
          "linked_task": { "type": "string", "pattern": "^TASK-[0-9]+$" },
          "remediation": { "type": "string", "maxLength": 2048 },
          "verifier": { "type": "string", "format": "email" }
        }
      }
    },
    "overall_status": {
      "type": "object",
      "required": ["verdict", "rationale"],
      "properties": {
        "verdict": { "type": "string", "enum": ["approved", "rejected", "approved_with_exceptions", "deferred"] },
        "rationale": { "type": "string", "minLength": 1, "maxLength": 2048 },
        "approved_by": { "type": "string", "format": "email" },
        "approved_at": { "type": "string", "format": "date-time" },
        "exceptions": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["finding_id", "exception_rationale"],
            "properties": {
              "finding_id": { "type": "string", "pattern": "^FIND-[0-9]+$" },
              "exception_rationale": { "type": "string", "minLength": 1, "maxLength": 1024 },
              "risk_accepted_by": { "type": "string", "format": "email" },
              "expires_at": { "type": "string", "format": "date-time" }
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
          "requirement": { "type": "string", "minLength": 1, "maxLength": 256 },
          "satisfied": { "type": "boolean" },
          "evidence_uri": { "type": "string", "format": "uri", "maxLength": 2048 },
          "notes": { "type": "string", "maxLength": 1024 }
        }
      }
    }
  },
  "additionalProperties": false
}
```

### Validator Contract

- `overall_status.verdict` must be `approved` or `approved_with_exceptions` to allow transition
- No `findings` with `severity: blocker` may have `status: open`
- Every `exceptions` entry must reference an existing `findings` `id`
- `approved_at` must be >= all `verification_methods` `completed_at`
- If `verdict` is `approved_with_exceptions`, at least one exception must be present
- Every `compliance_checklist` item marked `satisfied: false` must link to an open finding or documented exception

---

## 5. `report_digest/v1` — REPORT Phase Completion Artifact

Required to transition from `REPORT` to `ARCHIVE`.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "report_digest/v1",
  "title": "Report Digest",
  "description": "Final report summary, outcomes, lessons learned, and delivery confirmation",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "outcomes", "report_uris", "lessons_learned"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "report_digest/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "outcomes": {
      "type": "object",
      "required": ["objective_results"],
      "properties": {
        "summary": { "type": "string", "maxLength": 2048 },
        "objective_results": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "required": ["objective_id", "achieved"],
            "properties": {
              "objective_id": { "type": "string", "pattern": "^OBJ-[0-9]+$" },
              "achieved": { "type": "boolean" },
              "evidence": { "type": "string", "maxLength": 1024 },
              "notes": { "type": "string", "maxLength": 1024 }
            }
          }
        },
        "kpi_snapshot": {
          "type": "object",
          "additionalProperties": {
            "type": "object",
            "required": ["value", "unit"],
            "properties": {
              "value": { "type": "number" },
              "unit": { "type": "string", "maxLength": 32 },
              "target": { "type": "number" },
              "delta_pct": { "type": "number" }
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
          "format": { "type": "string", "enum": ["pdf", "html", "markdown", "json", "docx"] },
          "uri": { "type": "string", "format": "uri", "maxLength": 2048 },
          "checksum": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
          "size_bytes": { "type": "integer", "minimum": 0 }
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
          "category": { "type": "string", "enum": ["process", "technical", "communication", "tooling", "planning"] },
          "observation": { "type": "string", "minLength": 1, "maxLength": 1024 },
          "recommendation": { "type": "string", "maxLength": 1024 },
          "actionable": { "type": "boolean", "default": true }
        }
      }
    },
    "stakeholder_acknowledgments": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["stakeholder_email", "acknowledged_at"],
        "properties": {
          "stakeholder_email": { "type": "string", "format": "email" },
          "acknowledged_at": { "type": "string", "format": "date-time" },
          "comments": { "type": "string", "maxLength": 1024 }
        }
      }
    },
    "handoff_notes": { "type": "string", "maxLength": 4096 }
  },
  "additionalProperties": false
}
```

### Validator Contract

- Every `objective_id` must reference an objective from the `mission_brief`
- Every `stakeholder_email` must appear in `mission_brief` `stakeholders` or `report_digest` `stakeholder_acknowledgments`
- At least one `report_uris` entry must have `checksum` and `size_bytes`
- `lessons_learned` must contain at least one entry from each of `process`, `technical`, and `communication` categories
- All acknowledgments `acknowledged_at` must be >= `generated_at` of prior phase artifacts

---

## 6. `archive_bundle/v1` — ARCHIVE Phase Completion Artifact

Required to transition from `ARCHIVE` to `CLOSED`.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "archive_bundle/v1",
  "title": "Archive Bundle",
  "description": "Archive manifest, retention policy, and long-term storage confirmation",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "archive_manifest", "retention_policy", "storage_confirmation"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "archive_bundle/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "archive_manifest": {
      "type": "object",
      "required": ["artifacts"],
      "properties": {
        "archive_id": { "type": "string", "pattern": "^ARCH-[0-9a-z_-]+$", "maxLength": 64 },
        "artifacts": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "required": ["phase", "artifact_type", "uri", "checksum"],
            "properties": {
              "phase": { "type": "string", "enum": ["INIT", "PLAN", "EXECUTE", "VERIFY", "REPORT", "ARCHIVE"] },
              "artifact_type": { "type": "string", "maxLength": 64 },
              "uri": { "type": "string", "format": "uri", "maxLength": 2048 },
              "checksum": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
              "size_bytes": { "type": "integer", "minimum": 0 },
              "encrypted": { "type": "boolean", "default": false },
              "encryption_key_id": { "type": "string", "maxLength": 128 }
            }
          }
        },
        "index_uri": { "type": "string", "format": "uri", "maxLength": 2048 },
        "total_size_bytes": { "type": "integer", "minimum": 0 }
      }
    },
    "retention_policy": {
      "type": "object",
      "required": ["duration_years", "classification"],
      "properties": {
        "duration_years": { "type": "integer", "minimum": 1, "maximum": 100 },
        "classification": { "type": "string", "enum": ["public", "internal", "confidential", "restricted"] },
        "access_controls": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["role", "permission"],
            "properties": {
              "role": { "type": "string", "minLength": 1, "maxLength": 64 },
              "permission": { "type": "string", "enum": ["read", "admin", "none"] },
              "conditions": { "type": "string", "maxLength": 512 }
            }
          }
        },
        "destruction_procedure": { "type": "string", "maxLength": 2048 },
        "legal_hold": { "type": "boolean", "default": false }
      }
    },
    "storage_confirmation": {
      "type": "object",
      "required": ["provider", "location", "confirmed_at", "confirmation_id"],
      "properties": {
        "provider": { "type": "string", "minLength": 1, "maxLength": 128 },
        "location": { "type": "string", "minLength": 1, "maxLength": 256 },
        "confirmed_at": { "type": "string", "format": "date-time" },
        "confirmation_id": { "type": "string", "minLength": 1, "maxLength": 128 },
        "replica_locations": {
          "type": "array",
          "items": { "type": "string", "maxLength": 256 },
          "maxItems": 8
        },
        "integrity_verification": {
          "type": "object",
          "required": ["method", "result"],
          "properties": {
            "method": { "type": "string", "enum": ["checksum_reconcile", "merkle_verify", "signed_manifest"] },
            "result": { "type": "string", "enum": ["pass", "fail"] },
            "details": { "type": "string", "maxLength": 1024 }
          }
        }
      }
    },
    "metadata": {
      "type": "object",
      "properties": {
        "tags": { "type": "array", "items": { "type": "string", "maxLength": 64 }, "maxItems": 32 },
        "searchable_text": { "type": "string", "maxLength": 4096 },
        "related_missions": { "type": "array", "items": { "type": "string", "pattern": "^[a-z0-9_-]+$", "maxLength": 64 }, "maxItems": 16 }
      }
    }
  },
  "additionalProperties": false
}
```

### Validator Contract

- Every `archive_manifest.artifacts` entry must have a unique `(phase, artifact_type)` pair
- `archive_manifest.total_size_bytes` must equal sum of all artifact `size_bytes` (within 1% tolerance for overhead)
- `retention_policy.classification` must be at least as restrictive as the most sensitive artifact in the bundle
- `storage_confirmation.integrity_verification.result` must be `pass`
- If `legal_hold` is `true`, `retention_policy.duration_years` must be >= 7
- `confirmed_at` must be >= `generated_at`
- Every artifact `checksum` must be a valid 64-character hex SHA-256

---

## 7. `closure_certificate/v1` — CLOSED Phase Entry Artifact

Final artifact marking mission as formally closed. Required to transition from `ARCHIVE` to `CLOSED`. The CLOSED phase is terminal; no further transitions are allowed.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "schema_id": "closure_certificate/v1",
  "title": "Closure Certificate",
  "description": "Formal mission closure with final attestations and sign-offs",
  "type": "object",
  "required": ["mission_id", "schema_id", "version", "generated_at", "closure_type", "final_attestations"],
  "properties": {
    "mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "minLength": 1, "maxLength": 64 },
    "schema_id": { "type": "string", "const": "closure_certificate/v1" },
    "version": { "type": "string", "const": "v1" },
    "generated_at": { "type": "string", "format": "date-time" },
    "closure_type": {
      "type": "string",
      "enum": ["successful", "terminated", "cancelled", "merged", "superseded"]
    },
    "closure_reason": { "type": "string", "minLength": 1, "maxLength": 2048 },
    "final_attestations": {
      "type": "array",
      "minItems": 2,
      "items": {
        "type": "object",
        "required": ["role", "attestor_email", "attested_at", "statement"],
        "properties": {
          "role": { "type": "string", "minLength": 1, "maxLength": 128 },
          "attestor_email": { "type": "string", "format": "email" },
          "attested_at": { "type": "string", "format": "date-time" },
          "statement": { "type": "string", "minLength": 1, "maxLength": 1024 },
          "signature": {
            "type": "object",
            "required": ["type", "value"],
            "properties": {
              "type": { "type": "string", "enum": ["ed25519", "gpg", "x509"] },
              "value": { "type": "string", "minLength": 64, "maxLength": 512 },
              "public_key_fingerprint": { "type": "string", "maxLength": 64 }
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
          "obligation": { "type": "string", "minLength": 1, "maxLength": 512 },
          "due_date": { "type": "string", "format": "date-time" },
          "owner": { "type": "string", "format": "email" },
          "tracking_id": { "type": "string", "maxLength": 64 }
        }
      }
    },
    "successor_mission_id": { "type": "string", "pattern": "^[a-z0-9_-]+$", "maxLength": 64 },
    "final_merkle_root": { "type": "string", "pattern": "^sha256:[a-f0-9]{64}$" },
    "final_phase": { "type": "string", "const": "CLOSED" }
  },
  "additionalProperties": false
}
```

### Validator Contract

- `final_merkle_root` must match the current Merkle root in the phase-controller's `transition_log` for this mission
- `final_attestations` must contain at least one `role` from each of: `mission_lead`, `quality_assurance`, and `stakeholder_representative`
- Every `attestor_email` must appear in at least one prior phase artifact as an owner, decider, or verifier
- If `closure_type` is `merged` or `superseded`, `successor_mission_id` must be present and valid
- Every `post_closure_obligations` `due_date` must be >= `generated_at`
- `final_phase` must exactly equal `CLOSED`

---

## Schema Registry Runtime Contract

At startup, the phase-controller:

1. Scans the configured `schemas/` directory
2. Validates that each required transition has a matching schema and validator:
   - `INIT` → `PLAN`: requires `mission_brief/v1`
   - `PLAN` → `EXECUTE`: requires `plan_spec/v1`
   - `EXECUTE` → `VERIFY`: requires `execute_log/v1`
   - `VERIFY` → `REPORT`: requires `verify_results/v1`
   - `REPORT` → `ARCHIVE`: requires `report_digest/v1`
   - `ARCHIVE` → `CLOSED`: requires `archive_bundle/v1`
   - `CLOSED` terminal: requires `closure_certificate/v1` (stored but no transition follows)
3. Fails fast (exit code 1) if any required schema/validator pair is missing

## Adding a New Schema Version

1. Create `{artifact_type}/v{N+1}.schema.json` in `schemas/`
2. Create `{artifact_type}/v{N+1}.validator.py` implementing `validate(artifact: dict) -> list[str]`
3. Update phase-controller configuration to accept `v{N+1}` for the relevant transition
4. Deploy new phase-controller version; old version continues accepting `vN` during rolling update
5. Orchestrators opt-in by targeting `v{N+1}` in their artifact `version` field

## Validator Interface

All validator modules must expose:

```python
def validate(artifact: dict) -> list[str]:
    """
    Validate an artifact dict against this schema version.
    Returns a list of error strings. Empty list means valid.
    Must be deterministic and side-effect-free.
    """
    ...

SCHEMA_ID: str = "artifact_type/vN"
```
