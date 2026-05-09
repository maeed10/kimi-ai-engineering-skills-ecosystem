# Rule Schema Reference

## Overview

This document defines the authoritative JSON schema for policy rule files consumed by the `policy-engine`. Every `.json` file under the `policy/` directory must conform to this schema. The engine validates file integrity (SHA-256) and structural correctness before loading any rule into the runtime registry.

## Schema Version

- **Current:** `4.0.0`
- **Required field:** `version` (SemVer) inside each policy file and each rule
- **Ecosystem alignment:** The manifest `ecosystem_version` must match the orchestrator's declared version or the engine halts session startup.

---

## Policy File Root Schema

A policy file is a JSON object with a top-level `rules` array.

```json
{
  "$schema": "https://kimi.ai/skills/policy-engine/v4.0.0/policy-file.json",
  "version": "4.0.0",
  "description": "Optional human-readable summary of this policy set",
  "rules": [
    { /* Rule object */ }
  ]
}
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `$schema` | string | No | URI identifying the schema version (documentation only) |
| `version` | string | **Yes** | SemVer of this policy file. Must match manifest expectations. |
| `description` | string | No | Human-readable summary |
| `rules` | array[Rule] | **Yes** | Non-empty array of rule definitions |

---

## Rule Object Schema

Each rule defines a typed safety constraint with conditions, severity, and action.

```json
{
  "rule_id": "FS-001",
  "version": "4.0.0",
  "rule_type": "filesystem",
  "directive": "NEVER",
  "severity": "critical",
  "description": "Prevent writing to system directories",
  "conditions": { /* Condition object */ },
  "action": "block",
  "applies_to": { /* AppliesTo object */ },
  "metadata": { /* Metadata object */ }
}
```

| Property | Type | Required | Valid Values | Description |
|----------|------|----------|--------------|-------------|
| `rule_id` | string | **Yes** | `[A-Z0-9-]+` | Globally unique rule identifier |
| `version` | string | **Yes** | SemVer | Rule version for drift tracking |
| `rule_type` | string | **Yes** | `filesystem`, `network`, `execution`, `data`, `phase`, `skill` | Domain this rule protects |
| `directive` | string | **Yes** | `ALWAYS`, `NEVER` | Whether the rule is a mandatory requirement or a prohibition |
| `severity` | string | **Yes** | `info`, `warning`, `error`, `critical` | Impact level if triggered |
| `description` | string | **Yes** | free text | Human-readable explanation |
| `conditions` | Condition | **Yes** | see below | Logical predicates that determine if the rule triggers |
| `action` | string | **Yes** | `allow`, `block`, `escalate` | Default action when rule triggers |
| `applies_to` | AppliesTo | **Yes** | see below | Tool and phase scope |
| `metadata` | Metadata | No | see below | Optional rationale, remediation, tags |

### Notes on Directive Semantics

- **`NEVER`**: The rule triggers when its conditions match the request. A triggered `NEVER` rule blocks execution.
- **`ALWAYS`**: The rule defines a mandatory property. If the conditions match, it means the request **fails** the mandatory requirement and is blocked. To express a positive constraint (e.g., "path MUST be under /safe"), define the condition so it matches the *unsafe* case, making the `ALWAYS` rule trigger on violation.

---

## Condition Object Schema

Conditions support nested boolean logic via `operator`, a flat list of `predicates`, and recursive `sub_conditions`.

```json
{
  "operator": "ALL_OF",
  "predicates": [
    { "field": "path", "operator": "prefix", "value": "/etc" }
  ],
  "sub_conditions": [
    { /* nested Condition */ }
  ]
}
```

| Property | Type | Required | Valid Values | Description |
|----------|------|----------|--------------|-------------|
| `operator` | string | **Yes** | `ALL_OF`, `ANY_OF`, `NOT` | Boolean combinator |
| `predicates` | array[Predicate] | No | see below | Flat list of leaf conditions |
| `sub_conditions` | array[Condition] | No | see below | Nested condition blocks |

### Predicate Object Schema

```json
{
  "field": "path",
  "operator": "prefix",
  "value": "/etc"
}
```

| Property | Type | Required | Valid Values | Description |
|----------|------|----------|--------------|-------------|
| `field` | string | **Yes** | dot-path | Payload field to evaluate (supports nesting via `a.b.c`) |
| `operator` | string | **Yes** | `eq`, `ne`, `prefix`, `suffix`, `contains`, `regex`, `in`, `gt`, `gte`, `lt`, `lte` | Comparison operator |
| `value` | any | **Yes** | depends on operator | Target value for comparison |

#### Operator Reference

| Operator | `value` Type | Behavior |
|----------|--------------|----------|
| `eq` | any | Strict equality (`==`) |
| `ne` | any | Strict inequality (`!=`) |
| `prefix` | string | String starts with value |
| `suffix` | string | String ends with value |
| `contains` | string | String contains value |
| `regex` | string | Regular expression match (`re.search`) |
| `in` | array | Value is contained in the provided array |
| `gt` | number | Greater than |
| `gte` | number | Greater than or equal |
| `lt` | number | Less than |
| `lte` | number | Less than or equal |

### Condition Evaluation Semantics

- **`ALL_OF`**: Every predicate and every sub_condition must evaluate to `true`.
- **`ANY_OF`**: At least one predicate or one sub_condition must evaluate to `true`.
- **`NOT`**: The entire block (predicates + sub_conditions) must evaluate to `false`.

An empty condition block (no predicates, no sub_conditions) evaluates to:
- `ALL_OF` → `true` (vacuous truth)
- `ANY_OF` → `false`
- `NOT` → `true` (negation of vacuous `ALL_OF`)

---

## AppliesTo Object Schema

```json
{
  "tools": ["write_file", "edit_file"],
  "phases": ["*"]
}
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `tools` | array[string] | **Yes** | Tool names this rule guards. Use `["*"]` for all tools. |
| `phases` | array[string] | **Yes** | Phase names this rule applies in. Use `["*"]` for all phases. |

---

## Metadata Object Schema

```json
{
  "rationale": "System directory writes compromise host integrity",
  "remediation": "Write to /mnt/agents/output or request sandboxed path",
  "tags": ["host-security", "filesystem"],
  "owner": "security-team",
  "review_date": "2025-06-01"
}
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `rationale` | string | No | Why this rule exists |
| `remediation` | string | No | What the user/agent should do instead |
| `tags` | array[string] | No | Arbitrary classification tags |
| `owner` | string | No | Team or individual responsible |
| `review_date` | string (ISO8601) | No | Scheduled review date |

---

## Manifest Schema

The manifest (`policy/manifest.json`) lists all policy files with their SHA-256 hashes.

```json
{
  "ecosystem_version": "4.0.0",
  "manifest_hash": "sha256-of-this-manifest-canonical-form",
  "generated_at": "2025-01-15T09:00:00Z",
  "files": [
    {
      "path": "filesystem.json",
      "sha256": "abc123...",
      "description": "Filesystem safety rules"
    }
  ]
}
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `ecosystem_version` | string | **Yes** | Must match the running orchestrator |
| `manifest_hash` | string | **Yes** | SHA-256 of the manifest's canonical JSON (for self-integrity) |
| `generated_at` | string | No | ISO8601 timestamp of manifest generation |
| `files` | array[FileEntry] | **Yes** | Ordered list of policy files |

### FileEntry Schema

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | string | **Yes** | Relative path under `policy/` |
| `sha256` | string | **Yes** | SHA-256 of the file's raw bytes |
| `description` | string | No | Human-readable summary |

**Canonical form for `manifest_hash` computation:**
Sort keys alphabetically, use `separators=(",", ":")`, ensure UTF-8 encoding, exclude the `manifest_hash` field itself from the input payload.

---

## Complete Example: Multi-Type Policy File

```json
{
  "version": "4.0.0",
  "description": "Core safety rules for the Kimi v4.0 ecosystem",
  "rules": [
    {
      "rule_id": "FS-001",
      "version": "4.0.0",
      "rule_type": "filesystem",
      "directive": "NEVER",
      "severity": "critical",
      "description": "Prevent writes to system directories",
      "conditions": {
        "operator": "ANY_OF",
        "predicates": [
          { "field": "path", "operator": "prefix", "value": "/etc" },
          { "field": "path", "operator": "prefix", "value": "/usr/bin" },
          { "field": "path", "operator": "regex", "value": "^/sys/.*" }
        ]
      },
      "action": "block",
      "applies_to": {
        "tools": ["shell", "write_file", "edit_file"],
        "phases": ["*"]
      },
      "metadata": {
        "rationale": "System integrity",
        "remediation": "Use /mnt/agents/output or sandboxed paths"
      }
    },
    {
      "rule_id": "NET-007",
      "version": "4.0.0",
      "rule_type": "network",
      "directive": "ALWAYS",
      "severity": "error",
      "description": "Only allow HTTPS to known domains",
      "conditions": {
        "operator": "ANY_OF",
        "predicates": [
          { "field": "protocol", "operator": "ne", "value": "https" },
          { "field": "domain", "operator": "in", "value": ["api.github.com", "pypi.org"] }
        ]
      },
      "action": "block",
      "applies_to": {
        "tools": ["web_search", "browser_visit", "get_data_source"],
        "phases": ["*"]
      },
      "metadata": {
        "rationale": "Prevent data exfiltration to unknown endpoints"
      }
    },
    {
      "rule_id": "EXEC-009",
      "version": "4.0.0",
      "rule_type": "execution",
      "directive": "NEVER",
      "severity": "critical",
      "description": "Prevent recursive deletion of root",
      "conditions": {
        "operator": "ALL_OF",
        "predicates": [
          { "field": "command", "operator": "contains", "value": "rm" },
          { "field": "command", "operator": "regex", "value": "-r[fm]?" },
          { "field": "command", "operator": "regex", "value": "(/\s|\s/\s|\s/$)" }
        ]
      },
      "action": "block",
      "applies_to": {
        "tools": ["shell"],
        "phases": ["*"]
      },
      "metadata": {
        "rationale": "Host destruction protection"
      }
    },
    {
      "rule_id": "DATA-003",
      "version": "4.0.0",
      "rule_type": "data",
      "directive": "NEVER",
      "severity": "critical",
      "description": "Never emit unredacted SSNs",
      "conditions": {
        "operator": "ANY_OF",
        "predicates": [
          { "field": "response_text", "operator": "regex", "value": "\\b\\d{3}-\\d{2}-\\d{4}\\b" }
        ]
      },
      "action": "escalate",
      "applies_to": {
        "tools": ["*"],
        "phases": ["*"]
      },
      "metadata": {
        "rationale": "PII protection"
      }
    },
    {
      "rule_id": "PHASE-003",
      "version": "4.0.0",
      "rule_type": "phase",
      "directive": "NEVER",
      "severity": "critical",
      "description": "Prevent regression from DEPLOY to DESIGN",
      "conditions": {
        "operator": "ALL_OF",
        "predicates": [
          { "field": "from_phase", "operator": "eq", "value": "DEPLOY" },
          { "field": "to_phase", "operator": "eq", "value": "DESIGN" }
        ]
      },
      "action": "block",
      "applies_to": {
        "tools": ["phase_transition"],
        "phases": ["DEPLOY"]
      },
      "metadata": {
        "rationale": "Phase regression breaks traceability"
      }
    },
    {
      "rule_id": "SKILL-012",
      "version": "4.0.0",
      "rule_type": "skill",
      "directive": "NEVER",
      "severity": "error",
      "description": "Never activate sandbox-executor in ANALYSIS phase",
      "conditions": {
        "operator": "ALL_OF",
        "predicates": [
          { "field": "skill_name", "operator": "eq", "value": "sandbox-executor" },
          { "field": "current_phase", "operator": "eq", "value": "ANALYSIS" }
        ]
      },
      "action": "block",
      "applies_to": {
        "tools": ["skill_activation"],
        "phases": ["ANALYSIS"]
      },
      "metadata": {
        "rationale": "Sandbox execution is not permitted during analysis"
      }
    }
  ]
}
```

---

## Validation Rules

1. **Rule IDs must be unique across all loaded files.** If a duplicate is detected, the engine logs `POLICY_LOAD_FAILURE` and skips the conflicting rule.
2. **`rule_type` + `field` combinations must be sensible.** The engine does not enforce semantic validity (e.g., a `filesystem` rule referencing a `domain` field is syntactically valid but logically useless). Skill authors are responsible for semantic correctness.
3. **Circular sub_conditions are prohibited.** The engine detects recursion during parsing and raises `ValueError`.
4. **Empty `tools` or `phases` arrays are invalid.** Use `["*"]` to express universal scope.
5. **`manifest_hash` must be recomputed whenever any file entry changes.** Stale hashes cause session-start failures.

---

## Extending the Schema

When adding new rule types or operators:

1. Update this schema document.
2. Update `scripts/policy-engine.py` `ALLOWED_*` constants.
3. Add parser and evaluation logic in `PolicyEngine`.
4. Update the manifest `ecosystem_version` if the change is breaking.
5. Provide migration examples in the release notes.

---

**Schema Authority:** `policy-engine` skill  
**Version:** `4.0.0`  
**Last Updated:** 2025-01-15
