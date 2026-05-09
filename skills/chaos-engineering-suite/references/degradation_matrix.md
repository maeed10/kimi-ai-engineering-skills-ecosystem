# Degradation Matrix

Expected system behavior under each chaos failure mode, including fallback paths, state machine transitions, and recovery guarantees.

---

## Matrix Overview

Rows = Failure Modes. Columns = System Guarantees & Behaviors.

| Failure Mode | Fail-Closed Guarantee | Data Consistency | State Leakage | Latency Impact | User-Facing Behavior | Auto-Recovery |
|-------------|----------------------|------------------|---------------|----------------|----------------------|---------------|
| **CE-001 Policy Engine Kill** | BLOCK all in-flight | No partial decisions | None (ephemeral) | 500 ms spike → normal | Requests denied briefly | Yes (restart ≤ 5 s) |
| **CE-002 Sandbox OOM** | N/A (sandbox internal) | N/A | Zero leakage | Executor pause < 2 s | Task fails with cleanup message | Yes (executor healthy) |
| **CE-003 Clock Skew** | Preserved via logical clocks | Monotonic sequence | None | < 1 s overhead | Transparent to user | N/A (skew removal = immediate fix) |
| **CE-004 Malformed API** | Validator blocks poison | No invalid state stored | None | Fallback cache hit < 50 ms | 422 or cached safe result | Yes (auto-fallback to cache) |
| **CE-005 Vault Capacity** | Writes never partially commit | Atomic writes preserved | Zero (LRU eviction) | p99 < 200 ms | Writes succeed; old data evicted | Yes (continuous background eviction) |
| **CE-006 Network Partition** | BLOCK all requests | No orphaned evaluations | None | 2 s detection window | Requests denied during partition | Yes (heal = immediate resume) |
| **CE-007 Resource Exhaustion** | Circuit breaker opens | Load shed; no data loss | None if cb works | Fast-fail < 10 ms | 503 Service Unavailable | Yes (cb closes ≤ 30 s after relief) |

---

## Detailed Degradation Patterns

### CE-001: Policy Engine Kill

#### State Machine Transitions
```
HEALTHY → KILL_SIGNAL → IN_FLIGHT_DRAIN → DEAD → RESTARTING → HEALTHY
                    │
                    └──> All in-flight requests: outcome = BLOCK (grace_period_ms)
```

#### Fallback Path
- In-flight requests without a completed evaluation → `BLOCK` (default deny).
- New requests during restart → queue briefly, then evaluate normally once health check passes.

#### Observability & Alerts
- Metric: `policy_engine_restarts_total` increment.
- Metric: `in_flight_blocked_total` spike.
- Alert: `policy_engine_restarts_total > 0` in 1 min window (page if > 3 in 5 min).
- Log marker: `POLICY_ENGINE_SIGKILL_DETECTED`.

#### Recovery Pathway
1. Health manager / kubelet detects exit code.
2. Restart container / process.
3. Policy-engine replays any needed state from durable store (read-only on boot).
4. Health endpoint returns `200 OK`.
5. Traffic resumes.

---

### CE-002: Sandbox OOM

#### State Machine Transitions
```
RUNNING → MEMORY_ALLOC → OOM_KILL → SANDBOX_DEAD → CLEANUP → IDLE
                              │
                              └──> Executor emits SANDBOX_CLEANUP_COMPLETE
```

#### Fallback Path
- Task evaluation fails with explicit error `SANDBOX_OOM`.
- User receives task failure, not a timeout or stall.
- If retry policy allows, task may be rescheduled to a different sandbox with higher memory limit.

#### Observability & Alerts
- Metric: `sandbox_oom_kills_total` increment.
- Metric: `sandbox_cleanup_duration_seconds` histogram.
- Alert: `sandbox_oom_kills_total > 0` (info-level; page if > 10 in 5 min).
- Log marker: `SANDBOX_OOM_KILL` followed by `SANDBOX_CLEANUP_COMPLETE`.

#### Recovery Pathway
1. Cgroup OOM killer terminates sandbox process.
2. Executor `defer` / `finally` fires:
   - Remove `/tmp/sandbox-*`.
   - Revoke ephemeral tokens.
   - Release any shared-state leases.
3. Executor marks sandbox slot `IDLE`.
4. New tasks can be scheduled to the slot immediately.

---

### CE-003: Clock Skew

#### State Machine Transitions
```
SYNCED → SKEW_INTRODUCED → PHASE_TRANSITION_1 → PHASE_TRANSITION_2 → ... → COMPLETE
                              │
                              └──> Logical clock / sequence ID overrides wall-clock ordering
```

#### Fallback Path
- No explicit fallback needed; correctness is preserved by design.
- If wall-clock timers trigger spuriously due to skew, the phase-controller's sequence gate prevents execution.

#### Observability & Alerts
- Metric: `phase_controller_clock_skew_detected_seconds` (difference between local `time.Now()` and reference NTP source).
- Alert: `phase_controller_clock_skew_detected_seconds > 5` (warn); `> 30` (page).
- Log marker: `CLOCK_SKEW_IGNORED sequence_id=X wall_clock=Y`.

#### Recovery Pathway
1. NTP / chrony eventually resynchronizes wall clocks.
2. Alternatively, remove `libfaketime` / revert VM clock.
3. Phase-controller continues using logical sequence numbers; no restart required.

---

### CE-004: Malformed Gemini API Response

#### State Machine Transitions
```
REQUEST → GEMINI_CALL → MALFORMED_RESPONSE → VALIDATOR_REJECT → FALLBACK_CACHE → RETURN_SAFE
                                    │
                                    └──> If no cache → RETURN_422
```

#### Fallback Path
- **Primary**: Serve cached safe response if available and cache-eligible.
- **Secondary**: Return `422 Unprocessable Entity` to caller with structured error `validation_failed`.
- **Tertiary**: If validator itself throws an exception, outer middleware catches and returns `500` (this is a test failure — validator must never crash).

#### Observability & Alerts
- Metric: `gemini_validation_failure_total` increment with label `reason={syntax_error,schema_error,truncation,pollution}`.
- Metric: `gemini_fallback_cache_hits_total` increment.
- Alert: `gemini_validation_failure_total` rate > 0.1/sec (warn — may indicate upstream API degradation).
- Log marker: `GEMINI_VALIDATION_REJECT reason=X request_id=Y`.

#### Recovery Pathway
1. Validator rejects malformed payload immediately.
2. If cache miss, caller receives `422` and may retry.
3. Once upstream API returns valid JSON, normal path resumes automatically.
4. No restart or manual intervention required.

---

### CE-005: Obsidian Vault Capacity Exhaustion

#### State Machine Transitions
```
HEALTHY → NEAR_CAPACITY → WRITE_REQUESTED → LRU_EVICTION → ATOMIC_COMMIT → HEALTHY
                              │
                              └──> If no evictable entries → WRITE_REJECT (rare, capacity truly full)
```

#### Fallback Path
- Evict oldest unreferenced entries to make room.
- If entries are referenced (pinned), write is rejected with `507 Insufficient Storage`.
- Writes are always atomic — never a partial blob without metadata.

#### Observability & Alerts
- Metric: `obsidian_vault_size_bytes` gauge.
- Metric: `obsidian_eviction_total` counter with label `reason=capacity`.
- Metric: `obsidian_write_latency_seconds` histogram.
- Alert: `obsidian_vault_size_bytes > 0.95 * 1GB` (warn); `== 1GB` and `obsidian_eviction_rate` spikes (info).
- Log marker: `OBSIDIAN_EVICT key=K reason=capacity age_seconds=A`.

#### Recovery Pathway
1. Background eviction task continuously prunes LRU candidates.
2. If vault remains > 95 % for > 5 min, operator alert fires to investigate growth root cause.
3. No restart needed; system self-heals by eviction.

---

### CE-006: Network Partition (Policy ↔ Sandbox)

#### State Machine Transitions
```
CONNECTED → PARTITION_START → DETECTING → UNREACHABLE → FAIL_CLOSED → HEALED → CONNECTED
                                   │
                                   └──> All new requests: outcome = BLOCK (reason: SANDBOX_UNREACHABLE)
```

#### Fallback Path
- Requests during partition → `BLOCK` (fail-closed).
- No queued requests are retried indefinitely; they fail fast.
- After heal, new requests go through normal evaluation.

#### Observability & Alerts
- Metric: `policy_sandbox_partition_detected_total` increment.
- Metric: `policy_sandbox_unreachable_blocks_total` increment.
- Alert: `policy_sandbox_partition_detected_total > 0` (page if partition > 10 s — may indicate infra issue).
- Log marker: `NETWORK_PARTITION_DETECTED target=sandbox-executor duration_sec=X`.

#### Recovery Pathway
1. Health check / keep-alive fails for `detection_timeout_sec` (2 s).
2. Policy engine marks sandbox pool `UNHEALTHY`.
3. All new requests fast-fail to `BLOCK`.
4. Once TCP resumes, health check succeeds.
5. Sandbox pool marked `HEALTHY`; traffic resumes.
6. No restart required.

---

### CE-007: Resource Exhaustion (CPU & Memory)

#### State Machine Transitions
```
HEALTHY → PRESSURE_BUILD → THRESHOLD_EXCEEDED → CIRCUIT_BREAKER_OPEN → FAST_FAIL → RELIEF → HALF_OPEN → CLOSED → HEALTHY
```

#### Fallback Path
- While circuit breaker is open: fast-fail with `503 Service Unavailable`.
- Retry-After header set to 5 s (advisory).
- Load shed at the edge; no requests enter the degraded component.
- Other components unaffected due to bulkhead isolation.

#### Observability & Alerts
- Metric: `circuit_breaker_state` gauge (0=closed, 1=open, 2=half-open).
- Metric: `component_cpu_throttled_seconds` (CPU test) or `component_rss_bytes` (memory test).
- Alert: `circuit_breaker_state == 1` for > 60 s (page — indicates sustained pressure, not transient spike).
- Log marker: `CIRCUIT_BREAKER_OPEN component=X reason=resource_exhaustion`.

#### Recovery Pathway
1. Resource pressure is relieved (remove `cpulimit` / terminate memory workers).
2. Circuit breaker transitions to `HALF_OPEN` after cooldown (10 s).
3. A probe request is allowed through.
4. If probe succeeds, breaker moves to `CLOSED`.
5. Full traffic resumes.
6. If probe fails, breaker returns to `OPEN` for another cooldown cycle.

---

## Cross-Component Impact Map

### If Policy Engine Fails (CE-001, CE-006, CE-007-CPU)

| Component | Expected Impact | Mitigation |
|-----------|----------------|------------|
| Sandbox Executor | No new tasks scheduled | Tasks queue briefly; if queue full, reject |
| Phase Controller | Unaffected | Independent circuit breaker |
| Obsidian Vault | Unaffected | Read/write continues for non-policy ops |
| Gemini API Client | Unaffected | Only downstream of policy engine if policy allows |

### If Sandbox Executor Fails (CE-002, CE-006)

| Component | Expected Impact | Mitigation |
|-----------|----------------|------------|
| Policy Engine | Fails closed (BLOCK) | Partition detection or OOM awareness |
| Phase Controller | Unaffected | No direct dependency |
| Obsidian Vault | Unaffected | No direct dependency |

### If Phase Controller Fails (CE-003, CE-007-Memory)

| Component | Expected Impact | Mitigation |
|-----------|----------------|------------|
| Orchestrator | Workflow stalls | Orchestrator timeout + retry with backoff |
| Policy Engine | Unaffected | Policy evaluations continue independently |
| Sandbox Executor | Unaffected | Task execution continues independently |

### If Vault Fails (CE-005)

| Component | Expected Impact | Mitigation |
|-----------|----------------|------------|
| Phase Controller | Workflow pauses if phase state is vault-backed | In-memory fallback for transient state |
| Policy Engine | Unaffected | Policy state is separate |
| Sandbox Executor | Task outputs may fail to persist | Retry with exponential backoff |

### If Upstream API Fails (CE-004)

| Component | Expected Impact | Mitigation |
|-----------|----------------|------------|
| Post-Gemini Validator | Rejects malformed input | Cache fallback or 422 |
| Downstream Skills | Unaffected | Validator acts as firewall |
| Policy Engine | Unaffected | No direct dependency |

---

## Recovery Time Objectives (RTO)

| Failure Mode | Detection Time | Auto-Recovery Time | Max Acceptable Downtime |
|-------------|----------------|-------------------|------------------------|
| Policy Engine Kill | 0 s (immediate exit) | ≤ 5 s | 10 s |
| Sandbox OOM | 0 s (kernel event) | ≤ 10 s | 15 s |
| Clock Skew | 1 s (NTP diff check) | Immediate on skew removal | N/A |
| Malformed API | 0 s (inline validation) | Immediate (fallback or 422) | N/A |
| Vault Capacity | 0 s (inline size check) | Immediate (eviction inline) | N/A |
| Network Partition | 2 s (configurable) | Immediate on heal | 10 s |
| Resource Exhaustion | 5 s (circuit breaker) | ≤ 30 s after relief | 60 s |

*All RTOs assume standard hardware, no cascading failures, and healthy observability pipeline.*
