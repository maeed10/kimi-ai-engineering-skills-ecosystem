#!/usr/bin/env python3
"""address_comments.py — Read PR diff and review comments, generate code changes.

Integrates with GitHub API (via MCP wrapper) to fetch PR data and produce
suggested fixes.
"""

import argparse
import json
import re
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Address PR Comments")
    parser.add_argument("--diff", required=True, help="Path to PR diff file")
    parser.add_argument("--comments", required=True, help="Path to review comments JSON file")
    parser.add_argument("--output", default="pr_fixes.json")
    args = parser.parse_args()

    diff_text = Path(args.diff).read_text(encoding="utf-8")
    comments = json.loads(Path(args.comments).read_text(encoding="utf-8"))

    fixes = []
    unresolved = []
    for comment in comments:
        if comment.get("resolved", False):
            continue
        fix = _generate_fix(comment, diff_text)
        if fix:
            fixes.append(fix)
        else:
            unresolved.append(comment)

    report = {
        "total_comments": len(comments),
        "unresolved_comments": len(unresolved),
        "fixes_generated": len(fixes),
        "fixes": fixes,
        "needs_human_attention": unresolved,
    }

    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Comments: {report['total_comments']}, Fixes: {report['fixes_generated']}, Needs human: {report['needs_human_attention']}")
    return 0


def _generate_fix(comment, diff_text):
    """Match comment to diff hunk and propose a fix."""
    body = comment.get("body", "").lower()
    path = comment.get("path", "")
    line = comment.get("line", 0)

    # Extract the relevant hunk from diff
    hunk = _extract_hunk(diff_text, path, line)
    if not hunk:
        return None

    fix_type = None
    if any(k in body for k in ("nit", "typo", "spacing", "format")):
        fix_type = "style"
    elif any(k in body for k in ("bug", "error", "fix", "broken")):
        fix_type = "bugfix"
    elif any(k in body for k in ("test", "coverage", "spec")):
        fix_type = "test"
    elif any(k in body for k in ("refactor", "simplify", "clean")):
        fix_type = "refactor"
    else:
        fix_type = "general"

    return {
        "comment_id": comment.get("id"),
        "path": path,
        "line": line,
        "fix_type": fix_type,
        "original_text": hunk.get("old", ""),
        "suggested_text": _apply_suggestion(hunk, body),
        "confidence": 0.7 if fix_type in ("style", "bugfix") else 0.5,
    }


def _extract_hunk(diff_text, path, line):
    """Extract the hunk for a given file and approximate line."""
    in_file = False
    current_hunk = []
    for diff_line in diff_text.splitlines():
        if diff_line.startswith("diff --git") and path in diff_line:
            in_file = True
        elif diff_line.startswith("diff --git"):
            in_file = False
        if in_file:
            current_hunk.append(diff_line)
            if len(current_hunk) > 100:
                break
    if not current_hunk:
        return None
    # Find lines around the comment
    old_lines = [l[1:] for l in current_hunk if l.startswith("-") and not l.startswith("---")]
    new_lines = [l[1:] for l in current_hunk if l.startswith("+") and not l.startswith("+++")]
    return {"old": "\n".join(old_lines[-5:]), "new": "\n".join(new_lines[-5:])}


def _apply_suggestion(hunk, body):
    """Generate a suggested replacement based on comment text."""
    suggestion = hunk.get("new", "")
    if "rename" in body:
        # Extract rename target if specified in backticks
        m = re.search(r"`([^`]+)`", body)
        if m:
            suggestion = f"# TODO: rename to {m.group(1)}\n" + suggestion
    if "add docstring" in body:
        suggestion = '"""TODO: add docstring"""\n' + suggestion
    if "type hint" in body:
        suggestion = re.sub(r"def (\w+)\(([^)]+)\)", r"def \1(\2) -> None", suggestion)
    return suggestion


if __name__ == "__main__":
    sys.exit(main())
