#!/usr/bin/env python3
"""aggregate_telemetry.py — Session-level performance observability.

Reads telemetry JSON files and produces aggregated session reports.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Telemetry Aggregator")
    parser.add_argument("--files", nargs="+", required=True, help="Telemetry JSON files")
    parser.add_argument("--output", default="telemetry_summary.json")
    args = parser.parse_args()

    all_events = []
    for f in args.files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        if isinstance(data, list):
            all_events.extend(data)
        else:
            all_events.append(data)

    durations = [e.get("duration_ms", 0) for e in all_events]
    tokens_in = [e.get("token_in", 0) for e in all_events]
    tokens_out = [e.get("token_out", 0) for e in all_events]
    errors = [e for e in all_events if e.get("exit_status", "ok") != "ok"]

    by_skill = {}
    for e in all_events:
        skill = e.get("skill", "unknown")
        by_skill.setdefault(skill, []).append(e)

    skill_summary = {}
    for skill, events in by_skill.items():
        skill_summary[skill] = {
            "invocations": len(events),
            "avg_duration_ms": round(statistics.mean([e.get("duration_ms", 0) for e in events]), 2) if events else 0,
            "total_tokens_in": sum(e.get("token_in", 0) for e in events),
            "total_tokens_out": sum(e.get("token_out", 0) for e in events),
            "errors": sum(1 for e in events if e.get("exit_status", "ok") != "ok"),
        }

    report = {
        "sessions": len(args.files),
        "total_events": len(all_events),
        "total_errors": len(errors),
        "avg_duration_ms": round(statistics.mean(durations), 2) if durations else 0,
        "median_duration_ms": round(statistics.median(durations), 2) if durations else 0,
        "total_tokens_in": sum(tokens_in),
        "total_tokens_out": sum(tokens_out),
        "by_skill": skill_summary,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Aggregated {report['total_events']} events from {report['sessions']} sessions.")
    print(f"Errors: {report['total_errors']}, Avg duration: {report['avg_duration_ms']}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
