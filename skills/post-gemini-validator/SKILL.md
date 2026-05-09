---
name: post-gemini-validator
description: >
  Deterministic output validator that runs after Gemini CLI responses to verify 
  structural integrity, completeness, and absence of secrets before the output 
  enters the Kimi ecosystem. Ensures Gemini outputs meet downstream skill 
  requirements and contain no injected instructions, secrets, or PII. Integrates 
  with multi-model-router, memory-guard, ipi-defender, and artifact-verifier.
---

# post-gemini-validator — Gemini Output Verification

## Overview

`post-gemini-validator` is a deterministic validation gate that inspects all external model outputs (Gemini, Claude, local LLMs) before they are consumed by downstream Kimi skills. While `ipi-defender` scans for injection attacks and `artifact-verifier` checks structural schema compliance, this skill performs task-specific deterministic checks that verify the output is actually useful, complete, and safe for its intended purpose.

It operates as **Gate 0.75** within `tool-execution-gateway`. No external model output enters the Kimi context window without passing this validator. It is also invoked directly by `multi-model-router` as part of the response pipeline.

> **Architecture note:** As of v4.2.1, this validator is integrated into the Gateway Layer (§3) rather than operating as a standalone post-processing step. This ensures ALL external content — regardless of provider — passes through the same deterministic validation gate.

## When to Use

- After every external model response in the multi-model-router pipeline
- Before promoting any Gemini-generated content to semantic memory
- Before using Gemini-decomposed specs for planning
- Before incorporating Gemini-drafted documentation into deliverables
- During adversarial testing of the multi-model-router integration

## Core Capabilities

### 1. Spec-Decomposer Validation

When Gemini is used for requirement parsing (INGEST phase):

| Check | Method | Failure Action |
|-------|--------|---------------|
| Atomicity | Verify every task node has a single, non-compound action | Reject and fallback to Kimi |
| Referencing | Verify every task has at least one `reference` field | Flag as INCOMPLETE |
| Field completeness | Verify mandatory fields: `id`, `title`, `description`, `acceptance_criteria`, `references` | Reject if any missing |
| No placeholders | Detect `TODO`, `FIXME`, `TBD`, `...` in generated content | Flag for human review |
| Schema compliance | Validate against `spec-decomposer` JSON schema | Reject on schema violation |

### 2. Documentation-Synthesizer Validation

When Gemini is used for documentation drafting (DELIVER phase):

| Check | Method | Failure Action |
|-------|--------|---------------|
| No secret leakage | Run `secret-manager` regex scan on output | REJECT and alert |
| No PII leakage | Run `sanitize-vault.py` detection patterns | REJECT and alert |
| No hallucinated APIs | Cross-reference mentioned endpoints against `brownfield-intelligence` index | Flag as UNVERIFIED |
| Structural completeness | Verify all required sections present per doc type | Flag as INCOMPLETE |
| No embedded instructions | Scan for `ignore previous`, `disregard`, `override` patterns | REJECT and quarantine |

### 3. Remember-Phase Validation

When Gemini is used for summarization (REMEMBER phase):

| Check | Method | Failure Action |
|-------|--------|---------------|
| Factual grounding | Verify summaries reference actual session events | Flag if ungrounded |
| Decision preservation | Verify all decisions from session are captured | Flag as INCOMPLETE |
| Link integrity | Verify all `[[wikilinks]]` point to existing vault files | Flag broken links |
| No new claims | Detect statements not supported by session context | Strip or flag |

### 4. Plan-Phase Validation

When Gemini is used for initial decomposition (PLAN phase):

| Check | Method | Failure Action |
|-------|--------|---------------|
| Architectural constraint awareness | Verify decomposition respects declared boundaries | Flag boundary violations |
| Dependency ordering | Verify task ordering respects dependency graph | Reject if cycles detected |
| Estimation presence | Verify every task has effort estimate or complexity tag | Flag as INCOMPLETE |

## Safety Rules

| # | Rule | Enforcement |
|---|------|-------------|
| V1 | **NEVER allow an external model output to bypass validation** | Hard-coded in multi-model-router dispatch flow |
| V2 | **NEVER auto-correct Gemini output** — reject and fallback | Validator is gate, not editor; no LLM-based fixing |
| V3 | **ALWAYS log validation results to policy-engine audit trail** | Every check produces an audit record |
| V4 | **NEVER promote Gemini output to STRUCTURAL or INFERRED trust** | memory-guard enforces EXTERNAL (0.3) ceiling |
| V5 | **ALWAYS quarantine outputs that fail secret/PII checks** | Immediate quarantine, human alert, no downstream propagation |

## Integration Points

| Component | Integration |
|-----------|-------------|
| `multi-model-router` | Receives all external model outputs for validation before forwarding |
| `secret-manager` | Runs secret/PII detection scans as sub-check |
| `artifact-verifier` | Delegates schema validation for structured outputs |
| `memory-guard` | Ensures validated outputs still enter as EXTERNAL trust |
| `policy-engine` | Logs all validation decisions to audit trail |
| `brownfield-intelligence` | Provides ground-truth index for API/reference validation |

## Validation Workflow

```
Gemini Output
    |
    v
[1] ipi-defender scan (injection detection)
    |
    v
[2] secret-manager scan (secret/PII detection)
    +-- FAIL --> QUARANTINE + ALERT + FALLBACK
    |
    v
[3] Task-type specific validation
    +-- spec-decomposer checks (if INGEST)
    +-- documentation checks (if DELIVER)
    +-- summary checks (if REMEMBER)
    +-- plan checks (if PLAN)
    |
    +-- FAIL --> REJECT + LOG + FALLBACK
    |
    v
[4] artifact-verifier schema validation
    +-- FAIL --> REJECT + LOG + FALLBACK
    |
    v
[5] Trust tagging (EXTERNAL 0.3)
    |
    v
[6] Forward to downstream skill
```

## Configuration

```yaml
# post-gemini-validator.yaml
validation:
  mode: strict  # strict | lenient
  
  checks:
    secret_scan: true
    pii_scan: true
    injection_scan: true
    schema_validation: true
    completeness_check: true
    
  fallback:
    on_failure: FALLBACK_TO_KIMI
    max_retries: 0  # Never retry Gemini; fallback immediately
    
  quarantine:
    enabled: true
    path: "~/.kimi/quarantine/gemini/"
    retention_days: 30
```

## Resources

- `scripts/post-gemini-validator.py` — Reference implementation with pluggable check modules
- `references/validation-checklist.md` — Per-task-type check specifications

## Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-06 | Initial release — deterministic output validation for Gemini CLI integration |
