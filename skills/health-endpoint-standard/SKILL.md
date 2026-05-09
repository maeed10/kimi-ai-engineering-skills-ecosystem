---
name: health-endpoint-standard
description: Standardized health endpoint schema and implementation pattern for all L0 enforcement-layer skills. Use when implementing L0 skills, setting up monitoring, diagnosing incidents, or capacity planning. Defines consistent /health, /ready, /metrics endpoints with Prometheus-compatible metrics.
---

# health-endpoint-standard

Standardized health endpoint schema and implementation pattern for all L0 enforcement-layer skills. Enables monitoring systems to query operational status, queue depth, error rates, and rule counts with a single, predictable interface.

## When to Use

- **Implementing or updating any L0 skill**: Every new or modified L0 enforcement-layer skill must expose the standard health interface before promotion to production.
- **Setting up monitoring/alerting for the enforcement layer**: Use this skill to configure Prometheus rules, Grafana dashboards, and PagerDuty alerts that apply uniformly across all 15 L0 skills.
- **Diagnosing production incidents**: During an incident, query any L0 skill's `/health` and `/ready` endpoints to determine whether the skill is alive, capable of accepting work, or experiencing degradation.
- **Capacity planning for policy-engine or phase-controller**: Use `/metrics` queue depth and latency histograms to identify bottlenecks and justify horizontal scaling decisions.
- **Designing runbooks that depend on health state**: Build operational runbooks around the guaranteed schema so checks are portable across skills.

## Key Behaviors

1. **Standard health response schema**: All endpoints return a consistent envelope containing `status` (healthy / degraded / unhealthy), `last_successful_validation`, `queue_depth`, `error_rate_1m`, `rule_count`, `version`, and `uptime`. See [references/health_schema.md](references/health_schema.md) for the formal JSON Schema.
2. **HTTP/gRPC endpoint pattern per skill**: Each skill exposes three canonical paths:
   - `GET /health` — Liveness probe. Returns `200 OK` if the process is running and can respond. Returns `503 Service Unavailable` if the process is shutting down or deadlocked.
   - `GET /ready` — Readiness probe. Returns `200 OK` if the skill is initialized, connected to its dependencies (database, message bus, rule store), and able to accept new work. Returns `503` during startup, rule sync, or dependency outage.
   - `GET /metrics` — Prometheus-compatible metrics endpoint. Returns `text/plain` in Prometheus exposition format with custom metrics per skill type.
3. **Liveness vs readiness probes**: Kubernetes and systemd must use `/health` for liveness (restart the container) and `/ready` for readiness (remove from load balancer). Never use a single endpoint for both purposes.
4. **Prometheus-compatible `/metrics` endpoint**: Each skill type emits a baseline metric set plus optional skill-specific extensions. All histograms use seconds and explicit buckets. All counters are monotonic. See [references/metrics_catalog.md](references/metrics_catalog.md).
5. **Integration with K8s probes, systemd status, and monitoring stacks**:
   - **Kubernetes**: Configure `livenessProbe.httpGet.path: /health`, `readinessProbe.httpGet.path: /ready`, and `startupProbe.httpGet.path: /ready` with `initialDelaySeconds` derived from the skill's cold-start benchmark.
   - **systemd**: Use `ExecStartPost` to curl `/ready` before declaring the service `active`, or integrate with `sd_notify` by mapping `/ready` status to `READY=1`.
   - **Prometheus/Grafana**: Scrape `/metrics` every 15 s. Alert on `l0_health_status{status="unhealthy"} == 1`, `l0_queue_depth > threshold`, and `rate(l0_errors_total[1m]) > 0.05`.

## Endpoint Specification

### GET /health

Purpose: Liveness. Can the process respond to HTTP?

| Response | Meaning |
|----------|---------|
| `200 OK` | Process is alive. |
| `503 Service Unavailable` | Process is shutting down, deadlocked, or otherwise unable to serve any request. |

Response body follows the standard health envelope with `status` set to `healthy` or `unhealthy`. During graceful shutdown, return `unhealthy` and set `status_code` to `503`.

### GET /ready

Purpose: Readiness. Is the skill initialized and able to accept new validation/policy work?

| Response | Meaning |
|----------|---------|
| `200 OK` | Skill is fully initialized, rule set is loaded, upstream dependencies are reachable. |
| `503 Service Unavailable` | Skill is starting up, reloading rules, or has lost connectivity to a required dependency. |

Response body follows the standard health envelope with `status` set to `healthy` when ready and `degraded` or `unhealthy` when not.

### GET /metrics

Purpose: Observability. Prometheus scrape endpoint.

| Attribute | Value |
|-----------|-------|
| Content-Type | `text/plain; version=0.0.4; charset=utf-8` |
| Format | Prometheus exposition format |
| Status | `200 OK` (always; an unresponsive metrics endpoint is itself a signal) |

Metrics are documented in [references/metrics_catalog.md](references/metrics_catalog.md).

## Health Status Definitions

| Status | Criteria | Action |
|--------|----------|--------|
| `healthy` | Error rate < 1 %, queue depth < 80 % of max, all dependencies reachable, last successful validation < 30 s ago. | None. |
| `degraded` | Error rate 1–5 %, queue depth 80–95 % of max, one non-critical dependency flaky, or last successful validation 30–120 s ago. | Page on-call; investigate; consider scaling. |
| `unhealthy` | Error rate ≥ 5 %, queue depth ≥ 95 % of max, critical dependency down, or last successful validation > 120 s ago. | Alert critical; stop traffic if automated circuit breaker is enabled. |

## Implementation Checklist

When adding health endpoints to a new L0 skill, verify each item:

- [ ] `/health` returns `200` when process is alive, `503` during shutdown.
- [ ] `/ready` returns `503` until rule store is synced and dependencies pass a smoke test.
- [ ] `/metrics` emits `l0_health_status`, `l0_queue_depth`, `l0_errors_total`, `l0_rule_count`, `l0_request_duration_seconds`, and `l0_uptime_seconds`.
- [ ] All timestamps are RFC 3339 UTC.
- [ ] All durations are in seconds (float).
- [ ] Error rate is computed over a 1-minute rolling window.
- [ ] Queue depth is instantaneous (current value at scrape time).
- [ ] Version matches the skill's semantic version (e.g., `1.2.3`).
- [ ] Kubernetes manifests define separate liveness and readiness probes.
- [ ] Runbook references the standard schema; no skill-specific parsing required.

## Error Handling

- If the health check handler itself panics, the HTTP server must still return `503` with a minimal JSON body: `{"status":"unhealthy","error":"health_check_panic"}`.
- If metrics collection times out (> 2 s), return the metrics gathered so far with an `# ERROR` comment line per Prometheus exposition format.
- Never leak sensitive connection strings or credentials in `/health` or `/ready` response bodies.

## Version History

| Version | Change |
|---------|--------|
| 1.0.0 | Initial standard covering 15 L0 enforcement-layer skills. |
