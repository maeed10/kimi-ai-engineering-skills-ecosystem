# Chaos Test Catalog

Full test case definitions with injection methods, parameters, acceptance criteria, and recovery steps.

---

## CE-001: Policy Engine Kill Mid-Transaction

### Objective
Validate that in-flight policy evaluations are always resolved to `BLOCK` when the policy engine dies unexpectedly.

### Preconditions
- Policy engine is healthy and receiving traffic.
- At least 10 in-flight requests are actively being evaluated (injected via load generator).
- Audit log sink is writable and queryable within 1 s.
- `grace_period_ms` is set to 500 ms (default).

### Injection Steps
1. Start load generator: submit 50 requests/sec with 200 ms think time.
2. Wait for steady-state (10 s warm-up).
3. Identify active policy-engine PID via `pgrep policy-engine` or container ID via `docker ps`.
4. Execute `kill -9 <PID>` or `docker kill <container>`.
5. Start timer immediately after kill signal.
6. Continue capturing audit logs for 30 s.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `grace_period_ms` | 500 | Maximum time allowed for in-flight requests to resolve to `BLOCK` |
| `in_flight_target` | 10 | Minimum number of requests actively being evaluated at kill time |
| `load_rate` | 50 rps | Request injection rate during the test |
| `observation_window_sec` | 30 | Time to capture post-kill audit events |

### Expected System Reaction
- Policy engine restarts automatically via systemd / kubelet / health manager within 5 s.
- All in-flight requests observed in audit log within 500 ms of kill show outcome `BLOCK`.
- No in-flight request shows outcome `ALLOW` or `PENDING` after 500 ms.
- Post-restart, new requests are evaluated normally.

### Acceptance Criteria
```
PASS if:
  - count(audit.outcome == "BLOCK" for events in 0..500ms after kill) == count(in_flight)
  - count(audit.outcome == "ALLOW" for events in 0..30s after kill) == 0
  - policy-engine health check passes within 5s after kill
FAIL otherwise.
```

### Recovery Steps
- Verify policy-engine auto-restart is enabled (`Restart=always` in systemd, or pod `restartPolicy: Always`).
- If test fails, inspect shared state store for stale locks that may prevent re-election.

---

## CE-002: Sandbox Container OOM Kill

### Objective
Validate that sandbox OOM triggers graceful cleanup and zero state leakage.

### Preconditions
- Sandbox executor is running with cgroup v2 memory controller enabled.
- Sandbox memory limit is set to 50 MB for the test namespace / pod.
- `/tmp/sandbox-*` directories are mounted on a shared tmpfs or hostPath volume for verification.
- Audit log captures `SANDBOX_*` lifecycle events.

### Injection Steps
1. Configure sandbox memory limit to 50 MB.
2. Submit a task that intentionally allocates a 100 MB byte array inside the sandbox.
3. Wait for container runtime to deliver OOMKill.
4. Query sandbox executor logs for cleanup event.
5. Scan `/tmp/sandbox-*` for residual files.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `sandbox_mem_limit_mb` | 50 | Cgroup memory limit applied to sandbox container |
| `oom_payload_mb` | 100 | Memory allocation size inside sandbox to trigger OOM |
| `cleanup_timeout_sec` | 10 | Max time to wait for `SANDBOX_CLEANUP_COMPLETE` log |

### Expected System Reaction
- Container receives `Killed process ... (oom_score_adj: 1000)` from cgroup.
- Sandbox executor emits `SANDBOX_CLEANUP_COMPLETE` within 10 s.
- All ephemeral tokens issued to the sandbox are revoked.
- `/tmp/sandbox-*` is empty or removed entirely.
- No shared-state keys remain locked by the dead sandbox's PID.

### Acceptance Criteria
```
PASS if:
  - OOMKill event is observed in kernel log or container runtime event stream
  - "SANDBOX_CLEANUP_COMPLETE" appears in executor logs within cleanup_timeout_sec
  - /tmp/sandbox-* residual file count == 0
  - No orphaned token leases exist in token store
FAIL otherwise.
```

### Recovery Steps
- If cleanup fails, check executor's `defer` / `finally` blocks for missing temp directory removal.
- Verify token revocation endpoint is reachable from executor even when sandbox is dead.

---

## CE-003: Clock Skew Between Phase-Controller and Orchestrator

### Objective
Validate phase transition ordering correctness under clock skew.

### Preconditions
- Phase-controller and orchestrator are running on separate hosts or VMs.
- Both use NTP, but test will override via `libfaketime` or hypervisor clock skew.
- A 4-phase workflow is registered (`INIT` → `VALIDATE` → `EXECUTE` → `COMPLETE`).

### Injection Steps
1. Set phase-controller clock forward by +30 s: `LD_PRELOAD=libfaketime.so.1 FAKETIME="+30s" <phase-controller-cmd>`.
2. Orchestrator clock remains correct.
3. Submit a multi-phase workflow via orchestrator API.
4. Capture phase transition events from both components.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `skew_seconds` | 30 | Forward offset applied to phase-controller |
| `workflow_phases` | 4 | Number of phases in the test workflow |
| `max_transition_time_sec` | 60 | Upper bound for total workflow completion |

### Expected System Reaction
- Orchestrator timestamps remain correct; phase-controller timestamps are skewed.
- Transition ordering logic uses monotonic sequence numbers or vector clocks, not wall-clock time alone.
- Workflow completes in correct phase order without skipping or re-ordering.
- No duplicate phase executions occur due to skewed timeout logic.

### Acceptance Criteria
```
PASS if:
  - observed phase sequence == ["INIT", "VALIDATE", "EXECUTE", "COMPLETE"]
  - no phase is visited twice
  - no phase is skipped
  - total wall-clock time to completion < max_transition_time_sec
FAIL otherwise.
```

### Recovery Steps
- If ordering breaks, inspect whether phase-controller uses `time.Now()` instead of logical clocks or leased sequence numbers.
- Recommend replacing wall-clock comparisons with `phase_sequence_id` or hybrid logical clocks (HLC).

---

## CE-004: Gemini API Malformed JSON Response

### Objective
Validate that malformed upstream JSON is caught and never propagates downstream.

### Preconditions
- A Gemini API mock / proxy is deployed in the request path.
- `post-gemini-validator` middleware is active between API client and downstream skills.
- A warm cache exists with at least one safe, schema-valid cached response.

### Injection Steps
1. Configure Gemini API mock to return malformed JSON variants:
   - Unclosed braces / brackets.
   - Wrong schema (string where object expected).
   - Truncated payload (TCP close mid-response).
   - Valid JSON but disallowed fields (`__proto__`, constructor pollution).
2. Submit 100 requests through the system.
3. Capture outputs at each middleware layer.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `malformed_variants` | 4 | Number of distinct malformation types to test |
| `requests_per_variant` | 25 | Requests injected per variant |
| `fallback_cache_ttl_sec` | 300 | TTL for safe cached responses used as fallback |

### Expected System Reaction
- `post-gemini-validator` catches 100 % of malformed JSON.
- Validator returns `422 Unprocessable Entity` to the caller.
- If the request is cache-eligible and a safe cached response exists, it is served instead.
- Downstream skills never receive malformed objects.
- Alert / metric counter `gemini_validation_failure_total` is incremented.

### Acceptance Criteria
```
PASS if:
  - all 100 malformed responses are intercepted before downstream skills
  - downstream input validation logs show zero schema violations
  - validator returns HTTP 422 (or cached 200 with safe payload)
  - no panic, crash, or uncaught exception in any component
FAIL otherwise.
```

### Recovery Steps
- If any malformed payload leaks, add JSON Schema validation at the ingress edge before deserialization into native objects.
- Consider canonicalizing responses through a strict DTO layer with `json.Unmarshal` into typed structs with `disallowUnknownFields`.

---

## CE-005: Obsidian Vault 1 GB Capacity Exhaustion

### Objective
Validate atomic writes succeed and oldest entries are evicted under capacity pressure.

### Preconditions
- Obsidian vault backend is instrumented with size metrics.
- Vault max capacity is configured to 1 GB.
- A preload script exists to fill vault to ~1 GB − 10 MB with synthetic entries.

### Injection Steps
1. Pre-fill vault to 1 GB − 10 MB using historical synthetic entries.
2. Trigger 100 new atomic write operations that each add 1 MB of content.
3. Monitor vault size, write latency, and eviction events.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `vault_capacity_mb` | 1024 | Hard capacity ceiling |
| `preload_fill_mb` | 1014 | Amount to pre-fill before test |
| `new_write_count` | 100 | Number of concurrent atomic writes |
| `new_write_size_mb` | 1 | Size of each new write payload |
| `write_latency_p99_ms` | 200 | SLO for write latency p99 |

### Expected System Reaction
- Each new write is committed atomically (all-or-nothing).
- Vault size never exceeds 1 GB at any instant.
- Oldest unreferenced entries are evicted using strict LRU.
- Write latency p99 remains under 200 ms.
- Evicted entries are logged with `OBSIDIAN_EVICT` event including key and reason (`capacity`).

### Acceptance Criteria
```
PASS if:
  - all 100 writes return success (HTTP 201 or equivalent)
  - max(vault_size_mb) <= 1024 during test window
  - write latency p99 <= 200 ms
  - evicted entries are the oldest unreferenced keys
  - no partial writes observed (no orphaned metadata without blob)
FAIL otherwise.
```

### Recovery Steps
- If atomicity breaks, check whether blob write and metadata update share a single transaction or distributed transaction boundary.
- If eviction latency spikes, consider asynchronous background eviction with reserved headroom.

---

## CE-006: Network Partition Between Policy-Engine and Sandbox-Executor

### Objective
Validate fail-closed behavior when the policy-engine cannot reach the sandbox-executor.

### Preconditions
- Policy-engine and sandbox-executor communicate over TCP (gRPC or HTTP/2).
- Both run in containers or network namespaces where `iptables` rules can be applied.
- Partition detection timeout is configured to 2 s.

### Injection Steps
1. Identify the network bridge / veth pair linking policy-engine and sandbox-executor.
2. Apply `iptables -A FORWARD -s <policy-engine-ip> -d <sandbox-executor-ip> -j DROP` and reverse direction.
3. Immediately submit 20 new requests.
4. Hold partition for 30 s.
5. Remove `iptables` rules to heal partition.
6. Wait 10 s, then submit 5 recovery requests.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `partition_duration_sec` | 30 | Length of network blackout |
| `detection_timeout_sec` | 2 | Max time before fail-closed behavior must begin |
| `requests_during_partition` | 20 | Requests sent while partition is active |
| `requests_after_healing` | 5 | Requests sent after partition heals |

### Expected System Reaction
- Within 2 s of partition onset, policy-engine detects unreachability.
- All requests during partition are `BLOCK`ed with reason `SANDBOX_UNREACHABLE`.
- No requests are `ALLOW`ed or left in `PENDING` state.
- After partition heals, policy-engine resumes normal communication without manual restart.
- Recovery requests after healing are evaluated normally.

### Acceptance Criteria
```
PASS if:
  - all requests_during_partition outcomes == "BLOCK"
  - first "BLOCK" with reason "SANDBOX_UNREACHABLE" occurs within detection_timeout_sec
  - zero "ALLOW" or "PENDING" outcomes during partition
  - all requests_after_healing outcomes are normal (not forced "BLOCK")
  - no manual restart required to restore communication
FAIL otherwise.
```

### Recovery Steps
- If fail-closed does not trigger, inspect whether policy-engine uses a blocking call with long timeout instead of a short health-check ping.
- Ensure policy-engine has a separate liveness path distinct from the request forwarding path.

---

## CE-007: Resource Exhaustion (CPU & Memory Pressure)

### Objective
Validate circuit-breaker behavior under CPU starvation and memory pressure.

### Preconditions
- Circuit breaker is instrumented with metrics `circuit_breaker_state` (0=closed, 1=open, 2=half-open).
- Policy-engine and phase-controller expose health endpoints.
- Load generator can sustain 100 concurrent requests.

### Injection Steps (CPU Starvation)
1. Run `cpulimit -p <policy-engine-pid> -l 5` to limit policy-engine to 5 % of one core.
2. Submit 100 concurrent policy evaluations.
3. Monitor circuit breaker state transitions and error rate.
4. Release CPU limit after 60 s.

### Injection Steps (Memory Pressure)
1. In phase-controller, spawn 1 000 background workers each holding a 1 MB payload.
2. Submit normal phase-transition traffic.
3. Monitor memory RSS, OOM score, and circuit breaker state.
4. Terminate background workers after 60 s.

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `cpu_limit_percent` | 5 | CPU cap applied to policy-engine |
| `concurrent_requests` | 100 | Concurrent load during CPU starvation |
| `memory_workers` | 1000 | Background workers holding memory |
| `memory_per_worker_mb` | 1 | Memory held per background worker |
| `cb_open_max_sec` | 5 | Max time allowed for circuit breaker to open |
| `cb_close_max_sec` | 30 | Max time allowed for circuit breaker to close after recovery |

### Expected System Reaction
- Under CPU starvation: latency spikes, error rate exceeds threshold, circuit breaker opens within 5 s. Other components unaffected.
- Under memory pressure: phase-controller RSS climbs, health endpoint latency degrades, circuit breaker opens within 5 s. No OOMKill of phase-controller during test because limit is soft (workers stay within cgroup).
- After resource is released: error rate drops, circuit breaker transitions to half-open, then fully closes within 30 s.
- No cascading failures to other components (orchestrator, vault, policy-engine when testing memory pressure).

### Acceptance Criteria
```
PASS if:
  - circuit breaker opens within cb_open_max_sec for both CPU and memory tests
  - while open, >= 95% of requests to the stressed component receive fast-fail (HTTP 503 or equivalent)
  - other components show normal error rates (< 1%) during the test
  - circuit breaker closes within cb_close_max_sec after resource release
  - no component restart required during or after the test
FAIL otherwise.
```

### Recovery Steps
- If circuit breaker fails to open, check whether the failure threshold is too high or the measurement window is too long.
- If cascade occurs, verify that downstream components have their own circuit breakers and bulkheads.

---

## Test Execution Summary Table

| Test ID | Category | Injection Primitive | Target Component | Max Time to Detect | SLO Guarantee |
|---------|----------|---------------------|------------------|-------------------|---------------|
| CE-001  | Policy Kill | `SIGKILL` / `docker kill` | Policy Engine | 500 ms | 100 % BLOCK |
| CE-002  | Sandbox OOM | Cgroup memory limit | Sandbox Executor | 10 s | Zero leakage |
| CE-003  | Clock Skew | `libfaketime` / VM skew | Phase Controller | 60 s | Monotonic order |
| CE-004  | Malformed API | Gemini API mock | Post-Gemini Validator | 0 ms (inline) | Zero propagation |
| CE-005  | Vault Capacity | Pre-fill + atomic writes | Obsidian Vault | 200 ms p99 | Atomic + LRU eviction |
| CE-006  | Network Partition | `iptables` DROP | Policy ↔ Sandbox | 2 s | 100 % BLOCK |
| CE-007  | Resource Exhaustion | `cpulimit` / memory workers | Policy Engine + Phase Controller | 5 s | Circuit breaker open |

*All tests are designed to be run independently or as part of the full suite. Running in sequence is recommended to isolate side effects.*
