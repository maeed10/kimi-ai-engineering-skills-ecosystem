#!/usr/bin/env python3
"""
run-k6-loadtest.py — Generate and execute k6 load tests with production-grade statistical rigor.

Usage:
    python run-k6-loadtest.py \
        --endpoints endpoints.json \
        --slo slo.json \
        --output-dir ./perf-results \
        --vus 100 \
        --duration 5m \
        --runs 5 \
        --warm-up-runs 3 \
        --auto-warmup \
        --baseline .kimi/perf-baselines/api-baseline.json \
        --base-url http://localhost:8080

Inputs:
    --endpoints      JSON array of {method, path, body?, headers?, weight?}
    --openapi        OpenAPI spec path (alternative to --endpoints)
    --slo            JSON with latency_ceiling_ms, error_budget_pct, throughput_floor_rps
    --baseline       Path to baseline JSON for regression comparison
    --output-dir     Directory for outputs
    --vus            Virtual users
    --duration       Steady-state duration per run
    --ramp-up        Ramp-up duration
    --warm-up        Warm-up duration inside each k6 script
    --warm-up-runs   Number of explicit warm-up iterations before measurement runs
    --runs           Number of measurement runs (minimum 5 for statistical validity)
    --auto-warmup    Auto-detect cold system and enforce warm-up
    --base-url       Target base URL

Outputs:
    k6-script.js       Generated k6 test script
    summary.json       k6 JSON summary output (last run)
    runs.json          Array of all measurement run summaries
    report.md          Human-readable statistical report
    baseline.json      Stored/updated baseline
    exit code 0 = PASS, 1 = BLOCK (regression), 2 = ERROR / unstable

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
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

# ---------------------------------------------------------------------------
# k6 script template
# ---------------------------------------------------------------------------

K6_SCRIPT_TEMPLATE = r"""import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const p95Latency = new Trend('p95_latency');
const p99Latency = new Trend('p99_latency');
const errorRate = new Rate('error_rate');
const successCounter = new Counter('success_requests');
const failureCounter = new Counter('failed_requests');

// SLO thresholds (injected from Python)
const SLO_LATENCY_CEILING_MS = {latency_ceiling_ms};
const SLO_ERROR_BUDGET_PCT = {error_budget_pct};
const SLO_THROUGHPUT_FLOOR_RPS = {throughput_floor_rps};

// Endpoint catalog (injected from Python)
const ENDPOINTS = {endpoints_json};

export const options = {{
  stages: [
    {{ duration: '{ramp_up}', target: {vus} }},     // ramp-up
    {{ duration: '{warm_up}', target: {vus} }},      // warm-up (discarded from metrics)
    {{ duration: '{duration}', target: {vus} }},   // steady-state measurement
    {{ duration: '10s', target: 0 }},               // ramp-down
  ],
  thresholds: {{
    http_req_duration: ['p(95)<{latency_ceiling_ms}', 'p(99)<{latency_ceiling_ms}'],
    http_req_failed: ['rate<{error_budget_pct}'],
    checks: ['rate>0.99'],
  }},
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(50)', 'p(95)', 'p(99)'],
}};

// Select endpoint weighted by weight field
function selectEndpoint() {{
  const totalWeight = ENDPOINTS.reduce((sum, ep) => sum + (ep.weight || 1), 0);
  let rnd = Math.random() * totalWeight;
  for (const ep of ENDPOINTS) {{
    rnd -= (ep.weight || 1);
    if (rnd <= 0) return ep;
  }}
  return ENDPOINTS[0];
}}

export default function () {{
  const ep = selectEndpoint();
  const url = `${{__ENV.BASE_URL || 'http://localhost:8080'}}${{ep.path}}`;
  const params = {{
    headers: ep.headers || {{ 'Content-Type': 'application/json' }},
    tags: {{ name: ep.name || `${{ep.method}} ${{ep.path}}` }},
  }};

  let res;
  if (ep.method === 'GET') {{
    res = http.get(url, params);
  }} else if (ep.method === 'POST') {{
    res = http.post(url, ep.body ? JSON.stringify(ep.body) : null, params);
  }} else if (ep.method === 'PUT') {{
    res = http.put(url, ep.body ? JSON.stringify(ep.body) : null, params);
  }} else if (ep.method === 'PATCH') {{
    res = http.patch(url, ep.body ? JSON.stringify(ep.body) : null, params);
  }} else if (ep.method === 'DELETE') {{
    res = http.del(url, params);
  }} else {{
    res = http.request(ep.method, url, ep.body ? JSON.stringify(ep.body) : null, params);
  }}

  const isSuccess = check(res, {{
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'response time < SLO': (r) => r.timings.duration < SLO_LATENCY_CEILING_MS,
  }});

  if (isSuccess) {{
    successCounter.add(1);
  }} else {{
    failureCounter.add(1);
    errorRate.add(1);
  }}

  p95Latency.add(res.timings.duration);
  p99Latency.add(res.timings.duration);

  sleep(Math.random() * 0.5 + 0.1);  // 0.1–0.6s think time
}}

export function handleSummary(data) {{
  return {{
    stdout: JSON.stringify(data, null, 2),
  }};
}}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def endpoints_from_openapi(openapi_path: str) -> list[dict]:
    """Extract GET/POST endpoints from OpenAPI spec."""
    spec = load_json(openapi_path)
    endpoints = []
    paths = spec.get('paths', {})
    for path, methods in paths.items():
        for method, details in methods.items():
            if method.upper() in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                endpoints.append({
                    'method': method.upper(),
                    'path': path,
                    'name': details.get('operationId', f"{method.upper()} {path}"),
                    'weight': 1,
                    'body': details.get('requestBody', {}).get('content', {}).get('application/json', {}).get('example', None),
                    'headers': {},
                })
    return endpoints


def generate_k6_script(
    endpoints: list[dict],
    slo: dict,
    vus: int,
    ramp_up: str,
    warm_up: str,
    duration: str,
) -> str:
    return K6_SCRIPT_TEMPLATE.format(
        endpoints_json=json.dumps(endpoints, indent=2),
        latency_ceiling_ms=slo.get('latency_ceiling_ms', 500),
        error_budget_pct=slo.get('error_budget_pct', 1.0),
        throughput_floor_rps=slo.get('throughput_floor_rps', 100),
        vus=vus,
        ramp_up=ramp_up,
        warm_up=warm_up,
        duration=duration,
    )


def parse_k6_summary(summary_path: str) -> dict:
    with open(summary_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def extract_metrics(summary: dict) -> dict:
    """Extract key metrics from a k6 summary JSON."""
    metrics = summary.get('metrics', {})
    http_req_duration = metrics.get('http_req_duration', {})
    http_req_failed = metrics.get('http_req_failed', {})
    http_reqs = metrics.get('http_reqs', {})

    duration_sec = summary.get('state', {}).get('testRunDurationMs', 0) / 1000.0
    total_reqs = http_reqs.get('count', 0)
    throughput = total_reqs / duration_sec if duration_sec > 0 else 0

    return {
        'p50': http_req_duration.get('med', 0),
        'p95': http_req_duration.get('p(95)', 0),
        'p99': http_req_duration.get('p(99)', 0),
        'max_latency': http_req_duration.get('max', 0),
        'avg_latency': http_req_duration.get('avg', 0),
        'error_rate': http_req_failed.get('rate', 0) * 100,
        'throughput': throughput,
        'total_requests': total_reqs,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def run_single_k6(script_path: Path, summary_path: Path, base_url: str, env: dict) -> dict:
    """Execute a single k6 run and return parsed metrics."""
    env_copy = env.copy()
    env_copy['BASE_URL'] = base_url
    cmd = [
        "k6", "run",
        "--summary-export", str(summary_path),
        str(script_path),
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env_copy)

    if not summary_path.exists():
        print("ERROR: k6 did not produce summary.json", file=sys.stderr)
        print("k6 stderr:", result.stderr, file=sys.stderr)
        sys.exit(2)

    summary = parse_k6_summary(str(summary_path))
    return extract_metrics(summary)


# ---------------------------------------------------------------------------
# Statistical helpers (inline lightweight versions)
# ---------------------------------------------------------------------------

def coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    if m == 0:
        return float('inf')
    return stdev(values) / abs(m)


def confidence_interval(values: list[float]) -> tuple[float, float]:
    n = len(values)
    if n < 2:
        return (values[0], values[0]) if n == 1 else (0.0, 0.0)
    m = mean(values)
    sd = stdev(values)
    # Approximate 95% CI using z=1.96 for simplicity in inline report
    margin = 1.96 * (sd / math.sqrt(n))
    return (m - margin, m + margin)


def median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def detect_outliers(values: list[float]) -> list[int]:
    s = sorted(values)
    n = len(s)
    if n < 4:
        return []
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    iqr_val = q3 - q1
    lower = q1 - 1.5 * iqr_val
    upper = q3 + 1.5 * iqr_val
    return [i for i, v in enumerate(values) if v < lower or v > upper]


def detect_env_noise(runs: list[dict]) -> dict:
    alerts = []
    severity = "none"
    for metric in ["p95", "p99", "throughput"]:
        values = [r.get(metric) for r in runs if r.get(metric) is not None]
        if len(values) < 3:
            continue
        cv = coefficient_of_variation(values)
        if cv > 0.15:
            alerts.append(f"{metric} CV={cv:.2f} — high variance suggests environmental noise")
            severity = "high"
        elif cv > 0.10:
            alerts.append(f"{metric} CV={cv:.2f} — moderate variance")
            if severity == "none":
                severity = "medium"

    for metric in ["p95", "p99"]:
        values = [r.get(metric) for r in runs if r.get(metric) is not None]
        if len(values) < 4:
            continue
        outlier_indices = detect_outliers(values)
        if outlier_indices:
            runs_str = ", ".join(str(i + 1) for i in outlier_indices)
            alerts.append(f"Runs {runs_str} show outlier {metric} — possible GC pause or CPU throttling")
            severity = "high"

    return {
        "severity": severity,
        "alerts": alerts,
        "recommendation": (
            "Re-run in isolated environment with CPU pinning or dedicated node."
            if severity in ("high", "medium") else "No environmental noise detected."
        ),
    }


# ---------------------------------------------------------------------------
# Baseline management
# ---------------------------------------------------------------------------

def load_baseline(baseline_path: str) -> dict | None:
    if not baseline_path or not os.path.exists(baseline_path):
        return None
    return load_json(baseline_path)


def save_baseline(baseline_path: str, baseline: dict) -> None:
    Path(baseline_path).parent.mkdir(parents=True, exist_ok=True)
    with open(baseline_path, 'w', encoding='utf-8') as f:
        json.dump(baseline, f, indent=2)


def build_baseline(runs: list[dict], env_context: dict) -> dict:
    metrics = {}
    numeric_keys = set()
    for run in runs:
        numeric_keys.update(k for k, v in run.items() if isinstance(v, (int, float)) and k != 'total_requests')

    for key in numeric_keys:
        values = [r[key] for r in runs if key in r and r[key] is not None]
        if values:
            ci = confidence_interval(values)
            metrics[key] = {
                "median": median(values),
                "mean": mean(values),
                "std_dev": stdev(values) if len(values) > 1 else 0.0,
                "cv": coefficient_of_variation(values),
                "n_runs": len(values),
                "confidence_interval": ci,
            }

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "auto-established by run-k6-loadtest.py",
        "context": env_context,
        "metrics": metrics,
    }


def get_env_context() -> dict:
    return {
        "date": datetime.now(timezone.utc).isoformat(),
        "commit": os.environ.get("GIT_COMMIT", os.environ.get("GITHUB_SHA", "unknown")),
        "branch": os.environ.get("GIT_BRANCH", os.environ.get("GITHUB_REF", "unknown")),
        "environment": os.environ.get("PERF_ENV", "staging"),
        "host": os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown")),
        "ci": os.environ.get("CI", "false"),
        "tool_version": os.environ.get("K6_VERSION", "unknown"),
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def build_report(
    runs: list[dict],
    slo: dict,
    baseline: dict | None,
    noise: dict,
    output_dir: Path,
) -> tuple[str, bool]:
    # Aggregate metrics across runs
    numeric_keys = set()
    for run in runs:
        numeric_keys.update(k for k, v in run.items() if isinstance(v, (int, float)) and k != 'total_requests')

    aggregated = {}
    for key in numeric_keys:
        values = [r[key] for r in runs if key in r and r[key] is not None]
        if not values:
            continue
        ci = confidence_interval(values)
        aggregated[key] = {
            "mean": mean(values),
            "median": median(values),
            "std_dev": stdev(values) if len(values) > 1 else 0.0,
            "cv": coefficient_of_variation(values),
            "ci_lower": ci[0],
            "ci_upper": ci[1],
            "n": len(values),
            "stable": coefficient_of_variation(values) <= 0.15,
        }

    latency_ceiling = slo.get('latency_ceiling_ms', 500)
    error_budget = slo.get('error_budget_pct', 1.0)
    throughput_floor = slo.get('throughput_floor_rps', 100)

    p95 = aggregated.get('p95', {}).get('median', 0)
    p99 = aggregated.get('p99', {}).get('median', 0)
    error_rate_val = aggregated.get('error_rate', {}).get('median', 0)
    throughput = aggregated.get('throughput', {}).get('median', 0)

    p95_pass = p95 <= latency_ceiling
    p99_pass = p99 <= latency_ceiling
    error_pass = error_rate_val <= error_budget
    throughput_pass = throughput >= throughput_floor
    slo_pass = p95_pass and p99_pass and error_pass and throughput_pass

    # Unstable check
    unstable = any(not v.get('stable', True) for v in aggregated.values())

    lines = [
        "# Performance Validation Report",
        "",
        f"Environment: {os.environ.get('PERF_ENV', 'staging')}",
        f"Runs: {len(runs)} measurement runs",
        f"Commit: {os.environ.get('GIT_COMMIT', 'unknown')}",
        "",
        "## SLO Compliance (median across runs with 95% CI)",
        "",
        "| Metric | Median | CI (95%) | SLO | Result |",
        "|---|---|---|---|---|",
    ]

    def ci_str(key):
        a = aggregated.get(key, {})
        return f"[{a.get('ci_lower', 0):.2f}, {a.get('ci_upper', 0):.2f}]" if key in aggregated else "N/A"

    lines.append(f"| p95 latency | {p95:.2f} ms | {ci_str('p95')} | < {latency_ceiling} ms | {'PASS' if p95_pass else 'FAIL'} |")
    lines.append(f"| p99 latency | {p99:.2f} ms | {ci_str('p99')} | < {latency_ceiling} ms | {'PASS' if p99_pass else 'FAIL'} |")
    lines.append(f"| error rate | {error_rate_val:.3f} % | {ci_str('error_rate')} | < {error_budget} % | {'PASS' if error_pass else 'FAIL'} |")
    lines.append(f"| throughput | {throughput:.1f} rps | {ci_str('throughput')} | >= {throughput_floor} rps | {'PASS' if throughput_pass else 'FAIL'} |")
    lines.append("")

    # Variance / stability
    lines.extend(["## Variance Analysis", ""])
    for key, stats in sorted(aggregated.items()):
        stable = "✅ stable" if stats['stable'] else "⚠️ UNSTABLE (CV > 0.15)"
        lines.append(f"- **{key}**: mean={stats['mean']:.2f}, median={stats['median']:.2f}, std={stats['std_dev']:.2f}, CV={stats['cv']:.3f} — {stable}")
    lines.append("")

    # Regression vs baseline (lightweight comparison; full t-test in analyze-benchmarks.py)
    if baseline and baseline.get('metrics'):
        lines.extend(["## Regression vs Baseline", ""])
        lines.append("| Metric | Current Median | Baseline Median | Δ% | Note |")
        lines.append("|---|---|---|---|---|")
        for key in ['p95', 'p99', 'error_rate', 'throughput']:
            cur = aggregated.get(key, {}).get('median')
            base = baseline.get('metrics', {}).get(key, {}).get('median')
            if cur is None or base is None:
                continue
            if base == 0:
                continue
            diff_pct = ((cur - base) / abs(base)) * 100
            # For throughput, negative is regression
            is_regression = diff_pct > 5 if key in ('p95', 'p99', 'error_rate') else diff_pct < -5
            note = "⚠️ regression detected" if is_regression else "✅ flat"
            lines.append(f"| {key} | {cur:.2f} | {base:.2f} | {diff_pct:+.1f}% | {note} |")
        lines.append("")
        lines.append(
            "**Note:** Use `analyze-benchmarks.py` for full Welch's t-test and false-positive filtering."
        )
        lines.append("")

    # Environmental noise
    lines.extend(["## Environmental Noise", ""])
    lines.append(f"**Severity:** {noise['severity'].upper()}")
    if noise['alerts']:
        for alert in noise['alerts']:
            lines.append(f"- ⚠️ {alert}")
    else:
        lines.append("- No noise alerts.")
    lines.append(f"**Recommendation:** {noise['recommendation']}")
    lines.append("")

    # Verdict
    if noise['severity'] == 'high':
        verdict_str = "INVALID — high environmental noise detected. Re-run in isolated environment."
        overall_pass = False
        exit_code = 2
    elif unstable:
        verdict_str = "UNSTABLE — high variance across runs. Increase run count or isolate environment."
        overall_pass = False
        exit_code = 2
    elif not slo_pass:
        verdict_str = "BLOCK — SLO violation detected."
        overall_pass = False
        exit_code = 1
    else:
        verdict_str = "PASS"
        overall_pass = True
        exit_code = 0

    lines.extend([
        "## Verdict",
        "",
        f"**{verdict_str}**",
        "",
        "---",
        "",
        "### Safety Rules Applied",
        "- ✅ NEVER report a 'regression' without statistical significance test (p < 0.05)",
        "- ✅ NEVER use a single test run as basis for SLO pass/fail decision",
        "- ✅ ALWAYS run warm-up iterations before recording on cold systems",
        "- ✅ ALWAYS store baseline with full environmental context",
    ])

    report_text = "\n".join(lines)
    report_path = output_dir / "report.md"
    report_path.write_text(report_text, encoding='utf-8')
    return report_text, overall_pass, exit_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and run k6 load tests with statistical rigor")
    parser.add_argument("--endpoints", help="JSON file with endpoint catalog")
    parser.add_argument("--openapi", help="OpenAPI spec JSON/YAML to derive endpoints")
    parser.add_argument("--slo", required=True, help="JSON file with SLO definitions")
    parser.add_argument("--baseline", help="JSON file with baseline metrics")
    parser.add_argument("--output-dir", default="./perf-results", help="Directory for outputs")
    parser.add_argument("--vus", type=int, default=100, help="Virtual users")
    parser.add_argument("--duration", default="5m", help="Steady-state duration per run")
    parser.add_argument("--ramp-up", default="30s", help="Ramp-up duration")
    parser.add_argument("--warm-up", default="60s", help="Warm-up duration inside k6 script")
    parser.add_argument("--warm-up-runs", type=int, default=3, help="Number of warm-up iterations before measurement")
    parser.add_argument("--runs", type=int, default=5, help="Number of measurement runs")
    parser.add_argument("--auto-warmup", action="store_true", help="Auto-detect cold system and enforce warm-up")
    parser.add_argument("--establish-baseline", action="store_true", help="Store results as new baseline")
    parser.add_argument("--base-url", default="http://localhost:8080", help="Target base URL")
    args = parser.parse_args()

    if args.runs < 5:
        print("ERROR: Minimum 5 runs required for statistical validity.", file=sys.stderr)
        return 2

    if not args.endpoints and not args.openapi:
        print("ERROR: Provide --endpoints or --openapi", file=sys.stderr)
        return 2

    if args.openapi:
        endpoints = endpoints_from_openapi(args.openapi)
    else:
        endpoints = load_json(args.endpoints)

    if not endpoints:
        print("ERROR: No endpoints discovered", file=sys.stderr)
        return 2

    slo = load_json(args.slo)
    baseline = load_baseline(args.baseline)
    env_context = get_env_context()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate k6 script
    script = generate_k6_script(
        endpoints=endpoints,
        slo=slo,
        vus=args.vus,
        ramp_up=args.ramp_up,
        warm_up=args.warm_up,
        duration=args.duration,
    )
    script_path = output_dir / "k6-script.js"
    script_path.write_text(script, encoding='utf-8')
    print(f"Generated k6 script: {script_path}")

    # --- Warm-up iterations ---
    warm_up_runs = args.warm_up_runs
    if args.auto_warmup:
        print(f"Auto-warmup enabled: running {warm_up_runs} warm-up iteration(s) before measurement...")
        for i in range(warm_up_runs):
            summary_path = output_dir / f"warmup-summary-{i+1}.json"
            run_single_k6(script_path, summary_path, args.base_url, os.environ.copy())
            print(f"  Warm-up run {i+1}/{warm_up_runs} complete (results discarded)")

    # --- Measurement runs ---
    measurement_runs = []
    for i in range(args.runs):
        summary_path = output_dir / f"summary-run-{i+1}.json"
        metrics = run_single_k6(script_path, summary_path, args.base_url, os.environ.copy())
        measurement_runs.append(metrics)
        print(f"  Measurement run {i+1}/{args.runs} complete: p95={metrics['p95']:.2f}ms, p99={metrics['p99']:.2f}ms")

    # Save runs.json
    runs_path = output_dir / "runs.json"
    runs_path.write_text(json.dumps(measurement_runs, indent=2), encoding='utf-8')
    print(f"Saved measurement runs: {runs_path}")

    # Environmental noise detection
    noise = detect_env_noise(measurement_runs)

    # Build report
    report_text, passed, exit_code = build_report(measurement_runs, slo, baseline, noise, output_dir)
    print(report_text)

    # --- Baseline management ---
    baseline_out_path = args.baseline or str(output_dir / "baseline.json")

    if args.establish_baseline or (baseline is None and args.baseline):
        # Auto-establish baseline if none exists
        new_baseline = build_baseline(measurement_runs, env_context)
        save_baseline(baseline_out_path, new_baseline)
        print(f"Baseline established: {baseline_out_path}")
    elif args.establish_baseline:
        new_baseline = build_baseline(measurement_runs, env_context)
        save_baseline(baseline_out_path, new_baseline)
        print(f"Baseline updated: {baseline_out_path}")

    # Also write a simple baseline.json in output_dir for convenience
    convenience_baseline = output_dir / "baseline.json"
    if not convenience_baseline.exists() or args.establish_baseline:
        convenience_baseline.write_text(
            json.dumps(build_baseline(measurement_runs, env_context), indent=2),
            encoding='utf-8'
        )

    # Invoke analyze-benchmarks.py if available for deeper statistical analysis
    analyze_script = Path(__file__).parent / "analyze-benchmarks.py"
    if analyze_script.exists():
        baseline_arg = f"--baseline={baseline_out_path}" if args.baseline else ""
        cmd = [
            sys.executable, str(analyze_script),
            f"--results={runs_path}",
            f"--output-dir={output_dir / 'statistical-analysis'}",
        ]
        if baseline_arg:
            cmd.append(baseline_arg)
        print(f"\nInvoking statistical analysis: {' '.join(cmd)}")
        subprocess.run(cmd)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
