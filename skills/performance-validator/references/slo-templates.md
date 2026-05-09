# SLO Definition Templates

Reference templates for defining Service Level Objectives consumed by the Performance Validator skill. Each template includes required fields, example values, and guidance on selecting thresholds. All SLO validations now require **minimum 5 measurement runs** with warm-up and statistical rigor.

## Latency SLO Template

```json
{
  "slo_name": "api_latency_p95",
  "applies_to": ["GET /api/v1/users", "POST /api/v1/orders"],
  "latency_ceiling_ms": 200,
  "percentiles": {
    "p50": "should be < 50 ms",
    "p95": "must be < 200 ms",
    "p99": "must be < 500 ms"
  },
  "measurement_window": "5 minutes steady state after 1 minute warm-up",
  "enforcement": "BLOCK delivery if p95 or p99 exceeds ceiling with p < 0.05 significance",
  "statistical_requirements": {
    "min_runs": 5,
    "warm_up_runs": 3,
    "cv_threshold": 0.15,
    "confidence_level": 0.95
  }
}
```

**Guidance on ceilings:**
| Service type | p95 target | p99 target |
|---|---|---|
| User-facing synchronous API | 100–200 ms | 300–500 ms |
| Internal microservice sync call | 50–100 ms | 200 ms |
| Async worker / batch | 1–5 s | 10 s |
| Database read (cached) | 10 ms | 50 ms |
| Database read (uncached) | 50 ms | 200 ms |

## Throughput SLO Template

```json
{
  "slo_name": "api_throughput_floor",
  "applies_to": ["POST /api/v1/events"],
  "throughput_floor_rps": 1000,
  "concurrent_users": 500,
  "measurement_window": "5 minutes steady state",
  "enforcement": "WARN if below floor; BLOCK if < 80% of floor AND statistically significant (p < 0.05)",
  "statistical_requirements": {
    "min_runs": 5,
    "warm_up_runs": 3,
    "cv_threshold": 0.15,
    "confidence_level": 0.95
  }
}
```

## Error Rate / Error Budget Template

```json
{
  "slo_name": "api_error_budget",
  "applies_to": ["all endpoints"],
  "error_budget_pct": 0.1,
  "breakdown": {
    "5xx_rate": "must be < 0.05%",
    "4xx_rate": "should be < 1% (client errors are usually user-driven)",
    "timeout_rate": "must be < 0.1%",
    "dropped_rate": "must be 0%"
  },
  "measurement_window": "entire test duration excluding warm-up",
  "enforcement": "BLOCK delivery if 5xx or timeout exceeds budget with p < 0.05 significance",
  "statistical_requirements": {
    "min_runs": 5,
    "warm_up_runs": 3,
    "cv_threshold": 0.15,
    "confidence_level": 0.95
  }
}
```

**Guidance on budgets:**
| Reliability tier | Error budget | Max 5xx |
|---|---|---|
| Tier 1 (critical path) | 0.01% | 0.005% |
| Tier 2 (standard) | 0.1% | 0.05% |
| Tier 3 (internal tooling) | 1% | 0.5% |

## Resource Usage SLO Template

```json
{
  "slo_name": "resource_limits",
  "applies_to": ["service containers", "database connections"],
  "memory_rss_mb_ceiling": 512,
  "cpu_pct_ceiling": 80,
  "gc_pause_ms_ceiling": 50,
  "connection_pool_exhaustion": "must never occur",
  "measurement_window": "peak load during steady state",
  "enforcement": "WARN if > 80% of ceiling; BLOCK if ceiling breached",
  "statistical_requirements": {
    "min_runs": 5,
    "warm_up_runs": 3,
    "cv_threshold": 0.15,
    "confidence_level": 0.95
  }
}
```

## Composite SLO (Full Example)

```json
{
  "service": "order-service",
  "version": "v2.3.1",
  "environment": "staging",
  "slos": [
    {
      "category": "latency",
      "p95_ms": 200,
      "p99_ms": 500,
      "measurement": "http_req_duration after warm-up, median across 5+ runs"
    },
    {
      "category": "throughput",
      "floor_rps": 500,
      "concurrent_users": 100,
      "measurement": "http_reqs / steady_state_duration, median across 5+ runs"
    },
    {
      "category": "error_budget",
      "total_pct": 0.1,
      "5xx_pct": 0.05,
      "timeout_pct": 0.05,
      "measurement": "http_req_failed rate excluding warm-up, median across 5+ runs"
    },
    {
      "category": "resources",
      "memory_rss_mb": 512,
      "cpu_pct": 70,
      "gc_pause_ms": 30
    }
  ],
  "test_config": {
    "max_duration": "10m",
    "ramp_up": "30s",
    "warm_up": "60s",
    "warm_up_runs": 3,
    "measurement_runs": 5,
    "ramp_down": "10s",
    "isolation": "dedicated staging node",
    "cv_threshold": 0.15,
    "confidence_level": 0.95
  }
}
```

## SLO Naming Conventions

- Use `<service>-<category>-<percentile?>-<env>` format
- Examples: `order-service-latency-p95-staging`, `auth-service-error-budget-prod`
- Store SLO definitions in `docs/adr/NNNN-slo-definitions.md` or `.perf/slos.json`

## Baseline Storage

- Baselines are JSON files stored in `.kimi/perf-baselines/<service>-<env>.json`
- Baselines are per-service, per-environment, and per-release-branch
- Each baseline stores full environmental context: `date`, `commit`, `branch`, `environment`, `host`, `ci`, `tool_version`
- Baseline metrics include: `median`, `mean`, `std_dev`, `cv`, `n_runs`, `confidence_interval`
- Update baselines only after 3 consecutive PASS runs with stable metrics (CV < 5%)
- Never overwrite a baseline with a degraded run
- Auto-establish baseline on first run if none exists

## SLO Violation Escalation

| Severity | Condition | Action |
|---|---|---|
| BLOCK | p95/p99 > ceiling AND p < 0.05 OR 5xx > budget AND p < 0.05 OR resource ceiling breached | Stop delivery, require fix |
| WARN | throughput 80–100% of floor OR p50 regression > 10% OR regression detected but p ≥ 0.05 | Notify, require review |
| UNSTABLE | CV > 0.15 on any key metric OR high environmental noise detected | Re-run in isolated environment |
| INFO | p50 flat or improved with no tail regression | Log only |

## Statistical Requirements for All SLOs

| Parameter | Default | Rationale |
|---|---|---|
| `min_runs` | 5 | Central Limit Theorem; enough for t-test validity |
| `warm_up_runs` | 3 | JVM/JS JIT warm-up, connection pool priming, cache heating |
| `cv_threshold` | 0.15 | Industry standard for benchmark stability; above this = noisy |
| `confidence_level` | 0.95 | Standard for engineering confidence intervals |
| `p_value_threshold` | 0.05 | Standard for statistical significance in regression tests |
