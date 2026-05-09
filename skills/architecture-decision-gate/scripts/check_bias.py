#!/usr/bin/env python3
"""
check_bias.py — Bias detection heuristics for architecture decisions.

Analyzes recent session records to detect LLM pattern bias:
  1. Pattern Frequency Bias: pattern appears as top recommendation > 80% of sessions
  2. Team-Size Mismatch: complex patterns recommended for small teams (< 3 engineers or < 10K LOC)
  3. Default Bias: recommendation lacks specific business requirement / quality attribute linkage
  4. Complexity Escalation: monotonic increase in new infrastructure components over last 5 sessions

Usage:
    python check_bias.py --sessions sessions.json --proposal proposal.json --registry registry.json

Outputs JSON with bias flags, confidence scores, and remediation hints.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def load_json(path: str) -> dict | list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_pattern_frequency(sessions: list[dict], current_pattern: str, threshold: float = 0.80) -> dict:
    """Heuristic 1: Pattern appears as top recommendation in > threshold of recent sessions."""
    if not sessions:
        return {"flag": False, "ratio": 0.0, "detail": "No session history available."}

    total = len(sessions)
    matches = 0
    for session in sessions:
        patterns = session.get("recommended_patterns", [])
        if patterns and patterns[0] == current_pattern:
            matches += 1

    ratio = matches / total
    return {
        "flag": ratio > threshold,
        "ratio": round(ratio, 2),
        "threshold": threshold,
        "detail": f"Pattern '{current_pattern}' was top recommendation in {matches}/{total} sessions ({ratio:.0%}).",
    }


def compute_team_size_mismatch(proposal: dict, registry: dict | None) -> dict:
    """Heuristic 2: Complex patterns for small teams."""
    COMPLEX_PATTERNS = {"microservices", "cqrs", "event-driven architecture", "eda", "event sourcing", "saga"}
    pattern = proposal.get("primary_pattern", "").lower()
    team_size = proposal.get("team_size")
    loc = proposal.get("total_loc")

    if pattern not in COMPLEX_PATTERNS:
        return {"flag": False, "detail": f"Pattern '{pattern}' is not classified as complex."}

    flags = []
    if team_size is not None and team_size < 3:
        flags.append(f"team_size={team_size} < 3")
    if loc is not None and loc < 10_000:
        flags.append(f"total_loc={loc} < 10K")

    # Cross-check with registry team size range if available
    if registry:
        org = registry.get("org_context", {})
        ts_range = org.get("team_size_range", {})
        min_ts = ts_range.get("min")
        max_ts = ts_range.get("max")
        if min_ts is not None and team_size is not None and team_size < min_ts:
            flags.append(f"team_size={team_size} below registry minimum {min_ts}")
        if max_ts is not None and team_size is not None and team_size > max_ts:
            flags.append(f"team_size={team_size} above registry maximum {max_ts}")

    return {
        "flag": bool(flags),
        "detail": "; ".join(flags) if flags else f"Team context acceptable for '{pattern}'.",
    }


def compute_default_bias(proposal: dict) -> dict:
    """Heuristic 3: Pattern recommended without specific requirement or quality attribute scenario."""
    requirement_links = proposal.get("requirement_links", [])
    quality_attributes = proposal.get("quality_attributes", [])
    justification = proposal.get("justification", "")

    has_specific_link = bool(requirement_links) or bool(quality_attributes)
    has_business_rationale = any(
        kw in justification.lower()
        for kw in ("latency", "throughput", "availability", "scalability", "concurrency", "failure mode", "slo", "sla")
    )

    if has_specific_link or has_business_rationale:
        return {
            "flag": False,
            "detail": "Proposal links to specific requirements or quality attributes.",
        }

    return {
        "flag": True,
        "detail": "No specific requirement_links, quality_attributes, or business rationale detected. Pattern may be LLM default.",
    }


def compute_complexity_escalation(sessions: list[dict]) -> dict:
    """Heuristic 4: Monotonic increase in new infrastructure components per decision over last 5 sessions."""
    if len(sessions) < 5:
        return {"flag": False, "detail": f"Need >= 5 sessions; found {len(sessions)}."}

    last_5 = sessions[-5:]
    counts = []
    for session in last_5:
        components = set(session.get("new_data_stores", []))
        components.update(session.get("new_message_buses", []))
        components.update(session.get("new_observability", []))
        counts.append(len(components))

    # Check strict monotonic increase
    monotonic = all(counts[i] < counts[i + 1] for i in range(len(counts) - 1))

    return {
        "flag": monotonic,
        "component_counts_per_session": counts,
        "detail": (
            f"New infrastructure components per session (last 5): {counts}. "
            f"Monotonic escalation detected: {monotonic}."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Architecture decision bias detection")
    parser.add_argument("--sessions", required=True, help="Path to JSON array of recent session records")
    parser.add_argument("--proposal", required=True, help="Path to current proposal JSON")
    parser.add_argument("--registry", default=None, help="Path to criteria registry JSON (optional)")
    parser.add_argument("--output", default=None, help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    sessions = load_json(args.sessions)
    proposal = load_json(args.proposal)
    registry = load_json(args.registry) if args.registry else None

    if not isinstance(sessions, list):
        print("ERROR: --sessions must be a JSON array", file=sys.stderr)
        sys.exit(1)

    current_pattern = proposal.get("primary_pattern", "")

    result = {
        "decision_id": proposal.get("decision_id", "unknown"),
        "primary_pattern": current_pattern,
        "bias_flags": [],
        "heuristics": {},
        "recommendation": "PASS",
    }

    # Heuristic 1
    h1 = compute_pattern_frequency(sessions, current_pattern)
    result["heuristics"]["pattern_frequency"] = h1
    if h1["flag"]:
        result["bias_flags"].append("PATTERN_FREQUENCY_BIAS")

    # Heuristic 2
    h2 = compute_team_size_mismatch(proposal, registry)
    result["heuristics"]["team_size_mismatch"] = h2
    if h2["flag"]:
        result["bias_flags"].append("TEAM_SIZE_MISMATCH")

    # Heuristic 3
    h3 = compute_default_bias(proposal)
    result["heuristics"]["default_bias"] = h3
    if h3["flag"]:
        result["bias_flags"].append("DEFAULT_BIAS")

    # Heuristic 4
    h4 = compute_complexity_escalation(sessions)
    result["heuristics"]["complexity_escalation"] = h4
    if h4["flag"]:
        result["bias_flags"].append("COMPLEXITY_ESCALATION")

    if result["bias_flags"]:
        result["recommendation"] = "RISK_DETECTED"

    output_json = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
