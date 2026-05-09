---
name: dynamic-boundary-validator
description: >
  4-layer protocol that correlates runtime traces and logs with architecture maps to detect DDD boundary violations and map staleness. Use during VALIDATE phase, when processing production logs, or when architecture maps may have become outdated due to codebase evolution. Integrates with OpenTelemetry, Jaeger, and graphify.
---

# Dynamic Boundary Validator

Detects discrepancies between statically-defined architecture boundaries and runtime reality by correlating distributed traces, logs, and architecture maps. Produces `BOUNDARY_VIOLATIONS.md` with severity-ranked findings and triggers re-understanding when staleness exceeds threshold.

## Trigger Conditions

- `boundary-enforcer` architecture maps have not been updated in >7 days or >10 commits
- `log-analyzer` finishes processing production logs
- Microservice extraction, module merging, or large refactoring lands
- OpenTelemetry/Jaeger/Zipkin traces are available in the environment
- VALIDATE phase boundary compliance check is requested
- Cross-service call patterns change in frequency or direction

## Workflow: INGEST → CORRELATE → DETECT → ACT

---

## Phase 1: INGEST — Runtime Trace Ingestion

Reconstruct actual request flows from observability backends. Prefer OpenTelemetry; fall back to Jaeger or Zipkin.

### 1.1 Discover available trace backend

```yaml
discovery_order:
  - check: OTEL_EXPORTER_OTLP_ENDPOINT env var
    protocol: OTLP/gRPC or OTLP/HTTP
  - check: JAEGER_ENDPOINT or JAEGER_QUERY_URL
    protocol: Jaeger Query API v3
  - check: ZIPKIN_BASE_URL
    protocol: Zipkin API v2
  - fallback: read local trace JSON exports / span dumps
```

### 1.2 Query parameters

```yaml
lookback_window: "24h"          # extend to 7d for low-traffic services
min_call_count: 5               # ignore edges below this threshold
service_filter: []              # empty = all services; else restrict
include_tags:
  - http.url
  - db.system
  - messaging.system
  - rpc.service
```

### 1.3 Extract service dependency graph

Transform trace spans into a directed graph `G_runtime = (S, E)` where:
- `S` = set of services (from `service.name` resource attribute)
- `E` = weighted edges `(src, dst, count, latency_p99, tags)`

**Pseudocode:**
```python
def extract_runtime_graph(traces):
    for trace in traces:
        for span in trace.spans:
            src = span.resource.attributes["service.name"]
            dst = extract_destination(span)  # peer.service, http.host, db.system, etc.
            if dst:
                E[(src, dst)].count += 1
                E[(src, dst)].tags.update(span.attributes)
    return G_runtime
```

Load `references/trace_integration.md` for protocol-specific query examples and authentication patterns.

---

## Phase 2: CORRELATE — Map-to-Runtime Alignment

### 2.1 Load static architecture map

Read the current `boundary-enforcer` map (typically `.kimi/skills/boundary-enforcer/references/domain_map.json` or similar). Extract:

```yaml
static_map:
  bounded_contexts: []        # list of context names
  services_per_context: {}    # {context: [services]}
  allowed_crossings: []       # explicitly approved cross-boundary edges
  forbidden_crossings: []     # explicitly denied cross-boundary edges
```

### 2.2 Build context-level edge diff

Collapse runtime service graph to **bounded-context graph** using service-to-context mapping from static map.

```
G_context_runtime = collapse(G_runtime, service→context)
G_context_static  = allowed_crossings + forbidden_crossings
```

### 2.3 Compute staleness metrics

Compare `G_context_runtime` vs `G_context_static`. Load `references/staleness_metrics.md` for full formulas.

```yaml
metrics:
  new_edge_ratio:       count(new edges in runtime not in static) / count(static edges)
  missing_edge_ratio:   count(static edges not in runtime) / count(static edges)
  direction_mismatch:   count(edges with reversed direction)
  weight_deviation:     mean(|runtime_count - expected_count| / expected_count)
  staleness_score:      composite [0.0 - 1.0], see formula in references/staleness_metrics.md
```

---

## Phase 3: DETECT — Violation Classification

Classify each discrepancy into a severity tier. Output to `BOUNDARY_VIOLATIONS.md`.

### 3.1 Severity matrix

| Code | Severity | Condition | Example |
|------|----------|-----------|---------|
| BV-C1 | CRITICAL | Forbidden crossing observed in runtime | Auth service → Payment service direct call (bypasses Billing context) |
| BV-H1 | HIGH | New context-to-context edge not in static map | Order context now calls Inventory context directly (was via Warehouse) |
| BV-H2 | HIGH | Staleness score > 0.6 | >60% of expected edges missing or new edges dominate |
| BV-M1 | MEDIUM | Direction reversal on allowed crossing | A→B was allowed, but B→A appears with significant volume |
| BV-M2 | MEDIUM | Weight deviation > 3σ for allowed crossing | Expected 100 calls/day, observing 10,000 |
| BV-L1 | LOW | Missing static edge (runtime absent, but may be rare path) | Static map shows edge that never appears in 7d trace window |
| BV-L2 | LOW | Service found in traces with no context assignment | Orphan service not mapped to any bounded context |

### 3.2 BOUNDARY_VIOLATIONS.md output schema

```markdown
# Boundary Violations Report
Generated: <ISO8601 timestamp>
Staleness Score: <0.0-1.0>
Trace Window: <start> to <end>
Total Traces Analyzed: <N>

## Summary
| Severity | Count |
|----------|-------|
| CRITICAL | N     |
| HIGH     | N     |
| MEDIUM   | N     |
| LOW      | N     |

## Critical Findings

### BV-C1: <Title>
- **Source Context**: <ctx>
- **Target Context**: <ctx>
- **Services**: <src_service> → <dst_service>
- **Evidence**: <trace_count> calls, p99 latency <N>ms
- **Static Map Rule**: <reference to forbidden crossing>
- **Recommended Action**: <migrate call through allowed path | update static map | investigate>

## High Findings
[...]

## Context Diff
| Edge | Static | Runtime | Delta |
|------|--------|---------|-------|
| A→B  | allowed (100/day) | 10,500/day | +10500% |
```

---

## Phase 4: ACT — Auto-Trigger & Feedback

### 4.1 Re-understanding trigger

If `staleness_score > 0.6` OR any `BV-C1` violation exists:

```yaml
action: TRIGGER_REUNDERSTAND
target: boundary-enforcer skill
reason: >
  Runtime topology diverges significantly from static map.
  Staleness: <score>. New edges: <N>. Missing edges: <N>.
next_steps:
  - Re-run boundary-enforcer on current codebase
  - Update domain_map.json with validated runtime edges
  - Re-evaluate forbidden/allowed crossing list
```

### 4.2 Enrich graphify knowledge graph

Feed validated runtime edges into `graphify` to enrich the knowledge graph with production-grounded relationships:

```yaml
action: ENRICH_GRAPH
target: graphify skill
payload:
  edges:
    - source: <service_a>
      target: <service_b>
      relationship: CALLS_AT_RUNTIME
      weight: <call_count>
      evidence: TRACE
      staleness_validated: true
```

### 4.3 Log-analyzer integration hook

When invoked after `log-analyzer`, extract service names and correlation IDs from processed log entries. Treat log-derived service interactions as supplementary trace data when full OpenTelemetry is unavailable.

```python
def ingest_from_logs(log_analysis_output):
    """Convert log-analyzer output into lightweight runtime edges."""
    for entry in log_analysis_output.cross_service_calls:
        G_runtime.add_edge(
            src=entry.caller_service,
            dst=entry.callee_service,
            count=entry.frequency,
            source_type="LOG_INFERRED"   # lower confidence than TRACE
        )
```

---

## Confidence Levels

Tag every finding with its evidence provenance:

| Level | Meaning | Use In |
|-------|---------|--------|
| TRACE_DIRECT | Edge observed in distributed trace | Severity calculation, staleness score |
| LOG_INFERRED | Edge inferred from log correlation IDs | Supplementary only; flag with `[LOG]` |
| STATIC_MAP_ONLY | Edge exists only in static map | Missing-edge detection, not a violation |

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/extract_trace_graph.py` | Query OTLP/Jaeger/Zipkin and emit `runtime_graph.json` |
| `scripts/compute_staleness.py` | Diff runtime graph against static map; compute staleness score |

## References

| File | Load When |
|------|-----------|
| `references/trace_integration.md` | During Phase 1 (INGEST) — protocol-specific queries |
| `references/staleness_metrics.md` | During Phase 2 (CORRELATE) — scoring formulas |
