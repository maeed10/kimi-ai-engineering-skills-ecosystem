#!/usr/bin/env python3
"""
gemini-router — Backward-compatibility stub.

DEPRECATED: Use multi-model-router directly. This script delegates all calls
to multi-model-router with provider locked to gemini.

Removal date: 2026-11-07
"""

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Gemini router (deprecated stub)")
    parser.add_argument("--task-type", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--tools", default="[]")
    args = parser.parse_args()

    # Delegate to multi-model-router with provider=gemini
    multi_router = Path(__file__).parent.parent.parent / "multi-model-router" / "scripts" / "multi-model-router.py"
    cmd = [
        sys.executable,
        str(multi_router),
        "--provider", "gemini",
        "--task-type", args.task_type,
        "--phase", args.phase,
        "--payload", args.payload,
        "--tools", args.tools,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr:
        print("WARN: [gemini-router] deprecated stub — migrate to multi-model-router", file=sys.stderr)
        print(result.stderr, end="", file=sys.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
