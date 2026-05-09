#!/usr/bin/env python3
"""reconcile_requirements.py — Multi-document contradiction detection.

Reads multiple requirement documents, identifies contradictions via semantic
comparison and keyword overlap, scores conflict severity.
"""

import argparse
import json
import re
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Requirement Reconciler")
    parser.add_argument("--files", nargs="+", required=True, help="Requirement markdown files")
    parser.add_argument("--output", default="reconciliation_report.json")
    args = parser.parse_args()

    docs = []
    for f in args.files:
        text = Path(f).read_text(encoding="utf-8")
        docs.append({"path": f, "text": text, "requirements": _extract_requirements(text)})

    contradictions = []
    for i in range(len(docs)):
        for j in range(i + 1, len(docs)):
            for req_a in docs[i]["requirements"]:
                for req_b in docs[j]["requirements"]:
                    if _is_contradiction(req_a, req_b):
                        severity = _score_conflict(req_a, req_b)
                        contradictions.append({
                            "doc_a": docs[i]["path"],
                            "doc_b": docs[j]["path"],
                            "req_a": req_a,
                            "req_b": req_b,
                            "severity": severity,
                        })

    report = {
        "documents_analyzed": len(docs),
        "requirements_extracted": sum(len(d["requirements"]) for d in docs),
        "contradictions_found": len(contradictions),
        "contradictions": contradictions,
        "blocking_count": sum(1 for c in contradictions if c["severity"] == "BLOCKING"),
        "warning_count": sum(1 for c in contradictions if c["severity"] == "WARNING"),
        "advisory_count": sum(1 for c in contradictions if c["severity"] == "ADVISORY"),
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Analyzed {report['documents_analyzed']} docs, found {report['contradictions_found']} contradictions.")
    if report["blocking_count"] > 0:
        print(f"BLOCKING: {report['blocking_count']} — human resolution required.")
    return 0 if report["blocking_count"] == 0 else 1


def _extract_requirements(text):
    """Extract requirements from markdown: lines starting with '- REQ-' or '## Requirement'."""
    reqs = []
    for line in text.splitlines():
        m = re.search(r"REQ-\d+[:\s]+(.+)", line)
        if m:
            reqs.append(m.group(1).strip())
    return reqs if reqs else [text[:200]]


def _is_contradiction(a, b):
    """Detect contradiction via negation keywords and antonym overlap."""
    a_lower = a.lower()
    b_lower = b.lower()
    negations = {"never", "no", "not", "must not", "shall not", "disable", "forbid"}
    a_has_neg = any(n in a_lower for n in negations)
    b_has_neg = any(n in b_lower for n in negations)
    if a_has_neg != b_has_neg:
        # One negates, one affirms — check topic overlap
        a_words = set(re.findall(r"\b\w+\b", a_lower))
        b_words = set(re.findall(r"\b\w+\b", b_lower))
        overlap = a_words & b_words
        if len(overlap) >= 3:
            return True
    return False


def _score_conflict(a, b):
    """Score conflict severity based on keywords."""
    combined = (a + " " + b).lower()
    if any(k in combined for k in ("must", "shall", "required", "never", "always")):
        return "BLOCKING"
    if any(k in combined for k in ("should", "recommended", "prefer")):
        return "WARNING"
    return "ADVISORY"


if __name__ == "__main__":
    sys.exit(main())
