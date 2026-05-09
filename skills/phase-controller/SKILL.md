---
name: phase-controller
description: >
  Deterministic finite state machine that tracks the current pipeline phase, validates transitions, and enforces preconditions. The LLM cannot jump, skip, or retroactively complete phases. Enforces 7-phase progression: INGEST, UNDERSTAND, PLAN, ASSESS, EXECUTE, DELIVER, VALIDATE, REMEMBER. Each transition requires hash-verified completion artifacts. Integrates with skill-orchestrator, skill-registry, policy-engine, and error-policy. v4 Enhancement: governed iteration primitives (RETRY, ITERATE, REPLAN, ABORT) enable real-world Agile iteration without compromising safety.
---

# phase-controller

Deterministic finite state machine (FSM) that tracks the current pipeline phase, validates transitions, and enforces preconditions. The LLM cannot jump, skip, or retroactively complete phases. This skill provides the structural backbone that prevents the "phase wandering" vulnerability identified in ARC-2.1 (severity 9/10).

---

## Description

The `phase-controller` skill enforces a strict, immutable phase progression across the AI engineering pipeline. It operates as an external state machine — independent of the LLM's internal reasoning — and deterministically controls which phase is active, what transitions are legal, and what artifacts must exist before a phase can be entered or exited.

Without this skill, the LLM can declare any phase at any time, skip critical safety phases (e.g., ASSESS before EXECUTE), or retroactively claim completion. The `phase-controller` removes this autonomy by making phase state an objective, persisted, hash-verified system property.

---

## Invocation

```yaml
skill: phase-controller
action: <action_name>
parameters:
  ...
```

### Actions

| Action | Description |
|--------|-------------|
| `initialize` | Boot the state machine; load persisted state or start at `INGEST` |
| `get_state` | Return current phase, transition history, and active artifacts |
| `request_transition` | Request a move to a target phase; validates and blocks if illegal |
| `force_escalation` | Human override: force a transition with audit annotation |
| `crash_recovery` | Load persisted state from disk, validate consistency, resume or escalate |
| `inject_allowed_skills` | Return list of skills permitted for the current phase |

---

## Parameters

### `initialize`

```yaml
skill: phase-controller
action: initialize
parameters:
  resume_from_disk: true      # Load /mnt/agents/state/phase-state.json if present
  force_phase: null           # Optional: override to specific phase (requires HITL)
  audit_log_path: /mnt/agents/logs/phase-audit.log
  state_path: /mnt/agents/state/phase-state.json
```

### `get_state`

```yaml
skill: phase-controller
action: get_state
parameters: {}
```

Returns:
```yaml
current_phase: PLAN
phase_number: 2
allowed_next_phases: [ASSESS]
completed_phases: [INGEST, UNDERSTAND]
artifacts:
  INGEST:
    - file: /mnt/agents/artifacts/ingest-manifest.json
      sha256: abc123...
  UNDERSTAND:
    - file: /mnt/agents/artifacts/domain-model.md
      sha256: def456...
transition_history:
  - from: INGEST
    to: UNDERSTAND
    timestamp: "2025-01-15T09:23:17Z"
    artifact_hash: abc123...
  - from: UNDERSTAND
    to: PLAN
    timestamp: "2025-01-15T09:45:03Z"
    artifact_hash: def456...
```

### `request_transition`

```yaml
skill: phase-controller
action: request_transition
parameters:
  target_phase: EXECUTE
  proposed_artifacts:
    - file: /mnt/agents/artifacts/adr-042.md
      sha256: "sha256:7a3f..."
    - file: /mnt/agents/artifacts/blast-radius-report.json
      sha256: "sha256:9e2b..."
```

Returns on success:
```yaml
status: APPROVED
new_phase: EXECUTE
previous_phase: ASSESS
transition_id: tx-20250115-094503-7a3f
persisted: true
```

Returns on failure:
```yaml
status: BLOCKED
reason: PRECONDITION_FAILED
missing_artifacts:
  - blast-radius-report.json
detail: "Phase EXECUTE requires ADR + blast radius report (ARC-2.1 EXECUTE rule)"
escalation_triggered: true
error_policy_ref: error-policy/hitl-escalation
```

### `force_escalation`

```yaml
skill: phase-controller
action: force_escalation
parameters:
  target_phase: EXECUTE
  human_ticket: HITL-2047
  justification: "Emergency patch; blast radius contained via manual review"
  authorized_by: "human-operator-7"
```

### `crash_recovery`

```yaml
skill: phase-controller
action: crash_recovery
parameters:
  state_path: /mnt/agents/state/phase-state.json
  consistency_checks: [hash_verify, history_integrity, phase_sequence]
```

Returns:
```yaml
status: RECOVERED   # or CORRUPTED / UNRECOVERABLE
loaded_phase: PLAN
consistency_score: 3/3
next_action: resume_or_escalate
```

### `inject_allowed_skills`

```yaml
skill: phase-controller
action: inject_allowed_skills
parameters:
  skill_registry_path: /mnt/agents/skills/registry.json
```

Returns:
```yaml
current_phase: PLAN
allowed_skills:
  - skill-id: planner-v3
    injection_priority: high
  - skill-id: design-doc-generator
    injection_priority: medium
blocked_skills:
  - skill-id: code-executor
    reason: "EXECUTE-phase skill; current phase is PLAN"
```

---

## Dependencies

| Skill / System | Integration Point |
|----------------|-------------------|
| `skill-orchestrator` | Queries PhaseController for allowed transitions before executing any multi-phase plan |
| `skill-registry` | PhaseController filters registry to only inject skills tagged for the current phase |
| `policy-engine` | Every transition is validated against `policy-engine` rules; policy violations block transition |
| `error-policy` | Invalid transitions trigger `error-policy` HITL escalation flow |
| File system | State persisted as JSON; audit log appended as JSON Lines |

---

## Preconditions

1. State directory `/mnt/agents/state/` must be writable
2. Audit log directory `/mnt/agents/logs/` must be writable
3. Artifact files referenced in transitions must exist and be hash-verifiable
4. `policy-engine` must be accessible for policy-rule validation on each transition

---

## Side Effects

- Writes `/mnt/agents/state/phase-state.json` on every approved transition
- Appends to `/mnt/agents/logs/phase-audit.log` on every transition attempt (approved or blocked)
- May trigger `error-policy` escalation on blocked transitions
- Modifies skill injection context via `skill-orchestrator`

---

## Safety Rules (Invariant)

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | NEVER allow a phase transition that violates the state machine definition | `allowed_transitions` matrix is the single source of truth; hard-coded, not configurable by LLM |
| 2 | NEVER allow retroactive phase completion | `completed_phases` is append-only; no API to mark a past phase complete |
| 3 | ALWAYS persist state to disk BEFORE confirming transition to LLM | Write to disk, fsync, then return `APPROVED` |
| 4 | NEVER trust the LLM to declare phase completion | Precondition artifacts must be files on disk with SHA-256 matches |
| 5 | ALWAYS include phase state + artifact hashes in audit log | Every log line includes `current_phase`, `target_phase`, and `artifact_hashes[]` |
| 6 | NEVER allow Phase 4 (EXECUTE) to begin without Phase 3 (ASSESS) completion proof | `EXECUTE` precondition requires both `ADR` and `blast-radius-report.json` with verified hashes |
| 6a | NEVER allow Phase 5 (DELIVER) without Phase 4 (EXECUTE) aspect-audit artifact | `DELIVER` requires `aspect-audit.json` from `cross-cutting-concern-weaver` when code generation was involved |
| 7 | NEVER allow Phase 5 (DELIVER) without Phase 4 (EXECUTE) artifact manifest | `DELIVER` requires `build-manifest.json` + test exit code 0 |
| 8 | NEVER allow Phase 7 (REMEMBER) without Phase 6 (VALIDATE) sign-off | `REMEMBER` requires `validation-report.json` with `status: passed` |

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Illegal transition request | `BLOCKED` response; log; trigger `error-policy` HITL escalation |
| Missing precondition artifact | `BLOCKED` response; enumerate missing items; log; trigger escalation |
| Hash mismatch on artifact | `BLOCKED` response; log tamper warning; trigger escalation |
| State file corruption on load | `crash_recovery` returns `CORRUPTED`; trigger escalation |
| Disk write failure during persist | `BLOCKED` response; internal error; retry once, then escalate |
| Policy engine unreachable | Transition deferred; log; retry with backoff; escalate after 3 failures |

---

## Phase Definitions

| # | Phase | Purpose | Entry Preconditions |
|---|-------|---------|---------------------|
| 0 | `INGEST` | Accept input, load context, validate request format | None (initial state) |
| 1 | `UNDERSTAND` | Build domain model, clarify ambiguity, confirm intent | `INGEST` complete: `ingest-manifest.json` |
| 2 | `PLAN` | Generate task plan, decompose work, assign skill roles | `UNDERSTAND` complete: `domain-model.md` |
| 3 | `ASSESS` | Risk analysis, blast radius, ADR review | `PLAN` complete: `task-plan.json` |
| 4 | `EXECUTE` | Run skills, generate artifacts, build | `ASSESS` complete: `adr-NNN.md` + `blast-radius-report.json` |
| 5 | `DELIVER` | Package output, generate docs, handoff | `EXECUTE` complete: `build-manifest.json` + tests pass |
| 6 | `VALIDATE` | Verify output against requirements, run checks | `DELIVER` complete: `delivery-package/` + `delivery-notes.md` |
| 7 | `REMEMBER` | Persist learnings, update memory, close loop | `VALIDATE` complete: `validation-report.json` with `status: passed` |

---

## Example Usage

### Normal Flow: Initialize → Request Transition → Inject Skills

```yaml
# Step 1: Initialize the state machine
skill: phase-controller
action: initialize
parameters:
  resume_from_disk: true

# Step 2: Later, after UNDERSTAND work is done, request move to PLAN
skill: phase-controller
action: request_transition
parameters:
  target_phase: PLAN
  proposed_artifacts:
    - file: /mnt/agents/artifacts/domain-model.md
      sha256: "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# Step 3: Orchestrator asks what skills are allowed now
skill: phase-controller
action: inject_allowed_skills
parameters:
  skill_registry_path: /mnt/agents/skills/registry.json
```

### Crash Recovery Flow

```yaml
skill: phase-controller
action: crash_recovery
parameters:
  state_path: /mnt/agents/state/phase-state.json
```

---

# Governed Iteration Primitives (v4 Enhancement)

Governed iteration primitives for the phase-controller FSM. Every phase instance receives a UUID; transitions are append-only edges in a session-scoped DAG.

## Core Principle

**Append-only DAG, never mutate history.** When a backward transition occurs, create a new phase instance node and mark prior artifacts as `INVALIDATED_BY`. The old node stays visible for audit; execution always follows the newest valid path.

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
- **Behavior**: Create new phase instance at target phase (n-1 or n-2). Link backward edge with `justification_hash`.
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
  phase: enum                     # Phase name from the defined pipeline
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

When a backward transition occurs, all artifacts from the superseded phase instance chain are marked:

```yaml
artifact:
  uuid: uuid4
  phase_instance: uuid            # Owning phase instance
  invalidated_by: uuid | null     # Set to the transition edge that invalidated it
  invalidation_scope: enum        # SELF | CASCADE (CASCADE for REPLAN)
```

**CASCADE invalidation** (REPLAN only): All artifacts from all phases between old PLAN and the REPLAN point are invalidated in one operation.

## Iteration Depth Control

```
session.iteration_budget:
  ITERATE: { default: 5, per_phase: { VALIDATE: 3, EXECUTE: 4 } }
  RETRY:   { default: 3, per_phase: { EXECUTE: 5, INGEST: 2 } }
  REPLAN:  { default: 3 }
```

Depth counters are **session-scoped and monotonic**. A RETRY that becomes an ITERATE does not reset the counter; both accumulate.

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

Direct reversals (A→B followed immediately by B→A) are blocked. Minimum 2-phase forward progress required before a backward edge can return to a previously visited phase.

## Delta Manifest (REPLAN)

A REPLAN transition must include a delta manifest describing exactly what changed and which prior phases are affected. See `references/delta_manifest_schema.md` for full schema.

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

- `references/phase-transitions.md` — Single source of truth for the 7-phase FSM, allowed transitions matrix, precondition catalog, and ARC-2.1 enforcement rules
- `references/transition_schema.md` — JSON schema for all five transition types (NEXT, RETRY, ITERATE, REPLAN, ABORT)
- `references/delta_manifest_schema.md` — Delta manifest format for REPLAN transitions

## Version

`4.0.0` — Aligned with Kimi AI Engineering Skills Ecosystem v4.0

## Criticality

**CRITICAL** — This skill is a Tier-0 dependency. Without it, the phase boundary enforcement collapses and the entire safety architecture of the ecosystem is void.