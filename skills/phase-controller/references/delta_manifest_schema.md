# Delta Manifest Schema

Delta manifest format required for every `REPLAN` transition. Describes what changed, which prior
phases are affected, and how the plan must be revised.

## Full JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "DeltaManifest",
  "type": "object",
  "required": [
    "replan_id",
    "session_id",
    "triggered_in_phase",
    "discovery_description",
    "affected_prior_phases",
    "plan_delta",
    "risk_assessment",
    "confidence",
    "human_review_required",
    "created_at"
  ],
  "properties": {
    "replan_id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique identifier for this REPLAN event"
    },
    "session_id": {
      "type": "string",
      "description": "Parent session UUID"
    },
    "triggered_in_phase": {
      "type": "string",
      "enum": ["INGEST", "UNDERSTAND", "PLAN", "ASSESS", "EXECUTE", "DELIVER", "VALIDATE", "REMEMBER"],
      "description": "Phase where the new information was discovered"
    },
    "triggering_transition_id": {
      "type": "string",
      "format": "uuid",
      "description": "Optional: the transition edge that revealed the new information"
    },
    "discovery_description": {
      "type": "string",
      "minLength": 10,
      "maxLength": 2000,
      "description": "Narrative description of what changed and why the current plan is invalid"
    },
    "affected_prior_phases": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "string",
        "enum": ["INGEST", "UNDERSTAND", "PLAN", "ASSESS", "EXECUTE", "DELIVER", "VALIDATE"]
      },
      "description": "Phases whose artifacts are invalidated by this replan"
    },
    "plan_delta": {
      "type": "object",
      "required": ["added", "removed", "modified"],
      "properties": {
        "added": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["item_id", "description", "rationale"],
            "properties": {
              "item_id": { "type": "string", "minLength": 1 },
              "description": { "type": "string", "minLength": 1 },
              "rationale": { "type": "string", "description": "Why this item was added" },
              "estimated_effort": {
                "type": "string",
                "enum": ["low", "medium", "high"]
              }
            }
          }
        },
        "removed": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["item_id", "reason"],
            "properties": {
              "item_id": { "type": "string", "minLength": 1 },
              "reason": { "type": "string", "description": "Why this item was removed" }
            }
          }
        },
        "modified": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["item_id", "field", "old_value", "new_value"],
            "properties": {
              "item_id": { "type": "string", "minLength": 1 },
              "field": { "type": "string", "description": "Which field changed" },
              "old_value": { "type": "string" },
              "new_value": { "type": "string" },
              "change_reason": { "type": "string" }
            }
          }
        }
      }
    },
    "risk_assessment": {
      "type": "object",
      "required": ["scope_change", "complexity_delta"],
      "properties": {
        "scope_change": {
          "type": "boolean",
          "description": "True if new work is added or existing committed work is removed"
        },
        "complexity_delta": {
          "type": "integer",
          "description": "Net change in task count (+N added, -N removed)"
        },
        "risk_level": {
          "type": "string",
          "enum": ["low", "medium", "high", "critical"],
          "description": "Agent-assessed risk of the replan succeeding"
        }
      }
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "Agent's confidence (0.0–1.0) that the revised plan will succeed"
    },
    "human_review_required": {
      "type": "boolean",
      "description": "Auto-set true if scope_change=true or |complexity_delta|>threshold"
    },
    "human_review_reason": {
      "type": "string",
      "description": "Required when human_review_required=true; explains why human input is needed"
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "additionalProperties": false
}
```

## Minimal Valid Example

```json
{
  "replan_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "session_id": "sess-001",
  "triggered_in_phase": "EXECUTE",
  "discovery_description": "API rate limits discovered during EXECUTE are 10x lower than planned. Batch processing strategy must be redesigned with pagination and backoff.",
  "affected_prior_phases": ["PLAN", "EXECUTE"],
  "plan_delta": {
    "added": [
      {
        "item_id": "task-paginate",
        "description": "Implement request pagination",
        "rationale": "Required due to rate limit constraints",
        "estimated_effort": "medium"
      }
    ],
    "removed": [
      {
        "item_id": "task-bulk-upload",
        "reason": "Bulk upload incompatible with 10 req/min rate limit"
      }
    ],
    "modified": [
      {
        "item_id": "task-api-client",
        "field": "retry_strategy",
        "old_value": "3 retries with linear backoff",
        "new_value": "exponential backoff with jitter, max 10 retries",
        "change_reason": "Rate limits require more aggressive backoff"
      }
    ]
  },
  "risk_assessment": {
    "scope_change": true,
    "complexity_delta": 2,
    "risk_level": "medium"
  },
  "confidence": 0.78,
  "human_review_required": true,
  "human_review_reason": "Scope change adds 2 tasks and removes 1; timeline impact unknown",
  "created_at": "2024-01-15T09:30:00Z"
}
```

## Field Semantics

### `affected_prior_phases`

Determines the invalidation scope. Each listed phase has all its artifacts marked
`INVALIDATED_BY` this replan transition. Phases NOT listed remain valid and their artifacts are
reused.

Common patterns:

| Trigger Phase | Affected Phases | Rationale |
|---------------|-----------------|-----------|
| EXECUTE       | PLAN, EXECUTE   | Plan assumptions wrong, exec work invalid |
| VALIDATE      | EXECUTE         | Implementation correct but doesn't meet spec |
| DELIVER       | EXECUTE, DELIVER | Packaging issues, redo with same plan |

### `human_review_required` Auto-Triggers

The following conditions force `human_review_required = true`:

- `scope_change` is `true`
- `|complexity_delta|` ≥ 3 (default threshold)
- `risk_level` is `critical`
- `confidence` < 0.5

When `human_review_required` is true, the REPLAN transition enters `PENDING_HUMAN` state and the
agent must not proceed until explicit human approval is logged.

### `plan_delta` Rules

- Every `item_id` in `removed` must exist in the current plan.
- Every `item_id` in `modified` must exist in the current plan.
- `added` items receive new IDs; collision with existing IDs is an error.
- At least one of `added`, `removed`, or `modified` must be non-empty.
