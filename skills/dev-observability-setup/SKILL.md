---
name: dev-observability-setup
description: Developer-facing observability stack setup for metrics, logs, traces, and alerts. Configures Prometheus, Grafana, OpenTelemetry, Jaeger, Loki, and PagerDuty. Use when setting up monitoring, adding distributed tracing, configuring SLO alerts, or creating team dashboards. Includes RED method, correlation IDs, and cost optimization.
---

# Dev Observability Setup

## Overview

This skill guides developers through setting up complete observability stacks for applications: metrics (Prometheus/Grafana), logs (Loki/ELK), traces (OpenTelemetry/Jaeger), and alerts (Alertmanager/PagerDuty). It emphasizes the RED method for services, correlation across signals, and cost-aware retention/sampling.

Use this skill when:
- Bootstrapping monitoring for a new service or application
- Migrating from legacy monitoring to modern cloud-native observability
- Adding distributed tracing to microservices or serverless functions
- Configuring alerts for SLIs/SLOs with burn-rate-based paging
- Creating team dashboards for incident response and capacity planning
- Tuning cardinality, retention, or sampling to control observability costs

## Workflow Decision Tree

```
1. What is the primary goal?
   ├── "Monitor a new service"          → Go to 2. Metrics Setup (RED method)
   ├── "Add tracing to microservices"   → Go to 3. Tracing Setup (OpenTelemetry)
   ├── "Centralize logs"                → Go to 4. Logging Setup (structured + aggregation)
   ├── "Define SLOs and alerts"         → Go to 5. SLI/SLO & Alerting Setup
   └── "Create dashboards"              → Go to 6. Dashboard Design

2. Is the service containerized?
   ├── Yes (Kubernetes/Docker) → Use ServiceMonitor / PodMonitor + auto-discovery
   └── No (VM / bare metal)    → Use static scrape configs or node_exporter

3. Are there existing instrumentation libraries?
   ├── Yes (micrometer, statsd, custom) → Bridge to OpenTelemetry or Prometheus exposition
   └── No → Instrument with OTel SDK (auto-instrumentation where available)

4. Do logs need to correlate with traces?
   ├── Yes → Inject trace_id / span_id into structured JSON logs
   └── No → Standard structured logging without trace correlation
```

## 1. Metrics Setup (RED Method)

### 1.1 Prometheus Exposition

Every HTTP/gRPC service should expose a `/metrics` endpoint (Prometheus exposition format) with at minimum:

- **Rate**: `http_requests_total` (counter, labeled by method, path, status)
- **Errors**: `http_requests_total{status=~"5..|4.."}` subset of above
- **Duration**: `http_request_duration_seconds` (histogram or summary, same labels)

Additional system metrics via `node_exporter` (VMs) or `cAdvisor` + `kubelet` (Kubernetes).

### 1.2 Service Discovery

| Environment | Discovery Mechanism | Resource |
|-------------|---------------------|----------|
| Kubernetes  | ServiceMonitor / PodMonitor | `references/tool_configs.md` § Prometheus Operator |
| Consul      | `consul_sd_configs` | `references/tool_configs.md` § Prometheus Static |
| AWS ECS     | `ec2_sd_configs` / `file_sd_configs` | `references/tool_configs.md` § Prometheus AWS |
| Nomad       | `nomad_sd_configs` | `references/tool_configs.md` § Prometheus Nomad |
| Static VMs  | `static_configs` | `references/tool_configs.md` § Prometheus Static |

### 1.3 Recording Rules

Pre-aggregate high-cardinality queries for dashboards:

```yaml
# rate_http_requests_5m: per-service RPS
- record: rate_http_requests_5m
  expr: sum(rate(http_requests_total[5m])) by (service, method, path)

# error_rate_5m: per-service error ratio
- record: error_rate_5m
  expr: |
    sum(rate(http_requests_total{status=~"5.."}[5m])) by (service)
    /
    sum(rate(http_requests_total[5m])) by (service)

# latency_p99_5m: per-service P99 latency
- record: latency_p99_5m
  expr: histogram_quantile(0.99,
      sum(rate(http_request_duration_seconds_bucket[5m])) by (service, le))
```

### 1.4 Cardinality Guardrails

- Limit label cardinality in application code (avoid unbounded user IDs, session IDs, or timestamps as label values)
- Use `metric_relabel_configs` in Prometheus to drop high-cardinality labels at scrape time
- Target: keep metric count per job under 10,000; label value cardinality under 1,000 per label

## 2. Tracing Setup (OpenTelemetry)

### 2.1 Instrumentation Strategy

1. **Auto-instrumentation** (zero code changes)
   - Java: `-javaagent:opentelemetry-javaagent.jar -Dotel.service.name=my-service`
   - Python: `opentelemetry-instrument python main.py`
   - Node.js: `@opentelemetry/auto-instrumentations-node`
   - .NET: `OpenTelemetry.AutoInstrumentation`

2. **Manual SDK instrumentation** (fine-grained control)
   - Initialize `TracerProvider` with OTLP exporter
   - Add custom spans for business-critical operations
   - Attach attributes (span tags) for filtering in Jaeger/Tempo

### 2.2 Context Propagation

Use **W3C Trace Context** (`traceparent` header) as the default propagation format. Ensure:
- Incoming HTTP/gRPC requests extract `traceparent` and `tracestate`
- Outgoing HTTP/gRPC/client requests inject the current span context
- Async workers (queues, background jobs) propagate context via message metadata

### 2.3 Trace-to-Log Correlation

Inject trace identifiers into every log entry:

```json
{
  "timestamp": "2025-01-15T09:23:47Z",
  "level": "INFO",
  "message": "Order processed",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "service": "payment-service",
  "order_id": "ORD-12345"
}
```

Configure log aggregation to index `trace_id` for fast lookup from a trace view.

### 2.4 Sampling Strategy

| Stage | Strategy | Rate |
|-------|----------|------|
| Development | AlwaysOn | 100% |
| Staging | AlwaysOn or Probabilistic | 100% or 10% |
| Production low-traffic | AlwaysOn | 100% |
| Production high-traffic | ParentBased + Tail-based (via OTel Collector) | 1-5% |
| Critical paths (payment, auth) | AlwaysOn for specific spans | 100% |

Implement in OTel Collector with `probabilistic_sampler` or `tail_sampling` processor.

## 3. Logging Setup

### 3.1 Structured Logging (JSON)

All application logs must be structured JSON with standard fields:
- `timestamp` (RFC3339)
- `level` (DEBUG/INFO/WARN/ERROR/FATAL)
- `service` (service name)
- `message` (human-readable string)
- `trace_id`, `span_id` (when tracing enabled)
- `correlation_id` (request-scoped, for log correlation without traces)

### 3.2 Log Aggregation Architecture

| Stack | Components | Best For |
|-------|-----------|----------|
| PLG (Promtail + Loki + Grafana) | Promtail agent → Loki → Grafana | Kubernetes-native, cost-efficient, Prometheus-like querying |
| ELK | Filebeat/Fluentd → Logstash → Elasticsearch → Kibana | Full-text search, complex aggregations, legacy ecosystems |
| OpenTelemetry + OTLP | OTel Collector → backend (e.g., Loki, Elasticsearch, cloud vendor) | Unified pipeline for metrics, logs, and traces |

### 3.3 LogQL / Loki Stream Labels

Choose stream labels carefully (they create index shards). Good labels: `service`, `environment`, `level`. Bad labels: `user_id`, `request_id`, `timestamp`.

Example query:
```logql
{service="payment-service", environment="prod"}
  |= "error"
  | json
  | trace_id="4bf92f3577b34da6a3ce929d0e0e4736"
```

## 4. SLI/SLO & Alerting Setup

### 4.1 Defining SLIs

An SLI is a quantitative measure of service reliability. Common SLIs:

| Type | SLI | PromQL Example |
|------|-----|----------------|
| Availability | Ratio of successful requests | `1 - (error_rate_5m)` |
| Latency | Percentile of request duration | `histogram_quantile(0.99, ...)` |
| Throughput | Requests per second | `rate(http_requests_total[5m])` |
| Error Rate | Failed request ratio | `rate(http_requests_total{status=~"5.."}[5m])` |

### 4.2 Burn-Rate Alerting

Use multi-window, multi-burn-rate alerts to page only when an error budget is being consumed rapidly:

| Burn Rate | Lookback | Required Budget Consumption | Alert Severity |
|-----------|----------|----------------------------|----------------|
| 14.4x | 1 hour | 2% in 1 hour | page (critical) |
| 6x | 6 hours | 5% in 6 hours | page (critical) |
| 2x | 3 days | 10% in 3 days | ticket (warning) |
| 1x | 1 week | 20% in 1 week | ticket (warning) |

See `references/sli_slo_guide.md` for complete PromQL alert rule templates and recording rules.

### 4.3 Alert Routing (Alertmanager)

Route alerts by severity and service ownership:

```yaml
route:
  receiver: default
  group_by: ['alertname', 'service', 'severity']
  routes:
    - match:
        severity: critical
      receiver: pagerduty-critical
      continue: true
    - match:
        severity: warning
      receiver: slack-alerts
    - match_re:
        service: (payments|billing|auth)
      receiver: team-security-oncall
```

Receivers:
- `pagerduty-critical`: PagerDuty integration key, auto-escalate if unacknowledged in 5 min
- `slack-alerts`: `#alerts` channel with threaded updates for resolves
- `discord-alerts`: Webhook to `#incidents` for community projects

### 4.4 Alert Quality Checks

- Every paging alert must have a runbook link in annotations
- Every alert must distinguish between `symptom-based` (user-impacting) and `cause-based` (infra-impacting); prefer symptom-based paging
- Set `for:` duration to reduce flapping (typically 2-5 minutes for critical)
- Add `severity` label: `critical` (page), `warning` (ticket/Slack), `info` (dashboard only)

## 5. Dashboard Design

### 5.1 RED Dashboard Template (Per Service)

Row 1: Summary
- Request rate (RPS) over time
- Error rate (%) over time
- P50 / P95 / P99 latency over time

Row 2: Breakdown
- Rate by HTTP method / gRPC method
- Error rate by status code
- Latency heatmap (histogram buckets over time)

Row 3: Infrastructure
- CPU / Memory / Goroutines / JVM heap (container/VM metrics)
- Pod restarts / OOMKills (Kubernetes)

Row 4: Tracing & Logs
- Link to Jaeger search for selected time range
- Top 5 error log samples (via Loki/LogQL)

### 5.2 SLO Dashboard Template

- Current SLI value vs SLO line (e.g., 99.9% availability)
- Error budget remaining (%) for rolling 30-day window
- Burn-rate graph: current consumption rate vs 1x/2x/6x/14.4x lines
- Alert status: which burn-rate alerts are firing

## 6. Health Checks & Kubernetes Probes

### 6.1 Probe Types

| Probe | Purpose | Endpoint Pattern |
|-------|---------|-----------------|
| Liveness | Is the process running? Should K8s restart it? | `GET /health/live` — lightweight, always 200 if main loop active |
| Readiness | Is the service ready to accept traffic? | `GET /health/ready` — 200 if dependencies (DB, cache) healthy |
| Startup | Slow-starting apps: block liveness/readiness until ready | `GET /health/startup` — 200 when initialization complete |

### 6.2 Probe Implementation Rules

- Liveness must not depend on external services (to avoid cascading restarts)
- Readiness should fail when dependency pool is exhausted or degraded
- All probes should emit metrics: `healthcheck_status{probe="liveness"}` for debugging
- Keep liveness probe timeout < 1s to avoid false-positive kills under load

## 7. Cost Optimization

### 7.1 Retention Policies

| Signal | Default Retention | Cost-Optimized Strategy |
|--------|-------------------|------------------------|
| Metrics | 15 days Prometheus local + remote_write | 15 days local; 1 year compressed in Thanos/Mimir/Cortex |
| Traces | 7 days Jaeger/Tempo | Head-based sampling 1-5%; 3 days hot, 30 days cold storage |
| Logs | 30 days Loki / Elasticsearch | 7 days hot (index), 30 days warm, 90 days cold (object storage) |
| Alerts history | 1 year Alertmanager silences + PagerDuty | Keep in PagerDuty analytics; minimal local state |

### 7.2 Cardinality Management

- Drop debug metrics in production via metric relabeling
- Use `honor_labels: false` to prevent label spoofing
- Shard Prometheus by environment or team when total metrics exceed 5M series
- Use recording rules to pre-aggregate before querying dashboards

### 7.3 Sampling Strategies

- **Head-based sampling**: Fast, consistent (same trace sampled entirely), but statistically biased
- **Tail-based sampling**: Captures rare events (errors, high latency), higher collector resource cost
- **Intelligent sampling**: Combine both — head-based 1% default + tail-based capture of all errors/slow traces

## 8. Integration Patterns

### 8.1 Correlation: Metrics → Traces → Logs

1. **Metric alert fires** (e.g., `error_rate_5m > 0.01`)
2. Dashboard link includes `trace_id` search to Jaeger/Tempo
3. From trace view, click `trace_id` to Loki/Elasticsearch log query
4. From log view, pivot back to metrics for the same `service` + `time range`

### 8.2 CI/CD Integration

- Run `promtool check rules` and `promtool check config` in CI before deploying Prometheus changes
- Validate Grafana dashboards with `grafana-dashboard-linter` or `grafonnet` tests
- Store all observability configs (rules, dashboards, alerts) in Git; deploy via GitOps (Flux/ArgoCD)

### 8.3 Progressive Rollout Observability

For canary/blue-green deployments, add `version` label to metrics and trace attributes. Compare:
- Error rate: `stable` vs `canary`
- Latency: `stable` vs `canary`
- Log error volume: `stable` vs `canary`

Automate rollback triggers based on canary SLI regression.

## Resources

### scripts/
- `setup_observability.py` — Generates a complete observability stack manifest (Prometheus rules, Grafana dashboards JSON, OTel Collector config, Alertmanager routing) from a service inventory YAML.

### references/
- `tool_configs.md` — Copy-paste configuration templates for Prometheus, Grafana, OpenTelemetry Collector, Jaeger, Loki, Promtail, Alertmanager, and PagerDuty/Slack receivers.
- `sli_slo_guide.md` — Deep dive on SLI selection, SLO target negotiation, error budget policies, burn-rate alert math, and dashboard design patterns.
