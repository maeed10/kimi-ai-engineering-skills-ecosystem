# MADR-JSON Schema Reference

Complete JSON Schema (Draft 7) for Markdown Any Decision Records - JSON format.

## Schema Overview

MADR-JSON captures architectural decisions in a structured, machine-readable format that supports:
- Automated validation and constraint extraction
- Status lifecycle management
- Traceability to code, requirements, and stakeholders
- Queryable decision registries

## Schema Files

### Main Schema: `madr_json_schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://kimi.io/schemas/madr-json/v1.0.0",
  "title": "MADR-JSON Document",
  "description": "Machine-readable Markdown Any Decision Record (MADR) in JSON format",
  "type": "object",
  "required": ["meta", "context", "decision"],
  "additionalProperties": false,
  "properties": {
    "meta": {
      "$ref": "#/definitions/Meta"
    },
    "context": {
      "$ref": "#/definitions/Context"
    },
    "decision": {
      "$ref": "#/definitions/Decision"
    },
    "consequences": {
      "$ref": "#/definitions/Consequences"
    },
    "alternatives": {
      "$ref": "#/definitions/Alternatives"
    },
    "linked": {
      "$ref": "#/definitions/Linked"
    },
    "derived_constraints": {
      "$ref": "#/definitions/DerivedConstraints"
    }
  },
  "definitions": {
    "Meta": {
      "type": "object",
      "required": ["id", "date", "status"],
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string",
          "description": "Unique identifier for this ADR (e.g., ADR-0042)",
          "pattern": "^[A-Z]{2,4}-[0-9]{4,}$"
        },
        "date": {
          "type": "string",
          "description": "Date the decision was proposed or accepted",
          "format": "date"
        },
        "status": {
          "type": "string",
          "description": "Current lifecycle status",
          "enum": ["proposed", "accepted", "deprecated", "superseded", "rejected"]
        },
        "authors": {
          "type": "array",
          "description": "Individuals or teams responsible for this ADR",
          "items": {
            "type": "string"
          },
          "minItems": 1
        },
        "version": {
          "type": "string",
          "description": "Schema version this ADR conforms to",
          "default": "1.0.0",
          "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"
        },
        "tags": {
          "type": "array",
          "description": "Categorical tags for filtering and search",
          "items": {
            "type": "string",
            "enum": [
              "security",
              "scalability",
              "performance",
              "data-model",
              "integration",
              "deployment",
              "observability",
              "cost",
              "compliance",
              "api-design",
              "frontend",
              "backend",
              "infrastructure",
              "cross-cutting",
              "migration",
              "decommission"
            ]
          }
        },
        "status_history": {
          "type": "array",
          "description": "Chronological log of all status transitions",
          "items": {
            "$ref": "#/definitions/StatusTransition"
          }
        }
      }
    },
    "StatusTransition": {
      "type": "object",
      "required": ["from", "to", "date", "actor"],
      "additionalProperties": false,
      "properties": {
        "from": {
          "type": "string",
          "enum": ["proposed", "accepted", "deprecated", "superseded", "rejected"]
        },
        "to": {
          "type": "string",
          "enum": ["proposed", "accepted", "deprecated", "superseded", "rejected"]
        },
        "date": {
          "type": "string",
          "format": "date-time"
        },
        "actor": {
          "type": "string",
          "description": "Person or system that triggered the transition"
        },
        "reason": {
          "type": "string",
          "description": "Human-readable explanation for the transition"
        }
      }
    },
    "Context": {
      "type": "object",
      "required": ["problem"],
      "additionalProperties": false,
      "properties": {
        "problem": {
          "type": "string",
          "description": "The architectural problem or question this ADR addresses"
        },
        "background": {
          "type": "string",
          "description": "Additional context, history, or preceding events"
        },
        "forces": {
          "type": "array",
          "description": "Competing pressures shaping the decision",
          "items": {
            "type": "string"
          }
        },
        "constraints": {
          "type": "array",
          "description": "Hard constraints that bound the solution space",
          "items": {
            "type": "string"
          }
        },
        "assumptions": {
          "type": "array",
          "description": "Assumed facts taken as given during deliberation",
          "items": {
            "type": "string"
          }
        },
        "scope": {
          "type": "object",
          "description": "Decision applicability boundaries",
          "additionalProperties": false,
          "properties": {
            "system": {
              "type": "string"
            },
            "subsystem": {
              "type": "string"
            },
            "bounded_context": {
              "type": "string"
            },
            " Applies_to": {
              "type": "array",
              "items": { "type": "string" }
            },
            "exclusions": {
              "type": "array",
              "description": "Areas explicitly out of scope",
              "items": { "type": "string" }
            }
          }
        }
      }
    },
    "Decision": {
      "type": "object",
      "required": ["statement"],
      "additionalProperties": false,
      "properties": {
        "statement": {
          "type": "string",
          "description": "The decision itself, stated clearly and declaratively"
        },
        "rationale": {
          "type": "string",
          "description": "Primary reasoning behind the selected option"
        },
        "option_details": {
          "type": "object",
          "description": "Implementation specifics of the chosen option",
          "additionalProperties": true
        }
      }
    },
    "Consequences": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "positive": {
          "type": "array",
          "description": "Beneficial outcomes resulting from the decision",
          "items": { "type": "string" }
        },
        "negative": {
          "type": "array",
          "description": "Detrimental outcomes or trade-offs accepted",
          "items": { "type": "string" }
        },
        "neutral": {
          "type": "array",
          "description": "Observable outcomes that are neither beneficial nor detrimental",
          "items": { "type": "string" }
        }
      }
    },
    "Alternatives": {
      "type": "array",
      "description": "Options considered and rejected",
      "items": {
        "$ref": "#/definitions/Alternative"
      }
    },
    "Alternative": {
      "type": "object",
      "required": ["option", "rationale_rejected"],
      "additionalProperties": false,
      "properties": {
        "option": {
          "type": "string",
          "description": "Name or description of the rejected alternative"
        },
        "rationale_rejected": {
          "type": "string",
          "description": "Why this option was not selected"
        },
        "consequences_if_chosen": {
          "type": "object",
          "description": "Hypothetical consequences if this alternative had been selected",
          "additionalProperties": false,
          "properties": {
            "positive": {
              "type": "array",
              "items": { "type": "string" }
            },
            "negative": {
              "type": "array",
              "items": { "type": "string" }
            }
          }
        }
      }
    },
    "Linked": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "requirements": {
          "type": "array",
          "description": "Requirement identifiers that motivate or are satisfied by this decision",
          "items": { "type": "string" }
        },
        "supersedes": {
          "type": ["string", "null"],
          "description": "ADR ID that this decision replaces (if any)",
          "pattern": "^[A-Z]{2,4}-[0-9]{4,}$"
        },
        "superseded_by": {
          "type": ["string", "null"],
          "description": "ADR ID that has replaced this decision (if status is superseded)",
          "pattern": "^[A-Z]{2,4}-[0-9]{4,}$"
        },
        "related_adrs": {
          "type": "array",
          "description": "Other ADRs that relate to this decision",
          "items": { "type": "string", "pattern": "^[A-Z]{2,4}-[0-9]{4,}$" }
        },
        "code_paths": {
          "type": "array",
          "description": "File paths, modules, or repositories implementing this decision",
          "items": { "type": "string" }
        },
        "stakeholders": {
          "type": "array",
          "description": "Teams or individuals with interest in this decision",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "name": { "type": "string" },
              "role": { "type": "string" },
              "concern": { "type": "string" }
            }
          }
        }
      }
    },
    "DerivedConstraints": {
      "type": "array",
      "description": "Machine-verifiable constraints extracted from this ADR for fitness functions",
      "items": {
        "$ref": "#/definitions/Constraint"
      }
    },
    "Constraint": {
      "type": "object",
      "required": ["id", "source_adr", "predicate", "severity"],
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string",
          "description": "Unique constraint identifier",
          "pattern": "^CON-[0-9]+$"
        },
        "source_adr": {
          "type": "string",
          "description": "ADR ID from which this constraint was derived",
          "pattern": "^[A-Z]{2,4}-[0-9]{4,}$"
        },
        "predicate": {
          "type": "string",
          "description": "Human-readable statement of what must hold true"
        },
        "target": {
          "type": "string",
          "description": "Fitness function or verification target (e.g., test suite name, linter rule)"
        },
        "severity": {
          "type": "string",
          "enum": ["must", "should", "may"],
          "description": "RFC 2119 compliance level"
        },
        "automation_hint": {
          "type": "object",
          "description": "Machine-parseable hint for automated constraint checking",
          "additionalProperties": true,
          "properties": {
            "tool": {
              "type": "string",
              "description": "Tool that can verify this constraint"
            },
            "config_ref": {
              "type": "string",
              "description": "Reference to tool-specific configuration"
            }
          }
        }
      }
    }
  }
}
```

## Field Semantics

### `meta.id`

Format: `[PREFIX]-[NUMBER]`
- Prefix: 2-4 uppercase letters (e.g., `ADR`, `ARC`, `SEC`)
- Number: 4+ digits with leading zeros (e.g., `0042`)
- This ensures sortability and collision avoidance in large registries

### `meta.status` and `meta.status_history`

The `status` field reflects the current state. `status_history` provides a complete audit trail of transitions. When an ADR transitions, both the `status` field and `status_history` must be updated atomically.

### `context.forces`

Forces are competing pressures that make the decision non-trivial. Example forces:
- "compliance-sox" (regulatory)
- "performance-latency-p99" (operational)
- "team-kotlin-expertise" (human)
- "cost-infrastructure" (financial)

### `context.constraints`

Hard boundaries that cannot be violated. Constraints differ from forces in that they are inviolable. Example constraints:
- "must-run-on-aws-us-east-1"
- "must-support-100k-concurrent-users"
- "must-integrate-with-existing-active-directory"

### `alternatives`

Every significant alternative considered during deliberation must be recorded. The `rationale_rejected` field is the single most important field for future maintainers wondering "why didn't we do X?"

### `linked.supersedes` / `linked.superseded_by`

When an ADR supersedes another:
1. The new ADR sets `linked.supersedes` to the old ADR ID
2. The old ADR is updated: `meta.status` becomes `superseded`, and `linked.superseded_by` points to the new ADR
3. Both ADRs receive a `status_history` entry documenting the transition

### `derived_constraints`

Constraints may be:
- **Embedded**: Author explicitly writes constraints during ADR creation
- **Extracted**: `scripts/validate_adr.py --extract-constraints` generates constraints automatically from decision text
- **Curated**: `architecture-fitness-function` team reviews and approves derived constraints

## Validation Levels

| Level | Required Fields | Recommended Fields | Notes |
|-------|----------------|-------------------|-------|
| Minimal | `meta.id`, `meta.date`, `meta.status`, `context.problem`, `decision.statement` | | Emergency/hotfix path |
| Standard | All minimal + `meta.authors`, `context.forces`, `consequences`, `alternatives` | | Normal workflow |
| Strict | All standard + `meta.tags`, `context.constraints`, `context.scope`, `linked.requirements`, `linked.code_paths` | | Production registry |
| Full | All strict + `meta.status_history`, `derived_constraints` | | Audited environments |

## Example: Complete Document

```json
{
  "meta": {
    "id": "ADR-0042",
    "date": "2024-06-15",
    "status": "accepted",
    "authors": ["jane.architect@example.com", "platform-team"],
    "version": "1.0.0",
    "tags": ["security", "compliance", "data-model"],
    "status_history": [
      {
        "from": "proposed",
        "to": "accepted",
        "date": "2024-06-15T14:30:00Z",
        "actor": "tech-lead-council",
        "reason": "Approved in architecture review board meeting #24"
      }
    ]
  },
  "context": {
    "problem": "Audit log entries must be tamper-evident to satisfy SOX compliance requirements",
    "background": "Current audit logging uses standard PostgreSQL tables with UPDATE/DELETE permissions. External auditors flagged this as a control gap.",
    "forces": [
      "compliance-sox-section-302",
      "operational-simplicity",
      "cost-minimize-infrastructure",
      "performance-write-latency-under-50ms"
    ],
    "constraints": [
      "must-use-existing-postgresql-cluster",
      "must-not-require-application-code-changes",
      "must-support-7-year-retention"
    ],
    "assumptions": [
      "PostgreSQL 15+ with row-level security enabled",
      "Archive storage is available for cold data"
    ],
    "scope": {
      "system": "financial-platform",
      "subsystem": "audit-logging",
      "bounded_context": "compliance",
      " Applies_to": ["all-mutation-operations"],
      "exclusions": ["read-only-reporting-views"]
    }
  },
  "decision": {
    "statement": "Implement append-only audit tables with cryptographic hash chaining per row, enforced via PostgreSQL triggers and row-level security",
    "rationale": "Append-only semantics with hash chaining provide tamper-evidence without additional infrastructure. PostgreSQL triggers enforce immutability at the database layer, requiring zero application changes.",
    "option_details": {
      "table_schema": "audit.events with created_at, event_hash, previous_hash columns",
      "enforcement": "BEFORE UPDATE/DELETE trigger raises exception",
      "hash_algorithm": "SHA-256",
      "partitioning": "Monthly partitions by created_at for retention management"
    }
  },
  "consequences": {
    "positive": [
      "Zero application code changes required",
      "Cryptographic tamper detection at row level",
      "Uses existing database infrastructure",
      "Partitioning supports efficient archival"
    ],
    "negative": [
      "Table growth is unbounded without archival",
      "Hash computation adds ~2ms per write",
      "Cannot modify historical records even for legitimate corrections (requires compensating transaction pattern)"
    ],
    "neutral": [
      "Standard PostgreSQL backup strategies apply",
      "No impact on read query performance"
    ]
  },
  "alternatives": [
    {
      "option": "Separate immutable ledger database (e.g., Amazon QLDB)",
      "rationale_rejected": "Adds $12k/month infrastructure cost and requires new operational expertise. Benefit over PostgreSQL append-only is marginal for our threat model.",
      "consequences_if_chosen": {
        "positive": ["Native cryptographic verification", "Managed service"],
        "negative": ["Vendor lock-in", "Operational complexity", "Cost"]
      }
    },
    {
      "option": "Application-layer audit framework",
      "rationale_rejected": "Would require modifying 47 microservices. Enforcement is not guaranteed (bugs can bypass).",
      "consequences_if_chosen": {
        "positive": ["Flexible event schema"],
        "negative": ["High implementation cost", "Enforcement gaps"]
      }
    }
  ],
  "linked": {
    "requirements": ["REQ-1105", "REQ-2049", "SOX-CTRL-7.2"],
    "supersedes": null,
    "superseded_by": null,
    "related_adrs": ["ADR-0030", "ADR-0018"],
    "code_paths": [
      "infra/terraform/postgresql/audit-triggers.tf",
      "services/audit-log/",
      "db/migrations/V024__audit_hash_chain.sql"
    ],
    "stakeholders": [
      {
        "name": "compliance-team",
        "role": "reviewer",
        "concern": "SOX audit trail integrity"
      },
      {
        "name": "platform-team",
        "role": "implementer",
        "concern": "Operational manageability"
      }
    ]
  },
  "derived_constraints": [
    {
      "id": "CON-1",
      "source_adr": "ADR-0042",
      "predicate": "Audit events table must reject UPDATE and DELETE operations",
      "target": "db-migration-tests",
      "severity": "must",
      "automation_hint": {
        "tool": "postgresql-integration-test",
        "config_ref": "tests/db/test_audit_immutability.py"
      }
    },
    {
      "id": "CON-2",
      "source_adr": "ADR-0042",
      "predicate": "Every audit row must have a non-null event_hash",
      "target": "db-schema-validation",
      "severity": "must",
      "automation_hint": {
        "tool": "sqlalchemy-model-check",
        "config_ref": "models/audit.py:Event.hash_column"
      }
    },
    {
      "id": "CON-3",
      "source_adr": "ADR-0042",
      "predicate": "Audit table write latency must remain under 50ms p99",
      "target": "performance-tests",
      "severity": "should",
      "automation_hint": {
        "tool": "k6-load-test",
        "config_ref": "perf/audit-write-latency.js"
      }
    }
  ]
}
```

## Constraint Derivation Rules

When using `--extract-constraints`, the validator applies these heuristics:

1. **Immutability detection**: Keywords like "append-only", "immutable", "cannot delete", "no UPDATE" generate `must` constraints on write operations.

2. **Performance thresholds**: Numeric patterns like "under 50ms", "p99 < 200ms", "100k concurrent" generate `should` constraints with latency/throughput targets.

3. **Scope enforcement**: `context.scope` boundaries generate `must` constraints on cross-boundary coupling.

4. **Technology lock-in**: Decisions selecting specific technologies generate `must` constraints on dependency presence.

5. **Security posture**: Decisions mentioning encryption, authentication, or authorization generate `must` constraints on security controls.

## Extension Points

The schema supports controlled extension:

- `decision.option_details`: Arbitrary key-value pairs for implementation specifics
- `automation_hint`: Tool-specific configuration references
- Additional `meta.tags` values beyond the enum (validate with custom vocabulary)

Extensions should be documented in the project's ADR style guide.
