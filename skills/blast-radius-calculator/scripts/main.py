#!/usr/bin/env python3
"""Blast Radius Calculator — analyze code changes and compute impact scores."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze a codebase change and compute blast radius / risk score."
    )
    parser.add_argument("--repo", default=".", help="Path to git repository")
    parser.add_argument("--diff-file", help="Path to a git diff file")
    parser.add_argument("--files", help="Comma-separated list of changed files")
    parser.add_argument("--output", help="Path to write JSON report")
    parser.add_argument(
        "--weights",
        default="structural:0.25,semantic:0.35,historical:0.20,coverage:0.20",
        help="Risk dimension weights",
    )
    return parser.parse_args()


def parse_weights(weights_str: str) -> dict[str, float]:
    """Parse weight string into a dictionary."""
    weights = {}
    for part in weights_str.split(","):
        key, val = part.split(":")
        weights[key.strip()] = float(val.strip())
    return weights


def get_changed_files_from_diff(diff_file: str, repo: str) -> list[str]:
    """Extract changed file paths from a git diff."""
    content = Path(diff_file).read_text(encoding="utf-8")
    files = set()
    for line in content.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[2].lstrip("a/"))
                files.add(parts[3].lstrip("b/"))
        elif line.startswith("--- ") or line.startswith("+++ "):
            path = line[4:].split("\t")[0]
            if path not in ("/dev/null",):
                files.add(path.lstrip("a/").lstrip("b/"))
    return sorted(files)


def get_changed_files_from_git(repo: str) -> list[str]:
    """Get changed files from the working tree."""
    result = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f]


def get_git_log_for_files(repo: str, files: list[str], count: int = 20) -> list[dict[str, Any]]:
    """Retrieve recent git log entries touching the given files."""
    if not files:
        return []
    cmd = ["git", "-C", repo, "log", f"-n{count}", "--format=%H|%an|%ad|%s"] + files
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    entries = []
    for line in result.stdout.strip().split("\n"):
        if "|" not in line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            entries.append({"hash": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3]})
    return entries


def analyze_dependencies(repo: str, files: list[str]) -> dict[str, Any]:
    """Build a dependency graph for changed files using import scanning."""
    dependents = set()
    direct_count = 0

    for root, _dirs, filenames in os.walk(repo):
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, repo).replace("\\", "/")
            try:
                text = Path(fpath).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for changed in files:
                mod = changed.replace("/", ".").removesuffix(".py")
                # Simple import matching
                patterns = [
                    rf"^\s*import\s+{re.escape(mod)}",
                    rf"^\s*from\s+{re.escape(mod)}\s+import",
                ]
                for pat in patterns:
                    if re.search(pat, text, re.MULTILINE):
                        if rel not in files:
                            dependents.add(rel)
                        break
            if rel in files:
                direct_count += 1

    return {
        "direct_files": direct_count,
        "transitive_dependents": sorted(dependents),
        "transitive_count": len(dependents),
    }


def classify_change_type(files: list[str]) -> str:
    """Classify the change type based on affected files."""
    critical_keywords = ["auth", "security", "crypto", "password", "login", "token"]
    api_keywords = ["api", "endpoint", "route", "controller", "handler"]
    db_keywords = ["migration", "schema", "model", "db", "sql"]

    lowered = " ".join(files).lower()
    if any(k in lowered for k in critical_keywords):
        return "Type D — Systemic"
    if any(k in lowered for k in db_keywords):
        return "Type D — Systemic"
    if any(k in lowered for k in api_keywords):
        return "Type C — Cross-Module"
    if len(files) > 10:
        return "Type D — Systemic"
    if len(files) > 1:
        return "Type B — Localized"
    return "Type A — Isolated"


def compute_structural_risk(dependency_info: dict[str, Any]) -> float:
    """Compute structural risk score (0-10)."""
    score = 2.0
    score += min(dependency_info["transitive_count"] * 0.5, 5.0)
    if dependency_info["transitive_count"] > 20:
        score += 2.0
    return min(score, 10.0)


def compute_semantic_risk(files: list[str], change_type: str) -> float:
    """Compute semantic risk score (0-10)."""
    base = {"Type A — Isolated": 1.0, "Type B — Localized": 3.0, "Type C — Cross-Module": 6.0, "Type D — Systemic": 9.0}
    score = base.get(change_type, 5.0)
    lowered = " ".join(files).lower()
    if any(k in lowered for k in ["auth", "security", "crypto", "payment"]):
        score = max(score, 8.0)
    return min(score, 10.0)


def compute_historical_risk(git_log: list[dict[str, Any]]) -> float:
    """Compute historical risk score (0-10) based on commit churn."""
    if not git_log:
        return 5.0
    # Higher churn = higher risk (simplified heuristic)
    score = 2.0 + min(len(git_log) * 0.3, 6.0)
    return min(score, 10.0)


def compute_coverage_risk(repo: str, files: list[str]) -> float:
    """Compute coverage risk (0-10) based on presence of test files."""
    if not files:
        return 5.0
    tested = 0
    for f in files:
        # Naive heuristic: check if a corresponding test file exists
        dirname = os.path.dirname(f)
        basename = os.path.basename(f)
        candidates = [
            os.path.join(repo, dirname, f"test_{basename}"),
            os.path.join(repo, dirname, f"{basename.replace('.py', '_test.py')}"),
            os.path.join(repo, "tests", f"test_{basename}"),
        ]
        if any(os.path.exists(c) for c in candidates):
            tested += 1
    ratio = tested / len(files) if files else 0.0
    # Lower coverage => higher risk
    return (1.0 - ratio) * 10.0


def compute_composite_risk(
    structural: float,
    semantic: float,
    historical: float,
    coverage: float,
    weights: dict[str, float],
) -> dict[str, Any]:
    """Compute weighted composite risk score."""
    composite = (
        structural * weights.get("structural", 0.25)
        + semantic * weights.get("semantic", 0.35)
        + historical * weights.get("historical", 0.20)
        + coverage * weights.get("coverage", 0.20)
    )
    if composite <= 3:
        level = "Low"
    elif composite <= 6:
        level = "Medium"
    elif composite <= 8:
        level = "High"
    else:
        level = "Critical"

    return {
        "composite_score": round(composite, 2),
        "risk_level": level,
        "structural": round(structural, 2),
        "semantic": round(semantic, 2),
        "historical": round(historical, 2),
        "coverage": round(coverage, 2),
    }


def main() -> int:
    """Main entry point."""
    args = parse_args()
    weights = parse_weights(args.weights)

    # Determine changed files
    if args.diff_file:
        changed_files = get_changed_files_from_diff(args.diff_file, args.repo)
    elif args.files:
        changed_files = [f.strip() for f in args.files.split(",") if f.strip()]
    else:
        changed_files = get_changed_files_from_git(args.repo)

    if not changed_files:
        print(json.dumps({"success": False, "error": "No changed files detected."}), file=sys.stderr)
        return 1

    change_type = classify_change_type(changed_files)
    dependency_info = analyze_dependencies(args.repo, changed_files)
    git_log = get_git_log_for_files(args.repo, changed_files)

    structural = compute_structural_risk(dependency_info)
    semantic = compute_semantic_risk(changed_files, change_type)
    historical = compute_historical_risk(git_log)
    coverage = compute_coverage_risk(args.repo, changed_files)
    risk = compute_composite_risk(structural, semantic, historical, coverage, weights)

    escalation = (
        risk["risk_level"] in ("High", "Critical")
        or risk["composite_score"] >= 7.0
        or len(changed_files) > 10
        or any(k in " ".join(changed_files).lower() for k in ["auth", "schema", "migration"])
    )

    report = {
        "success": True,
        "repo": os.path.abspath(args.repo),
        "changed_files": changed_files,
        "change_classification": change_type,
        "dependency_analysis": dependency_info,
        "historical_commits_analyzed": len(git_log),
        "risk_score": risk,
        "escalation_required": escalation,
        "recommended_tests": [f"test_{os.path.basename(f)}" for f in changed_files],
        "mitigation": {
            "split_prs": len(changed_files) > 10,
            "add_characterization_tests": coverage < 5.0,
            "feature_flags": change_type in ("Type C — Cross-Module", "Type D — Systemic"),
            "rollback_plan": "Maintain atomic commits and tagged rollback points",
        },
    }

    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
