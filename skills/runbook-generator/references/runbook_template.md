# Standard Runbook Template: `{skill_name}`

> **Skill ID:** `{skill_id}`  
> **Layer:** L0 — Enforcement  
> **Owner:** `{owner_team}`  
> **Generated:** `{generation_timestamp}`  
> **Version:** `{runbook_version}` (matches skill version `{skill_version}`)  
> **Review Cadence:** 90 days or after any skill release that changes health endpoints, config schema, or deployment topology.

---

## 1. Skill Overview

### 1.1 Purpose (One Sentence)
{one_sentence_purpose}

### 1.2 Criticality
- **Enforcement Scope:** {what_this_skill_enforces}
- **Blast Radius if Failed:** {blast_radius_description}
- **Singleton vs. Replicated:** {deployment_topology}
- **Fail Mode:** {fail_closed | fail_open | fail_fixed | fail_partial | fail_queue | fail_alert}
- **Compensating Control (if fail-open):** {compensating_control_or_n/a}

### 1.3 Architecture Snapshot
```
[Control Plane] --(config sync)--> [{skill_name}] --(enforcement decisions)--> [Protected Resources]
                                     ^
                                     |--(health, metrics, logs)--> [Observability Stack]
                                     |
                                     |--(hard deps)--> {hard_dependency_list}
                                     |--(soft deps)--> {soft_dependency_list}
```

---

## 2. Failure Modes

> Generated from skill metadata + health endpoint schema + historical incident data. Each failure mode follows: Symptom → Detection → Impact Assessment → Recovery → Verification.

### 2.1 {Failure Mode: CRASH | HANG | CORRUPTION | RESOURCE | CONFIG | DEPENDENCY} — {Unique Failure Name}

#### Symptom
- **Observed Behavior:** {what_the_user_or_system_sees}
- **Log Signature (exact grep / filter):** `{log_pattern}`
- **Metric Signature:** `{prometheus_query_or_cloudwatch_metric}`
- **Duration to Manifest:** {typical_time_from_trigger_to_observable}

#### Detection
| Source | Query / Check | Threshold | Polling Interval |
|--------|---------------|-----------|-----------------|
| Health Endpoint | `GET {health_endpoint}` | Expected: `{expected_response}`. Failure: `{failure_response}` | {interval} |
| Liveness Probe | `{probe_command}` | {success_criteria} | {interval} |
| Readiness Probe | `{probe_command}` | {success_criteria} | {interval} |
| Log Alert | `{log_alert_query}` | > {count} in {window} | real-time |
| Metric Alert | `{metric_alert_query}` | {threshold} for {duration} | {interval} |
| Synthetics / Canary | `{canary_test_description}` | {pass_criteria} | {frequency} |

**PagerDuty / OpsGenie Integration:**
- **Service Key:** `{pagerduty_service_key}`
- **Alert Name:** `{alert_name}`
- **Severity:** SEV-{0-4}
- **Escalation Policy:** `{escalation_policy_name}`
- **Auto-Escalation After:** {minutes} minutes if unacknowledged.

#### Impact Assessment
- **Immediate Impact:** {what_breaks_right_now}
- **Degradation Mode Entered:** {which_degradation_mode_from_taxonomy}
- **Scope of Impact:** {single_node | shard | zone | region | global}
- **Estimated Time to Full Outage (if unrecovered):** {time_estimate}
- **Data Loss Risk:** {none | bounded_seconds | unbounded}
- **Compliance / Regulatory Risk:** {yes/no + brief explanation}
- **Cascade Trigger Risk:** {which_L1-L8_layers_may_cascade}

#### Recovery

**Step-by-Step Procedure:**

1. **Acknowledge & Triage (0–2 min)**
   - Acknowledge alert in PagerDuty / OpsGenie.
   - Verify alert is not a false positive by running: `{validation_command_or_query}`
   - Check `{status_dashboard_url}` for correlated incidents.

2. **Immediate Mitigation (2–10 min)** — Goal: restore safe enforcement state
   - **Option A (preferred if stateless):** Restart / rolling-restart the skill:
     ```bash
     {restart_command}
     ```
   - **Option B (if stateful / quorum):** Fail over to healthy replica set:
     ```bash
     {failover_command}
     ```
   - **Option C (if corruption suspected):** Roll back to last known good version:
     ```bash
     {rollback_command}
     ```
   - **Option D (if dependency issue):** Verify dependency health; if dependency is down, invoke dependency runbook: `{dependency_runbook_link}`.

3. **Root Cause Isolation (parallel with mitigation)**
   - Collect diagnostics:
     ```bash
     {diagnostic_commands}
     ```
   - Capture logs for the incident window: `{log_collection_command}`
   - Capture heap / thread / goroutine dumps if applicable: `{dump_commands}`

4. **Corrective Action (once stable)**
   - Apply permanent fix: {brief_description_or_link_to_ticket}
   - If config-related, validate config before apply:
     ```bash
     {config_validation_command}
     ```

#### Verification
- **Health Check:** `GET {health_endpoint}` returns `{expected_response}` for ≥ {duration}.
- **Liveness / Readiness:** Kubernetes shows `{pod_status}` with 0 restarts for ≥ {duration}.
- **Metric Verification:** `{recovery_metric_query}` returns `{expected_value}`.
- **Functional Verification:** Execute canary test: `{canary_command}` — expect `{expected_canary_result}`.
- **Log Verification:** No recurrence of `{log_pattern}` for ≥ {duration}.
- **Downstream Check:** Verify that dependent skills (L1-L8) show green health: `{downstream_health_query}`.

#### Post-Incident
- **Incident Ticket Template:** Create `{incident_ticket_type}` with label `l0-failure/{skill_id}`.
- **Post-Mortem Required:** {yes/no} if SEV ≤ 2 or duration > {threshold}.
- **Runbook Update Required:** {yes/no} if the recovery procedure deviated from this runbook.
- **Metric / Alert Tuning Ticket:** Create if detection was delayed (> {threshold} between failure and page).
- **Escalation Contact:** `{escalation_contact_info}`

---

### 2.2 {Next Failure Mode} — {Unique Failure Name}
[Repeat Symptom → Detection → Impact Assessment → Recovery → Verification → Post-Incident]

---

### 2.N {Final Failure Mode} — {Unique Failure Name}
[Repeat Symptom → Detection → Impact Assessment → Recovery → Verification → Post-Incident]

---

## 3. Common Diagnostic Commands

### 3.1 Quick Status
```bash
# Overall skill health
curl -sf http://{skill_host}:{port}{health_endpoint} | jq .

# Kubernetes status (if containerized)
kubectl get pods -n {namespace} -l app={skill_label} -o wide
kubectl describe pod -n {namespace} {pod_name}

# Systemd status (if bare metal / VM)
systemctl status {service_name}
journalctl -u {service_name} --since "{time_window}" --no-pager
```

### 3.2 Log Extraction
```bash
# Real-time tail
kubectl logs -n {namespace} -l app={skill_label} --tail=500 -f

# Historical search (incident window)
kubectl logs -n {namespace} -l app={skill_label} --since={time_window} | grep -E "{log_pattern_1}|{log_pattern_2}"

# Structured query (if sent to centralized logging)
{log_platform_query_example}
```

### 3.3 Metrics & Dashboards
- **Primary Dashboard:** `{grafana_or_cloudwatch_dashboard_url}`
- **Key Prometheus Queries:**
  ```promql
  # Error rate
  rate({skill_metric_prefix}_errors_total[5m])

  # Latency
  histogram_quantile(0.99, rate({skill_metric_prefix}_request_duration_seconds_bucket[5m]))

  # Resource saturation
  container_memory_working_set_bytes{pod=~"{skill_label}-.*"} / container_spec_memory_limit_bytes{pod=~"{skill_label}-.*"}
  ```

### 3.4 Dependency Checks
```bash
# Check each hard dependency
curl -sf {dependency_1_health_url}
curl -sf {dependency_2_health_url}
# ...
```

---

## 4. Escalation & Communication

### 4.1 On-Call Rotation
- **Primary On-Call:** `{primary_oncall_rotation}`
- **Secondary On-Call:** `{secondary_oncall_rotation}`
- **Skill Owner Engineering Team:** `{engineering_team_contact}`
- **SRE Escalation:** `{sre_escalation_contact}`

### 4.2 Incident Communication Templates

**SEV-1 Page (auto-generated):**
```
[SEV-1] {skill_name} {failure_mode} detected in {environment}
- Detection time: {timestamp}
- Degradation mode: {degradation_mode}
- Impact scope: {scope}
- Runbook: {runbook_link}
- Dashboard: {dashboard_link}
```

**Status Update (every 30 min during SEV-1):**
```
[Update] {skill_name} incident
- Status: {investigating | mitigating | monitoring | resolved}
- Actions taken: {summary}
- ETA to resolution: {estimate or TBD}
- Next update: {timestamp}
```

**Resolution Notice:**
```
[Resolved] {skill_name} incident
- Duration: {duration}
- Root cause (preliminary): {summary}
- Post-mortem ticket: {ticket_link}
```

---

## 5. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | {date} | {author} | Initial runbook generated from skill metadata v{skill_version} |
| {ver} | {date} | {author} | {description} |
