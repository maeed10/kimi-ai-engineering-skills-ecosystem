---
name: production-drift-bridge
description: 4-layer protocol that extends drift-monitor to deployed applications by ingesting production telemetry and correlating it with agent sessions. Use when production metrics show anomalies, when validating that agent-generated code performs correctly in production, or when building closed-loop feedback from runtime behavior back to the pipeline. Auto-triggers log-analyzer and error-policy on drift detection.
---

# production-drift-bridge

4-layer runtime drift protection protocol that bridges `drift-monitor` baseline tracking with live production systems. Ingests telemetry from Prometheus, OpenTelemetry, or cloud-native metric APIs; correlates anomalies to specific agent sessions via required tags; evaluates against 3-tier sigma thresholds; and auto-triggers `log-analyzer` + `error-policy` corrective workflows.

## 1. Telemetry Ingestion Layer

Collect production metrics via one or more adapters. All ingested data must be normalized to the internal `MetricEnvelope` schema before correlation. Load `references/telemetry_adapter.md` when implementing a new adapter.

### Supported Sources
- **Prometheus**: remote-read API, `/api/v1/query_range`, recording rules
- **OpenTelemetry**: OTLP/gRPC or HTTP, span metrics, exemplars
- **Cloud-native**: AWS CloudWatch, GCP Monitoring, Azure Monitor, Datadog

### Required Metrics (always collect)
| Metric | Kind | Source Key |
|---|---|---|
| p99 latency | histogram percentile | `latency_p99` |
| Error rate | counter/rate | `error_rate` |
| Throughput | counter/rate | `requests_per_sec` |

### Normalized `MetricEnvelope`
```yaml
timestamp_ms: 1716230400000
tags:
  service: "payment-gateway"
  environment: "production"
  kimi_session_id: "abc123"
  kimi_commit_hash: "def4567"
  kimi_skill_set: "api-contract-tester"
value: 0.042
metric_name: "error_rate"
unit: "ratio"
```

### Ingestion Rules
- Batch reads at 30s or 60s granularity; no finer than 10s to avoid noise
- Enforce tag presence: if `kimi_session_id`, `kimi_commit_hash`, or `kimi_skill_set` is missing, emit a missing-tags warning and attempt backfill from deployment metadata
- Store raw envelopes in local timeseries buffer (keep last 24h) before anomaly evaluation

## 2. Session Correlation Layer

Map every production metric stream to the agent session that produced the deployed code. Load `references/correlation_schema.md` when configuring tag sources.

### Tag Resolution Order
1. **Direct labels** from metric source (e.g., Prometheus `kimi_session_id` label)
2. **Deployment metadata** sidecar — CI/CD webhook payload or container annotations
3. **Git commit → session lookup** — query the session registry by commit hash

### Correlation Output
```yaml
correlation:
  session_id: "abc123"
  commit_hash: "def4567"
  skill_set: "api-contract-tester"
  deployment_time_ms: 1716226800000
  metric_source: "prometheus"
  confidence: 1.0   # 1.0 = direct label, 0.8 = deployment metadata, 0.6 = git lookup
```

### Rules
- If confidence < 0.8, flag the correlation for manual review but continue processing
- A session can have multiple deployments; track `deployment_time_ms` to select the active one
- Correlations are cached for 5 minutes to reduce repeated lookups

## 3. Threshold Evaluation Layer

Evaluate each correlated metric stream against per-session baselines maintained by `drift-monitor`. Baselines are pre-computed rolling means and standard deviations.

### 3-Tier Thresholds
| Tier | Sigma Deviation | Action |
|---|---|---|
| **WARNING** | >= 2σ | Log, increment warning counter, notify |
| **CRITICAL** | >= 3σ | Log, **auto-trigger** `api-contract-tester` breach protocol |
| **EMERGENCY** | >= 4σ | Log, auto-trigger `log-analyzer` + `error-policy`, page on-call |

### Evaluation Pseudocode
```
for each (session_id, metric_name) stream:
    baseline = drift_monitor.get_baseline(session_id, metric_name)
    for point in window(5m):
        deviation = abs(point.value - baseline.mean) / baseline.std
        if deviation >= 4.0:
            emit(EMERGENCY, point)
            auto_trigger("log-analyzer", "error-policy", session_id, point)
        elif deviation >= 3.0:
            emit(CRITICAL, point)
            auto_trigger("api-contract-tester", "breach", session_id, point)
        elif deviation >= 2.0:
            emit(WARNING, point)
```

### Rules
- Baselines must exist for at least 1h before evaluation starts; otherwise skip with `baseline_insufficient` status
- Sigma calculations use population std dev over the baseline window (not sample std dev)
- Multiple metrics can breach simultaneously — each triggers independently
- Evaluation runs continuously; emit at most 1 alert per (session, metric, tier) per 5-minute window to prevent flapping

## 4. Auto-Trigger & Trust Score Feedback Layer

### Auto-Trigger Chain

| Detected Breach | First Action | Second Action | Escalation |
|---|---|---|---|
| `api-contract-tester` breach → production metrics | invoke `log-analyzer` on session logs | invoke `error-policy` to evaluate rollback | page on-call if error-policy flags `rollback_required` |
| `drift-monitor` baseline deviation | correlate to deployment → production telemetry | invoke `api-contract-tester` for contract validation | invoke `log-analyzer` if contracts fail |
| Any EMERGENCY threshold | invoke `log-analyzer` + `error-policy` immediately | lock further deployments for session | manual review gate |

### Trust Score Feedback Loop
Production outcomes directly influence session trust scores consumed by `memory-guard`.

| Outcome | Trust Score Effect | Halflife |
|---|---|---|
| Clean deployment (0 breaches 24h) | +0.05 | 24h |
| WARNING breach | -0.02 | 6h |
| CRITICAL breach | -0.10 | 6h |
| EMERGENCY breach | -0.25 | 6h |
| Rollback executed | -0.15 additional | 6h |

```
trust_score = clamp(base_score + Σ(outcome_effects), 0.0, 1.0)
effective_score = trust_score * 2^(-elapsed / halflife)
```

### Rules
- Trust score updates are sent to `memory-guard` via the session registry API
- A session with trust score < 0.3 is auto-flagged for `restricted-deploy` mode (requires manual approval)
- A session with trust score < 0.1 is auto-flagged for `blocked-deploy` mode (no deployments allowed)
- Successful deployments that remain clean for 7 consecutive days add a +0.10 permanent bonus (max 1.0)

## 5. Operational Workflow

### On Production Metric Anomaly
1. Ingest metrics via configured adapter(s) → `MetricEnvelope`
2. Correlate to agent session using tag resolution order
3. Evaluate against `drift-monitor` baselines using 3-tier sigma thresholds
4. On CRITICAL/EMERGERY: execute auto-trigger chain (`log-analyzer` → `error-policy`)
5. Update session trust score in `memory-guard`
6. Emit structured alert with session context, metric snapshot, and recommended action

### On `api-contract-tester` Breach
1. Receive breach notification with `kimi_session_id` and metric evidence
2. Ingest last 1h of production telemetry for that session
3. Confirm correlation; evaluate if breach is production-wide or canary-scoped
4. Auto-trigger `log-analyzer` + `error-policy`
5. Update trust score based on outcome

## Output Format

All drift reports must contain:
- `session_id`, `commit_hash`, `skill_set`
- Metric snapshot at breach time (value, baseline mean, baseline std, sigma deviation)
- Tier classification (WARNING / CRITICAL / EMERGENCY)
- Triggered actions (which skills were invoked)
- Trust score delta and new effective score
- Recommended next action (monitor / investigate / rollback / block)
