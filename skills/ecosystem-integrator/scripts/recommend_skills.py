#!/usr/bin/env python3
"""
Skill recommendation engine for ecosystem-integrator interactive flow.

Takes the user's task description and outputs ranked skill recommendations
with rationale. The user then selects which to activate.

Usage:
    python recommend_skills.py "Generate a FastAPI endpoint for users" --language python --framework fastapi
    python recommend_skills.py "Debug test failures in CI" --context cicd
"""

import argparse
import json
import sys
from typing import List, Dict, Optional

SKILL_CATALOG = [
    # Developer skills
    {"name": "dev-code-generator", "triggers": ["generate code", "scaffold", "create", "write code", "boilerplate", "implement"], "languages": ["python", "javascript", "typescript", "go", "rust", "java", "csharp"], "priority": 1},
    {"name": "dev-test-automation", "triggers": ["test", "coverage", "pytest", "jest", "unit test", "integration test"], "languages": ["*"], "priority": 1},
    {"name": "dev-debug-assistant", "triggers": ["debug", "error", "trace", "fail", "broken", "crash", "exception"], "languages": ["*"], "priority": 1},
    {"name": "dev-ci-cd-pipeline", "triggers": ["ci/cd", "pipeline", "deploy", "github actions", "gitlab ci", "jenkins"], "languages": ["*"], "priority": 2},
    {"name": "dev-dependency-manager", "triggers": ["dependency", "package", "npm", "pip", "cargo", "audit", "cve", "vulnerability"], "languages": ["*"], "priority": 2},
    {"name": "dev-performance-profiler", "triggers": ["profile", "performance", "slow", "optimize", "latency", "memory leak"], "languages": ["*"], "priority": 2},
    {"name": "dev-security-scanner", "triggers": ["security", "vulnerability", "scan", "sast", "secret", "audit"], "languages": ["*"], "priority": 2},
    {"name": "dev-api-designer", "triggers": ["api", "endpoint", "rest", "graphql", "openapi", "swagger"], "languages": ["*"], "priority": 1},
    {"name": "dev-database-migrator", "triggers": ["database", "migration", "schema", "table", "index", "sql"], "languages": ["*"], "priority": 2},
    {"name": "dev-observability-setup", "triggers": ["monitor", "metrics", "dashboard", "logging", "observability", "prometheus", "grafana"], "languages": ["*"], "priority": 3},
    {"name": "dev-incident-responder", "triggers": ["incident", "alert", "on-call", "outage", "post-mortem"], "languages": ["*"], "priority": 1},
    {"name": "dev-infrastructure-coder", "triggers": ["terraform", "infrastructure", "cloudformation", "pulumi", "aws", "kubernetes"], "languages": ["*"], "priority": 2},
    {"name": "dev-docs-maintainer", "triggers": ["documentation", "readme", "docstring", "changelog", "diagram"], "languages": ["*"], "priority": 3},
    {"name": "dev-git-workflow", "triggers": ["git", "commit", "branch", "merge", "pr", "pull request", "review"], "languages": ["*"], "priority": 2},
    {"name": "dev-container-builder", "triggers": ["docker", "container", "image", "dockerfile", "compose"], "languages": ["*"], "priority": 2},
    # Safety skills (context-dependent)
    {"name": "architecture-decision-gate", "triggers": ["architecture", "design decision", "microservices", "pattern"], "languages": ["*"], "priority": 2},
    {"name": "formal-verification-assistant", "triggers": ["formal verification", "mathematical proof", "safety critical", "risk score"], "languages": ["*"], "priority": 3},
    {"name": "chaos-engineering-suite", "triggers": ["chaos", "resilience", "failure injection", "disaster recovery"], "languages": ["*"], "priority": 3},
]


def score_skill(skill: Dict, task: str, language: Optional[str], framework: Optional[str]) -> float:
    """Score a skill match against the user's task."""
    score = 0.0
    task_lower = task.lower()

    # Trigger word matching
    for trigger in skill["triggers"]:
        if trigger.lower() in task_lower:
            score += 10.0

    # Language match
    if language and language.lower() in [l.lower() for l in skill["languages"]]:
        score += 5.0
    if "*" in skill["languages"]:
        score += 2.0  # Universal skills get small bonus

    # Framework match (in trigger or name)
    if framework and framework.lower() in task_lower:
        score += 3.0

    # Priority weighting
    score += (4 - skill["priority"]) * 2.0

    return score


def recommend(task: str, language: Optional[str] = None, framework: Optional[str] = None) -> List[Dict]:
    """Recommend skills for a given task."""
    scored = []
    for skill in SKILL_CATALOG:
        s = score_skill(skill, task, language, framework)
        if s > 0:
            scored.append({"name": skill["name"], "score": s, "triggers": skill["triggers"]})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:5]  # Top 5


def format_recommendations(recs: List[Dict]) -> str:
    """Format recommendations as interactive prompt."""
    lines = [
        "Based on your task, I recommend these skills:",
        "",
    ]
    for i, rec in enumerate(recs, 1):
        lines.append(f"  [{i}] {rec['name']} (relevance: {rec['score']:.1f})")
    lines.append("")
    lines.append("Which skills would you like to activate?")
    lines.append("  Enter numbers (e.g., '1,3'), 'all', or 'skip':")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Recommend skills for a task")
    parser.add_argument("task", help="User's task description")
    parser.add_argument("--language", "-l", help="Programming language")
    parser.add_argument("--framework", "-f", help="Framework")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    recs = recommend(args.task, args.language, args.framework)

    if args.json:
        print(json.dumps(recs, indent=2))
    else:
        print(format_recommendations(recs))

    # Return exit code 0 with recommendations, 1 if no matches
    return 0 if recs else 1


if __name__ == "__main__":
    sys.exit(main())
