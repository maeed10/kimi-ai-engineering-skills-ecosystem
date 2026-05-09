#!/usr/bin/env python3
"""
error-policy.py — Universal Error Recovery and Circuit Breaker System

Kimi AI Engineering Skills Ecosystem v4.0
Purpose: Centralized error handling for ALL skill scripts. No ad-hoc try/except.

Exports:
    ScriptResult      — Universal execution result dataclass
    ErrorPolicy       — Recovery state enum
    CircuitBreaker    — Per-skill failure rate tracker
    FallbackRegistry  — Degraded mode strategy registry
    ErrorPolicyEngine — Main orchestrator with .run()
    HITLTicket        — Human escalation payload builder

Usage:
    from error_policy import ScriptResult, ErrorPolicyEngine

    engine = ErrorPolicyEngine()
    result = engine.run(
        lambda: my_skill_function(),
        skill_id="security-auditor",
        operation="analyze"
    )
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import logging
import os
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logger = logging.getLogger("kimi.error_policy")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


def _audit_log(event_type: str, payload: Dict[str, Any]) -> None:
    """Append structured audit record to JSONL log."""
    log_dir = Path(os.environ.get("KIMI_LOG_DIR", "~/.kimi/logs")).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "error-policy-audit.jsonl"

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        **payload,
    }
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError as exc:
        logger.warning("Failed to write audit log: %s", exc)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

DEFAULTS = {
    "retry_max": int(os.environ.get("KIMI_EP_RETRY_MAX", "3")),
    "retry_backoff_base": float(os.environ.get("KIMI_EP_BACKOFF_BASE", "1.0")),
    "circuit_failure_threshold": int(os.environ.get("KIMI_EP_CB_THRESHOLD", "5")),
    "circuit_time_window": int(os.environ.get("KIMI_EP_CB_WINDOW", "600")),
    "circuit_cooldown": int(os.environ.get("KIMI_EP_CB_COOLDOWN", "60")),
    "hitl_timeout": int(os.environ.get("KIMI_EP_HITL_TIMEOUT", "1800")),
    "destructive_retry_max": int(os.environ.get("KIMI_EP_DESTRUCTIVE_RETRY", "1")),
}

CRITICAL_GATES: Tuple[str, ...] = (
    "security-auditor",
    "code-tester",
    "gateway",
    "phase-controller",
    "policy-engine",
)

DESTRUCTIVE_OPS: Tuple[str, ...] = ("write", "delete", "apply")


def _load_config() -> Dict[str, Any]:
    """Load user config overrides from JSON file."""
    config_path = Path("~/.kimi/skills/error-policy/config.json").expanduser()
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Invalid config file at %s", config_path)
    return {}


_CONFIG = {**DEFAULTS, **_load_config()}


# ---------------------------------------------------------------------------
# ScriptResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScriptResult:
    """Universal execution result returned by every skill script."""

    exit_code: int = 0
    findings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    fallback_recommendation: Optional[str] = None
    escalate_to_human: bool = False
    execution_time: float = 0.0
    skill_id: str = "unknown"
    operation: str = "read"
    degraded: bool = False
    circuit_open: bool = False

    # Internal bookkeeping (not part of the public contract)
    _retry_count: int = 0
    _fallback_executed: Optional[str] = field(default=None, repr=False)

    def is_success(self) -> bool:
        return self.exit_code == 0 and not self.errors

    def is_policy_violation(self) -> bool:
        return self.exit_code == 3

    @staticmethod
    def from_exception(
        exc: BaseException,
        skill_id: str,
        operation: str,
        input_params: Optional[Dict[str, Any]] = None,
    ) -> ScriptResult:
        """Build a ScriptResult from an arbitrary exception."""
        env_snapshot = {
            "cwd": str(Path.cwd()),
            "relevant_env": _relevant_env(),
        }
        error_record = {
            "message": str(exc),
            "exception_type": type(exc).__name__,
            "stack_trace": traceback.format_exc(),
            "input_hash": _hash_params(input_params or {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "env_snapshot": env_snapshot,
        }
        return ScriptResult(
            exit_code=2,
            errors=[error_record],
            skill_id=skill_id,
            operation=operation,
        )

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def with_degraded(self, flag: bool = True) -> ScriptResult:
        """Return a copy with degraded flag set."""
        return dataclasses.replace(self, degraded=flag)


def _relevant_env() -> Dict[str, str]:
    """Return a scrubbed snapshot of environment variables useful for debugging."""
    keys = [
        "KIMI_PHASE",
        "KIMI_PROJECT",
        "KIMI_LOG_DIR",
        "KIMI_EP_RETRY_MAX",
        "KIMI_EP_CB_THRESHOLD",
        "PATH",
        "PYTHONPATH",
        "HOME",
    ]
    return {k: os.environ.get(k, "<unset>") for k in keys}


def _hash_params(params: Dict[str, Any]) -> str:
    """Stable SHA256 hash of input parameters for correlation."""
    payload = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# ErrorPolicy Enum
# ---------------------------------------------------------------------------

class ErrorPolicy(enum.Enum):
    """Four-state recovery machine."""

    RETRY = "retry"
    FALLBACK = "fallback"
    ESCALATE = "escalate"
    HALT = "halt"


# ---------------------------------------------------------------------------
# HITL Ticket
# ---------------------------------------------------------------------------

@dataclass
class HITLTicket:
    """Human-in-the-loop escalation payload."""

    ticket_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    skill_id: str = "unknown"
    operation: str = "read"
    phase_blocked: Optional[str] = None
    error_policy_state: ErrorPolicy = ErrorPolicy.ESCALATE
    script_result: ScriptResult = field(default_factory=ScriptResult)
    circuit_state: str = "CLOSED"
    fallback_attempted: bool = False
    fallback_results: Optional[ScriptResult] = None
    retry_log: List[Dict[str, Any]] = field(default_factory=list)
    environment: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved: bool = False
    resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "skill_id": self.skill_id,
            "operation": self.operation,
            "phase_blocked": self.phase_blocked,
            "error_policy_state": self.error_policy_state.value,
            "script_result": self.script_result.to_dict(),
            "circuit_state": self.circuit_state,
            "fallback_attempted": self.fallback_attempted,
            "fallback_results": (
                self.fallback_results.to_dict() if self.fallback_results else None
            ),
            "retry_log": self.retry_log,
            "environment": self.environment,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }

    def submit(self) -> None:
        """Persist ticket and notify integration points."""
        _audit_log("escalate", self.to_dict())
        logger.critical(
            "HITL ticket created: %s for skill=%s operation=%s",
            self.ticket_id,
            self.skill_id,
            self.operation,
        )
        # Integration hook: drift-monitor, phase-controller
        _emit_integration_event("hitl_created", self.to_dict())


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-skill circuit breaker with rolling window and half-open probing."""

    def __init__(
        self,
        skill_id: str,
        failure_threshold: int = _CONFIG["circuit_failure_threshold"],
        time_window: int = _CONFIG["circuit_time_window"],
        cooldown: int = _CONFIG["circuit_cooldown"],
    ):
        self.skill_id = skill_id
        self.failure_threshold = failure_threshold
        self.time_window = time_window
        self.cooldown = cooldown

        self._state = CircuitState.CLOSED
        self._failures: deque[float] = deque()
        self._last_opened: Optional[float] = None
        self._half_open_calls: int = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            now = time.monotonic()
            if self._last_opened and (now - self._last_opened) >= self.cooldown:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(
                    "Circuit %s moved OPEN -> HALF_OPEN", self.skill_id
                )
                _audit_log(
                    "circuit_state_change",
                    {
                        "skill_id": self.skill_id,
                        "from_state": "OPEN",
                        "to_state": "HALF_OPEN",
                    },
                )
                _emit_integration_event(
                    "circuit_state_change",
                    {
                        "skill_id": self.skill_id,
                        "from": "OPEN",
                        "to": "HALF_OPEN",
                    },
                )
        return self._state

    def record_success(self) -> None:
        """Record a successful call. If HALF_OPEN, close the circuit."""
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failures.clear()
            self._last_opened = None
            logger.info("Circuit %s closed after verified success", self.skill_id)
            _audit_log(
                "circuit_state_change",
                {
                    "skill_id": self.skill_id,
                    "from_state": "HALF_OPEN",
                    "to_state": "CLOSED",
                    "reason": "verified_success",
                },
            )
            _emit_integration_event(
                "circuit_state_change",
                {
                    "skill_id": self.skill_id,
                    "from": "HALF_OPEN",
                    "to": "CLOSED",
                },
            )

    def record_failure(self) -> None:
        """Record a failure and open circuit if threshold exceeded."""
        now = time.monotonic()
        self._failures.append(now)
        self._trim_window(now)

        if self._state == CircuitState.HALF_OPEN:
            # Reopen immediately on failure in half-open
            self._open_circuit(now)
            return

        if len(self._failures) >= self.failure_threshold:
            self._open_circuit(now)

    def _trim_window(self, now: float) -> None:
        cutoff = now - self.time_window
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def _open_circuit(self, now: float) -> None:
        if self._state != CircuitState.OPEN:
            previous = self._state.value
            self._state = CircuitState.OPEN
            self._last_opened = now
            logger.error(
                "Circuit OPEN for %s after %d failures in %ds",
                self.skill_id,
                len(self._failures),
                self.time_window,
            )
            _audit_log(
                "circuit_state_change",
                {
                    "skill_id": self.skill_id,
                    "from_state": previous.upper(),
                    "to_state": "OPEN",
                    "failure_count": len(self._failures),
                },
            )
            _emit_integration_event(
                "circuit_state_change",
                {
                    "skill_id": self.skill_id,
                    "from": previous.upper(),
                    "to": "OPEN",
                    "severity": "critical"
                    if self.skill_id in CRITICAL_GATES
                    else "warning",
                },
            )

    def can_execute(self) -> bool:
        """Return True if the circuit allows execution."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            return False
        if state == CircuitState.HALF_OPEN:
            # Allow only one test call
            if self._half_open_calls < 1:
                self._half_open_calls += 1
                return True
            return False
        return False

    def force_close(self, reason: str = "manual") -> None:
        """Human operator override to close circuit. Logged as audit event."""
        previous = self._state.value
        self._state = CircuitState.CLOSED
        self._failures.clear()
        self._last_opened = None
        logger.warning(
            "Circuit %s force-closed by operator. Reason: %s", self.skill_id, reason
        )
        _audit_log(
            "circuit_state_change",
            {
                "skill_id": self.skill_id,
                "from_state": previous.upper(),
                "to_state": "CLOSED",
                "reason": reason,
                "operator": "human",
            },
        )


# ---------------------------------------------------------------------------
# Fallback Registry
# ---------------------------------------------------------------------------

class FallbackCallable(Protocol):
    def __call__(self, original_params: Dict[str, Any]) -> ScriptResult:
        ...


class FallbackRegistry:
    """Registry of degraded-mode strategies per skill."""

    _registry: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def register(
        cls,
        skill_id: str,
        strategy_id: str,
        fn: FallbackCallable,
        requires_policy_approval: bool = False,
        description: str = "",
    ) -> None:
        """Register a fallback strategy for a skill."""
        if skill_id not in cls._registry:
            cls._registry[skill_id] = []
        cls._registry[skill_id].append(
            {
                "strategy_id": strategy_id,
                "fn": fn,
                "requires_policy_approval": requires_policy_approval,
                "description": description,
            }
        )
        logger.info(
            "Registered fallback %s for skill %s", strategy_id, skill_id
        )

    @classmethod
    def get_fallback(
        cls,
        skill_id: str,
        strategy_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a fallback strategy."""
        strategies = cls._registry.get(skill_id, [])
        if strategy_id:
            for s in strategies:
                if s["strategy_id"] == strategy_id:
                    return s
            return None
        # Return first available strategy
        return strategies[0] if strategies else None

    @classmethod
    def list_strategies(cls, skill_id: str) -> List[str]:
        return [s["strategy_id"] for s in cls._registry.get(skill_id, [])]


# ---------------------------------------------------------------------------
# Integration Event Emitter
# ---------------------------------------------------------------------------

def _emit_integration_event(event_name: str, payload: Dict[str, Any]) -> None:
    """Fire-and-forget event to drift-monitor and other subscribers."""
    # In production, this would publish to a message bus or webhook.
    # For the skill template, we log and audit only.
    logger.debug("Integration event: %s | payload keys: %s", event_name, list(payload.keys()))


# ---------------------------------------------------------------------------
# ErrorPolicyEngine
# ---------------------------------------------------------------------------

class ErrorPolicyEngine:
    """Central orchestrator for error recovery."""

    def __init__(self) -> None:
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.retry_max = _CONFIG["retry_max"]
        self.retry_backoff_base = _CONFIG["retry_backoff_base"]
        self.destructive_retry_max = _CONFIG["destructive_retry_max"]
        self.hitl_timeout = _CONFIG["hitl_timeout"]

    def _get_cb(self, skill_id: str) -> CircuitBreaker:
        if skill_id not in self.circuit_breakers:
            self.circuit_breakers[skill_id] = CircuitBreaker(skill_id)
        return self.circuit_breakers[skill_id]

    def run(
        self,
        script_call: Callable[[], ScriptResult],
        skill_id: str,
        operation: str = "read",
        input_params: Optional[Dict[str, Any]] = None,
        fallback_strategy_id: Optional[str] = None,
    ) -> ScriptResult:
        """
        Execute a script under the universal error recovery protocol.

        Returns a ScriptResult regardless of internal failures.
        """
        start_time = time.monotonic()
        cb = self._get_cb(skill_id)
        retry_log: List[Dict[str, Any]] = []

        # 1. Circuit breaker guard
        if not cb.can_execute():
            result = ScriptResult(
                exit_code=2,
                errors=[
                    {
                        "message": f"Circuit breaker OPEN for {skill_id}",
                        "exception_type": "CircuitBreakerOpen",
                        "input_hash": _hash_params(input_params or {}),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "env_snapshot": _relevant_env(),
                    }
                ],
                skill_id=skill_id,
                operation=operation,
                circuit_open=True,
                execution_time=time.monotonic() - start_time,
            )
            _audit_log("halt", {"reason": "circuit_open", **result.to_dict()})
            return result

        # 2. Execute with retry loop
        is_destructive = operation in DESTRUCTIVE_OPS
        max_retries = (
            self.destructive_retry_max if is_destructive else self.retry_max
        )

        last_result: Optional[ScriptResult] = None

        for attempt in range(max_retries + 1):
            attempt_start = time.monotonic()
            try:
                raw_result = script_call()
            except Exception as exc:
                raw_result = ScriptResult.from_exception(
                    exc, skill_id=skill_id, operation=operation, input_params=input_params
                )

            elapsed = time.monotonic() - attempt_start
            # Ensure execution_time is set if caller forgot
            if raw_result.execution_time == 0.0:
                raw_result = dataclasses.replace(raw_result, execution_time=elapsed)

            if raw_result.is_success():
                cb.record_success()
                _audit_log(
                    "success",
                    {
                        "skill_id": skill_id,
                        "operation": operation,
                        "attempt": attempt,
                        "execution_time": elapsed,
                    },
                )
                return dataclasses.replace(
                    raw_result,
                    skill_id=skill_id,
                    operation=operation,
                    _retry_count=attempt,
                )

            # Failure on this attempt
            last_result = dataclasses.replace(raw_result, _retry_count=attempt)
            retry_log.append(
                {
                    "attempt": attempt + 1,
                    "wait": (
                        self.retry_backoff_base * (2 ** attempt)
                        if attempt < max_retries
                        else 0
                    ),
                    "outcome": raw_result.errors[0].get("exception_type", "failure")
                    if raw_result.errors
                    else "failure",
                }
            )

            # Policy violation → immediate HALT
            if raw_result.is_policy_violation():
                return self._halt(
                    raw_result,
                    skill_id,
                    operation,
                    reason="policy_violation",
                    start_time=start_time,
                )

            # If script itself demands escalation, skip further retries
            if raw_result.escalate_to_human:
                break

            # Retry if allowed and not last attempt
            if attempt < max_retries:
                backoff = self.retry_backoff_base * (2 ** attempt)
                logger.warning(
                    "Retrying skill=%s operation=%s attempt=%d/%d after %.1fs",
                    skill_id,
                    operation,
                    attempt + 1,
                    max_retries,
                    backoff,
                )
                _audit_log(
                    "retry",
                    {
                        "skill_id": skill_id,
                        "operation": operation,
                        "attempt": attempt + 1,
                        "backoff_seconds": backoff,
                    },
                )
                time.sleep(backoff)
            else:
                logger.error(
                    "Retries exhausted for skill=%s operation=%s", skill_id, operation
                )

        # 3. Retry exhausted — evaluate fallback
        if last_result is None:
            # Should never happen, but guard anyway
            last_result = ScriptResult(
                exit_code=2,
                errors=[{"message": "Unexpected empty result after retry loop"}],
                skill_id=skill_id,
                operation=operation,
            )

        cb.record_failure()

        fallback_strategy = FallbackRegistry.get_fallback(
            skill_id, fallback_strategy_id
        )

        if fallback_strategy:
            # Security check: less-secure fallbacks need policy approval
            if fallback_strategy["requires_policy_approval"]:
                # In a full integration, ask policy-engine. Here we escalate.
                logger.error(
                    "Fallback %s for %s requires policy approval — escalating",
                    fallback_strategy["strategy_id"],
                    skill_id,
                )
                return self._escalate(
                    last_result,
                    skill_id,
                    operation,
                    retry_log=retry_log,
                    fallback_attempted=False,
                    start_time=start_time,
                )

            logger.warning(
                "Executing fallback %s for skill=%s",
                fallback_strategy["strategy_id"],
                skill_id,
            )
            fb_result = self._run_fallback(
                fallback_strategy, input_params or {}, skill_id, operation
            )

            if fb_result.is_success():
                _audit_log(
                    "fallback",
                    {
                        "skill_id": skill_id,
                        "operation": operation,
                        "fallback_strategy": fallback_strategy["strategy_id"],
                        "outcome": "success",
                    },
                )
                return dataclasses.replace(
                    fb_result,
                    degraded=True,
                    _fallback_executed=fallback_strategy["strategy_id"],
                    execution_time=time.monotonic() - start_time,
                )

            # Fallback failed
            logger.error(
                "Fallback %s failed for skill=%s", fallback_strategy["strategy_id"], skill_id
            )
            if skill_id in CRITICAL_GATES:
                return self._escalate(
                    last_result,
                    skill_id,
                    operation,
                    retry_log=retry_log,
                    fallback_attempted=True,
                    fallback_results=fb_result,
                    start_time=start_time,
                )

            # Non-critical: return degraded failure but allow pipeline to continue
            return dataclasses.replace(
                fb_result,
                exit_code=1,
                degraded=True,
                _fallback_executed=fallback_strategy["strategy_id"],
                execution_time=time.monotonic() - start_time,
            )

        # 4. No fallback available
        if skill_id in CRITICAL_GATES:
            return self._escalate(
                last_result,
                skill_id,
                operation,
                retry_log=retry_log,
                fallback_attempted=False,
                start_time=start_time,
            )

        # Non-critical, no fallback: warn and continue degraded
        logger.warning(
            "No fallback for non-critical skill=%s. Continuing degraded.", skill_id
        )
        _audit_log(
            "degraded_continue",
            {
                "skill_id": skill_id,
                "operation": operation,
                "reason": "no_fallback",
            },
        )
        return dataclasses.replace(
            last_result,
            exit_code=1,
            degraded=True,
            execution_time=time.monotonic() - start_time,
        )

    def _run_fallback(
        self,
        strategy: Dict[str, Any],
        original_params: Dict[str, Any],
        skill_id: str,
        operation: str,
    ) -> ScriptResult:
        """Execute a fallback strategy with its own error wrapping."""
        try:
            result = strategy["fn"](original_params)
            return dataclasses.replace(result, skill_id=skill_id, operation=operation)
        except Exception as exc:
            return ScriptResult.from_exception(
                exc,
                skill_id=skill_id,
                operation=operation,
                input_params=original_params,
            )

    def _escalate(
        self,
        original_result: ScriptResult,
        skill_id: str,
        operation: str,
        retry_log: List[Dict[str, Any]],
        fallback_attempted: bool = False,
        fallback_results: Optional[ScriptResult] = None,
        start_time: float = 0.0,
    ) -> ScriptResult:
        """Create HITL ticket and return escalation result."""
        ticket = HITLTicket(
            skill_id=skill_id,
            operation=operation,
            error_policy_state=ErrorPolicy.ESCALATE,
            script_result=original_result,
            circuit_state=self._get_cb(skill_id).state.value.upper(),
            fallback_attempted=fallback_attempted,
            fallback_results=fallback_results,
            retry_log=retry_log,
            environment=_relevant_env(),
        )
        ticket.submit()

        _audit_log(
            "escalate",
            {
                "ticket_id": ticket.ticket_id,
                "skill_id": skill_id,
                "operation": operation,
            },
        )

        return dataclasses.replace(
            original_result,
            exit_code=2,
            escalate_to_human=True,
            execution_time=time.monotonic() - start_time,
        )

    def _halt(
        self,
        original_result: ScriptResult,
        skill_id: str,
        operation: str,
        reason: str,
        start_time: float = 0.0,
    ) -> ScriptResult:
        """Halt the pipeline for policy violations or unresolvable failures."""
        _audit_log(
            "halt",
            {
                "skill_id": skill_id,
                "operation": operation,
                "reason": reason,
                "policy_violation": original_result.is_policy_violation(),
            },
        )
        logger.critical(
            "HALT triggered for skill=%s operation=%s reason=%s",
            skill_id,
            operation,
            reason,
        )
        _emit_integration_event(
            "pipeline_halt",
            {
                "skill_id": skill_id,
                "operation": operation,
                "reason": reason,
                "result": original_result.to_dict(),
            },
        )
        return dataclasses.replace(
            original_result,
            exit_code=3,
            execution_time=time.monotonic() - start_time,
        )

    def resolve_hitl(
        self,
        ticket_id: str,
        resolution: str,
        close_circuit: bool = False,
    ) -> None:
        """
        Human operator resolves a HITL ticket.

        Args:
            ticket_id: The HITL ticket UUID.
            resolution: Description of resolution action.
            close_circuit: If True, also force-close the associated circuit.
        """
        logger.info(
            "HITL ticket %s resolved: %s", ticket_id, resolution
        )
        _audit_log(
            "hitl_resolved",
            {"ticket_id": ticket_id, "resolution": resolution},
        )
        # In a full system, this would update a persistent ticket store.
        if close_circuit:
            # We would need skill_id mapping from ticket store; simplified here
            pass


# ---------------------------------------------------------------------------
# Convenience exports for skill scripts
# ---------------------------------------------------------------------------

def run_with_policy(
    script_call: Callable[[], ScriptResult],
    skill_id: str,
    operation: str = "read",
    **kwargs: Any,
) -> ScriptResult:
    """One-shot convenience wrapper using a global engine instance."""
    engine = ErrorPolicyEngine()
    return engine.run(script_call, skill_id=skill_id, operation=operation, **kwargs)


# ---------------------------------------------------------------------------
# Self-test / sanity check
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Basic sanity checks for the error policy module."""
    logger.info("Running error-policy self-test...")

    # 1. ScriptResult construction
    sr = ScriptResult(findings=[{"ok": True}])
    assert sr.is_success()

    # 2. ScriptResult from exception
    try:
        raise ValueError("boom")
    except Exception as e:
        sr_err = ScriptResult.from_exception(e, "test-skill", "read")
    assert not sr_err.is_success()
    assert sr_err.errors[0]["exception_type"] == "ValueError"

    # 3. Circuit breaker
    cb = CircuitBreaker("test-skill", failure_threshold=2, time_window=60)
    assert cb.can_execute()
    cb.record_failure()
    assert cb.can_execute()
    cb.record_failure()
    assert not cb.can_execute()
    assert cb.state == CircuitState.OPEN

    # 4. Retry flow — non-destructive failure should exhaust retries
    call_count = 0

    def fail_twice() -> ScriptResult:
        nonlocal call_count
        call_count += 1
        return ScriptResult.from_exception(RuntimeError("transient"), "test-skill", "read")

    engine = ErrorPolicyEngine()
    # Override config for test speed
    engine.retry_max = 2
    engine.retry_backoff_base = 0.01

    result = engine.run(fail_twice, skill_id="test-skill", operation="read")
    assert call_count == 3  # initial + 2 retries
    assert result._retry_count == 2

    # 5. Fallback execution
    def good_fallback(_params: Dict[str, Any]) -> ScriptResult:
        return ScriptResult(findings=[{"mode": "fallback"}])

    FallbackRegistry.register(
        "test-skill", "regex-scan", good_fallback, description="Test fallback"
    )

    call_count = 0

    def always_fail() -> ScriptResult:
        nonlocal call_count
        call_count += 1
        return ScriptResult.from_exception(RuntimeError("persistent"), "test-skill", "read")

    result = engine.run(
        always_fail,
        skill_id="test-skill",
        operation="read",
        fallback_strategy_id="regex-scan",
    )
    assert result.degraded
    assert result.is_success()

    logger.info("error-policy self-test passed.")


if __name__ == "__main__":
    _self_test()
