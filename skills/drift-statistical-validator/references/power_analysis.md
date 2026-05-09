# Power Analysis Formulas and Sample Size Tables

## Overview

Power analysis ensures the burn-in period is long enough to reliably detect meaningful drift. This reference provides formulas, pre-computed tables, and effect-size guidance for drift-monitor baseline design.

---

## Key Parameters

| Symbol | Name | Typical Value | Description |
|--------|------|---------------|-------------|
| α | Significance level | 0.05 | Probability of false positive (Type I error) |
| β | Type II error rate | 0.20 | Probability of false negative |
| 1-β | Power | 0.80 | Probability of detecting true drift |
| δ | Minimum detectable effect (MDE) | Problem-specific | Smallest drift magnitude that must be caught |
| σ | Baseline standard deviation | Estimated from burn-in | Natural variability of metric |
| d | Cohen's d | δ/σ | Standardized effect size |
| p₀ | Baseline proportion | Estimated | For count/proportion metrics |
| p₁ | Drifted proportion | p₀ + δ | Alternative proportion |

**Standard normal critical values:**
- Z_{1-α/2} = 1.96 (two-tailed, α=0.05)
- Z_{1-β} = 0.84 (power=0.80)
- Z_{1-α} = 1.645 (one-tailed, α=0.05)

---

## Formula 1: Mean Shift in Gaussian Data (Z-Test)

Use when population σ is known or n > 30 with stable sample variance.

```
n = ((Z_{1-α/2} + Z_{1-β}) * σ / δ)²
```

**Example:**
- Latency baseline: μ = 200ms, σ = 30ms
- Must detect shift of δ = 15ms (7.5% increase)
- n = ((1.96 + 0.84) * 30 / 15)² = (2.8 * 2)² = 31.4 → **32 sessions**

---

## Formula 2: Mean Shift in Gaussian Data (T-Test)

Use when σ is estimated from same sample; more conservative.

```
n ≈ ((t_{α/2, n-1} + t_{β, n-1}) * s / δ)²
```

Solved iteratively since t depends on n. For large n (>30), converges to z-test result.

**Conservative approximation:**
```
n = ((1.96 + 0.84) * s / δ)² + 2   # +2 accounts for t vs z
```

---

## Formula 3: Proportion Drift (Two-Proportion Z-Test)

For binary outcomes: error rate, success rate, feature flags.

```
n = [Z_{1-α/2} * sqrt(2*p*(1-p)) + Z_{1-β} * sqrt(p0*(1-p0) + p1*(1-p1))]² / (p0 - p1)²
```

Where p = (p0 + p1)/2 (pooled proportion under null).

**Example:**
- Baseline error rate: p₀ = 0.05
- Must detect increase to p₁ = 0.10 (doubling)
- p = 0.075
- n = [1.96 * sqrt(2*0.075*0.925) + 0.84 * sqrt(0.05*0.95 + 0.10*0.90)]² / (0.05)²
- n = [1.96 * 0.372 + 0.84 * 0.377]² / 0.0025
- n = [0.729 + 0.317]² / 0.0025 = 1.095² / 0.0025 = 480 → **480 sessions**

**Note:** Proportions near 0 or 1 require much larger n. Consider exact binomial methods or arcsine transformation.

---

## Formula 4: Variance Shift (Chi-Square Test)

Detect when variability increases (e.g., latency becomes erratic).

```
n = 1 + (Z_{1-α/2} * sqrt(2) + Z_{1-β} * sqrt( (σ1²/σ0²)² + 1 ))² / (2 * (σ1²/σ0² - 1)²)
```

**Example:**
- Baseline σ₀ = 10ms; must detect increase to σ₁ = 15ms (50% variance increase)
- Ratio = 2.25
- n = 1 + (1.96*1.414 + 0.84*sqrt(5.0625+1))² / (2*1.25²)
- n = 1 + (2.772 + 2.163)² / 3.125 = 1 + 24.36 / 3.125 = 8.8 → **9 sessions**

*Variance shifts are easier to detect than mean shifts at small n.*

---

## Formula 5: Non-Inferiority / Equivalence

If goal is to ensure metric stays within bounds (not just detect change):

```
n = ((Z_{1-α} + Z_{1-β}) * σ / δ)²
```

Use one-tailed Z_{1-α} = 1.645. Smaller n required than two-tailed.

---

## Pre-Computed Sample Size Tables

### Table A: Mean Shift Detection (Gaussian, α=0.05, power=0.80)

| Cohen's d (δ/σ) | n (z-test) | n (t-test, approx) | Interpretation |
|-----------------|------------|-------------------|----------------|
| 0.10 (tiny) | 1571 | 1573 | Detect 10% of σ shift |
| 0.20 (small) | 393 | 395 | Detect 20% of σ shift |
| 0.30 (small-med) | 175 | 177 | Detect 30% of σ shift |
| 0.50 (medium) | 63 | 65 | Detect ½ σ shift |
| 0.80 (large) | 25 | 27 | Detect 4/5 σ shift |
| 1.00 (large) | 16 | 18 | Detect 1 σ shift |
| 1.50 (very large) | 8 | 10 | Detect 1.5 σ shift |
| 2.00 (huge) | 5 | 7 | Detect 2 σ shift |

**Interpretation for drift-monitor:**
- d = 0.2–0.3: Typical for subtle degradation (latency creep)
- d = 0.5: Meaningful performance regression
- d = 0.8+: Critical failure mode; should alert immediately if suspected

### Table B: Proportion Drift (α=0.05, power=0.80)

| Baseline p₀ | Detect p₁ = 2*p₀ | Detect p₁ = 1.5*p₀ | Detect p₁ = p₀+0.05 |
|-------------|------------------|--------------------|---------------------|
| 0.01 | 4744 | 17340 | 1096 |
| 0.02 | 2314 | 8300 | 2055 |
| 0.05 | 942 | 3277 | 4744 |
| 0.10 | 474 | 1603 | 8645 |
| 0.20 | 199 | 688 | 1386 |
| 0.30 | 107 | 374 | 783 |

**Note:** Values computed with two-tailed test and pooled proportion. For rare events (p₀ < 0.01), use exact Poisson power formulas or simulation.

### Table C: Minimum Sessions for Target Precision (CI on Mean)

Desired condition: 95% CI width ≤ W (absolute) or ≤ r*μ (relative).

```
n = (2 * Z_{1-α/2} * σ / W)²
or
n = (2 * Z_{1-α/2} * CV / r)²
```

Where CV = σ/μ (coefficient of variation).

| CV | CI width = 10% of mean | CI width = 20% of mean | CI width = 30% of mean |
|----|------------------------|------------------------|------------------------|
| 0.05 | 4 | 2 | 1 |
| 0.10 | 16 | 4 | 2 |
| 0.20 | 62 | 16 | 7 |
| 0.30 | 139 | 35 | 16 |
| 0.50 | 385 | 97 | 43 |

---

## Effect Size Guidance for Drift Metrics

### What is "Meaningful" Drift?

The MDE (minimum detectable effect) should be set by operational impact, not statistical convenience.

| Metric | Typical σ | Small MDE | Medium MDE | Large MDE |
|--------|-----------|-----------|------------|-----------|
| Latency (ms) | 50 | 10ms (20%) | 25ms (50%) | 50ms (100%) |
| Throughput (tok/s) | 20 | 5 (25%) | 10 (50%) | 20 (100%) |
| Error rate (%) | 2% abs | +1pp | +2pp | +4pp |
| Memory (MB) | 100 | 20MB | 50MB | 100MB |
| Queue depth | 5 | 2 | 3 | 5 |

**Setting MDE:**
1. Identify SLA threshold for metric
2. Set MDE = (SLA - baseline) / 2  (detect trouble halfway to breach)
3. Round to conservative (smaller) value if SLA is strict
4. If resulting n > operational burn-in limit, negotiate SLA or accept lower power

---

## Retrospective Power Analysis (Post-Hoc)

After an alert or missed drift, compute achieved power:

```
Power = Φ( (δ / (σ/sqrt(n))) - Z_{1-α/2} )
```

**Use cases:**
- "Why did we miss the latency spike?" → Achieved power was only 0.45 at that effect size.
- "Was this alert real or noise?" → p = 0.03 with power = 0.95 is convincing; p = 0.04 with power = 0.40 is marginal.

---

## Simulation-Based Power (When Formulas Fail)

For non-Gaussian data, composite metrics, or complex thresholds, use simulation:

```python
# Pseudocode
power_estimates = []
for delta in candidate_deltas:
    detections = 0
    for sim in range(10000):
        baseline = sample_from_baseline_model(n_burnin)
        new_data = sample_from_drifted_model(n_new, delta)
        threshold = compute_threshold(baseline)
        if drift_detected(new_data, threshold):
            detections += 1
    power_estimates.append(detections / 10000)
```

**When to simulate:**
- Robust thresholds (MAD, IQR) with non-Gaussian data
- Sequential/CUSUM detection rules
- Multi-variate drift detection
- Percentile-based thresholds (P99)

---

## Power Analysis Integration with Burn-in Design

```
for each metric:
    estimate σ from pilot data (10-15 sessions minimum)
    set δ from operational SLA
    compute required_n
    
    if required_n <= 30:
        burn_in = 30  (absolute minimum for CLT and outlier detection)
    elif required_n <= 60:
        burn_in = required_n (rounded to multiple of 5)
    else:
        raise "Metric requires excessive burn-in"
        options:
          - Increase δ (accept larger undetectable drift)
          - Decrease α (more false positives, fewer sessions)
          - Accept lower power (document as 0.70)
          - Switch to sequential detection (no fixed burn-in)
```

---

## Formulas in Python

```python
import math
from scipy import stats

def n_for_mean_shift(delta, sigma, alpha=0.05, power=0.80, two_tailed=True):
    """Minimum n for detecting mean shift in Gaussian data."""
    z_alpha = stats.norm.ppf(1 - alpha/2) if two_tailed else stats.norm.ppf(1 - alpha)
    z_beta = stats.norm.ppf(power)
    return math.ceil(((z_alpha + z_beta) * sigma / delta) ** 2)

def n_for_proportion(p0, p1, alpha=0.05, power=0.80, two_tailed=True):
    """Minimum n per group for detecting proportion shift."""
    p = (p0 + p1) / 2
    z_alpha = stats.norm.ppf(1 - alpha/2) if two_tailed else stats.norm.ppf(1 - alpha)
    z_beta = stats.norm.ppf(power)
    num = z_alpha * math.sqrt(2 * p * (1 - p)) + z_beta * math.sqrt(p0*(1-p0) + p1*(1-p1))
    return math.ceil((num / (p0 - p1)) ** 2)

def n_for_precision(cv, relative_width, alpha=0.05):
    """Minimum n for CI on mean with target relative width."""
    z = stats.norm.ppf(1 - alpha/2)
    return math.ceil((2 * z * cv / relative_width) ** 2)
```
