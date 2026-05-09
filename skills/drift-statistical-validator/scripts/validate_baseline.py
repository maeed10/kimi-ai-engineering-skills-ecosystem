#!/usr/bin/env python3
"""
validate_baseline.py

Statistical validation script for drift-monitor baseline establishment.

Validates:
- Distributional assumptions (Gaussian, Poisson, log-normal)
- Power analysis: minimum sample size for target MDE
- Burn-in stationarity (ADF test, runs test)
- Grubbs outlier method assumptions
- Confidence intervals on thresholds
- Non-parametric fallback thresholds (MAD, IQR, percentiles)

Usage:
    python validate_baseline.py \
        --baseline-data baseline_sessions.csv \
        --metric latency_ms \
        --burn-in 30 \
        --alpha 0.05 \
        --power 0.8 \
        --mde 0.3

Output:
    JSON or formatted text report with validation results and recommendations.
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate statistical rigor of drift-monitor baseline data."
    )
    parser.add_argument(
        "--baseline-data", required=True, help="Path to CSV with baseline sessions (rows=sessions, cols=metrics)."
    )
    parser.add_argument(
        "--metric", required=True, help="Column name of the metric to validate."
    )
    parser.add_argument(
        "--burn-in", type=int, default=30, help="Configured burn-in period length (sessions)."
    )
    parser.add_argument(
        "--alpha", type=float, default=0.05, help="Significance level for tests (default 0.05)."
    )
    parser.add_argument(
        "--power", type=float, default=0.80, help="Target statistical power (default 0.80)."
    )
    parser.add_argument(
        "--mde", type=float, default=None,
        help="Minimum detectable effect size (absolute, in metric units). If None, uses 0.5*std."
    )
    parser.add_argument(
        "--threshold-sigma", type=float, default=2.5,
        help="Anomaly threshold in standard deviations above mean (default 2.5)."
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON path. If omitted, prints formatted text to stdout."
    )
    parser.add_argument(
        "--log-transform", action="store_true",
        help="Test log-normal distribution by log-transforming values first."
    )
    parser.add_argument(
        "--count-metric", action="store_true",
        help="Metric is a count; test Poisson assumption instead of Gaussian."
    )
    return parser.parse_args()


@dataclass
class DistributionResult:
    assumed: str
    test_name: str
    statistic: float
    p_value: float
    passed: bool
    notes: str = ""


@dataclass
class PowerResult:
    target_power: float
    alpha: float
    mde: float
    baseline_std: float
    required_n: int
    configured_n: int
    sufficient: bool
    recommendation: str


@dataclass
class StationarityResult:
    adf_statistic: float
    adf_pvalue: float
    is_stationary: bool
    runs_test_pvalue: float
    runs_test_passed: bool
    cv: float
    notes: str


@dataclass
class GrubbsResult:
    valid: bool
    sample_size_ok: bool
    gaussian_ok: bool
    single_outlier_assumed: bool
    critical_value: float
    max_g_value: float
    outliers_detected: int
    recommendation: str


@dataclass
class CIResult:
    mean: float
    ci_mean_lower: float
    ci_mean_upper: float
    std: float
    ci_std_lower: float
    ci_std_upper: float
    threshold: float
    ci_threshold_lower: float
    ci_threshold_upper: float
    mean_relative_width: float
    std_relative_width: float
    acceptable_precision: bool


@dataclass
class RobustResult:
    median: float
    mad: float
    mad_threshold: float
    q1: float
    q3: float
    iqr: float
    iqr_threshold_lower: float
    iqr_threshold_upper: float
    p95: float
    p99: float
    recommendation: str


@dataclass
class ValidationReport:
    metric: str
    n_samples: int
    burn_in_configured: int
    distribution: DistributionResult
    power: PowerResult
    stationarity: StationarityResult
    grubbs: GrubbsResult
    confidence_intervals: CIResult
    robust_fallbacks: RobustResult
    overall_passed: bool
    flags: List[str] = field(default_factory=list)


def load_baseline_data(path: str, metric: str) -> np.ndarray:
    df = pd.read_csv(path)
    if metric not in df.columns:
        raise ValueError(f"Metric '{metric}' not found in columns: {list(df.columns)}")
    values = df[metric].dropna().to_numpy(dtype=float)
    if len(values) == 0:
        raise ValueError("No non-null values found for metric.")
    return values


def test_gaussian(data: np.ndarray, alpha: float, log_transform: bool = False) -> DistributionResult:
    if log_transform:
        if np.any(data <= 0):
            # Shift to positive
            shift = abs(data.min()) + 1 if data.min() <= 0 else 0
            data = np.log(data + shift)
        else:
            data = np.log(data)
        assumed = "log-normal"
    else:
        assumed = "gaussian"

    n = len(data)
    if n < 3:
        return DistributionResult(
            assumed=assumed,
            test_name="insufficient_data",
            statistic=0.0,
            p_value=0.0,
            passed=False,
            notes="Need at least 3 samples for distribution testing."
        )

    if n <= 50:
        stat, p = stats.shapiro(data)
        test_name = "shapiro-wilk"
    else:
        # Anderson-Darling returns multiple critical values; we use the 5% one
        result = stats.anderson(data, dist="norm")
        stat = result.statistic
        crit_5_idx = list(result.significance_level).index(5.0) if 5.0 in result.significance_level else 2
        crit_5 = result.critical_values[crit_5_idx]
        p = None  # Anderson-Darling doesn't return exact p in scipy
        test_name = "anderson-darling"
        passed = stat < crit_5
        return DistributionResult(
            assumed=assumed,
            test_name=test_name,
            statistic=stat,
            p_value=p,
            passed=passed,
            notes=f"5% critical value = {crit_5:.4f}"
        )

    return DistributionResult(
        assumed=assumed,
        test_name=test_name,
        statistic=stat,
        p_value=p,
        passed=p >= alpha,
        notes=""
    )


def test_poisson(data: np.ndarray, alpha: float) -> DistributionResult:
    n = len(data)
    if n < 3:
        return DistributionResult(
            assumed="poisson",
            test_name="insufficient_data",
            statistic=0.0,
            p_value=0.0,
            passed=False,
            notes="Need at least 3 samples."
        )
    mean = np.mean(data)
    var = np.var(data, ddof=1)
    if mean == 0:
        return DistributionResult(
            assumed="poisson",
            test_name="dispersion_index",
            statistic=0.0,
            p_value=1.0,
            passed=True,
            notes="All values are zero; cannot test dispersion."
        )
    dispersion = var / mean
    # Chi-square test for dispersion: (n-1)*D ~ Chi2(n-1)
    chi2_stat = (n - 1) * dispersion
    p_lower = stats.chi2.cdf(chi2_stat, n - 1)
    p_upper = 1 - stats.chi2.cdf(chi2_stat, n - 1)
    p_value = 2 * min(p_lower, p_upper)

    # For small n, use rule-of-thumb
    rule_passed = 0.8 <= dispersion <= 1.2

    if n < 20:
        passed = rule_passed
        notes = f"Small sample: using rule-of-thumb (0.8 <= D <= 1.2). D={dispersion:.3f}"
    else:
        passed = p_value >= alpha
        notes = f"Dispersion D={dispersion:.3f}, formal p={p_value:.4f}"

    return DistributionResult(
        assumed="poisson",
        test_name="dispersion_index",
        statistic=dispersion,
        p_value=p_value,
        passed=passed,
        notes=notes
    )


def compute_power_analysis(
    data: np.ndarray,
    alpha: float,
    target_power: float,
    mde: Optional[float],
    configured_n: int,
    count_metric: bool,
) -> PowerResult:
    std = float(np.std(data, ddof=1))
    mean = float(np.mean(data))

    if mde is None:
        mde = 0.5 * std  # Default: detect half-std shift

    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(target_power)

    # Use mean-shift formula for all metric types; proportion formula
    # is only valid for true binary (0/1) rates, not general counts.
    required_n = math.ceil(((z_alpha + z_beta) * std / mde) ** 2)

    sufficient = configured_n >= required_n and configured_n >= 20

    if not sufficient:
        if configured_n < required_n:
            rec = f"Extend burn-in to at least {required_n} sessions for target power={target_power} and MDE={mde:.2f}."
        else:
            rec = f"Configured burn-in ({configured_n}) meets power target but is below absolute floor of 20."
    else:
        rec = "Burn-in period is sufficient for target power and MDE."

    return PowerResult(
        target_power=target_power,
        alpha=alpha,
        mde=mde,
        baseline_std=std,
        required_n=required_n,
        configured_n=configured_n,
        sufficient=sufficient,
        recommendation=rec,
    )


def test_stationarity(data: np.ndarray, alpha: float) -> StationarityResult:
    n = len(data)
    if n < 10:
        return StationarityResult(
            adf_statistic=0.0,
            adf_pvalue=1.0,
            is_stationary=False,
            runs_test_pvalue=1.0,
            runs_test_passed=False,
            cv=0.0,
            notes="Too few observations for stationarity testing."
        )

    # Augmented Dickey-Fuller (constant only)
    try:
        adf_stat, adf_p, _, _, crit_vals, _ = stats.adfuller(data, regression="c")
        is_stationary = adf_p < alpha
    except Exception as e:
        adf_stat, adf_p, is_stationary = 0.0, 1.0, False

    # Runs test (above/below median)
    median = np.median(data)
    signs = (data > median).astype(int)
    # Count runs
    runs = 1
    for i in range(1, n):
        if signs[i] != signs[i - 1]:
            runs += 1
    n1 = int(np.sum(signs))
    n2 = n - n1
    if n1 == 0 or n2 == 0:
        runs_p = 1.0
        runs_passed = False
    else:
        expected_runs = (2 * n1 * n2) / n + 1
        var_runs = (2 * n1 * n2 * (2 * n1 * n2 - n)) / (n ** 2 * (n - 1))
        if var_runs > 0:
            z_runs = (runs - expected_runs) / math.sqrt(var_runs)
            runs_p = 2 * (1 - stats.norm.cdf(abs(z_runs)))
            runs_passed = runs_p >= alpha  # too few runs OR too many runs both indicate non-random
        else:
            runs_p = 1.0
            runs_passed = False

    mean = np.mean(data)
    std = np.std(data, ddof=1)
    cv = std / mean if mean != 0 else float("inf")

    notes = []
    if not is_stationary:
        notes.append("ADF suggests non-stationarity (possible trend or unit root).")
    if not runs_passed:
        notes.append("Runs test failed (non-random ordering).")
    if cv < 0.05:
        notes.append(f"Very low CV ({cv:.3f}); metric may be too stable for meaningful drift detection.")

    return StationarityResult(
        adf_statistic=float(adf_stat),
        adf_pvalue=float(adf_p),
        is_stationary=is_stationary,
        runs_test_pvalue=float(runs_p),
        runs_test_passed=runs_passed,
        cv=cv,
        notes=" ".join(notes) if notes else "Series appears stationary with sufficient variance."
    )


def compute_grubbs(data: np.ndarray, alpha: float, gaussian_passed: bool) -> GrubbsResult:
    n = len(data)
    sample_size_ok = n >= 7
    gaussian_ok = gaussian_passed
    single_outlier_assumed = True  # We test once; iterative + Bonferroni for multiple

    if not sample_size_ok:
        return GrubbsResult(
            valid=False,
            sample_size_ok=False,
            gaussian_ok=gaussian_ok,
            single_outlier_assumed=single_outlier_assumed,
            critical_value=0.0,
            max_g_value=0.0,
            outliers_detected=0,
            recommendation="Sample size < 7: Grubbs has low power. Use robust estimators (MAD) or collect more data."
        )

    mean = np.mean(data)
    std = np.std(data, ddof=1)
    if std == 0:
        return GrubbsResult(
            valid=True,
            sample_size_ok=True,
            gaussian_ok=gaussian_ok,
            single_outlier_assumed=True,
            critical_value=0.0,
            max_g_value=0.0,
            outliers_detected=0,
            recommendation="Zero variance: no outliers possible. Metric may be constant or quantized."
        )

    max_dev = max(abs(data - mean))
    g = max_dev / std

    # Grubbs critical value approximation
    # G_crit = (n-1)/sqrt(n) * sqrt(t^2 / (n-2 + t^2))
    # where t is the two-tailed t-value for alpha/(2n), df=n-2
    t_crit = stats.t.ppf(1 - alpha / (2 * n), n - 2)
    g_crit = ((n - 1) / math.sqrt(n)) * math.sqrt((t_crit ** 2) / (n - 2 + t_crit ** 2))

    outliers = int(g > g_crit)

    if gaussian_ok and sample_size_ok:
        valid = True
        rec = "Grubbs test is appropriate."
    elif not gaussian_ok:
        valid = False
        rec = "Data non-Gaussian: use MAD for symmetric distributions or IQR for skewed."
    else:
        valid = False
        rec = "Grubbs assumptions violated. Review sample size or distribution."

    return GrubbsResult(
        valid=valid,
        sample_size_ok=sample_size_ok,
        gaussian_ok=gaussian_ok,
        single_outlier_assumed=single_outlier_assumed,
        critical_value=float(g_crit),
        max_g_value=float(g),
        outliers_detected=outliers,
        recommendation=rec,
    )


def compute_cis(data: np.ndarray, alpha: float, threshold_sigma: float) -> CIResult:
    n = len(data)
    mean = float(np.mean(data))
    std = float(np.std(data, ddof=1))

    # CI on mean (t-distribution)
    t_crit = stats.t.ppf(1 - alpha / 2, max(1, n - 1))
    se_mean = std / math.sqrt(n) if n > 0 else 0
    ci_mean_lower = mean - t_crit * se_mean
    ci_mean_upper = mean + t_crit * se_mean

    # CI on std (chi-square)
    if n > 1 and std > 0:
        chi2_lower = stats.chi2.ppf(alpha / 2, n - 1)
        chi2_upper = stats.chi2.ppf(1 - alpha / 2, n - 1)
        ci_std_lower = math.sqrt((n - 1) * std ** 2 / chi2_upper) if chi2_upper > 0 else 0
        ci_std_upper = math.sqrt((n - 1) * std ** 2 / chi2_lower) if chi2_lower > 0 else 0
    else:
        ci_std_lower = ci_std_upper = std

    # Threshold and its uncertainty
    threshold = mean + threshold_sigma * std
    # Propagate uncertainty: σ_T ≈ sqrt( σ_μ² + (k*σ_σ)² )
    sigma_mu = (ci_mean_upper - ci_mean_lower) / 2
    sigma_sigma = (ci_std_upper - ci_std_lower) / 2
    sigma_threshold = math.sqrt(sigma_mu ** 2 + (threshold_sigma * sigma_sigma) ** 2)
    ci_threshold_lower = threshold - sigma_threshold
    ci_threshold_upper = threshold + sigma_threshold

    mean_rel_width = (ci_mean_upper - ci_mean_lower) / abs(mean) if mean != 0 else float("inf")
    std_rel_width = (ci_std_upper - ci_std_lower) / abs(std) if std != 0 else float("inf")
    acceptable = mean_rel_width <= 0.20 and std_rel_width <= 0.30

    return CIResult(
        mean=mean,
        ci_mean_lower=ci_mean_lower,
        ci_mean_upper=ci_mean_upper,
        std=std,
        ci_std_lower=ci_std_lower,
        ci_std_upper=ci_std_upper,
        threshold=threshold,
        ci_threshold_lower=ci_threshold_lower,
        ci_threshold_upper=ci_threshold_upper,
        mean_relative_width=mean_rel_width,
        std_relative_width=std_rel_width,
        acceptable_precision=acceptable,
    )


def compute_robust_thresholds(data: np.ndarray, threshold_sigma: float) -> RobustResult:
    median = float(np.median(data))
    mad = float(stats.median_abs_deviation(data, scale="normal"))  # scaled to normal consistency
    if mad == 0:
        mad = np.mean(np.abs(data - median)) * 1.4826  # fallback

    q1 = float(np.percentile(data, 25))
    q3 = float(np.percentile(data, 75))
    iqr = q3 - q1

    mad_threshold = median + 3.5 * mad
    iqr_threshold_upper = q3 + 1.5 * iqr
    iqr_threshold_lower = q1 - 1.5 * iqr

    p95 = float(np.percentile(data, 95))
    p99 = float(np.percentile(data, 99))

    rec = (
        "Use MAD-based threshold if distribution is symmetric but non-Gaussian. "
        "Use IQR if distribution is skewed. Use P99 for extreme-value or heavy-tailed metrics."
    )

    return RobustResult(
        median=median,
        mad=mad,
        mad_threshold=mad_threshold,
        q1=q1,
        q3=q3,
        iqr=iqr,
        iqr_threshold_lower=iqr_threshold_lower,
        iqr_threshold_upper=iqr_threshold_upper,
        p95=p95,
        p99=p99,
        recommendation=rec,
    )


def build_report(
    data: np.ndarray,
    args: argparse.Namespace,
    dist: DistributionResult,
    power: PowerResult,
    stationarity: StationarityResult,
    grubbs: GrubbsResult,
    ci: CIResult,
    robust: RobustResult,
) -> ValidationReport:
    flags = []
    if not dist.passed:
        flags.append(f"DISTRIBUTION_FAIL: {dist.assumed} assumption rejected ({dist.test_name} p={dist.p_value:.4f}).")
    if not power.sufficient:
        flags.append(f"POWER_INSUFFICIENT: Need {power.required_n} sessions, configured {power.configured_n}.")
    if not stationarity.is_stationary:
        flags.append("NON_STATIONARY: Burn-in data show trend or unit root (ADF failed).")
    if not stationarity.runs_test_passed:
        flags.append("NON_RANDOM: Runs test failed; data may have autocorrelation or cycles.")
    if not grubbs.valid:
        flags.append(f"GRUBBS_INVALID: {grubbs.recommendation}")
    if not ci.acceptable_precision:
        flags.append(f"CI_TOO_WIDE: Mean CI width = {ci.mean_relative_width:.1%}, Std CI width = {ci.std_relative_width:.1%}.")

    overall = len(flags) == 0

    return ValidationReport(
        metric=args.metric,
        n_samples=len(data),
        burn_in_configured=args.burn_in,
        distribution=dist,
        power=power,
        stationarity=stationarity,
        grubbs=grubbs,
        confidence_intervals=ci,
        robust_fallbacks=robust,
        overall_passed=overall,
        flags=flags,
    )


def report_to_dict(report: ValidationReport) -> dict:
    def b(val):
        return bool(val)
    return {
        "metric": report.metric,
        "n_samples": report.n_samples,
        "burn_in_configured": report.burn_in_configured,
        "overall_passed": b(report.overall_passed),
        "flags": report.flags,
        "distribution": {
            "assumed": report.distribution.assumed,
            "test_name": report.distribution.test_name,
            "statistic": round(float(report.distribution.statistic), 4),
            "p_value": round(float(report.distribution.p_value), 4) if report.distribution.p_value is not None else None,
            "passed": b(report.distribution.passed),
            "notes": report.distribution.notes,
        },
        "power_analysis": {
            "target_power": report.power.target_power,
            "alpha": report.power.alpha,
            "mde": round(float(report.power.mde), 4),
            "baseline_std": round(float(report.power.baseline_std), 4),
            "required_n": report.power.required_n,
            "configured_n": report.power.configured_n,
            "sufficient": b(report.power.sufficient),
            "recommendation": report.power.recommendation,
        },
        "stationarity": {
            "adf_statistic": round(float(report.stationarity.adf_statistic), 4),
            "adf_pvalue": round(float(report.stationarity.adf_pvalue), 4),
            "is_stationary": b(report.stationarity.is_stationary),
            "runs_test_pvalue": round(float(report.stationarity.runs_test_pvalue), 4),
            "runs_test_passed": b(report.stationarity.runs_test_passed),
            "cv": round(float(report.stationarity.cv), 4),
            "notes": report.stationarity.notes,
        },
        "grubbs_validation": {
            "valid": b(report.grubbs.valid),
            "sample_size_ok": b(report.grubbs.sample_size_ok),
            "gaussian_ok": b(report.grubbs.gaussian_ok),
            "single_outlier_assumed": b(report.grubbs.single_outlier_assumed),
            "critical_value": round(float(report.grubbs.critical_value), 4),
            "max_g_value": round(float(report.grubbs.max_g_value), 4),
            "outliers_detected": report.grubbs.outliers_detected,
            "recommendation": report.grubbs.recommendation,
        },
        "confidence_intervals": {
            "mean": round(float(report.confidence_intervals.mean), 4),
            "ci_mean": [
                round(float(report.confidence_intervals.ci_mean_lower), 4),
                round(float(report.confidence_intervals.ci_mean_upper), 4),
            ],
            "std": round(float(report.confidence_intervals.std), 4),
            "ci_std": [
                round(float(report.confidence_intervals.ci_std_lower), 4),
                round(float(report.confidence_intervals.ci_std_upper), 4),
            ],
            "threshold": round(float(report.confidence_intervals.threshold), 4),
            "ci_threshold": [
                round(float(report.confidence_intervals.ci_threshold_lower), 4),
                round(float(report.confidence_intervals.ci_threshold_upper), 4),
            ],
            "mean_relative_width": round(float(report.confidence_intervals.mean_relative_width), 4),
            "std_relative_width": round(float(report.confidence_intervals.std_relative_width), 4),
            "acceptable_precision": b(report.confidence_intervals.acceptable_precision),
        },
        "robust_fallbacks": {
            "median": round(float(report.robust_fallbacks.median), 4),
            "mad": round(float(report.robust_fallbacks.mad), 4),
            "mad_threshold": round(float(report.robust_fallbacks.mad_threshold), 4),
            "q1": round(float(report.robust_fallbacks.q1), 4),
            "q3": round(float(report.robust_fallbacks.q3), 4),
            "iqr": round(float(report.robust_fallbacks.iqr), 4),
            "iqr_threshold_lower": round(float(report.robust_fallbacks.iqr_threshold_lower), 4),
            "iqr_threshold_upper": round(float(report.robust_fallbacks.iqr_threshold_upper), 4),
            "p95": round(float(report.robust_fallbacks.p95), 4),
            "p99": round(float(report.robust_fallbacks.p99), 4),
            "recommendation": report.robust_fallbacks.recommendation,
        },
    }


def print_text_report(report: ValidationReport) -> None:
    print("=" * 70)
    print(f"DRIFT-MONITOR BASELINE VALIDATION REPORT")
    print(f"Metric: {report.metric}  |  Samples: {report.n_samples}  |  Burn-in configured: {report.burn_in_configured}")
    print("=" * 70)

    print("\n[1] DISTRIBUTION TEST")
    d = report.distribution
    print(f"  Assumed:      {d.assumed}")
    print(f"  Test:         {d.test_name}")
    print(f"  Statistic:    {d.statistic:.4f}")
    if d.p_value is not None:
        print(f"  p-value:      {d.p_value:.4f}")
    print(f"  Result:       {'PASS' if d.passed else 'FAIL'}")
    if d.notes:
        print(f"  Notes:        {d.notes}")

    print("\n[2] POWER ANALYSIS")
    p = report.power
    print(f"  Target power: {p.target_power}")
    print(f"  Alpha:        {p.alpha}")
    print(f"  MDE:          {p.mde:.4f}")
    print(f"  Baseline std: {p.baseline_std:.4f}")
    print(f"  Required n:   {p.required_n}")
    print(f"  Configured n: {p.configured_n}")
    print(f"  Sufficient:   {'YES' if p.sufficient else 'NO'}")
    print(f"  Recommendation: {p.recommendation}")

    print("\n[3] STATIONARITY & BURN-IN")
    s = report.stationarity
    print(f"  ADF stat:     {s.adf_statistic:.4f}  (p={s.adf_pvalue:.4f})")
    print(f"  Stationary:   {'YES' if s.is_stationary else 'NO'}")
    print(f"  Runs test p:  {s.runs_test_pvalue:.4f}")
    print(f"  CV:           {s.cv:.4f}")
    print(f"  Notes:        {s.notes}")

    print("\n[4] GRUBBS OUTLIER VALIDATION")
    g = report.grubbs
    print(f"  Valid:        {'YES' if g.valid else 'NO'}")
    print(f"  n >= 7:       {'YES' if g.sample_size_ok else 'NO'}")
    print(f"  Gaussian OK:  {'YES' if g.gaussian_ok else 'NO'}")
    print(f"  Critical G:   {g.critical_value:.4f}")
    print(f"  Max G:        {g.max_g_value:.4f}")
    print(f"  Outliers:     {g.outliers_detected}")
    print(f"  Recommendation: {g.recommendation}")

    print("\n[5] CONFIDENCE INTERVALS")
    c = report.confidence_intervals
    print(f"  Mean:         {c.mean:.4f}  [{c.ci_mean_lower:.4f}, {c.ci_mean_upper:.4f}]")
    print(f"  Std:          {c.std:.4f}  [{c.ci_std_lower:.4f}, {c.ci_std_upper:.4f}]")
    print(f"  Threshold:    {c.threshold:.4f}  [{c.ci_threshold_lower:.4f}, {c.ci_threshold_upper:.4f}]")
    print(f"  Mean CI width: {c.mean_relative_width:.1%}  (limit: 20%)")
    print(f"  Std CI width:  {c.std_relative_width:.1%}  (limit: 30%)")
    print(f"  Precision:    {'ACCEPTABLE' if c.acceptable_precision else 'TOO WIDE'}")

    print("\n[6] ROBUST / NON-PARAMETRIC FALLBACKS")
    r = report.robust_fallbacks
    print(f"  Median:       {r.median:.4f}")
    print(f"  MAD:          {r.mad:.4f}")
    print(f"  MAD threshold:{r.mad_threshold:.4f}")
    print(f"  IQR lower:    {r.iqr_threshold_lower:.4f}")
    print(f"  IQR upper:    {r.iqr_threshold_upper:.4f}")
    print(f"  P95:          {r.p95:.4f}")
    print(f"  P99:          {r.p99:.4f}")
    print(f"  Recommendation: {r.recommendation}")

    print("\n" + "=" * 70)
    print(f"OVERALL: {'PASS' if report.overall_passed else 'FAIL'}")
    if report.flags:
        print("\nFLAGS:")
        for f in report.flags:
            print(f"  - {f}")
    print("=" * 70)


def main() -> int:
    args = parse_args()

    try:
        data = load_baseline_data(args.baseline_data, args.metric)
    except Exception as e:
        print(f"ERROR loading data: {e}", file=sys.stderr)
        return 1

    if len(data) < 3:
        print("ERROR: Need at least 3 baseline sessions to validate.", file=sys.stderr)
        return 1

    # Distribution test
    if args.count_metric:
        dist = test_poisson(data, args.alpha)
    else:
        dist = test_gaussian(data, args.alpha, log_transform=args.log_transform)

    # Power analysis
    power = compute_power_analysis(
        data, args.alpha, args.power, args.mde, args.burn_in, args.count_metric
    )

    # Stationarity
    stationarity = test_stationarity(data, args.alpha)

    # Grubbs validation
    grubbs = compute_grubbs(data, args.alpha, dist.passed and dist.assumed in ("gaussian", "log-normal"))

    # CIs
    ci = compute_cis(data, args.alpha, args.threshold_sigma)

    # Robust fallbacks
    robust = compute_robust_thresholds(data, args.threshold_sigma)

    # Build report
    report = build_report(data, args, dist, power, stationarity, grubbs, ci, robust)

    # Output
    if args.output:
        with open(args.output, "w") as f:
            json.dump(report_to_dict(report), f, indent=2)
        print(f"Report written to {args.output}")
    else:
        print_text_report(report)

    return 0 if report.overall_passed else 2


if __name__ == "__main__":
    sys.exit(main())
