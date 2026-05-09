---
name: canary-orchestrator
description: Progressive delivery orchestration skill that translates blast-radius-calculator risk scores into deployment strategies (canary, blue-green, direct) and monitors production health post-deployment with auto-rollback. Use when deploying agent-generated changes, configuring progressive rollouts, or managing deployment risk. Integrates with ci-cd-integrator and error-policy.
---

# Canary Orchestrator

## Overview

Orchestrates progressive delivery (canary, blue-green, direct) based on `blast-radius-calculator` risk scores. Monitors production health post-deployment and triggers auto-rollback on error spikes. Every traffic shift, health observation, and rollback decision is recorded in a cryptographic audit trail.

## Workflow

```
┌─────────────────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│ 1. LOAD RISK SCORE      │────▶│ 2. SELECT STRATEGY  │────▶│ 3. DEPLOY        │
│    (blast-radius-calc)  │     │    (strategy_matrix)│     │    (ci-cd-integr)│
└─────────────────────────┘     └─────────────────────┘     └──────────────────┘
                                                                    │
                              ┌─────────────────────┐              │
                              │ 5. ROLLBACK/PROCEED │◀─────────────┘
                              │    (auto or manual) │     4. HEALTH PROBE
                              └─────────────────────┘        (continuous)
```

### Step 1: Load Risk Score

Read the risk score artifact from `blast-radius-calculator`. The artifact is a JSON file with this schema:

```json
{
  "risk_score": 7,
  "max_risk_dimension": "data_integrity",
  "blast_radius": "file_scope",
  "affected_components": ["user-service", "payment-gateway"],
  "confidence": 0.85,
  "generated_at": "2025-01-15T09:32:00Z"
}
```

If the risk score artifact is missing or malformed, abort deployment and surface the error to `error-policy`. Do not default to a safe strategy — missing risk data is a blocking condition.

### Step 2: Select Strategy

Use `references/strategy_matrix.md` to map `risk_score` → deployment strategy. Strategy selection is deterministic:

| Risk Score | Strategy | Description |
|-----------|----------|-------------|
| `< 5` | `direct` | Full traffic shift immediately |
| `5–8` | `blue-green` | Parallel environment, instant cutover with rollback option |
| `>= 9` | `canary` | 1% → 5% → 25% → 50% → 100% SLO-gated traffic ramp |

Record the selected strategy and justification in the audit trail before proceeding.

### Step 3: Deploy via ci-cd-integrator

Generate a deployment configuration and pass it to `ci-cd-integrator`. The config must include:

```yaml
deployment:
  strategy: "canary"   # or "blue-green" / "direct"
  risk_score: 9
  version: "v1.2.3"
  previous_stable: "v1.2.2"
  feature_flags:
    - name: "new-checkout-flow"
      default: false
      targeting:
        - rule: "canary_traffic"
          enabled: true
          percentage: 1   # overridden by orchestrator during ramp
  canary_steps:          # only when strategy == canary
    - percentage: 1
    - percentage: 5
    - percentage: 25
    - percentage: 50
    - percentage: 100
```

For `canary`, `ci-cd-integrator` sets the initial feature flag percentage. This skill controls subsequent ramp steps via the health probe loop.

### Step 4: Health Probe (Continuous)

After deployment, begin the health probe loop. Sampling frequency and observation windows are defined in `references/health_thresholds.md`.

**Metrics to sample:**
- `http_error_rate` — 5xx / total requests
- `p99_latency_ms` — 99th percentile response time
- `throughput_rps` — requests per second
- `custom_slo_indicators` — any domain-specific SLOs from the service catalog

**Probe schedule by strategy:**

| Strategy | Window | Sample Interval | Promote If | Rollback If |
|----------|--------|----------------|------------|-------------|
| `direct` | 5 min | 10s | N/A (single shift) | any threshold breach |
| `blue-green` | 30 min | 30s | stable throughout | any threshold breach |
| `canary` | 15 min per step | 30s | all SLOs pass step gate | any threshold breach |

**Step-gate logic for canary:** Each percentage step is a gate. Promote to the next step only if all metrics pass for the full 15-minute observation window. If a step fails, rollback to `previous_stable` immediately — do not hold at the current percentage.

### Step 5: Auto-Rollback or Proceed

**Rollback triggers** (from `references/health_thresholds.md`):

1. **Error rate spike**: `error_rate > baseline_error_rate + 3σ` OR `error_rate > 1%`
2. **Latency regression**: `p99_latency > baseline_p99 * 1.5`
3. **Throughput collapse**: `throughput < baseline_throughput * 0.5`
4. **Custom SLO breach**: any configured SLO indicator exceeds its threshold
5. **Probe timeout**: zero healthy samples for `2 * sample_interval`

**Rollback procedure:**
1. Set feature flag percentage to 0 (new version) / 100 (previous stable)
2. For blue-green: switch load balancer to previous stable environment
3. Emit rollback event to audit trail with trigger reason and metric snapshot
4. Notify `error-policy` with severity `critical` and attach metric data
5. Keep the failed revision deployed but receiving 0% traffic for post-mortem analysis

**Proceed signal:** If the observation window completes with all SLOs satisfied, promote:
- `blue-green`: confirm cutover, decommission old environment after 60 min buffer
- `canary`: advance to next percentage step; at 100% mark deployment complete
- `direct`: deployment complete on successful 5-min window

## Audit Trail

Every event in the deployment lifecycle is appended to an immutable audit log.

**Event schema:**
```json
{
  "event_id": "uuid-v4",
  "timestamp": "RFC3339",
  "event_type": "strategy_selected | deployment_initiated | health_sample | step_promoted | rollback_triggered | deployment_complete",
  "deployment_id": "uuid-v4",
  "version": "v1.2.3",
  "previous_stable": "v1.2.2",
  "details": {},
  "signature": "ed25519:<base64-signature>"
}
```

**Events that must be signed:**
- `strategy_selected` — includes risk score and chosen strategy
- `step_promoted` — includes from/to percentage and metric summary
- `rollback_triggered` — includes trigger reason and full metric snapshot
- `deployment_complete` — includes final strategy outcome

The signing key is environment-specific. If no key is configured, log a warning but continue — the event is still recorded, just unauthenticated.

## Integration Points

| Skill | Direction | Purpose |
|-------|-----------|---------|
| `blast-radius-calculator` | input | Risk score that drives strategy selection |
| `ci-cd-integrator` | output | Generates deployment config; executes traffic shifts |
| `error-policy` | output | Escalation channel for rollbacks and probe failures |

## Resources

- `references/strategy_matrix.md` — Full risk-to-strategy mapping with rationale
- `references/health_thresholds.md` — Metric thresholds, observation windows, rollback rules
