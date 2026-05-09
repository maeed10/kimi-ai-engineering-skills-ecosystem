#!/usr/bin/env python3
"""weave_concerns.py — Cross-cutting concern enforcement.

Analyzes a codebase for missing cross-cutting concerns (security, logging,
resilience, observability, compliance) and reports gaps.
"""

import argparse
import json
import re
import sys
from pathlib import Path

CONCERNS = {
    "security": {
        "patterns": [r"auth", r"encrypt", r"hashlib", r"secrets", r"csrf", r"xss", r"sanitize"],
        "required_files": ["security.md", "AUTHORS", ".snyk"],
    },
    "logging": {
        "patterns": [r"logging", r"loguru", r"structlog", r"logger"],
        "required_files": [],
    },
    "resilience": {
        "patterns": [r"retry", r"circuit.?breaker", r"timeout", r"fallback", r"backoff"],
        "required_files": [],
    },
    "observability": {
        "patterns": [r"metrics", r"prometheus", r"otel", r"trace", r"span", r"counter"],
        "required_files": [],
    },
    "compliance": {
        "patterns": [r"gdpr", r"soc2", r"hipaa", r"pci", r"audit", r"retention"],
        "required_files": ["LICENSE", "CONTRIBUTING.md"],
    },
}


def main():
    parser = argparse.ArgumentParser(description="Cross-Cutting Concern Weaver")
    parser.add_argument("--path", required=True, help="Codebase root directory")
    parser.add_argument("--output", default="concern_report.json")
    args = parser.parse_args()

    root = Path(args.path)
    if not root.exists():
        print(f"ERROR: Path not found: {root}", file=sys.stderr)
        return 1

    findings = {}
    for concern, config in CONCERNS.items():
        findings[concern] = _analyze_concern(root, concern, config)

    report = {
        "path": str(root),
        "concerns_analyzed": len(CONCERNS),
        "findings": findings,
        "overall_score": round(sum(f["score"] for f in findings.values()) / len(findings), 2),
        "gaps": [{"concern": c, **f} for c, f in findings.items() if f["score"] < 0.5],
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Analyzed {report['concerns_analyzed']} concerns. Overall score: {report['overall_score']}")
    if report["gaps"]:
        print(f"Gaps found: {len(report['gaps'])}")
    return 0


def _analyze_concern(root, concern, config):
    files_scanned = 0
    matches = 0
    for pyfile in list(root.rglob("*.py"))[:200]:
        try:
            text = pyfile.read_text(encoding="utf-8")
        except Exception:
            continue
        files_scanned += 1
        for pattern in config["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                matches += 1
                break

    score = min(matches / max(files_scanned * 0.1, 1), 1.0)
    missing_files = [f for f in config["required_files"] if not any(root.rglob(f))]

    return {
        "score": round(score, 2),
        "files_scanned": files_scanned,
        "files_with_concern": matches,
        "missing_required_files": missing_files,
        "recommendation": f"Add {concern} instrumentation" if score < 0.5 else "Sufficient coverage",
    }


if __name__ == "__main__":
    sys.exit(main())
