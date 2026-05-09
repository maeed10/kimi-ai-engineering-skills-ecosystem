#!/usr/bin/env python3
"""
triage_incident.py — Correlates alerts and generates an incident report skeleton.

Usage:
    python triage_incident.py \\
        --alerts "HighErrorRate,LatencySpike" \\
        --service api-prod \\
        --since "2024-05-06T14:00:00Z" \\
        --output incident_report.md

This script is designed to be run from a developer workstation or CI pipeline
when multiple alerts fire. It produces a structured incident record that can
be pasted into Slack, PagerDuty, or your incident tracker.
"""

import argparse
import datetime
import json
import os
import re
import sys
from typing import List, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Severity heuristics
# ---------------------------------------------------------------------------

SEV1_KEYWORDS = {
    "outage", "down", "data loss", "corruption", "breach", "security",
    "payment failure", "auth failure", "database down", "critical",
}

SEV2_KEYWORDS = {
    "high error rate", "latency spike", "degraded", "unavailable",
    "queue depth", "memory leak", "oom", "5xx", "slow",
}

SEV3_KEYWORDS = {
    "elevated", "minor", "warning", "disk usage", "certificate expiry",
    "backup failed", "stuck", "retry",
}

PLAYBOOK_MAP = {
    "database": "Database Outage / Connection Pool Exhaustion",
    "db": "Database Outage / Connection Pool Exhaustion",
    "connection pool": "Database Outage / Connection Pool Exhaustion",
    "postgres": "Database Outage / Connection Pool Exhaustion",
    "mysql": "Database Outage / Connection Pool Exhaustion",
    "5xx": "API Failure / 5xx Spike",
    "api": "API Failure / 5xx Spike",
    "error rate": "API Failure / 5xx Spike",
    "latency": "API Failure / 5xx Spike",
    "memory": "Memory Leak / OOMKill",
    "oom": "Memory Leak / OOMKill",
    "restart": "Memory Leak / OOMKill",
    "ddos": "DDoS / Traffic Anomaly",
    "traffic spike": "DDoS / Traffic Anomaly",
    "rate limit": "DDoS / Traffic Anomaly",
    "cdn": "CDN / Cache Failure",
    "cache": "CDN / Cache Failure",
    "queue": "Message Queue Backlog",
    "consumer lag": "Message Queue Backlog",
    "dlq": "Message Queue Backlog",
    "third party": "Third-Party Dependency Failure",
    "integration": "Third-Party Dependency Failure",
    "external": "Third-Party Dependency Failure",
    "disk": "Disk Full / Storage Exhaustion",
    "storage": "Disk Full / Storage Exhaustion",
    "certificate": "TLS / Certificate Expiry",
    "tls": "TLS / Certificate Expiry",
    "deploy": "Deployment Failure / Rollback Stuck",
    "rollout": "Deployment Failure / Rollback Stuck",
    "canary": "Deployment Failure / Rollback Stuck",
}


def _normalize_alert_name(name: str) -> str:
    """Convert camelCase / PascalCase / snake_case to spaced lowercase."""
    # Insert space before uppercase letters, handling acronyms correctly:
    # - Space before an uppercase that follows a lowercase letter (camelCase boundary)
    # - Space before an uppercase that is followed by a lowercase letter (end of acronym)
    spaced = re.sub(r"((?<=[a-z])[A-Z]|(?!^)[A-Z](?=[a-z]))", r" \1", name)
    # Replace underscores and hyphens with spaces
    spaced = re.sub(r"[_\-]", " ", spaced)
    return spaced.lower()


def severity_from_alerts(alerts: List[str]) -> str:
    """
    Score severity based on alert names. Returns one of SEV1/SEV2/SEV3/SEV4.
    """
    normalized = " ".join(_normalize_alert_name(a) for a in alerts)
    s1_score = sum(1 for kw in SEV1_KEYWORDS if kw in normalized)
    s2_score = sum(1 for kw in SEV2_KEYWORDS if kw in normalized)
    s3_score = sum(1 for kw in SEV3_KEYWORDS if kw in normalized)

    if s1_score > 0:
        return "SEV1"
    if s2_score > 0:
        return "SEV2"
    if s3_score > 0:
        return "SEV3"
    return "SEV4"


def playbook_from_alerts(alerts: List[str]) -> List[str]:
    """Suggest relevant playbooks based on alert names."""
    normalized = " ".join(_normalize_alert_name(a) for a in alerts)
    matches: List[str] = []
    for kw, playbook in PLAYBOOK_MAP.items():
        if kw in normalized and playbook not in matches:
            matches.append(playbook)
    return matches


def now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def parse_iso8601(ts: str) -> datetime.datetime:
    """Parse ISO-8601 timestamp with or without Z."""
    ts = ts.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(ts)


def format_iso8601(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_incident_id() -> str:
    """Generate a simple incident ID based on date."""
    today = now_utc().strftime("%Y%m%d")
    # In a real system, this would query the incident tracker for the next sequence.
    return f"INC-{today}-001"


def suggest_deploy_suspect(since: datetime.datetime) -> str:
    """
    Suggest checking recent deploys. In a real system this would query
    the deployment API (GitHub Actions, ArgoCD, etc.).
    """
    lookback = since - datetime.timedelta(minutes=30)
    return (
        f"Check deployments between {format_iso8601(lookback)} and {format_iso8601(since)}. "
        "Common suspect: last deploy + 5 minutes."
    )


def build_timeline(alerts: List[str], since: datetime.datetime) -> List[Dict[str, str]]:
    """Build a skeleton timeline from the alert list."""
    timeline = []
    for i, alert in enumerate(alerts):
        ts = since + datetime.timedelta(minutes=i * 2)
        timeline.append({
            "time": format_iso8601(ts),
            "event": f"Alert `{alert}` fired",
            "actor": "Monitoring",
            "note": "",
        })
    # Add generic next steps
    timeline.append({
        "time": format_iso8601(since + datetime.timedelta(minutes=len(alerts) * 2 + 2)),
        "event": "On-call acknowledged",
        "actor": "On-call engineer",
        "note": "",
    })
    timeline.append({
        "time": format_iso8601(since + datetime.timedelta(minutes=len(alerts) * 2 + 5)),
        "event": "Triage in progress: correlating metrics, logs, traces",
        "actor": "On-call engineer",
        "note": "",
    })
    return timeline


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_markdown_report(
    incident_id: str,
    alerts: List[str],
    service: str,
    since: datetime.datetime,
    severity: str,
    playbooks: List[str],
) -> str:
    timeline = build_timeline(alerts, since)
    playbook_lines = "\n".join(f"- [{pb}](references/incident_playbooks.md)" for pb in playbooks) or "- None identified — manual triage required."

    lines = [
        f"# {incident_id} — Incident Report (Draft)",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f'| **Severity** | {severity} |',
        f'| **Status** | Investigating |',
        f'| **Started** | {format_iso8601(since)} |',
        f'| **Detected by** | {", ".join(alerts)} |',
        f'| **Affected service** | {service} |',
        '| **Customer impact** | *TODO: quantify % users, regions, features* |',
        '| **Incident commander** | *TODO: assign* |',
        '| **Slack channel** | *TODO: #inc-<id>* |',
        "",
        "## Triage Summary",
        "",
        f"- **Alerts firing:** {', '.join(f'`{a}`' for a in alerts)}",
        f"- **Suggested severity:** {severity}",
        f"- **Deployment suspect:** {suggest_deploy_suspect(since)}",
        "",
        "## Suggested Playbooks",
        "",
        playbook_lines,
        "",
        "## Timeline (skeleton)",
        "",
        "| Time (UTC) | Event | Actor |",
        "|------------|-------|-------|",
    ]

    for entry in timeline:
        lines.append(f"| {entry['time']} | {entry['event']} | {entry['actor']} |")

    lines.extend([
        "",
        "## Immediate Actions",
        "",
        "- [ ] Confirm customer impact (check error rate, latency, support tickets)",
        "- [ ] Check for recent deploy / config change / infrastructure change",
        "- [ ] Correlate metrics, logs, and traces around the incident start time",
        "- [ ] Load the appropriate playbook from `references/incident_playbooks.md`",
        "- [ ] If customer impact confirmed, mitigate first, root-cause later",
        "- [ ] Open war-room bridge for SEV1/SEV2 if cross-team coordination needed",
        "",
        "## Observability Quick Links (populate)",
        "",
        f"- **Metrics dashboard:** `<Grafana/Datadog link for {service}>`",
        f"- **Logs:** `<ELK/Loki/Splunk link for {service}>`",
        f"- **Traces:** `<Jaeger/Zipkin/X-Ray link for {service}>`",
        "- **Deployments:** `<CI/CD pipeline link>`",
        "- **Status page:** `<status page link>`",
        "",
        "---",
        "",
        "*Generated by triage_incident.py. Fill in TODOs, then copy to incident tracker.*",
    ])

    return "\n".join(lines)


def generate_json_report(
    incident_id: str,
    alerts: List[str],
    service: str,
    since: datetime.datetime,
    severity: str,
    playbooks: List[str],
) -> str:
    timeline = build_timeline(alerts, since)
    data = {
        "incident_id": incident_id,
        "severity": severity,
        "status": "Investigating",
        "started": format_iso8601(since),
        "detected_by": alerts,
        "affected_service": service,
        "customer_impact": "TODO: quantify",
        "incident_commander": "TODO: assign",
        "suggested_playbooks": playbooks,
        "deployment_suspect": suggest_deploy_suspect(since),
        "timeline": timeline,
        "immediate_actions": [
            "Confirm customer impact",
            "Check for recent deploy / config / infra change",
            "Correlate metrics, logs, and traces",
            "Load appropriate playbook",
            "Mitigate first if customer impact confirmed",
        ],
        "generated_at": format_iso8601(now_utc()),
    }
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Correlate alerts and generate an incident report skeleton."
    )
    parser.add_argument(
        "--alerts",
        required=True,
        help='Comma-separated list of alert names, e.g., "HighErrorRate,LatencySpike"',
    )
    parser.add_argument(
        "--service",
        required=True,
        help="Name of the affected service, e.g., api-prod",
    )
    parser.add_argument(
        "--since",
        required=True,
        help="Incident start time in ISO-8601, e.g., 2024-05-06T14:00:00Z",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output file path (e.g., incident_report.md or incident_report.json)",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "auto"],
        default="auto",
        help="Output format. 'auto' guesses from --output extension (default: auto)",
    )
    parser.add_argument(
        "--incident-id",
        default="",
        help="Optional incident ID. If omitted, one is generated.",
    )

    args = parser.parse_args()

    alerts = [a.strip() for a in args.alerts.split(",") if a.strip()]
    if not alerts:
        print("ERROR: At least one alert must be provided.", file=sys.stderr)
        return 1

    try:
        since = parse_iso8601(args.since)
    except ValueError as exc:
        print(f"ERROR: Invalid --since timestamp: {exc}", file=sys.stderr)
        return 1

    severity = severity_from_alerts(alerts)
    playbooks = playbook_from_alerts(alerts)
    incident_id = args.incident_id or generate_incident_id()

    # Determine format
    out_path = args.output
    out_format = args.format
    if out_format == "auto":
        if out_path.endswith(".json"):
            out_format = "json"
        else:
            out_format = "markdown"

    if out_format == "json":
        content = generate_json_report(incident_id, alerts, args.service, since, severity, playbooks)
    else:
        content = generate_markdown_report(incident_id, alerts, args.service, since, severity, playbooks)

    # Write output
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        print(f"ERROR: Cannot write to {out_path}: {exc}", file=sys.stderr)
        return 1

    print(f"Incident report generated: {out_path}")
    print(f"  Incident ID : {incident_id}")
    print(f"  Severity    : {severity}")
    print(f"  Service     : {args.service}")
    print(f"  Alerts      : {', '.join(alerts)}")
    print(f"  Playbooks   : {', '.join(playbooks) if playbooks else 'None'}")
    print(f"  Format      : {out_format}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
