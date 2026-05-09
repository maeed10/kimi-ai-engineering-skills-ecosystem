---
name: requirement-reconciler
description: >
  INGEST-phase multi-document contradiction detection and reconciliation skill.
  Takes multiple input documents (SPEC.md, PRD.md, ADR/*.md, REQUIREMENTS.md),
  identifies contradictions via semantic comparison and keyword overlap, scores
  conflict severity as BLOCKING / WARNING / ADVISORY, and either forces human
  resolution (BLOCKING) or flags for downstream attention before allowing
  spec-decomposer to proceed. Use when multiple source documents are detected
  or when stakeholder inputs may conflict.
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# requirement-reconciler — Multi-Document Requirement Reconciliation

## Overview

`requirement-reconciler` hardens the INGEST phase by detecting contradictions across multiple source documents before they silently propagate through all 7 downstream phases. While `requirement-refinement` handles ambiguity within a single source, this skill handles **cross-document inconsistency**: conflicting PRDs, ADR contradictions, stakeholder disagreements, and mismatched requirements.

## When to Use

- Multiple source documents are detected in the input context (`SPEC.md`, `PRD.md`, `ADR/*.md`, `REQUIREMENTS.md`)
- Stakeholder inputs are known to disagree
- A previous INGEST produced downstream failures traceable to bad assumptions
- `spec-decomposer` task nodes contain cross-references that do not align

## Activation Rules

| Rule | Description |
|------|-------------|
| **Conditional** | Activates ONLY when >1 source document is detected |
| **Pre-refinement** | Runs after `spec-decomposer` and before `requirement-refinement` |
| **Blocking** | BLOCKING conflicts halt the pipeline; WARNING/ADVISORY proceed with flags |
| **Human gate** | BLOCKING conflicts require explicit human resolution before PLAN |

## Input

```yaml
inputs:
  - path: SPEC.md
    weight: 1.0      # Primary source
  - path: PRD.md
    weight: 0.9      # Secondary source
  - path: ADR/*.md
    weight: 0.8      # Architectural decisions
  - path: REQUIREMENTS.md
    weight: 0.7      # Formal requirements
```

## Workflow

### Step 1: Document Ingestion & Normalization

1. Parse all input documents into structured requirement fragments
2. Normalize terminology using `references/term_normalization.md`
3. Extract: requirement_id, text, source_file, section, priority, stakeholder

### Step 2: Semantic Comparison

For every pair of requirement fragments across documents:

```python
similarity = combine(
    semantic_embedding_cosine(r1, r2),   # 0.6 weight
    keyword_overlap_jaccard(r1, r2),     # 0.3 weight
    structural_path_match(r1, r2)        # 0.1 weight
)
```

- `similarity > 0.85`: Treat as same requirement (merge or flag redundancy)
- `0.65 < similarity < 0.85`: Potential contradiction — flag for review
- `similarity < 0.65`: Distinct requirements — no action

### Step 3: Contradiction Detection

Identify explicit contradictions using pattern matching:

| Pattern Type | Example |
|-------------|---------|
| Negation flip | "System SHALL use JWT" vs "System SHALL NOT use JWT" |
| Numeric conflict | "Max 100 req/s" vs "Max 10,000 req/s" |
| Temporal conflict | "Deploy by Q1" vs "Deploy by Q3" |
| Technology conflict | "Use PostgreSQL" vs "Use MongoDB" |
| Scope conflict | "Include payment module" vs "Exclude payment module" |
| NFR conflict | "Real-time latency" vs "Eventual consistency" |

### Step 4: Severity Scoring

```yaml
severity_levels:
  BLOCKING:
    condition: |
      contradiction_affects_core_functionality OR
      contradiction_involves_security_boundary OR
      stakeholder_mandate_conflict_without_resolution_path
    action: halt_pipeline
    requires: human_resolution

  WARNING:
    condition: |
      contradiction_affects_non_core_feature OR
      contradiction_has_documented_resolution_path OR
      numeric_mismatch_within_tolerable_range
    action: proceed_with_flag
    requires: annotate_artifacts

  ADVISORY:
    condition: |
      cosmetic_terminology_difference OR
      redundant_requirement_across_docs OR
      minor_priority_disagreement
    action: log_only
    requires: none
```

### Step 5: Output

**If no BLOCKING conflicts:**
- Output: `RECONCILIATION_REPORT.md`
- Append to `ASSUMPTIONS.md`: "Cross-document reconciliation passed with [N] warnings"
- Proceed to `requirement-refinement`

**If BLOCKING conflicts exist:**
- Output: `BLOCK_REPORT.md` with specific human questions
- Halt pipeline before `requirement-refinement`
- Surface to user: "The following documents contradict each other on [topic]. Please resolve: [options]"

## Output Artifacts

| Artifact | Purpose | Consumed By |
|----------|---------|-------------|
| `RECONCILIATION_REPORT.md` | Per-document similarity matrix, flagged contradictions, severity scores | `requirement-refinement`, PLAN phase |
| `BLOCK_REPORT.md` | Human-resolution questions for BLOCKING conflicts | User |
| `MERGED_REQUIREMENTS.md` | Deduplicated, normalized requirement set | `spec-decomposer`, PLAN phase |

## Safety Rules

| # | Rule | Enforcement |
|---|------|-------------|
| R1 | **NEVER silently ignore a BLOCKING contradiction** | Hard stop in pipeline; no bypass flag |
| R2 | **NEVER auto-resolve a contradiction using LLM inference** | Only human resolution or explicit user sign-off accepted |
| R3 | **ALWAYS preserve original document provenance** | Every merged requirement retains source_file and original_text |
| R4 | **NEVER downgrade BLOCKING to WARNING without human approval** | Severity escalation requires HITL; downgrades also require HITL |

## Integration Points

| Skill | Direction | Data |
|-------|-----------|------|
| `spec-decomposer` | Input | Task nodes, initial requirement fragments |
| `requirement-refinement` | Output | Reconciled requirements, validated assumptions |
| `brownfield-intelligence` | Query | Codebase state for feasibility cross-check |
| `architecture-design` | Output | ADR consistency validation |

## Scripts

- `scripts/reconcile_requirements.py` — Reference implementation with semantic embedding, keyword overlap, and severity classification

## References

- `references/term_normalization.md` — Canonical term mappings across document types
- `references/contradiction_patterns.md` — Regex and NLP patterns for explicit contradiction detection

## Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-07 | Initial release — multi-document reconciliation, semantic comparison, 3-tier severity scoring, blocking human gate |
