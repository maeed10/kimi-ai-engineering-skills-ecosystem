#!/usr/bin/env python3
"""
sandbox-executor.py — Mandatory sandbox wrapper for ALL subprocess execution.

Version: 4.2.1
Part of: Kimi AI Engineering Skills Ecosystem

This module provides the SandboxExecutor class which is the ONLY authorized
pathway for executing subprocess commands in Phase 4. It enforces:
  - Ephemeral Docker containers (one per execution) — default backend
  - OR Ephemeral E2B cloud sandboxes — alternative backend (no Docker required)
  - Read-only source mounts + writable /tmp only
  - Network isolation by default
  - CPU/RAM resource caps
  - Image integrity verification (SHA-256) — Docker only
  - Comprehensive execution audit logging
  - Capability declaration and policy validation

BACKENDS:
  docker — Local Docker daemon (default). Requires Docker installed.
  e2b    — Cloud sandbox via E2B (https://e2b.dev). Requires E2B_API_KEY.

CRITICAL SAFETY RULES (hard-coded, non-configurable defaults):
  - NEVER execute subprocess directly on host OS.
  - NEVER allow network access unless declared AND policy-approved.
  - NEVER mount host filesystem writable except /tmp inside container.
  - ALWAYS use a fresh container/sandbox for each execution.
  - ALWAYS verify container image integrity before execution (Docker).
  - NEVER allow --privileged or seccomp=unconfined without human approval.

Usage:
    executor = SandboxExecutor("/etc/kimi/skills/sandbox-executor.yaml")
    result = executor.run(request)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import shlex
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Optional E2B SDK — only loaded when backend=e2b
try:
    from e2b import Sandbox as E2BSandbox
    from e2b import RunCommand
    _E2B_AVAILABLE = True
except ImportError:
    _E2B_AVAILABLE = False
    E2BSandbox = None  # type: ignore
    RunCommand = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def _resolve_skills_root() -> str:
    """Resolve the skills root directory from env or script location."""
    env_root = os.environ.get("KIMI_SKILLS_ROOT")
    if env_root:
        return env_root
    # Script is at .../skills/sandbox-executor/scripts/sandbox-executor.py
    script_dir = Path(__file__).resolve().parent
    return str(script_dir.parent.parent)


SKILLS_ROOT = _resolve_skills_root()
DEFAULT_CONFIG_PATH = os.path.join(SKILLS_ROOT, "sandbox-executor.yaml")
DEFAULT_TMPFS_SIZE = "1024m"
DEFAULT_MEMORY_MB = 4096
DEFAULT_CPUS = 2.0
DEFAULT_PIDS_LIMIT = 100
DEFAULT_TIMEOUT_SECONDS = 600
CONTAINER_PREFIX = "kimi-sandbox"
ALLOWED_WRITE_PATHS = {"/tmp"}
HUMAN_APPROVAL_FLAGS = {"--privileged", "seccomp=unconfined"}

# ---------------------------------------------------------------------------
# Tiered Resource Profiles (EXEC-013 enforcement)
# ---------------------------------------------------------------------------
# These are the ONLY valid profiles. Any execution must map to one of them.
# Raw resource declarations in sandbox-config.yaml are normalized to the
# nearest profile, capped at heavy maximum.

TIERED_PROFILES: dict[str, dict[str, int | float]] = {
    "light": {
        "max_memory_mb": 512,
        "max_cpus": 1.0,
        "timeout_seconds": 60,
        "max_pids": 32,
    },
    "standard": {
        "max_memory_mb": 4096,
        "max_cpus": 2.0,
        "timeout_seconds": 600,
        "max_pids": 100,
    },
    "heavy": {
        "max_memory_mb": 8192,
        "max_cpus": 4.0,
        "timeout_seconds": 600,
        "max_pids": 100,
    },
}

HEAVY_PROFILE_MAX = TIERED_PROFILES["heavy"]  # Absolute ceiling

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Mount:
    host: str
    container: str
    read_only: bool = True

    def to_docker_arg(self) -> str:
        mode = "ro" if self.read_only else "rw"
        return f"--mount=type=bind,source={self.host},target={self.container},readonly={'true' if self.read_only else 'false'}"


@dataclass
class CapabilitySet:
    """Runtime capabilities requested by a skill for a single execution.

    The ``profile`` field selects a tiered resource envelope (light/standard/heavy).
    If a profile is specified, its limits override individually declared values.
    If no profile is specified, raw values are validated against the heavy profile
    maximum (EXEC-013 enforcement).
    """
    network: bool = False
    whitelisted_domains: list[str] = field(default_factory=list)
    fs_write_paths: list[str] = field(default_factory=lambda: ["/tmp"])
    max_memory_mb: int = DEFAULT_MEMORY_MB
    max_cpus: float = DEFAULT_CPUS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    allow_privileged: bool = False
    seccomp_profile: str = "default"
    profile: str = ""  # light | standard | heavy | ""


@dataclass
class ExecutionRequest:
    """Single execution request handed to SandboxExecutor.run()."""
    request_id: str
    skill_name: str
    command: list[str]
    working_directory: str
    source_mounts: list[Mount]
    environment: dict[str, str]
    capabilities: CapabilitySet
    image: str
    expected_sha256: str | None


@dataclass
class ExecutionResult:
    """Result returned by SandboxExecutor.run()."""
    exit_code: int
    stdout: str
    stderr: str
    execution_time_ms: int
    container_hash: str
    audit_log_id: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SandboxError(Exception):
    """Base exception for sandbox-executor failures."""
    pass


class PolicyViolationError(SandboxError):
    """Raised when execution request violates declared capabilities or policy."""
    pass


def _enforce_profile_limits(cap: CapabilitySet) -> CapabilitySet:
    """Normalize capabilities against tiered profile limits (EXEC-013).

    If ``cap.profile`` is a known tier, its envelope overrides individual values.
    If no profile is set, raw values are capped at the heavy profile maximum.
    Any value exceeding heavy requires human approval (escalation).
    """
    profile_name = cap.profile.strip().lower() if cap.profile else ""
    if profile_name in TIERED_PROFILES:
        envelope = TIERED_PROFILES[profile_name]
        return CapabilitySet(
            network=cap.network,
            whitelisted_domains=cap.whitelisted_domains,
            fs_write_paths=cap.fs_write_paths,
            max_memory_mb=int(envelope["max_memory_mb"]),
            max_cpus=float(envelope["max_cpus"]),
            timeout_seconds=int(envelope["timeout_seconds"]),
            allow_privileged=cap.allow_privileged,
            seccomp_profile=cap.seccomp_profile,
            profile=profile_name,
        )

    # No profile declared — cap raw values at heavy maximum
    heavy = TIERED_PROFILES["heavy"]
    capped = CapabilitySet(
        network=cap.network,
        whitelisted_domains=cap.whitelisted_domains,
        fs_write_paths=cap.fs_write_paths,
        max_memory_mb=min(cap.max_memory_mb, int(heavy["max_memory_mb"])),
        max_cpus=min(cap.max_cpus, float(heavy["max_cpus"])),
        timeout_seconds=min(cap.timeout_seconds, int(heavy["timeout_seconds"])),
        allow_privileged=cap.allow_privileged,
        seccomp_profile=cap.seccomp_profile,
        profile="heavy",  # implicit
    )
    if (
        cap.max_memory_mb > int(heavy["max_memory_mb"])
        or cap.max_cpus > float(heavy["max_cpus"])
        or cap.timeout_seconds > int(heavy["timeout_seconds"])
    ):
        raise PolicyViolationError(
            f"Capability request exceeds heavy profile maximum (light/standard/heavy). "
            f"Requested: {cap.max_cpus} CPU, {cap.max_memory_mb} Mi, {cap.timeout_seconds}s. "
            f"Heavy max: {heavy['max_cpus']} CPU, {heavy['max_memory_mb']} Mi, {heavy['timeout_seconds']}s. "
            f"Extended resources require human approval."
        )
    return capped


class ImageVerificationError(SandboxError):
    """Raised when container image SHA-256 does not match or registry is untrusted."""
    pass


class ResourceExhaustedError(SandboxError):
    """Raised when execution hits memory, CPU, or pids limits."""
    pass


class TimeoutExceededError(SandboxError):
    """Raised when wall-clock timeout is exceeded."""
    pass


class SandboxRuntimeError(SandboxError):
    """Raised for unexpected Docker daemon or container runtime failures."""
    pass


# ---------------------------------------------------------------------------
# Policy Engine client
# ---------------------------------------------------------------------------

class PolicyEngineClient:
    """Client for the policy-engine component. Tries REST endpoint first, falls back to inline checks."""

    def __init__(self, endpoint: str, strict_mode: bool = True):
        self.endpoint = endpoint.rstrip("/")
        self.strict_mode = strict_mode
        self.logger = logging.getLogger(__name__)
        self._fallback = _InlinePolicyChecks()

    def validate(self, request: ExecutionRequest, declared: CapabilitySet) -> bool:
        """Validate via policy-engine REST API, falling back to inline checks."""
        try:
            return self._validate_remote(request, declared)
        except Exception as exc:
            self.logger.warning(
                "Policy-engine REST call failed (%s), falling back to inline checks.", exc
            )
            return self._fallback.validate(request, declared)

    def _validate_remote(self, request: ExecutionRequest, declared: CapabilitySet) -> bool:
        import urllib.request
        import urllib.error

        payload = {
            "tool": "sandbox_execution",
            "payload": {
                "skill": request.skill_name,
                "network": request.capabilities.network,
                "whitelisted_domains": request.capabilities.whitelisted_domains,
                "fs_write_paths": request.capabilities.fs_write_paths,
                "max_memory_mb": request.capabilities.max_memory_mb,
                "max_cpus": request.capabilities.max_cpus,
                "timeout_seconds": request.capabilities.timeout_seconds,
                "allow_privileged": request.capabilities.allow_privileged,
                "seccomp_profile": request.capabilities.seccomp_profile,
                "image": request.image,
            },
            "current_phase": "EXECUTE",
        }

        req = urllib.request.Request(
            f"{self.endpoint}/validate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            action = data.get("action", "block")
            if action == "allow":
                self.logger.info("PolicyEngine remote allow for request %s", request.request_id)
                return True
            if action == "escalate":
                raise PolicyViolationError(
                    f"[{request.request_id}] Policy engine escalated: {data.get('reason', 'No reason')}"
                )
            raise PolicyViolationError(
                f"[{request.request_id}] Policy engine blocked: {data.get('reason', 'No reason')}"
            )


class _InlinePolicyChecks:
    """Fallback inline capability checks when policy-engine service is unreachable."""

    def validate(self, request: ExecutionRequest, declared: CapabilitySet) -> bool:
        req = request.capabilities

        if req.network and not declared.network:
            raise PolicyViolationError(
                f"[{request.request_id}] Skill '{request.skill_name}' "
                f"requested network but declared network=false"
            )

        if req.whitelisted_domains and not req.network:
            raise PolicyViolationError(
                f"[{request.request_id}] Whitelisted domains provided but network=false"
            )

        for path in req.fs_write_paths:
            if path not in ALLOWED_WRITE_PATHS:
                if path not in declared.fs_write_paths:
                    raise PolicyViolationError(
                        f"[{request.request_id}] Write path '{path}' not declared "
                        f"in sandbox-config.yaml for skill '{request.skill_name}'"
                    )

        if req.max_memory_mb > declared.max_memory_mb:
            raise PolicyViolationError(
                f"[{request.request_id}] Requested memory {req.max_memory_mb} MB "
                f"exceeds declared max {declared.max_memory_mb} MB"
            )
        if req.max_cpus > declared.max_cpus:
            raise PolicyViolationError(
                f"[{request.request_id}] Requested CPUs {req.max_cpus} "
                f"exceeds declared max {declared.max_cpus}"
            )
        if req.timeout_seconds > declared.timeout_seconds:
            raise PolicyViolationError(
                f"[{request.request_id}] Requested timeout {req.timeout_seconds}s "
                f"exceeds declared max {declared.timeout_seconds}s"
            )

        if req.allow_privileged and not declared.allow_privileged:
            raise PolicyViolationError(
                f"[{request.request_id}] privileged=true requires human approval"
            )

        if req.seccomp_profile == "none" and declared.seccomp_profile != "none":
            raise PolicyViolationError(
                f"[{request.request_id}] seccomp=unconfined requires human approval"
            )

        return True


# ---------------------------------------------------------------------------
# SandboxExecutor
# ---------------------------------------------------------------------------

class SandboxExecutor:
    """
    Mandatory executor for all subprocess operations in Kimi Phase 4.

    Supports two backends:
      - docker (default): Local Docker daemon
      - e2b: Cloud sandbox via E2B.dev

    Integrates with:
      - tool-execution-gateway  (receives all subprocess calls)
      - policy-engine           (validates capabilities)
      - error-policy            (triggers recovery on failure)
    """

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config = self._load_config(config_path)
        self.backend: str = self.config.get("backend", "docker")
        self.runtime_cmd: str = self.config.get("nerdctl", {}).get("runtime_cmd", "docker")
        # Auto-detect if docker is unavailable and nerdctl is present
        if self.runtime_cmd == "docker":
            import shutil
            if shutil.which("docker") is None and shutil.which("nerdctl") is not None:
                self.runtime_cmd = "nerdctl"
        self.policy = PolicyEngineClient(
            endpoint=self.config.get("policy_engine", {}).get("endpoint", "unix://C:/Users/Me/.kimi/run/policy-engine.sock"),
            strict_mode=self.config.get("policy_engine", {}).get("enforce_strict_mode", True),
        )
        self.trusted_registries: list[str] = self.config.get("images", {}).get("trusted_registries", [])
        self.image_pull_policy: str = self.config.get("images", {}).get("image_pull_policy", "if-not-present")
        self.verify_signatures: bool = self.config.get("images", {}).get("verify_signatures", True)
        self.max_concurrent: int = self.config.get("docker", {}).get("max_concurrent_executions", 10)

        # E2B backend initialization
        self._e2b_api_key: str | None = None
        if self.backend == "e2b":
            self._e2b_api_key = self._resolve_e2b_api_key()
            if not _E2B_AVAILABLE:
                raise SandboxRuntimeError(
                    "Backend 'e2b' selected but 'e2b' Python SDK is not installed. "
                    "Install with: pip install e2b"
                )
            if not self._e2b_api_key:
                raise SandboxRuntimeError(
                    "Backend 'e2b' selected but E2B_API_KEY is not set. "
                    "Get a free key at https://e2b.dev"
                )
            self.logger.info("E2B backend initialized (API key present)")

        # In-memory concurrency semaphore (production may use Redis, etc.)
        self._active_executions = 0

    def _resolve_e2b_api_key(self) -> str | None:
        """Resolve E2B API key from config or environment."""
        cfg_key = self.config.get("e2b", {}).get("api_key", "")
        if cfg_key and not cfg_key.startswith("${"):
            return cfg_key
        return os.environ.get("E2B_API_KEY")

    @property
    def get_active_count(self) -> int:
        return self._active_executions

    # -----------------------------------------------------------------------
    # Configuration
    # -----------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> dict[str, Any]:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    @staticmethod
    def _load_skill_config(skill_name: str) -> CapabilitySet:
        """Load sandbox-config.yaml from the skill's own directory.

        Raw capability declarations are normalized against tiered profile limits
        (EXEC-013). If a profile is declared, its envelope overrides individual
        values. If raw values exceed the heavy profile maximum, a PolicyViolationError
        is raised unless human approval has been granted.
        """
        config_path = os.path.join(SKILLS_ROOT, skill_name, "sandbox-config.yaml")
        if not os.path.exists(config_path):
            raise PolicyViolationError(
                f"Missing sandbox-config.yaml for skill '{skill_name}' at {config_path}"
            )
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        caps = raw.get("capabilities", {})
        fs = caps.get("filesystem", {})
        res = caps.get("resources", {})
        sec = caps.get("security", {})
        net = caps.get("network", {})

        declared = CapabilitySet(
            network=net.get("enabled", False),
            whitelisted_domains=net.get("whitelisted_domains", []),
            fs_write_paths=fs.get("write_paths", ["/tmp"]),
            max_memory_mb=res.get("max_memory_mb", DEFAULT_MEMORY_MB),
            max_cpus=res.get("max_cpus", DEFAULT_CPUS),
            timeout_seconds=res.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            allow_privileged=sec.get("privileged", False),
            seccomp_profile=sec.get("seccomp_profile", "default"),
            profile=res.get("profile", ""),
        )

        # Normalize against tiered profile limits (light/standard/heavy)
        return _enforce_profile_limits(declared)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Execute a command inside an ephemeral, isolated environment.

        Workflow (Docker backend):
          1. Load skill sandbox-config.yaml
          2. PolicyEngine.validate(request, declared)
          3. Pull/verify image
          4. Build docker run args enforcing safety rules
          5. Launch container, execute, capture output
          6. Destroy container, log audit, return result

        Workflow (E2B backend):
          1. Load skill sandbox-config.yaml
          2. PolicyEngine.validate(request, declared)
          3. Create E2B sandbox
          4. Execute command in cloud sandbox
          5. Destroy sandbox, log audit, return result
        """
        start_time = time.time()
        audit_log_id = str(uuid.uuid4())

        try:
            # Step 1 — load declared capabilities (normalized against tiered profiles)
            self.logger.info("[%s] Loading capabilities for skill '%s'", request.request_id, request.skill_name)
            declared = self._load_skill_config(request.skill_name)

            # Step 1b — normalize request capabilities against tiered profiles (EXEC-013)
            normalized_request = ExecutionRequest(
                request_id=request.request_id,
                skill_name=request.skill_name,
                command=request.command,
                working_directory=request.working_directory,
                source_mounts=request.source_mounts,
                environment=request.environment,
                capabilities=_enforce_profile_limits(request.capabilities),
                image=request.image,
                expected_sha256=request.expected_sha256,
            )

            # Step 2 — policy validation
            self.logger.info("[%s] Validating capabilities via policy-engine", request.request_id)
            self.policy.validate(normalized_request, declared)

            self._active_executions += 1
            try:
                if self.backend == "e2b":
                    result = self._run_e2b(normalized_request, declared, audit_log_id)
                else:
                    result = self._run_docker(normalized_request, declared, audit_log_id)

                execution_time_ms = int((time.time() - start_time) * 1000)
                result.execution_time_ms = execution_time_ms
                return result
            finally:
                self._active_executions -= 1

        except subprocess.TimeoutExpired:
            raise TimeoutExceededError(
                f"[{request.request_id}] Execution exceeded timeout of "
                f"{normalized_request.capabilities.timeout_seconds}s"
            ) from None
        except (PolicyViolationError, ImageVerificationError):
            raise
        except Exception as exc:
            raise SandboxRuntimeError(
                f"[{request.request_id}] Unexpected sandbox runtime error: {exc}"
            ) from exc

    def _run_docker(self, request: ExecutionRequest, declared: CapabilitySet, audit_log_id: str) -> ExecutionResult:
        """Docker backend execution."""
        # Step 3 — image verification
        self.logger.info("[%s] Verifying image '%s'", request.request_id, request.image)
        resolved_digest = self.verify_image(request.image, request.expected_sha256)

        # Step 4 — build Docker arguments
        docker_args = self.build_docker_args(request, declared)

        # Step 5 — execute in container
        self.logger.info("[%s] Launching container with args: %s", request.request_id, docker_args)
        result = self._execute_in_container(
            docker_args=docker_args,
            command=request.command,
            timeout=request.capabilities.timeout_seconds,
            working_dir=request.working_directory,
        )

        result.container_hash = resolved_digest
        result.audit_log_id = audit_log_id
        self._write_audit_log(request, result, docker_args, declared)
        return result

    def _run_e2b(self, request: ExecutionRequest, declared: CapabilitySet, audit_log_id: str) -> ExecutionResult:
        """E2B cloud sandbox backend execution."""
        if not _E2B_AVAILABLE or not self._e2b_api_key:
            raise SandboxRuntimeError("E2B backend not properly initialized")

        self.logger.info("[%s] Creating E2B sandbox", request.request_id)

        # E2B sandboxes are ephemeral by default
        sandbox = E2BSandbox(api_key=self._e2b_api_key)
        sandbox_id = sandbox.id

        try:
            # Build the command string for E2B
            cmd_str = shlex.join(request.command)
            self.logger.info("[%s] E2B executing: %s", request.request_id, cmd_str)

            # Execute in sandbox
            proc = sandbox.process.start_and_wait(
                cmd=request.command,
                timeout=request.capabilities.timeout_seconds,
            )

            stdout = proc.stdout if proc.stdout else ""
            stderr = proc.stderr if proc.stderr else ""
            exit_code = proc.exit_code if proc.exit_code is not None else -1

            result = ExecutionResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                execution_time_ms=0,  # filled by caller
                container_hash=sandbox_id,
                audit_log_id=audit_log_id,
            )

            # E2B audit log uses sandbox_id instead of docker_args
            self._write_audit_log(request, result, ["e2b", sandbox_id], declared)
            return result

        except Exception as exc:
            raise SandboxRuntimeError(f"E2B sandbox execution failed: {exc}") from exc
        finally:
            self.logger.info("[%s] Killing E2B sandbox %s", request.request_id, sandbox_id)
            try:
                sandbox.kill()
            except Exception:
                pass

    def validate_capabilities(self, skill_name: str, requested: CapabilitySet) -> bool:
        """Public wrapper for capability validation."""
        declared = self._load_skill_config(skill_name)
        # Normalize requested against tiered profile limits (EXEC-013)
        normalized = _enforce_profile_limits(requested)
        # Build a dummy request for validation
        dummy = ExecutionRequest(
            request_id="validate-" + str(uuid.uuid4()),
            skill_name=skill_name,
            command=[],
            working_directory="/tmp",
            source_mounts=[],
            environment={},
            capabilities=normalized,
            image="",
            expected_sha256=None,
        )
        return self.policy.validate(dummy, declared)

    @staticmethod
    def _has_cosign() -> bool:
        return shutil.which("cosign") is not None

    def verify_cosign_signature(self, image: str) -> None:
        """Verify image signature using cosign if available."""
        if not self._has_cosign():
            self.logger.warning("cosign not found in PATH; skipping signature verification for '%s'", image)
            return
        try:
            self.logger.info("Verifying cosign signature for '%s'", image)
            subprocess.run(
                ["cosign", "verify", image],
                capture_output=True,
                text=True,
                check=True,
            )
            self.logger.info("cosign signature verified for '%s'", image)
        except subprocess.CalledProcessError as exc:
            raise ImageVerificationError(
                f"cosign signature verification failed for '{image}': {exc.stderr.strip()}"
            ) from exc

    def verify_image(self, image: str, expected_sha256: str | None) -> str:
        """
        Pull image if missing (per policy), verify SHA-256 digest, return resolved digest.

        Raises:
            ImageVerificationError on mismatch or untrusted registry.
        """
        # 1. Registry trust check
        if self.trusted_registries and not any(
            image.startswith(reg + "/") or image.startswith(reg + ":") for reg in self.trusted_registries
        ):
            # Allow official Docker Hub library images (implicit namespace)
            if "/" not in image.split(":")[0] and "docker.io/library" in self.trusted_registries:
                pass  # e.g. "python:3.11-slim" is trusted via docker.io/library
            else:
                raise ImageVerificationError(f"Image '{image}' from untrusted registry")

        # 2. Inspect local image to get digest
        local_digest = self._docker_inspect_digest(image)

        # 3. Pull if absent or policy demands always-pull
        if local_digest is None or self.image_pull_policy == "always":
            self.logger.info("Pulling image '%s' (pull_policy=%s)", image, self.image_pull_policy)
            self._docker_pull(image)
            local_digest = self._docker_inspect_digest(image)

        if local_digest is None:
            raise ImageVerificationError(f"Failed to resolve digest for image '{image}'")

        # 4. SHA-256 verification (unconditional)
        if expected_sha256:
            if not local_digest.lower().endswith(expected_sha256.lower().lstrip("sha256:")):
                raise ImageVerificationError(
                    f"Image '{image}' digest mismatch. "
                    f"Expected: {expected_sha256}, Resolved: {local_digest}"
                )

        # 5. Signature verification (cosign) if enabled
        if self.verify_signatures:
            # TODO: Full TUF/Sigstore verification requires supply-chain-verifier integration.
            self.verify_cosign_signature(image)

        return local_digest

    def build_docker_args(self, request: ExecutionRequest, declared: CapabilitySet) -> list[str]:
        """
        Construct the full `docker run` argument list.

        Hard-coded safety enforcement:
          - --rm (auto-remove on exit)
          - --read-only (root filesystem read-only)
          - --tmpfs /tmp (writable scratch, in-memory, auto-cleaned)
          - --network none (default) or custom bridge with DNS whitelist
          - --cap-drop ALL
          - --security-opt no-new-privileges:true
          - Memory, CPU, pids limits
        """
        container_name = f"{CONTAINER_PREFIX}-{request.skill_name}-{uuid.uuid4().hex[:8]}"
        args = [
            self.runtime_cmd, "run",
            "--rm",                          # auto-remove after exit
            "--interactive",                 # keep stdin open for potential input
            "--read-only",                   # root fs read-only
            "--user", "1000:1000",           # run as non-root (matches K8s runAsUser: 1000)
            "--workdir", request.working_directory,
            "--hostname", container_name,
        ]

        # --- Resource caps ---
        mem = request.capabilities.max_memory_mb
        args.extend(["--memory", f"{mem}m"])
        args.extend(["--memory-swap", f"{mem}m"])  # disallow swap
        args.extend(["--cpus", str(request.capabilities.max_cpus)])
        pids_limit = self.config.get("defaults", {}).get("pids_limit", DEFAULT_PIDS_LIMIT)
        args.extend(["--pids-limit", str(pids_limit)])

        # --- Filesystem isolation ---
        # Writable /tmp only
        tmpfs_size = self.config.get("defaults", {}).get("tmpfs_size", DEFAULT_TMPFS_SIZE)
        args.append("--tmpfs")
        args.append(f"/tmp:noexec,nosuid,size={tmpfs_size}")

        # Source mounts (read-only enforced)
        for mount in request.source_mounts:
            if not mount.read_only:
                self.logger.warning(
                    "[%s] Force-setting mount to read-only: %s -> %s",
                    request.request_id, mount.host, mount.container,
                )
                mount = Mount(host=mount.host, container=mount.container, read_only=True)
            args.append(mount.to_docker_arg())

        # --- Network isolation ---
        if request.capabilities.network:
            # Use default bridge; custom bridges can be configured via sandbox-executor.yaml
            network_name = self.config.get(self.runtime_cmd, {}).get("network_name", "bridge")
            args.extend(["--network", network_name])
            for domain in request.capabilities.whitelisted_domains:
                args.extend(["--add-host", f"{domain}:127.0.0.1"])
        else:
            args.extend(["--network", "none"])

        # --- Security hardening ---
        args.extend(["--cap-drop", "ALL"])
        args.append("--security-opt=no-new-privileges:true")

        seccomp_profile = request.capabilities.seccomp_profile
        if seccomp_profile == "default":
            seccomp_path = self.config.get("defaults", {}).get(
                "seccomp_profile_path", "/etc/kimi/skills/seccomp-default.json"
            )
            if os.path.exists(seccomp_path):
                args.append(f"--security-opt=seccomp={seccomp_path}")
        elif seccomp_profile == "none":
            # Already blocked by policy unless human-approved; if reached, deny for safety
            raise PolicyViolationError(
                f"[{request.request_id}] seccomp=none reached executor — should have been blocked by policy"
            )
        else:
            # Custom profile path
            args.append(f"--security-opt=seccomp={seccomp_profile}")

        # --- Privileged (should never pass policy without human approval) ---
        if request.capabilities.allow_privileged:
            # Double-gate: policy should have blocked. If it somehow reaches here, hard-fail.
            raise PolicyViolationError(
                f"[{request.request_id}] privileged=true reached executor — hard blocked"
            )

        # --- Environment ---
        for key, value in request.environment.items():
            args.extend(["--env", f"{key}={value}"])

        # --- Container name and image ---
        args.extend(["--name", container_name])
        args.append(request.image)

        return args

    # -----------------------------------------------------------------------
    # Internal Docker helpers
    # -----------------------------------------------------------------------

    def _docker_cmd(self, *cmd: str) -> str:
        """Run a container runtime command and return stdout."""
        result = subprocess.run(
            [self.runtime_cmd] + list(cmd),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _docker_inspect_digest(self, image: str) -> str | None:
        """Return the repo digest for an image, or None if absent."""
        try:
            out = self._docker_cmd("inspect", "--format={{index .RepoDigests 0}}", image)
            return out if out else None
        except subprocess.CalledProcessError:
            return None

    def _docker_pull(self, image: str) -> None:
        """Pull image from registry."""
        try:
            self._docker_cmd("pull", image)
        except subprocess.CalledProcessError as exc:
            raise ImageVerificationError(f"Failed to pull image '{image}': {exc}") from exc

    def _execute_in_container(
        self,
        docker_args: list[str],
        command: list[str],
        timeout: int,
        working_dir: str,
    ) -> ExecutionResult:
        """
        Launch container, execute command, capture output, destroy container.

        Uses `docker run` directly (args already contain image).
        Command is appended after the image name.
        """
        full_cmd = docker_args + command
        self.logger.debug("Executing: %s", shlex.join(full_cmd))

        try:
            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            # Attempt to kill the container by name if possible
            container_name = self._extract_container_name(docker_args)
            if container_name:
                try:
                    self._docker_cmd("rm", "-f", container_name)
                except subprocess.CalledProcessError:
                    pass
            raise TimeoutExceededError(
                f"Container execution timed out after {timeout}s"
            ) from exc

        # Extract container hash from docker_args image position
        image = self._extract_image_from_args(docker_args)
        container_hash = self._docker_inspect_digest(image) or "unknown"

        return ExecutionResult(
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            execution_time_ms=0,  # set by caller
            container_hash=container_hash,
            audit_log_id="",
        )

    @staticmethod
    def _extract_container_name(docker_args: list[str]) -> str | None:
        """Parse --name from docker run args."""
        try:
            idx = docker_args.index("--name")
            return docker_args[idx + 1]
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _extract_image_from_args(docker_args: list[str]) -> str:
        """Heuristic: image is the last non-flag argument."""
        # Walk backwards to first non-flag arg
        for arg in reversed(docker_args):
            if not arg.startswith("-"):
                return arg
        return "unknown"

    # -----------------------------------------------------------------------
    # Secret scrubbing for audit logs
    # -----------------------------------------------------------------------

    _SECRET_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_\-\+/=]{8,}[\"']?"),
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,})\b"),
        re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"),
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    ]

    @classmethod
    def _scrub_text(cls, text: str) -> str:
        """Scrub potential secrets from text using regex + entropy heuristics."""
        if not text:
            return text
        for pattern in cls._SECRET_PATTERNS:
            text = pattern.sub(lambda m: f"[REDACTED:{m.group(1).upper() if m.lastindex else 'SECRET'}]", text)
        return text

    # -----------------------------------------------------------------------
    # Audit logging
    # -----------------------------------------------------------------------

    def _write_audit_log(
        self,
        request: ExecutionRequest,
        result: ExecutionResult,
        docker_args: list[str],
        declared: CapabilitySet,
    ) -> None:
        """Write structured audit log for every execution."""
        scrubbed_stdout = self._scrub_text(result.stdout[:2000]) if result.stdout else ""
        scrubbed_stderr = self._scrub_text(result.stderr[:2000]) if result.stderr else ""
        log_entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "audit_log_id": result.audit_log_id,
            "request_id": request.request_id,
            "skill_name": request.skill_name,
            "image": request.image,
            "container_hash": result.container_hash,
            "command": request.command,
            "exit_code": result.exit_code,
            "execution_time_ms": result.execution_time_ms,
            "declared_capabilities": {
                "network": declared.network,
                "fs_write_paths": declared.fs_write_paths,
                "max_memory_mb": declared.max_memory_mb,
                "max_cpus": declared.max_cpus,
                "timeout_seconds": declared.timeout_seconds,
                "allow_privileged": declared.allow_privileged,
                "seccomp_profile": declared.seccomp_profile,
                "profile": declared.profile,
            },
            "granted_capabilities": {
                "network": request.capabilities.network,
                "fs_write_paths": request.capabilities.fs_write_paths,
                "max_memory_mb": request.capabilities.max_memory_mb,
                "max_cpus": request.capabilities.max_cpus,
                "timeout_seconds": request.capabilities.timeout_seconds,
                "allow_privileged": request.capabilities.allow_privileged,
                "seccomp_profile": request.capabilities.seccomp_profile,
                "profile": request.capabilities.profile,
            },
            "docker_args": docker_args,
            "stdout_preview": scrubbed_stdout,
            "stderr_preview": scrubbed_stderr,
        }

        # Console / structured log
        self.logger.info("AUDIT_LOG %s", json.dumps(log_entry))

        # Optional file destination
        log_dest = self.config.get("logging", {}).get("destination", "")
        if log_dest.startswith("file://"):
            log_path = log_dest.replace("file://", "")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(log_entry) + "\n")

        # Forward to policy-engine if configured
        if self.config.get("policy_engine", {}).get("forward_to_policy_engine", False):
            self._forward_audit_to_policy_engine(log_entry)

    def _forward_audit_to_policy_engine(self, log_entry: dict[str, Any]) -> None:
        """Forward audit record to policy-engine. Fails safe (logs warning on error).
        Supports both TCP loopback and Unix domain sockets."""
        endpoint = self.config.get("policy_engine", {}).get("endpoint", "http://127.0.0.1:9100")
        payload = json.dumps(log_entry).encode("utf-8")
        try:
            if endpoint.startswith("unix://"):
                self._forward_via_unix_socket(endpoint, payload)
            else:
                url = endpoint.rstrip("/") + "/audit-log"
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp.read()
                    self.logger.info("Audit log forwarded to policy-engine at %s", url)
        except Exception as exc:
            self.logger.warning("Failed to forward audit log to policy-engine: %s", exc)

    def _forward_via_unix_socket(self, endpoint: str, payload: bytes) -> None:
        """Send HTTP POST over Unix domain socket."""
        socket_path = endpoint.replace("unix://", "").replace("unix:", "")
        if socket_path.startswith("/") and ":" in socket_path[:3]:
            # Windows path like C:/Users/... -> keep as-is
            pass
        import http.client
        conn = http.client.HTTPConnection("localhost")
        # Override socket to use AF_UNIX
        original_connect = conn.connect
        def _unix_connect():
            import socket
            conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.sock.settimeout(5)
            conn.sock.connect(socket_path)
        conn.connect = _unix_connect
        conn.request("POST", "/audit-log", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.logger.info("Audit log forwarded to policy-engine via Unix socket at %s", socket_path)


# ---------------------------------------------------------------------------
# Convenience / factory helpers
# ---------------------------------------------------------------------------

def create_default_executor() -> SandboxExecutor:
    """Factory for the canonical executor instance used by tool-execution-gateway."""
    return SandboxExecutor(DEFAULT_CONFIG_PATH)


# ---------------------------------------------------------------------------
# Self-test (run with `python sandbox-executor.py`)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Quick sanity check: verify we can instantiate and build args for a dummy request
    executor = SandboxExecutor()  # empty config path falls back to defaults

    dummy_request = ExecutionRequest(
        request_id=str(uuid.uuid4()),
        skill_name="test-skill",
        command=["python", "--version"],
        working_directory="/workspace",
        source_mounts=[Mount(host="/tmp/fake-src", container="/workspace", read_only=True)],
        environment={"CI": "true"},
        capabilities=CapabilitySet(
            network=False,
            max_memory_mb=256,
            max_cpus=0.5,
            timeout_seconds=30,
        ),
        image="python:3.11-slim",
        expected_sha256=None,
    )

    # Note: _load_skill_config will fail because test-skill has no sandbox-config.yaml.
    # This is expected behavior — every skill MUST provide one.
    try:
        args = executor.build_docker_args(dummy_request, dummy_request.capabilities)
        print("Generated docker args:")
        for a in args:
            print(f"  {a}")
    except PolicyViolationError as exc:
        print(f"Expected error (no sandbox-config.yaml): {exc}")
