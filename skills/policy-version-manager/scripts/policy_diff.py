#!/usr/bin/env python3
"""
policy_diff.py

Generate human-readable diffs between two policy file versions.

Usage:
    python policy_diff.py old.json new.json
    python policy_diff.py old.json new.json --mode summary
    python policy_diff.py old.json new.json --mode full
    python policy_diff.py old.json new.json --rule <rule_key>
    python policy_diff.py old.json new.json --format markdown

Exit codes:
    0 — diff generated successfully
    1 — file not found or invalid JSON
    2 — no differences found (when --fail-on-empty)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_policy(path: str) -> Tuple[Dict[str, Any], str, str]:
    """Load a policy file and return (data, version, path)."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)

    meta = data.get("_meta", {})
    version = meta.get("version", "unknown")
    return data, version, path


def flatten_policy(data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """
    Flatten a nested policy dict into dot-notation keys for comparison.
    Ignores the _meta section.
    """
    flat: Dict[str, Any] = {}
    for key, value in data.items():
        if key == "_meta":
            continue
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_policy(value, full_key))
        else:
            flat[full_key] = value
    return flat


def compute_diff(old_flat: Dict[str, Any], new_flat: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute differences between two flattened policy maps.
    Returns a dict structured as:
    {
        "added": {key: new_value, ...},
        "removed": {key: old_value, ...},
        "modified": {key: {"old": old_value, "new": new_value}, ...},
        "unchanged": [key, ...]
    }
    """
    old_keys = set(old_flat.keys())
    new_keys = set(new_flat.keys())

    added = {k: new_flat[k] for k in (new_keys - old_keys)}
    removed = {k: old_flat[k] for k in (old_keys - new_keys)}
    modified = {}
    unchanged = []

    for k in old_keys & new_keys:
        if old_flat[k] != new_flat[k]:
            modified[k] = {"old": old_flat[k], "new": new_flat[k]}
        else:
            unchanged.append(k)

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
    }


def classify_change(key: str, old_val: Any, new_val: Any) -> str:
    """
    Classify a rule change by severity for semantic versioning guidance.
    """
    # If the key is about an ALWAYS/NEVER/CONDITIONAL rule value changing
    if isinstance(old_val, str) and isinstance(new_val, str):
        states = {"ALWAYS", "NEVER", "CONDITIONAL"}
        if old_val in states and new_val in states:
            if old_val != new_val:
                return "MAJOR"
    # If the key is being added or removed, it could be minor or major
    if old_val is None:
        return "MINOR"
    if new_val is None:
        return "MAJOR"
    # Everything else is likely a description/comment change
    return "PATCH"


def format_value(value: Any) -> str:
    """Format a value for display."""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def render_markdown(diff: Dict[str, Any], old_ver: str, new_ver: str, old_path: str, new_path: str) -> str:
    """Render diff as Markdown."""
    lines: List[str] = []
    lines.append(f"# Policy Diff: {Path(old_path).name} → {Path(new_path).name}")
    lines.append(f"")
    lines.append(f"| | Old | New |")
    lines.append(f"|---|---|---|")
    lines.append(f"| **Version** | {old_ver} | {new_ver} |")
    lines.append(f"| **Path** | `{old_path}` | `{new_path}` |")
    lines.append(f"")

    added = diff["added"]
    removed = diff["removed"]
    modified = diff["modified"]
    unchanged = diff["unchanged"]

    total_changes = len(added) + len(removed) + len(modified)
    lines.append(f"## Summary")
    lines.append(f"")
    lines.append(f"- **Added**: {len(added)}")
    lines.append(f"- **Removed**: {len(removed)}")
    lines.append(f"- **Modified**: {len(modified)}")
    lines.append(f"- **Unchanged**: {len(unchanged)}")
    lines.append(f"- **Total changes**: {total_changes}")
    lines.append(f"")

    if added:
        lines.append(f"## Added Rules")
        lines.append(f"")
        for key, value in sorted(added.items()):
            lines.append(f"- `{key}` = `{format_value(value)}`")
        lines.append(f"")

    if removed:
        lines.append(f"## Removed Rules")
        lines.append(f"")
        for key, value in sorted(removed.items()):
            lines.append(f"- `{key}` = `{format_value(value)}`")
        lines.append(f"")

    if modified:
        lines.append(f"## Modified Rules")
        lines.append(f"")
        lines.append(f"| Rule | Old Value | New Value | Severity |")
        lines.append(f"|---|---|---|---|")
        for key in sorted(modified.keys()):
            m = modified[key]
            sev = classify_change(key, m["old"], m["new"])
            lines.append(f"| `{key}` | `{format_value(m['old'])}` | `{format_value(m['new'])}` | {sev} |")
        lines.append(f"")

    if not total_changes:
        lines.append(f"*No differences found.*")
        lines.append(f"")

    return "\n".join(lines)


def render_text(diff: Dict[str, Any], old_ver: str, new_ver: str, old_path: str, new_path: str) -> str:
    """Render diff as plain text."""
    lines: List[str] = []
    lines.append(f"Policy Diff: {old_path} ({old_ver}) → {new_path} ({new_ver})")
    lines.append("")

    added = diff["added"]
    removed = diff["removed"]
    modified = diff["modified"]
    unchanged = diff["unchanged"]

    total_changes = len(added) + len(removed) + len(modified)
    lines.append(f"Summary: +{len(added)} / -{len(removed)} / ~{len(modified)} / ={len(unchanged)} (total changes: {total_changes})")
    lines.append("")

    if added:
        lines.append("[ADDED]")
        for key, value in sorted(added.items()):
            lines.append(f"  + {key} = {format_value(value)}")
        lines.append("")

    if removed:
        lines.append("[REMOVED]")
        for key, value in sorted(removed.items()):
            lines.append(f"  - {key} = {format_value(value)}")
        lines.append("")

    if modified:
        lines.append("[MODIFIED]")
        for key in sorted(modified.keys()):
            m = modified[key]
            sev = classify_change(key, m["old"], m["new"])
            lines.append(f"  ~ {key}")
            lines.append(f"      old: {format_value(m['old'])}")
            lines.append(f"      new: {format_value(m['new'])}")
            lines.append(f"      severity: {sev}")
        lines.append("")

    if not total_changes:
        lines.append("No differences found.")
        lines.append("")

    return "\n".join(lines)


def render_summary(diff: Dict[str, Any], old_ver: str, new_ver: str) -> str:
    """Render a one-line or minimal summary."""
    added = diff["added"]
    removed = diff["removed"]
    modified = diff["modified"]
    total = len(added) + len(removed) + len(modified)

    sevs = {"MAJOR": 0, "MINOR": 0, "PATCH": 0}
    for key, m in modified.items():
        sev = classify_change(key, m["old"], m["new"])
        sevs[sev] += 1
    for _ in added:
        sevs["MINOR"] += 1
    for _ in removed:
        sevs["MAJOR"] += 1

    parts = [f"{old_ver} → {new_ver}: +{len(added)} -{len(removed)} ~{len(modified)}"]
    if total > 0:
        parts.append(f"(severity: MAJOR={sevs['MAJOR']} MINOR={sevs['MINOR']} PATCH={sevs['PATCH']})")
    return " ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate diffs between two policy file versions."
    )
    parser.add_argument("old", help="Path to the older policy JSON file")
    parser.add_argument("new", help="Path to the newer policy JSON file")
    parser.add_argument(
        "--mode",
        choices=["full", "summary"],
        default="full",
        help="Output mode: full diff or summary only",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown"],
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--rule",
        help="Show diff only for a specific rule key (dot notation)",
    )
    parser.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="Exit with code 2 if no differences are found",
    )
    args = parser.parse_args()

    old_data, old_ver, old_path = load_policy(args.old)
    new_data, new_ver, new_path = load_policy(args.new)

    old_flat = flatten_policy(old_data)
    new_flat = flatten_policy(new_data)

    diff = compute_diff(old_flat, new_flat)

    # If a specific rule is requested, filter the diff
    if args.rule:
        rule = args.rule
        filtered: Dict[str, Any] = {"added": {}, "removed": {}, "modified": {}, "unchanged": []}
        if rule in diff["added"]:
            filtered["added"][rule] = diff["added"][rule]
        if rule in diff["removed"]:
            filtered["removed"][rule] = diff["removed"][rule]
        if rule in diff["modified"]:
            filtered["modified"][rule] = diff["modified"][rule]
        if rule in diff["unchanged"]:
            filtered["unchanged"] = [rule]
        diff = filtered

    if args.mode == "summary":
        print(render_summary(diff, old_ver, new_ver))
    else:
        if args.format == "markdown":
            print(render_markdown(diff, old_ver, new_ver, old_path, new_path))
        else:
            print(render_text(diff, old_ver, new_ver, old_path, new_path))

    total_changes = len(diff["added"]) + len(diff["removed"]) + len(diff["modified"])
    if args.fail_on_empty and total_changes == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
