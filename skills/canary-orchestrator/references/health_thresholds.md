# Health Thresholds

Metric thresholds, observation windows, and rollback rules for post-deployment health monitoring.

## Baseline Collection

Before deployment, establish a 30-minute baseline of the current stable revision. Sample at the same interval as post-deploy probes. Record:

| Metric | Baseline Statistic |
|--------|-------------------|
| `error_rate` | mean + 2σ |
| `p99_latency_ms` | p95 of the window |
| `throughput_rps` | mean |

If baseline data is unavailable (new service, cold start), use static fallback thresholds from the "Fallback Thresholds" section below.

## Rollback Triggers

Trigger rollback when **any** of the following conditions are met:

| # | Condition | Threshold | Measurement Window |
|---|-----------|-----------|-------------------|
| 1 | Error rate spike | `error_rate > baseline_error_rate + 3σ` **OR** `error_rate > 1%` | 2 consecutive samples (60s at 30s interval) |
| 2 | Latency regression | `p99_latency > baseline_p99 * 1.5` | 3 consecutive samples (90s at 30s interval) |
| 3 | Throughput collapse | `throughput < baseline_throughput * 0.5` | 2 consecutive samples (60s at 30s interval) |
| 4 | Custom SLO breach | Per-indicator threshold from service catalog | Per-indicator config |
| 5 | Probe timeout | Zero healthy samples | `2 * sample_interval` |
| 6 | Error budget exhaustion | Cumulative errors exceed step error budget | Full observation window |

### Consecutive Sample Rule

Thresholds use consecutive samples to avoid rollback on transient spikes. A single out-of-bounds sample triggers a `warning` log; consecutive out-of-bounds samples trigger `rollback`. The rollback decision is made at the first sample that completes the consecutive sequence.

## Canary Step Gates

Each canary percentage step has a dedicated error budget. Exhausting the budget fails the gate and triggers rollback.

| Step | Traffic % | Max Error Budget (5xx) | Max Latency Regression | Hold Duration |
|------|-----------|----------------------|----------------------|---------------|
| 1 | 1% | 10 requests | 2x baseline p99 | 15 min |
| 2 | 5% | 50 requests | 1.75x baseline p99 | 15 min |
| 3 | 25% | 200 requests | 1.5x baseline p99 | 15 min |
| 4 | 50% | 500 requests | 1.35x baseline p99 | 15 min |
| 5 | 100% | 1000 requests | 1.2x baseline p99 | 15 min |

If a step clears its hold duration without exhausting the error budget, promote to the next step. If the error budget is exhausted at any point, rollback immediately — even if the hold duration has not elapsed.

## Fallback Thresholds

Use when baseline data is unavailable:

| Metric | Fallback Threshold |
|--------|-------------------|
| `error_rate` | 0.5% |
| `p99_latency_ms` | 2000 ms |
| `throughput_rps` | 10% of provisioned capacity |

## Sample Configuration

```yaml
health_probe:
  sample_interval_seconds: 30
  strategies:
    direct:
      observation_window_minutes: 5
    blue_green:
      observation_window_minutes: 30
    canary:
      observation_window_minutes: 15
      steps: [1, 5, 25, 50, 100]
  rollback:
    consecutive_samples_error: 2
    consecutive_samples_latency: 3
    consecutive_samples_throughput: 2
    error_rate_absolute_max: 0.01
    latency_multiplier: 1.5
    throughput_multiplier: 0.5
```

## Alert Severity Mapping

| Event | Severity | Channel |
|-------|----------|---------|
| Single threshold breach (warning) | `warning` | Audit log only |
| Rollback triggered | `critical` | `error-policy` + audit log + on-call |
| Step promotion | `info` | Audit log |
| Deployment complete | `info` | Audit log + team notification |
| Probe timeout | `critical` | `error-policy` + audit log |
