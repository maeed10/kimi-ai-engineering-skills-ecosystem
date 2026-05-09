---
name: dev-incident-responder
description: Developer-facing incident response skill that guides triage, remediation, and post-mortem generation. Use when alerts fire, investigating outages, coordinating multi-team responses, or writing blameless post-mortems. Integrates with PagerDuty, Slack, status pages, and observability tools. Tracks MTTD, MTTR, and action items.
---

# dev-incident-responder

Guides incident response from detection through resolution and post-mortem. Integrates with alerting systems, provides runbook-driven remediation, generates blameless post-mortems, and tracks action items to completion.

## When to Use This Skill

- A production alert fires (high error rate, latency spike, downtime, memory pressure)
- Investigating a customer-reported issue that may be systemic
- Coordinating a multi-team incident response
- Writing a post-mortem after an incident is resolved
- Running a chaos engineering exercise and something breaks
- On-call handoff or shift-start incident briefings

## Incident Response Lifecycle

All incidents follow the `DETECT → TRIAGE → MITIGATE → RESOLVE → LEARN` loop. The skill acts as an on-call partner at each stage.

```
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ DETECT  │───▶│ TRIAGE  │───▶│ MITIGATE│───▶│ RESOLVE │───▶│  LEARN  │
│         │    │         │    │         │    │         │    │         │
│ Alert   │    │ Classify│    │ Execute │    │ Verify  │    │ Post-   │
│ Ticket  │    │ Corr-   │    │ Runbook │    │ Monitor │    │ mortem  │
│ Page    │    │ elate   │    │ Escalate│    │ Communicate│   │ Track   │
└─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘
```

At each stage, ask the user: **"What signal triggered this?"** and **"What is the customer impact?"** — these two questions anchor every decision.

## Severity Classification

Classify immediately upon detection. Severity drives notification channels, response-time expectations, and escalation paths.

| Level | Name | Criteria | Response Time | Notification |
|-------|------|----------|---------------|--------------|
| **SEV1** | Critical | Complete service outage; data loss; security breach; revenue-critical failure | Immediate (15 min) | Page on-call + exec + status page + war room |
| **SEV2** | Major | Significant degradation; major feature unusable; partial outage affecting >25% users | 30 minutes | Page on-call + team lead + status page |
| **SEV3** | Minor | Degraded experience; isolated feature broken; workaround available | 2 hours | Ticket/Slack alert; no page |
| **SEV4** | Low | Cosmetic issues; monitoring noise; non-production failures | Next business day | Ticket only |

**Severity can be upgraded or downgraded** as new information emerges. Document every change with timestamp and reasoning.

### Severity Decision Tree

```
Is the service completely unavailable?
  YES → SEV1
  NO → Is customer data at risk or being modified incorrectly?
          YES → SEV1
          NO → Is a major feature degraded for >25% of users?
                  YES → SEV2
                  NO → Is there a workaround and <25% affected?
                          YES → SEV3
                          NO → SEV4
```

## Step 1: Detection & Triage

### Alert Correlation Checklist

When an alert fires, triage by correlating signals across the observability stack:

1. **Alerts** — What fired? When? How many times? (PagerDuty/OpsGenie)
2. **Metrics** — What changed at the same time? (Prometheus/Datadog/Grafana)
3. **Logs** — What errors appeared? Any new log patterns? (ELK/Loki/Splunk)
4. **Traces** — Which services are affected? Where is latency introduced? (Jaeger/Zipkin/X-Ray)
5. **Deployments** — Did a deploy, config change, or infra change coincide? (GitHub Actions/ArgoCD/Terraform)
6. **External** — Any third-party status page issues? (Cloudflare/AWS/GCP status)

### Incident Record Template (create immediately)

```markdown
# INC-<id> — <short title>
- **Severity**: SEV1/SEV2/SEV3/SEV4
- **Status**: Investigating / Identified / Mitigating / Monitoring / Resolved
- **Started**: <ISO-8601 timestamp>
- **Detected by**: <alert source or human reporter>
- **Affected services**: <list>
- **Customer impact**: <quantify: % users, regions, features>
- **Incident commander**: <name>
- **Slack channel**: #inc-<id>
- **Bridge line**: <zoom/meet link if war room>
```

### Initial Triage Questions

Ask these in order to build context fast:

1. What is the exact error rate / latency / availability change?
2. When did it start? (look at `deployment_timestamp - 5 min` first)
3. Is it global or regional?
4. Which upstream dependency is failing? (database, cache, queue, third-party API)
5. Is there a recent deploy, feature flag change, or config rollout?

## Step 2: Mitigation & Runbook Execution

### First Response Actions (in priority order)

1. **If customer impact is confirmed → mitigate first, root-cause later**
2. **If a recent deploy is suspect → consider rollback immediately**
3. **If a dependency is failing → circuit-break, degrade gracefully, or fail over**
4. **If data corruption is possible → stop the writes, preserve evidence**

### Runbook Loading

The skill references `references/incident_playbooks.md` for known incident types. When the alert type matches a playbook, load it and execute step-by-step. Common playbooks included:

- Database outage / connection pool exhaustion
- API failure / 5xx spike
- Memory leak / OOMKill
- DDoS / traffic anomaly
- CDN / cache failure
- Message queue backlog
- Third-party dependency failure

### Mitigation Tactics

| Situation | Common Mitigations |
|-----------|-------------------|
| Bad deploy | Rollback to last known good version |
| Config issue | Revert config; restart with last good config |
| DB overload | Enable read replicas; kill slow queries; rate-limit |
| Cache failure | Warm cache; bypass cache temporarily; fallback to origin |
| Traffic spike | Scale horizontally; enable rate-limiting; CDN rule |
| Dependency down | Enable circuit breaker; serve stale data; queue for retry |
| Memory leak | Restart pods/instances; move traffic to new pool; profile |

## Step 3: Communication

### Communication Cadence by Severity

| Severity | Internal Update | External Update | Stakeholder |
|----------|-----------------|-----------------|-------------|
| SEV1 | Every 15 min | Every 30 min | Exec + CS + Sales |
| SEV2 | Every 30 min | Every 60 min | Team lead + CS |
| SEV3 | Every 2 hours | Optional / per request | Team only |
| SEV4 | End-of-day summary | None | Reporter only |

### Status Page Update Template

```markdown
**Investigating** — We are investigating reports of <symptom> affecting <service>.
Some users may experience <impact>. We will provide an update in <X> minutes.

**Identified** — We have identified the cause as <root cause>. We are actively
mitigating and expect resolution within <ETA>.

**Monitoring** — A fix has been deployed and we are monitoring recovery.
All systems are showing healthy metrics.

**Resolved** — The incident is resolved. <Short summary>. We will publish a
post-mortem within <48/72 hours>.
```

### Slack/Teams Incident Channel Protocol

- Create `#inc-<id>` (or equivalent) for every SEV1/SEV2
- Pin the incident record, bridge line, and current status
- Use threads for deep-dive troubleshooting to reduce channel noise
- Only incident commander posts status updates to channel topic
- `@channel` only for severity changes, new findings, or all-clear

## Step 4: Log & Metric Correlation

Build a timeline of evidence. Link each observation to a source.

### Observability Query Patterns

**Error rate spike:**
```
sum(rate(http_requests_total{status=~"5.."}[5m])) by (service, route)
/ sum(rate(http_requests_total[5m])) by (service, route)
```

**Latency spike:**
```
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, service))
```

**Log error correlation:**
```
{service="<service>"} |= "error" | json | line_format "{{.ts}} {{.level}} {{.msg}}"
```

**Trace correlation:**
```
Find spans where: duration > p99 AND service = <affected> AND error = true
Look for: root span changes, downstream fan-out failures, DB lock waits
```

### Timeline Construction

Maintain a running timeline in the incident record:

```markdown
## Timeline (all times UTC)
- `14:03` — Alert `HighErrorRate` fired for `api-prod`
- `14:04` — On-call acknowledged
- `14:07` — Deploy `v2.4.1` identified as correlating event
- `14:09` — Rollback initiated to `v2.3.9`
- `14:15` — Error rate dropped below threshold
- `14:20` — All metrics green; moved to Monitoring
- `14:45` — Incident declared Resolved
```

## Step 5: Escalation Management

### Escalation Triggers

| Condition | Action |
|-----------|--------|
| SEV1 not acknowledged in 10 min | Page secondary on-call |
| No mitigation progress in 30 min | Escalate to team lead + engineering manager |
| Cross-team dependency identified | Page owning team + join to war room |
| Customer-impacting data loss | Engage security + legal immediately |
| Public security incident | Engage comms + exec immediately |

### Escalation Message Template

```
[ESCALATION] INC-<id> — <severity>
Current status: <status>
Blocked on: <reason>
Customer impact: <impact>
Bridge: <link>
Next action needed from you: <specific ask>
```

## Step 6: Resolution & Verification

Before declaring "Resolved":

1. **Error rate** below baseline for >10 minutes
2. **Latency** below SLO for >10 minutes
3. **Key business metrics** recovering (sign-ups, checkouts, API success rate)
4. **No new** related alerts
5. **Customer-facing probes** passing
6. **Status page** updated to Resolved

After resolution, keep monitoring for **at least 30 minutes** (SEV1) or **15 minutes** (SEV2) before closing the incident.

## Step 7: Post-Mortem Generation

Generate a blameless post-mortem within **48 hours** for SEV1 and **72 hours** for SEV2.

The skill loads `references/postmortem_template.md` to produce a standardized document.

### Blameless Principles

- Focus on **what** failed and **why**, never **who**
- Assume good intent; people do not come to work to cause outages
- Look for systemic fixes: better guardrails, automation, or observability
- Action items must be **specific, assignable, and deadline-driven**

### Post-Mortem Structure

1. **Executive Summary** — One-paragraph TL;DR of impact and resolution
2. **Timeline** — Precise, minute-level timeline of detection through resolution
3. **Impact Assessment** — Quantified: users affected, requests failed, revenue at risk, data affected
4. **Root Cause Analysis** — Use 5 Whys to trace to contributing factors
5. **Contributing Factors** — Code, config, process, observability, communication gaps
6. **Lessons Learned** — What went well, what went poorly, surprises
7. **Action Items** — Ticketed, owner-assigned, deadline-bound
8. **Appendix** — Key metrics graphs, logs excerpts, linked alerts

### Action Item Rules

- Every action item needs an owner and a due date
- If it cannot be completed within 30 days, it needs a milestone plan
- Track in the same ticket system as regular work (Jira/GitHub Issues/etc.)
- Review open action items in weekly incident review meetings

## Incident Metrics

Track and improve these metrics over time:

| Metric | Definition | Target |
|--------|-----------|--------|
| **MTTD** | Mean Time To Detect (alert fired → acknowledged) | < 5 min |
| **MTTR** | Mean Time To Resolve (alert fired → status Resolved) | SEV1 < 1 hr, SEV2 < 4 hr |
| **MTTF** | Mean Time To Failure (resolution → next related alert) | > 7 days |
| **Ack Time** | Alert fired → on-call acknowledges | < 5 min |
| **Escalation Rate** | % incidents escalated beyond first on-call | < 20% |
| **Post-Mortem SLA** | % post-mortems completed within 48/72 hr | 100% |
| **Action Item Closure** | % action items closed by due date | > 90% |

## Running the Triage Script

The skill includes `scripts/triage_incident.py` to correlate alerts and generate an incident report skeleton. Run it when:

- Multiple alerts fired in a short window and correlation is unclear
- You need a structured incident record quickly
- You want to auto-pull deployment times and suggest suspects

```bash
python scripts/triage_incident.py \
  --alerts "HighErrorRate,LatencySpike" \
  --service api-prod \
  --since "2024-05-06T14:00:00Z" \
  --output incident_report.md
```

## Quick Reference: Incident Commands

| I want to... | Use this skill section |
|--------------|------------------------|
| Classify severity | Severity Classification + Decision Tree |
| Correlate alerts and logs | Step 1: Triage + triage_incident.py |
| Find the runbook for a DB outage | references/incident_playbooks.md |
| Rollback a bad deploy | Step 2: Mitigation Tactics |
| Write a status page update | Step 3: Communication |
| Decide when to escalate | Step 5: Escalation Management |
| Write a blameless post-mortem | Step 7: Post-Mortem + postmortem_template.md |
| Track MTTD / MTTR | Incident Metrics |

## Resources

### scripts/
- `triage_incident.py` — Correlates alerts, builds incident report skeleton, suggests suspects

### references/
- `incident_playbooks.md` — Common incident types with step-by-step remediation playbooks
- `postmortem_template.md` — Blameless post-mortem template with 5-whys and action items

### assets/
- Not used by this skill (no external assets required)
