#!/usr/bin/env python3
"""
run-skill-sandboxed.py — Generic launcher to run any skill script inside a sandbox.

Usage:
    python run-skill-sandboxed.py --skill code-tester -- python -m pytest -v
    python run-skill-sandboxed.py --skill security-auditor --network -- python run-sast.py --target ./src

Environment:
    KIMI_SKILLS_ROOT — root directory containing skill folders
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

# sandbox-executor.py has a hyphen; load dynamically
import importlib.util
_sandbox_path = _SCRIPT_DIR / "sandbox-executor.py"
_sandbox_spec = importlib.util.spec_from_file_location("sandbox_executor", str(_sandbox_path))
_sandbox_mod = importlib.util.module_from_spec(_sandbox_spec)
sys.modules["sandbox_executor"] = _sandbox_mod
_sandbox_spec.loader.exec_module(_sandbox_mod)  # type: ignore

SandboxExecutor = _sandbox_mod.SandboxExecutor
ExecutionRequest = _sandbox_mod.ExecutionRequest
ExecutionResult = _sandbox_mod.ExecutionResult
CapabilitySet = _sandbox_mod.CapabilitySet
Mount = _sandbox_mod.Mount


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a skill command inside an isolated sandbox.",
    )
    parser.add_argument("--skill", required=True, help="Skill name (must have sandbox-config.yaml)")
    parser.add_argument("--cwd", default="/workspace", help="Working directory inside container")
    parser.add_argument("--network", action="store_true", help="Enable network access")
    parser.add_argument("--timeout", type=int, help="Override timeout seconds")
    parser.add_argument("--memory", type=int, help="Override memory limit (MB)")
    parser.add_argument("--cpus", type=float, help="Override CPU limit")
    parser.add_argument(
        "--mount", action="append", default=[],
        help="Bind mount in form host_path:container_path (read-only by default)"
    )
    parser.add_argument("--mount-rw", action="append", default=[], help="Writable bind mount host_path:container_path")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run inside sandbox")

    args = parser.parse_args()

    if not args.command:
        print("Error: No command provided.", file=sys.stderr)
        return 1

    # Strip leading '--' if present
    if args.command[0] == "--":
        args.command = args.command[1:]

    executor = SandboxExecutor()
    declared = executor._load_skill_config(args.skill)

    # Build capability set with overrides
    caps = CapabilitySet(
        network=args.network or declared.network,
        whitelisted_domains=declared.whitelisted_domains,
        fs_write_paths=declared.fs_write_paths,
        max_memory_mb=args.memory or declared.max_memory_mb,
        max_cpus=args.cpus or declared.max_cpus,
        timeout_seconds=args.timeout or declared.timeout_seconds,
        allow_privileged=declared.allow_privileged,
        seccomp_profile=declared.seccomp_profile,
    )

    # Build mounts
    mounts: List[Mount] = []
    for m in args.mount:
        parts = m.split(":")
        if len(parts) != 2:
            print(f"Error: Invalid mount format: {m}", file=sys.stderr)
            return 1
        mounts.append(Mount(host=parts[0], container=parts[1], read_only=True))
    for m in args.mount_rw:
        parts = m.split(":")
        if len(parts) != 2:
            print(f"Error: Invalid mount format: {m}", file=sys.stderr)
            return 1
        mounts.append(Mount(host=parts[0], container=parts[1], read_only=False))

    # Default mount: current dir -> /workspace
    if not mounts:
        mounts.append(Mount(host=os.getcwd(), container="/workspace", read_only=False))

    # Resolve image
    import yaml
    skills_root = os.environ.get("KIMI_SKILLS_ROOT", str(_SCRIPT_DIR.parent.parent))
    config_path = os.path.join(skills_root, args.skill, "sandbox-config.yaml")
    image = "python:3.11-slim"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        image = cfg.get("runtime", {}).get("image", image)

    import uuid
    request = ExecutionRequest(
        request_id=str(uuid.uuid4()),
        skill_name=args.skill,
        command=args.command,
        working_directory=args.cwd,
        source_mounts=mounts,
        environment={},
        capabilities=caps,
        image=image,
        expected_sha256=None,
    )

    print(f"[sandbox] skill={args.skill} image={image}")
    print(f"[sandbox] command={' '.join(args.command)}")
    print(f"[sandbox] network={caps.network} memory={caps.max_memory_mb}MB cpus={caps.max_cpus}")

    try:
        result = executor.run(request)
    except Exception as exc:
        print(f"[sandbox] ERROR: {exc}", file=sys.stderr)
        return 1

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    print(f"[sandbox] exit_code={result.exit_code} time_ms={result.execution_time_ms}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
