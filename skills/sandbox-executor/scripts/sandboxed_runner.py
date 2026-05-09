#!/usr/bin/env python3
"""
sandboxed_runner.py — Drop-in subprocess replacement for Phase 4 skill scripts.

Usage in a skill script:
    from sandboxed_runner import run, check_output, SandboxRunner

    result = run(["python", "-m", "pytest"], cwd="/workspace", timeout=300)

Environment:
    KIMI_SKILLS_ROOT — root of the skills directory (auto-detected if absent)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure sandbox-executor.py is importable
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


class SandboxRunner:
    """Convenience wrapper around SandboxExecutor for skill scripts."""

    def __init__(self, skill_name: str, skills_root: Optional[str] = None):
        self.skill_name = skill_name
        self.skills_root = skills_root or os.environ.get("KIMI_SKILLS_ROOT", str(_SCRIPT_DIR.parent.parent))
        self.executor = SandboxExecutor(os.path.join(self.skills_root, "sandbox-executor.yaml"))

    def run(
        self,
        command: List[str],
        cwd: str = "/workspace",
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        network: bool = False,
        whitelisted_domains: Optional[List[str]] = None,
        source_mounts: Optional[List[Dict[str, Any]]] = None,
        stdout_callback=None,
    ) -> ExecutionResult:
        """Run a command inside the sandbox."""
        import uuid

        # Load declared capabilities to get defaults
        declared = self.executor._load_skill_config(self.skill_name)

        caps = CapabilitySet(
            network=network or declared.network,
            whitelisted_domains=whitelisted_domains or declared.whitelisted_domains,
            fs_write_paths=declared.fs_write_paths,
            max_memory_mb=declared.max_memory_mb,
            max_cpus=declared.max_cpus,
            timeout_seconds=timeout or declared.timeout_seconds,
            allow_privileged=declared.allow_privileged,
            seccomp_profile=declared.seccomp_profile,
        )

        mounts = []
        if source_mounts:
            for m in source_mounts:
                mounts.append(Mount(host=m["host"], container=m["container"], read_only=m.get("read_only", True)))
        else:
            # Default mount: current working directory -> /workspace
            mounts.append(Mount(host=os.getcwd(), container="/workspace", read_only=True))

        # Find image from sandbox-config
        import yaml
        config_path = os.path.join(self.skills_root, self.skill_name, "sandbox-config.yaml")
        image = "python:3.11-slim"
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            image = cfg.get("runtime", {}).get("image", image)

        request = ExecutionRequest(
            request_id=str(uuid.uuid4()),
            skill_name=self.skill_name,
            command=command,
            working_directory=cwd,
            source_mounts=mounts,
            environment=env or {},
            capabilities=caps,
            image=image,
            expected_sha256=None,
        )

        return self.executor.run(request)


# Module-level helpers for simple usage
_default_runner: Optional[SandboxRunner] = None


def _get_runner(skill_name: str) -> SandboxRunner:
    global _default_runner
    if _default_runner is None or _default_runner.skill_name != skill_name:
        _default_runner = SandboxRunner(skill_name)
    return _default_runner


def run(
    command: List[str],
    *,
    skill_name: str,
    cwd: str = "/workspace",
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
    network: bool = False,
    whitelisted_domains: Optional[List[str]] = None,
    source_mounts: Optional[List[Dict[str, Any]]] = None,
) -> ExecutionResult:
    """Run a command sandboxed. Returns ExecutionResult."""
    return _get_runner(skill_name).run(
        command=command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        network=network,
        whitelisted_domains=whitelisted_domains,
        source_mounts=source_mounts,
    )


def check_output(
    command: List[str],
    *,
    skill_name: str,
    cwd: str = "/workspace",
    env: Optional[Dict[str, str]] = None,
    timeout: Optional[int] = None,
    network: bool = False,
) -> str:
    """Run a command sandboxed and return stdout as string."""
    result = _get_runner(skill_name).run(
        command=command,
        cwd=cwd,
        env=env,
        timeout=timeout,
        network=network,
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"Sandboxed command failed (exit {result.exit_code}): {result.stderr}"
        )
    return result.stdout
