# Phase Validation Schemas

This document defines the JSON schemas and structural requirements for artifact validation across each phase of the 7-phase pipeline.

---

## Schema: `plan_artifact_v1`

Applies to: PLAN phase artifacts (JSON or frontmatter-parsable markdown).

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PlanArtifact",
  "type": "object",
  "required": ["objectives", "constraints", "alternatives", "risk_assessment", "timeline"],
  "properties": {
    "objectives": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "description", "priority"],
        "properties": {
          "id": { "type": "string", "pattern": "^OBJ-[0-9]+$" },
          "description": { "type": "string", "minLength": 10 },
          "priority": { "type": "string", "enum": ["critical", "high", "medium", "low"] },
          "acceptance_criteria": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "constraints": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "description"],
        "properties": {
          "type": { "type": "string", "enum": ["technical", "business", "legal", "resource", "time"] },
          "description": { "type": "string", "minLength": 5 }
        }
      }
    },
    "alternatives": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "description", "tradeoffs"],
        "properties": {
          "id": { "type": "string", "pattern": "^ALT-[0-9]+$" },
          "description": { "type": "string", "minLength": 10 },
          "tradeoffs": {
            "type": "array",
            "minItems": 1,
            "items": { "type": "string", "minLength": 5 }
          }
        }
      }
    },
    "risk_assessment": {
      "type": "object",
      "required": ["risks"],
      "properties": {
        "risks": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "required": ["id", "severity", "mitigation"],
            "properties": {
              "id": { "type": "string", "pattern": "^RISK-[0-9]+$" },
              "description": { "type": "string", "minLength": 5 },
              "severity": { "type": "string", "enum": ["critical", "high", "medium", "low", "info"] },
              "mitigation": { "type": "string", "minLength": 5 },
              "owner": { "type": "string" }
            }
          }
        }
      }
    },
    "timeline": {
      "type": "object",
      "required": ["phases"],
      "properties": {
        "phases": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "required": ["name", "order"],
            "properties": {
              "name": {
                "type": "string",
                "enum": ["INGEST", "PLAN", "ASSESS", "EXECUTE", "DELIVER", "VALIDATE", "REMEMBER"]
              },
              "order": { "type": "integer", "minimum": 1 },
              "duration_estimate": { "type": "string" },
              "dependencies": { "type": "array", "items": { "type": "string" } }
            }
          }
        }
      }
    }
  }
}
```

**Additional constraints (enforced by script, not JSON Schema):**
- All `id` values must be unique within their containing array (`objectives`, `alternatives`, `risks`).
- `timeline.phases` must not contain duplicate `name` values.
- At least one objective must have `priority: "critical"` or `"high"`.
- At least one risk must have `severity: "critical"` or `"high"`.

---

## Schema: `execute_artifact_v1`

Applies to: EXECUTE phase artifacts (source code files and directories).

This schema is **structural and pattern-based**, not JSON Schema, because code artifacts are heterogeneous.

### Python Source (`*.py`)

**AST checks:**
- Must parse with `ast.parse()` without `SyntaxError`
- No bare `except:` clauses (`ast.ExceptHandler(type=None)`)
- No `eval()` calls at module level or in function bodies (`ast.Call(func=ast.Name(id='eval'))`)
- No `exec()` calls (`ast.Call(func=ast.Name(id='exec'))`)

**Import checks:**
- Standard library imports: must exist in `sys.stdlib_module_names` (Python 3.10+) or a maintained allowlist.
- Third-party imports: must be listed in `requirements.txt`, `pyproject.toml`, or `setup.py` in the artifact directory or project root.
- Local imports: the referenced module file must exist (e.g., `from .foo import bar` requires `foo.py` or `foo/__init__.py`).

**Forbidden pattern regexes:**
```python
FORBIDDEN_PATTERNS_PYTHON = [
    {"id": "AV-005-P1", "pattern": r"(?i)(password\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded password detected"},
    {"id": "AV-005-P2", "pattern": r"(?i)(api_key\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded API key detected"},
    {"id": "AV-005-P3", "pattern": r"(?i)(secret\s*=\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded secret detected"},
    {"id": "AV-005-P4", "pattern": r"\beval\s*\(", "severity": "critical", "description": "eval() call detected"},
    {"id": "AV-005-P5", "pattern": r"\bexec\s*\(", "severity": "critical", "description": "exec() call detected"},
    {"id": "AV-005-P6", "pattern": r"except\s*:\s*$", "severity": "high", "description": "Bare except clause detected"},
    {"id": "AV-005-P7", "pattern": r"subprocess\..*shell\s*=\s*True", "severity": "high", "description": "subprocess with shell=True detected"},
    {"id": "AV-005-P8", "pattern": r"\bos\.system\s*\(", "severity": "high", "description": "os.system() call detected"},
    {"id": "AV-005-P9", "pattern": r"\bprint\s*\(", "severity": "low", "description": "print() debug statement detected"},
]
```

### JavaScript / TypeScript Source (`*.js`, `*.ts`, `*.jsx`, `*.tsx`)

**AST checks:**
- Must parse with `acorn` / `typescript` parser equivalent, or if unavailable, at least validate as valid JS/TS with `esprima`-like heuristics.
- No `eval()` calls.
- No `Function()` constructor with string arguments.

**Forbidden pattern regexes:**
```javascript
FORBIDDEN_PATTERNS_JS = [
    {"id": "AV-005-J1", "pattern": "(?i)(password\\s*=\\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded password detected"},
    {"id": "AV-005-J2", "pattern": "(?i)(api_key\\s*=\\s*['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded API key detected"},
    {"id": "AV-005-J3", "pattern": "\\beval\\s*\\(", "severity": "critical", "description": "eval() call detected"},
    {"id": "AV-005-J4", "pattern": "\\bFunction\\s*\\(\\s*['\"]", "severity": "critical", "description": "Function constructor with string detected"},
    {"id": "AV-005-J5", "pattern": "\\bconsole\\.log\\s*\\(", "severity": "low", "description": "console.log() debug statement detected"},
]
```

### Shell Scripts (`*.sh`, `*.bash`)

**Forbidden pattern regexes:**
```bash
FORBIDDEN_PATTERNS_SHELL = [
    {"id": "AV-005-S1", "pattern": "(?i)(password=['\"][^'\"]+['\"])", "severity": "critical", "description": "Hardcoded password detected"},
    {"id": "AV-005-S2", "pattern": "\\beval\\s", "severity": "critical", "description": "eval call detected"},
    {"id": "AV-005-S3", "pattern": "curl\\s+.*\\|\\s*bash", "severity": "high", "description": "Pipe-to-bash anti-pattern detected"},
    {"id": "AV-005-S4", "pattern": "wget\\s+.*\\|\\s*bash", "severity": "high", "description": "Pipe-to-bash anti-pattern detected"},
    {"id": "AV-005-S5", "pattern": "rm\\s+-rf\\s+/(?!\\*)\\b", "severity": "high", "description": "Dangerous rm -rf / detected"},
]
```

---

## Schema: `deliver_artifact_v1`

Applies to: DELIVER phase artifacts (Markdown documentation, README, API docs, changelogs).

**Required section headings (case-insensitive, any heading level):**
- `Overview`, `Summary`, or `Introduction`
- `Prerequisites`, `Requirements`, or `Dependencies`
- `Installation`, `Setup`, or `Getting Started`
- `Usage`, `How to Use`, or `Examples`

**Optional sections (flagged if missing, not failing):**
- `API Reference`, `Configuration`
- `Troubleshooting`, `FAQ`
- `Changelog`, `Version History`, `Release Notes`

**Markdown structural checks:**
- No skipped heading levels (e.g., `##` → `####` without `###`)
- Minimum 3 headings for documents >500 words
- Code blocks must have language tags: ` ```python `, not bare ` ``` `
- Internal anchor links `[text](#anchor)` must reference existing heading anchors

---

## Schema: `validate_artifact_v1`

Applies to: VALIDATE phase artifacts (test reports, coverage reports, security scan outputs).

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ValidateArtifact",
  "type": "object",
  "required": ["test_results", "coverage", "findings"],
  "properties": {
    "test_results": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "status"],
        "properties": {
          "name": { "type": "string" },
          "status": { "type": "string", "enum": ["pass", "fail", "skip", "error"] },
          "duration_ms": { "type": "number", "minimum": 0 },
          "message": { "type": "string" }
        }
      }
    },
    "coverage": {
      "type": "object",
      "required": ["lines"],
      "properties": {
        "lines": { "type": "number", "minimum": 0, "maximum": 100 },
        "branches": { "type": "number", "minimum": 0, "maximum": 100 },
        "functions": { "type": "number", "minimum": 0, "maximum": 100 }
      }
    },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["severity", "description"],
        "properties": {
          "severity": { "type": "string", "enum": ["critical", "high", "medium", "low", "info"] },
          "description": { "type": "string", "minLength": 5 },
          "location": { "type": "string" },
          "rule_id": { "type": "string" }
        }
      }
    }
  }
}
```

**Consistency checks (enforced by script):**
- If any `test_results[].status == "fail"` or `"error"`, then `findings` must be non-empty.
- If `findings` contains any item with `severity == "critical"`, then `overall_status` (if present) must not be `"pass"`.
- `coverage.lines` should be ≥ 60 for production code deliverables (warn if <60, fail if <30).

---

## Schema: `remember_artifact_v1`

Applies to: REMEMBER phase artifacts (session memory indices, knowledge base updates).

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RememberArtifact",
  "type": "object",
  "required": ["session_id", "timestamp", "artifacts", "learnings"],
  "properties": {
    "session_id": { "type": "string", "minLength": 1 },
    "timestamp": { "type": "string", "format": "date-time" },
    "artifacts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "type", "checksum"],
        "properties": {
          "path": { "type": "string", "minLength": 1 },
          "type": { "type": "string" },
          "checksum": { "type": "string", "pattern": "^[a-f0-9]{64}$" }
        }
      }
    },
    "learnings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["category", "description"],
        "properties": {
          "category": { "type": "string", "enum": ["technical", "process", "security", "business"] },
          "description": { "type": "string", "minLength": 10 },
          "related_artifact": { "type": "string" }
        }
      }
    }
  }
}
```

**Checksum validation:**
- Each `checksum` must be a 64-character hex string (SHA-256).
- (Optional) The verifier may recompute the SHA-256 of the file at `path` and verify it matches `checksum`.

---

## Schema: `ingest_artifact_v1`

Applies to: INGEST phase artifacts (requirement documents, input specifications, user requests).

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "IngestArtifact",
  "type": "object",
  "required": ["request", "context"],
  "properties": {
    "request": {
      "type": "object",
      "required": ["description"],
      "properties": {
        "description": { "type": "string", "minLength": 10 },
        "source": { "type": "string", "enum": ["user", "system", "automation", "integration"] },
        "priority": { "type": "string", "enum": ["critical", "high", "medium", "low"] }
      }
    },
    "context": {
      "type": "object",
      "properties": {
        "domain": { "type": "string" },
        "constraints": { "type": "array", "items": { "type": "string" } },
        "references": { "type": "array", "items": { "type": "string" } }
      }
    },
    "metadata": {
      "type": "object",
      "properties": {
        "ingested_at": { "type": "string", "format": "date-time" },
        "ingested_by": { "type": "string" }
      }
    }
  }
}
```

---

## Schema: `assess_artifact_v1`

Applies to: ASSESS phase artifacts (gap analysis, feasibility studies, risk pre-assessments).

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AssessArtifact",
  "type": "object",
  "required": ["gaps", "feasibility", "recommendations"],
  "properties": {
    "gaps": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "description", "impact"],
        "properties": {
          "id": { "type": "string", "pattern": "^GAP-[0-9]+$" },
          "description": { "type": "string", "minLength": 10 },
          "impact": { "type": "string", "enum": ["critical", "high", "medium", "low"] },
          "mitigation_strategy": { "type": "string" }
        }
      }
    },
    "feasibility": {
      "type": "object",
      "required": ["overall", "factors"],
      "properties": {
        "overall": { "type": "string", "enum": ["feasible", "partially_feasible", "not_feasible", "needs_clarification"] },
        "factors": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["name", "rating"],
            "properties": {
              "name": { "type": "string" },
              "rating": { "type": "string", "enum": ["favorable", "neutral", "unfavorable", "blocking"] },
              "details": { "type": "string" }
            }
          }
        }
      }
    },
    "recommendations": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["id", "description"],
        "properties": {
          "id": { "type": "string", "pattern": "^REC-[0-9]+$" },
          "description": { "type": "string", "minLength": 10 },
          "priority": { "type": "string", "enum": ["critical", "high", "medium", "low"] },
          "related_gap": { "type": "string" }
        }
      }
    }
  }
}
```

**Consistency checks:**
- All `gaps` `id` values must be unique.
- All `recommendations` `id` values must be unique.
- `recommendations[].related_gap` must reference an existing `gaps[].id` if provided.
- At least one gap must have `impact: "critical"` or `"high"`.
