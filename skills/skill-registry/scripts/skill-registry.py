#!/usr/bin/env python3
"""
skill-registry.py

Skill lifecycle manager for the Kimi AI Engineering Skills Ecosystem v4.0.

Controls which skills are active, loaded, or purged. The Orchestrator composes
LLM prompts ONLY from ACTIVE skills for the current phase. Prevents stale skills
from persisting in context, addressing ARC-2.2 (severity 8/10).

Usage:
    from skill_registry import SkillRegistry, SkillState, LifecycleTransition

    registry = SkillRegistry(skills_dir=".kimi/skills/", policy_engine=policy_engine)
    active_skills = registry.get_active_skills_for_phase("code_review")
    registry.transition_phase("testing")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple


# ---------------------------------------------------------------------------
# Enums and Constants
# ---------------------------------------------------------------------------

class SkillState(Enum):
    """Canonical lifecycle states for a skill."""
    REGISTERED = auto()   # Discovered; manifest parsed
    LOADED = auto()       # Integrity verified; ready
    ACTIVE = auto()       # In LLM context; tools callable
    UNLOADED = auto()     # Removed from context
    PURGED = auto()       # Terminal; cannot be reactivated


class ViolationType(Enum):
    """Types of skill reference violations detected in LLM output."""
    LLM_REACTIVATION_ATTEMPT = auto()   # References an UNLOADED skill
    RESURRECTION_ATTEMPT = auto()       # References a PURGED skill
    HALLUCINATED_SKILL = auto()         # References a non-existent skill


class TransitionReason(Enum):
    """Canonical reasons for lifecycle transitions."""
    DISCOVERED = "discovered from disk"
    INTEGRITY_VERIFIED = "SHA-256 integrity verified"
    INTEGRITY_FAILED = "SHA-256 mismatch"
    POLICY_ALLOWED = "policy validation passed"
    POLICY_BLOCKED = "policy validation failed"
    PHASE_MATCHED = "phase in allowed_phases"
    PHASE_UNMATCHED = "phase not in allowed_phases"
    DEPENDENCIES_MET = "all dependencies active"
    DEPENDENCIES_UNMET = "dependencies not satisfied"
    PHASE_CHANGE = "phase transition"
    NO_REMAINING_PHASES = "not needed in remaining phases"
    SESSION_END = "session terminated"
    MANUAL_REQUEST = "manual orchestrator request"
    LLM_REFERENCE_BLOCKED = "blocked due to invalid LLM reference"


LOG_FORMAT = "[{timestamp}] [{phase}] {skill}: {old_state} → {new_state} | {reason} | policy={policy} | sha256={sha256}"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillManifest:
    """Machine-readable capability manifest for a skill."""
    name: str
    version: str
    type: str
    allowed_phases: Tuple[str, ...]
    required_permissions: Tuple[str, ...]
    tools: Tuple[str, ...]
    side_effects: Tuple[str, ...]
    dependencies: Tuple[str, ...] = field(default_factory=tuple)
    integrity_hash: str = ""
    required_capabilities: Dict[str, Any] = field(default_factory=dict)
    parameter_constraints: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    risk_level: str = "low"
    author: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SkillManifest:
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.0.0"),
            type=data.get("type", "utility"),
            allowed_phases=tuple(data.get("allowed_phases", [])),
            required_permissions=tuple(data.get("required_permissions", [])),
            tools=tuple(data.get("tools", [])),
            side_effects=tuple(data.get("side_effects", [])),
            dependencies=tuple(data.get("dependencies", [])),
            integrity_hash=data.get("integrity_hash", ""),
            required_capabilities=data.get("required_capabilities", {}),
            parameter_constraints=data.get("parameter_constraints", {}),
            risk_level=data.get("risk_level", "low"),
            author=data.get("author", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "allowed_phases": list(self.allowed_phases),
            "required_permissions": list(self.required_permissions),
            "tools": list(self.tools),
            "side_effects": list(self.side_effects),
            "dependencies": list(self.dependencies),
            "integrity_hash": self.integrity_hash,
            "required_capabilities": self.required_capabilities,
            "parameter_constraints": self.parameter_constraints,
            "risk_level": self.risk_level,
            "author": self.author,
        }


@dataclass
class LifecycleTransition:
    """Record of a single lifecycle state change."""
    timestamp: str
    skill_name: str
    old_state: SkillState
    new_state: SkillState
    reason: TransitionReason
    phase: str
    policy_result: str
    sha256_hash: str
    justification: str = ""


@dataclass
class SkillViolation:
    """Record of an LLM skill reference violation."""
    timestamp: str
    violation_type: ViolationType
    skill_name: str
    phase: str
    context: str = ""  # Snippet of LLM output containing the reference


@dataclass
class SkillRecord:
    """Internal record tracking a skill's current state and history."""
    name: str
    path: Path
    manifest: SkillManifest
    state: SkillState = SkillState.REGISTERED
    transition_history: List[LifecycleTransition] = field(default_factory=list)
    current_sha256: str = ""
    last_verified: Optional[str] = None


# ---------------------------------------------------------------------------
# Protocols (Integration Points)
# ---------------------------------------------------------------------------

class PolicyEngine(Protocol):
    """Protocol for policy-engine integration."""
    def validate(self, manifest: SkillManifest, context: Dict[str, Any]) -> ValidationResult:
        ...


@dataclass
class ValidationResult:
    """Result from policy-engine validation."""
    allowed: bool
    reason: str = ""
    missing_permissions: List[str] = field(default_factory=list)


class PhaseController(Protocol):
    """Protocol for phase-controller integration."""
    def get_current_phase(self) -> str:
        ...

    def get_remaining_phases(self) -> List[str]:
        ...


class ToolExecutionGateway(Protocol):
    """Protocol for tool-execution-gateway integration."""
    def validate_tool_call(
        self,
        skill_name: str,
        tool_name: str,
        args: Dict[str, Any],
        manifest_tools: List[str],
        parameter_constraints: Dict[str, Dict[str, Any]],
    ) -> ValidationResult:
        ...


class SandboxExecutor(Protocol):
    """Protocol for sandbox-executor integration."""
    def configure_from_capabilities(self, capabilities: Dict[str, Any]) -> Dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Core SkillRegistry Class
# ---------------------------------------------------------------------------

class SkillRegistry:
    """
    Central registry for skill lifecycle management.

    Responsibilities:
      1. Discover skills from disk and parse manifests.
      2. Maintain explicit state machines (REGISTERED → LOADED → ACTIVE → UNLOADED → PURGED).
      3. Verify SHA-256 integrity before every LOADED → ACTIVE transition.
      4. Validate policy compliance via policy-engine.
      5. Compose the set of ACTIVE skills for the current phase.
      6. Track and flag invalid LLM skill references.
      7. Log every transition with timestamp, phase, and justification.

    Safety invariants (enforced at every code path):
      - ONLY ACTIVE skills are returned for prompt composition.
      - Integrity check MUST pass before ACTIVE.
      - UNLOADED skills CANNOT be "reactivated" by LLM references.
      - Tool calls are blocked for non-ACTIVE skills.
    """

    def __init__(
        self,
        skills_dir: str = ".kimi/skills/",
        policy_engine: Optional[PolicyEngine] = None,
        phase_controller: Optional[PhaseController] = None,
        sandbox_executor: Optional[SandboxExecutor] = None,
        log_file: Optional[str] = None,
    ):
        self.skills_dir = Path(skills_dir).expanduser().resolve()
        self.policy_engine = policy_engine
        self.phase_controller = phase_controller
        self.sandbox_executor = sandbox_executor
        self.log_file = Path(log_file).expanduser().resolve() if log_file else None

        # Internal state
        self._skills: Dict[str, SkillRecord] = {}
        self._violations: List[SkillViolation] = []
        self._current_phase: str = "init"
        self._remaining_phases: List[str] = []

        # Logger
        self._logger = logging.getLogger("skill-registry")
        self._setup_logger()

        # Discovery on init
        self._discover_skills()

    # -----------------------------------------------------------------------
    # Logger Setup
    # -----------------------------------------------------------------------

    def _setup_logger(self) -> None:
        self._logger.setLevel(logging.DEBUG)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    # -----------------------------------------------------------------------
    # Discovery
    # -----------------------------------------------------------------------

    def _discover_skills(self) -> None:
        """
        Scan `.kimi/skills/` for SKILL.md files, parse manifests, set state to REGISTERED.
        """
        if not self.skills_dir.exists():
            self._logger.warning(f"Skills directory does not exist: {self.skills_dir}")
            return

        for skill_path in self.skills_dir.rglob("SKILL.md"):
            skill_dir = skill_path.parent
            manifest = self._load_manifest(skill_dir)
            if manifest is None:
                self._logger.error(f"No valid manifest found for skill at {skill_dir}")
                continue

            name = manifest.name or skill_dir.name
            record = SkillRecord(
                name=name,
                path=skill_dir,
                manifest=manifest,
                state=SkillState.REGISTERED,
            )
            self._skills[name] = record
            self._log_transition(
                record,
                SkillState.REGISTERED,
                TransitionReason.DISCOVERED,
                policy="n/a",
                sha256="",
                justification=f"discovered at {skill_dir}",
            )
            self._logger.info(f"Discovered skill '{name}' → REGISTERED")

    def _load_manifest(self, skill_dir: Path) -> Optional[SkillManifest]:
        """
        Load manifest from `manifest.json` or extract from `SKILL.md` frontmatter.
        """
        manifest_json = skill_dir / "manifest.json"
        if manifest_json.exists():
            try:
                with open(manifest_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return SkillManifest.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                self._logger.error(f"Invalid manifest.json at {skill_dir}: {exc}")
                return None

        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            return self._parse_frontmatter(skill_md, skill_dir.name)

        return None

    def _parse_frontmatter(self, skill_md: Path, default_name: str) -> Optional[SkillManifest]:
        """Extract manifest data from SKILL.md YAML-like frontmatter (between --- lines)."""
        try:
            text = skill_md.read_text(encoding="utf-8")
            if text.startswith("---"):
                _, frontmatter, rest = text.split("---", 2)
                # Simple key: value extraction
                data: Dict[str, Any] = {"name": default_name}
                for line in frontmatter.strip().splitlines():
                    if ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip()
                        val = val.strip()
                        if val.startswith("[") and val.endswith("]"):
                            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
                        data[key] = val
                return SkillManifest.from_dict(data)
        except Exception as exc:
            self._logger.error(f"Failed to parse frontmatter from {skill_md}: {exc}")
        return None

    # -----------------------------------------------------------------------
    # Integrity Verification
    # -----------------------------------------------------------------------

    def _compute_sha256(self, skill_dir: Path) -> str:
        """Compute SHA-256 over all canonical files in the skill directory."""
        hasher = hashlib.sha256()
        # Canonical files: SKILL.md, manifest.json, scripts/*.py
        canonical_patterns = ["SKILL.md", "manifest.json", "scripts/*"]
        files: List[Path] = []
        for pattern in canonical_patterns:
            files.extend(skill_dir.glob(pattern))
        # Sort for deterministic hashing
        for file_path in sorted(files):
            if file_path.is_file():
                hasher.update(file_path.read_bytes())
                hasher.update(b"\x00")  # delimiter
        return hasher.hexdigest()

    def _verify_integrity(self, record: SkillRecord) -> bool:
        """
        Verify SHA-256 of skill files against manifest.integrity_hash.
        Safety rule: ALWAYS verify before LOADED → ACTIVE.
        """
        if not record.manifest.integrity_hash:
            self._logger.warning(f"Skill '{record.name}' has no integrity_hash in manifest")
            self._log_transition(
                record,
                record.state,
                TransitionReason.INTEGRITY_FAILED,
                policy="n/a",
                sha256="missing",
                justification="manifest missing integrity_hash",
            )
            return False

        computed = self._compute_sha256(record.path)
        record.current_sha256 = computed
        record.last_verified = self._now()

        if computed == record.manifest.integrity_hash:
            self._logger.debug(f"Integrity verified for '{record.name}': {computed}")
            return True

        self._logger.error(
            f"Integrity FAILURE for '{record.name}': computed={computed}, expected={record.manifest.integrity_hash}"
        )
        self._log_transition(
            record,
            record.state,
            TransitionReason.INTEGRITY_FAILED,
            policy="n/a",
            sha256=computed,
            justification="SHA-256 mismatch",
        )
        return False

    # -----------------------------------------------------------------------
    # Policy Validation
    # -----------------------------------------------------------------------

    def _validate_policy(self, record: SkillRecord, context: Optional[Dict[str, Any]] = None) -> ValidationResult:
        """Validate skill activation against policy-engine."""
        if self.policy_engine is None:
            return ValidationResult(allowed=True, reason="no policy engine configured")

        ctx = context or {}
        ctx["current_phase"] = self._current_phase
        result = self.policy_engine.validate(record.manifest, ctx)
        return result

    # -----------------------------------------------------------------------
    # Dependency Resolution
    # -----------------------------------------------------------------------

    def _check_dependencies(self, record: SkillRecord) -> bool:
        """Return True if all skills in manifest.dependencies are ACTIVE."""
        for dep in record.manifest.dependencies:
            dep_record = self._skills.get(dep)
            if dep_record is None or dep_record.state != SkillState.ACTIVE:
                self._logger.warning(
                    f"Dependency '{dep}' not ACTIVE for skill '{record.name}'"
                )
                return False
        return True

    # -----------------------------------------------------------------------
    # State Transitions
    # -----------------------------------------------------------------------

    def _transition(
        self,
        record: SkillRecord,
        new_state: SkillState,
        reason: TransitionReason,
        policy: str = "n/a",
        sha256: str = "",
        justification: str = "",
    ) -> bool:
        """
        Execute a lifecycle state transition with logging.
        Returns True if transition succeeded.
        """
        old_state = record.state
        record.state = new_state
        transition = LifecycleTransition(
            timestamp=self._now(),
            skill_name=record.name,
            old_state=old_state,
            new_state=new_state,
            reason=reason,
            phase=self._current_phase,
            policy_result=policy,
            sha256_hash=sha256 or record.current_sha256,
            justification=justification,
        )
        record.transition_history.append(transition)
        self._persist_log(transition)
        self._logger.info(
            f"Transition: {record.name} | {old_state.name} → {new_state.name} | {reason.value}"
        )
        return True

    def _log_transition(
        self,
        record: SkillRecord,
        new_state: SkillState,
        reason: TransitionReason,
        policy: str,
        sha256: str,
        justification: str,
    ) -> None:
        """Log a transition without changing state (used for blocked attempts)."""
        transition = LifecycleTransition(
            timestamp=self._now(),
            skill_name=record.name,
            old_state=record.state,
            new_state=new_state,
            reason=reason,
            phase=self._current_phase,
            policy_result=policy,
            sha256_hash=sha256,
            justification=justification,
        )
        record.transition_history.append(transition)
        self._persist_log(transition)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # -----------------------------------------------------------------------
    # Prompt Composition Interface
    # -----------------------------------------------------------------------

    def get_active_skills_for_phase(
        self,
        phase: str,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> List[SkillRecord]:
        """
        Main orchestrator interface: return all ACTIVE skills for the given phase.

        Workflow:
          1. Update current phase.
          2. Filter skills where phase ∈ allowed_phases.
          3. Transition filtered skills: REGISTERED → LOADED (integrity check).
          4. Transition verified skills: LOADED → ACTIVE (policy + dependencies).
          5. Transition non-matching ACTIVE skills → UNLOADED.
          6. Transition UNLOADED skills with no remaining phases → PURGED.
          7. Return list of ACTIVE skill records.
        """
        self._current_phase = phase
        self._logger.info(f"=== Phase activation: {phase} ===")

        # Step 1: Identify skills allowed for this phase
        allowed_skills: List[SkillRecord] = []
        for record in self._skills.values():
            if phase in record.manifest.allowed_phases:
                allowed_skills.append(record)

        # Step 2: Transition allowed skills toward ACTIVE
        for record in allowed_skills:
            if record.state == SkillState.REGISTERED:
                if self._verify_integrity(record):
                    self._transition(
                        record,
                        SkillState.LOADED,
                        TransitionReason.INTEGRITY_VERIFIED,
                        policy="pending",
                        sha256=record.current_sha256,
                        justification="integrity verified on load",
                    )
                else:
                    continue  # remains REGISTERED

            if record.state == SkillState.LOADED:
                policy_result = self._validate_policy(record, extra_context)
                deps_ok = self._check_dependencies(record)
                if policy_result.allowed and deps_ok:
                    self._transition(
                        record,
                        SkillState.ACTIVE,
                        TransitionReason.POLICY_ALLOWED,
                        policy=policy_result.reason,
                        sha256=record.current_sha256,
                        justification="policy and deps satisfied",
                    )
                else:
                    reason = TransitionReason.POLICY_BLOCKED
                    if not deps_ok:
                        reason = TransitionReason.DEPENDENCIES_UNMET
                    self._log_transition(
                        record,
                        SkillState.ACTIVE,
                        reason,
                        policy=policy_result.reason,
                        sha256=record.current_sha256,
                        justification="blocked from activation",
                    )

            # If already ACTIVE, re-verify integrity (safety rule #4)
            if record.state == SkillState.ACTIVE:
                if not self._verify_integrity(record):
                    self._transition(
                        record,
                        SkillState.UNLOADED,
                        TransitionReason.INTEGRITY_FAILED,
                        policy="n/a",
                        sha256=record.current_sha256,
                        justification="re-verification failed; unloading",
                    )

        # Step 3: Transition disallowed ACTIVE skills → UNLOADED
        allowed_names = {r.name for r in allowed_skills}
        for record in self._skills.values():
            if record.state == SkillState.ACTIVE and record.name not in allowed_names:
                self._transition(
                    record,
                    SkillState.UNLOADED,
                    TransitionReason.PHASE_UNMATCHED,
                    policy="n/a",
                    sha256=record.current_sha256,
                    justification=f"phase '{phase}' not in allowed_phases",
                )

        # Step 4: Transition UNLOADED skills not needed for remaining phases → PURGED
        for record in self._skills.values():
            if record.state == SkillState.UNLOADED:
                needed = any(
                    rem_phase in record.manifest.allowed_phases
                    for rem_phase in self._remaining_phases
                )
                if not needed:
                    self._transition(
                        record,
                        SkillState.PURGED,
                        TransitionReason.NO_REMAINING_PHASES,
                        policy="n/a",
                        sha256=record.current_sha256,
                        justification="no remaining phases require this skill",
                    )

        active = [r for r in self._skills.values() if r.state == SkillState.ACTIVE]
        self._logger.info(
            f"Phase '{phase}' active skills: {[r.name for r in active]}"
        )
        return active

    def get_active_skills(self) -> List[SkillRecord]:
        """Return all currently ACTIVE skills without triggering transitions."""
        return [r for r in self._skills.values() if r.state == SkillState.ACTIVE]

    # -----------------------------------------------------------------------
    # Phase Change
    # -----------------------------------------------------------------------

    def transition_phase(
        self,
        new_phase: str,
        remaining_phases: Optional[List[str]] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> List[SkillRecord]:
        """
        Handle phase change from phase-controller.
        Returns the new set of ACTIVE skills.
        """
        self._remaining_phases = remaining_phases or []
        self._logger.info(
            f"=== Phase transition: {self._current_phase} → {new_phase} ==="
        )
        return self.get_active_skills_for_phase(new_phase, extra_context)

    def on_phase_change(
        self,
        new_phase: str,
        remaining_phases: List[str],
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> List[SkillRecord]:
        """Alias for transition_phase; explicit naming for phase-controller integration."""
        return self.transition_phase(new_phase, remaining_phases, extra_context)

    # -----------------------------------------------------------------------
    # Reference Tracking
    # -----------------------------------------------------------------------

    def scan_for_skill_references(self, llm_output: str) -> List[SkillViolation]:
        """
        Scan LLM output for skill name references.
        Flag violations where referenced skills are not ACTIVE.
        """
        violations: List[SkillViolation] = []
        # Extract skill mentions: match words that correspond to known skill names
        # Also capture patterns like "using skill-name" or "@skill-name"
        words = set(re.findall(r"[a-zA-Z0-9_-]+", llm_output))

        for name, record in self._skills.items():
            if name not in words:
                continue
            if record.state == SkillState.ACTIVE:
                continue  # normal usage

            snippet = self._extract_snippet(llm_output, name)
            if record.state == SkillState.UNLOADED:
                violation = SkillViolation(
                    timestamp=self._now(),
                    violation_type=ViolationType.LLM_REACTIVATION_ATTEMPT,
                    skill_name=name,
                    phase=self._current_phase,
                    context=snippet,
                )
                self._logger.warning(
                    f"VIOLATION: LLM referenced UNLOADED skill '{name}'"
                )
            elif record.state == SkillState.PURGED:
                violation = SkillViolation(
                    timestamp=self._now(),
                    violation_type=ViolationType.RESURRECTION_ATTEMPT,
                    skill_name=name,
                    phase=self._current_phase,
                    context=snippet,
                )
                self._logger.warning(
                    f"VIOLATION: LLM referenced PURGED skill '{name}'"
                )
            else:
                # REGISTERED or LOADED — not yet active, still a violation
                violation = SkillViolation(
                    timestamp=self._now(),
                    violation_type=ViolationType.LLM_REACTIVATION_ATTEMPT,
                    skill_name=name,
                    phase=self._current_phase,
                    context=snippet,
                )
                self._logger.warning(
                    f"VIOLATION: LLM referenced non-ACTIVE skill '{name}' (state={record.state.name})"
                )

            self._violations.append(violation)
            violations.append(violation)

        # Check for hallucinated skills (names not in registry at all)
        known_names = set(self._skills.keys())
        for word in words:
            if "skill" in word.lower() and word not in known_names:
                # Heuristic: if word contains "skill" but isn't known, flag as hallucinated
                if len(word) > 5:
                    violation = SkillViolation(
                        timestamp=self._now(),
                        violation_type=ViolationType.HALLUCINATED_SKILL,
                        skill_name=word,
                        phase=self._current_phase,
                        context=self._extract_snippet(llm_output, word),
                    )
                    self._violations.append(violation)
                    violations.append(violation)
                    self._logger.warning(f"VIOLATION: Hallucinated skill reference '{word}'")

        return violations

    def _extract_snippet(self, text: str, word: str, window: int = 40) -> str:
        """Extract a snippet of text around the first occurrence of word."""
        match = re.search(rf".{window}{re.escape(word)}.{window}", text, re.IGNORECASE)
        if match:
            return match.group(0)
        return ""

    def get_violations(self) -> List[SkillViolation]:
        """Return all recorded violations."""
        return self._violations.copy()

    # -----------------------------------------------------------------------
    # Tool Execution Gateway Interface
    # -----------------------------------------------------------------------

    def assert_tool_allowed(
        self,
        skill_name: str,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate a tool call against the skill's manifest.
        Called by tool-execution-gateway before executing any tool.
        """
        args = args or {}
        record = self._skills.get(skill_name)
        if record is None:
            return ValidationResult(
                allowed=False,
                reason=f"Skill '{skill_name}' not found in registry",
            )

        if record.state != SkillState.ACTIVE:
            return ValidationResult(
                allowed=False,
                reason=f"Skill '{skill_name}' is not ACTIVE (state={record.state.name})",
            )

        if tool_name not in record.manifest.tools:
            return ValidationResult(
                allowed=False,
                reason=f"Tool '{tool_name}' not declared in manifest for '{skill_name}'",
            )

        # Parameter constraint check (basic)
        constraints = record.manifest.parameter_constraints.get(tool_name, {})
        for param, expected in constraints.items():
            if param not in args:
                return ValidationResult(
                    allowed=False,
                    reason=f"Missing required parameter '{param}' for tool '{tool_name}'",
                )

        return ValidationResult(allowed=True, reason="tool call validated")

    # -----------------------------------------------------------------------
    # Sandbox Executor Interface
    # -----------------------------------------------------------------------

    def get_sandbox_profile(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        Return sandbox configuration derived from skill's required_capabilities.
        Called by sandbox-executor to configure sandbox boundaries.
        """
        record = self._skills.get(skill_name)
        if record is None:
            return None
        if not record.manifest.required_capabilities:
            return {}
        if self.sandbox_executor:
            return self.sandbox_executor.configure_from_capabilities(
                record.manifest.required_capabilities
            )
        return record.manifest.required_capabilities

    # -----------------------------------------------------------------------
    # Audit / Logging
    # -----------------------------------------------------------------------

    def _persist_log(self, transition: LifecycleTransition) -> None:
        """Append transition to on-disk audit log."""
        if self.log_file is None:
            return
        line = LOG_FORMAT.format(
            timestamp=transition.timestamp,
            phase=transition.phase,
            skill=transition.skill_name,
            old_state=transition.old_state.name,
            new_state=transition.new_state.name,
            reason=transition.reason.value,
            policy=transition.policy_result,
            sha256=transition.sha256_hash,
        )
        # Append to file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get_audit_log(self) -> List[str]:
        """Read the full audit log from disk."""
        if self.log_file is None or not self.log_file.exists():
            return []
        with open(self.log_file, "r", encoding="utf-8") as f:
            return f.read().splitlines()

    def get_transition_history(self, skill_name: str) -> List[LifecycleTransition]:
        """Return the transition history for a specific skill."""
        record = self._skills.get(skill_name)
        if record is None:
            return []
        return record.transition_history.copy()

    # -----------------------------------------------------------------------
    # Session End
    # -----------------------------------------------------------------------

    def end_session(self) -> None:
        """
        Clean up at session end: unload all active, purge all unloaded.
        """
        self._logger.info("=== Session end: purging all skills ===")
        for record in list(self._skills.values()):
            if record.state == SkillState.ACTIVE:
                self._transition(
                    record,
                    SkillState.UNLOADED,
                    TransitionReason.SESSION_END,
                    policy="n/a",
                    sha256=record.current_sha256,
                    justification="session termination",
                )
            if record.state == SkillState.UNLOADED:
                self._transition(
                    record,
                    SkillState.PURGED,
                    TransitionReason.SESSION_END,
                    policy="n/a",
                    sha256=record.current_sha256,
                    justification="session termination",
                )

    # -----------------------------------------------------------------------
    # Debug / Introspection
    # -----------------------------------------------------------------------

    def get_all_skills(self) -> Dict[str, SkillRecord]:
        """Return a copy of the internal skills map (for debugging)."""
        return {name: record for name, record in self._skills.items()}

    def get_skill_state(self, skill_name: str) -> Optional[SkillState]:
        """Return the current state of a skill."""
        record = self._skills.get(skill_name)
        return record.state if record else None

    def __repr__(self) -> str:
        counts = {state: 0 for state in SkillState}
        for r in self._skills.values():
            counts[r.state] += 1
        return (
            f"<SkillRegistry skills={len(self._skills)} "
            f"registered={counts[SkillState.REGISTERED]} "
            f"loaded={counts[SkillState.LOADED]} "
            f"active={counts[SkillState.ACTIVE]} "
            f"unloaded={counts[SkillState.UNLOADED]} "
            f"purged={counts[SkillState.PURGED]}>"
        )
