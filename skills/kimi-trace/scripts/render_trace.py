#!/usr/bin/env python3
"""render_trace.py — Session replay and visualization.

Reads a session telemetry JSON file and renders a timeline report.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Kimi Trace Renderer")
    parser.add_argument("--session", required=True, help="Session telemetry JSON file")
    parser.add_argument("--output", default="trace_report.md")
    args = parser.parse_args()

    data = json.loads(Path(args.session).read_text(encoding="utf-8"))
    events = data if isinstance(data, list) else data.get("events", [data])

    lines = [
        "# Session Trace Report",
        "",
        f"**Events:** {len(events)}",
        "",
        "| Time | Phase | Skill | Duration (ms) | Tokens In | Tokens Out | Status |",
        "|------|-------|-------|---------------|-----------|------------|--------|",
    ]

    total_in = 0
    total_out = 0
    for evt in events:
        ts = evt.get("timestamp", "N/A")
        phase = evt.get("phase", "-")
        skill = evt.get("skill", "-")
        duration = evt.get("duration_ms", "-")
        tin = evt.get("token_in", 0)
        tout = evt.get("token_out", 0)
        status = evt.get("exit_status", "-")
        lines.append(f"| {ts} | {phase} | {skill} | {duration} | {tin} | {tout} | {status} |")
        total_in += tin
        total_out += tout

    lines.extend([
        "",
        f"**Total tokens in:** {total_in}",
        f"**Total tokens out:** {total_out}",
    ])

    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    print(f"Trace report written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
