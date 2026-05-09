# Health Response JSON Schema

This document defines the canonical JSON Schema for all L0 enforcement-layer skill health endpoints (`/health` and `/ready`).

Every response must validate against this schema. Fields are ordered for human readability; parsers must not rely on field order.

---

## Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://kimi-cli.dev/schemas/l0/health-response.json",
  "title": "L0SkillHealthResponse",
  "description": "Standard health response envelope for L0 enforcement-layer skills.",
  "type": "object",
  "required": [
    "status",
    "last_successful_validation",
    "queue_depth",
    "error_rate_1m",
    "rule_count",
    "version",
    "uptime"
  ],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["healthy", "degraded", "unhealthy"],
      "description": "Aggregate health status derived from internal signals."
    },
    "last_successful_validation": {
      "type": "string",
      "format": "date-time",
      "description": "RFC 3339 UTC timestamp of the last successful policy validation or work item completion. Null if none yet."
    },
    "queue_depth": {
      "type": "integer",
      "minimum": 0,
      "description": "Current number of items awaiting processing in the skill's internal queue."
    },
    "error_rate_1m": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Ratio of failed requests/validations in the last 60 seconds. 0.0 = none, 1.0 = all failed."
    },
    "rule_count": {
      "type": "integer",
      "minimum": 0,
      "description": "Number of active rules/policies loaded in memory. 0 during initial load."
    },
    "version": {
      "type": "string",
      "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-([a-zA-Z0-9-]+(?:\\.[a-zA-Z0-9-]+)*))?(?:\\+([a-zA-Z0-9-]+(?:\\.[a-zA-Z0-9-]+)*))?$",
      "description": "Semantic version of the skill binary."
    },
    "uptime": {
      "type": "number",
      "minimum": 0,
      "description": "Seconds since process start. Float for sub-second precision."
    },
    "checks": {
      "type": "object",
      "description": "Optional sub-component health checks. Keys are check names; values are check results.",
      "additionalProperties": {
        "type": "object",
        "required": ["status"],
        "properties": {
          "status": {
            "type": "string",
            "enum": ["pass", "fail", "warn"]
          },
          "latency_ms": {
            "type": "number",
            "minimum": 0,
            "description": "Time taken to perform the check, in milliseconds."
          },
          "message": {
            "type": "string",
            "description": "Human-readable detail, especially for fail/warn states."
          }
        }
      }
    },
    "dependencies": {
      "type": "object",
      "description": "Optional upstream dependency health map.",
      "additionalProperties": {
        "type": "object",
        "required": ["reachable"],
        "properties": {
          "reachable": {
            "type": "boolean"
          },
          "latency_ms": {
            "type": "number",
            "minimum": 0
          },
          "last_check": {
            "type": "string",
            "format": "date-time"
          }
        }
      }
    }
  },
  "additionalProperties": false
}
```

---

## Examples

### Healthy State

```json
{
  "status": "healthy",
  "last_successful_validation": "2024-06-12T14:23:01Z",
  "queue_depth": 12,
  "error_rate_1m": 0.0,
  "rule_count": 847,
  "version": "2.4.1",
  "uptime": 86400.5,
  "checks": {
    "rule_store_sync": {
      "status": "pass",
      "latency_ms": 45.2,
      "message": "Last sync 45 ms ago"
    },
    "policy_engine_connection": {
      "status": "pass",
      "latency_ms": 12.0
    }
  },
  "dependencies": {
    "redis": {
      "reachable": true,
      "latency_ms": 0.8,
      "last_check": "2024-06-12T14:23:01Z"
    },
    "postgres": {
      "reachable": true,
      "latency_ms": 3.2,
      "last_check": "2024-06-12T14:23:01Z"
    }
  }
}
```

### Degraded State

```json
{
  "status": "degraded",
  "last_successful_validation": "2024-06-12T14:21:30Z",
  "queue_depth": 892,
  "error_rate_1m": 0.03,
  "rule_count": 847,
  "version": "2.4.1",
  "uptime": 86400.5,
  "checks": {
    "rule_store_sync": {
      "status": "pass",
      "latency_ms": 45.2
    },
    "policy_engine_connection": {
      "status": "warn",
      "latency_ms": 2100.0,
      "message": "Latency above 2 s SLA"
    }
  },
  "dependencies": {
    "redis": {
      "reachable": true,
      "latency_ms": 0.8,
      "last_check": "2024-06-12T14:23:01Z"
    },
    "postgres": {
      "reachable": true,
      "latency_ms": 3.2,
      "last_check": "2024-06-12T14:23:01Z"
    }
  }
}
```

### Unhealthy State

```json
{
  "status": "unhealthy",
  "last_successful_validation": "2024-06-12T14:20:00Z",
  "queue_depth": 1980,
  "error_rate_1m": 0.12,
  "rule_count": 0,
  "version": "2.4.1",
  "uptime": 86400.5,
  "checks": {
    "rule_store_sync": {
      "status": "fail",
      "latency_ms": 5005.0,
      "message": "Timeout contacting rule-store endpoint"
    },
    "policy_engine_connection": {
      "status": "fail",
      "latency_ms": 0,
      "message": "Connection refused"
    }
  },
  "dependencies": {
    "redis": {
      "reachable": false,
      "latency_ms": 0,
      "last_check": "2024-06-12T14:23:01Z"
    },
    "postgres": {
      "reachable": true,
      "latency_ms": 3.2,
      "last_check": "2024-06-12T14:23:01Z"
    }
  }
}
```

---

## Validation Rules

1. `status` must be derived from the worst of `checks` and `dependencies`, plus queue depth and error rate, using the decision matrix in SKILL.md.
2. `last_successful_validation` must be within 30 s of now for `healthy`, 30–120 s for `degraded`, and > 120 s (or null) for `unhealthy`.
3. `queue_depth` must reflect the instantaneous length of the work queue, not a time-series average.
4. `error_rate_1m` must be computed as `errors / total` over a rolling 60-second window. If `total` is zero, the value is `0.0`.
5. `rule_count` must be zero only during initial load or after a catastrophic rule store disconnect.
6. `uptime` must be monotonic within a single process lifetime.
7. `additionalProperties: false` means unknown fields are rejected by validators; do not add custom fields without a schema revision.

## Notes on Optional Sections

- `checks` is recommended but not required. Small skills with no external dependencies may omit it.
- `dependencies` is recommended when the skill connects to databases, caches, message buses, or other services.
- If present, both objects must follow the sub-schemas above (no extra fields, correct types).
