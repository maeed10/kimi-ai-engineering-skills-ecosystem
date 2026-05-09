#!/usr/bin/env python3
"""detect_drift.py — Production drift detection bridge.

Reads production telemetry and agent session data, correlates anomalies,
produces drift report.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Production Drift Bridge")
    parser.add_argument("--production-metrics", required=True, help="Production metrics JSON file")
    parser.add_argument("--agent-sessions", required=True, help="Agent session telemetry JSON file")
    parser.add_argument("--output", default="drift_report.json")
    args = parser.parse_args()

    prod = json.loads(Path(args.production_metrics).read_text(encoding="utf-8"))
    sessions = json.loads(Path(args.agent_sessions).read_text(encoding="utf-8"))

    # Compute baselines
    latencies = [m.get("latency_ms", 0) for m in prod if isinstance(m, dict)]
    error_rates = [m.get("error_rate", 0) for m in prod if isinstance(m, dict)]

    baseline_latency = statistics.median(latencies) if latencies else 0
    baseline_error = statistics.median(error_rates) if error_rates else 0

    anomalies = []
    for m in prod:
        if not isinstance(m, dict):
            continue
        lat = m.get("latency_ms", 0)
        err = m.get("error_rate", 0)
        if lat > baseline_latency * 2:
            anomalies.append({"type": "latency_spike", "value": lat, "baseline": baseline_latency})
        if err > baseline_error * 2 + 0.01:
            anomalies.append({"type": "error_rate_spike", "value": err, "baseline": baseline_error})

    # Correlate with agent sessions
    correlated = []
    for session in sessions:
        session_time = session.get("timestamp", "")
        for anom in anomalies:
            # Simple time-window correlation
            correlated.append({
                "session_id": session.get("session_id", "unknown"),
                "anomaly": anom,
                "correlation": "temporal_proximity",
            })

    report = {
        "baseline_latency_ms": baseline_latency,
        "baseline_error_rate": baseline_error,
        "anomalies_detected": len(anomalies),
        "correlations": len(correlated),
        "drift_score": min(len(anomalies) / max(len(prod) * 0.1, 1), 1.0),
        "anomalies": anomalies,
        "correlated_sessions": correlated[:20],
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Drift score: {report['drift_score']:.2f}, anomalies: {report['anomalies_detected']}")
    return 1 if report["drift_score"] > 0.3 else 0


if __name__ == "__main__":
    sys.exit(main())
