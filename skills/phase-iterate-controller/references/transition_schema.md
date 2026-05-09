# Transition JSON Schema

JSON schema definitions for all five transition types in the phase iteration controller.

## Common Definitions

```json
{
  "$defs": {
    "UUID": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    },
    "PhaseName": {
      "type": "string",
      "enum": ["INIT", "PLAN", "EXECUTE", "REVIEW", "VALIDATE", "DOCUMENT", "COMPLETE"]
    },
    "Timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "TransitionType": {
      "type": "string",
      "enum": ["NEXT", "RETRY", "ITERATE", "REPLAN", "ABORT"]
    }
  }
}
```

---

## 1. NEXT Transition

Forward progress. Simplest transition type.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "NextTransition",
  "type": "object",
  "required": ["uuid", "session_id", "from_phase", "to_phase", "type", "created_at"],
  "properties": {
    "uuid":          { "$ref": "#/$defs/UUID" },
    "session_id":    { "type": "string", "minLength": 1 },
    "from_phase":    { "$ref": "#/$defs/UUID" },
    "to_phase":      { "$ref": "#/$defs/UUID" },
    "type":          { "const": "NEXT" },
    "justification_hash": { "type": "null" },
    "delta_manifest":     { "type": "null" },
    "metadata": {
      "type": "object",
      "properties": {
        "triggered_by": { "type": "string", "description": "Phase exit criteria met" }
      }
    },
    "created_at": { "$ref": "#/$defs/Timestamp" }
  },
  "additionalProperties": false
}
```

---

## 2. RETRY Transition

Self-loop on the same phase for transient failures.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RetryTransition",
  "type": "object",
  "required": ["uuid", "session_id", "from_phase", "to_phase", "type", "metadata", "created_at"],
  "properties": {
    "uuid":          { "$ref": "#/$defs/UUID" },
    "session_id":    { "type": "string", "minLength": 1 },
    "from_phase":    { "$ref": "#/$defs/UUID" },
    "to_phase":      { "$ref": "#/$defs/UUID" },
    "type":          { "const": "RETRY" },
    "justification_hash": { "type": "null" },
    "delta_manifest":     { "type": "null" },
    "metadata": {
      "type": "object",
      "required": ["retry_count", "triggered_by"],
      "properties": {
        "retry_count":  { "type": "integer", "minimum": 1, "maximum": 5 },
        "triggered_by": { "type": "string", "minLength": 1, "description": "Transient failure description" },
        "previous_error": { "type": "string", "description": "Error message from failed attempt" }
      }
    },
    "created_at": { "$ref": "#/$defs/Timestamp" }
  },
  "additionalProperties": false
}
```

---

## 3. ITERATE Transition

Backward 1-2 phases with justification.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "IterateTransition",
  "type": "object",
  "required": ["uuid", "session_id", "from_phase", "to_phase", "type", "justification_hash", "metadata", "created_at"],
  "properties": {
    "uuid":          { "$ref": "#/$defs/UUID" },
    "session_id":    { "type": "string", "minLength": 1 },
    "from_phase":    { "$ref": "#/$defs/UUID" },
    "to_phase":      { "$ref": "#/$defs/UUID" },
    "type":          { "const": "ITERATE" },
    "justification_hash": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "SHA256 of reason_text + session_id + timestamp"
    },
    "delta_manifest": { "type": "null" },
    "metadata": {
      "type": "object",
      "required": ["iteration_depth", "triggered_by"],
      "properties": {
        "iteration_depth": {
          "type": "integer",
          "minimum": 1,
          "maximum": 5,
          "description": "Current iteration depth at target phase"
        },
        "triggered_by": { "type": "string", "minLength": 1 },
        "target_phase_name": { "$ref": "#/$defs/PhaseName", "description": "Human-readable target" },
        "steps_back": { "type": "integer", "minimum": 1, "maximum": 2 }
      }
    },
    "created_at": { "$ref": "#/$defs/Timestamp" }
  },
  "additionalProperties": false
}
```

---

## 4. REPLAN Transition

Jump to PLAN phase with delta manifest.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ReplanTransition",
  "type": "object",
  "required": ["uuid", "session_id", "from_phase", "to_phase", "type", "justification_hash", "delta_manifest", "metadata", "created_at"],
  "properties": {
    "uuid":          { "$ref": "#/$defs/UUID" },
    "session_id":    { "type": "string", "minLength": 1 },
    "from_phase":    { "$ref": "#/$defs/UUID" },
    "to_phase":      { "$ref": "#/$defs/UUID" },
    "type":          { "const": "REPLAN" },
    "justification_hash": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "SHA256 of discovery_description + session_id + timestamp"
    },
    "delta_manifest": { "$ref": "#/$defs/UUID", "description": "Reference to delta manifest artifact" },
    "metadata": {
      "type": "object",
      "required": ["replan_count", "triggered_by"],
      "properties": {
        "replan_count": { "type": "integer", "minimum": 1, "maximum": 3 },
        "triggered_by": { "type": "string", "minLength": 1 },
        "scope_change": { "type": "boolean" },
        "invalidated_phases": {
          "type": "array",
          "items": { "$ref": "#/$defs/PhaseName" }
        }
      }
    },
    "created_at": { "$ref": "#/$defs/Timestamp" }
  },
  "additionalProperties": false
}
```

---

## 5. ABORT Transition

Terminal transition. Ends the session.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AbortTransition",
  "type": "object",
  "required": ["uuid", "session_id", "from_phase", "to_phase", "type", "justification_hash", "metadata", "created_at"],
  "properties": {
    "uuid":          { "$ref": "#/$defs/UUID" },
    "session_id":    { "type": "string", "minLength": 1 },
    "from_phase":    { "$ref": "#/$defs/UUID" },
    "to_phase":      { "type": "null", "description": "No target phase; session terminates" },
    "type":          { "const": "ABORT" },
    "justification_hash": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$",
      "description": "SHA256 of abort_reason + session_id + timestamp"
    },
    "delta_manifest": { "type": "null" },
    "metadata": {
      "type": "object",
      "required": ["abort_reason", "triggered_by"],
      "properties": {
        "abort_reason": {
          "type": "string",
          "enum": ["SAFETY", "UNRECOVERABLE", "HUMAN", "TIMEOUT"]
        },
        "triggered_by": { "type": "string", "minLength": 1 },
        "final_phase": { "$ref": "#/$defs/PhaseName" },
        "cleanup_status": {
          "type": "string",
          "enum": ["CLEAN", "DIRTY", "INCOMPLETE"]
        }
      }
    },
    "created_at": { "$ref": "#/$defs/Timestamp" }
  },
  "additionalProperties": false
}
```

---

## Combined Transition (Discriminated Union)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PhaseTransition",
  "oneOf": [
    { "$ref": "#/$defs/NextTransition" },
    { "$ref": "#/$defs/RetryTransition" },
    { "$ref": "#/$defs/IterateTransition" },
    { "$ref": "#/$defs/ReplanTransition" },
    { "$ref": "#/$defs/AbortTransition" }
  ],
  "discriminator": {
    "propertyName": "type"
  }
}
```

## Validation Rules (Engine-Side)

The following constraints are enforced by the policy engine and are not expressible in JSON Schema
alone:

| Rule | Description | Error Code |
|------|-------------|------------|
| `from_phase` must exist | Source phase instance UUID must be in session DAG | `UNKNOWN_SOURCE` |
| `to_phase` must not already have `transition_out` | Target must be the current leaf node | `NOT_LEAF_NODE` |
| `retry_count` monotonic | Must equal prior retry_count + 1 | `RETRY_COUNT_JUMP` |
| `iteration_depth` ≤ budget | Checked against session config | `ITERATION_DEPTH_EXCEEDED` |
| `replan_count` ≤ budget | Checked against session config | `REPLAN_COUNT_EXCEEDED` |
| No 2-cycle | Block A→B→A within 2 steps | `CYCLE_DETECTED` |
| ITERATE target distance ≤ 2 | steps_back must be 1 or 2 | `ITERATE_TOO_FAR` |
| ABORT always allowed | Even when other budgets exhausted | — |
