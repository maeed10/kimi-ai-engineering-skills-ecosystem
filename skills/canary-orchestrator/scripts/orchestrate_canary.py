#!/usr/bin/env python3
"""orchestrate_canary.py — Progressive delivery orchestration.

Translates blast-radius risk scores into deployment strategies and monitors
health post-deployment with auto-rollback thresholds.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Canary Orchestrator")
    parser.add_argument("--risk-score", type=float, required=True, help="Blast radius risk score (0-10)")
    parser.add_argument("--service", required=True, help="Service name")
    parser.add_argument("--version", required=True, help="Deployment version/tag")
    parser.add_argument("--health-url", default="", help="Health check endpoint")
    parser.add_argument("--output", default="canary_plan.json")
    args = parser.parse_args()

    strategy = _select_strategy(args.risk_score)
    plan = {
        "service": args.service,
        "version": args.version,
        "risk_score": args.risk_score,
        "strategy": strategy["name"],
        "steps": strategy["steps"],
        "health_checks": {
            "endpoint": args.health_url or f"http://{args.service}/health",
            "interval_seconds": 30,
            "failure_threshold": 3,
            "rollback_on_failure": True,
        },
        "auto_rollback": strategy["rollback"],
    }

    Path(args.output).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"Canary plan: {strategy['name']} for {args.service}@{args.version}")
    for i, step in enumerate(strategy["steps"], 1):
        print(f"  Step {i}: {step['traffic_percent']}% traffic — {step['duration_minutes']} min")
    return 0


def _select_strategy(risk):
    if risk <= 2:
        return {
            "name": "direct",
            "steps": [{"traffic_percent": 100, "duration_minutes": 0}],
            "rollback": False,
        }
    elif risk <= 5:
        return {
            "name": "canary",
            "steps": [
                {"traffic_percent": 5, "duration_minutes": 10},
                {"traffic_percent": 25, "duration_minutes": 15},
                {"traffic_percent": 50, "duration_minutes": 20},
                {"traffic_percent": 100, "duration_minutes": 0},
            ],
            "rollback": True,
        }
    else:
        return {
            "name": "blue-green",
            "steps": [
                {"traffic_percent": 0, "duration_minutes": 30, "note": "Warm up green environment"},
                {"traffic_percent": 1, "duration_minutes": 20},
                {"traffic_percent": 10, "duration_minutes": 30},
                {"traffic_percent": 50, "duration_minutes": 30},
                {"traffic_percent": 100, "duration_minutes": 0},
            ],
            "rollback": True,
        }


if __name__ == "__main__":
    sys.exit(main())
