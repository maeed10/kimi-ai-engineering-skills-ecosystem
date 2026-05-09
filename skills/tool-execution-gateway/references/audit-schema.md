# Audit Log JSON Schema

This schema defines the structure of every immutable audit log entry produced by the Tool Execution Gateway.

## Schema Definition

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ToolExecutionGatewayAuditEntry",
  "description": "Immutable audit log entry for a single tool call interception and decision event.",
  "type": "object",
  "required": [
    "audit_ref",
    "timestamp",
    "skill",
    "tool",
    "args_hash",
    "decision",
    "risk_score",
    "gate_results"
  ],
  "properties": {
    "audit_ref": {
      "type": "string",
      "format": "uuid",
      "description": "Unique v4 UUID for this audit entry. Immutable reference for lookups and incident response."
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "UTC ISO 8601 timestamp when the decision was recorded."
    },
    "skill": {
      "type": "string",
      "description": "Name of the calling skill that initiated the tool call."
    },
    "tool": {
      "type": "string",
      "description": "Name of the requested tool or function."
    },
    "args_hash": {
      "type": "string",
      "pattern": "^sha256:[a-f0-9]{64}$",
      "description": "SHA-256 hash of the redacted argument payload. Secrets are replaced with <REDACTED> before hashing."
    },
    "redacted_args_preview": {
      "type": "string",
      "maxLength": 500,
      "description": "Human-readable summary of redacted arguments for quick inspection. No secrets or raw values."
    },
    "decision": {
      "type": "string",
      "enum": ["AUTO_APPROVED", "PENDING_OVERRIDE", "BLOCKED", "EXEC_ERROR", "OVERRIDE_GRANTED"],
      "description": "Final execution decision issued by the Gateway."
    },
    "risk_score": {
      "type": "integer",
      "minimum": 0,
      "maximum": 10,
      "description": "Risk score assigned to this call. 0 = no risk, 10 = critical."
    },
    "gate_results": {
      "type": "object",
      "required": ["capability", "idempotency", "rate_limit", "path_safety", "sanitization"],
      "properties": {
        "capability": {
          "type": "object",
          "required": ["passed", "source"],
          "properties": {
            "passed": { "type": "boolean" },
            "source": { "type": "string", "enum": ["manifest", "temporary_grant", "denied"] },
            "grant_expiry": { "type": "string", "format": "date-time", "description": "If temporary grant, when it expires." }
          }
        },
        "idempotency": {
          "type": "object",
          "required": ["passed", "classification"],
          "properties": {
            "passed": { "type": "boolean" },
            "classification": { "type": "string", "enum": ["idempotent", "non_idempotent", "read_only"] },
            "requires_override": { "type": "boolean" }
          }
        },
        "rate_limit": {
          "type": "object",
          "required": ["passed", "turn_call_count", "token_estimate"],
          "properties": {
            "passed": { "type": "boolean" },
            "turn_call_count": { "type": "integer", "minimum": 0 },
            "token_estimate": { "type": "integer", "minimum": 0 },
            "limit_hit": { "type": "boolean" }
          }
        },
        "path_safety": {
          "type": "object",
          "required": ["passed", "paths_checked"],
          "properties": {
            "passed": { "type": "boolean" },
            "paths_checked": { "type": "array", "items": { "type": "string" } },
            "traversal_detected": { "type": "boolean" }
          }
        },
        "sanitization": {
          "type": "object",
          "required": ["passed", "shell_metacharacters_found"],
          "properties": {
            "passed": { "type": "boolean" },
            "shell_metacharacters_found": { "type": "array", "items": { "type": "string" } },
            "command_preview": { "type": "string", "description": "Sanitized command string with secrets removed." }
          }
        },
        "network_whitelist": {
          "type": "object",
          "required": ["passed"],
          "properties": {
            "passed": { "type": "boolean" },
            "domain": { "type": "string" },
            "whitelisted": { "type": "boolean" }
          }
        }
      }
    },
    "execution_result": {
      "type": "object",
      "description": "Populated only if decision is AUTO_APPROVED or OVERRIDE_GRANTED.",
      "properties": {
        "status": { "type": "string", "enum": ["success", "failure", "timeout"] },
        "elapsed_ms": { "type": "integer", "minimum": 0 },
        "output_hash": { "type": "string", "pattern": "^sha256:[a-f0-9]{64}$" },
        "output_preview": { "type": "string", "maxLength": 1000 }
      }
    },
    "override_record": {
      "type": "object",
      "description": "Populated only if human override was involved.",
      "properties": {
        "granted_by": { "type": "string", "enum": ["user", "orchestrator", "system"] },
        "justification": { "type": "string" },
        "grant_duration_minutes": { "type": "integer", "minimum": 1 },
        "revoked_at": { "type": "string", "format": "date-time" }
      }
    },
    "error_details": {
      "type": "object",
      "description": "Populated only if decision is BLOCKED or EXEC_ERROR.",
      "properties": {
        "reason": { "type": "string" },
        "remediation": { "type": "string" },
        "gate_failed": { "type": "string" }
      }
    },
    "context_budget": {
      "type": "object",
      "properties": {
        "tokens_used_before": { "type": "integer", "minimum": 0 },
        "tokens_used_after": { "type": "integer", "minimum": 0 },
        "ceiling_breached": { "type": "boolean" }
      }
    }
  }
}
```

## Example Entry

```json
{
  "audit_ref": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-01-15T09:23:17Z",
  "skill": "refactoring-engine",
  "tool": "edit_file",
  "args_hash": "sha256:a3b8c9d...e4f5",
  "redacted_args_preview": "edit_file(path=src/utils.py, old=...utils..., new=...helpers...)",
  "decision": "AUTO_APPROVED",
  "risk_score": 3,
  "gate_results": {
    "capability": { "passed": true, "source": "manifest" },
    "idempotency": { "passed": true, "classification": "non_idempotent", "requires_override": false },
    "rate_limit": { "passed": true, "turn_call_count": 2, "token_estimate": 1200, "limit_hit": false },
    "path_safety": { "passed": true, "paths_checked": ["src/utils.py"], "traversal_detected": false },
    "sanitization": { "passed": true, "shell_metacharacters_found": [], "command_preview": "" },
    "network_whitelist": { "passed": true, "whitelisted": true }
  },
  "execution_result": {
    "status": "success",
    "elapsed_ms": 45,
    "output_hash": "sha256:7f8e9d...c3b2",
    "output_preview": "1 file changed, 12 insertions(+), 8 deletions(-)"
  },
  "context_budget": {
    "tokens_used_before": 14500,
    "tokens_used_after": 15700,
    "ceiling_breached": false
  }
}
```
