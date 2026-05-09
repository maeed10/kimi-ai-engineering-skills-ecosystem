---
name: requirement-refinement
description: INGEST-phase ambiguity detection and requirement clarification skill. Augments spec-decomposer with example mapping, feasibility pre-checks, and assumption tracking before PLAN. Use when requirements lack clear acceptance criteria, have conflicting NFRs, or reference systems that may not exist in the codebase. Blocks PLAN phase if ambiguity score exceeds threshold.
---

# Requirement Refinement

## Overview

INGEST-phase companion to `spec-decomposer` that hardens task nodes before they reach PLAN. Detects ambiguity, generates concrete examples, validates assumptions against codebase reality, and produces a signed-off ASSUMPTIONS.md. Requirements with ambiguity score > 0.5 cannot proceed to PLAN.

## Trigger Conditions

Run this skill immediately after `spec-decomposer` produces initial task nodes and before PLAN phase begins. Specifically triggered when:

- Requirements lack quantifiable acceptance criteria (no numbers, no boundaries, no negative cases)
- User stories contain conflicting NFRs (e.g., "real-time" + "eventual consistency")
- Domain terms are undefined or used inconsistently across tasks
- Tasks reference external systems, APIs, or modules without codebase verification
- Brownfield context exists (legacy code, existing schemas, prior implementations)
- Any task node description is < 20 words or contains hedge words ("maybe", "perhaps", "as needed", "appropriate", "relevant")

## Workflow

### Phase 1: Ambiguity Scan (Input: task nodes from spec-decomposer)

For each task node, evaluate against the 5 detection dimensions in `references/ambiguity_scoring.md`. Compute per-node ambiguity score (0-1).

**Auto-fail triggers** (score = 1.0, immediate block):
- No acceptance criteria of any form
- Contradictory NFRs on the same task
- References a system/component not found in codebase (and brownfield-intelligence unavailable)

**Score > 0.5**: Node blocked from PLAN. Must resolve via user clarification or assumption sign-off.

**Score <= 0.5**: Node proceeds with assumptions documented.

Output: `AMBIGUITY_REPORT.md` — per-node scores, flagged issues, recommended resolutions.

### Phase 2: Example Mapping

For every user story with ambiguity score > 0.2, generate 2-3 concrete Given/When/Then examples following `references/example_mapping_guide.md`.

- **Happy path**: standard success scenario
- **Edge case**: boundary condition (empty input, max size, timeout)
- **Failure path**: expected error handling

Present examples to user for validation. User must confirm, correct, or reject each example. Unvalidated examples block PLAN for that node.

Output: `EXAMPLES.md` — validated G/W/T scenarios per story.

### Phase 3: Feasibility Pre-Check

Query `brownfield-intelligence` skill (or direct codebase search if unavailable) to verify:

1. **System existence**: Every referenced API, module, database table, or external service exists in codebase or is explicitly marked as greenfield
2. **Schema compatibility**: Data shapes referenced in requirements match actual codebase types
3. **Permission/constraint reality**: Auth models, rate limits, deployment constraints are as described

For each reference, record: `VERIFIED` | `NOT_FOUND` | `MISMATCH` | `ASSUMED`.

A `NOT_FOUND` or `MISMATCH` without user sign-off blocks PLAN.

Output: `FEASIBILITY_REPORT.md` — verification results per reference.

### Phase 4: Assumption Ledger

Compile all assumptions from Phases 1-3 into `ASSUMPTIONS.md`:

```markdown
## Assumption Ledger

| ID | Assumption | Source | Confidence | Sign-off | Blocking |
|----|-----------|--------|------------|----------|----------|
| A1 | Rate limit is 100 req/min | NFR conflict resolution | medium | pending | yes |
| A2 | User table has `tenant_id` column | Schema verification | high | auto | no |
```

**Confidence levels**: `high` (verified in code), `medium` (inferred or user-stated), `low` (guess, no evidence).

**Sign-off states**: `auto` (high confidence + verified), `user` (user explicitly confirmed), `pending` (awaiting response), `deferred` (accepted risk, documented).

Any assumption with `Blocking = yes` and `Sign-off != user|auto|deferred` prevents PLAN phase.

### Phase 5: Gate Decision

```
FOR each task node:
  IF ambiguity_score > 0.5 → BLOCK, add to CLARIFICATION_REQUIRED
  IF unvalidated examples exist → BLOCK, add to EXAMPLES_PENDING
  IF feasibility check has NOT_FOUND without sign-off → BLOCK, add to FEASIBILITY_PENDING
  IF blocking assumptions unsigned → BLOCK, add to ASSUMPTIONS_PENDING
  ELSE → APPROVE for PLAN

IF any blocked nodes → output BLOCK_REPORT.md with specific user questions
IF all approved → append ASSUMPTIONS.md to PLAN context, proceed
```

## Output Artifacts

| Artifact | Purpose | Consumed By |
|----------|---------|-------------|
| `AMBIGUITY_REPORT.md` | Per-node scores and flagged issues | User, PLAN phase |
| `EXAMPLES.md` | Validated G/W/T scenarios | PLAN phase, test generation |
| `FEASIBILITY_REPORT.md` | Codebase verification results | PLAN phase, architecture decisions |
| `ASSUMPTIONS.md` | Signed-off assumption ledger | PLAN phase, CODE phase, QA |
| `BLOCK_REPORT.md` (if blocked) | Specific user questions to resolve | User |

## Ambiguity Score Computation

See `references/ambiguity_scoring.md` for full rubric. Summary:

```
score = weighted_average(
  criteria_clarity,      # 0.30 — are AC quantifiable?
  nfr_consistency,       # 0.25 — do NFRs contradict?
  domain_precision,      # 0.20 — are terms defined?
  scope_boundaries,      # 0.15 — what's in/out of scope?
  dependency_clarity     # 0.10 — are dependencies explicit?
)

auto_fail_override = any(auto_fail_trigger)
final_score = 1.0 if auto_fail_override else score
```

## Integration Points

| Skill | Direction | Data |
|-------|-----------|------|
| `spec-decomposer` | Input | Task nodes, user stories, initial NFRs |
| `brownfield-intelligence` | Query | Codebase state, schema info, API existence |
| PLAN phase | Output | Refined requirements, validated examples, signed assumptions |

## Quality Bar

- Every task node entering PLAN has <= 0.5 ambiguity score
- Every user story has >= 1 validated happy-path example
- Every external reference is VERIFIED or explicitly ASSUMED with sign-off
- ASSUMPTIONS.md is non-empty (at minimum contains "no assumptions" entry)
- BLOCK_REPORT.md questions are specific, answerable, and include suggested defaults
