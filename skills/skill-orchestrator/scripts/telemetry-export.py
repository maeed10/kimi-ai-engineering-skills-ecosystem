#!/usr/bin/env python3
"""
telemetry-export.py — Skill Orchestrator Telemetry Exporter

Reads session logs in JSONL format from `.kimi/telemetry/sessions.jsonl`
and exports to Splunk / Datadog / ELK-compatible structured JSON.

Supports filtering by skill, date range, or risk threshold.

Usage:
    python telemetry-export.py --input .kimi/telemetry/sessions.jsonl --output splunk.json
    python telemetry-export.py --input sessions.jsonl --skill code-tester --since 2026-07-01
    python telemetry-export.py --input sessions.jsonl --risk-above 0.5 --format datadog
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


def parse_iso(ts: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp string to datetime."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield valid JSON objects from a JSONL file."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def format_splunk(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert event to Splunk HEC-compatible JSON."""
    return {
        "time": parse_iso(event.get("timestamp", "")).timestamp() if parse_iso(event.get("timestamp", "")) else datetime.now(timezone.utc).timestamp(),
        "source": event.get("source", "kimi-skill-orchestrator"),
        "sourcetype": "_json",
        "host": event.get("session_id", "unknown"),
        "event": event,
    }


def format_datadog(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert event to Datadog log-compatible JSON."""
    return {
        "timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "hostname": event.get("session_id", "unknown"),
        "service": event.get("source", "kimi-skill-orchestrator"),
        "status": "info",
        "message": json.dumps(event),
        "attributes": event,
    }


def format_elk(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert event to ELK / Elasticsearch-compatible JSON."""
    return {
        "@timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "event": event,
    }


def filter_event(
    event: Dict[str, Any],
    skill: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    risk_above: Optional[float] = None,
) -> bool:
    """Return True if event passes all active filters."""
    ts = parse_iso(event.get("timestamp", ""))
    if since and ts and ts < since:
        return False
    if until and ts and ts > until:
        return False
    if skill and event.get("skill") != skill:
        return False
    if event_type and event.get("event_type") != event_type:
        return False
    if risk_above is not None:
        risk = event.get("risk_score")
        if risk is None or float(risk) <= risk_above:
            return False
    return True


def export_telemetry(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        return 1

    since = parse_iso(args.since) if args.since else None
    until = parse_iso(args.until) if args.until else None
    risk_above = float(args.risk_above) if args.risk_above is not None else None

    events: List[Dict[str, Any]] = []
    for event in read_jsonl(input_path):
        if filter_event(
            event,
            skill=args.skill,
            event_type=args.event_type,
            since=since,
            until=until,
            risk_above=risk_above,
        ):
            events.append(event)

    formatter = {
        "splunk": format_splunk,
        "datadog": format_datadog,
        "elk": format_elk,
        "raw": lambda e: e,
    }.get(args.format, format_splunk)

    formatted = [formatter(e) for e in events]

    report = {
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path.resolve()),
        "format": args.format,
        "filters": {
            "skill": args.skill,
            "event_type": args.event_type,
            "since": args.since,
            "until": args.until,
            "risk_above": args.risk_above,
        },
        "total_events": len(formatted),
        "events": formatted,
    }

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Exported {len(formatted)} events to {output_path}")
    else:
        print(json.dumps(report, indent=2))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export skill orchestrator telemetry to SIEM-compatible JSON."
    )
    parser.add_argument("--input", required=True, help="Path to sessions.jsonl")
    parser.add_argument("--output", help="Output JSON file path (stdout if omitted)")
    parser.add_argument(
        "--format",
        choices=["splunk", "datadog", "elk", "raw"],
        default="splunk",
        help="Target SIEM format",
    )
    parser.add_argument("--skill", help="Filter by skill name")
    parser.add_argument("--event-type", help="Filter by event type")
    parser.add_argument("--since", help="ISO date: include events on or after")
    parser.add_argument("--until", help="ISO date: include events on or before")
    parser.add_argument(
        "--risk-above",
        type=float,
        help="Filter events with risk_score > threshold",
    )
    args = parser.parse_args()

    return export_telemetry(args)


if __name__ == "__main__":
    sys.exit(main())
