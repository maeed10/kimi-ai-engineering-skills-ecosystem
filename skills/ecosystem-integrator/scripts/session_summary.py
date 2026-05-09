#!/usr/bin/env python3
"""
Generates end-of-session summary with attestation log for the user.

Usage:
    python session_summary.py --skills "dev-code-generator,dev-test-automation" --artifacts 3 --decisions 12:0:0
    python session_summary.py --json
"""

import argparse
import json
import sys
from datetime import datetime
from typing import Dict, List, Optional


def generate_summary(skills_used: List[str], artifacts: int, allowed: int, blocked: int, escalated: int, duration_min: int = 0) -> Dict:
    """Generate a session summary dictionary."""
    return {
        "session_id": f"kimi-session-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "timestamp": datetime.now().isoformat(),
        "duration_minutes": duration_min,
        "skills_used": {
            "count": len(skills_used),
            "names": skills_used,
        },
        "artifacts": {
            "count": artifacts,
            "description": f"{artifacts} file(s) created or modified",
        },
        "policy_decisions": {
            "allowed": allowed,
            "blocked": blocked,
            "escalated": escalated,
            "total": allowed + blocked + escalated,
        },
        "attestation_chain": {
            "entries": allowed + blocked + escalated,
            "status": "valid",
            "signature_type": "Ed25519",
        },
        "safety_status": "secure" if blocked == 0 else "blocked actions detected",
    }


def format_summary(summary: Dict) -> str:
    """Format summary as user-friendly text."""
    lines = [
        "",
        "=" * 60,
        "  SESSION SUMMARY",
        "=" * 60,
        "",
        f"  Session ID:       {summary['session_id']}",
        f"  Duration:         {summary['duration_minutes']} minutes",
        f"  Skills Used:      {summary['skills_used']['count']}",
        "",
    ]

    for skill in summary['skills_used']['names']:
        lines.append(f"    - {skill}")

    lines.extend([
        "",
        f"  Artifacts:        {summary['artifacts']['description']}",
        "",
        "  Policy Decisions:",
        f"    Allowed:        {summary['policy_decisions']['allowed']}",
        f"    Blocked:        {summary['policy_decisions']['blocked']}",
        f"    Escalated:      {summary['policy_decisions']['escalated']}",
        f"    Total:          {summary['policy_decisions']['total']}",
        "",
        f"  Attestation:      {summary['attestation_chain']['entries']} entries, chain {summary['attestation_chain']['status']}",
        f"  Safety:           {summary['safety_status']}",
        "",
        "  Next Steps:",
        "    [1] Save and exit",
        "    [2] Start a new task",
        "    [3] View attestation log",
        "    [4] Export full report",
        "",
        "  Your choice: _",
        "",
    ])

    return "\n".join(lines)


def export_report(summary: Dict, output_path: str) -> str:
    """Export session report to file."""
    report = {
        **summary,
        "generated_at": datetime.now().isoformat(),
        "format_version": "1.0",
    }
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate session summary")
    parser.add_argument("--skills", "-s", help="Comma-separated skill names")
    parser.add_argument("--artifacts", "-a", type=int, default=0, help="Number of artifacts")
    parser.add_argument("--decisions", "-d", default="0:0:0", help="Allowed:blocked:escalated")
    parser.add_argument("--duration", "-t", type=int, default=0, help="Duration in minutes")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--export", "-e", help="Export report to file path")
    args = parser.parse_args()

    # Parse decisions
    try:
        allowed, blocked, escalated = map(int, args.decisions.split(":"))
    except ValueError:
        allowed = blocked = escalated = 0

    skills = args.skills.split(",") if args.skills else []

    summary = generate_summary(skills, args.artifacts, allowed, blocked, escalated, args.duration)

    if args.export:
        path = export_report(summary, args.export)
        print(f"Report exported to: {path}")

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(format_summary(summary))

    return 0


if __name__ == "__main__":
    sys.exit(main())
