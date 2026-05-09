#!/usr/bin/env python3
"""analyze_tradeoffs.py — Weighted trade-off analysis with mandatory alternatives.

Requires 2+ alternatives including the do-nothing option. Produces a scored
recommendation matrix and silent debt tracking.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Trade-off Analyzer")
    parser.add_argument("--topic", required=True, help="Decision topic")
    parser.add_argument("--alternatives", required=True, help="JSON array of alternative objects [{name, description, pros, cons, costs}]")
    parser.add_argument("--criteria", required=True, help="JSON array of criteria [{name, weight, description}]")
    parser.add_argument("--output", default="tradeoff_report.json", help="Output file path")
    args = parser.parse_args()

    alternatives = json.loads(args.alternatives)
    criteria = json.loads(args.criteria)

    if len(alternatives) < 2:
        print("ERROR: At least 2 alternatives required (including do-nothing).", file=sys.stderr)
        return 1

    if not any(a.get("name", "").lower() in ("do nothing", "status quo", "none") for a in alternatives):
        print("WARNING: No do-nothing alternative found. Adding one.", file=sys.stderr)
        alternatives.append({"name": "Do nothing", "description": "Maintain current state", "pros": ["No risk"], "cons": ["No improvement"], "costs": 0})

    # Score each alternative against each criterion (0-10)
    scores = {}
    for alt in alternatives:
        alt_scores = {}
        total = 0.0
        for crit in criteria:
            # In a real implementation, this would use LLM reasoning or structured rubrics.
            # Here we use a heuristic based on keyword overlap.
            score = _heuristic_score(alt, crit)
            weighted = score * crit.get("weight", 1.0)
            alt_scores[crit["name"]] = {"raw": score, "weighted": weighted}
            total += weighted
        alt_scores["_total"] = total
        scores[alt["name"]] = alt_scores

    # Rank
    ranked = sorted(scores.items(), key=lambda x: x[1]["_total"], reverse=True)

    report = {
        "topic": args.topic,
        "alternatives_count": len(alternatives),
        "criteria_count": len(criteria),
        "recommendation": ranked[0][0],
        "ranking": [{"name": name, "total_score": round(data["_total"], 2)} for name, data in ranked],
        "detailed_scores": scores,
        "silent_debt": _track_debt(ranked, alternatives),
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {out_path}")
    print(f"Recommendation: {report['recommendation']}")
    return 0


def _heuristic_score(alt, crit):
    """Simple heuristic: if pros mention criterion, boost score."""
    text = " ".join(alt.get("pros", []) + alt.get("cons", []) + [alt.get("description", "")]).lower()
    crit_name = crit["name"].lower()
    if crit_name in text:
        return 7.0
    return 5.0


def _track_debt(ranked, alternatives):
    """Track architectural debt from rejected alternatives."""
    debt = []
    winner = ranked[0][0]
    for alt in alternatives:
        if alt["name"] != winner:
            debt.append({
                "rejected_alternative": alt["name"],
                "debt_type": "opportunity_cost",
                "rationale": f"Benefits of '{alt['name']}' forfeited by choosing '{winner}'",
            })
    return debt


if __name__ == "__main__":
    sys.exit(main())
