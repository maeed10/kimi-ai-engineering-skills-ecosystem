#!/usr/bin/env python3
"""enforce_style.py — Commit style analysis and enforcement.

Reads git log, extracts team-specific commit patterns, validates against
conventional commits.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from collections import Counter

CONVENTIONAL_TYPES = {"feat", "fix", "docs", "style", "refactor", "perf", "test", "chore", "ci", "build"}


def main():
    parser = argparse.ArgumentParser(description="Style Enforcer")
    parser.add_argument("--repo", default=".", help="Git repository path")
    parser.add_argument("--since", default="30 days ago", help="Git log since")
    parser.add_argument("--output", default="style_report.json")
    args = parser.parse_args()

    result = subprocess.run(
        ["git", "-C", args.repo, "log", f"--since={args.since}", "--pretty=format:%s"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: git log failed: {result.stderr}", file=sys.stderr)
        return 1

    commits = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    types = Counter()
    valid = 0
    invalid = []
    for msg in commits:
        m = re.match(r"^(\w+)(\(.+\))?!?:\s*(.+)", msg)
        if m:
            ctype = m.group(1)
            types[ctype] += 1
            if ctype in CONVENTIONAL_TYPES:
                valid += 1
            else:
                invalid.append(msg)
        else:
            invalid.append(msg)

    report = {
        "repo": args.repo,
        "commits_analyzed": len(commits),
        "valid_conventional": valid,
        "invalid": len(invalid),
        "type_distribution": dict(types),
        "invalid_samples": invalid[:10],
        "pass_rate": round(valid / len(commits), 2) if commits else 1.0,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Commits: {report['commits_analyzed']}, Valid: {report['valid_conventional']}, Pass rate: {report['pass_rate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
