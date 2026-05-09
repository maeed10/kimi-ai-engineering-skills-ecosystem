---
name: slo-enforcer
description: Service Level Objective definition and enforcement for all L0 enforcement-layer skills. Use when setting up production monitoring, capacity planning, investigating performance regressions, or defining SLA commitments. Covers latency, error rate, throughput, and availability with burn-rate alerting and load testing harness.
---

# slo-enforcer

## Overview

`slo-enforcer` defines, measures, and enforces Service Level Objectives (SLOs) for the entire L0 enforcement layer. It closes the gap where "policy validation latency is unbounded" by establishing concrete thresholds, measurement methodologies, alerting rules, and load testing procedures for every enforcement-layer skill.

This skill treats SLOs as first-class infrastructure: each L0 skill has defined latency distributions, error budgets, burn-rate alerts, and a repeatable load testing harness. It enables proactive capacity planning, rapid regression detection, and defensible SLA commitments to downstream users.

## When to Use This Skill

- **Setting up production monitoring and alerting** — Establish dashboards, metrics pipelines, and on-call rules for enforcement layer health.
- **Capacity planning** — Determine when to scale the policy-engine, phase-controller, or sandbox-executor based on throughput degradation curves.
- **Suspected performance regression** — Compare current p50/p95/p99 against baselines to identify which skill regressed and by how much.
- **Defining SLA commitments to users** — Translate internal SLOs into externally documented SLAs with error budgets.
- **Benchmarking enforcement layer performance** — Run synthetic load tests before releases to validate that latency and throughput meet SLO commitments.
- **Incident response and post-mortems** — Measure actual error budget consumed during an incident and adjust SLOs if the burn rate was unexpected.

## Core Capabilities

### 1. Per-Skill SLO Definitions

Every L0 enforcement-layer skill has four golden-signal SLOs:

| Signal | Definition | Measurement Source |
|--------|-----------|--------------------|
| **Latency** | p50 / p95 / p99 distributions per operation type | In-process histograms (Prometheus/OpenTelemetry) |
| **Error Rate** | Ratio of failed operations to total operations | HTTP 5xx, gRPC status != OK, sandbox exit code != 0 |
| **Throughput** | Operations per second (ops/s) per skill | Request rate counters |
| **Availability** | Uptime percentage over rolling 30-day window | Health-check probes + synthetic canaries |

### 2. Policy-Engine SLOs

- **p99 validation latency < 50 ms** — Measured from request receipt to response bytes written, excluding network round-trip.
- **Availability > 99.9%** — Rolling 30-day window; downtime budget = 43.2 minutes/month.
- **Max rule count before degradation** — 10,000 active rules with p95 latency still < 100 ms.
- **Error rate < 0.1%** — Any validation that throws or returns `ALLOW`/`DENY` incorrectly.

### 3. Sandbox-Executor SLOs

- **Container launch < 5 s** — From `create` API call to process `execve` inside the container.
- **Image pull < 30 s** — For images <= 500 MB, layer-cache warm. Fallback to 120 s for cold large images.
- **Sandbox teardown < 2 s** — From termination signal to complete resource release (cgroups, netns, mounts).

### 4. Phase-Controller SLOs

- **Transition proposal < 100 ms** — From request to proposed next-phase artifact.
- **Artifact validation < 200 ms** — Deep structural validation of the proposed artifact against the schema.
- **State machine consistency** — 100% of transitions must pass atomic compare-and-swap; no split-brain transitions allowed.

### 5. Burn-Rate Alerting

Alerts are based on **error budget consumption velocity**, not raw metric thresholds. This eliminates noisy paging and ensures on-call only fires when user experience is actually at risk.

| Burn Rate | Budget Window | Severity | Response |
|-----------|---------------|----------|----------|
| Fast burn | 2% budget in 1 hour | **P1 — Page** | Immediate human intervention |
| Slow burn | 5% budget in 6 hours | **P2 — Ticket** | Investigate within business hours |
| Exhaustion | 100% budget in 30 days | **P0 — War room** | Emergency mitigation / freeze deploys |

Details and notification channel mapping are in [`references/alerting_rules.md`](references/alerting_rules.md).

### 6. Load Testing Harness

A reusable Python script ([`scripts/load_test.py`](scripts/load_test.py)) generates synthetic validation requests against the enforcement layer. It supports:

- Configurable concurrency, request rate, and payload complexity.
- Latency histogram export (HDR / Prometheus text format).
- Rule-count sweep to find degradation knee-point.
- Phase-transition workload simulation.

Use it before every production push to certify that the enforcement layer still meets its latency SLOs at peak projected throughput.

## Workflow: Investigating a Suspected Latency Regression

1. **Confirm the signal** — Check the per-skill latency dashboard (p50/p95/p99) over the last 4 hours vs. the 7-day baseline.
2. **Identify the skill** — Use the SLO tables in [`references/slo_definitions.md`](references/slo_definitions.md) to see which threshold was breached.
3. **Correlate deploys** — Map the regression timestamp to the most recent deployment of that skill.
4. **Run load test baseline** — Execute `scripts/load_test.py --mode=baseline` against the previous stable version to capture clean numbers.
5. **Run load test candidate** — Execute `scripts/load_test.py --mode=candidate` against the current version.
6. **Compare degradation curves** — If p99 increased by > 20% at identical throughput, treat as confirmed regression.
7. **Decide action** — Rollback (if > 50% SLO breach), hotfix (if < 50% breach), or tune resource limits.
8. **Update error budget ledger** — Record budget consumed during the regression window for the 30-day review.

## Workflow: Setting Up Monitoring for a New L0 Skill

1. **Instrument the skill** — Emit OpenTelemetry traces + Prometheus histograms for every operation.
2. **Pick initial SLO thresholds** — Use the reference tables in [`references/slo_definitions.md`](references/slo_definitions.md) as starting points; adjust based on actual distribution after 7 days.
3. **Configure burn-rate alerts** — Copy the alert rule templates from [`references/alerting_rules.md`](references/alerting_rules.md) and set `skill_name` label.
4. **Add load test coverage** — Extend `scripts/load_test.py` with a new workload generator for the skill's RPC surface.
5. **Run 48-hour burn-in** — Load test + soak test to validate that SLOs are realistic and alert rules fire correctly.
6. **Document commitments** — Publish internal SLO dashboard; derive external SLA from SLO minus safety margin (usually SLO - 0.5%).

## File Reference

| File | Purpose |
|------|---------|
| `references/slo_definitions.md` | Per-skill SLO tables with thresholds, rationales, and measurement details |
| `references/alerting_rules.md` | Burn-rate alert definitions, severity mapping, and notification routing |
| `scripts/load_test.py` | Synthetic load testing harness for enforcement layer validation |

## Error Budget Policy

- **Budget period**: 30 days, rolling window.
- **Budget source**: (1 - SLO target) * total requests in window.
- **Burn-rate calculation**: `(errors in window / total requests in window) / (1 - SLO target)`.
- **Budget exhaustion action**: Freeze non-critical deploys to the affected skill until the budget recovers (either via reduced error rate or window rollover).
- **Exception process**: Emergency security patches may deploy even with exhausted budget, but require post-incident review within 24 hours.

## Dependencies

- Prometheus or compatible metrics store for histogram aggregation.
- OpenTelemetry SDK in each L0 skill for trace and metric emission.
- PagerDuty / Slack / ticketing system for alert routing.
- Python 3.10+ for the load testing harness.
