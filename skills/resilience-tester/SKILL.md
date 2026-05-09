---
name: resilience-tester
description: >
  Injects controlled failures during integration tests to validate circuit breakers,
  fallbacks, retry logic, and overall system resilience. Runs exclusively in staging
  or isolated environments after functional tests pass and before production promotion.
  Triggers on: resilience review requests, pre-promotion gates, circuit breaker changes,
  retry policy updates, infrastructure drift alerts, scheduled chaos days.
---

# Resilience Tester

## What it does
Injects controlled failures into staging environments to validate that resilience
mechanisms (circuit breakers, fallbacks, retries, bulkheads) behave correctly under
stress. Produces pass/fail experiment reports with actionable recommendations.

## When to use
- Functional tests pass but system resilience is unverified
- Pre-promotion gate for services with new/changed circuit breakers or retry policies
- Post-incident validation that fixes prevent recurrence
- Scheduled chaos days or continuous resilience validation
- Infrastructure drift detected that could affect failure isolation
- New dependency added to a service mesh or API gateway

## Key capabilities
- **Chaos injection** — Simulate HTTP 5xx, timeouts, connection drops, resource
  exhaustion (CPU/memory pressure), network partitions, and degraded latency
- **Circuit breaker validation** — Verify open/close transitions under failure load
  and half-open recovery probing
- **Fallback testing** — Verify degraded-mode responses activate within SLO bounds
- **Retry logic validation** — Verify backoff strategies don't overwhelm recovering
  systems (no retry storms)
- **Latency fault injection** — Test timeout boundaries and tail-latency behavior
- **Bulkhead validation** — Verify thread pool / connection pool isolation limits
  prevent cascading failures

## Workflow

1. **Load topology** — Read application graph from `graphify` or `brownfield` to
   identify service dependencies, API endpoints, and data flow paths.
2. **Discover mechanisms** — Scan code/config for circuit breakers (`@CircuitBreaker`,
   `resilience4j`, `hystrix`, `polly`), retry policies (`@Retry`, `backoff` config),
   fallbacks (`@Fallback`, `cache` reads), and bulkheads (`@Bulkhead`, `semaphore`).
3. **Define hypothesis** — Write a falsifiable statement per experiment:
   *"When payment-service returns 503 at 100% for 60s, checkout-service circuit
   breaker opens within 10s and cached pricing fallback serves checkout within 500ms."*
4. **Select fault type** — Match failure mode to mechanism under test:
   | Mechanism | Fault Type |
   |-----------|-----------|
   | Circuit breaker | HTTP 5xx at threshold rate |
   | Fallback | Total dependency blackout |
   | Retry | Intermittent 5xx / slow responses |
   | Bulkhead | Request flood above pool limit |
   | Timeout boundary | Fixed latency injection above threshold |
5. **Verify staging isolation** — Confirm non-production environment, no production
   traffic mirrors, emergency stop endpoint reachable, rollback scripts tested.
6. **Record baseline** — Collect latency P50/P99, throughput, error rate via
   `performance-validator` before chaos. Store as "steady state" reference.
7. **Execute injection** — Run fault with defined scope (target service, affected
   endpoints, percentage of traffic, fixed duration). Start timer.
8. **Monitor behavior** — Poll metrics during injection:
   - Circuit state transitions (CLOSED → OPEN, OPEN → HALF_OPEN)
   - Fallback hit ratio and response latency
   - Retry attempt counts and inter-retry intervals
   - Bulkhead queue depth and rejection rate
   - Error rate and latency shifts vs. baseline
9. **Validate hypothesis** — Compare observed behavior to prediction. Mark PASS if
   resilience mechanisms activated within configured thresholds. Mark FAIL if:
   - Circuit breaker never opened / opened too late
   - Fallback not triggered / returned errors / exceeded latency SLO
   - Retry storm observed (spike in outgoing requests)
   - Bulkhead failed to isolate (errors leaked to other pools)
   - Latency propagated upstream without timeout cutoff
10. **Collect recovery metrics** — After fault removal, verify return to baseline
    within expected time (circuit closes, caches warm, queues drain).
11. **Generate report** — Experiment log (timestamp, fault, duration), hypothesis
    result, metric deltas, findings, recommended fixes, promotion block status.
12. **Promotion decision** — If any critical vulnerability found, set
    `BLOCK_PRODUCTION_PROMOTION = true` and alert via `ci-cd-integrator`. Feed
    DoS-related findings into `security-auditor`. Route logs to `log-analyzer` for
    post-chaos trace reconstruction.

## Safety highlights

- **NEVER** run chaos experiments in production environments. Staging or fully
  isolated environments only. Environment guard must check `ENV=STAGING` or
  `ENV=ISOLATED` and fail closed otherwise.
- **NEVER** inject failures without explicit experiment scope (target service,
  affected endpoints, traffic percentage) and duration limits (max 300s default).
- **ALWAYS** have an emergency stop mechanism. Abort experiment immediately on
  external signal, uncontrolled error rate spike (>10x baseline), or manual trigger.
- **NEVER** target critical data stores with destructive chaos. No database
  corruption, disk fill, or log partition exhaustion. Read replicas and caches only.
- **ALWAYS** notify stakeholders before starting experiments that may trigger
  staging alerts. Include experiment ID, expected symptoms, duration, and abort URL.
- **NEVER** run chaos experiments without rollback verification first. Confirm
  fault removal restores steady state within 60 seconds in a dry run.
- **ALWAYS** enforce blast radius limits: single service per experiment, bounded
  traffic percentage (start at 5%, max 50%), no cross-region faults.
- **NEVER** chain multiple fault types in the first run of a new experiment.
  Validate single-fault behavior before composing failure scenarios.
- **ALWAYS** log every injection action with immutable timestamps for audit
  and post-incident correlation.

## Integration with other skills
- **graphify / brownfield** — Reads service topology, dependency graph, and
  endpoint lists to select injection targets and avoid unintended blast radius.
- **infrastructure-as-code** — Reads staging environment manifests to verify
  isolation and identify rollback procedures.
- **ci-cd-integrator** — Resilience stage runs after `code-tester` functional
  tests pass and gates production promotion on experiment results.
- **performance-validator** — Provides baseline latency/throughput/error metrics
  and evaluates metric deltas during chaos.
- **security-auditor** — Forwards DoS-related vulnerabilities (retry storms,
  unbounded queue growth, timeout bypass) for risk scoring.
- **log-analyzer** — Routes post-chaos logs and traces for failure-mode
  reconstruction and root-cause confirmation.

## References
- `references/chaos-patterns.md` — Circuit breaker, fallback, retry, bulkhead
  validation patterns with pass/fail criteria and metric thresholds

## Scripts
- `scripts/run-chaos.py` — Template CLI for defining and running chaos experiments
  with configurable fault injection, monitoring hooks, and report generation
