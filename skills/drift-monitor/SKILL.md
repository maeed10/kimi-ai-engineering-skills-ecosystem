---
name: drift-monitor
description: >
  Behavioral anomaly detection with defined thresholds, statistical baselines, and automatic safe shutdown capability. Tracks token usage patterns, tool call frequencies, phase transition validity, skill reactivation attempts, and IPI detection rate changes. Establishes baselines during 10-session burn-in period. 3-tier thresholds: WARNING (2 sigma), CRITICAL (3 sigma), EMERGENCY (4 sigma or policy violation). Integrates with phase-controller, skill-registry, error-policy, policy-engine, and ipi-defender.
---

## 1. Purpose

`drift-monitor` is the behavioral anomaly detection and safe-shutdown skill for the Kimi AI Engineering Skills Ecosystem. It defines what "drift" means in concrete, measurable terms, establishes statistical baselines during a burn-in period, and enforces 3-tier threshold-based alerting with automatic pipeline halt on EMERGENCY drift events.

Unlike the legacy `drift-detector.py` referenced in ecosystem documentation, `drift-monitor` provides:
- Explicit anomaly definitions with hard-coded or human-configured thresholds
- Statistical baselines computed from the first 10 sessions (burn-in)
- Safe shutdown capability with full forensics preservation
- Slow-drip attack detection via cumulative deviation tracking

---

## 2. Key Capabilities

### 2.1 Anomaly Definition

`drift-monitor` detects the following concrete anomaly types:

| # | Anomaly Type | Description | Source Metric |
|---|-------------|-------------|---------------|
| 1 | **Token Usage Spike** | Total or per-skill token consumption exceeds baseline by >2σ/3σ/4σ | `session.tokens.total`, `session.tokens.per_skill[]`, `session.tokens.per_tool_call[]` |
| 2 | **Tool Call Frequency Deviation** | Count of tool calls by type, skill, or phase deviates from baseline | `session.tool_calls.count_by_type[]`, `session.tool_calls.count_by_skill[]`, `session.tool_calls.count_by_phase[]` |
| 3 | **Phase Skipping Attempt** | Transition from phase N to phase N+k (k>1) without valid checkpoint | `session.phase_transitions.valid_ratio`, `session.phase_transitions.skip_events[]` |
| 4 | **UNLOADED Skill Reactivation** | A skill in `UNLOADED` state receives an activation request | `session.skill_lifecycle.unloaded_reactivations[]` |
| 5 | **IPI Pattern Detection Rate Change** | Invisible Prompt Injection detection rate drops or spikes vs. baseline | `session.ipi.detections`, `session.ipi.severity_distribution[]` |
| 6 | **Policy Violation** | Any rule from `policy-engine` is breached during session execution | `session.policy_violations.count`, `session.policy_violations.types[]` |

### 2.2 Statistical Baselines

During the **burn-in phase** (minimum 30 sessions), `drift-monitor` collects per-session metrics and computes:

- **Mean (μ)**: arithmetic mean per metric (outliers beyond 2.5σ rejected using Grubbs' test)
- **Standard Deviation (σ)**: sample standard deviation with Bessel's correction (n-1)
- **Operating Range**: [μ - 2σ, μ + 2σ] for normal operation
- **Minimum Variance Threshold**: If σ < 0.01 * μ, use absolute deviation thresholds instead of z-scores to avoid false positives from near-constant metrics

**Statistical Rigor Requirements:**
- Minimum burn-in sessions: 30 (up from 10). A 10-session window is statistically fragile for σ estimation.
- Outlier rejection: Apply Grubbs' test (alpha=0.05) to burn-in data before computing μ/σ.
- Minimum variance floor: If any metric has σ < 0.01 * μ, flag as LOW_VARIANCE and switch to absolute delta thresholds.
- Confidence interval: Report 95% CI for μ in baseline metadata: [μ - t(0.025, n-1) * σ/sqrt(n), μ + t(0.025, n-1) * σ/sqrt(n)]

Burn-in metrics are stored immutably. Drift detection is **inactive** until burn-in completes.

### 2.3 Threshold-Based Alerting

3-tier thresholds are applied to z-scores (standard scores) computed per metric:

| Tier | Z-Score | Policy Trigger | Action |
|------|---------|---------------|--------|
| **WARNING** | ≥ 2σ | N/A | Log anomaly, flag in session report, increment cumulative deviation counter |
| **CRITICAL** | ≥ 3σ | N/A | Notify human (async channel), require explicit checkpoint before pipeline continues |
| **EMERGENCY** | ≥ 4σ | OR any policy violation | **Halt pipeline**, preserve forensics, notify human with full context |

Z-score formula: `z = (x - μ) / σ` where `σ > 0`. If `σ = 0`, deviation is measured as absolute delta from μ.

### 2.4 Auto-Shutdown

On EMERGENCY drift:
1. Set pipeline state to `HALTING`
2. Capture full forensics package (see §4.5)
3. Invoke `ErrorPolicy.halt_pipeline()` via `error-policy` integration
4. Notify human through highest-priority channel with:
   - Triggering metric name and value
   - Baseline μ/σ
   - Z-score or policy violation detail
   - Session ID and phase at time of detection
   - Link to forensics package
5. Pipeline remains in `HALTED` state until human explicitly clears

### 2.5 Trend Analysis (Slow-Drip Detection)

Even if per-session metrics remain within WARNING thresholds, gradual drift over multiple sessions can indicate a slow-drip attack or systemic degradation.

- **Window**: rolling 5-session window
- **Trigger**: cumulative z-score deviation across all metrics exceeds `5 * WARNING_THRESHOLD` (i.e., 10σ cumulative)
- **Action**: escalate to CRITICAL tier, require checkpoint before next session

---

## 3. Integration Points

### 3.1 `phase-controller`
- Receives: `phase_transition_events` (from → to, timestamp, validation status)
- Drift event: `skip_detected` when transition validation fails or non-adjacent phase jump occurs without explicit override

### 3.2 `skill-registry`
- Receives: `skill_lifecycle_events` (skill_id, event_type: LOAD/UNLOAD/ACTIVATE/DEACTIVATE)
- Drift event: `unloaded_reactivation` when event_type=ACTIVATE and current state=UNLOADED

### 3.3 `error-policy`
- Sends: `halt_pipeline_request` with reason=`EMERGENCY_DRIFT` and forensics payload
- Receives: `halt_ack` / `halt_nack`
- Contract: `error-policy` MUST halt on `EMERGENCY_DRIFT` unless already in HALTED state

### 3.4 `policy-engine`
- Receives: `policy_violation_events` (policy_id, severity, context)
- Every policy violation is automatically an EMERGENCY drift event regardless of z-score

### 3.5 `ipi-defender`
- Receives: `ipi_detection_report` (count, severity_distribution, evasion_signals)
- Drift event: `ipi_rate_change` when detection count z-score ≥ WARNING or evasion_signals ≥ 1

---

## 4. Safety Rules

| # | Rule | Enforcement |
|---|------|-------------|
| R1 | **NEVER ignore an EMERGENCY drift signal** — always halt pipeline or escalate | Hard-coded in `DriftMonitor.evaluate()`; no bypass flag |
| R2 | **NEVER auto-close an EMERGENCY state without human verification** | `HALTED` state requires human `clear_emergency()` call |
| R3 | **ALWAYS maintain 10-session "burn-in" baseline before drift detection is active** | `DriftMonitor.burn_in_complete` gates all evaluation logic |
| R4 | **NEVER let anomaly thresholds be modified by the LLM** | Thresholds are hard-coded constants or loaded from human-configured `references/anomaly-thresholds.md` at startup |
| R5 | **ALWAYS preserve full context before shutdown for forensics** | `preserve_forensics()` serializes logs, memory state, tool call history, metric snapshot |
| R6 | **NEVER allow drift detection itself to be disabled without human approval** | No `disable_monitoring()` method exposed to LLM runtime |

---

## 5. Workflow

```
┌─────────────────┐
│  Session Start  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ Burn-in active?         │
│ (< 10 sessions recorded)│
└────────┬────────────────┘
   Yes │          │ No
      ▼          ▼
┌──────────┐  ┌─────────────────────┐
│ Collect  │  │ Compute z-scores    │
│ metrics  │  │ vs. baseline        │
│ only     │  └────────┬────────────┘
└──────────┘           │
                       ▼
              ┌─────────────────────┐
              │ Any z ≥ WARNING?    │
              └────────┬────────────┘
                 Yes │          │ No
                    ▼          ▼
         ┌──────────────┐  ┌──────────────┐
         │ Any z ≥ CRIT?│  │ Slow-drip?   │
         └──────┬───────┘  │ (5-ses cum)  │
            Yes │    │ No   └──────┬───────┘
               ▼    ▼             Yes │    │ No
      ┌──────────┐┌──────────┐      ▼    ▼
      │ EMERGENCY││ CRITICAL │ ┌──────────┐┌──────────┐
      │ ≥4σ or   ││ ≥3σ      │ │ CRITICAL ││ NORMAL   │
      │ policy   ││          │ │ ≥cum     ││          │
      │ violation││          │ │ threshold││          │
      └────┬─────┘└────┬─────┘ └────┬─────┘└────┬─────┘
           │           │            │           │
           ▼           ▼            ▼           ▼
      ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
      │ HALT    │ │ CHECKPT │ │ CHECKPT │ │ REPORT  │
      │ + FOREN-│ │ REQUIRED│ │ REQUIRED│ │ OK      │
      │ SICS    │ │         │ │         │ │         │
      └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### 5.1 Per-Session Metrics Collection

For every session, the following metrics are recorded:

#### Token Usage
- `tokens_total`: total tokens consumed in session
- `tokens_per_skill`: dict mapping `skill_id → token count`
- `tokens_per_tool_call`: dict mapping `tool_name → token count`

#### Tool Call Frequency
- `tool_calls_count_by_type`: dict mapping `tool_type → count`
- `tool_calls_count_by_skill`: dict mapping `skill_id → count`
- `tool_calls_count_by_phase`: dict mapping `phase_id → count`

#### Phase Transitions
- `phase_transitions_total`: total transitions observed
- `phase_transitions_valid`: count of validated transitions
- `phase_transition_skip_events`: list of `{from, to, timestamp, reason}`

#### Skill Lifecycle
- `skill_loads`: count
- `skill_unloads`: count
- `skill_activations`: count
- `skill_deactivations`: count
- `unloaded_reactivations`: list of `{skill_id, timestamp, requested_by}`

#### IPI Detections
- `ipi_detection_count`: number of IPI patterns detected
- `ipi_severity_distribution`: dict mapping `severity → count`
- `ipi_evasion_signals`: count of evasion-like patterns (e.g., obfuscation, fragmentation)

#### Policy Violations
- `policy_violation_count`: total violations
- `policy_violation_types`: dict mapping `policy_id → count`

### 5.2 Baseline Computation (Post Burn-in)

After session 10 completes:

```python
for metric in all_metrics:
    baseline.mean[metric]   = mean(session_values[metric][0:10])
    baseline.stdev[metric]  = stdev(session_values[metric][0:10])
    baseline.threshold_2sigma = baseline.mean + 2 * baseline.stdev
    baseline.threshold_3sigma = baseline.mean + 3 * baseline.stdev
    baseline.threshold_4sigma = baseline.mean + 4 * baseline.stdev
```

### 5.3 Slow-Drip Detection

```python
cumulative_deviation_window = sessions[-5:]
cumulative_z = sum(
    abs((x - baseline.mean) / baseline.stdev)
    for x in cumulative_deviation_window
    if baseline.stdev > 0
)
if cumulative_z > SLOW_DRIP_CUMULATIVE_THRESHOLD:  # 10σ default
    raise SlowDripAlert(require_checkpoint=True)
```

---

## 6. Configuration

### 6.1 Startup Parameters

| Parameter | Default | Source | Description |
|-----------|---------|--------|-------------|
| `BURN_IN_SESSIONS` | 30 | Hard-coded | Sessions required before active detection |
| `MIN_VARIANCE_RATIO` | 0.01 | Hard-coded | Minimum σ/μ ratio before switching to absolute thresholds |
| `OUTLIER_ALPHA` | 0.05 | Hard-coded | Significance level for Grubbs' outlier rejection |
| `WARNING_Z` | 2.0 | Hard-coded | Z-score for WARNING tier |
| `CRITICAL_Z` | 3.0 | Hard-coded | Z-score for CRITICAL tier |
| `EMERGENCY_Z` | 4.0 | Hard-coded | Z-score for EMERGENCY tier |
| `SLOW_DRIP_WINDOW` | 5 | Hard-coded | Rolling session window for slow-drip |
| `SLOW_DRIP_CUMULATIVE_THRESHOLD` | 10.0 | Hard-coded | Total z-score across window to trigger escalation |

> **Note**: These values are hard-coded in `drift-monitor.py` constants and documented in `references/anomaly-thresholds.md`. They require human approval and ecosystem version bump to change.

### 6.2 Runtime State

| State | Description |
|-------|-------------|
| `BURN_IN` | Collecting baseline data (sessions 1–30) |
| `ACTIVE` | Baseline established; evaluating drift per session |
| `WARNING` | One or more metrics ≥2σ; flagged in report |
| `CRITICAL` | One or more metrics ≥3σ or slow-drip triggered; checkpoint required |
| `EMERGENCY` | ≥4σ or policy violation; pipeline halted |
| `HALTED` | Pipeline execution stopped; awaiting human clearance |

---

## 7. API Reference

### 7.1 `DriftMonitor` Class

#### Constructor
```python
DriftMonitor(
    error_policy_client: ErrorPolicyClient,   # integration with error-policy
    policy_engine_client: PolicyEngineClient,  # integration with policy-engine
    notifier: Notifier,                       # human notification channel
    burn_in_sessions: int = 30,
    min_variance_ratio: float = 0.01,
    outlier_alpha: float = 0.05,
    warning_z: float = 2.0,
    critical_z: float = 3.0,
    emergency_z: float = 4.0,
    slow_drip_window: int = 5,
    slow_drip_threshold: float = 10.0
)
```

#### Methods

**`record_session(session_metrics: SessionMetrics) → DriftReport`**
- Records a completed session's metrics
- If burn-in incomplete, appends to baseline dataset only
- If burn-in complete, computes z-scores and evaluates thresholds
- Returns `DriftReport` with tier, flagged metrics, and recommended action

**`evaluate_phase_transition(event: PhaseTransitionEvent) → Optional[DriftEvent]`**
- Called live during session execution
- Returns `DriftEvent` if skip detected or invalid transition

**`evaluate_skill_lifecycle(event: SkillLifecycleEvent) → Optional[DriftEvent]`**
- Called live during session execution
- Returns `DriftEvent` on UNLOADED reactivation

**`evaluate_policy_violation(event: PolicyViolationEvent) → DriftEvent`**
- Called live during session execution
- Always returns EMERGENCY-tier `DriftEvent`

**`evaluate_ipi_report(report: IPIDetectionReport) → Optional[DriftEvent]`**
- Called at session end or on periodic IPI report
- Returns `DriftEvent` if detection rate z-score ≥ WARNING or evasion_signals > 0

**`preserve_forensics() → ForensicsPackage`**
- Captures current state: logs, memory snapshot, tool call history, metric series, active skills, phase state
- Returns serializable `ForensicsPackage`

**`clear_emergency() → bool`**
- **Human-only** API to clear HALTED state and resume pipeline
- Returns `True` if state was HALTED and is now cleared
- Returns `False` if state was not HALTED (no-op)

---

## 8. Data Structures

```python
class SessionMetrics:
    session_id: str
    tokens: TokenMetrics
    tool_calls: ToolCallMetrics
    phase_transitions: PhaseTransitionMetrics
    skill_lifecycle: SkillLifecycleMetrics
    ipi: IPIMetrics
    policy_violations: PolicyViolationMetrics

class DriftReport:
    session_id: str
    tier: DriftTier              # NORMAL | WARNING | CRITICAL | EMERGENCY
    flagged_metrics: List[FlaggedMetric]
    slow_drip_triggered: bool
    action: Action               # REPORT | CHECKPOINT | HALT
    forensics_url: Optional[str]

class FlaggedMetric:
    metric_name: str
    value: float
    baseline_mean: float
    baseline_stdev: float
    z_score: float
    tier: DriftTier

class ForensicsPackage:
    timestamp: str
    session_id: str
    logs: List[str]
    memory_state: Dict
    tool_call_history: List[Dict]
    metric_series: List[SessionMetrics]
    active_skills: List[str]
    current_phase: str
    triggering_event: DriftEvent
```

---

## 9. Testing & Validation

### 9.1 Burn-in Validation
- Assert detection is no-op for sessions 1–10
- Assert baseline mean/stdev are finite and non-negative after session 10
- Assert baseline is immutable (subsequent sessions do not alter μ/σ)

### 9.2 Threshold Validation
- Inject metric at exactly 2.0σ → expect WARNING
- Inject metric at exactly 3.0σ → expect CRITICAL
- Inject metric at exactly 4.0σ → expect EMERGENCY + halt
- Inject policy violation → expect EMERGENCY regardless of z-score

### 9.3 Slow-Drip Validation
- Inject 5 sessions at 1.9σ each → cumulative = 9.5σ → expect NORMAL (just under 10)
- Inject 5 sessions at 2.1σ each → cumulative = 10.5σ → expect CRITICAL slow-drip

### 9.4 Safety Rule Validation
- Assert no method exists to disable monitoring from LLM runtime
- Assert `clear_emergency()` requires explicit human caller token
- Assert forensics package is non-empty after EMERGENCY halt

---

## 10. Changelog

| Version | Date | Change |
|---------|------|--------|
| v4.0.0 | 2026-01-15 | Initial release replacing vague `drift-detector.py`. Defined concrete anomalies, 3-tier thresholds, burn-in baselines, auto-shutdown, slow-drip detection, and 5 integration points. |
| v4.2.1 | 2026-05-06 | Increased minimum burn-in from 10 to 30 sessions. Added Grubbs' outlier rejection, minimum variance threshold (0.01), absolute delta fallback for low-variance metrics, and 95% confidence interval reporting. |

---

## 11. References

- `references/anomaly-thresholds.md` — Per-anomaly-type threshold definitions and rationale
- `scripts/drift-monitor.py` — Reference implementation (`DriftMonitor` class)
- Related skills: `phase-controller`, `skill-registry`, `error-policy`, `policy-engine`, `ipi-defender`