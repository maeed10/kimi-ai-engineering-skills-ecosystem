# Chaos Patterns Reference

Validation patterns, pass/fail criteria, and metric thresholds for resilience
mechanisms under test. Use these as templates when designing experiments.

---

## 1. Circuit Breaker Validation

### Purpose
Verify the circuit breaker transitions correctly under sustained failure and
recovers after dependency health returns.

### Typical Configuration
- `failureRateThreshold`: 50% (open after half of calls fail)
- `slowCallRateThreshold`: 80% (open if too many calls are slow)
- `slowCallDurationThreshold`: 2s
- `waitDurationInOpenState`: 30s
- `permittedNumberOfCallsInHalfOpenState`: 5

### Experiment Pattern
1. Baseline: record `resilience4j_circuitbreaker_state{name="cb-checkout"}` = CLOSED.
2. Inject `http_5xx` at 100% to `payment-service` for 60s.
3. Expect state transition to OPEN within 10s after threshold crossed.
4. Stop fault. Wait `waitDurationInOpenState`.
5. Expect state transition to HALF_OPEN, then CLOSED after permitted probes pass.

### Pass Criteria
| Check | Threshold |
|-------|-----------|
| State reaches OPEN | Within 2 × threshold evaluation window |
| Error rate during OPEN | <5% (calls rejected fast, not forwarded) |
| Recovery to HALF_OPEN | Within `waitDurationInOpenState` + 10s tolerance |
| Recovery to CLOSED | After permitted probes, within 30s |

### Fail Criteria
- Circuit never opens → vulnerability: cascading failure risk
- Opens too late (>2× window) → vulnerability: blast radius already damaged
- Calls still forwarded in OPEN state → vulnerability: bypass or config error
- Never recovers to CLOSED → vulnerability: stuck-open, false-positive failure detection

### Metrics to Watch
- `resilience4j_circuitbreaker_state`
- `resilience4j_circuitbreaker_calls_total{kind="failed"}`
- `resilience4j_circuitbreaker_calls_total{kind="successful"}`
- `resilience4j_circuitbreaker_calls_total{kind="ignored"}`
- Application error rate (should drop immediately when OPEN)

---

## 2. Fallback Testing

### Purpose
Verify that when a dependency is unavailable, the service degrades gracefully
using cached data, static defaults, or alternative paths.

### Experiment Pattern
1. Baseline: normal request to `checkout-service` via `GET /api/v1/cart/pricing`.
2. Inject `connection_drop` or `http_5xx` at 100% to `pricing-service`.
3. Observe if responses still succeed with degraded data (stale cache, default price).

### Pass Criteria
| Check | Threshold |
|-------|-----------|
| Fallback hit ratio | ≥ expected minimum (usually 80–100% during total outage) |
| Fallback latency | ≤ fallback SLO (often 2× normal P99, max 500ms for cached) |
| Response validity | Data schema correct; no null-pointer exceptions |
| User-visible errors | 0% user-facing 5xx (service should return 200 with degraded body) |

### Fail Criteria
- Fallback not triggered → vulnerability: total outage propagates
- Fallback returns errors (500 from service itself) → vulnerability: fallback code broken
- Fallback latency exceeds SLO → vulnerability: cache is cold or fallback path is too slow
- Fallback data silently wrong → vulnerability: stale/corrupt data served without warning

### Metrics to Watch
- `resilience4j_fallback_calls_total`
- Response latency of requests during fault
- HTTP status distribution (should shift from 200/5xx mix to 100% 200 if fallback works)
- Cache hit ratio (if fallback uses cache)

---

## 3. Retry Logic Validation

### Purpose
Verify that transient failures are retried with appropriate backoff, and that
retry does not overwhelm a recovering downstream service.

### Typical Configuration
- `maxAttempts`: 3
- `waitDuration`: 1s (exponential backoff, max 10s)
- `retryExceptions`: `IOException`, `TimeoutException`
- `ignoreExceptions`: `BadRequestException` (non-retryable)

### Experiment Pattern
1. Baseline: stable dependency, measure normal request volume.
2. Inject intermittent `http_5xx` or `latency` (50% of calls fail/slow, alternating).
3. Measure outgoing request volume vs. incoming request volume.
4. Stop fault. Measure if retry rate drops as dependency recovers.

### Pass Criteria
| Check | Threshold |
|-------|-----------|
| Retry attempts avg | ≤ `maxAttempts` − 1 (most succeed on first or second try) |
| Outgoing request multiplier | ≤ 2.5× incoming during transient faults (no retry storm) |
| Inter-retry interval | ≥ `waitDuration` with exponential growth observed |
| No retry on non-retryable | `ignoreExceptions` never retried (verify with bad-request test) |

### Fail Criteria
- Retry storm: outgoing requests >3× incoming → vulnerability: amplifies failure
- Immediate retry (no backoff) → vulnerability: thundering herd on recovery
- Retries on non-retryable errors (e.g., 400) → vulnerability: wasted resources, possible mutation replay
- No retries on transient 503 → vulnerability: unnecessary user-facing errors

### Metrics to Watch
- `resilience4j_retry_calls_total{kind="failed_retry"}`
- `resilience4j_retry_calls_total{kind="successful_without_retry"}`
- `resilience4j_retry_calls_total{kind="successful_with_retry"}`
- Outgoing request rate vs. incoming request rate ratio
- Dependency response time during recovery (should not spike due to retry load)

---

## 4. Bulkhead Validation

### Purpose
Verify that resource limits (thread pools, connection pools, semaphores) prevent
one workload from exhausting capacity shared by others.

### Typical Configuration
- `maxConcurrentCalls`: 25
- `maxWaitDuration`: 500ms (queue time before rejection)

### Experiment Pattern
1. Baseline: two workloads A and B hit service concurrently. Both healthy.
2. Flood workload A above `maxConcurrentCalls` while keeping workload B at normal rate.
3. Expect workload A rejections, workload B unaffected.

### Pass Criteria
| Check | Threshold |
|-------|-----------|
| Workload B error rate | ≤ baseline + 1% (isolation holds) |
| Workload B latency | ≤ baseline P99 × 1.2 (no queue starvation) |
| Workload A rejection rate | >0 and ≤100% (backpressure applied, not hung) |
| Queue depth | ≤ `maxConcurrentCalls` × 0.5 (reasonable queuing) |

### Fail Criteria
- Workload B errors increase → vulnerability: bulkhead ineffective, cascading failure
- Service hangs instead of rejecting → vulnerability: thread exhaustion, no backpressure
- Rejections happen on healthy workload first → vulnerability: unfair scheduling or config swapped
- Queue grows unbounded → vulnerability: memory pressure, eventual OOM

### Metrics to Watch
- `resilience4j_bulkhead_available_concurrent_calls`
- `resilience4j_bulkhead_calls_total{kind="rejected"}`
- Per-workload error rate and latency
- Thread pool active count vs. max

---

## 5. Latency Fault Injection

### Purpose
Verify timeout boundaries and understand tail-latency behavior under degraded
network or slow dependency conditions.

### Experiment Pattern
1. Baseline: measure normal latency distribution (P50, P95, P99).
2. Inject fixed latency (+500ms, +1000ms, +2000ms) to dependency responses.
3. Observe if upstream timeouts fire appropriately and if circuit breaker/slow-call
   threshold triggers.

### Pass Criteria
| Check | Threshold |
|-------|-----------|
| Timeout fires at boundary | Requests canceled within `timeout + 100ms` |
| Slow-call circuit opens | If `slowCallRateThreshold` exceeded, circuit opens |
| No unbounded thread growth | Active threads stable; no accumulation of hung requests |
| P99 bounded | If timeout configured, P99 ≤ `timeout + jitter_margin` |

### Fail Criteria
- No timeout applied → vulnerability: threads hang indefinitely, cascading latency
- Timeout too aggressive → vulnerability: false positives on healthy but slow dependencies
- Timeout not propagated → vulnerability: caller waits longer than downstream, resource leak
- Latency amplification (each layer adds delay) → vulnerability: no deadline propagation

### Metrics to Watch
- Request latency histogram (P50, P95, P99)
- `http_request_duration_seconds_bucket` shifts
- Thread pool active / waiting counts
- Connection pool wait time

---

## 6. Resource Exhaustion (Read-Only)

### Purpose
Validate behavior when CPU or memory pressure is elevated. **Read-only only** —
no data store corruption, no disk fill, no OOM kill of critical processes.

### Safe Patterns
- CPU pressure via `stress-ng --cpu` on non-critical sidecar or dedicated chaos pod
- Memory pressure by allocating in a controlled container with strict cgroup limit
- Verify auto-scaling triggers, degrade modes, or graceful queue shedding

### Pass Criteria
| Check | Threshold |
|-------|-----------|
| Health check stays up | `/health` returns 200 (or expected degraded code) |
| Critical path latency | ≤ 3× baseline under moderate CPU pressure |
- Queue shedding activates | If memory high, new requests rejected with 503 instead of OOM |

### Fail Criteria
- Process crashes → vulnerability: no graceful degradation under pressure
- Auto-scaling never triggers → vulnerability: static capacity assumption
- Requests accepted then dropped → vulnerability: queue grows until crash

---

## Quick Reference: Fault Type → Mechanism Mapping

| Fault Type | Primary Mechanism | Secondary |
|-----------|-------------------|-----------|
| `http_5xx` (sustained) | Circuit breaker | Fallback |
| `http_5xx` (intermittent) | Retry | Circuit breaker |
| `timeout` | Timeout boundary | Circuit breaker (slow-call) |
| `latency` (degraded) | Timeout / Bulkhead | Circuit breaker |
| `connection_drop` | Fallback | Circuit breaker |
| `resource_cpu_pressure` | Bulkhead | Auto-scaling |
| `resource_memory_pressure` | Bulkhead | Queue shedding |
| `network_partition` | Fallback | Circuit breaker |

---

## Metric Threshold Defaults

Use these as starting points; tune to service SLOs.

| Metric | Normal Baseline | During Fault (Acceptable) | Recovery Target |
|--------|-----------------|---------------------------|-----------------|
| Error rate | <0.1% | <5% with resilience active | <0.2% within 60s |
| Latency P99 | Baseline | ≤2× baseline or fallback SLO | ≤1.2× baseline |
| Retry multiplier | 1.0x | ≤2.5x | 1.0x within 30s |
| Bulkhead rejections | 0% | >0% on flooded workload only | 0% on normal workloads |
| Circuit state | CLOSED | OPEN or HALF_OPEN as expected | CLOSED within 60s |
