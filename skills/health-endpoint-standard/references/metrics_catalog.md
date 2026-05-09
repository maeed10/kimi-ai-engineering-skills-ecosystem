# Metrics Catalog

This document lists every metric that L0 enforcement-layer skills must expose on `GET /metrics`, plus per-skill extensions, thresholds, and recommended Prometheus alert expressions.

All metrics follow Prometheus [naming best practices](https://prometheus.io/docs/practices/naming/):
- Base unit is seconds for time, bytes for size, ratios are 0–1.
- Histograms carry the `_bucket`, `_sum`, and `_count` suffixes automatically.
- Gauges may go up and down; counters are monotonic and should be queried with `rate()` or `increase()`.

---

## Baseline Metrics (All 15 L0 Skills)

Every skill must emit these metrics regardless of its specific domain.

| Metric | Type | Labels | Description | Thresholds |
|--------|------|--------|-------------|------------|
| `l0_health_status` | Gauge | `skill`, `status` | 1 if the skill reports the given status, 0 otherwise. Labels: `skill=<name>`, `status={healthy,degraded,unhealthy}`. | Alert when `status="unhealthy" == 1` for > 1 min. |
| `l0_queue_depth` | Gauge | `skill`, `queue_name` | Current number of items in the internal work queue. | Warning > 80 % of `max_queue_size`; Critical > 95 %. |
| `l0_queue_limit` | Gauge | `skill`, `queue_name` | Configured maximum queue size (for ratio alerting). | — |
| `l0_errors_total` | Counter | `skill`, `error_type` | Total number of failed validations or processing errors. `error_type` examples: `validation`, `io`, `timeout`, `panic`. | Alert when `rate(l0_errors_total[1m]) > 0.05` of total throughput. |
| `l0_requests_total` | Counter | `skill`, `result` | Total requests processed. `result={success,error,dropped}`. | — |
| `l0_request_duration_seconds` | Histogram | `skill`, `route` | Request/validation latency. `route` examples: `validate`, `health`, `ready`, `metrics`. | P99 < 500 ms for `validate`; P99 < 100 ms for `health`. |
| `l0_rule_count` | Gauge | `skill`, `source` | Active rules/policies loaded. `source={memory,cache,store}`. | Alert = 0 after startup grace period. |
| `l0_uptime_seconds` | Gauge | `skill` | Seconds since process start. | Useful for correlating restarts with incidents. |
| `l0_last_successful_validation_timestamp` | Gauge | `skill` | Unix timestamp of the last successful validation. | Alert if `time() - metric > 120`. |
| `l0_dependency_up` | Gauge | `skill`, `dependency_name` | 1 if the dependency is reachable, 0 otherwise. | Alert on 0 for critical dependencies. |
| `l0_dependency_latency_seconds` | Histogram | `skill`, `dependency_name` | Round-trip latency to each dependency. | P99 > 2 s triggers degraded status. |
| `l0_reloads_total` | Counter | `skill`, `outcome` | Number of rule/config reloads. `outcome={success,failure}`. | Alert on `rate(...{outcome="failure"}[5m]) > 0`. |
| `l0_goroutines` / `l0_threads` | Gauge | `skill` | Current goroutine or OS thread count. | Warning > 10 000 (goroutines) or > 500 (threads). |
| `l0_memory_bytes` | Gauge | `skill`, `type` | Memory usage. `type={heap,stack,total}`. | — |

---

## Per-Skill Metric Extensions

The 15 L0 skills are grouped by functional family. Each family adds the metrics below to the baseline set.

### Policy Validation Family

**Skills**: `input-policy-validator`, `output-policy-validator`, `context-policy-validator`

| Metric | Type | Labels | Description | Thresholds |
|--------|------|--------|-------------|------------|
| `l0_policies_evaluated_total` | Counter | `skill`, `policy_id`, `result` | Evaluations per policy. `result={pass,fail,error,skip}`. | — |
| `l0_policy_evaluation_duration_seconds` | Histogram | `skill`, `policy_id` | Time spent evaluating a single policy. | P99 < 50 ms per policy. |
| `l0_batch_size` | Gauge | `skill` | Current validation batch size. | Alert if > 10× normal baseline. |

### Phase Controller Family

**Skills**: `phase-controller`, `stage-gatekeeper`, `transition-validator`

| Metric | Type | Labels | Description | Thresholds |
|--------|------|--------|-------------|------------|
| `l0_phase_transitions_total` | Counter | `skill`, `from_phase`, `to_phase`, `result` | Phase transition attempts and outcomes. | Alert on `result="blocked"` rate spike. |
| `l0_active_phases` | Gauge | `skill`, `phase_name` | Number of sessions/conversations in each phase. | — |
| `l0_phase_transition_duration_seconds` | Histogram | `skill` | Time to validate and commit a phase change. | P99 < 200 ms. |

### Admission / Enforcement Family

**Skills**: `admission-controller`, `rate-limiter`, `quota-enforcer`, `circuit-breaker`

| Metric | Type | Labels | Description | Thresholds |
|--------|------|--------|-------------|------------|
| `l0_admissions_total` | Counter | `skill`, `decision` | Admission decisions. `decision={allow,deny,throttle}`. | — |
| `l0_rate_limit_hits_total` | Counter | `skill`, `limit_name` | Rate-limit breaches. | Alert if > 10 % of requests. |
| `l0_quota_consumed` | Gauge | `skill`, `user_id`, `quota_name` | Current quota consumption per principal. | Alert at 90 % of limit. |
| `l0_circuit_breaker_state` | Gauge | `skill`, `breaker_name` | 0=closed, 1=open, 2=half-open. | Alert on 1 (open). |
| `l0_throttled_requests_total` | Counter | `skill` | Requests actively throttled. | — |

### Audit & Observability Family

**Skills**: `audit-logger`, `trace-collector`, `compliance-reporter`

| Metric | Type | Labels | Description | Thresholds |
|--------|------|--------|-------------|------------|
| `l0_audit_events_total` | Counter | `skill`, `event_type`, `result` | Audit events emitted. `result={success,dropped,queued}`. | Alert on `result="dropped"` > 0. |
| `l0_audit_queue_lag_seconds` | Gauge | `skill` | Time oldest event has waited in audit queue. | Critical > 30 s. |
| `l0_trace_spans_dropped_total` | Counter | `skill`, `reason` | Dropped trace spans. | Alert if rate > 1 /s. |
| `l0_compliance_checks_total` | Counter | `skill`, `standard`, `result` | Compliance checks run. | Alert on `result="fail"` rate spike. |

### Identity & Security Family

**Skills**: `identity-validator`, `token-refresher`, `secret-scanner`

| Metric | Type | Labels | Description | Thresholds |
|--------|------|--------|-------------|------------|
| `l0_identity_validations_total` | Counter | `skill`, `result` | Identity check results. | — |
| `l0_token_refresh_duration_seconds` | Histogram | `skill` | Token rotation latency. | P99 < 1 s. |
| `l0_secrets_detected_total` | Counter | `skill`, `severity` | Secrets found in payloads. `severity={critical,high,medium,low}`. | Alert on any `critical`. |

---

## Prometheus Alert Rules

Copy these into your Prometheus `rule_files` or equivalent Cortex/Mimir namespace.

```yaml
groups:
  - name: l0_health_alerts
    interval: 15s
    rules:
      - alert: L0SkillUnhealthy
        expr: |
          l0_health_status{status="unhealthy"} == 1
        for: 1m
        labels:
          severity: critical
          layer: l0
        annotations:
          summary: "L0 skill {{ $labels.skill }} is unhealthy"
          description: "Skill {{ $labels.skill }} has reported unhealthy status for more than 1 minute."

      - alert: L0SkillDegraded
        expr: |
          l0_health_status{status="degraded"} == 1
        for: 3m
        labels:
          severity: warning
          layer: l0
        annotations:
          summary: "L0 skill {{ $labels.skill }} is degraded"
          description: "Skill {{ $labels.skill }} has been degraded for more than 3 minutes."

      - alert: L0HighErrorRate
        expr: |
          rate(l0_errors_total[1m])
          /
          clamp_min(rate(l0_requests_total[1m]), 1)
          > 0.05
        for: 2m
        labels:
          severity: critical
          layer: l0
        annotations:
          summary: "High error rate on {{ $labels.skill }}"
          description: "Error rate is {{ $value | humanizePercentage }} over the last 2 minutes."

      - alert: L0QueueDepthHigh
        expr: |
          l0_queue_depth / clamp_min(l0_queue_limit, 1) > 0.95
        for: 1m
        labels:
          severity: critical
          layer: l0
        annotations:
          summary: "Queue depth critical on {{ $labels.skill }}"
          description: "Queue {{ $labels.queue_name }} is at {{ $value | humanizePercentage }} capacity."

      - alert: L0QueueDepthWarning
        expr: |
          l0_queue_depth / clamp_min(l0_queue_limit, 1) > 0.80
        for: 3m
        labels:
          severity: warning
          layer: l0
        annotations:
          summary: "Queue depth warning on {{ $labels.skill }}"
          description: "Queue {{ $labels.queue_name }} is at {{ $value | humanizePercentage }} capacity."

      - alert: L0NoRecentValidation
        expr: |
          time() - l0_last_successful_validation_timestamp > 120
        for: 1m
        labels:
          severity: critical
          layer: l0
        annotations:
          summary: "No recent successful validation on {{ $labels.skill }}"
          description: "Last successful validation was more than 2 minutes ago."

      - alert: L0DependencyDown
        expr: |
          l0_dependency_up == 0
        for: 30s
        labels:
          severity: critical
          layer: l0
        annotations:
          summary: "Dependency {{ $labels.dependency_name }} unreachable from {{ $labels.skill }}"
          description: "Skill {{ $labels.skill }} cannot reach dependency {{ $labels.dependency_name }}."

      - alert: L0RuleCountZero
        expr: |
          l0_rule_count == 0
        for: 1m
        labels:
          severity: critical
          layer: l0
        annotations:
          summary: "Skill {{ $labels.skill }} has zero active rules"
          description: "Rule count is zero after startup grace period; skill cannot enforce policies."

      - alert: L0CircuitBreakerOpen
        expr: |
          l0_circuit_breaker_state == 1
        for: 0m
        labels:
          severity: warning
          layer: l0
        annotations:
          summary: "Circuit breaker open on {{ $labels.skill }}"
          description: "Breaker {{ $labels.breaker_name }} is open; downstream calls are failing."

      - alert: L0AuditEventsDropped
        expr: |
          rate(l0_audit_events_total{result="dropped"}[1m]) > 0
        for: 0m
        labels:
          severity: warning
          layer: l0
        annotations:
          summary: "Audit events are being dropped by {{ $labels.skill }}"
          description: "Audit queue is overflowing; compliance trail may be incomplete."
```

---

## Recording Rules (Dashboards & SLOs)

```yaml
groups:
  - name: l0_recording
    interval: 15s
    rules:
      - record: l0:request_rate_1m
        expr: rate(l0_requests_total[1m])

      - record: l0:error_rate_1m
        expr: rate(l0_errors_total[1m])

      - record: l0:availability_1m
        expr: |
          1 - (
            rate(l0_requests_total{result="error"}[1m])
            /
            clamp_min(rate(l0_requests_total[1m]), 1)
          )

      - record: l0:p99_latency
        expr: |
          histogram_quantile(0.99,
            rate(l0_request_duration_seconds_bucket[5m])
          )
```

---

## Metric Lifecycle & Cardinality Guardrails

| Guardrail | Limit | Rationale |
|-----------|-------|-----------|
| Max label values per metric | 10 000 | Prevent unbounded cardinality from `user_id` or `policy_id`. |
| Max labels per metric | 6 | Keep scrape payload small; use `info` metrics for static metadata. |
| Histogram buckets | ≤ 12 | Use default buckets: `0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10` seconds. |
| Metric name prefix | `l0_` | Uniform namespace; easy `job` aggregation. |
| Scraping interval | 15 s | Balance granularity vs. load. High-frequency skills may opt into 5 s. |

---

## Endpoint Compliance Matrix

| Skill Family | Baseline | Extensions | Notes |
|--------------|----------|------------|-------|
| Policy Validation | ✅ All | `l0_policies_evaluated_total`, `l0_policy_evaluation_duration_seconds`, `l0_batch_size` | `policy_id` cardinality capped at 500 via relabel. |
| Phase Controller | ✅ All | `l0_phase_transitions_total`, `l0_active_phases`, `l0_phase_transition_duration_seconds` | `from_phase`/`to_phase` limited to known enum values. |
| Admission / Enforcement | ✅ All | `l0_admissions_total`, `l0_rate_limit_hits_total`, `l0_quota_consumed`, `l0_circuit_breaker_state`, `l0_throttled_requests_total` | `quota_consumed` without `user_id` uses `user_hash` or aggregated bucket. |
| Audit & Observability | ✅ All | `l0_audit_events_total`, `l0_audit_queue_lag_seconds`, `l0_trace_spans_dropped_total`, `l0_compliance_checks_total` | Lag metric is critical for compliance SLAs. |
| Identity & Security | ✅ All | `l0_identity_validations_total`, `l0_token_refresh_duration_seconds`, `l0_secrets_detected_total` | `secrets_detected_total` alerts fire immediately on `critical`. |
