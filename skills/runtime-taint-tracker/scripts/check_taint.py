#!/usr/bin/env python3
"""
check_taint.py - Evaluate if a proposed action violates taint thresholds.

Usage:
    python check_taint.py --action file_write --target /etc/passwd --taint-tags tags.json
    python check_taint.py --action browser_visit --target https://evil.com --taint-tags tags.json
    python check_taint.py --action code_execution --target "rm -rf /" --taint-tags tags.json

Exit codes:
    0 = ALLOW
    1 = BLOCK (red taint on critical op)
    2 = JUSTIFY (yellow taint on critical op)
    3 = ERROR (invalid input)
"""

import argparse
import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CRITICAL_OPS = {
    "file_write",
    "file_delete",
    "file_create",
    "network_request",
    "code_execution",
    "exec",
    "eval",
    "shell",
    "privilege_escalation",
    "credential_access",
}

READONLY_OPS = {
    "file_read",
    "directory_list",
    "grep_search",
    "read_file",
    "browser_visit",
}

GREEN_MIN = 0.75
YELLOW_MIN = 0.35
POISON_RATIO_THRESHOLD = 0.5

# ---------------------------------------------------------------------------
# Taint evaluation
# ---------------------------------------------------------------------------

def color_from_score(score: float) -> str:
    if score >= GREEN_MIN:
        return "green"
    if score >= YELLOW_MIN:
        return "yellow"
    return "red"

def effective_taint(taint_tags: list[dict]) -> dict[str, Any]:
    """
    Compute the effective taint across a list of taint tags.
    Returns dict with effective_color, effective_score, min_source, poison_ratio.
    """
    if not taint_tags:
        # No taint data = treat as fully trusted (system default)
        return {
            "effective_color": "green",
            "effective_score": 1.0,
            "min_source": "system",
            "poison_ratio": 0.0,
        }

    min_score = min(t.get("trust_score", 1.0) for t in taint_tags)
    min_source = min(
        taint_tags,
        key=lambda t: t.get("trust_score", 1.0),
    ).get("source", "unknown")

    effective_score = min_score
    effective_color = color_from_score(effective_score)

    # Aggregation poisoning: if >= 50% of "content" is from red sources
    total_tokens = sum(t.get("token_count", 1) for t in taint_tags)
    red_tokens = sum(
        t.get("token_count", 1)
        for t in taint_tags
        if color_from_score(t.get("trust_score", 1.0)) == "red"
    )
    poison_ratio = red_tokens / total_tokens if total_tokens > 0 else 0.0

    if poison_ratio >= POISON_RATIO_THRESHOLD:
        effective_color = "red"
        effective_score = min(effective_score, 0.34)

    return {
        "effective_color": effective_color,
        "effective_score": effective_score,
        "min_source": min_source,
        "poison_ratio": poison_ratio,
    }

def evaluate_action(action: str, target: str, taint_tags: list[dict]) -> dict[str, Any]:
    """
    Evaluate whether an action should be ALLOWed, BLOCKed, or require JUSTIFY.
    """
    result = {
        "action": action,
        "target": target,
        "critical": action in CRITICAL_OPS,
        "decision": "ALLOW",
        "reason": "",
        "taint_analysis": effective_taint(taint_tags),
        "justification_required": False,
    }

    eff = result["taint_analysis"]

    # Readonly ops always allowed (taint logged but not enforced)
    if action in READONLY_OPS:
        result["decision"] = "ALLOW"
        result["reason"] = "Readonly operation; taint logged but not blocking."
        return result

    # Unknown ops: treat as critical if they look dangerous
    if action not in CRITICAL_OPS and action not in READONLY_OPS:
        result["reason"] = f"Unknown action '{action}'; applying critical-op policy."
        result["critical"] = True

    # Critical op enforcement
    if result["critical"]:
        if eff["effective_color"] == "red":
            result["decision"] = "BLOCK"
            result["reason"] = (
                f"Red taint ({eff['effective_score']:.2f}) on critical op. "
                f"Lowest source: {eff['min_source']}. "
                f"Poison ratio: {eff['poison_ratio']:.2%}."
            )
            result["justification_required"] = True
        elif eff["effective_color"] == "yellow":
            result["decision"] = "JUSTIFY"
            result["reason"] = (
                f"Yellow taint ({eff['effective_score']:.2f}) on critical op. "
                f"Lowest source: {eff['min_source']}. "
                f"Explicit justification required before proceeding."
            )
            result["justification_required"] = True
        else:
            result["decision"] = "ALLOW"
            result["reason"] = "Green taint on critical op. Normal flow."

    return result

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate if a proposed action violates taint thresholds."
    )
    parser.add_argument("--action", required=True, help="Action being proposed")
    parser.add_argument("--target", required=True, help="Target of the action")
    parser.add_argument(
        "--taint-tags",
        required=True,
        help="JSON file containing list of taint tag objects",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()

    # Load taint tags
    try:
        with open(args.taint_tags, "r", encoding="utf-8") as f:
            taint_tags = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Cannot load taint tags: {e}", file=sys.stderr)
        return 3

    if not isinstance(taint_tags, list):
        print("ERROR: taint tags must be a JSON list", file=sys.stderr)
        return 3

    result = evaluate_action(args.action, args.target, taint_tags)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Decision: {result['decision']}")
        print(f"Reason:   {result['reason']}")
        print(f"Score:    {result['taint_analysis']['effective_score']:.2f}")
        print(f"Color:    {result['taint_analysis']['effective_color']}")
        if result["justification_required"]:
            print("JUSTIFICATION REQUIRED")

    # Exit codes
    if result["decision"] == "ALLOW":
        return 0
    elif result["decision"] == "BLOCK":
        return 1
    elif result["decision"] == "JUSTIFY":
        return 2
    return 3

if __name__ == "__main__":
    sys.exit(main())
