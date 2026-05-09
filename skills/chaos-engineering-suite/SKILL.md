---
name: chaos-engineering-suite
description: Chaos engineering test suite that injects controlled failures (policy engine crashes, sandbox OOM, clock skew, API malformation, resource exhaustion) to validate graceful degradation and fail-closed guarantees. Use before production declaration, during staging validation, or when verifying resilience under infrastructure failures.
---

# Chaos Engineering Suite

## Overview

Production failures are cascades, race conditions, and resource exhaustion — not the attacks you tested for. This skill provides a chaos engineering test suite that injects controlled, reproducible failures into the ecosystem to validate graceful degradation, fail-closed guarantees, and recovery behavior under real-world infrastructure stress.

## When to Use

- **Before declaring the ecosystem production-ready** — run the full suite to prove degradation guarantees.
- **During staging environment validation** — validate that staging behavior matches production failure modes.
- **When validating fail-closed guarantees under real failure conditions** — ensure the system denies access rather than allowing unsafe fallbacks.
- **When testing the ecosystem's resilience to infrastructure failures** — verify survival of network partitions, OOM kills, and clock skew.
- **When updating L0 skills and verifying degradation behavior** — regression-test failure handling after core skill changes.

## Key Behaviors Validated

1. **Policy engine kill mid-transaction**: All in-flight requests must transition to `BLOCK` within the policy-engine's configured `grace_period_ms` (default 500 ms).
2. **Sandbox container OOM kill**: Sandbox executor must perform graceful cleanup, release all ephemeral tokens, and leave zero state leakage in shared storage.
3. **Clock skew between phase-controller and orchestrator**: Phase transition ordering must remain correct despite NTP skew up to ±30 seconds.
4. **Gemini API returning malformed JSON**: The post-Gemini JSON validator must catch all malformed responses, fall back to cached safe results, and never propagate poisoned payloads.
5. **Obsidian vault hitting 1 GB cap**: Atomic writes must still succeed; oldest unreferenced entries must be evicted using LRU policy.
6. **Network partition between policy-engine and sandbox-executor**: System must fail-closed (deny all requests) within the partition detection timeout (default 2 s).
7. **Resource exhaustion**: CPU starvation on policy-engine and memory pressure on phase-controller must trigger circuit-breaker open states before cascading to other components.

## Workflow Decision Tree

```
Is this a production-readiness gate?
├── Yes → Run FULL_SUITE (all 7 test categories)
│   └── Must pass 100 % to declare production-ready
└── No → Is this a targeted regression after an L0 skill update?
    ├── Yes → Run SUBSET targeting updated skill's failure domain
    └── No → Is this staging validation?
        ├── Yes → Run FULL_SUITE with reduced repetition count (1x instead of 3x)
        └── No → Run individual test category matching the failure mode
```

## Test Categories

### 1. Policy Engine Kill Mid-Transaction
**Injection**: Send SIGKILL to policy-engine container/process while in-flight requests are being evaluated.  
**Validation**: Monitor request outcomes via audit log; expect 100 % `BLOCK` for all in-flight transactions.  
**Script**: `scripts/run_chaos_test.py --category policy-kill`

### 2. Sandbox OOM Kill
**Injection**: Configure sandbox memory limit to 50 MB, then submit a task that allocates >100 MB.  
**Validation**: Sandbox container receives OOMKill from cgroup; executor logs `SANDBOX_CLEANUP_COMPLETE`; no residual files in `/tmp/sandbox-*`.  
**Script**: `scripts/run_chaos_test.py --category sandbox-oom`

### 3. Clock Skew
**Injection**: Use `libfaketime` or VM clock manipulation to offset phase-controller clock by +30 s relative to orchestrator.  
**Validation**: Submit a multi-phase workflow; verify phase transitions proceed in monotonic order (`INIT` → `VALIDATE` → `EXECUTE` → `COMPLETE`) without re-ordering or skipped states.  
**Script**: `scripts/run_chaos_test.py --category clock-skew`

### 4. Malformed API Response
**Injection**: Deploy a Gemini API mock that returns syntactically invalid JSON, JSON with wrong schema, or truncated payloads.  
**Validation**: `post-gemini-validator` rejects 100 % of malformed responses; system falls back to safe cached response or returns `422 Unprocessable Entity`. No poisoned payload reaches downstream skills.  
**Script**: `scripts/run_chaos_test.py --category malformed-api`

### 5. Vault Capacity Exhaustion
**Injection**: Pre-fill Obsidian vault to 1 GB − 10 MB, then trigger atomic writes that would exceed cap.  
**Validation**: All atomic writes succeed; oldest unreferenced entries are evicted; vault size never exceeds 1 GB; write operation latency p99 stays under 200 ms.  
**Script**: `scripts/run_chaos_test.py --category vault-capacity`

### 6. Network Partition
**Injection**: Use `iptables` or Linux network namespaces to drop all packets between policy-engine and sandbox-executor for 30 s.  
**Validation**: Before partition detection timeout (2 s), all new requests are `BLOCK`ed; after partition heals, normal operation resumes without manual intervention.  
**Script**: `scripts/run_chaos_test.py --category network-partition`

### 7. Resource Exhaustion
**Injection**: 
- **CPU starvation**: `cpulimit` policy-engine to 5 % of one core while submitting 100 concurrent policy evaluations.  
- **Memory pressure**: Spawn 1 000 phase-controller event goroutines/threads with 1 MB payloads each.  
**Validation**: Circuit breaker opens within 5 s; component enters `DEGRADED` mode; other components continue operating normally; after pressure is released, circuit breaker closes automatically within 30 s.  
**Script**: `scripts/run_chaos_test.py --category resource-exhaustion`

## Execution & Validation

### Quick Start

```bash
# Run the full production-readiness suite (3 repetitions per test)
python3 scripts/run_chaos_test.py --suite full --repeat 3

# Run a single category for targeted debugging
python3 scripts/run_chaos_test.py --category network-partition --repeat 1

# Run staging validation with reduced repetition
python3 scripts/run_chaos_test.py --suite full --repeat 1
```

### Expected Output

A successful run produces:
- `chaos_report_YYYYMMDD_HHMMSS.json` — machine-readable per-test results, latencies, and pass/fail status.
- `chaos_report_YYYYMMDD_HHMMSS.md` — human-readable summary with degradation pattern verification.

### Failure Criteria

Any of the following causes the suite to fail:
- An in-flight request is `ALLOW`ed after a policy-engine kill.
- Sandbox OOM leaves files in shared `/tmp` or does not emit `SANDBOX_CLEANUP_COMPLETE`.
- Phase transitions appear out of order or are skipped under clock skew.
- Malformed JSON reaches any downstream skill.
- Vault exceeds 1 GB at any point, or atomic write fails.
- Requests are `ALLOW`ed during a network partition.
- Circuit breaker does not open within 5 s under resource exhaustion, or does not close within 30 s after recovery.

## References

- `references/chaos_test_catalog.md` — Full test case definitions with injection scripts, parameters, and expected system reactions.
- `references/degradation_matrix.md` — Expected system behavior under each failure mode, including fallback paths and state machine transitions.

## Resources

### scripts/
- `run_chaos_test.py` — Main orchestration script. Parses CLI arguments, runs injection primitives, validates outcomes, and generates JSON + Markdown reports.

### references/
- `chaos_test_catalog.md` — Deep-dive on each chaos test: preconditions, injection steps, measurement windows, acceptance criteria.
- `degradation_matrix.md` — Cross-reference matrix of failure modes vs. system guarantees.

---

*Version: 1.0.0 | Last validated against ecosystem L0 skills v2.4+*