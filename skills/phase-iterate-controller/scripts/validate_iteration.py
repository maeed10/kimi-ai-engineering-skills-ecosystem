#!/usr/bin/env python3
"""validate_iteration.py — Governed iteration primitive validation.

Validates RETRY, ITERATE, REPLAN, ABORT transitions and produces audit reports.
"""

import argparse
import json
import sys
from pathlib import Path

VALID_PRIMITIVES = {"RETRY", "ITERATE", "REPLAN", "ABORT"}


def main():
    parser = argparse.ArgumentParser(description="Phase Iterate Controller")
    parser.add_argument("--transitions", required=True, help="JSON array of phase transition records")
    parser.add_argument("--output", default="iteration_audit.json")
    args = parser.parse_args()

    transitions = json.loads(Path(args.transitions).read_text(encoding="utf-8"))

    findings = []
    depth = 0
    for t in transitions:
        primitive = t.get("primitive", "")
        if primitive not in VALID_PRIMITIVES:
            findings.append({
                "transition": t,
                "valid": False,
                "reason": f"Invalid primitive: {primitive}",
            })
            continue

        if primitive == "RETRY":
            valid = t.get("from_phase") == t.get("to_phase")
            reason = "RETRY must stay in same phase" if not valid else ""
        elif primitive == "ITERATE":
            valid = _is_forward(t.get("from_phase"), t.get("to_phase"))
            reason = "ITERATE must move forward" if not valid else ""
        elif primitive == "REPLAN":
            valid = t.get("to_phase") in ("PLAN", "UNDERSTAND")
            reason = "REPLAN must target PLAN or UNDERSTAND" if not valid else ""
        elif primitive == "ABORT":
            valid = True
            reason = ""

        depth += 1 if primitive in ("RETRY", "ITERATE") else 0
        if depth > 10:
            valid = False
            reason = "Iteration depth exceeds limit (10)"

        findings.append({
            "transition": t,
            "valid": valid,
            "reason": reason,
            "depth": depth,
        })

    all_valid = all(f["valid"] for f in findings)
    report = {
        "transitions_checked": len(transitions),
        "valid_primitives": sum(1 for f in findings if f["valid"]),
        "invalid_primitives": sum(1 for f in findings if not f["valid"]),
        "max_depth": max((f["depth"] for f in findings), default=0),
        "all_valid": all_valid,
        "findings": findings,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Checked {report['transitions_checked']} transitions, {report['invalid_primitives']} invalid.")
    return 0 if all_valid else 1


def _is_forward(from_phase, to_phase):
    order = ["INGEST", "UNDERSTAND", "PLAN", "ASSESS", "EXECUTE", "DELIVER", "VALIDATE", "REMEMBER"]
    try:
        return order.index(to_phase) > order.index(from_phase)
    except ValueError:
        return False


if __name__ == "__main__":
    sys.exit(main())
