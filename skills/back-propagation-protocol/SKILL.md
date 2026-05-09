---
name: back-propagation-protocol
description: 4-layer structured failure feedback protocol that carries validation failures back to planning phases without context loss. Use when VALIDATE fails (resilience-tester, api-contract-tester, security-auditor, performance-validator), when failures require architectural redesign, or when error-policy processes critical path failures. Integrates blast-radius-calculator impact analysis, policy-engine authorization, and skill-orchestrator context re-injection. Trigger on phase-controller backward transitions, validation tool failures, or security remediation report findings.
---

# Back-Propagation Protocol

Structured 4-layer protocol for carrying failure context backward through the execution pipeline — from VALIDATE to PLAN — without losing traceability, scope control, or authorization state.

## Activation Triggers

Activate this protocol when ANY of the following occur:

1. **VALIDATE phase failure**: Any validation skill (`resilience-tester`, `api-contract-tester`, `security-auditor`, `performance-validator`) reports non-passing status
2. **Architectural redesign required**: Failure category is `architectural_mismatch`, `breaking_change`, or `security_critical`
3. **Critical path failure**: `error-policy` flags a failure on the critical execution path
4. **Phase controller backward transition**: `phase-controller` initiates a backward phase transition from VALIDATE → EXECUTE, EXECUTE → PLAN, or VALIDATE → PLAN

## Protocol Architecture

```
VALIDATE failure
     |
     v
[L1] Failure Capture ───────> Structured failure report
     |
     v
[L2] Impact Analysis ───────> blast-radius-calculator
     |
     v
[L3] Transition Authorization ──> policy-engine + HITL gating
     |
     v
[L4] Context Re-injection ────> skill-orchestrator
     |
     v
Revised PLAN phase
```

---

## L1: Failure Capture

Produce a structured failure report immediately upon validation failure. Do not proceed to L2 until the report passes schema validation.

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `failure_id` | UUID | Unique identifier for this failure instance |
| `source_phase` | enum | Phase where failure originated: `VALIDATE`, `EXECUTE`, `INTEGRATE` |
| `source_skill` | string | Skill name that raised the failure (e.g., `security-auditor`) |
| `severity` | enum | `critical`, `high`, `medium`, `low`, `info` |
| `category` | enum | `contract_violation`, `performance_regression`, `security_vulnerability`, `architectural_mismatch`, `resource_exhaustion`, `flaky_test`, `breaking_change`, `environment_error` |
| `artifact_hash` | string | BLAKE3 hash of the artifact that failed validation |
| `message` | string | Human-readable failure description |
| `raw_output` | string | Full stderr / test output / scanner report (truncated to 64KB) |
| `timestamp` | ISO-8601 | Failure detection time |
| `retry_count` | integer | Number of retry attempts already exhausted |

### Failure Severity Heuristic

```
IF category == security_vulnerability AND CVSS >= 7.0: severity = critical
IF category == breaking_change AND affects_public_api: severity = critical
IF category == architectural_mismatch: severity = high
IF retry_count >= max_retries: severity = min(severity + 1, critical)
IF category == flaky_test: severity = low
```

### L1 Output Contract

- `failure_id` must be globally unique (use UUID v4)
- `artifact_hash` must reference the exact artifact under test
- `raw_output` must include at minimum the last 4KB of diagnostic output

---

## L2: Impact Analysis

Invoke `blast-radius-calculator` to determine the scope of the failure and the optimal re-entry phase.

### Input to blast-radius-calculator

```json
{
  "failure_report": "<L1 failure report object>",
  "dependency_graph": "<artifact dependency DAG from skill-orchestrator>",
  "change_set": "<files modified since last successful validation>",
  "execution_history": "<phase execution log>",
  "policy_context": "<applicable constraints from error-policy>"
}
```

### Output from blast-radius-calculator

| Field | Type | Description |
|-------|------|-------------|
| `impact_radius` | integer | Count of downstream artifacts affected |
| `affected_nodes` | string[] | List of affected artifact identifiers |
| `impact_depth` | integer | Longest dependency chain from failure point |
| `recommended_target_phase` | enum | `PLAN`, `EXECUTE`, or `VALIDATE` (re-validate only) |
| `recommendation_rationale` | string | Human-readable justification for target phase |
| `estimated_rework_scope` | enum | `single_artifact`, `module_scope`, `system_scope`, `architectural` |
| `risk_of_cascade_failure` | enum | `none`, `low`, `medium`, `high`, `certain` |

### Target Phase Decision Matrix

| Condition | Target Phase | Rationale |
|-----------|-------------|-----------|
| `estimated_rework_scope == architectural` | `PLAN` | Requires redesign |
| `risk_of_cascade_failure >= high` | `PLAN` | Need holistic review |
| `impact_depth > 3` | `PLAN` | Deep dependency chain |
| `estimated_rework_scope == system_scope` | `EXECUTE` | Broad but not architectural |
| `impact_radius > 5 AND risk < high` | `EXECUTE` | Many artifacts, manageable risk |
| All other cases | `VALIDATE` | Re-validate after targeted fix |

### L2 Gate

If `risk_of_cascade_failure == certain`, immediately escalate to HITL before L3. Do not auto-authorize backward transitions with guaranteed cascade risk.

---

## L3: Transition Authorization

Submit the L1 report + L2 analysis to `policy-engine` for backward transition approval.

### Authorization Request Schema

```json
{
  "request_type": "backward_transition",
  "failure_report": "<L1 object>",
  "impact_analysis": "<L2 object>",
  "proposed_transition": {
    "from_phase": "VALIDATE",
    "to_phase": "<from L2 recommended_target_phase>",
    "authorized_by": null,
    "authorization_timestamp": null
  },
  "gating_rules": []
}
```

### Policy Engine Rules

1. **Auto-approve**: `severity == low` OR `estimated_rework_scope == single_artifact`
2. **Require HITL**: `severity >= high` OR `risk_of_cascade_failure >= high`
3. **Block transition**: `category == security_vulnerability AND severity == critical` without security lead approval
4. **Require traceability**: Every backward transition MUST produce a `backpropagation_artifact` (see schema in `references/backprop_schema.md`)

### HITL Gating

When HITL is required:

1. `policy-engine` sets `proposed_transition.authorized_by = null`
2. Present the operator with:
   - Failure summary (severity, category, message)
   - Impact analysis (impact_radius, affected_nodes, estimated_rework_scope)
   - Proposed target phase with rationale
   - Risk of cascade failure
3. Operator options: `approve`, `approve_with_constraints`, `deny`, `escalate`
4. On `approve_with_constraints`: capture constraints in `gating_rules` array
5. On `deny`: `phase-controller` halts pipeline; failure is terminal
6. On `escalate`: route to security/compliance lead per `error-policy`

### L3 Output Contract

- `authorization_status`: `approved`, `denied`, `pending_hitl`, `escalated`
- `gating_rules`: Array of constraint objects applied to the transition
- `approved_by`: `auto` or operator identifier
- `approval_timestamp`: ISO-8601

---

## L4: Context Re-injection

`skill-orchestrator` re-composes the prompt for the target phase, embedding the back-propagation artifact as a **system message** with the highest context priority.

### Context Re-injection Rules

1. **Priority**: Back-propagation artifact is injected at context priority level `0` (highest)
2. **Format**: Rendered as structured system message, not appended to user prompt
3. **Attribution**: All downstream skills see `failure_id`, `source_skill`, and `impact_analysis`
4. **Scope limitation**: Only affected nodes (from L2) receive the full failure context; unaffected nodes receive summary only
5. **Freshness**: The re-composed prompt MUST include `timestamp` and `retry_count` to prevent stale context replay

### System Message Template

```
[BACK-PROPAGATION CONTEXT]
Failure ID: {failure_id}
Source: {source_skill} in {source_phase} phase
Severity: {severity} | Category: {category}
Impact Radius: {impact_radius} artifacts affected
Target Phase: {recommended_target_phase}
Previous Attempts: {retry_count}
Rationale: {recommendation_rationale}
Constraints: {gating_rules}

Failure Summary:
{message}

Affected Artifacts: {affected_nodes}
```

### L4 Verification

Before handing off to the target phase:
- Verify `artifact_hash` matches the artifact now in scope
- Verify `gating_rules` are encoded as skill constraints
- Log the full `backpropagation_artifact` to execution trace

---

## Back-Propagation Artifact

The complete artifact produced by the protocol is a single JSON document consumed by the target phase. Full schema is defined in `references/backprop_schema.md`.

### Artifact Sections

| Section | Source Layer | Content |
|---------|-------------|---------|
| `source` | L1 | Failure report with identity, severity, category, artifact hash |
| `analysis` | L2 | Impact radius, affected nodes, target phase recommendation |
| `authorization` | L3 | Approval status, gating rules, operator attribution |
| `context_bundle` | L4 | Rendered system message, skill constraints, scope map |

### Artifact Lifecycle

1. Created at end of L1, appended at each subsequent layer
2. Stored in execution trace with `failure_id` as lookup key
3. Referenced by `phase-controller` during backward transition
4. Consumed by target phase skill as system context
5. Archived after successful re-validation; retained for audit

---

## Integration Points

| Skill / Component | Integration Role |
|-------------------|-----------------|
| `error-policy` | Provides critical path flags and severity escalation rules; consulted in L1 severity assignment |
| `phase-controller` | Initiates backward transitions; validates authorization token from L3 before transition |
| `skill-orchestrator` | Performs L4 context re-injection; manages prompt re-composition with failure context |
| `blast-radius-calculator` | L2 impact analysis engine; produces impact radius and target phase recommendation |
| `policy-engine` | L3 authorization engine; applies gating rules and HITL workflows |
| `resilience-tester` | Common L1 failure source; produces structured failure reports on recovery failure |
| `api-contract-tester` | Common L1 failure source; produces contract violation reports |
| `security-auditor` | Common L1 failure source; produces vulnerability reports with CVSS scores |
| `performance-validator` | Common L1 failure source; produces performance regression reports |

---

## Workflow Decision Tree

```
VALIDATE failure detected
|
+--> L1: Capture structured failure report
|    |
|    +--> Validate schema compliance
|         |
|         +--> FAIL: Re-capture with corrections
|
+--> L2: Invoke blast-radius-calculator
|    |
|    +--> impact_radius == 0?
|    |    +--> YES: Log anomaly, skip back-propagation
|    |
|    +--> risk_of_cascade_failure == certain?
|         +--> YES: Immediate HITL escalation
|
+--> L3: Submit to policy-engine
|    |
|    +--> Auto-approved?
|    |    +--> YES: Proceed to L4
|    |    +--> NO: Await HITL / escalate
|    |
|    +--> Denied?
|         +--> YES: Terminal failure, halt pipeline
|
+--> L4: skill-orchestrator re-injects context
     |
     +--> Compose backpropagation_artifact
     |
     +--> Target phase receives system message + constraints
     |
     +--> Resume pipeline at recommended_target_phase
```

## Resources

- `references/backprop_schema.md` — Full JSON schema for Back-Propagation Artifact
- `scripts/validate_backprop.py` — Validate a back-propagation artifact against schema