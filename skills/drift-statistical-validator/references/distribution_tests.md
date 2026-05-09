# Distribution Testing Procedures and Alternatives

## Overview

The drift-monitor assumes distributions for behavioral metrics. These assumptions drive the choice of outlier detection, confidence intervals, and drift thresholds. This reference provides exact test procedures, decision criteria, and fallback recommendations.

---

## Gaussian (Normal) Distribution Testing

### When to Test

Continuous metrics: latency (ms), throughput (tokens/sec), queue depth, memory usage.

### Shapiro-Wilk Test (n < 50)

**Procedure:**
1. Sort observations: x_(1) ≤ x_(2) ≤ ... ≤ x_(n)
2. Compute coefficients a_i from Shapiro-Wilk tables (or use scipy.stats.shapiro)
3. Calculate W statistic:
   ```
   W = (Σ a_i * x_(i))² / Σ (x_i - x̄)²
   ```
4. Compare against critical values or use p-value

**Decision:**
- p ≥ 0.05: Do not reject Gaussian assumption. Grubbs and parametric CIs are valid.
- p < 0.05: Reject Gaussian. Use robust alternatives.

**Limitations:**
- Sensitive to sample size: very large n may flag trivial deviations
- Ties in data (e.g., integer metrics) reduce accuracy; jitter slightly if needed

### Anderson-Darling Test (any n)

**Procedure:**
1. Compute empirical CDF F_n(x)
2. Compute theoretical Gaussian CDF Φ((x-μ)/σ) with estimated parameters
3. Calculate:
   ```
   A² = -n - (1/n) * Σ [(2i-1)ln(F_n(x_(i))) + (2(n-i)+1)ln(1-F_n(x_(i)))]
   ```
4. Adjust for estimated parameters (for μ, σ unknown, multiply by (1 + 4/n - 25/n²))

**Decision:**
- Compare against critical values: 0.576 (15%), 0.656 (10%), 0.787 (5%), 1.092 (1%)
- A² > critical at chosen level → reject Gaussian

### Visual Diagnostics (always run)

1. **Q-Q plot:** Plot sample quantiles vs. theoretical Gaussian quantiles. Systematic curvature indicates non-normality.
2. **Histogram with KDE:** Overlay fitted Gaussian. Obvious skewness or heavy tails are visible.
3. **Residual plot:** If metric is expected to be constant, plot (x_i - median); check for patterns.

### Log-Normal Alternative

If right-skewed but log-transformed values pass Gaussian test, the data are log-normal.

**Procedure:**
1. Transform: y_i = ln(x_i)  (require x_i > 0; if not, use ln(x_i - min(x) + 1))
2. Apply Shapiro-Wilk or Anderson-Darling to y_i
3. If p ≥ 0.05: use geometric mean (exp(mean(log(x)))) and log-space thresholds

**Threshold for log-normal:**
```
threshold = exp(μ_log + k * σ_log)
```

---

## Poisson Distribution Testing

### When to Test

Count metrics: errors per session, retry attempts, API call counts.

### Dispersion Index Test

**Procedure:**
1. Compute sample mean: λ̂ = x̄
2. Compute sample variance: s²
3. Calculate dispersion index: D = s² / λ̂

**Decision:**
- D ≈ 1 (0.8 to 1.2 for n=30): Consistent with Poisson
- D > 1.2: Overdispersed. Consider negative binomial or quasi-Poisson.
- D < 0.8: Underdispersed. Possible zero-inflation or rounding artifacts.

**Formal test (for large n):**
```
χ² = (n-1) * D
```
Compare to χ²_{n-1} distribution.
- p < 0.05: Reject Poisson assumption.

### Visual Diagnostics

1. **Variance vs mean plot:** For multiple groups/sessions, plot s² vs x̄. Poisson points cluster around s² = x̄ line.
2. **Probability mass function:** Compare observed counts to fitted Poisson PMF.

### Alternatives to Poisson

| Condition | Alternative | When to Use |
|-----------|-------------|-------------|
| Overdispersed (D > 1.2) | Negative binomial | Extra variance from heterogeneity |
| Many zeros | Zero-inflated Poisson | Excess zeros beyond Poisson expectation |
| Bounded counts | Binomial | Count out of fixed possible trials |
| Rare events | Exact Poisson test | n small, λ small; avoid normal approximations |

---

## Heavy-Tailed / Extreme Value Testing

### When to Test

Metrics with occasional extreme values: peak latency, max memory, worst-case throughput.

### Kolmogorov-Smirnov vs Laplace

Test if data are better modeled by Laplace (double exponential) than Gaussian:
1. Estimate Laplace parameters: μ̂ = median, b̂ = (1/n) Σ |x_i - median|
2. Compute KS statistic against Laplace CDF
3. Compare to KS against Gaussian CDF
4. Select distribution with lower KS statistic

### Generalized Extreme Value (GEV) for Maxima

If tracking session maxima, use GEV:
```
F(x; μ, σ, ξ) = exp(-(1 + ξ(x-μ)/σ)^(-1/ξ))
```

Fit via maximum likelihood; if ξ > 0, distribution has heavy tail (Fréchet type).

**Implication:** Heavy tails invalidate Grubbs (assumes finite variance); use MAD or percentile thresholds.

---

## Decision Matrix: Metric Type → Test → Alternative

```
metric_type = identify(metric)

if metric_type == "continuous_latency":
    test = Shapiro-Wilk or Anderson-Darling
    if skewed_right:
        also_test = log-normal
    if rejected:
        fallback = MAD thresholds
        ci_method = bootstrap

elif metric_type == "count_errors":
    test = dispersion_index
    if overdispersed:
        fallback = negative_binomial_thresholds
        ci_method = profile_likelihood
    if underdispersed:
        fallback = exact_binomial_or_empirical

elif metric_type == "proportion":
    test = exact_binomial_test
    if n*p < 5 or n*(1-p) < 5:
        fallback = exact_methods_no_normal_approx

elif metric_type == "extreme_value":
    test = GEV_fit
    if xi > 0:
        fallback = percentile_thresholds (P99, P99.9)
        ci_method = bootstrap
```

---

## Multi-Metric Baseline Strategy

When establishing baseline for K metrics simultaneously:

1. Test each metric's distribution independently
2. Apply Bonferroni correction if using α = 0.05/K for each test (familywise error control)
3. If ≥20% of metrics reject their assumed distribution, switch entire monitor to robust/non-parametric mode
4. Document per-metric decisions in configuration comments:
   ```yaml
   latency_ms:
     assumed_distribution: gaussian
     test_result: pass (SW W=0.97, p=0.42)
     outlier_method: grubbs
   
   error_count:
     assumed_distribution: poisson
     test_result: fail (D=2.3, overdispersed)
     outlier_method: mad
     notes: "Switched to MAD due to negative binomial behavior"
   ```

---

## Quick Reference: Test Selection by Sample Size

| n | Gaussian Test | Poisson Test | Robustness |
|---|-------------|--------------|------------|
| < 7 | Visual only; do not use Grubbs | Exact confidence intervals only | Mandatory MAD |
| 7-15 | Shapiro-Wilk | Dispersion index; visual | Prefer MAD |
| 15-50 | Shapiro-Wilk | Dispersion index + χ² | Grubbs if passes; else MAD |
| 50-100 | Anderson-Darling | χ² goodness-of-fit | Grubbs if passes |
| > 100 | Anderson-Darling + QQ | χ² + PMF overlay | Grubbs valid if passes; flag if marginally rejected |

---

## Tools

- **scipy.stats:** shapiro, anderson, kstest, normaltest, poisson (for PMF)
- **statsmodels:** qqplot, goodness-of-fit statistics
- **Manual:** Dispersion index requires only mean and variance
