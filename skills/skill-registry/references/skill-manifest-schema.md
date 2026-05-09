# Skill Manifest JSON Schema

This document defines the canonical JSON Schema for skill capability manifests in the Kimi AI Engineering Skills Ecosystem v4.0. Every skill MUST provide a manifest conforming to this schema, either as a standalone `manifest.json` file or as frontmatter within `SKILL.md`.

The manifest is consumed by the `skill-registry` to enforce lifecycle management, prompt composition, policy validation, tool authorization, and sandbox configuration.

---

## Schema Overview

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for the skill. Must match directory name conventionally. |
| `version` | string | Yes | Semantic version of the skill (e.g., `4.0.0`). |
| `type` | string | Yes | Category: `core-infrastructure`, `utility`, `domain-specific`, `orchestrator`, `sandbox`. |
| `allowed_phases` | array[string] | Yes | Workflow phases in which this skill may become ACTIVE. |
| `required_permissions` | array[string] | No | Policy permissions that must be granted for activation. |
| `tools` | array[string] | Yes | Exact list of tool names this skill may invoke via the tool-execution-gateway. |
| `side_effects` | array[string] | No | Declared mutations: `file_write`, `network_request`, `process_spawn`, `state_mutation`. |
| `dependencies` | array[string] | No | Other skills that must be ACTIVE before this skill can activate. |
| `integrity_hash` | string | Yes | SHA-256 hash of the skill's canonical source files. |
| `required_capabilities` | object | No | Sandbox capability requirements forwarded to `sandbox-executor`. |
| `parameter_constraints` | object | No | Per-tool parameter validation rules. |
| `risk_level` | string | No | One of `low`, `medium`, `high`, `critical`. Defaults to `low`. |
| `author` | string | No | Author or maintainer identifier. |

---

## JSON Schema (Draft 7)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://kimi.ai/schemas/skill-manifest-v4.json",
  "title": "Kimi Skill Capability Manifest v4.0",
  "description": "Machine-readable capability manifest for skills in the Kimi AI Engineering Skills Ecosystem.",
  "type": "object",
  "required": [
    "name",
    "version",
    "type",
    "allowed_phases",
    "tools",
    "integrity_hash"
  ],
  "properties": {
    "name": {
      "type": "string",
      "description": "Unique skill identifier. Lowercase with hyphens.",
      "pattern": "^[a-z0-9-]+$",
      "minLength": 1,
      "maxLength": 64
    },
    "version": {
      "type": "string",
      "description": "Semantic version of the skill.",
      "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-((?:0|[1-9]\\d*|\\d*[a-zA-Z-][a-zA-Z0-9-]*)(?:\\.(?:0|[1-9]\\d*|\\d*[a-zA-Z-][a-zA-Z0-9-]*))*))?(?:\\+([0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*))?$"
    },
    "type": {
      "type": "string",
      "description": "Skill category.",
      "enum": [
        "core-infrastructure",
        "utility",
        "domain-specific",
        "orchestrator",
        "sandbox"
      ]
    },
    "allowed_phases": {
      "type": "array",
      "description": "Phases in which this skill may become ACTIVE. Empty array means the skill is never activated automatically.",
      "items": {
        "type": "string",
        "minLength": 1
      },
      "uniqueItems": true
    },
    "required_permissions": {
      "type": "array",
      "description": "Policy permissions required for this skill to transition to ACTIVE.",
      "items": {
        "type": "string",
        "minLength": 1
      },
      "uniqueItems": true
    },
    "tools": {
      "type": "array",
      "description": "Tool names this skill is authorized to invoke through the tool-execution-gateway.",
      "items": {
        "type": "string",
        "minLength": 1
      },
      "uniqueItems": true
    },
    "side_effects": {
      "type": "array",
      "description": "Declared side effects this skill may perform.",
      "items": {
        "type": "string",
        "enum": [
          "file_read",
          "file_write",
          "file_delete",
          "network_request",
          "process_spawn",
          "state_mutation",
          "shell_command",
          "database_access",
          "none"
        ]
      },
      "uniqueItems": true
    },
    "dependencies": {
      "type": "array",
      "description": "Skills that must be ACTIVE before this skill can become ACTIVE.",
      "items": {
        "type": "string",
        "minLength": 1
      },
      "uniqueItems": true
    },
    "integrity_hash": {
      "type": "string",
      "description": "SHA-256 hash of canonical skill source files (SKILL.md, manifest.json, scripts/*).",
      "pattern": "^[a-f0-9]{64}$"
    },
    "required_capabilities": {
      "type": "object",
      "description": "Sandbox capability requirements forwarded to sandbox-executor.",
      "additionalProperties": true,
      "properties": {
        "filesystem": {
          "type": "object",
          "properties": {
            "read_paths": {
              "type": "array",
              "items": { "type": "string" }
            },
            "write_paths": {
              "type": "array",
              "items": { "type": "string" }
            },
            "allow_absolute": {
              "type": "boolean"
            },
            "max_file_size_mb": {
              "type": "number",
              "minimum": 0
            }
          }
        },
        "network": {
          "type": "object",
          "properties": {
            "allow_outbound": {
              "type": "boolean"
            },
            "allowed_hosts": {
              "type": "array",
              "items": { "type": "string" }
            },
            "allowed_ports": {
              "type": "array",
              "items": { "type": "integer", "minimum": 1, "maximum": 65535 }
            }
          }
        },
        "process": {
          "type": "object",
          "properties": {
            "allow_spawn": {
              "type": "boolean"
            },
            "max_processes": {
              "type": "integer",
              "minimum": 0
            },
            "allowed_commands": {
              "type": "array",
              "items": { "type": "string" }
            }
          }
        },
        "resources": {
          "type": "object",
          "properties": {
            "max_memory_mb": {
              "type": "integer",
              "minimum": 0
            },
            "max_cpu_time_sec": {
              "type": "integer",
              "minimum": 0
            },
            "timeout_sec": {
              "type": "integer",
              "minimum": 0
            }
          }
        }
      }
    },
    "parameter_constraints": {
      "type": "object",
      "description": "Per-tool parameter validation constraints.",
      "additionalProperties": {
        "type": "object",
        "description": "Map of parameter names to constraint objects for a specific tool.",
        "additionalProperties": {
          "type": "object",
          "properties": {
            "type": {
              "type": "string",
              "enum": ["string", "integer", "number", "boolean", "array", "object"]
            },
            "required": {
              "type": "boolean"
            },
            "min": {
              "type": "number"
            },
            "max": {
              "type": "number"
            },
            "pattern": {
              "type": "string"
            },
            "enum": {
              "type": "array"
            },
            "max_length": {
              "type": "integer",
              "minimum": 0
            },
            "description": {
              "type": "string"
            }
          }
        }
      }
    },
    "risk_level": {
      "type": "string",
      "description": "Risk classification for policy evaluation.",
      "enum": ["low", "medium", "high", "critical"],
      "default": "low"
    },
    "author": {
      "type": "string",
      "description": "Author or maintainer identifier.",
      "maxLength": 128
    }
  },
  "additionalProperties": false
}
```

---

## Example Manifest

```json
{
  "name": "code-reviewer",
  "version": "4.1.0",
  "type": "domain-specific",
  "allowed_phases": ["review", "refinement"],
  "required_permissions": ["file_read", "ast_analysis"],
  "tools": ["parse_ast", "query_symbol", "compare_diff", "generate_comment"],
  "side_effects": ["file_read", "state_mutation"],
  "dependencies": ["parser-core"],
  "integrity_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "required_capabilities": {
    "filesystem": {
      "read_paths": ["./src", "./tests"],
      "write_paths": [],
      "allow_absolute": false,
      "max_file_size_mb": 10
    },
    "network": {
      "allow_outbound": false
    },
    "process": {
      "allow_spawn": false,
      "max_processes": 0
    },
    "resources": {
      "max_memory_mb": 512,
      "max_cpu_time_sec": 30,
      "timeout_sec": 30
    }
  },
  "parameter_constraints": {
    "parse_ast": {
      "language": {
        "type": "string",
        "required": true,
        "enum": ["python", "javascript", "typescript", "rust"]
      },
      "file_path": {
        "type": "string",
        "required": true,
        "max_length": 4096
      }
    },
    "generate_comment": {
      "severity": {
        "type": "string",
        "required": true,
        "enum": ["info", "warning", "error", "critical"]
      }
    }
  },
  "risk_level": "medium",
  "author": "kimi-ai-engineering"
}
```

---

## Integrity Hash Computation

The `integrity_hash` is a SHA-256 digest computed over the skill's **canonical source files** in a deterministic order:

1. `SKILL.md` (if present)
2. `manifest.json` (if present)
3. All files in `scripts/` directory, sorted alphabetically
4. All files in `references/` directory, sorted alphabetically

Each file's raw bytes are fed into the hasher, followed by a null byte delimiter (`\x00`) to prevent concatenation ambiguity.

### Computation Script (Python)

```python
import hashlib
from pathlib import Path

def compute_skill_sha256(skill_dir: Path) -> str:
    hasher = hashlib.sha256()
    canonical_patterns = [
        "SKILL.md",
        "manifest.json",
        "scripts/*",
        "references/*",
    ]
    files = []
    for pattern in canonical_patterns:
        files.extend(skill_dir.glob(pattern))
    for file_path in sorted(files):
        if file_path.is_file():
            hasher.update(file_path.read_bytes())
            hasher.update(b"\x00")
    return hasher.hexdigest()
```

The `skill-registry` re-computes this hash on every `LOADED → ACTIVE` transition and rejects the transition if the hash does not match the manifest.

---

## Frontmatter Alternative

If a skill does not include a standalone `manifest.json`, the manifest MAY be embedded as YAML-like frontmatter at the top of `SKILL.md`, delimited by `---`:

```markdown
---
name: code-reviewer
version: 4.1.0
type: domain-specific
allowed_phases: [review, refinement]
required_permissions: [file_read, ast_analysis]
tools: [parse_ast, query_symbol, compare_diff, generate_comment]
side_effects: [file_read, state_mutation]
dependencies: [parser-core]
integrity_hash: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
risk_level: medium
author: kimi-ai-engineering
---

# code-reviewer

Skill documentation continues here...
```

The `skill-registry` parses frontmatter when `manifest.json` is absent. Frontmatter MUST still conform to the schema above.

---

## Validation Rules

1. **Required Fields**: `name`, `version`, `type`, `allowed_phases`, `tools`, and `integrity_hash` must be present.
2. **Name Format**: Must match `^[a-z0-9-]+$` (lowercase, hyphens, alphanumeric).
3. **Version Format**: Must be valid semantic version (MAJOR.MINOR.PATCH).
4. **Integrity Hash**: Must be exactly 64 hexadecimal characters.
5. **Phase References**: All strings in `allowed_phases` must be non-empty and unique.
6. **Dependency Resolution**: All entries in `dependencies` must refer to skills that exist in the registry. The registry checks this at activation time, not at discovery time.
7. **Tool Uniqueness**: `tools` array must contain unique entries. Duplicate tool declarations are a schema violation.
8. **No Additional Properties**: The schema does not permit unknown top-level properties. Extra fields cause validation failure.

---

## Policy Integration

The `policy-engine` uses the following manifest fields for validation:

| Manifest Field | Policy Usage |
|---------------|--------------|
| `required_permissions` | Checked against session-granted permissions. |
| `risk_level` | Compared against `trust_zone` maximum risk tolerance. |
| `side_effects` | Checked against environment restrictions (e.g., air-gapped mode blocks `network_request`). |
| `type` | Core infrastructure skills may have elevated trust defaults. |

A skill that fails policy validation remains in `LOADED` state (or is demoted from `ACTIVE` to `UNLOADED`) and is never injected into the LLM context.

---

## Tool Execution Gateway Integration

The `tool-execution-gateway` validates every tool call against the manifest:

1. **Skill State Check**: The calling skill MUST be `ACTIVE`.
2. **Tool Declaration Check**: The tool name MUST appear in the skill's `tools` array.
3. **Parameter Constraint Check**: Tool arguments MUST satisfy the corresponding `parameter_constraints` rules.

If any check fails, the gateway blocks the call and returns an authorization error to the LLM.

---

## Sandbox Executor Integration

The `sandbox-executor` receives the `required_capabilities` object from the manifest to configure the execution environment. The registry queries `get_sandbox_profile(skill_name)` and forwards the result to the executor before running any sandboxed code on behalf of the skill.

---

## Version History

| Schema Version | Date | Changes |
|---------------|------|---------|
| v4.0 | 2024-01-15 | Initial schema. Introduced `integrity_hash`, `required_capabilities`, `parameter_constraints`, and `risk_level`. Tightened required fields. |
