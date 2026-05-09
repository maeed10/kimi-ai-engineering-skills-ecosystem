# Statistical Methods Reference

Deep dive on the statistical methodology used by `scripts/analyze-benchmarks.py` and `scripts/run-k6-loadtest.py` for production-grade benchmark analysis.

## 1. Warm-up Automation

### Why warm-up matters
- JVM / V8 JIT compilation introduces cold-start latency
- Connection pools, thread pools, and caches need priming
- First-run metrics can be 20–50% slower than steady state

### Auto-detection heuristic
If the first measurement run's p95 latency exceeds 1.2× the mean of subsequent runs, it is flagged as warm-up contamination and discarded. This is conservative — when `--auto-warmup` is enabled, explicit warm-up runs are executed **before** any measurement, making auto-detection a safety net.

### Configuration
- `warm_up_runs`: 3 (default) iterations executed before measurement
- `warm_up` duration inside script: 60s (default) of load at target VU count
- Warm-up results are **never** included in `runs.json`, `analysis.json`, or the report

## 2. Coefficient of Variation (CV)

### Definition
```
CV = σ / μ
```
Where σ = standard deviation across runs, μ = mean across runs.

### Interpretation
| CV range | Stability |
|---|---|
| < 0.05 | Excellent — benchmark is highly repeatable |
| 0.05 – 0.10 | Good — acceptable for CI gating |
| 0.10 – 0.15 | Fair — watch for environmental changes |
| > 0.15 | Unstable — results may be noise; more runs or isolation needed |

### Enforcement
- CV > 0.15 on any key metric (p95, p99, throughput) → flagged **UNSTABLE**
- CV > 0.15 on CPU% → possible noisy neighbor or scheduler jitter
- CV > 0.30 on GC pause times → possible heap pressure or memory contention

## 3. Welch's t-test

### Why Welch's t-test?
- Benchmark variances are rarely equal between current and baseline
- Welch's version does **not** assume equal variances, making it robust for performance data

### Formula
```
t = |μ₁ − μ₂| / √(σ₁²/n₁ + σ₂²/n₂)
```
Degrees of freedom (Welch–Satterthwaite):
```
df = (σ₁²/n₁ + σ₂²/n₂)² / [ (σ₁²/n₁)²/(n₁−1) + (σ₂²/n₂)²/(n₂−1) ]
```

### p-value approximation
The implementation uses a pragmatic piecewise approximation (no scipy required):
- t < 1.0 → p ≈ 1.0 (no difference)
- 1.0 ≤ t < 1.5 → p ≈ 0.15 (weak)
- 1.5 ≤ t < 2.0 → p ≈ 0.05 (borderline)
- 2.0 ≤ t < 2.5 → p ≈ 0.02 (significant)
- 2.5 ≤ t < 3.0 → p ≈ 0.005 (strong)
- t ≥ 3.0 → p ≈ 0.001 (very strong)

For critical decisions, users may re-run with scipy for exact p-values.

### Decision rule
- **p < 0.05** → regression/improvement is **statistically significant**
- **p ≥ 0.05** → observed delta is within noise → **false positive**, do not block delivery

## 4. Confidence Intervals

### Formula (t-distribution)
```
CI = μ ± t_crit(df, α/2) × (σ / √n)
```
Where `t_crit` is the two-tailed critical value from the t-distribution.

### Pre-computed t-critical values (95% confidence)
| df | t_crit |
|---|---|
| 1 | 12.706 |
| 4 | 2.776 |
| 5 | 2.571 |
| 10 | 2.228 |
| 20 | 2.086 |
| 30 | 2.042 |
| > 30 | ≈ 1.96 + 2.4/df |

### Interpretation
- If baseline mean falls inside current CI → likely no real change
- If baseline mean is outside current CI → likely real change (consistent with t-test)

## 5. False-Positive Filtering

### Environmental noise heuristics

1. **High CV check**
   - CV > 0.15 on p95/p99/throughput → environmental instability

2. **Outlier run detection (IQR × 1.5)**
   - Any run with metric outside [Q1 − 1.5×IQR, Q3 + 1.5×IQR] flagged
   - Outliers often indicate GC pauses, CPU throttling, or network blips

3. **CPU variance check**
   - CPU% CV > 0.20 → noisy neighbor, scheduler jitter, or container contention

4. **GC pause variance check**
   - GC pause CV > 0.30 → heap pressure, allocation spikes, or memory limits

5. **Bimodal distribution check**
   - If high cluster median > low cluster median × 1.3 → possible intermittent interference or warm-up contamination

### Action matrix
| Noise severity | Action |
|---|---|
| none | Proceed with analysis |
| medium | Log warnings; proceed with caution |
| high | Mark run INVALID; recommend re-run with CPU pinning, dedicated node, or stopped co-located workloads |

## 6. Baseline Management

### Baseline structure
```json
{
  "created_at": "2024-01-15T09:30:00+00:00",
  "source": "auto-established from first benchmark run",
  "context": {
    "date": "2024-01-15T09:30:00+00:00",
    "commit": "abc1234",
    "branch": "main",
    "environment": "staging",
    "host": "perf-node-01",
    "ci": "true",
    "tool_version": "k6 v0.47.0"
  },
  "metrics": {
    "p95": {
      "median": 120.5,
      "mean": 121.2,
      "std_dev": 3.1,
      "cv": 0.026,
      "n_runs": 5,
      "confidence_interval": [117.8, 124.6]
    }
  }
}
```

### Auto-establishment
- If `--baseline` path does not exist and `--establish-baseline` is set → create baseline automatically
- Baseline stores **median** (not mean) as the primary comparison point — medians are robust to outliers

### Trend detection
- Compare current median vs baseline median for primary metric (default: p95)
- Alert if degradation exceeds `degradation_pct` threshold (default: 10%)
- Trend alerts are **WARN** unless they also breach SLO or statistical significance

## 7. Minimum Run Counts

| Context | Minimum runs | Rationale |
|---|---|---|
| Standard CI load test | 5 | t-test needs df ≥ 4; CLT begins to apply |
| High-stakes release gate | 7–10 | Lower variance, tighter confidence intervals |
| Soak / nightly benchmark | 10–20 | Detect rare events and long-tail variance |
| Warm-up only | 3 | Sufficient for JIT/cache warm-up |

## 8. Common Pitfalls

1. **Comparing single runs** — Never claim regression after one run. Always use ≥5 runs and t-test.
2. **Ignoring warm-up** — First-run latency can be 50% higher. Always warm up and discard.
3. **Using mean instead of median** — Means are skewed by outliers. Baselines and reports use medians for robustness.
4. **Equal-variance t-test** — Welch's t-test is safer because benchmark variances differ between commits.
5. **Over-interpreting small deltas** — A 3% delta with p = 0.12 is noise, not a regression.

## References

- Welch, B. L. (1947). "The generalization of 'Student's' problem when several different population variances are involved." *Biometrika*.
- Chen et al. (2012). "Statistically Rigorous Java Performance Evaluation." *OOPSLA*.
- Błażejczyk et al. (2021). "How to Compare the Performance of Two Java Applications?" *ACM SIGPLAN*.
