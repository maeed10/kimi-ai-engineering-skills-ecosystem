---
name: architecture-decision-gate
description: PLAN-phase mandatory human-in-the-loop gate for architecture decisions. Intercepts architecture-design and trade-off-analyzer outputs before ASSESS, requiring human approval for pattern introductions, deployment topology changes, and operational complexity additions. Uses human-curated criteria registry and bias detection heuristics to prevent LLM-driven architectural misalignment.
---

# Architecture Decision Gate

## Overview

This skill is a PLAN-phase mandatory gate that intercepts all architecture proposals from `architecture-design` and `trade-off-analyzer` before they transition to ASSESS. It enforces human-in-the-loop (HITL) approval for significant complexity introductions, detects LLM pattern bias via session analysis, and validates that trade-off scoring relies on human-curated criteria rather than synthesized defaults.

## Workflow Decision Tree

```
architecture-design / trade-off-analyzer output arrives
         |
         v
[GATE 1] Complexity Assessment — does this trigger mandatory HITL?
         |
         +-- YES -> stop and present HITL checkpoint immediately
         |
         +-- NO  -> continue to Gate 2
         |
         v
[GATE 2] Bias Detection — does the recommended pattern exhibit LLM bias?
         |
         +-- YES -> flag as BIAS_RISK, require HITL + justification
         |
         +-- NO  -> continue to Gate 3
         |
         v
[GATE 3] Criteria Registry Compliance — are external weights present?
         |
         +-- FAIL (< 50% external weights) -> require registry update + HITL
         |
         +-- PASS -> continue to Gate 4
         |
         v
[GATE 4] HITL Checkpoint — formal approval prompt if Gates 1-3 raised flags
         |
         +-- DENIED -> return to PLAN with remediation notes
         |
         +-- APPROVED -> emit gated output + approval record to ASSESS
```

## Gate 1: Complexity Assessment

Mandatory HITL is required when the architecture proposal introduces ANY of the following:

### Pattern Introductions
- New infrastructure paradigms: microservices, modular monolith, serverless, CQRS, event-driven architecture (EDA), saga pattern, strangler fig, multi-tenant data isolation
- New bounded contexts or domain splits not present in the current codebase
- New data access patterns: event sourcing, sharding, read replicas, cache-aside with write-through

### Deployment Topology Changes
- New runtime platforms (Kubernetes, ECS, Lambda, containerization of previously bare-metal services)
- Network boundary changes (new VPCs, service mesh, API gateway additions, cross-region replication)
- New isolation levels (air-gapped, hybrid cloud, multi-cloud)

### Operational Complexity Additions
- New data stores (any additional database, cache, search index, or blob store)
- New message buses or streaming platforms (Kafka, RabbitMQ, SNS/SQS, EventBridge)
- New observability infrastructure (distributed tracing, new metrics pipeline, new log aggregation)
- Security boundary changes (new IAM realm, new authN/authZ provider, secrets manager)

### Decision Rule
If ANY item above is present, emit `COMPLEXITY_GATE: MANDATORY_HITL_REQUIRED` and proceed to Gate 4 immediately. Do not proceed to ASSESS without explicit human confirmation.

## Gate 2: Bias Detection

Load and execute `scripts/check_bias.py` against the session's recommended patterns and recent session history (up to 20 prior sessions in the current project context). If script execution is unavailable, apply these heuristics manually:

### Bias Heuristics
1. **Pattern Frequency Bias**: If the recommended primary pattern appears as the top recommendation in > 80% of recent sessions, flag `PATTERN_FREQUENCY_BIAS`. Exception: pattern correlates with documented team size or org constraints in the criteria registry.
2. **Team-Size Mismatch**: If the proposal recommends microservices/CQRS/EDA for a team size < 3 engineers or a total codebase < 10K LOC, flag `TEAM_SIZE_MISMATCH`.
3. **Default Bias**: If the proposal uses a pattern without referencing a specific business requirement or quality attribute scenario (latency, throughput, availability target), flag `DEFAULT_BIAS`.
4. **Complexity Escalation**: If the session count of new infrastructure components per decision is monotonically increasing over the last 5 sessions, flag `COMPLEXITY_ESCALATION`.

### Action on Bias Flag
- Emit `BIAS_GATE: RISK_DETECTED` with flagged heuristic(s).
- Require human justification: ask the user to confirm the pattern is driven by a specific requirement, not LLM defaulting.
- Proceed to Gate 4.

## Gate 3: Criteria Registry Compliance

Load `references/criteria_registry_schema.md` and validate the current trade-off analysis against the human-curated `architecture-criteria-registry` (JSON/YAML file maintained by the team).

### Compliance Rules
1. **External Weight Minimum**: At least 50% of the scoring criteria used in the trade-off analysis must have weights sourced from the human-curated registry or documented historical decision records.
2. **Registry Coverage**: Every new pattern or infrastructure component must map to at least one registry entry covering operational cost, team expertise, and maintainability.
3. **No Synthetic Defaults**: Criteria weights labeled as "default", "typical", or "industry standard" without a registry source are treated as missing external weights.

### Action on Compliance Failure
- Emit `REGISTRY_GATE: INSUFFICIENT_EXTERNAL_WEIGHTS` or `REGISTRY_GATE: MISSING_COVERAGE`.
- Present the user with the registry schema and request:
  - Either human-provided weights for the missing criteria
  - Or explicit documented override with justification
- Proceed to Gate 4.

## Gate 4: HITL Checkpoint

This gate is always reached if ANY prior gate emitted a flag. If all gates passed silently, this gate is optional (emit `HITL_GATE: BYPASSED` with rationale).

### Checkpoint Format
Present to the user a single consolidated approval prompt:

```
ARCHITECTURE DECISION GATE — APPROVAL REQUIRED
================================================
Decision ID: <generate unique id>
Proposed Pattern(s): <list>
Affected Components: <list>

Gating Results:
- Complexity:      [PASS | MANDATORY_HITL_REQUIRED]
- Bias Detection:    [PASS | RISK_DETECTED — <flags>]
- Registry Compliance: [PASS | <failure mode>]

External Weight Ratio: X% (threshold: 50%)

Trade-Off Summary:
<table of options vs criteria with weights>

APPROVE / DENY / MODIFY?
```

### Response Handling
- **APPROVE**: Append `approval: {decision_id, timestamp, approver, gates_passed}` to the architecture output and proceed to ASSESS.
- **DENY**: Append `denial: {decision_id, timestamp, gates_failed, remediation_notes}` and return to PLAN with explicit remediation instructions.
- **MODIFY**: Treat as DENY with `status: MODIFY` and include the user's specific changes as the remediation plan.

## Output Requirements

All gated outputs must include:
1. `decision_gate_record` metadata block with decision_id, timestamp, gate results, and approval status
2. If HITL was required: include approver identifier (even if "anonymous user") and brief justification
3. If bias was detected: include bias flags and any mitigations applied
4. If registry was incomplete: list missing registry entries and whether they were added during the gate

The output must be emitted as a single well-formed block (YAML frontmatter or JSON header) prepended to the architecture document before it enters ASSESS.

## Resources

### scripts/check_bias.py
Execute this script against recent session logs to compute pattern frequency and team-size correlation. The script returns a JSON object with bias flags and confidence scores.

### references/criteria_registry_schema.md
JSON schema and example for the human-curated `architecture-criteria-registry`. Load this when validating Gate 3 compliance or when the user needs to create/update their registry.
