# Blameless Post-Mortem Template

Use this template for every SEV1 and SEV2 incident. Complete within 48 hours for SEV1, 72 hours for SEV2. Remove bracketed guidance before publishing.

---

## Post-Mortem: <INC-ID> — <Short descriptive title>

| Field | Value |
|-------|-------|
| **Incident ID** | INC-YYYY-NNNN |
| **Severity** | SEV1 / SEV2 / SEV3 |
| **Date** | YYYY-MM-DD |
| **Duration** | HH:MM (start to resolution) |
| **Detected by** | <alert name / human / customer> |
| **Incident Commander** | <Name> |
| **Status** | Draft / Review / Published |
| **Review Date** | <Date of team review meeting> |

---

## 1. Executive Summary

[One to three paragraphs. Anyone should understand the incident from this section alone.]

- **What happened?** In plain language, what service failed and what symptoms users saw.
- **What was the impact?** Quantified: approximate users affected, regions, revenue at risk, data lost or at risk.
- **How was it resolved?** The primary mitigation (rollback, failover, config fix, etc.).
- **What is the one-line takeaway?** The most important contributing factor and the fix being implemented.

> **Example:** On 2024-05-06 at 14:03 UTC, the `api-prod` service began returning 5xx errors due to a connection pool exhaustion in the primary PostgreSQL database. Approximately 40% of API requests failed for 42 minutes until the on-call engineer performed a failover to a read replica and restarted the application connection pools. No data was lost. The root cause was a recently deployed N+1 query pattern introduced in release v2.4.1 combined with a lack of connection pool growth alerting.

---

## 2. Timeline

[Minute-level precision from detection to resolution. All times in UTC. Include every status change, every command run, every communication sent. This is the most important section for learning.]

| Time (UTC) | Event | Actor | Evidence Link |
|------------|-------|-------|---------------|
| `14:03:00` | Alert `HighErrorRate` fired for `api-prod` | PagerDuty | [Alert link] |
| `14:03:45` | On-call paged | PagerDuty | [Page log] |
| `14:05:00` | On-call acknowledged alert | <Engineer> | [Ack log] |
| `14:06:00` | `api-prod` error rate confirmed at 42% | <Engineer> | [Grafana link] |
| `14:07:00` | Deploy `v2.4.1` at `13:58` identified as correlating event | <Engineer> | [Deploy log] |
| `14:09:00` | Attempted rollback to `v2.3.9` | <Engineer> | [CI/CD log] |
| `14:12:00` | Rollback completed; error rate dropped to 15% but not baseline | <Engineer> | [Metric link] |
| `14:15:00` | Identified DB connection pool exhaustion as co-factor | <Engineer> | [DB dashboard] |
| `14:18:00` | Failover to read replica initiated | <Engineer> | [Runbook log] |
| `14:22:00` | Application connection pools restarted | <Engineer> | [Deploy log] |
| `14:30:00` | Error rate returned to < 0.1% | Metrics | [Grafana link] |
| `14:35:00` | Status page updated to "Monitoring" | <Engineer> | [Status page log] |
| `14:45:00` | All metrics green for 15 min; declared Resolved | <Engineer> | [Incident record] |
| `15:00:00` | Status page updated to "Resolved" | <Engineer> | [Status page log] |

---

## 3. Impact Assessment

[Quantify everything possible. If exact numbers are unavailable, provide a reasoned estimate with confidence interval.]

### Customer Impact
- **Users affected:** ~X% of active users (approx N users)
- **Geographic scope:** <regions or "global">
- **Features affected:** <list>
- **Requests failed:** N requests (X% of total traffic during window)
- **Support tickets raised:** N
- **SLA breach:** Yes / No — <which SLOs were breached>

### Business Impact
- **Revenue at risk:** $N (if calculable)
- **Revenue lost:** $N (if calculable)
- **Data loss:** None / <describe> — <how many records, if any>
- **Data integrity:** No issues / <describe>
- **Brand / trust impact:** <social media mentions, press, major customer complaints>

### Internal Impact
- **Engineering hours spent on response:** N engineer-hours
- **Other teams disrupted:** <teams and why>
- **Planned work deferred:** <sprints, releases>

---

## 4. Root Cause Analysis (5 Whys)

[Use the 5 Whys technique to trace from the symptom to the deepest contributing factor. Do not stop at a single cause; there are always multiple contributing factors.]

**The symptom:** <What users saw>

**Why did the symptom occur?**
> <Answer>

**Why did <that> happen?**
> <Answer>

**Why did <that> happen?**
> <Answer>

**Why did <that> happen?**
> <Answer>

**Why did <that> happen?**
> <Answer>

### Contributing Factors

[List every factor that contributed. Each is necessary but not sufficient alone.]

1. **Code / Config:** <What code or config change introduced the failure mode>
2. **Testing:** <Why did tests not catch this?>
3. **Observability:** <Why did we not see this earlier or with more precision?>
4. **Process:** <What process gap allowed this to reach production?>
5. **Architecture:** <What systemic design issue made this possible?>
6. **Communication:** <Were there communication gaps during response?>

> **Example contributing factors:**
> 1. A new ORM query in v2.4.1 loaded related entities in a loop (N+1), multiplying DB connections by 100x under load.
> 2. Load tests did not include the user-journey that triggered the N+1 path.
> 3. Connection pool utilization was not alerted until 95%, giving no early warning.
> 4. Code review focused on business logic, not query plan impact; no DB reviewer required.
> 5. The service shares a single DB pool for reads and writes, so read pressure blocked writes.
> 6. The on-call engineer did not have direct access to the DB console and lost 5 minutes waiting for credentials.

---

## 5. What Went Well

[Highlight successes. This reinforces good behavior and practices.]

1. <Example: Rollback tooling worked flawlessly and completed in 3 minutes.>
2. <Example: On-call engineer followed the database playbook precisely.>
3. <Example: Customer support proactively informed enterprise customers before they noticed.>
4. <Example: The failover to read replica had been tested last month, so execution was confident.>

---

## 6. What Went Poorly

[Be honest and specific. This is not about blame; it is about identifying gaps to close.]

1. <Example: The N+1 query was not caught in code review because reviewers were not trained to spot ORM anti-patterns.>
2. <Example: Load tests do not cover the "bulk export" user journey that triggered the issue.>
3. <Example: On-call did not have DB console access; credentials had to be escalated.>
4. <Example: The error rate alert threshold was too high (10%), so we were already severely impacted before paging.>

---

## 7. Lessons Learned

[Surprises and insights. What did we learn that was not obvious before?]

1. <Example: The ORM's default eager-loading behavior is dangerous for large datasets.>
2. <Example: Read replica failover is faster than we assumed; we can afford to fail over earlier.>
3. <Example: Connection pool exhaustion manifests as 5xx in the app, making triage harder than if we had a direct DB alert.>

---

## 8. Action Items

[Every action item must be specific, assigned to an owner, and have a due date. Vague action items are worthless. If an item cannot be done in 30 days, it needs a milestone plan.]

| # | Action Item | Owner | Due Date | Priority | Ticket Link |
|---|-------------|-------|----------|----------|-------------|
| 1 | Add query-plan review to backend code review checklist | <Name> | YYYY-MM-DD | P0 | [TICKET-1] |
| 2 | Load-test the bulk-export user journey in staging | <Name> | YYYY-MM-DD | P0 | [TICKET-2] |
| 3 | Add connection pool utilization alert at 70% with 5-min window | <Name> | YYYY-MM-DD | P1 | [TICKET-3] |
| 4 | Separate read and write connection pools in `api-prod` | <Name> | YYYY-MM-DD | P1 | [TICKET-4] |
| 5 | Grant on-call DB read-only console access via IAM | <Name> | YYYY-MM-DD | P1 | [TICKET-5] |
| 6 | Reduce `HighErrorRate` alert threshold from 10% to 2% | <Name> | YYYY-MM-DD | P0 | [TICKET-6] |
| 7 | Document N+1 query patterns and ORM safe-loading practices | <Name> | YYYY-MM-DD | P2 | [TICKET-7] |

### Action Item Rules
- **P0:** Must complete within 7 days (critical safety / reliability fix)
- **P1:** Must complete within 30 days (significant risk reduction)
- **P2:** Should complete within 90 days (process improvement, hygiene)
- If an owner is unavailable, reassign immediately — do not leave unassigned.
- Review open action items in the weekly incident review meeting.

---

## 9. Appendix

### Key Metrics Graphs
[Insert links or embed Grafana / Datadog screenshots for:]
- Error rate over incident window
- Latency p99 over incident window
- Relevant resource metrics (CPU, memory, DB connections)
- Traffic volume / QPS

### Relevant Log Excerpts
```
[Insert 5–10 lines of the most relevant log entries with timestamps]
```

### Alert Links
- [Alert: HighErrorRate](<link>)
- [Alert: LatencySpike](<link>)

### Deploy / Change Log
- [Deploy v2.4.1](<CI/CD link>)
- [Config change](<link>)

### Runbook Followed
- [Playbook: Database Outage](<link>)

---

## Blameless Reminder

> **This post-mortem is blameless.** The purpose is to understand the system and improve it. Every person involved acted with good intent and did their best with the information and tools available. If we find process or tooling gaps, we fix the system so the next person cannot make the same mistake. We do not assign blame to individuals.

---

## Review Sign-Off

| Role | Name | Sign-Off Date | Notes |
|------|------|---------------|-------|
| Incident Commander | | | |
| Engineering Manager | | | |
| Product Manager (if customer-facing) | | | |
| SRE / Platform Lead | | | |
| Security (if applicable) | | | |
