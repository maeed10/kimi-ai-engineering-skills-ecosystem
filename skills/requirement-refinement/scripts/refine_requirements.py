#!/usr/bin/env python3
"""refine_requirements.py — Ambiguity detection and requirement clarification.

Reads a requirement document, detects ambiguities, suggests clarifications
with example mappings. Blocks PLAN phase if ambiguity score exceeds threshold.
"""

import argparse
import json
import re
import sys
from pathlib import Path


AMBIGUITY_THRESHOLD = 0.3


def main():
    parser = argparse.ArgumentParser(description="Requirement Refinement")
    parser.add_argument("--file", required=True, help="Requirement markdown file")
    parser.add_argument("--threshold", type=float, default=AMBIGUITY_THRESHOLD)
    parser.add_argument("--output", default="refinement_report.json")
    args = parser.parse_args()

    text = Path(args.file).read_text(encoding="utf-8")
    reqs = _extract_requirements(text)

    findings = []
    total_ambiguity = 0.0
    for req in reqs:
        score, issues = _score_ambiguity(req)
        total_ambiguity += score
        if score > 0:
            findings.append({
                "requirement": req,
                "ambiguity_score": round(score, 3),
                "issues": issues,
                "suggestions": _suggest_clarifications(req, issues),
                "example_mapping": _example_mapping(req),
            })

    avg_ambiguity = total_ambiguity / len(reqs) if reqs else 0.0

    report = {
        "file": args.file,
        "requirements_count": len(reqs),
        "average_ambiguity_score": round(avg_ambiguity, 3),
        "threshold": args.threshold,
        "blocks_plan": avg_ambiguity > args.threshold,
        "findings": findings,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Analyzed {report['requirements_count']} requirements.")
    print(f"Average ambiguity: {report['average_ambiguity_score']} (threshold: {args.threshold})")
    if report["blocks_plan"]:
        print("RESULT: BLOCKS PLAN — ambiguity too high. Address findings before planning.")
    else:
        print("RESULT: CLEAR — proceed to PLAN phase.")
    return 1 if report["blocks_plan"] else 0


def _extract_requirements(text):
    reqs = []
    for line in text.splitlines():
        m = re.search(r"REQ-\d+[:\s]+(.+)", line)
        if m:
            reqs.append(m.group(1).strip())
    return reqs if reqs else [text[:300]]


def _score_ambiguity(req):
    issues = []
    score = 0.0
    # Vague quantifiers
    vague = {"some", "many", "few", "several", "often", "usually", "maybe", "perhaps", "as needed"}
    for v in vague:
        if v in req.lower():
            score += 0.15
            issues.append(f"Vague quantifier: '{v}'")
    # Missing acceptance criteria
    if not any(k in req.lower() for k in ("given", "when", "then", "acceptance", "criteria")):
        score += 0.2
        issues.append("Missing acceptance criteria (Given/When/Then)")
    # Unbounded terms
    unbounded = {"fast", "slow", "large", "small", "easy", "hard", "soon", "later"}
    for u in unbounded:
        if u in req.lower():
            score += 0.1
            issues.append(f"Unbounded term: '{u}'")
    # No metric
    if not re.search(r"\d", req):
        score += 0.1
        issues.append("No quantifiable metric")
    return min(score, 1.0), issues


def _suggest_clarifications(req, issues):
    suggestions = []
    for issue in issues:
        if "Vague quantifier" in issue:
            suggestions.append("Replace with specific number or percentage")
        elif "Missing acceptance criteria" in issue:
            suggestions.append("Add Gherkin scenario: Given X When Y Then Z")
        elif "Unbounded term" in issue:
            suggestions.append("Define concrete threshold with units")
        elif "No quantifiable metric" in issue:
            suggestions.append("Add numeric target (latency ms, throughput rps, etc.)")
    return suggestions


def _example_mapping(req):
    return {
        "original": req,
        "clarified_example": f"Given [specific context], When [specific action], Then [measurable outcome] — e.g., {req[:80]}...",
    }


if __name__ == "__main__":
    sys.exit(main())
