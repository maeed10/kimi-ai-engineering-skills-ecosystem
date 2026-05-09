---
name: performance-validator
description: Runs load tests, benchmarks, and performance validations against defined SLOs with production-grade statistical rigor. Includes warm-up automation, variance analysis (CV), Welch's t-test for regression significance, false-positive filtering, environmental noise detection, baseline management, and confidence intervals. Feeds real metrics back into Trade-off Analyzer and Blast Radius Calculator. Trigger when validating API performance, checking benchmark regressions, enforcing latency/error-rate SLOs, or gating delivery on performance criteria.
---

# Performance Validator

## What it does
Runs load tests, benchmarks, and performance validations against defined SLOs with production-grade statistical rigor. Collects real latency percentiles, throughput, error rates, and resource usage across multiple iterations. Computes variance (CV), confidence intervals, and Welch's t-test for significance. Detects environmental noise and filters false-positive regressions. Manages baselines with full context. Feeds results into downstream skills for rescoring and impact assessment.

## When to use
- A Code Tester run has passed and the next phase is performance gating
- A new ADR or Architecture Design document defines latency/error-rate SLOs
- An API Contract Tester has validated endpoints and performance must be verified
- A Trade-off Analyzer needs real Performance-dimension data instead of estimates
- A Blast Radius Calculator needs to assess the impact of a performance change
- CI/CD pipeline needs a go/no-go decision based on benchmark regression
- User explicitly requests load testing, stress testing, or SLO validation
- Benchmark results show variance and need statistical analysis before claiming regression

## Key capabilities
1. **Load testing** — Run k6 (JS/TS projects), Locust (Python), JMeter, or `go test -bench`
2. **Benchmark regression** — Compare current benchmarks against historical baselines with Welch's t-test (p < 0.05)
3. **SLO validation** — Validate latency percentiles (p50, p95, p99), throughput, error rate against thresholds using **median across ≥5 runs**
4. **Resource profiling** — Memory usage, CPU utilization, connection pool exhaustion, GC pause times
5. **Integration testing** — Performance under concurrent load for API endpoints
6. **Warm-up automation** — Auto-detect cold systems; run configurable warm-up iterations before recording; discard warm-up from final report
7. **Variance analysis** — Compute coefficient of variation (CV) across runs; flag CV > 0.15 as unstable
8. **Statistical significance testing** — Welch's t-test for unequal variances; report p-values; flag regressions within noise as false positives
9. **Confidence intervals** — 95% CI for latency percentiles and throughput means
10. **False-positive filtering** — Detect environmental noise (CPU throttling, GC pauses, noisy neighbors, bimodal distributions); flag potentially invalid runs
11. **Baseline management** — Store baselines in `.kimi/perf-baselines/` with full context (date, commit, branch, env, host, CI); auto-establish on first run; detect gradual degradation trends
12. **Trend detection** — Alert on gradual degradation over time against stored baseline

## Workflow

### 1. Discover test targets
- Read API endpoints from **Brownfield Intelligence** or **API Contract Tester** output
- Read function signatures from **Blast Radius Calculator** critical-path output
- Read SLO definitions from **Architecture Design** ADRs or `references/slo-templates.md`
- Determine environment: staging, isolated perf-env, or local with profiling

### 2. Select load testing tool
| Project type | Default tool | Override |
|---|---|---|
| JS/TS Node.js | k6 | `--tool=locust` |
| Python | Locust | `--tool=k6` |
| Java | JMeter | `--tool=k6` |
| Go | `go test -bench` + k6 for HTTP | `--tool=locust` |

If the user specifies a tool, honor it. If the project has existing load-test scripts, reuse and extend them.

### 3. Generate or reuse load test scripts
- If OpenAPI spec exists → generate k6 script with `run-k6-loadtest.py`
- If endpoint catalog exists → map endpoints to test scenarios (read, write, mixed)
- If benchmark functions exist → wrap in `go test -bench` with `-count=5` for statistical stability
- Always include: ramp-up, steady state, ramp-down, and warm-up phase

### 4. Establish baseline
- Check for existing baseline in `.kimi/perf-baselines/<service>-<env>.json`
- Baseline stores **full environmental context**: date, commit SHA, branch, environment, hostname, CI flag, tool version
- If no baseline exists: run 3 warm-up iterations, then 5 measurement runs, store aggregated baseline with medians, means, std dev, CV, and confidence intervals
- Baseline MUST be established before any "improved" or "degraded" claim
- Never overwrite a baseline with a degraded run

### 5. Execute load test with warm-up automation
- **Cold system detection**: If `--auto-warmup` is set, the runner detects cold systems and executes warm-up iterations before measurement
- **Warm-up iterations**: Default 3 warm-up runs executed before the measurement phase; warm-up results are **discarded** and never enter the report
- **Configuration bounds** (ALWAYS enforce):
  - Minimum measurement runs: **5** (required for statistical validity)
  - Max duration: 10 minutes per run for standard load, 30 minutes for soak test
  - Max requests: define `VU * iterations` ceiling
  - Ramp-up: at least 30 seconds
  - Warm-up inside script: at least 1 minute before recording metrics
- Isolation: run on dedicated staging node or container with no other tests

### 6. Collect metrics across all runs
- Latency: p50, p95, p99, max (median + 95% CI across runs)
- Throughput: requests/second (median + CI)
- Error rate: 4xx%, 5xx%, timeout%, dropped% (median + CI)
- Resource usage: CPU%, memory RSS, goroutine count, open connections, GC pause times
- Saturation: connection pool exhaustion, thread pool queue depth, disk I/O wait
- Per-run JSON summaries saved to `summary-run-{N}.json`; aggregated to `runs.json`

### 7. Variance analysis
- Compute **coefficient of variation (CV)** = std_dev / mean for each metric across runs
- If **CV > 0.15** → flag metric as **UNSTABLE**; report warns that more runs or better isolation is needed
- Minimum 5 runs enforced; reject analysis if fewer provided

### 8. Statistical significance testing (Welch's t-test)
- Compare current vs baseline using **Welch's t-test** (handles unequal variances)
- **p < 0.05** = statistically significant difference
- Regressions with **p ≥ 0.05** are flagged as **false positives** ("regression within noise") and do NOT block delivery
- Report confidence intervals for all latency percentiles and throughput

### 9. False-positive filtering / environmental noise detection
- Detect signs of environmental interference:
  - High CV (>0.15) on p95/p99/throughput
  - Outlier runs via IQR×1.5 rule (possible GC pause or CPU throttling)
  - High CPU variance (CV > 0.20) → noisy neighbor or scheduler jitter
  - High GC pause variance (CV > 0.30) → heap pressure
  - Bimodal latency distributions → warm-up contamination or intermittent interference
- Flag runs with anomalous variance as **"potentially invalid"**
- Suggest re-run in isolated environment (CPU pinning, dedicated node, stop co-located workloads)

### 10. Trend detection
- Compare current median vs baseline median for configured primary metric (default p95)
- Alert if gradual degradation exceeds threshold (default 10%) over time
- Trend alerts are **WARN** unless they also breach SLO ceilings or statistical significance

### 11. Compare against SLOs and baseline
| Metric | SLO violation rule | Regression rule |
|---|---|---|
| p50 latency | > SLO ceiling | > baseline + 10% |
| p95 latency | > SLO ceiling | > baseline + 5% AND p < 0.05 |
| p99 latency | > SLO ceiling | > baseline + 5% AND p < 0.05 |
| Error rate | > SLO budget | > baseline + 0.1% AND p < 0.05 |
| Throughput | < SLO floor | < baseline - 10% AND p < 0.05 |
| Memory RSS | > SLO ceiling | > baseline + 20% |

- NEVER ignore p95/p99 latency regressions even if p50 improves
- A single p99 regression is a blocking failure **only if statistically significant (p < 0.05)**
- Regressions that are not statistically significant are logged as noise, not blockers

### 12. Generate report
```
Performance Validation Report — <commit-sha>
Environment: <staging|perf-env|local>
Runs: <N> measurement runs | Warm-up runs: <W> (discarded)

SLO Compliance (median with 95% CI):
  p95 latency: <value> ms  [PASS/FAIL]  SLO: <ceiling> ms  CI: [<low>, <high>]
  p99 latency: <value> ms  [PASS/FAIL]  SLO: <ceiling> ms  CI: [<low>, <high>]
  error rate:  <value> %   [PASS/FAIL]  SLO: <budget> %     CI: [<low>, <high>]
  throughput:  <value> rps [PASS/FAIL]  SLO: <floor> rps    CI: [<low>, <high>]

Variance Analysis:
  p95 CV: <value>  [stable / UNSTABLE]
  p99 CV: <value>  [stable / UNSTABLE]
  throughput CV: <value>  [stable / UNSTABLE]

Regression vs Baseline (Welch's t-test):
  p95: <value> ms  [improved/degraded/flat]  baseline: <base> ms  (±X%, p=<p>)
  p99: <value> ms  [improved/degraded/flat]  baseline: <base> ms  (±X%, p=<p>)
  error rate: <value>% [improved/degraded/flat] baseline: <base>% (±X%, p=<p>)

False-Positive Filtering:
  - <metric>: Δ+X% (p=0.XX) — regression within noise, NOT statistically significant

Environmental Noise:
  Severity: <none/medium/high>
  Alerts:
    - <alert 1>
    - <alert 2>

Trend Detection:
  - p95: <degradation_pct>% vs baseline (threshold: 10%) [ALERT/OK]

Verdict: [PASS / BLOCK / UNSTABLE / INVALID]
```

### 13. Gate delivery
- If any SLO violated → BLOCK delivery, attach bottleneck analysis
- If any p95/p99 regression > 5% **with p < 0.05** → BLOCK delivery, attach diff and profile
- If regression > 5% but **p ≥ 0.05** → WARN, do NOT block (false positive within noise)
- If throughput regression > 10% **with p < 0.05** → BLOCK
- If high environmental noise detected (CV > 0.15, outlier runs) → INVALID, require re-run in isolated environment
- If unstable metrics (high variance) → UNSTABLE, recommend increasing run count or isolating environment
- If all metrics pass and stable → PASS, emit metrics to downstream skills

### 14. Feed metrics to downstream skills
- Send structured results to **Trade-off Analyzer** for Performance-dimension rescoring
- Send regression diff to **Blast Radius Calculator** for impact assessment of perf changes
- If BLOCK → trigger **CI/CD Integrator** with `perf-gate-failed` label and bottleneck report
- If PASS → trigger **CI/CD Integrator** with `perf-gate-passed` label and metric summary
- If UNSTABLE/INVALID → trigger **CI/CD Integrator** with `perf-gate-invalid` label and noise report

## Safety highlights

- **NEVER** run load tests against production environments — staging or isolated performance environments only
- **NEVER** ignore p95/p99 latency regressions even if p50 improves
- **NEVER** run unbounded load tests — define max duration and request limits upfront
- **NEVER** report a "regression" without statistical significance test (p < 0.05)
- **NEVER** use a single test run as basis for SLO pass/fail decision — minimum 5 measurement runs required
- **ALWAYS** establish baseline before comparing "improved" or "degraded"
- **ALWAYS** warm up the system for at least 1 minute before recording metrics
- **ALWAYS** run warm-up iterations before recording on cold systems (3 warm-up runs default, discarded from report)
- **ALWAYS** isolate performance tests from other test runs to prevent interference
- **ALWAYS** include ramp-up and ramp-down phases to avoid cold-start and shock effects
- **ALWAYS** retry a failed perf test once before declaring BLOCK — transient infra issues are common
- **ALWAYS** store baseline with full environmental context (date, commit, branch, env, host)
- **ALWAYS** flag results with CV > 0.15 as unstable and suggest more runs or better isolation

## Integration with other skills

| Skill | Direction | Data |
|---|---|---|
| **Brownfield Intelligence** | Reads | API endpoints, service topology, known bottlenecks |
| **API Contract Tester** | Reads | Validated endpoint list, request/response schemas |
| **Architecture Design** | Reads | ADR-defined SLOs, latency ceilings, error budgets |
| **Blast Radius Calculator** | Reads | Critical-path functions; Writes | Perf regression impact |
| **Trade-off Analyzer** | Writes | Real p95/p99/throughput/error-rate metrics with CI and p-values for Performance rescoring |
| **CI/CD Integrator** | Writes | `perf-gate-passed`, `perf-gate-failed`, or `perf-gate-invalid` with report |
| **Code Tester** | Triggered by | Runs after unit/integration tests pass |
| **Resilience Tester** | Coordinates with | Performance under failure modes (chaos + load) |

## References

- `references/slo-templates.md` — SLO definition templates for latency, throughput, error rate, and resource usage
- `references/statistical-methods.md` — Deep dive on Welch's t-test, CV, confidence intervals, and noise detection heuristics

## Scripts

- `scripts/run-k6-loadtest.py` — Python template for generating k6 scripts from OpenAPI specs or endpoint catalogs, executing **multiple measurement runs** with warm-up automation, variance analysis, and baseline management
- `scripts/analyze-benchmarks.py` — Standalone statistical analysis of benchmark results: Welch's t-test, CV computation, confidence intervals, environmental noise detection, false-positive filtering, trend detection, and baseline management in `.kimi/perf-baselines/`
