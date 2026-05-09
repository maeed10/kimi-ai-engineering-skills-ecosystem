# Alerting Rules: Burn-Rate Alerting for Enforcement Layer

This document defines the burn-rate alerting rules, severity mapping, and notification routing for all L0 enforcement-layer SLOs. The goal is to page on **fast error-budget depletion** (user impact is acute) and ticket on **slow depletion** (user impact is chronic but not yet critical).

## Alerting Philosophy

- **Page only when error budget is at risk of exhaustion before the current SLO window ends.**
- **Ticket when the trend is concerning but there is no immediate risk of breach.**
- **Never alert on raw metric thresholds alone** (e.g., "CPU > 80%"); always correlate to error budget.
- **Multi-window, multi-burn-rate alerts** reduce noise while preserving detection speed.

## Burn-Rate Formula

For a given SLO window (e.g., 30 days) and a short lookback window (e.g., 1 hour):

```
burn_rate = (error_rate_in_short_window) / (1 - SLO_target)
```

A `burn_rate == 1` means the service is consuming budget exactly as expected (linear).  
A `burn_rate > 1` means the service is consuming budget faster than linear and will exhaust before the window ends.

### Example

SLO target = 99.9% → error budget = 0.1%.  
If the service has an error rate of 1% over the last hour:

```
burn_rate = 0.01 / 0.001 = 10
```

This means the service is burning budget at 10x the sustainable rate. At this velocity, the 30-day budget would be consumed in ~72 hours.

---

## Severity Definitions

| Severity | Response Time | Channel | Escalation |
|----------|--------------|---------|------------|
| **P0 — Critical** | Immediate (<= 5 min) | Page + war-room bridge | Auto-escalate to director if unacknowledged in 15 min |
| **P1 — Page** | <= 15 min | Page + Slack #incidents | Escalate to on-call manager if unacknowledged in 30 min |
| **P2 — Ticket** | <= 4 business hours | Jira ticket + Slack #alerts | Escalate if ticket untouched in 24 h |
| **P3 — Log / Dashboard** | Next business day | Metrics dashboard annotation only | No escalation |

---

## Burn-Rate Alert Matrix

### Fast Burn (P1 — Page)

| Condition | Lookback | Burn Rate | Action |
|-----------|----------|-----------|--------|
| 2% of 30-day budget consumed in 1 hour | 1 h | >= 14.4 | Page on-call |
| 1% of 30-day budget consumed in 30 min | 30 min | >= 14.4 | Page on-call (redundant safety net) |

> Derivation: 2% of 30-day budget in 1 hour → `(0.02 * 30d_budget) / 1h` = `(0.02 * 0.001 * 30d_requests) / 1h`.  
> For a service doing ~10,000 RPS, that's ~720,000 errors in one hour vs. a budget of ~25,920,000 errors in 30 days.  
> Sustaining that for 50 hours would exhaust the budget. Hence, page immediately.

### Slow Burn (P2 — Ticket)

| Condition | Lookback | Burn Rate | Action |
|-----------|----------|-----------|--------|
| 5% of 30-day budget consumed in 6 hours | 6 h | >= 6.0 | Create Jira ticket |
| 10% of 30-day budget consumed in 3 days | 3 d | >= 1.0 | Create Jira ticket (trend confirmation) |

> Rationale: A burn rate of 6.0 sustained for 5 days would exhaust the budget. A burn rate of 1.0 is exactly the "on pace to exhaust" linear rate. Both deserve human attention but not immediate paging.

### Exhaustion Imminent (P0 — War Room)

| Condition | Lookback | Threshold | Action |
|-----------|----------|-----------|--------|
| 100% of 30-day budget consumed | 30 d | >= 100% | Freeze deploys + bridge + exec notification |
| Projected exhaustion < 7 days | 3 d trend | linear regression | Preemptive war room |

> Rationale: Once budget is exhausted, the SLO is mathematically breached for the remainder of the window. The only acceptable next step is to stop adding risk (freeze deploys) and begin emergency mitigation.

### Safety SLO Breach (P0 — Always)

Certain SLOs are safety-critical, not reliability targets. Any breach is P0 regardless of burn rate because the impact is unbounded.

| SLO | Skill | Detection | Response |
|-----|-------|-----------|----------|
| Escape events == 0 | Sandbox-Executor | Audit + seccomp log | Immediate P0 |
| ACL mis-evaluation == 0 | Memory-Guard | Differential audit sampling | Immediate P0 |
| State inconsistency == 0 | Phase-Controller | CAS conflict log | Immediate P0 |
| False-negative leak == 0 | Egress-DPI-Guard | Canary leak probe | Immediate P0 |

---

## Notification Channels

### PagerDuty
- **Service**: `enforcement-layer-slo`
- **Escalation policy**: Primary on-call (rotation A/B) → Secondary on-call → Engineering manager → Director of Infrastructure.
- **Auto-resolve**: If burn rate drops below threshold for 2x the lookback period.

### Slack
- **#incidents**: All P0 and P1 alerts. Thread per alert for context aggregation.
- **#alerts**: All P2 tickets posted as threaded summary.
- **#slo-budgets**: Daily digest of current budget percentages per skill (P3).

### Jira
- **Project**: `SLO`
- **Issue type**: `Bug` for regressions; `Task` for capacity reviews.
- **Labels**: `burn-rate`, `fast-burn` or `slow-burn`, skill name, SLO name.
- **Priority**: Blocker (P0), Critical (P1), Major (P2), Minor (P3).

### Metrics Dashboard Links
Every alert must include a deep link to the pre-filtered Grafana dashboard:

```
https://grafana.example.com/d/enforcement-slo/slo-enforcer?var-skill={skill_name}&var-slo={slo_name}&from={alert_start}&to=now
```

---

## Alert Rule Templates (Prometheus / Alertmanager)

### Fast Burn Alert (P1)

```yaml
- alert: EnforcementLayer_FastBurn
  expr: |
    (
      sum by (skill, slo) (increase(errors_total[1h]))
      /
      sum by (skill, slo) (increase(requests_total[1h]))
    )
    /
    (1 - slo_target)
    > 14.4
  for: 5m
  labels:
    severity: p1
    team: enforcement
  annotations:
    summary: "Fast burn detected on {{ $labels.skill }} / {{ $labels.slo }}"
    description: "2% of 30-day error budget consumed in 1h. Burn rate: {{ $value }}x."
    dashboard: "https://grafana.example.com/d/enforcement-slo/slo-enforcer?var-skill={{ $labels.skill }}&var-slo={{ $labels.slo }}"
    runbook_url: "https://wiki.example.com/runbooks/enforcement-layer/fast-burn"
```

### Slow Burn Alert (P2)

```yaml
- alert: EnforcementLayer_SlowBurn
  expr: |
    (
      sum by (skill, slo) (increase(errors_total[6h]))
      /
      sum by (skill, slo) (increase(requests_total[6h]))
    )
    /
    (1 - slo_target)
    > 6.0
  for: 15m
  labels:
    severity: p2
    team: enforcement
  annotations:
    summary: "Slow burn detected on {{ $labels.skill }} / {{ $labels.slo }}"
    description: "5% of 30-day error budget consumed in 6h. Burn rate: {{ $value }}x."
    dashboard: "https://grafana.example.com/d/enforcement-slo/slo-enforcer?var-skill={{ $labels.skill }}&var-slo={{ $labels.slo }}"
```

### Budget Exhausted (P0)

```yaml
- alert: EnforcementLayer_BudgetExhausted
  expr: |
    (
      sum by (skill, slo) (increase(errors_total[30d]))
      /
      sum by (skill, slo) (increase(requests_total[30d]))
    )
    > (1 - slo_target)
  for: 0m
  labels:
    severity: p0
    team: enforcement
  annotations:
    summary: "Error budget exhausted for {{ $labels.skill }} / {{ $labels.slo }}"
    description: "30-day error budget is fully consumed. Freeze deploys immediately."
```

### Safety SLO Breach (P0)

```yaml
- alert: EnforcementLayer_SafetyBreach_SandboxEscape
  expr: increase(sandbox_escape_events_total[5m]) > 0
  for: 0m
  labels:
    severity: p0
    team: enforcement
    type: safety
  annotations:
    summary: "Sandbox escape detected"
    description: "A sandbox escape event was recorded. Immediate response required."
```

---

## Alert Tuning Guidelines

1. **Start with higher thresholds** after initial rollout. If false-positive pages exceed 10% of all pages, raise the burn-rate multiplier by 20%.
2. **Never disable a safety SLO alert** without a documented risk acceptance from the security team.
3. **Tune lookback windows per skill**: A batch skill (sandbox-executor) may use longer windows than a real-time skill (egress-dpi-guard). Derive from the natural job duration distribution.
4. **Add suppression for known maintenance** — pre-scheduled maintenance windows should suppress burn-rate alerts, but never suppress safety SLO alerts.

## On-Call Runbook Quick Reference

| Alert | First Check | Second Check | Third Check |
|-------|-------------|--------------|-------------|
| Fast burn | Grafana: is it a traffic spike? | Logs: any new error code? | Deploy log: did a release just land? |
| Slow burn | 7-day latency trend | Resource saturation (CPU/mem) | Rule / corpus growth (policy-engine) |
| Budget exhausted | Confirm metric correctness | Freeze deploy pipeline | Schedule post-mortem within 24 h |
| Safety breach | Isolate affected node | Preserve forensic logs | Engage security on-call immediately |
