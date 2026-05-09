# Failure Mode Taxonomy

Standardized classification system for L0 enforcement-layer skill failures. Use this taxonomy to categorize failures consistently across all runbooks, alerting rules, and incident response procedures.

---

## 1. Failure Mode Categories

### 1.1 Crash (CRASH)

**Definition:** The skill process terminates unexpectedly or enters a non-recoverable error state from which it cannot continue serving requests.

**Subtypes:**
- **Panic/Unhandled Exception:** Runtime error that bubbles to the top without recovery (e.g., null pointer dereference, index out of bounds).
- **Fatal Signal:** Process killed by OS signal (SIGKILL, SIGSEGV, SIGBUS).
- **Assertion Failure:** Invariant violation that triggers a defensive abort.
- **Early Exit:** Process exits with non-zero status during initialization or shutdown.

**Typical Symptoms:**
- Container / pod enters `CrashLoopBackOff`.
- Process disappears from `ps` / systemd status shows `failed`.
- Log stream ends abruptly with a stack trace or fatal error.
- Health endpoint returns connection refused.

**Severity Floor:** SEV-1 (Critical) for enforcement-layer skills because safety invariants may no longer be enforced.

---

### 1.2 Hang (HANG)

**Definition:** The skill process remains alive but stops making forward progress. It accepts no new work, or existing work stalls indefinitely.

**Subtypes:**
- **Deadlock:** Circular lock dependency or resource contention blocking all worker threads.
- **Livelock:** Threads are active but make no useful progress (spinning on conflicting work).
- **Infinite Loop:** CPU-bound runaway execution consuming a full core.
- **I/O Block:** All threads blocked on a slow or unresponsive external resource (network, disk, subprocess).
- **Zombie State:** Process exists but its event loop / main thread is parked and unresponsive.

**Typical Symptoms:**
- Health endpoint times out or returns HTTP 504.
- CPU usage drops to near-zero despite queued work.
- Memory usage flatlines (no allocation activity).
- Request latency p99 spikes to timeout threshold.
- Goroutine / thread count plateaus at an abnormal high watermark.

**Severity Floor:** SEV-1 (Critical) because enforcement decisions are silently deferred while the skill appears healthy at the process level.

---

### 1.3 Corruption (CORRUPTION)

**Definition:** The skill persists or returns incorrect, partial, or stale state that deviates from the expected ground truth.

**Subtypes:**
- **State Corruption:** In-memory or on-disk state (cache, index, registry) becomes inconsistent with the authoritative source.
- **Data Corruption:** Payloads, events, or audit logs are mutated, truncated, or out-of-order.
- **Rule/Policy Corruption:** Active enforcement rules differ from the declared configuration due to a parse error, partial apply, or race during update.
- **Silent Skip:** The skill returns success but actually performed no enforcement action (false negative).
- **False Positive:** The skill denies or quarantines legitimate traffic / operations incorrectly.

**Typical Symptoms:**
- Drift between `expected_config_hash` and `running_config_hash`.
- Audit logs contain gaps in sequence numbers.
- Downstream consumers report anomalies despite the skill showing green health.
- Canary requests return unexpected allow/deny decisions.
- Checksum / hash mismatches on replicated state.

**Severity Floor:** SEV-1 (Critical) for enforcement-layer skills because corrupted policy may disable protections or block legitimate traffic.

---

### 1.4 Resource Exhaustion (RESOURCE)

**Definition:** The skill cannot acquire sufficient compute, memory, storage, or I/O resources to meet its service-level objectives.

**Subtypes:**
- **Memory Exhaustion:** OOMKilled, excessive GC pressure, swap thrashing, or heap growth beyond limit.
- **CPU Exhaustion:** Throttling, inability to keep up with event rate, scheduler delays.
- **Disk / Storage Exhaustion:** Volume full, WAL / log rotation blocked, inability to checkpoint state.
- **File Descriptor Exhaustion:** Too many open sockets or files; `EMFILE` / `ENFILE` errors.
- **Network Exhaustion:** Bandwidth saturation, connection pool depletion, DNS resolution failure.
- **Thread / Goroutine Exhaustion:** Scheduler latency grows as concurrency primitives are exhausted.

**Typical Symptoms:**
- Container OOMKilled events.
- `container_cpu_throttled_seconds_total` increases.
- Disk usage > 90% with write failures in logs.
- `too many open files` in application or system logs.
- Request queue depth growing monotonically.
- Latency increases linearly with load while throughput flatlines.

**Severity Floor:** SEV-2 (Major) unless the skill is a singleton (no horizontal scaling), in which case SEV-1.

---

### 1.5 Misconfiguration (CONFIG)

**Definition:** The skill is operating with an invalid, inconsistent, or unintended configuration that prevents correct enforcement or causes unsafe defaults.

**Subtypes:**
- **Schema Violation:** Config file fails validation against the skill's JSON Schema / protobuf definition.
- **Missing Required Field:** Mandatory parameter absent; skill falls back to an unsafe default or fails to start.
- **Cross-Field Inconsistency:** Two or more config values contradict each other (e.g., `timeout_ms > deadline_ms`).
- **Environment Mismatch:** Config intended for staging is deployed to production (wrong endpoints, relaxed TLS).
- **Secret/Reference Error:** Invalid API key, expired certificate, unreadable IAM policy, missing vault path.
- **Hot-Reload Failure:** Dynamic config update partially applied, leaving the skill in a split-brain state.

**Typical Symptoms:**
- Startup logs emit `config validation failed` and exit code != 0.
- Health endpoint returns `status: degraded` with `reason: config_sync_error`.
- Metrics show `config_reload_failures_total` incrementing.
- Skill behavior diverges from the declared policy without a code change.
- Operator notes a config version hash mismatch between control plane and skill.

**Severity Floor:** SEV-2 (Major) if caught at startup; SEV-1 (Critical) if a hot reload corrupts the running state of an active enforcement skill.

---

### 1.6 Dependency Failure (DEPENDENCY)

**Definition:** An external service, datastore, network path, or shared platform component that the skill requires becomes unavailable, slow, or returns incorrect responses.

**Subtypes:**
- **Hard Dependency Down:** Required service returns connection refused, DNS failure, or TLS handshake failure. Skill cannot function.
- **Soft Dependency Degraded:** Optional cache, telemetry sink, or sidecar is slow or absent. Skill functions in reduced mode.
- **Dependency Latency Spike:** Upstream API crosses timeout threshold, causing cascading timeouts in the skill.
- **Dependency Contract Break:** Upstream returns unexpected schema version, breaking deserialization.
- **Dependency Split-Brain:** Multi-node dependency (e.g., etcd, ZooKeeper) loses quorum; stale reads possible.

**Typical Symptoms:**
- `dependency_health_check{status="unhealthy"}` flips to 1.
- Circuit breaker metrics show `state="open"`.
- RPC client metrics show p99 latency > timeout and error rate > threshold.
- Skill logs show repeated `Retry-After` backoff loops.
- Skill enters `degraded` or `fallback` mode explicitly documented in its spec.

**Severity Floor:**
- SEV-1 if hard dependency (enforcement state store, identity provider, control plane).
- SEV-2 if soft dependency (metrics, non-critical cache).
- SEV-1 if fallback mode silently weakens enforcement (e.g., allow-all on auth failure).

---

## 2. Severity Definitions

| Severity | Title | Response Time | Impact | Escalation |
|----------|-------|---------------|--------|------------|
| **SEV-0** | Emergency | Immediate (≤ 5 min) | Catastrophic: cluster-wide safety compromise, active data loss, or regulatory breach. Page the on-call director. | Auto-escalate to incident commander after 5 min. |
| **SEV-1** | Critical | ≤ 15 min | Skill is down or enforcement is effectively disabled / dangerously corrupted. Immediate production risk. | Page on-call SRE + skill owner. |
| **SEV-2** | Major | ≤ 60 min | Skill is severely degraded: partial outage, resource exhaustion, significant latency, or false positives affecting users. | Page on-call SRE; notify skill owner Slack channel. |
| **SEV-3** | Minor | ≤ 4 hours | Degraded experience, minor false positives, or soft dependency failure. No immediate safety impact. | Ticket to skill owner; monitor during business hours. |
| **SEV-4** | Warning | ≤ 24 hours | Anomaly detected but no customer / enforcement impact. Pre-failure indicator. | Automated ticket; review in next standup. |

### Severity Mapping Rules for L0 Skills

1. **Any CRASH or HANG of an L0 enforcement skill is at least SEV-1.** Enforcement ceases; the layer below (or above) may not compensate in time.
2. **CORRUPTION that weakens or inverts enforcement is SEV-1 or SEV-0.** A corrupted deny-list that becomes an allow-all is SEV-0.
3. **RESOURCE exhaustion that triggers OOM or FD exhaustion is SEV-1** if the skill is a singleton or has no auto-scaling headroom.
4. **CONFIG errors caught at startup** block deployment and are SEV-2 (major deployment blocker).
5. **CONFIG hot-reload failures on a running enforcement skill** are SEV-1 because the running configuration may no longer match the declared policy.
6. **DEPENDENCY failure of a hard dependency** is SEV-1; soft dependency is SEV-2 or SEV-3 depending on user impact.

---

## 3. Degradation Modes

When a skill cannot operate at full capacity, it may enter one of the following degradation modes. Runbooks must document which mode the skill uses.

| Mode | Description | Safety Implication |
|------|-------------|--------------------|
| **Fail-Closed** | Deny all traffic / operations by default. | Safest for security enforcement; may cause service outage. |
| **Fail-Open** | Allow all traffic / operations by default. | Dangerous for enforcement; only acceptable with compensating controls. |
| **Fail-Fixed** | Continue using the last known good state / snapshot. | Safe if the snapshot is recent; risk of stale policy. |
| **Fail-Partial** | Degrade to a subset of functionality (e.g., local decisions only, no global aggregation). | Mixed; must document exactly which subsystems remain active. |
| **Fail-Queue** | Accept and queue work but stop processing; drain when recovered. | Safe if queue has back-pressure and bounded size; unbounded queue = memory risk. |
| **Fail-Alert** | Continue operating but escalate aggressively to operators. | Only viable if the skill can still perform its core function. |

**Enforcement-Layer Requirement:**
- L0 skills **must not** use `fail-open` for safety-critical enforcement without an explicit, documented, and regularly reviewed risk acceptance.
- If `fail-open` is used (e.g., availability-critical path), the runbook must list the compensating control (e.g., L1 skill that double-checks, canary gate, emergency manual review).

---

## 4. Cascade Risk Matrix

Failure in one L0 skill can trigger downstream failures in L1-L8 skills. When writing a runbook, document the cascade potential using this matrix:

| Downstream Layer | Typical Cascade Trigger | Effect |
|------------------|------------------------|--------|
| **L1 (Orchestration)** | L0 policy engine fails closed → pods denied scheduling / ingress blocked | Workload deployment freeze or traffic blackout |
| **L2 (Service Mesh)** | L0 mTLS / identity provider down → sidecars fail validation | East-west traffic dropped cluster-wide |
| **L3 (Application)** | L0 secrets manager unavailable → apps cannot fetch credentials | Application startup failure or secret fallback to static (risk) |
| **L4 (Data)** | L0 access control sync failed → database layer sees stale IAM | Unauthorized access possible or authorized access denied |
| **L5 (Analytics)** | L0 audit log shipper down → compliance events lost | Regulatory gap; downstream SIEM / lake sees missing data |
| **L6 (ML/Inference)** | L0 model governance gate offline → unapproved models may deploy | Model risk: unvalidated inference paths opened |
| **L7 (UI/API Gateway)** | L0 rate-limiter / WTL fails open → gateway overload | Gateway OOM, 502/503 to all clients |
| **L8 (Integration)** | L0 event bus policy engine offline → malformed events forwarded | Partner data corruption or contract violation |

**Runbook Requirement:**
For each L0 skill, list the **top-3 downstream cascade risks** and the **detection method** for each cascade (metric, log pattern, or alert name).
