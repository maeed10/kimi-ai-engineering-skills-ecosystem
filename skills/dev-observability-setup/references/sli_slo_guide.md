# SLI / SLO Guide

A practical guide for defining, measuring, and alerting on Service Level Indicators (SLIs) and Service Level Objectives (SLOs) in Prometheus-based environments.

## Table of Contents

1. [Fundamentals](#fundamentals)
2. [SLI Selection](#sli-selection)
3. [SLO Target Negotiation](#slo-target-negotiation)
4. [Error Budget Math](#error-budget-math)
5. [Burn-Rate Alerting](#burn-rate-alerting)
6. [PromQL Implementations](#promql-implementations)
7. [Dashboard Design](#dashboard-design)
8. [Incident Response Playbook](#incident-response-playbook)

---

## Fundamentals

### Definitions

| Term | Definition | Example |
|------|-----------|---------|
| **SLI** | Service Level Indicator — a quantitative measure of service behavior | " proportion of HTTP requests < 200ms " |
| **SLO** | Service Level Objective — a target value for an SLI over a time window | " 99.9% of requests < 200ms over 30 days " |
| **Error Budget** | The allowable unreliability (1 - SLO) over the compliance window | 0.1% of requests may exceed 200ms in 30 days |
| **Burn Rate** | How fast the error budget is being consumed relative to the ideal rate | 1x = budget exhausted exactly at window end |

### Why SLOs Matter

- They align engineering effort with user-perceived reliability
- They provide an objective signal for prioritizing reliability work vs feature work
- They reduce alert fatigue by paging only when error budgets are threatened
- They make canary analysis and deployment gates data-driven

---

## SLI Selection

### SLI Specification Template

For each SLI, fill out:

```
SLI Name: [availability|latency|throughput|freshness|correctness|coverage]
Metric: [PromQL expression or metric name]
Good Events: [definition of what counts as "good"]
Valid Events: [definition of the total event set]
Labels: [dimensions to aggregate by: service, method, status, environment]
```

### Common SLIs by Service Type

#### Request-Driven (HTTP / gRPC / API)

| Category | SLI | Good Events | Valid Events |
|----------|-----|-------------|--------------|
| Availability | Ratio of successful requests | `status !~ "5.."` | All requests |
| Latency | Proportion fast enough | `duration <= threshold` | All requests |
| Quality | Proportion of correct responses | Response validated correct | All requests |

**Recommended minimum**: Availability + Latency

#### Pipeline / Batch (ETL, ML training, CI)

| Category | SLI | Good Events | Valid Events |
|----------|-----|-------------|--------------|
| Freshness | Proportion of data recent enough | `now() - last_update <= threshold` | All data partitions |
| Coverage | Proportion of expected runs completed | `run_count >= expected_count` | All scheduled runs |
| Correctness | Proportion of outputs passing validation | `validation_pass == true` | All outputs |

#### Storage / Database

| Category | SLI | Good Events | Valid Events |
|----------|-----|-------------|--------------|
| Availability | Proportion of successful operations | `error == false` | All read/write operations |
| Durability | Proportion of data retained without loss | `loss == false` | All stored objects |
| Latency | Proportion of fast operations | `duration <= threshold` | All operations |

### SLI Anti-Patterns

- **Using infrastructure metrics as SLIs directly**: CPU usage is not a user-facing SLI. Derive from request outcomes.
- **Overly broad definitions**: "All requests" may hide problems in critical endpoints. Segment by `path` or `method`.
- **Too many SLIs**: Start with 2-3. More than 5 SLOs per service becomes operationally noisy.
- **Lacking valid event filtering**: Exclude health checks, load balancer probes, and synthetic traffic from valid events.

---

## SLO Target Negotiation

### Selecting the Target

| SLO Target | Downtime Budget (30d) | Typical Use Case |
|------------|----------------------|------------------|
| 99% | 7h 12m | Internal tools, batch pipelines |
| 99.5% | 3h 36m | Non-critical customer-facing services |
| 99.9% | 43m 12s | Core APIs, payment services |
| 99.99% | 4m 19s | Critical infrastructure, auth services |
| 99.999% | 25s | Life-critical, extremely expensive to achieve |

### Negotiation Process

1. **Measure current performance** for 2-4 weeks without an SLO target. Use the 50th percentile of observed SLI values as a starting baseline.
2. **Identify user pain points**: What error rate or latency actually causes support tickets, churn, or revenue impact?
3. **Account for dependency SLOs**: Your SLO cannot be tighter than your critical dependency's SLO. If your database promises 99.9%, your service cannot realistically promise 99.99% without redundancy.
4. **Leave headroom**: Set internal SLOs 0.1-0.5% higher than external SLAs to provide a buffer.
5. **Review quarterly**: Adjust targets based on operational data and business needs.

### Window Selection

| Window | Use Case | Trade-off |
|--------|----------|-----------|
| Rolling 30 days | Standard for most services | Balances responsiveness with statistical stability |
| Calendar month | Aligns with billing / reporting | Less responsive; edge effects at month boundaries |
| Rolling 7 days | Fast iteration, high-churn services | Higher variance; may require wider alerting bands |
| Rolling 90 days | Infrastructure platforms | Very stable; slow to reflect regressions |

---

## Error Budget Math

### Basic Formula

```
Error Budget = (1 - SLO) * Valid Events in Window
```

Example:
- SLO = 99.9% availability
- 1,000,000 requests in 30 days
- Error budget = 0.001 * 1,000,000 = 1,000 failed requests

### Burn Rate

Burn rate measures how fast the error budget is being consumed:

```
Burn Rate = (Current Error Ratio) / (1 - SLO)
```

Example:
- SLO = 99.9% → budget ratio = 0.001
- Current hour: 5% errors
- Burn rate = 0.05 / 0.001 = 50x
- At 50x burn, the 30-day budget is consumed in ~14.4 hours

### Alerting Thresholds

Google SRE Workbook recommends multi-window, multi-burn-rate alerts:

| Burn Rate | Lookback Window | Minimum Alert Duration | Alert Type |
|-----------|----------------|----------------------|------------|
| 14.4x | 1 hour | 2 minutes | Page immediately |
| 6x | 6 hours | 3 minutes | Page within 1 hour |
| 2x | 3 days | 5 minutes | Ticket within 3 days |
| 1x | 1 week | 10 minutes | Ticket, review weekly |

The math: if you alert when `(error rate over short window) / (1 - SLO) >= burn_rate` for a sufficient duration, you guarantee that the alert fires before the budget is consumed.

---

## Burn-Rate Alerting

### The Multi-Window Approach

A single alert rule evaluates two time windows simultaneously. This prevents:
- **Spurious pages** from brief blips (the long window smooths noise)
- **Missed pages** from gradual degradation (the short window catches fast burns)

### Rule Structure

```yaml
groups:
  - name: slo_burn_rate
    rules:
      # Recording rule: current error ratio over 1h
      - record: slo:error_rate_1h
        expr: |
          (
            sum by (service) (rate(http_requests_total{status=~"5.."}[1h]))
            /
            sum by (service) (rate(http_requests_total[1h]))
          )

      # Recording rule: current error ratio over 5m
      - record: slo:error_rate_5m
        expr: |
          (
            sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
            /
            sum by (service) (rate(http_requests_total[5m]))
          )

      # Recording rule: error ratio over 6h
      - record: slo:error_rate_6h
        expr: |
          (
            sum by (service) (rate(http_requests_total{status=~"5.."}[6h]))
            /
            sum by (service) (rate(http_requests_total[6h]))
          )

      # Recording rule: error ratio over 3d
      - record: slo:error_rate_3d
        expr: |
          (
            sum by (service) (rate(http_requests_total{status=~"5.."}[3d]))
            /
            sum by (service) (rate(http_requests_total[3d]))
          )
```

### Critical Alert (Page): 14.4x Burn

```yaml
      - alert: ErrorBudgetBurn14x
        expr: |
          (
            slo:error_rate_1h{service=~".+"} > (14.4 * 0.001)
          and
            slo:error_rate_5m{service=~".+"} > (14.4 * 0.001)
          )
        for: 2m
        labels:
          severity: critical
          team: sre
        annotations:
          summary: "High error budget burn rate on {{ $labels.service }}"
          description: "1h error rate {{ $value | humanizePercentage }} exceeds 14.4x burn for 99.9% SLO"
          runbook_url: "https://wiki.internal/runbooks/error-budget-burn"
```

### Fast Burn Alert (Page): 6x Burn

```yaml
      - alert: ErrorBudgetBurn6x
        expr: |
          (
            slo:error_rate_6h{service=~".+"} > (6 * 0.001)
          and
            slo:error_rate_30m{service=~".+"} > (6 * 0.001)
          )
        for: 5m
        labels:
          severity: critical
          team: sre
        annotations:
          summary: "Moderate error budget burn on {{ $labels.service }}"
          description: "6h error rate {{ $value | humanizePercentage }} exceeds 6x burn for 99.9% SLO"
```

### Slow Burn Alert (Ticket): 2x Burn

```yaml
      - alert: ErrorBudgetBurn2x
        expr: |
          (
            slo:error_rate_3d{service=~".+"} > (2 * 0.001)
          and
            slo:error_rate_6h{service=~".+"} > (2 * 0.001)
          )
        for: 10m
        labels:
          severity: warning
          team: sre
        annotations:
          summary: "Slow error budget burn on {{ $labels.service }}"
          description: "3d error rate {{ $value | humanizePercentage }} exceeds 2x burn for 99.9% SLO. Investigate within 3 days."
```

### Adjusting for Different SLO Targets

Replace `0.001` with `(1 - SLO)`:

| SLO | (1 - SLO) | 14.4x Threshold | 6x Threshold | 2x Threshold |
|-----|-----------|-----------------|--------------|--------------|
| 99% | 0.01 | 14.4% | 6% | 2% |
| 99.5% | 0.005 | 7.2% | 3% | 1% |
| 99.9% | 0.001 | 1.44% | 0.6% | 0.2% |
| 99.99% | 0.0001 | 0.144% | 0.06% | 0.02% |

---

## PromQL Implementations

### SLI: Availability Ratio

```promql
# Availability over 30d rolling window
1 - (
  sum(increase(http_requests_total{status=~"5.."}[30d])) by (service)
  /
  sum(increase(http_requests_total[30d])) by (service)
)
```

### SLI: Latency Proportion

```promql
# Proportion of requests under 200ms over 30d
1 - (
  (
    sum(increase(http_request_duration_seconds_bucket{le="0.2"}[30d])) by (service)
    -
    sum(increase(http_request_duration_seconds_bucket{le="+Inf"}[30d])) by (service)
  )
  /
  sum(increase(http_request_duration_seconds_count[30d])) by (service)
)
# Simpler: use bucket directly if histogram is cumulative
sum(increase(http_request_duration_seconds_bucket{le="0.2"}[30d])) by (service)
/
sum(increase(http_request_duration_seconds_count[30d])) by (service)
```

### Error Budget Remaining

```promql
# Remaining budget % for 30-day availability SLO of 99.9%
(
  0.001 - (
    sum(increase(http_requests_total{status=~"5.."}[30d])) by (service)
    /
    sum(increase(http_requests_total[30d])) by (service)
  )
)
/
0.001
```

### Current Burn Rate

```promql
# Current hourly burn rate vs 1x (ideal)
(
  sum(rate(http_requests_total{status=~"5.."}[1h])) by (service)
  /
  sum(rate(http_requests_total[1h])) by (service)
)
/
0.001
```

### Budget Exhaustion Forecast

```promql
# Hours until budget exhausted at current burn rate, if > 1x
(
  (
    0.001 * sum(increase(http_requests_total[30d])) by (service)
    -
    sum(increase(http_requests_total{status=~"5.."}[30d])) by (service)
  )
  /
  sum(rate(http_requests_total{status=~"5.."}[1h])) by (service)
)
```

### Filtering Out Health Checks

```promql
# Exclude known health check paths from valid events
sum(
  rate(http_requests_total{path!~"/healthz|/readyz|/livez|/metrics"}[5m])
) by (service)
```

---

## Dashboard Design

### SLO Dashboard Layout

**Row 1: SLI Compliance**
- Singlestat: Current 30d SLI value with color thresholds (green > SLO, yellow close, red below)
- Singlestat: Remaining error budget %
- Graph: SLI value over last 90 days with SLO line reference

**Row 2: Burn Rate Analysis**
- Timeseries: Current burn rate (1h, 6h, 3d windows) with 1x/2x/6x/14.4x reference lines
- Singlestat: Hours until budget exhaustion at current rate
- Bar gauge: Budget consumed by day of month

**Row 3: Alert Status**
- Table: Active burn-rate alerts (severity, start time, service, current value)
- Annotation overlay on SLI graph showing incident start/end times

**Row 4: Root Cause Links**
- Link to RED dashboard for the service (filtered time range)
- Link to Jaeger trace search for the service
- Link to Loki error logs for the service

### Grafana Panel JSON: Burn Rate Gauge

```json
{
  "datasource": {"type": "prometheus", "uid": "${datasource}"},
  "fieldConfig": {
    "defaults": {
      "unit": "short",
      "min": 0,
      "max": 20,
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "green", "value": null},
          {"color": "yellow", "value": 2},
          {"color": "orange", "value": 6},
          {"color": "red", "value": 14.4}
        ]
      }
    }
  },
  "options": {
    "orientation": "auto",
    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
    "showThresholdLabels": true,
    "showThresholdMarkers": true
  },
  "pluginVersion": "10.0.0",
  "targets": [
    {
      "expr": "(sum(rate(http_requests_total{status=~\"5..\",service=\"$service\"}[1h])) / sum(rate(http_requests_total{service=\"$service\"}[1h]))) / 0.001",
      "legendFormat": "1h burn rate",
      "refId": "A"
    }
  ],
  "title": "Current Burn Rate (1h)",
  "type": "gauge"
}
```

### Grafana Panel JSON: Error Budget Remaining

```json
{
  "datasource": {"type": "prometheus", "uid": "${datasource}"},
  "fieldConfig": {
    "defaults": {
      "unit": "percentunit",
      "min": -0.5,
      "max": 1,
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red", "value": null},
          {"color": "orange", "value": 0},
          {"color": "yellow", "value": 0.25},
          {"color": "green", "value": 0.5}
        ]
      }
    }
  },
  "options": {
    "colorMode": "background",
    "graphMode": "area",
    "justifyMode": "auto",
    "orientation": "auto",
    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
    "showPercentChange": false,
    "textMode": "auto",
    "wideLayout": true
  },
  "pluginVersion": "10.0.0",
  "targets": [
    {
      "expr": "(0.001 - (sum(increase(http_requests_total{status=~\"5..\",service=\"$service\"}[30d])) / sum(increase(http_requests_total{service=\"$service\"}[30d])))) / 0.001",
      "legendFormat": "Budget Remaining",
      "refId": "A"
    }
  ],
  "title": "30d Error Budget Remaining",
  "type": "stat"
}
```

---

## Incident Response Playbook

### When a Burn-Rate Alert Pages

1. **Acknowledge** within 5 minutes
2. **Open the SLO dashboard** for the affected service
3. **Check the RED dashboard** — is this high error rate, high latency, or both?
4. **Find a trace** — click from Grafana to Jaeger using the trace_id in logs or the Jaeger panel
5. **Read recent logs** — Loki query: `{service="X"} |= "error"` for the alert time range
6. **Identify scope** — is it one pod, one AZ, all instances?
7. **Decide**: Rollback deployment? Scale up? Failover? Disable feature flag?
8. **Document** in incident channel; update runbook if gap found
9. **Post-incident**: Measure error budget consumed. If > 20% in a single incident, schedule post-mortem.

### Error Budget Policy

When the 30-day error budget is exhausted:

| Budget Remaining | Action |
|-----------------|--------|
| > 50% | Normal operations |
| 25-50% | Increase monitoring; defer non-critical deploys |
| 10-25% | Freeze feature releases; prioritize reliability work |
| < 10% | All deploys require SRE approval; incident commander rotation |
| 0% (exhausted) | Halt all non-urgent changes; mandatory post-mortem; reliability sprint |

### Quarterly SLO Review Agenda

1. Review each service's SLI vs SLO for the quarter
2. Identify services that consistently stayed well above target (consider tightening SLO)
3. Identify services that missed target (investigate root causes, decide on target adjustment or engineering investment)
4. Update SLI definitions if service boundaries or architecture changed
5. Refresh burn-rate alert thresholds if SLO targets changed
