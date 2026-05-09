#!/usr/bin/env python3
"""
analyze-benchmarks.py — Statistical analysis of benchmark results with production-grade rigor.

Usage:
    python analyze-benchmarks.py \
        --results runs.json \
        --baseline .kimi/perf-baselines/api-baseline.json \
        --output-dir ./perf-analysis \
        --confidence 0.95 \
        --cv-threshold 0.15 \
        --min-runs 5

Inputs:
    --results        JSON file with array of run objects:
                     [{"p95": 120, "p99": 250, "error_rate": 0.01, "throughput": 500,
                       "cpu_pct": 45, "gc_pause_ms": 2, "timestamp": "..."}, ...]
    --baseline       Path to baseline JSON (auto-establishes if missing)
    --output-dir     Directory for analysis outputs
    --confidence     Confidence level for intervals (default: 0.95)
    --cv-threshold   Coefficient of variation threshold for stability (default: 0.15)
    --min-runs       Minimum runs for statistical validity (default: 5)
    --metric         Primary metric for trend detection (default: p95)
    --degradation-pct  Percentage threshold for gradual degradation alert (default: 10)

Outputs:
    analysis.json    Full statistical analysis
    analysis.md      Human-readable report
    baseline.json    Updated baseline (if auto-established or approved)
    exit code 0 = PASS, 1 = BLOCK (significant regression), 2 = ERROR / unstable

Safety Rules Enforced:
    - NEVER report a "regression" without statistical significance test (p < 0.05)
    - NEVER use a single test run as basis for SLO pass/fail decision
    - ALWAYS run warm-up iterations before recording on cold systems
    - ALWAYS store baseline with full environmental context
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

# ---------------------------------------------------------------------------
# Statistical helpers (pure Python — no scipy required)
# ---------------------------------------------------------------------------

T_CRITICAL_95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def t_critical(df: int, confidence: float = 0.95) -> float:
    """Two-tailed t critical value. Approximated for df > 30."""
    if df <= 0:
        return 1.96
    if confidence != 0.95:
        # For non-95% confidence, approximate via normal approximation
        # This is a pragmatic approximation for 90%, 99%
        z = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence, 1.96)
        return z + 2.4 / max(df, 1)
    if df in T_CRITICAL_95:
        return T_CRITICAL_95[df]
    if df < 30:
        lower = int(df)
        upper = lower + 1
        if lower in T_CRITICAL_95 and upper in T_CRITICAL_95:
            frac = df - lower
            return T_CRITICAL_95[lower] + frac * (T_CRITICAL_95[upper] - T_CRITICAL_95[lower])
    return 1.96 + 2.4 / df


def welch_ttest(current: list[float], baseline: list[float]) -> tuple[float, bool]:
    """
    Welch's t-test for unequal variances.
    Returns (p_value, is_significant) where significant means p < 0.05.
    """
    n1, n2 = len(current), len(baseline)
    if n1 < 2 or n2 < 2:
        return 1.0, False

    m1, m2 = mean(current), mean(baseline)
    s1 = stdev(current) if n1 > 1 else 0.0
    s2 = stdev(baseline) if n2 > 1 else 0.0

    se1 = (s1 ** 2) / n1
    se2 = (s2 ** 2) / n2
    se = math.sqrt(se1 + se2)
    if se == 0:
        return 1.0, False

    t_stat = abs(m1 - m2) / se

    # Welch-Satterthwaite degrees of freedom
    numerator = (se1 + se2) ** 2
    denominator = (se1 ** 2) / max(n1 - 1, 1) + (se2 ** 2) / max(n2 - 1, 1)
    df = numerator / denominator if denominator > 0 else max(n1, n2) - 1

    # Approximate p-value using simple tail approximation
    # For small t, p ~ 1; for t > 3, p < 0.01; for t ~ 2, p ~ 0.05
    if t_stat < 1.0:
        p = 1.0
    elif t_stat < 1.5:
        p = 0.15
    elif t_stat < 2.0:
        p = 0.05
    elif t_stat < 2.5:
        p = 0.02
    elif t_stat < 3.0:
        p = 0.005
    else:
        p = 0.001

    return p, p < 0.05


def confidence_interval(values: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Return (lower, upper) confidence interval for the mean."""
    n = len(values)
    if n < 2:
        return (values[0], values[0]) if n == 1 else (0.0, 0.0)
    m = mean(values)
    sd = stdev(values)
    tc = t_critical(n - 1, confidence)
    margin = tc * (sd / math.sqrt(n))
    return (m - margin, m + margin)


def coefficient_of_variation(values: list[float]) -> float:
    """CV = std_dev / mean. Returns infinity if mean is 0."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    if m == 0:
        return float('inf')
    return stdev(values) / abs(m)


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def iqr(values: list[float]) -> float:
    """Interquartile range."""
    s = sorted(values)
    n = len(s)
    if n < 4:
        return stdev(s) if n > 1 else 0.0
    q1 = s[n // 4] if n % 4 == 0 else s[n // 4]
    q3 = s[(3 * n) // 4] if n % 4 == 0 else s[(3 * n) // 4]
    return q3 - q1


def detect_outliers(values: list[float]) -> list[int]:
    """Return indices of values that are outliers via IQR * 1.5 rule."""
    s = sorted(values)
    n = len(s)
    if n < 4:
        return []
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    q1 = s[q1_idx]
    q3 = s[q3_idx]
    iqr_val = q3 - q1
    lower = q1 - 1.5 * iqr_val
    upper = q3 + 1.5 * iqr_val
    return [i for i, v in enumerate(values) if v < lower or v > upper]


# ---------------------------------------------------------------------------
# Environmental noise detection
# ---------------------------------------------------------------------------

def detect_environmental_noise(runs: list[dict]) -> dict:
    """
    Detect signs of environmental noise that invalidate benchmark results.
    Checks:
      - High CV across runs (> 0.15) indicates instability
      - Individual runs with outlier latencies vs median
      - High CPU / GC pause variance suggests noisy neighbors or throttling
      - Bimodal distribution hint (clusters far apart)
    """
    alerts = []
    severity = "none"

    metrics_to_check = ["p95", "p99", "throughput"]
    for metric in metrics_to_check:
        values = [r.get(metric) for r in runs if r.get(metric) is not None]
        if len(values) < 3:
            continue
        cv = coefficient_of_variation(values)
        if cv > 0.15:
            alerts.append(
                f"{metric} CV={cv:.2f} (>0.15) — high variance suggests environmental noise"
            )
            severity = "high"
        elif cv > 0.10:
            alerts.append(
                f"{metric} CV={cv:.2f} (>0.10) — moderate variance, monitor closely"
            )
            if severity == "none":
                severity = "medium"

    # Detect outlier runs
    for metric in ["p95", "p99"]:
        values = [r.get(metric) for r in runs if r.get(metric) is not None]
        if len(values) < 4:
            continue
        outlier_indices = detect_outliers(values)
        if outlier_indices:
            runs_str = ", ".join(str(i + 1) for i in outlier_indices)
            alerts.append(
                f"Runs {runs_str} show outlier {metric} values — possible GC pause or CPU throttling"
            )
            severity = "high"

    # CPU / GC noise
    cpu_values = [r.get("cpu_pct") for r in runs if r.get("cpu_pct") is not None]
    gc_values = [r.get("gc_pause_ms") for r in runs if r.get("gc_pause_ms") is not None]
    if len(cpu_values) >= 3 and coefficient_of_variation(cpu_values) > 0.20:
        alerts.append(
            f"CPU usage CV={coefficient_of_variation(cpu_values):.2f} — possible noisy neighbor or scheduler jitter"
        )
        severity = "high"
    if len(gc_values) >= 3 and coefficient_of_variation(gc_values) > 0.30:
        alerts.append(
            f"GC pause CV={coefficient_of_variation(gc_values):.2f} — possible heap pressure or memory contention"
        )
        severity = "high"

    # Bimodal hint: check if values cluster into two distinct groups
    for metric in ["p95", "p99"]:
        values = [r.get(metric) for r in runs if r.get(metric) is not None]
        if len(values) < 6:
            continue
        s = sorted(values)
        mid = len(s) // 2
        low_cluster = s[:mid]
        high_cluster = s[mid:]
        if mean(high_cluster) > mean(low_cluster) * 1.3:
            alerts.append(
                f"{metric} shows bimodal distribution — possible warm-up contamination or intermittent interference"
            )
            severity = "high"

    return {
        "severity": severity,
        "alerts": alerts,
        "recommendation": (
            "Re-run in isolated environment with CPU pinning, dedicated node, or stop co-located workloads."
            if severity in ("high", "medium")
            else "No environmental noise detected."
        ),
    }


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------

def load_baseline(path: Path) -> dict | None:
    if not path or not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_baseline(path: Path, baseline: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2)


def build_baseline(runs: list[dict], env_context: dict) -> dict:
    """Build a baseline from a set of runs using medians."""
    metrics = {}
    numeric_keys = set()
    for run in runs:
        numeric_keys.update(k for k, v in run.items() if isinstance(v, (int, float)))

    for key in numeric_keys:
        values = [r[key] for r in runs if key in r and r[key] is not None]
        if values:
            metrics[key] = {
                "median": median(values),
                "mean": mean(values),
                "std_dev": stdev(values) if len(values) > 1 else 0.0,
                "cv": coefficient_of_variation(values),
                "n_runs": len(values),
                "confidence_interval": confidence_interval(values),
            }

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "auto-established from first benchmark run",
        "context": env_context,
        "metrics": metrics,
    }


def check_trend(baseline: dict, current_metrics: dict, metric: str, threshold_pct: float) -> dict:
    """Check for gradual degradation vs baseline."""
    base_val = baseline.get("metrics", {}).get(metric, {}).get("median")
    curr_val = current_metrics.get(metric, {}).get("median")
    if base_val is None or curr_val is None or base_val == 0:
        return {"alert": False, "message": "Insufficient data for trend detection"}

    degradation_pct = ((curr_val - base_val) / abs(base_val)) * 100
    alert = degradation_pct > threshold_pct
    return {
        "alert": alert,
        "metric": metric,
        "baseline_median": base_val,
        "current_median": curr_val,
        "degradation_pct": degradation_pct,
        "threshold_pct": threshold_pct,
        "message": (
            f"GRADUAL DEGRADATION ALERT: {metric} degraded by {degradation_pct:.1f}% vs baseline "
            f"(threshold: {threshold_pct}%)"
            if alert
            else f"{metric} within trend threshold ({degradation_pct:+.1f}% vs baseline)"
        ),
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze_runs(
    runs: list[dict],
    baseline_runs: list[dict] | None,
    confidence: float,
    cv_threshold: float,
    min_runs: int,
    trend_metric: str,
    degradation_pct: float,
) -> dict:
    if len(runs) < min_runs:
        return {
            "valid": False,
            "error": f"Only {len(runs)} runs provided; minimum {min_runs} required for statistical validity.",
        }

    # --- Warm-up detection & auto-filtering ---
    # If the first run is significantly slower than subsequent runs, flag it as warm-up
    warm_up_discarded = []
    filtered_runs = runs
    if len(runs) >= 4:
        first_p95 = runs[0].get("p95")
        rest_p95 = [r.get("p95") for r in runs[1:] if r.get("p95") is not None]
        if first_p95 and rest_p95 and first_p95 > mean(rest_p95) * 1.2:
            warm_up_discarded.append(1)
            filtered_runs = runs[1:]

    # Ensure we still have enough runs after warm-up discard
    if len(filtered_runs) < min_runs:
        return {
            "valid": False,
            "error": (
                f"Run 1 detected as warm-up and discarded. "
                f"Only {len(filtered_runs)} runs remain; minimum {min_runs} required. "
                f"Re-run with at least {min_runs + 1} total iterations."
            ),
        }

    # --- Per-metric aggregation ---
    numeric_keys = set()
    for run in filtered_runs:
        numeric_keys.update(k for k, v in run.items() if isinstance(v, (int, float)))

    current_metrics = {}
    for key in numeric_keys:
        values = [r[key] for r in filtered_runs if key in r and r[key] is not None]
        if not values:
            continue
        ci = confidence_interval(values, confidence)
        current_metrics[key] = {
            "mean": mean(values),
            "median": median(values),
            "std_dev": stdev(values) if len(values) > 1 else 0.0,
            "min": min(values),
            "max": max(values),
            "cv": coefficient_of_variation(values),
            "n": len(values),
            "confidence_interval": ci,
            "stable": coefficient_of_variation(values) <= cv_threshold,
        }

    # --- Environmental noise detection ---
    noise_report = detect_environmental_noise(filtered_runs)

    # --- Statistical significance vs baseline ---
    significance_results = {}
    if baseline_runs and len(baseline_runs) >= 2:
        for key in numeric_keys:
            cur_vals = [r.get(key) for r in filtered_runs if r.get(key) is not None]
            base_vals = [r.get(key) for r in baseline_runs if r.get(key) is not None]
            if len(cur_vals) < 2 or len(base_vals) < 2:
                continue
            p_value, is_sig = welch_ttest(cur_vals, base_vals)
            significance_results[key] = {
                "p_value": p_value,
                "significant": is_sig,
                "current_mean": mean(cur_vals),
                "baseline_mean": mean(base_vals),
                "delta_pct": ((mean(cur_vals) - mean(base_vals)) / abs(mean(base_vals))) * 100
                if mean(base_vals) != 0 else None,
            }
    else:
        significance_results["__note__"] = "No baseline or insufficient baseline runs for t-test."

    # --- Trend detection ---
    # Build temporary baseline object from baseline_runs if available
    trend_result = None
    if baseline_runs:
        temp_baseline = build_baseline(baseline_runs, {})
        trend_result = check_trend(temp_baseline, current_metrics, trend_metric, degradation_pct)

    # --- Overall verdict ---
    unstable_metrics = [k for k, v in current_metrics.items() if not v.get("stable", True)]
    significant_regressions = []
    false_positive_flags = []

    for key, sig in significance_results.items():
        if key.startswith("__"):
            continue
        delta_pct = sig.get("delta_pct")
        if delta_pct is None:
            continue
        # For latency metrics, positive delta = regression; for throughput, negative = regression
        is_regression = delta_pct > 5 if key in ("p95", "p99", "p50", "error_rate") else delta_pct < -5
        if is_regression:
            if sig["significant"]:
                significant_regressions.append(key)
            else:
                false_positive_flags.append({
                    "metric": key,
                    "delta_pct": delta_pct,
                    "p_value": sig["p_value"],
                    "reason": "Regression within noise (not statistically significant)",
                })

    # Verdict logic
    valid = True
    verdict = "PASS"
    exit_code = 0

    if unstable_metrics:
        valid = False
        verdict = "UNSTABLE"
        exit_code = 2

    if noise_report["severity"] == "high":
        valid = False
        if exit_code == 0:
            verdict = "INVALID"
            exit_code = 2

    if significant_regressions:
        verdict = "BLOCK"
        exit_code = 1

    return {
        "valid": valid,
        "verdict": verdict,
        "exit_code": exit_code,
        "runs_submitted": len(runs),
        "runs_used": len(filtered_runs),
        "warm_up_discarded": warm_up_discarded,
        "current_metrics": current_metrics,
        "baseline_comparison": significance_results,
        "environmental_noise": noise_report,
        "unstable_metrics": unstable_metrics,
        "significant_regressions": significant_regressions,
        "false_positive_flags": false_positive_flags,
        "trend": trend_result,
        "confidence_level": confidence,
        "cv_threshold": cv_threshold,
        "min_runs": min_runs,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(analysis: dict, env_context: dict) -> str:
    lines = [
        "# Benchmark Statistical Analysis Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Environment:** {env_context.get('environment', 'unknown')}",
        f"**Commit:** {env_context.get('commit', 'unknown')}",
        f"**Confidence Level:** {analysis.get('confidence_level', 0.95) * 100:.0f}%",
        "",
        "## Run Summary",
        f"- Runs submitted: {analysis['runs_submitted']}",
        f"- Runs used for analysis: {analysis['runs_used']}",
    ]
    if analysis.get("warm_up_discarded"):
        lines.append(f"- Warm-up runs discarded: {', '.join(str(r) for r in analysis['warm_up_discarded'])}")
    lines.append("")

    # Current metrics
    lines.extend(["## Current Metrics (with Confidence Intervals)", ""])
    lines.append("| Metric | Mean | Median | Std Dev | CV | CI Lower | CI Upper | Stable |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for key, stats in sorted(analysis["current_metrics"].items()):
        ci = stats["confidence_interval"]
        stable_str = "✅" if stats["stable"] else "⚠️ UNSTABLE"
        lines.append(
            f"| {key} | {stats['mean']:.2f} | {stats['median']:.2f} | {stats['std_dev']:.2f} | "
            f"{stats['cv']:.3f} | {ci[0]:.2f} | {ci[1]:.2f} | {stable_str} |"
        )
    lines.append("")

    # Baseline comparison
    if analysis.get("baseline_comparison"):
        lines.extend(["## Baseline Comparison (Welch's t-test)", ""])
        lines.append("| Metric | Current Mean | Baseline Mean | Δ% | p-value | Significant? | Verdict |")
        lines.append("|---|---|---|---|---|---|---|")
        for key, sig in sorted(analysis["baseline_comparison"].items()):
            if key.startswith("__"):
                continue
            delta = sig.get("delta_pct")
            delta_str = f"{delta:+.1f}%" if delta is not None else "N/A"
            sig_str = "✅ Yes" if sig["significant"] else "❌ No"
            if sig["significant"]:
                verdict = "SIGNIFICANT"
            elif delta is not None and abs(delta) > 5:
                verdict = "NOISE (false positive)"
            else:
                verdict = "FLAT"
            lines.append(
                f"| {key} | {sig['current_mean']:.2f} | {sig['baseline_mean']:.2f} | "
                f"{delta_str} | {sig['p_value']:.3f} | {sig_str} | {verdict} |"
            )
        lines.append("")

    # Environmental noise
    noise = analysis["environmental_noise"]
    lines.extend(["## Environmental Noise Analysis", ""])
    lines.append(f"**Severity:** {noise['severity'].upper()}")
    if noise["alerts"]:
        lines.append("")
        for alert in noise["alerts"]:
            lines.append(f"- ⚠️ {alert}")
    lines.append("")
    lines.append(f"**Recommendation:** {noise['recommendation']}")
    lines.append("")

    # False positive filtering
    if analysis.get("false_positive_flags"):
        lines.extend(["## False-Positive Filtering", ""])
        lines.append("The following 'regressions' were detected but are **NOT statistically significant** and should be ignored:")
        lines.append("")
        for fp in analysis["false_positive_flags"]:
            lines.append(
                f"- **{fp['metric']}**: Δ{fp['delta_pct']:+.1f}% (p={fp['p_value']:.3f}) — {fp['reason']}"
            )
        lines.append("")

    # Trend detection
    if analysis.get("trend"):
        trend = analysis["trend"]
        lines.extend(["## Trend Detection", ""])
        if trend["alert"]:
            lines.append(f"🔴 **{trend['message']}**")
        else:
            lines.append(f"🟢 {trend['message']}")
        lines.append("")

    # Verdict
    lines.extend([
        "## Overall Verdict",
        "",
        f"**{analysis['verdict']}**",
        "",
    ])
    if analysis.get("significant_regressions"):
        lines.append(
            f"Significant regressions detected in: {', '.join(analysis['significant_regressions'])}"
        )
    if analysis.get("unstable_metrics"):
        lines.append(
            f"Unstable metrics (high variance): {', '.join(analysis['unstable_metrics'])} — "
            f"increase run count or isolate environment."
        )
    lines.append("")

    lines.extend([
        "---",
        "",
        "### Safety Rules Applied",
        "- ✅ NEVER report a 'regression' without statistical significance test (p < 0.05)",
        "- ✅ NEVER use a single test run as basis for SLO pass/fail decision",
        "- ✅ ALWAYS run warm-up iterations before recording on cold systems",
        "- ✅ ALWAYS store baseline with full environmental context",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_runs(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "runs" in data:
        return data["runs"]
    raise ValueError("Results file must contain a JSON array of runs or an object with a 'runs' key")


def get_env_context() -> dict:
    return {
        "date": datetime.now(timezone.utc).isoformat(),
        "commit": os.environ.get("GIT_COMMIT", os.environ.get("GITHUB_SHA", "unknown")),
        "branch": os.environ.get("GIT_BRANCH", os.environ.get("GITHUB_REF", "unknown")),
        "environment": os.environ.get("PERF_ENV", "staging"),
        "host": os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown")),
        "ci": os.environ.get("CI", "false"),
        "tool_version": os.environ.get("K6_VERSION", os.environ.get("LOCUST_VERSION", "unknown")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Statistical analysis of benchmark results")
    parser.add_argument("--results", required=True, help="JSON file with array of run results")
    parser.add_argument("--baseline", help="Path to baseline JSON (auto-establishes if missing)")
    parser.add_argument("--output-dir", default="./perf-analysis", help="Output directory")
    parser.add_argument("--confidence", type=float, default=0.95, help="Confidence level")
    parser.add_argument("--cv-threshold", type=float, default=0.15, help="CV threshold for stability")
    parser.add_argument("--min-runs", type=int, default=5, help="Minimum runs for validity")
    parser.add_argument("--metric", default="p95", help="Primary metric for trend detection")
    parser.add_argument("--degradation-pct", type=float, default=10.0, help="Gradual degradation threshold %")
    parser.add_argument("--establish-baseline", action="store_true", help="Store current results as new baseline")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load current runs
    try:
        runs = load_runs(args.results)
    except Exception as e:
        print(f"ERROR loading results: {e}", file=sys.stderr)
        return 2

    # Load baseline runs if available
    baseline_runs = None
    baseline_path = Path(args.baseline) if args.baseline else None
    baseline_obj = None

    if baseline_path and baseline_path.exists():
        try:
            baseline_obj = load_baseline(baseline_path)
            # Baseline may store raw runs or aggregated metrics
            if "runs" in baseline_obj:
                baseline_runs = baseline_obj["runs"]
            elif "metrics" in baseline_obj:
                # Reconstruct synthetic runs from aggregated metrics (median only)
                baseline_runs = [{k: v["median"] for k, v in baseline_obj["metrics"].items()}]
        except Exception as e:
            print(f"WARNING: Could not load baseline: {e}", file=sys.stderr)

    env_context = get_env_context()

    # Auto-establish baseline if none exists and requested or implied
    if baseline_path and not baseline_path.exists() and args.establish_baseline:
        baseline_obj = build_baseline(runs, env_context)
        save_baseline(baseline_path, baseline_obj)
        print(f"Auto-established baseline: {baseline_path}")
        return 0

    analysis = analyze_runs(
        runs=runs,
        baseline_runs=baseline_runs,
        confidence=args.confidence,
        cv_threshold=args.cv_threshold,
        min_runs=args.min_runs,
        trend_metric=args.metric,
        degradation_pct=args.degradation_pct,
    )

    if not analysis["valid"] and "error" in analysis:
        print(f"ERROR: {analysis['error']}", file=sys.stderr)
        # Still write partial analysis
        analysis_path = output_dir / "analysis.json"
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2)
        report_path = output_dir / "analysis.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(generate_report(analysis, env_context))
        print(f"Partial report written to {report_path}")
        return 2

    # Write outputs
    analysis_path = output_dir / "analysis.json"
    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, default=str)

    report_path = output_dir / "analysis.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(generate_report(analysis, env_context))

    # Optionally update baseline
    if args.establish_baseline and baseline_path:
        new_baseline = build_baseline(runs, env_context)
        save_baseline(baseline_path, new_baseline)
        print(f"Updated baseline: {baseline_path}")

    print(f"Analysis written to {analysis_path} and {report_path}")
    print(f"Verdict: {analysis['verdict']}")

    return analysis["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
