# SLO Definitions for L0 Enforcement-Layer Skills

This document defines the quantitative Service Level Objectives for every L0 enforcement-layer skill. All thresholds are derived from user-facing impact: if an SLO is missed, a downstream user experiences delayed decisions, failed policy checks, or unavailable sandbox execution.

## Measurement Principles

1. **In-process histograms** record latency at microsecond granularity using exponential buckets (base 2) to minimize relative error at the tail.
2. **Availability** is measured from the edge load balancer or the first hop that can report health. A skill is "up" when its health probe returns 200 OK and it can serve at least one request class within SLO latency.
3. **Error rate** includes all outcomes that violate the caller's contract: 5xx, timeouts, `ALLOW` when policy says `DENY`, `DENY` when policy says `ALLOW`, sandbox escapes, and phase-transition collisions.
4. **Throughput** is reported as sustained RPS (not burst). A skill must sustain the listed throughput for 5 minutes without p99 latency degrading > 10%.

---

## Policy-Engine (`policy-engine-standalone`)

The policy-engine evaluates every inbound request against a corpus of rules. Latency is critical because it sits in the synchronous path of request admission.

### Latency SLOs

| Operation | p50 Target | p95 Target | p99 Target | Rationale |
|-----------|-----------:|-----------:|-----------:|-----------|
| Single-rule evaluation | 2 ms | 5 ms | 10 ms | Fast path: simple attribute match |
| Multi-rule batch (100 rules) | 10 ms | 25 ms | 50 ms | Primary user-facing metric |
| Complex regex / PCRE rule | 5 ms | 15 ms | 30 ms | Regex backtracking risk |
| Policy reload (hot swap) | 50 ms | 100 ms | 200 ms | Must not block in-flight requests |

### Throughput SLO

| Metric | Target | Degradation Threshold |
|--------|-------:|----------------------:|
| Sustained validations/sec | 10,000 RPS | p99 > 50 ms at 8,000 RPS |
| Peak burst (5 s) | 25,000 RPS | Queue depth > 100 |

### Availability & Error Rate

| Metric | Target | Budget |
|--------|-------:|-------:|
| Availability | 99.9% | 43.2 min / 30 days |
| Error rate | < 0.1% | 0.1% of total requests |

### Capacity SLO: Max Rule Count

| Rule Type | Count Before p95 > 100 ms | Hard Limit |
|-----------|--------------------------:|-----------:|
| Simple attribute rules | 50,000 | 100,000 |
| Regex rules | 2,000 | 5,000 |
| Composite (AND/OR) rules | 10,000 | 20,000 |
| **Total mixed corpus** | **10,000** | **25,000** |

> Rationale: The 10,000 mixed-corpus knee-point is the primary capacity planning number. When the active rule count approaches 8,000, plan horizontal sharding or rule simplification.

---

## Sandbox-Executor (`sandbox-allowlist-enforcer`, `tee-executor`)

Sandbox skills create isolated execution environments. SLOs are dominated by container lifecycle and image logistics.

### Latency SLOs

| Operation | p50 Target | p95 Target | p99 Target | Rationale |
|-----------|-----------:|-----------:|-----------:|-----------|
| Container create + start | 1.5 s | 3.0 s | 5.0 s | User-visible warm-up time |
| Image pull (warm cache, <= 500 MB) | 2 s | 8 s | 30 s | Standard image path |
| Image pull (cold, > 500 MB) | 10 s | 30 s | 120 s | Documented fallback; not paged |
| Sandbox teardown | 200 ms | 800 ms | 2,000 ms | Resource release must be fast |
| Exec inside running sandbox | 50 ms | 100 ms | 200 ms | Interactive command latency |

### Throughput SLO

| Metric | Target | Degradation Threshold |
|--------|-------:|----------------------:|
| Concurrent sandboxes | 500 | p95 launch > 5 s at 400 |
| Launches per minute | 120 | p99 launch > 10 s at 100/min |
| Teardowns per minute | 300 | Zombie cgroups > 10 after 60 s |

### Availability & Error Rate

| Metric | Target | Budget |
|--------|-------:|-------:|
| Availability | 99.5% | 216 min / 30 days |
| Launch failure rate | < 0.5% | 0.5% of total launches |
| Escape events | 0 | Any escape = P0 incident |

> Rationale: Sandbox availability target is intentionally lower than policy-engine because it depends on external image registries and host resources. However, escape events are a safety SLO, not a reliability SLO, and must be zero.

---

## Phase-Controller (`phase-iterate-controller`, `phase-controller-external`)

Phase-controller orchestrates multi-step transitions between pipeline phases. Latency is measured from request ingress to the controller emitting the next-phase artifact.

### Latency SLOs

| Operation | p50 Target | p95 Target | p99 Target | Rationale |
|-----------|-----------:|-----------:|-----------:|-----------|
| Transition proposal | 20 ms | 50 ms | 100 ms | Core loop latency |
| Artifact validation (deep) | 50 ms | 100 ms | 200 ms | Schema + signature + dependency check |
| Artifact validation (shallow) | 5 ms | 15 ms | 30 ms | Hash + size check only |
| State persistence write | 10 ms | 25 ms | 50 ms | Atomic CAS to backing store |
| Full phase transition (end-to-end) | 40 ms | 100 ms | 200 ms | Proposal + validation + persistence + emit |

### Throughput SLO

| Metric | Target | Degradation Threshold |
|--------|-------:|----------------------:|
| Transitions/sec | 1,000 TPS | p99 > 200 ms at 800 TPS |
| Concurrent in-flight transitions | 200 | State version collisions > 1% |

### Availability & Error Rate

| Metric | Target | Budget |
|--------|-------:|-------:|
| Availability | 99.95% | 21.6 min / 30 days |
| Transition failure rate | < 0.05% | 0.05% of total transitions |
| State machine inconsistency | 0 | Any inconsistency = P0 incident |

> Rationale: Phase-controller has the strictest availability target because a failure here blocks the entire pipeline. The 99.95% target allows only ~21 minutes of downtime per month, justifying active-active replication.

---

## Memory-Guard (`federated-memory-mesh`)

Memory-guard skills enforce access controls and quotas on the federated memory mesh. Query latency affects every retrieval and embedding operation.

### Latency SLOs

| Operation | p50 Target | p95 Target | p99 Target | Rationale |
|-----------|-----------:|-----------:|-----------:|-----------|
| Access-control query | 1 ms | 3 ms | 5 ms | Hot path: every read/write |
| Quota check | 500 µs | 1 ms | 2 ms | Must not add overhead to fast stores |
| Cross-node permission resolution | 5 ms | 15 ms | 30 ms | Distributed consensus for sensitive ops |
| Audit log write (async) | 5 ms | 20 ms | 50 ms | Fire-and-forget but must not backlog |

### Throughput SLO

| Metric | Target | Degradation Threshold |
|--------|-------:|----------------------:|
| ACL queries/sec | 50,000 QPS | p99 > 5 ms at 40,000 QPS |
| Audit log events/sec | 10,000 EPS | Log queue depth > 1,000 |

### Availability & Error Rate

| Metric | Target | Budget |
|--------|-------:|-------:|
| Availability | 99.9% | 43.2 min / 30 days |
| ACL mis-evaluation rate | 0 | Any incorrect ALLOW/DENY = P0 |
| Quota overrun events | < 0.01% | 0.01% of total operations |

> Rationale: ACL mis-evaluation is a security SLO, not a reliability SLO. It must be zero. Quota overruns are reliability-adjacent but can degrade fairness, so they are capped at 0.01%.

---

## Egress-DPI-Guard (`egress-dpi-guard`)

Deep-packet inspection for outbound traffic. Latency is measured per flow or per chunk, not per byte.

### Latency SLOs

| Operation | p50 Target | p95 Target | p99 Target | Rationale |
|-----------|-----------:|-----------:|-----------:|-----------|
| Flow classification | 50 µs | 100 µs | 200 µs | Kernel-bypass path |
| DPI inspection (first packet) | 200 µs | 500 µs | 1 ms | TLS handshake / SNI extraction |
| Content filter decision | 100 µs | 300 µs | 500 µs | Per-chunk after classification |
| Rule update (hot) | 1 ms | 5 ms | 10 ms | Must not drop flows during reload |

### Throughput SLO

| Metric | Target | Degradation Threshold |
|--------|-------:|----------------------:|
| Flows/sec | 100,000 | p99 classification > 1 ms at 80,000 |
| Gbps throughput | 10 Gbps | Packet drops > 0.001% at 8 Gbps |

### Availability & Error Rate

| Metric | Target | Budget |
|--------|-------:|-------:|
| Availability | 99.95% | 21.6 min / 30 days |
| False-negative rate (undetected leak) | 0 | Any leak = P0 |
| False-positive rate (blocked benign) | < 0.1% | 0.1% of total flows |

---

## SLO Rationale Summary Table

| Skill | Strictest Latency | Strictest Availability | Why It Matters |
|-------|-------------------|------------------------|----------------|
| Policy-Engine | p99 < 50 ms | 99.9% | Blocks every request admission decision |
| Sandbox-Executor | p99 < 5 s launch | 99.5% | User-visible warm-up; lower target due to external deps |
| Phase-Controller | p99 < 200 ms E2E | 99.95% | Pipeline heartbeat; any stall blocks all downstream work |
| Memory-Guard | p99 < 5 ms ACL | 99.9% | Hot path for all memory mesh reads/writes |
| Egress-DPI-Guard | p99 < 1 ms | 99.95% | Packet-level inline; drops directly impact connectivity |

---

## SLO Review Cadence

- **Weekly**: Automated error-budget burn report emailed to skill owners.
- **Monthly**: Human review of thresholds; adjust if empirical distribution shows > 5% headroom or consistent misses.
- **Quarterly**: Re-baseline all SLOs after major architecture changes (e.g., new storage backend, kernel upgrade).
