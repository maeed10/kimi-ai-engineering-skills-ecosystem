#!/usr/bin/env python3
"""
drift-detector.py — Skill Orchestrator Behavioral Drift Detector

Reads historical session logs (JSONL) and calculates baseline tool-call
frequency per skill. Flags deviations >2 standard deviations from baseline
as potential anomalies. Generates structured alert reports.

Usage:
    python drift-detector.py --history .kimi/telemetry/sessions.jsonl --current .kimi/telemetry/current.jsonl
    python drift-detector.py --history sessions.jsonl --window-days 14 --alert-threshold 2.0
    python drift-detector.py --history sessions.jsonl --baseline-out baseline.json
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple


class BaselineMetric(NamedTuple):
    mean: float
    std: float
    count: int


class DriftAlert(NamedTuple):
    skill: str
    metric: str
    baseline_mean: float
    baseline_std: float
    observed: float
    z_score: float
    severity: str
    action: str


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def build_baseline(
    events: Iterator[Dict[str, Any]], window_days: int
) -> Dict[str, Dict[str, BaselineMetric]]:
    """
    Build per-skill baseline metrics from historical events.

    Metrics tracked:
    - tool_call_count: number of tool calls per session
    - token_cost_mean: average token cost per tool call
    - unique_tools: number of distinct tool types used per session
    - contradiction_rate: contradictions per 100 sessions
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # skill -> metric -> list of values
    data: Dict[str, Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for event in events:
        ts = parse_iso(event.get("timestamp", ""))
        if not ts or ts < cutoff:
            continue

        skill = event.get("skill")
        if not skill:
            continue

        # tool_call events
        if event.get("event_type") == "tool_call":
            data[skill]["tool_call_count"].append(1)
            tc = event.get("token_cost")
            if tc is not None:
                data[skill]["token_cost_per_call"].append(float(tc))
            tool = event.get("tool")
            if tool:
                data[skill]["tool_types"].append(tool)

        # contradiction events
        if event.get("event_type") == "contradiction_resolve":
            data[skill]["contradiction_count"].append(1)

    # Convert lists to session-aggregated metrics
    baselines: Dict[str, Dict[str, BaselineMetric]] = {}
    for skill, metrics in data.items():
        baselines[skill] = {}

        # tool_call_count: sum per session approximation (each event = 1 call)
        tcc = metrics.get("tool_call_count", [0])
        baselines[skill]["tool_call_count"] = _compute_metric(tcc)

        # token_cost_per_call
        tpc = metrics.get("token_cost_per_call", [0])
        baselines[skill]["token_cost_per_call"] = _compute_metric(tpc)

        # unique_tools: count of distinct tool types per session approximation
        tool_types = metrics.get("tool_types", [])
        # Approximate: use the count of unique tools across all events as proxy
        unique_count = len(set(tool_types)) if tool_types else 0
        baselines[skill]["unique_tools"] = BaselineMetric(
            mean=float(unique_count),
            std=0.0,
            count=len(tool_types),
        )

        # contradiction_rate
        cc = metrics.get("contradiction_count", [0])
        baselines[skill]["contradiction_rate"] = _compute_metric(cc)

    return baselines


def _compute_metric(values: List[float]) -> BaselineMetric:
    """Calculate mean, std, and count."""
    if not values:
        return BaselineMetric(mean=0.0, std=0.0, count=0)
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n if n > 0 else 0.0
    std = math.sqrt(variance)
    return BaselineMetric(mean=mean, std=std, count=n)


def analyze_current_session(
    events: Iterator[Dict[str, Any]],
    baselines: Dict[str, Dict[str, BaselineMetric]],
    threshold_sigma: float,
) -> List[DriftAlert]:
    """Compare current session events against baselines and flag anomalies."""
    # Aggregate current session by skill
    current: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "tool_call_count": 0,
            "token_costs": [],
            "tool_types": set(),
            "contradiction_count": 0,
        }
    )

    for event in events:
        skill = event.get("skill")
        if not skill:
            continue

        if event.get("event_type") == "tool_call":
            current[skill]["tool_call_count"] += 1
            tc = event.get("token_cost")
            if tc is not None:
                current[skill]["token_costs"].append(float(tc))
            tool = event.get("tool")
            if tool:
                current[skill]["tool_types"].add(tool)

        if event.get("event_type") == "contradiction_resolve":
            current[skill]["contradiction_count"] += 1

    alerts: List[DriftAlert] = []
    for skill, metrics in current.items():
        baseline = baselines.get(skill)
        if not baseline:
            # No baseline yet — flag as info
            alerts.append(
                DriftAlert(
                    skill=skill,
                    metric="baseline_missing",
                    baseline_mean=0.0,
                    baseline_std=0.0,
                    observed=0.0,
                    z_score=0.0,
                    severity="info",
                    action="Collect more historical data to establish baseline.",
                )
            )
            continue

        # Check each metric
        for metric_name, observed_val, baseline_key in [
            ("tool_call_count", metrics["tool_call_count"], "tool_call_count"),
            (
                "token_cost_per_call",
                sum(metrics["token_costs"]) / len(metrics["token_costs"])
                if metrics["token_costs"]
                else 0.0,
                "token_cost_per_call",
            ),
            (
                "unique_tools",
                len(metrics["tool_types"]),
                "unique_tools",
            ),
            (
                "contradiction_rate",
                metrics["contradiction_count"],
                "contradiction_rate",
            ),
        ]:
            bm = baseline.get(baseline_key)
            if not bm or bm.count == 0:
                continue
            if bm.std == 0:
                # All values identical; treat any deviation as 1σ
                z_score = 1.0 if observed_val != bm.mean else 0.0
            else:
                z_score = abs(observed_val - bm.mean) / bm.std

            if z_score > threshold_sigma:
                severity = (
                    "critical" if z_score > 3.0 else "warning" if z_score > 2.0 else "info"
                )
                action = _suggest_action(skill, metric_name, observed_val, bm)
                alerts.append(
                    DriftAlert(
                        skill=skill,
                        metric=metric_name,
                        baseline_mean=bm.mean,
                        baseline_std=bm.std,
                        observed=observed_val,
                        z_score=z_score,
                        severity=severity,
                        action=action,
                    )
                )

    return sorted(alerts, key=lambda a: a.z_score, reverse=True)


def _suggest_action(
    skill: str, metric: str, observed: float, baseline: BaselineMetric
) -> str:
    if metric == "tool_call_count":
        if observed > baseline.mean:
            return f"Investigate why {skill} is making more tool calls than usual. Possible runaway loop or misrouted task."
        return f"{skill} is unusually idle. Verify skill activation succeeded."
    if metric == "token_cost_per_call":
        return f"Review {skill} token efficiency. Large payloads or excessive context may be inflating costs."
    if metric == "unique_tools":
        if observed > baseline.mean:
            return f"{skill} is using unexpected tools. Verify tool routing and skill scope."
        return f"{skill} tool usage narrowed. May indicate reduced task complexity or a stuck workflow."
    if metric == "contradiction_rate":
        return f"High contradiction rate in {skill}. Review active skill combinations for conflicting directives."
    return f"Review {skill} behavior for {metric} anomaly."


def print_alerts(alerts: List[DriftAlert], threshold: float) -> None:
    print("=" * 70)
    print("BEHAVIORAL DRIFT DETECTION REPORT")
    print("=" * 70)
    print(f"Threshold: {threshold}σ  |  Alerts generated: {len(alerts)}")
    print("-" * 70)

    if not alerts:
        print("No behavioral drift detected. All skills within baseline.")
        print("=" * 70)
        return

    for alert in alerts:
        print(f"\n  [{alert.severity.upper()}] {alert.skill}  |  {alert.metric}")
        print(f"    Baseline: μ={alert.baseline_mean:.2f}, σ={alert.baseline_std:.2f}")
        print(f"    Observed: {alert.observed:.2f}  |  Z-score: {alert.z_score:.2f}")
        print(f"    Action:   {alert.action}")

    print("\n" + "=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect behavioral drift in skill orchestrator telemetry."
    )
    parser.add_argument(
        "--history", required=True, help="Path to historical sessions.jsonl"
    )
    parser.add_argument(
        "--current",
        help="Path to current session JSONL (defaults to same as history)",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=14,
        help="Days of history to use for baseline (default: 14)",
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=2.0,
        help="Z-score threshold for alerts in σ (default: 2.0)",
    )
    parser.add_argument(
        "--baseline-out",
        help="Write computed baseline JSON to file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit report as JSON",
    )
    args = parser.parse_args()

    history_path = Path(args.history)
    if not history_path.exists():
        print(f"Error: history file not found: {history_path}", file=sys.stderr)
        return 1

    current_path = Path(args.current) if args.current else history_path
    if not current_path.exists():
        print(f"Error: current file not found: {current_path}", file=sys.stderr)
        return 1

    # Build baseline from history
    baselines = build_baseline(read_jsonl(history_path), args.window_days)

    if args.baseline_out:
        baseline_serializable = {
            skill: {
                metric: {"mean": bm.mean, "std": bm.std, "count": bm.count}
                for metric, bm in metrics.items()
            }
            for skill, metrics in baselines.items()
        }
        Path(args.baseline_out).write_text(
            json.dumps(baseline_serializable, indent=2), encoding="utf-8"
        )
        print(f"Baseline written to {args.baseline_out}")

    # Analyze current session
    alerts = analyze_current_session(
        read_jsonl(current_path), baselines, args.alert_threshold
    )

    if args.json:
        report = {
            "threshold_sigma": args.alert_threshold,
            "alert_count": len(alerts),
            "alerts": [
                {
                    "skill": a.skill,
                    "metric": a.metric,
                    "baseline_mean": a.baseline_mean,
                    "baseline_std": a.baseline_std,
                    "observed": a.observed,
                    "z_score": a.z_score,
                    "severity": a.severity,
                    "action": a.action,
                }
                for a in alerts
            ],
        }
        print(json.dumps(report, indent=2))
    else:
        print_alerts(alerts, args.alert_threshold)

    # Exit code: 0 = no drift, 1 = drift detected (CI block)
    return 1 if any(a.severity in ("warning", "critical") for a in alerts) else 0


if __name__ == "__main__":
    sys.exit(main())
