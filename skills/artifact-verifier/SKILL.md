---
name: artifact-verifier
description: L0 deterministic per-phase artifact validator that checks semantic correctness, structural completeness, and forbidden patterns before phase-controller accepts transitions. Run after PLAN, EXECUTE, and DELIVER phases to validate artifacts beyond hash checks. Uses JSON schema, AST parsing, and regex — no LLM inference. Triggered by phase-controller before any phase transition.
---

# artifact-verifier

## Overview

The `artifact-verifier` is an L0 Enforcement Layer skill that runs deterministic, non-LLM validators on phase completion artifacts **before** the `phase-controller` accepts a phase transition. It goes beyond hash verification to check semantic correctness, structural completeness, and forbidden patterns.

This skill is **strictly non-inferential**: all checks use structured parsers, JSON schemas, regex, and AST tools. The output is a machine-readable pass/fail report consumed by `phase-controller` as a transition prerequisite.

## When to Run

- Immediately before any phase transition in the 7-phase pipeline (INGEST → PLAN → ASSESS → EXECUTE → DELIVER → VALIDATE → REMEMBER).
- When `phase-controller` emits a `VERIFY_ARTIFACT` signal.
- On any artifact produced at the end of PLAN, EXECUTE, or DELIVER.

## Architecture

```
phase-controller ---(VERIFY_ARTIFACT)---> artifact-verifier ---(report)---> phase-controller
                                              |
                    +-------------------------+-------------------------+
                    |                         |                         |
              JSON Schema               AST / Regex               Section Coverage
              (structure)               (forbidden patterns)      (completeness)
```

## Validation Rules by Phase

### PLAN Phase — Plan Artifact Validation

Validates that the plan artifact (JSON or structured markdown) contains mandatory sections.

**Mandatory sections (JSON schema enforced):**
- `objectives`: non-empty array of objective objects with `id`, `description`, `priority`
- `constraints`: array of constraint objects with `type`, `description`
- `alternatives`: array of alternative objects with `id`, `description`, `tradeoffs`
- `risk_assessment`: object with `risks` array, each risk having `id`, `severity`, `mitigation`
- `timeline`: object with `phases` array mapping to the 7-phase pipeline

**Forbidden patterns:**
- Empty `objectives` or `risk_assessment.risks`
- Duplicate `id` values within any array
- Missing `priority` values outside allowed enum: `["critical", "high", "medium", "low"]`
- `severity` outside allowed enum: `["critical", "high", "medium", "low", "info"]`

**Schema reference:** See `references/phase_validation_schemas.md` — Schema `plan_artifact_v1`.

### EXECUTE Phase — Code Artifact Validation

Validates code artifacts (Python, JavaScript/TypeScript, shell, etc.) for structural integrity and forbidden patterns.

**Checks performed:**
1. **AST Parseability** — file must parse without syntax errors
2. **Import/Require Resolution** — all imports must be resolvable (stdlib, declared deps, or local modules)
3. **Forbidden Patterns** — regex-based detection of dangerous constructs

**Forbidden patterns (regex-based):**
| Pattern | Regex | Severity |
|---|---|---|
| Hardcoded secrets | `(?i)(password\s*=\s*["\'][^"\']+["\'])\|`api_key\s*=\s*["\'][^"\']+["\']` | critical |
| `eval()` / `exec()` | `\beval\s*\(|\bexec\s*\(` | critical |
| Bare `except:` | `except\s*:\s*$` | high |
| `subprocess` shell=True | `subprocess\..*shell\s*=\s*True` | high |
| `os.system` calls | `\bos\.system\s*\(` | high |
| TODO/FIXME markers | `TODO|FIXME|XXX` (if >3) | medium |
| `console.log` / `print` debug | `\bconsole\.log\s*\(|\bprint\s*\(` | low |

**Note:** The script auto-detects language from file extension and runs the appropriate parser.

### DELIVER Phase — Documentation Artifact Validation

Validates deliverable documentation for required sections and structural completeness.

**Mandatory sections:**
- `Overview` / `Summary` / `Introduction` (any heading level)
- `Prerequisites` / `Requirements`
- `Installation` / `Setup` (if code deliverable)
- `Usage` / `How to Use`
- `API Reference` / `Configuration` (if applicable)
- `Troubleshooting` / `FAQ` (optional but flagged if missing)
- `Changelog` / `Version History` (optional but flagged)

**Checks:**
- Heading hierarchy: no skipped levels (e.g., no `h1` → `h3` without `h2`)
- Minimum heading count: ≥ 3 for any document >500 words
- Broken internal links: `\[.+?\]\(#.+?\)` that reference non-existent anchors
- Code blocks must have language tags: triple-backtick blocks should specify language

### VALIDATE Phase — Validation Report Verification

Validates that validation artifacts contain:
- `test_results` array with `status` ∈ `["pass", "fail", "skip", "error"]`
- `coverage` object with `lines`, `branches` as percentages (0–100)
- `findings` array with `severity` and `description`
- No `status: "pass"` paired with non-empty `findings` array (inconsistency flag)

### REMEMBER Phase — Memory Artifact Validation

Validates memory/index artifacts for:
- Valid JSON / YAML syntax
- Required top-level keys: `session_id`, `timestamp`, `artifacts`, `learnings`
- `artifacts` array entries have `path`, `type`, `checksum`
- `learnings` array entries have `category`, `description`

## Output Format

The verifier emits a single JSON report:

```json
{
  "verifier": "artifact-verifier",
  "version": "1.0.0",
  "timestamp": "2025-01-15T10:30:00Z",
  "artifact_path": "/path/to/artifact",
  "phase": "EXECUTE",
  "result": "fail",
  "checks": {
    "structure": { "passed": true, "details": [] },
    "syntax": { "passed": true, "details": [] },
    "imports": { "passed": false, "details": ["Unresolved import: 'numpy' at line 12"] },
    "forbidden_patterns": { "passed": true, "details": [] },
    "coverage": { "passed": true, "details": [] }
  },
  "summary": {
    "total_checks": 5,
    "passed": 4,
    "failed": 1,
    "critical_failures": 0
  },
  "recommendation": "Phase transition BLOCKED. Resolve 1 import resolution failure before proceeding."
}
```

**Result values:**
- `"pass"` — all checks passed; phase-controller may proceed
- `"fail"` — ≥1 check failed; transition blocked
- `"warn"` — only low-severity findings; transition allowed with escalation flag

**Critical failures:** Any finding with `severity: "critical"` immediately sets `result: "fail"` regardless of other checks.

## Integration with phase-controller

1. `phase-controller` calls `artifact-verifier` via the validation script:
   ```bash
   python scripts/validate_artifact.py --artifact <path> --phase <PHASE_NAME>
   ```
2. The script returns exit code `0` for pass/warn, `1` for fail.
3. `phase-controller` reads the JSON report from stdout (last line).
4. On `fail`: transition is blocked; `phase-controller` must loop back to the current phase.
5. On `warn`: transition proceeds but `phase-controller` logs the warning in session memory.
6. On `pass`: transition proceeds normally.

**Contract:**
- The verifier must complete in <5 seconds per artifact.
- The verifier must not modify the artifact under test.
- The verifier must not use LLM-based inference for any check.

## Quick Reference — Running the Verifier

```bash
# Validate a plan artifact
python scripts/validate_artifact.py --artifact plan.json --phase PLAN

# Validate a Python code artifact
python scripts/validate_artifact.py --artifact src/module.py --phase EXECUTE

# Validate documentation
python scripts/validate_artifact.py --artifact README.md --phase DELIVER

# Validate with strict mode (no warnings allowed)
python scripts/validate_artifact.py --artifact plan.json --phase PLAN --strict

# Output to file
python scripts/validate_artifact.py --artifact src/ --phase EXECUTE --output report.json
```

## Extending the Verifier

To add a new phase or artifact type:

1. Add a JSON schema to `references/phase_validation_schemas.md`
2. Implement the validator class in `scripts/validate_artifact.py` (subclass `BaseValidator`)
3. Register the phase-to-validator mapping in `PHASE_REGISTRY`
4. Add forbidden patterns to the `FORBIDDEN_PATTERNS` registry if applicable

## Error Codes

| Code | Meaning |
|---|---|
| `AV-001` | Missing mandatory section |
| `AV-002` | Schema validation failure |
| `AV-003` | Syntax / AST parse error |
| `AV-004` | Unresolved import / dependency |
| `AV-005` | Forbidden pattern detected |
| `AV-006` | Duplicate identifier |
| `AV-007` | Invalid enum value |
| `AV-008` | Structural inconsistency |
| `AV-009` | Broken internal link |
| `AV-010` | Missing code block language tag |
