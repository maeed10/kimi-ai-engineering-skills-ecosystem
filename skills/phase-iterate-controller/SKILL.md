---
name: phase-iterate-controller
description: >
  Extends the 7-phase pipeline FSM with governed iteration primitives (RETRY, ITERATE, REPLAN, ABORT)
  that enable real-world Agile iteration without compromising safety. Use when phases fail and need
  re-execution, when VALIDATE failure requires returning to PLAN or EXECUTE, when new discoveries
  in EXECUTE mandate re-planning, or when configuring phase-controller transition rules. Maintains
  cryptographic audit trails and iteration depth limits.
---

# Phase Iterate Controller

Governed iteration primitives for the 7-phase FSM (INIT → PLAN → EXECUTE → REVIEW → VALIDATE →
DOCUMENT → COMPLETE). Every phase instance receives a UUID; transitions are append-only edges in a
session-scoped DAG.

## Core Principle

**Append-only DAG, never mutate history.** When a backward transition occurs, create a new phase
instance node and mark prior artifacts as `INVALIDATED_BY`. The old node stays visible for audit;
execution always follows the newest valid path.

## Transition Taxonomy

| Type | Direction | Trigger | Audit Required | Policy Check |
|------|-----------|---------|----------------|--------------|
| `NEXT` | Forward (n → n+1) | Phase completes normally | None | Auto-allowed |
| `RETRY` | Self-loop (n → n) | Transient failure, same inputs | `retry_count` < max | Depth check |
| `ITERATE` | Backward (n → n-1 or n-2) | VALIDATE fails, needs rework | `justification_hash` | Depth + policy |
| `REPLAN` | Backward to PLAN | New information invalidates plan | Delta manifest | Full review |
| `ABORT` | Terminal (any → END) | Unrecoverable failure or safety violation | `abort_reason` | Immediate |

### Transition Detail

#### NEXT
- **Trigger**: Phase output meets exit criteria.
- **Behavior**: Create edge from current phase UUID to next phase UUID.
- **Constraints**: None.

#### RETRY
- **Trigger**: Phase fails due to transient error (network timeout, flaky tool, resource lock).
- **Behavior**: Create new phase instance with same `phase_id`, increment `retry_count`.
- **Constraints**:
  - `max_retries`: 3 (default), configurable per phase.
  - `retry_count` is monotonic per phase type within session.
  - RETRY must use identical inputs; any input change → use ITERATE or REPLAN.

#### ITERATE
- **Trigger**: Downstream validation fails; fix requires reworking 1-2 preceding phases.
- **Behavior**: Create new phase instance at target phase (n-1 or n-2). Link backward edge
  with `justification_hash`.
- **Constraints**:
  - `iteration_depth` ≤ 5 (default), configurable.
  - Target phase must be within 2 steps.
  - Every ITERATE increments the `iteration_depth` counter scoped to the target phase.
  - `justification_hash` = SHA256(reason_text + session_id + timestamp).

#### REPLAN
- **Trigger**: EXECUTE discovers new constraints that invalidate the current plan.
- **Behavior**: Jump to PLAN phase. Submit delta manifest describing what changed.
- **Constraints**:
  - Delta manifest required (see `references/delta_manifest_schema.md`).
  - Invalidates all EXECUTE artifacts downstream of old PLAN.
  - `replan_count` ≤ 3 per session.

#### ABORT
- **Trigger**: Unrecoverable error, safety policy violation, or human command.
- **Behavior**: Terminal transition to END state. Session ends.
- **Constraints**:
  - `abort_reason` must be categorized: `SAFETY`, `UNRECOVERABLE`, `HUMAN`, `TIMEOUT`.
  - All in-flight phase instances marked `ABORTED`.

## Phase DAG Model

### Node Schema

```yaml
phase_instance:
  uuid: uuid7                     # Time-sortable UUID
  session_id: string              # Parent session UUID
  phase: enum                     # INIT | PLAN | EXECUTE | REVIEW | VALIDATE | DOCUMENT | COMPLETE
  sequence_number: int            # Monotonic within session (0, 1, 2, ...)
  retry_count: int                # 0 for first attempt
  iteration_depth: int            # 0 for forward transitions; increments on ITERATE
  status: enum                    # PENDING | ACTIVE | COMPLETED | FAILED | ABORTED | INVALIDATED
  artifacts: list[uuid]           # References to artifact nodes
  invalidated_by: uuid | null     # Set when a backward transition supersedes this node
  transition_in: uuid             # Edge that created this node
  transition_out: uuid | null     # Edge leaving this node (null if current)
  started_at: timestamp
  completed_at: timestamp | null
```

### Edge Schema

```yaml
transition:
  uuid: uuid4
  session_id: string
  from_phase: uuid                # Source phase_instance.uuid
  to_phase: uuid                  # Target phase_instance.uuid
  type: enum                      # NEXT | RETRY | ITERATE | REPLAN | ABORT
  justification_hash: string | null
  delta_manifest: uuid | null     # Set for REPLAN transitions
  metadata:
    retry_count: int | null
    iteration_depth: int | null
    replan_count: int | null
    triggered_by: string          # Phase name + failure description
  created_at: timestamp
```

### Artifact Invalidation

When a backward transition occurs, all artifacts from the superseded phase instance chain are
marked:

```yaml
artifact:
  uuid: uuid4
  phase_instance: uuid            # Owning phase instance
  invalidated_by: uuid | null     # Set to the transition edge that invalidated it
  invalidation_scope: enum        # SELF | CASCADE (CASCADE for REPLAN)
```

**CASCADE invalidation** (REPLAN only): All artifacts from all phases between old PLAN and the
REPLAN point are invalidated in one operation.

## Iteration Depth Control

```
session.iteration_budget:
  ITERATE: { default: 5, per_phase: { VALIDATE: 3, EXECUTE: 4 } }
  RETRY:   { default: 3, per_phase: { EXECUTE: 5, INIT: 2 } }
  REPLAN:  { default: 3 }
```

Depth counters are **session-scoped and monotonic**. A RETRY that becomes an ITERATE does not
reset the counter; both accumulate.

### Depth Exhaustion Behavior

When any counter reaches its limit:
1. Block further transitions of that type.
2. Log `DEPTH_EXHAUSTED` event.
3. Require explicit human approval or ABORT.
4. Optionally escalate `max_depth` via signed override with `escalation_reason`.

## Policy Engine Validation

Every non-NEXT transition runs through the policy engine:

```
validate_transition(session, proposed_transition) -> Result:
  1. Check type-specific counters (RETRY, ITERATE, REPLAN) against budget.
  2. Verify justification_hash present for ITERATE, REPLAN, ABORT.
  3. Verify delta_manifest present and well-formed for REPLAN.
  4. Verify target phase is within allowed distance (ITERATE: max 2 back).
  5. Verify no cycles shorter than 2 phases (prevent A→B→A ping-pong).
  6. Log transition attempt to session audit log.
  7. Return ALLOW, BLOCK(reason), or ESCALATE(reason).
```

### Cycle Prevention

Direct reversals (A→B followed immediately by B→A) are blocked. Minimum 2-phase forward progress
required before a backward edge can return to a previously visited phase.

## Delta Manifest (REPLAN)

A REPLAN transition must include a delta manifest describing exactly what changed and which prior
phases are affected. See `references/delta_manifest_schema.md` for full schema.

Minimal required fields:

```yaml
delta_manifest:
  replan_id: uuid                 # Unique ID for this replan event
  triggered_in_phase: enum        # Phase where new info was discovered
  discovery_description: string   # What changed (max 2000 chars)
  affected_prior_phases: list[enum]  # Which phases need re-execution
  plan_delta:                     # What specifically changes in PLAN
    added: list[string]
    removed: list[string]
    modified: list[{id, old, new}]
  risk_assessment:
    scope_change: boolean
    complexity_delta: int         # +N tasks, -N tasks
  confidence: float               # 0.0–1.0, agent's confidence in new plan
  human_review_required: boolean  # True if scope_change or complexity_delta > threshold
```

## Audit Requirements

Every transition produces an append-only audit record:

```
audit_log_entry:
  timestamp: ISO8601
  session_id: string
  transition_id: uuid
  transition_type: enum
  from_phase: {uuid, name}
  to_phase: {uuid, name}
  justification_hash: string | null
  policy_result: ALLOW | BLOCK | ESCALATE
  depth_counters: {RETRY, ITERATE, REPLAN}
```

Audit logs are immutable and session-scoped. They can be dumped for human review at any time.

## Quick Reference: Decision Tree

```
Phase completed successfully?
  YES → NEXT
  NO  → Failure type?
    Transient / identical inputs?     → RETRY (check retry_count)
    Needs 1-2 phase rework?           → ITERATE (check iteration_depth, justify)
    Plan invalidated by new info?     → REPLAN (delta manifest required)
    Unrecoverable / safety violation? → ABORT (abort_reason required)
```

## Resources

- `references/transition_schema.md` — JSON schema for all transition types
- `references/delta_manifest_schema.md` — Delta manifest format for REPLAN transitions
