---
name: drift-statistical-validator
description: Statistical validation skill for drift-monitor baseline establishment. Use when configuring anomaly detection parameters, determining burn-in periods, or peer-reviewing drift methodology. Validates distributional assumptions, computes power analysis, verifies burn-in sufficiency, and provides non-parametric fallbacks.
---

# Drift Statistical Validator

## Context

**Production Readiness Finding:** PR-8 — Drift monitor burn-in statistically questionable

The `drift-monitor` component establishes anomaly detection thresholds during a 30-session "burn-in" baseline period. This skill validates whether that baseline period, the Grubbs outlier rejection, and the variance thresholds have proper statistical grounding. It answers: *Is our anomaly detection actually detecting anomalies, or just noise?*

## When to Use

- Configuring `drift-monitor` baseline parameters for new deployments
- Determining appropriate burn-in period length for new workload patterns
- Responding to peer review challenges on statistical validity of anomaly thresholds
- Adapting drift detection methodology to different agent behavioral metrics
- Investigating false-positive or false-negative drift alerts

## Workflow

### 1. Inspect Current Baseline Configuration

Gather the current statistical parameters:

```yaml
# Typical drift-monitor baseline configuration
burn_in_sessions: 30
outlier_method: grubbs
outlier_alpha: 0.05
variance_threshold: 2.5  # standard deviations
minimum_sessions: 15    # absolute floor before threshold calculation
```

Flag immediately if:
- `burn_in_sessions` < 20 (insufficient for CLT approximations)
- `outlier_alpha` > 0.10 (excessive rejection rate for small samples)
- No `minimum_sessions` floor exists (risk of thresholds computed from <10 samples)

### 2. Distribution Testing

Test whether agent behavioral metrics follow assumed distributions. The drift-monitor typically assumes Gaussian behavior for continuous metrics (latency, token count) and Poisson for count metrics (errors, retries).

**Required tests per metric:**

| Metric Type | Assumed Distribution | Required Test |
|-------------|---------------------|---------------|
| Latency, throughput | Gaussian | Shapiro-Wilk (n < 50) or Anderson-Darling |
| Error counts, retries | Poisson | Dispersion index (variance/mean ratio) |
| Queue depth, memory | Log-normal | Shapiro-Wilk on log-transformed values |
| Binary outcomes | Bernoulli/Binomial | Exact binomial test on proportions |

**Decision logic:**

```
if p_value < 0.05:
    distribution = NONPARAMETRIC
    recommend_mad = True
    grubbs_valid = FALSE
else:
    distribution = ASSUMED
    grubbs_valid = TRUE
```

See `references/distribution_tests.md` for detailed procedures.

### 3. Power Analysis

Compute minimum sample size needed to detect meaningful drift at specified power (0.8) and alpha (0.05).

**For mean-shift detection (Gaussian):**

```
n = ((Z_(1-α/2) + Z_(1-β)) * σ / δ)^2
```

Where:
- `δ` = minimum detectable effect size (meaningful drift magnitude)
- `σ` = baseline standard deviation
- `Z_(1-α/2)` = 1.96 (two-tailed, α=0.05)
- `Z_(1-β)` = 0.84 (power=0.8)

**For proportion drift (Bernoulli):**

```
n = (Z_(1-α/2) * sqrt(2*p*(1-p)) + Z_(1-β) * sqrt(p1*(1-p1) + p2*(1-p2)))^2 / (p1 - p2)^2
```

**Validation rule:**

```
if power_analysis_n > configured_burn_in:
    RAISE: "Burn-in period insufficient for target power"
    suggest_burn_in = power_analysis_n (rounded up to multiple of 5)
```

See `references/power_analysis.md` for pre-computed tables and effect-size guidance.

### 4. Burn-in Period Validation

Verify the burn-in period captures sufficient variance and is stationary.

**Stationarity checks:**
1. **Visual inspection:** Plot metric over burn-in sessions; flag trends, cycles, or step changes
2. **Augmented Dickey-Fuller (ADF):** p < 0.05 rejects unit root (series is stationary)
3. **Runs test:** Count runs above/below median; too few runs suggests trend

**Variance sufficiency:**
1. Compute coefficient of variation: `CV = σ / μ`
2. If `CV < 0.05`, metric may be too stable to detect meaningful drift; flag for review
3. Check if range spans at least 3 instrument precision units

**Minimum viable burn-in:**

```
actual_burn_in >= max(30, power_analysis_n, 5 / p_outlier_expected)
```

Where `p_outlier_expected` is the expected outlier rate under the assumed distribution.

**Non-stationary handling:**
- If trend detected: require difference-statistics or rolling baseline
- If seasonal: require seasonal decomposition or extend burn-in to cover full cycle
- If regime shift: discard pre-shift data; restart burn-in

### 5. Outlier Method Validation

Validate Grubbs test assumptions; suggest alternatives when violated.

**Grubbs test requirements:**
1. Data are approximately Gaussian (see Distribution Testing)
2. Single outlier expected (or iterative application with Bonferroni correction)
3. Sample size n >= 7 (test has low power below this)

**Grubbs critical value:**

```
G_crit = (n-1) / sqrt(n) * sqrt(t²_{α/(2n), n-2} / (n-2 + t²_{α/(2n), n-2}))
```

Where `t` is the critical value from Student's t-distribution.

**Decision matrix:**

| Condition | Grubbs Valid | Recommended Alternative |
|-----------|-------------|------------------------|
| Gaussian, n >= 7, single outlier | Yes | Grubbs (standard) |
| Gaussian, n >= 7, multiple outliers | Partial | Grubbs iterative + Bonferroni, or generalized ESD |
| Non-Gaussian, symmetric | No | MAD (Median Absolute Deviation): reject if `\|x - median\| / MAD > 3.5` |
| Non-Gaussian, skewed | No | IQR method: reject if `x > Q3 + 1.5*IQR` or `x < Q1 - 1.5*IQR` |
| Small sample (n < 7) | No | No rejection; collect more data or use robust estimators |
| Heavy-tailed | No | Modified Z-score with MAD |

### 6. Confidence Intervals on Thresholds

Report confidence intervals on baseline means and anomaly thresholds.

**CI on mean:**

```
CI_μ = x̄ ± t_{α/2, n-1} * (s / sqrt(n))
```

**CI on standard deviation (Gaussian):**

```
CI_σ = (sqrt((n-1)*s² / χ²_{α/2, n-1}), sqrt((n-1)*s² / χ²_{1-α/2, n-1}))
```

**Threshold uncertainty:**

The anomaly threshold `T = μ + k*σ` has propagated uncertainty:

```
σ_T ≈ sqrt( (σ_μ)² + (k*σ_σ)² )
```

**Flagging rule:**

```
if (CI_width_μ / μ > 0.20) or (CI_width_σ / σ > 0.30):
    RAISE: "Threshold confidence intervals exceed acceptable precision"
    recommend_action = "Extend burn-in period or increase minimum_sessions"
```

### 7. Non-Parametric Fallbacks

When distributional assumptions fail, switch to rank-based or robust methods.

**Robust baseline estimators:**

| Parameter | Classical | Robust Fallback |
|-----------|-----------|-----------------|
| Central tendency | Mean | Median, trimmed mean (trim=0.1) |
| Spread | Standard deviation | MAD, IQR/1.35, Qn estimator |
| Threshold | μ + 2.5σ | Median + 3.5*MAD, or percentile-based (P99) |

**Rank-based drift detection:**

Instead of z-scores, use:
1. **Mann-Whitney U-test:** Compare new session distribution against baseline
2. **Kolmogorov-Smirnov:** Test for any distributional shift
3. **CUSUM on ranks:** Sequential rank-based cumulative sum for online detection

**Bootstrap confidence intervals:**

When parametric CIs are invalid:
1. Resample baseline data with replacement (B >= 1000)
2. Compute statistic (median, MAD, threshold) per resample
3. Report percentile bootstrap CI: [2.5th percentile, 97.5th percentile]

## Tooling

### Quick Validation

Run the validation script against baseline data:

```bash
python scripts/validate_baseline.py \
  --baseline-data baseline_sessions.csv \
  --metric latency_ms \
  --burn-in 30 \
  --alpha 0.05 \
  --power 0.8 \
  --mde 0.3
```

The script outputs:
- Distribution test results with p-values
- Power analysis: minimum n for target MDE
- Stationarity test (ADF)
- Grubbs validity assessment
- Recommended threshold with confidence intervals
- Non-parametric fallback thresholds if assumptions fail

### Integration Points

- **Input:** Session-level metric CSVs, current `drift-monitor` YAML config
- **Output:** Validated config fragment, statistical justification paragraph for PR review, flags for assumption violations

## Common Pitfalls

1. **Assuming 30 sessions is always enough:** For high-variance metrics or small effect sizes, 30 sessions may yield <0.5 power. Always compute.
2. **Applying Grubbs to count data:** Poisson errors are right-skewed; Grubbs rejects valid high-count sessions as outliers. Use MAD or IQR.
3. **Ignoring burn-in non-stationarity:** If agent behavior changes during burn-in (e.g., warming caches), the baseline is contaminated. Test stationarity before computing thresholds.
4. **Single threshold for all metrics:** Latency and error rates have different distributions and should have different outlier methods and burn-in requirements.
5. **Not reporting CI width:** A threshold with ±50% CI width is not a threshold; it's a guess. Extend burn-in until CIs tighten.

## Decision Summary

```
START: Inspect burn-in configuration
  |
  +-- Distribution test fails? --> Use MAD/IQR robust thresholds
  |                                Use bootstrap CIs
  |                                Use Mann-Whitney for drift detection
  |
  +-- Power analysis says n > 30? --> Extend burn-in to recommended n
  |                                   Flag in PR review
  |
  +-- Burn-in non-stationary? --> De-trend or restart burn-in
  |                                Do not compute thresholds on non-stationary data
  |
  +-- Grubbs invalid? --> Switch to MAD (symmetric) or IQR (skewed)
  |                       Document alternative in config comments
  |
  +-- CI width too large? --> Extend burn-in or increase session frequency
  |
  +-- All clear? --> Report validated thresholds with CIs
                     Document distributional assumptions
                     Attach statistical justification to PR
```
