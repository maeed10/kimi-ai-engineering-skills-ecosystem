# Anomaly Thresholds Reference

**Skill**: `drift-monitor` v4.0.0  
**Document**: `references/anomaly-thresholds.md`  
**Policy**: These thresholds are **hard-coded** in `scripts/drift-monitor.py` and require human approval + ecosystem version bump to modify. They are **never** exposed to LLM runtime mutation.

---

## 1. Global Statistical Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **Burn-in sessions** | 10 | Sufficient to establish mean and standard deviation without over-fitting; minimum statistically meaningful sample for variance estimation |
| **WARNING z-score** | 2.0σ | Captures ~95% of normal distribution; flags genuinely unusual behavior while keeping false-positive rate manageable |
| **CRITICAL z-score** | 3.0σ | Captures ~99.7% of normal distribution; indicates highly anomalous behavior requiring human checkpoint |
| **EMERGENCY z-score** | 4.0σ | Beyond ~99.99% of normal distribution; indicates extreme anomaly or active attack |
| **Slow-drip window** | 5 sessions | Balances detection latency vs. sensitivity; detects gradual drift before it compounds into per-session EMERGENCY |
| **Slow-drip cumulative threshold** | 10.0σ total across window | Equivalent to 2.0σ per session sustained for 5 sessions; catches gradual elevation that stays just below WARNING per session |

---

## 2. Anomaly-Type Definitions & Thresholds

### 2.1 Token Usage Spike

**Metric keys**: `tokens_total`, `tokens_per_skill_<skill_id>`, `tokens_per_tool_call_<tool_name>`

| Tier | Condition | Action |
|------|-----------|--------|
| WARNING | z ≥ 2.0σ on any token metric | Log anomaly, flag in session report |
| CRITICAL | z ≥ 3.0σ on any token metric | Notify human, require checkpoint before next phase |
| EMERGENCY | z ≥ 4.0σ on any token metric | Halt pipeline, preserve forensics |

**Description**: Sudden increase in total token consumption or per-skill/per-tool token usage. May indicate prompt injection amplification, recursive tool looping, or unbounded context growth.

**Examples**:
- Baseline μ=1000, σ=50 → WARNING at 1100, CRITICAL at 1150, EMERGENCY at 1200
- Per-skill spike where a normally 50-token skill suddenly consumes 500 tokens

---

### 2.2 Tool Call Frequency Deviation

**Metric keys**: `tool_calls_type_<type>`, `tool_calls_skill_<skill_id>`, `tool_calls_phase_<phase_id>`

| Tier | Condition | Action |
|------|-----------|--------|
| WARNING | z ≥ 2.0σ on any frequency metric | Log anomaly, flag in session report |
| CRITICAL | z ≥ 3.0σ on any frequency metric | Notify human, require checkpoint |
| EMERGENCY | z ≥ 4.0σ on any frequency metric | Halt pipeline, preserve forensics |

**Description**: Deviation in the number or pattern of tool invocations. May indicate:
- Tool-abuse loops (repeated calls to expensive or dangerous tools)
- Phase-inappropriate tool usage
- Skill hijacking (one skill calling tools assigned to another)

**Special case**: If a single tool type is called >10× in rapid succession without interleaving other operations, this triggers **CRITICAL** regardless of baseline (rate-abuse override).

---

### 2.3 Phase Skipping Attempt

**Metric keys**: `phase_transitions_total`, `phase_transitions_valid_ratio`, `phase_transition_skip_events[]`

| Tier | Condition | Action |
|------|-----------|--------|
| WARNING | valid_ratio < 0.90 (1+ invalid transitions in a session) | Log anomaly, flag in session report |
| CRITICAL | valid_ratio < 0.50 or 2+ skip events | Notify human, require checkpoint |
| EMERGENCY | Any `skip_detected=True` event OR valid_ratio = 0 | **Immediate halt** |

**Description**: Invalid transition between pipeline phases. The ecosystem defines valid phase sequences (e.g., INIT → SETUP → EXECUTE → TEARDOWN). A skip from INIT → EXECUTE bypasses safety checkpoints in SETUP.

**Integration**: `phase-controller` emits `phase_transition_events`. `drift-monitor` evaluates `valid` and `skip_detected` fields.

---

### 2.4 UNLOADED Skill Reactivation

**Metric keys**: `skill_activations`, `unloaded_reactivations[]`

| Tier | Condition | Action |
|------|-----------|--------|
| WARNING | N/A (this anomaly has no WARNING tier) | — |
| CRITICAL | N/A | — |
| EMERGENCY | Any `event_type=ACTIVATE` where `current_state=UNLOADED` | **Immediate halt** |

**Description**: A skill that has been explicitly unloaded (e.g., for security isolation or resource reclamation) receives an activation request. This may indicate:
- Registry corruption
- Confused deputy attack
- Skill reference from stale memory

**Rationale for no WARNING/CRITICAL**: There is no legitimate reason to activate an unloaded skill. Any occurrence is a direct policy violation or system integrity failure.

---

### 2.5 IPI Pattern Detection Rate Change

**Metric keys**: `ipi_detection_count`, `ipi_severity_<severity>`, `ipi_evasion_signals`

| Tier | Condition | Action |
|------|-----------|--------|
| WARNING | z ≥ 2.0σ on `ipi_detection_count` OR `ipi_evasion_signals` ≥ 1 | Log anomaly, flag in session report |
| CRITICAL | z ≥ 3.0σ on `ipi_detection_count` OR `ipi_evasion_signals` ≥ 3 | Notify human, require checkpoint |
| EMERGENCY | z ≥ 4.0σ on `ipi_detection_count` OR `ipi_evasion_signals` ≥ 5 | Halt pipeline, preserve forensics |

**Description**: Changes in Invisible Prompt Injection detection patterns. A **drop** in detection rate may indicate evasion success (attacker learned to obfuscate). A **spike** may indicate poisoning or false-positive storm. Evasion signals (fragmentation, encoding tricks, semantic splitting) are counted separately and have lower absolute thresholds because they are direct attack indicators.

**Integration**: `ipi-defender` emits periodic `ipi_detection_report`. `drift-monitor` compares against baseline and inspects `evasion_signals`.

---

### 2.6 Policy Violation

**Metric keys**: `policy_violation_count`, `policy_violation_type_<policy_id>`

| Tier | Condition | Action |
|------|-----------|--------|
| WARNING | N/A (this anomaly has no WARNING tier) | — |
| CRITICAL | N/A | — |
| EMERGENCY | `policy_violation_count` ≥ 1 | **Immediate halt** |

**Description**: Any breach of `policy-engine` rules. Policies cover:
- Output constraints (no PII, no executable code without review)
- Tool restrictions (no file deletion, no network egress to untrusted hosts)
- Skill boundaries (no cross-skill memory access)
- Human-in-the-loop requirements (high-stakes decisions)

**Rationale for no WARNING/CRITICAL**: Policy violations are explicit rule breaks, not statistical deviations. By definition they violate system governance and require immediate halt regardless of magnitude.

---

## 3. Slow-Drip (Cumulative) Thresholds

| Window | Cumulative z threshold | Trigger condition | Escalation |
|--------|----------------------|-------------------|------------|
| 5 sessions | 10.0σ | Sum of absolute z-scores across all metrics over last 5 sessions > 10.0 | Escalate to **CRITICAL** (require checkpoint) |

**Rationale**: Attackers may gradually increase resource usage or decrease detection visibility to stay below per-session WARNING. The cumulative threshold ensures sustained 2.0σ-level deviation for 5 sessions is caught. If the cumulative deviation reaches 15.0σ (3.0σ average per session), escalation is to **EMERGENCY**.

| Cumulative z | Escalation tier |
|--------------|-----------------|
| 10.0σ – 14.9σ | CRITICAL |
| ≥ 15.0σ | EMERGENCY |

---

## 4. Hard-Coded Constants (Immutable at Runtime)

```python
# From scripts/drift-monitor.py
BURN_IN_SESSIONS = 10
WARNING_Z = 2.0
CRITICAL_Z = 3.0
EMERGENCY_Z = 4.0
SLOW_DRIP_WINDOW = 5
SLOW_DRIP_CUMULATIVE_THRESHOLD = 10.0
```

**Mutation policy**: These constants are defined at module load time. There is no setter, no environment-variable override, and no configuration API exposed to the LLM. To change:

1. Human operator edits `scripts/drift-monitor.py` or `references/anomaly-thresholds.md`
2. Change is reviewed and approved via ecosystem governance
3. Ecosystem version is bumped (e.g., v4.0.0 → v4.1.0)
4. Deployment requires restart of `drift-monitor` skill

---

## 5. Threshold Summary Matrix

| Anomaly | WARNING | CRITICAL | EMERGENCY | Notes |
|---------|---------|----------|-----------|-------|
| Token usage spike | ≥2.0σ | ≥3.0σ | ≥4.0σ | Per-metric z-score |
| Tool call frequency | ≥2.0σ | ≥3.0σ | ≥4.0σ | + rate-abuse override |
| Phase skip | valid_ratio <0.90 | valid_ratio <0.50 | skip_detected=True | Immediate halt on skip |
| UNLOADED reactivation | — | — | Any occurrence | Immediate halt |
| IPI rate change | ≥2.0σ or evasion≥1 | ≥3.0σ or evasion≥3 | ≥4.0σ or evasion≥5 | Drop OR spike |
| Policy violation | — | — | ≥1 occurrence | Immediate halt |
| Slow-drip (5-ses) | — | cum z >10.0σ | cum z ≥15.0σ | Sustained gradual drift |

---

## 6. Forensics Trigger Conditions

Forensics package is automatically preserved when any of the following occur:
- EMERGENCY tier drift event (any cause)
- CRITICAL tier drift event if `preserve_forensics_on_critical=True` (default: False)
- Manual human invocation of `DriftMonitor.preserve_forensics()`

Forensics package includes:
- Timestamp and session ID
- Full log buffer (last N lines)
- Memory state snapshot (via hook)
- Tool call history (chronological)
- Complete metric series (all sessions to date)
- Active skill list
- Current phase ID
- Triggering drift event details

---

## 7. Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-01-15 | Initial threshold definitions for v4.0.0 | Ecosystem Security Team |
