#!/usr/bin/env python3
"""
drift-monitor.py — Behavioral Anomaly Detection & Safe Shutdown

Reference implementation for the `drift-monitor` skill in the
Kimi AI Engineering Skills Ecosystem v4.0.

Defines concrete anomaly types, establishes statistical baselines during
a 10-session burn-in period, enforces 3-tier threshold alerting
(WARNING / CRITICAL / EMERGENCY), and triggers automatic safe shutdown
with full forensics preservation on EMERGENCY drift.

Safety rules enforced:
  R1. NEVER ignore EMERGENCY drift — always halt or escalate.
  R2. NEVER auto-close EMERGENCY without human verification.
  R3. ALWAYS complete 10-session burn-in before active detection.
  R4. NEVER let thresholds be modified by the LLM at runtime.
  R5. ALWAYS preserve full context before shutdown.
  R6. NEVER allow drift detection to be disabled without human approval.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Callable

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("drift-monitor")


# ---------------------------------------------------------------------------
# Constants — Hard-coded; human approval required to change
# ---------------------------------------------------------------------------

BURN_IN_SESSIONS: int = 10
WARNING_Z: float = 2.0
CRITICAL_Z: float = 3.0
EMERGENCY_Z: float = 4.0
SLOW_DRIP_WINDOW: int = 5
SLOW_DRIP_CUMULATIVE_THRESHOLD: float = 10.0


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DriftTier(Enum):
    NORMAL = auto()
    WARNING = auto()
    CRITICAL = auto()
    EMERGENCY = auto()


class Action(Enum):
    REPORT = auto()      # Log and flag in session report
    CHECKPOINT = auto()  # Require human checkpoint before proceeding
    HALT = auto()        # Halt pipeline, preserve forensics, notify


class MonitorState(Enum):
    BURN_IN = auto()
    ACTIVE = auto()
    WARNING = auto()
    CRITICAL = auto()
    EMERGENCY = auto()
    HALTED = auto()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TokenMetrics:
    total: int = 0
    per_skill: Dict[str, int] = field(default_factory=dict)
    per_tool_call: Dict[str, int] = field(default_factory=dict)


@dataclass
class ToolCallMetrics:
    count_by_type: Dict[str, int] = field(default_factory=dict)
    count_by_skill: Dict[str, int] = field(default_factory=dict)
    count_by_phase: Dict[str, int] = field(default_factory=dict)


@dataclass
class PhaseTransitionMetrics:
    total: int = 0
    valid: int = 0
    skip_events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def valid_ratio(self) -> float:
        return self.valid / self.total if self.total > 0 else 1.0


@dataclass
class SkillLifecycleMetrics:
    loads: int = 0
    unloads: int = 0
    activations: int = 0
    deactivations: int = 0
    unloaded_reactivations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class IPIMetrics:
    detection_count: int = 0
    severity_distribution: Dict[str, int] = field(default_factory=dict)
    evasion_signals: int = 0


@dataclass
class PolicyViolationMetrics:
    count: int = 0
    types: Dict[str, int] = field(default_factory=dict)


@dataclass
class SessionMetrics:
    session_id: str
    tokens: TokenMetrics = field(default_factory=TokenMetrics)
    tool_calls: ToolCallMetrics = field(default_factory=ToolCallMetrics)
    phase_transitions: PhaseTransitionMetrics = field(default_factory=PhaseTransitionMetrics)
    skill_lifecycle: SkillLifecycleMetrics = field(default_factory=SkillLifecycleMetrics)
    ipi: IPIMetrics = field(default_factory=IPIMetrics)
    policy_violations: PolicyViolationMetrics = field(default_factory=PolicyViolationMetrics)


@dataclass
class FlaggedMetric:
    metric_name: str
    value: float
    baseline_mean: float
    baseline_stdev: float
    z_score: float
    tier: DriftTier


@dataclass
class DriftEvent:
    event_type: str
    tier: DriftTier
    description: str
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftReport:
    session_id: str
    tier: DriftTier
    flagged_metrics: List[FlaggedMetric] = field(default_factory=list)
    slow_drip_triggered: bool = False
    action: Action = Action.REPORT
    forensics_url: Optional[str] = None
    events: List[DriftEvent] = field(default_factory=list)


@dataclass
class ForensicsPackage:
    timestamp: str
    session_id: str
    logs: List[str] = field(default_factory=list)
    memory_state: Dict[str, Any] = field(default_factory=dict)
    tool_call_history: List[Dict[str, Any]] = field(default_factory=list)
    metric_series: List[Dict[str, Any]] = field(default_factory=list)
    active_skills: List[str] = field(default_factory=list)
    current_phase: str = ""
    triggering_event: Optional[DriftEvent] = None


# ---------------------------------------------------------------------------
# Clients / integration stubs (to be wired by ecosystem bootstrap)
# ---------------------------------------------------------------------------

class ErrorPolicyClient:
    """Stub for error-policy integration."""

    def halt_pipeline(self, reason: str, forensics: Dict[str, Any]) -> bool:
        logger.critical("[ErrorPolicyClient.halt_pipeline] reason=%s", reason)
        # Real implementation delegates to error-policy skill
        return True


class PolicyEngineClient:
    """Stub for policy-engine integration."""

    def get_active_policies(self) -> List[str]:
        return []


class Notifier:
    """Stub for human notification channel."""

    def notify(self, tier: DriftTier, message: str, context: Dict[str, Any]) -> bool:
        logger.critical("[Notifier] tier=%s message=%s", tier.name, message)
        return True


# ---------------------------------------------------------------------------
# Statistical baseline
# ---------------------------------------------------------------------------

class Baseline:
    """Immutable statistical baseline computed from burn-in sessions."""

    def __init__(self, metrics_series: List[SessionMetrics]) -> None:
        self._mean: Dict[str, float] = {}
        self._stdev: Dict[str, float] = {}
        self._count: int = len(metrics_series)
        self._compute(metrics_series)

    def _compute(self, series: List[SessionMetrics]) -> None:
        # Flatten session metrics into scalar fields for baseline
        values: Dict[str, List[float]] = {}
        for m in series:
            flat = self._flatten(m)
            for k, v in flat.items():
                values.setdefault(k, []).append(float(v))

        for k, vals in values.items():
            n = len(vals)
            mean = sum(vals) / n if n > 0 else 0.0
            variance = sum((x - mean) ** 2 for x in vals) / n if n > 0 else 0.0
            stdev = math.sqrt(variance)
            self._mean[k] = mean
            self._stdev[k] = stdev

    @staticmethod
    def _flatten(m: SessionMetrics) -> Dict[str, float]:
        """Extract scalar metrics from a SessionMetrics object."""
        out: Dict[str, float] = {
            "tokens_total": float(m.tokens.total),
            "phase_transitions_total": float(m.phase_transitions.total),
            "phase_transitions_valid_ratio": float(m.phase_transitions.valid_ratio),
            "skill_loads": float(m.skill_lifecycle.loads),
            "skill_unloads": float(m.skill_lifecycle.unloads),
            "skill_activations": float(m.skill_lifecycle.activations),
            "skill_deactivations": float(m.skill_lifecycle.deactivations),
            "ipi_detection_count": float(m.ipi.detection_count),
            "ipi_evasion_signals": float(m.ipi.evasion_signals),
            "policy_violation_count": float(m.policy_violations.count),
        }
        # Per-skill / per-tool / per-phase / per-type counts
        for k, v in m.tokens.per_skill.items():
            out[f"tokens_per_skill_{k}"] = float(v)
        for k, v in m.tokens.per_tool_call.items():
            out[f"tokens_per_tool_call_{k}"] = float(v)
        for k, v in m.tool_calls.count_by_type.items():
            out[f"tool_calls_type_{k}"] = float(v)
        for k, v in m.tool_calls.count_by_skill.items():
            out[f"tool_calls_skill_{k}"] = float(v)
        for k, v in m.tool_calls.count_by_phase.items():
            out[f"tool_calls_phase_{k}"] = float(v)
        for k, v in m.ipi.severity_distribution.items():
            out[f"ipi_severity_{k}"] = float(v)
        for k, v in m.policy_violations.types.items():
            out[f"policy_violation_type_{k}"] = float(v)
        return out

    def z_score(self, metric_name: str, value: float) -> float:
        mean = self._mean.get(metric_name, 0.0)
        stdev = self._stdev.get(metric_name, 0.0)
        if stdev == 0:
            return abs(value - mean)
        return (value - mean) / stdev

    def mean(self, metric_name: str) -> float:
        return self._mean.get(metric_name, 0.0)

    def stdev(self, metric_name: str) -> float:
        return self._stdev.get(metric_name, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self._count,
            "mean": copy.deepcopy(self._mean),
            "stdev": copy.deepcopy(self._stdev),
        }


# ---------------------------------------------------------------------------
# DriftMonitor
# ---------------------------------------------------------------------------

class DriftMonitor:
    """
    Core drift detection engine.

    Integrates with phase-controller, skill-registry, error-policy,
    policy-engine, and ipi-defender to detect behavioral anomalies
    and enforce safe shutdown.
    """

    def __init__(
        self,
        error_policy_client: ErrorPolicyClient,
        policy_engine_client: PolicyEngineClient,
        notifier: Notifier,
        burn_in_sessions: int = BURN_IN_SESSIONS,
        warning_z: float = WARNING_Z,
        critical_z: float = CRITICAL_Z,
        emergency_z: float = EMERGENCY_Z,
        slow_drip_window: int = SLOW_DRIP_WINDOW,
        slow_drip_threshold: float = SLOW_DRIP_CUMULATIVE_THRESHOLD,
        forensics_output_dir: str = "./forensics",
    ) -> None:
        self._error_policy = error_policy_client
        self._policy_engine = policy_engine_client
        self._notifier = notifier

        # Thresholds — immutable after construction (R4)
        self._burn_in_sessions = burn_in_sessions
        self._warning_z = warning_z
        self._critical_z = critical_z
        self._emergency_z = emergency_z
        self._slow_drip_window = slow_drip_window
        self._slow_drip_threshold = slow_drip_threshold
        self._forensics_dir = forensics_output_dir

        # Runtime state
        self._state = MonitorState.BURN_IN
        self._session_metrics: List[SessionMetrics] = []
        self._baseline: Optional[Baseline] = None
        self._live_events: List[DriftEvent] = []
        self._halted = False

        # Memory snapshot hooks (to be wired by ecosystem)
        self._memory_snapshot_hook: Optional[Callable[[], Dict[str, Any]]] = None
        self._tool_call_history_hook: Optional[Callable[[], List[Dict[str, Any]]]] = None
        self._active_skills_hook: Optional[Callable[[], List[str]]] = None
        self._current_phase_hook: Optional[Callable[[], str]] = None

        logger.info(
            "DriftMonitor initialized: burn_in=%d warning_z=%.1f critical_z=%.1f emergency_z=%.1f",
            burn_in_sessions, warning_z, critical_z, emergency_z,
        )

    # ------------------------------------------------------------------
    # Hooks for ecosystem wiring
    # ------------------------------------------------------------------

    def set_memory_snapshot_hook(self, hook: Callable[[], Dict[str, Any]]) -> None:
        self._memory_snapshot_hook = hook

    def set_tool_call_history_hook(self, hook: Callable[[], List[Dict[str, Any]]]) -> None:
        self._tool_call_history_hook = hook

    def set_active_skills_hook(self, hook: Callable[[], List[str]]) -> None:
        self._active_skills_hook = hook

    def set_current_phase_hook(self, hook: Callable[[], str]) -> None:
        self._current_phase_hook = hook

    # ------------------------------------------------------------------
    # Burn-in & baseline
    # ------------------------------------------------------------------

    @property
    def burn_in_complete(self) -> bool:
        return len(self._session_metrics) >= self._burn_in_sessions

    def _ensure_baseline(self) -> None:
        if self._baseline is None and self.burn_in_complete:
            self._baseline = Baseline(self._session_metrics[: self._burn_in_sessions])
            self._state = MonitorState.ACTIVE
            logger.info("Baseline established from %d sessions", self._burn_in_sessions)

    # ------------------------------------------------------------------
    # Main per-session entry point
    # ------------------------------------------------------------------

    def record_session(self, metrics: SessionMetrics) -> DriftReport:
        """
        Record a completed session's metrics and evaluate drift.

        During burn-in, metrics are stored but no drift detection occurs (R3).
        After burn-in, z-scores are computed and thresholds evaluated.
        """
        self._session_metrics.append(metrics)
        self._ensure_baseline()

        if not self.burn_in_complete:
            logger.info("Session %s recorded (burn-in %d/%d)", metrics.session_id, len(self._session_metrics), self._burn_in_sessions)
            return DriftReport(session_id=metrics.session_id, tier=DriftTier.NORMAL, action=Action.REPORT)

        # Evaluate drift
        report = self._evaluate_metrics(metrics)
        report.session_id = metrics.session_id

        # Slow-drip check
        slow_drip = self._check_slow_drip()
        if slow_drip:
            report.slow_drip_triggered = True
            report.events.append(
                DriftEvent(
                    event_type="slow_drip",
                    tier=DriftTier.CRITICAL,
                    description=f"Cumulative deviation over {self._slow_drip_window} sessions exceeded threshold",
                )
            )
            # Escalate tier if not already at or above CRITICAL
            if report.tier.value < DriftTier.CRITICAL.value:
                report.tier = DriftTier.CRITICAL
                report.action = Action.CHECKPOINT

        # Merge live events (phase skip, skill reactivation, policy violations)
        if self._live_events:
            report.events.extend(self._live_events)
            # Any live EMERGENCY event forces EMERGENCY tier
            if any(e.tier == DriftTier.EMERGENCY for e in self._live_events):
                report.tier = DriftTier.EMERGENCY
                report.action = Action.HALT
            self._live_events.clear()

        # Policy violations always trigger EMERGENCY
        if metrics.policy_violations.count > 0:
            report.tier = DriftTier.EMERGENCY
            report.action = Action.HALT
            report.events.append(
                DriftEvent(
                    event_type="policy_violation",
                    tier=DriftTier.EMERGENCY,
                    description=f"{metrics.policy_violations.count} policy violation(s) detected",
                    context={"types": metrics.policy_violations.types},
                )
            )

        # Final state update and action
        self._apply_tier(report.tier)

        if report.tier == DriftTier.EMERGENCY:
            self._handle_emergency(report, metrics)
        elif report.tier == DriftTier.CRITICAL:
            self._handle_critical(report, metrics)
        elif report.tier == DriftTier.WARNING:
            self._handle_warning(report, metrics)
        else:
            logger.info("Session %s: NORMAL drift report", metrics.session_id)

        return report

    # ------------------------------------------------------------------
    # Metric evaluation
    # ------------------------------------------------------------------

    def _evaluate_metrics(self, metrics: SessionMetrics) -> DriftReport:
        assert self._baseline is not None
        flat = Baseline._flatten(metrics)
        flagged: List[FlaggedMetric] = []
        max_tier = DriftTier.NORMAL

        for metric_name, value in flat.items():
            z = self._baseline.z_score(metric_name, value)
            tier = self._tier_from_z(abs(z))
            if tier.value > DriftTier.NORMAL.value:
                flagged.append(
                    FlaggedMetric(
                        metric_name=metric_name,
                        value=value,
                        baseline_mean=self._baseline.mean(metric_name),
                        baseline_stdev=self._baseline.stdev(metric_name),
                        z_score=z,
                        tier=tier,
                    )
                )
                if tier.value > max_tier.value:
                    max_tier = tier

        action = {
            DriftTier.NORMAL: Action.REPORT,
            DriftTier.WARNING: Action.REPORT,
            DriftTier.CRITICAL: Action.CHECKPOINT,
            DriftTier.EMERGENCY: Action.HALT,
        }[max_tier]

        return DriftReport(
            session_id=metrics.session_id,
            tier=max_tier,
            flagged_metrics=flagged,
            action=action,
        )

    def _tier_from_z(self, z_abs: float) -> DriftTier:
        if z_abs >= self._emergency_z:
            return DriftTier.EMERGENCY
        if z_abs >= self._critical_z:
            return DriftTier.CRITICAL
        if z_abs >= self._warning_z:
            return DriftTier.WARNING
        return DriftTier.NORMAL

    # ------------------------------------------------------------------
    # Slow-drip detection
    # ------------------------------------------------------------------

    def _check_slow_drip(self) -> bool:
        if len(self._session_metrics) < self._slow_drip_window:
            return False
        assert self._baseline is not None
        window = self._session_metrics[-self._slow_drip_window :]
        cumulative_z = 0.0
        for m in window:
            flat = Baseline._flatten(m)
            for metric_name, value in flat.items():
                stdev = self._baseline.stdev(metric_name)
                if stdev > 0:
                    z = abs(self._baseline.z_score(metric_name, value))
                    cumulative_z += z
        return cumulative_z > self._slow_drip_threshold

    # ------------------------------------------------------------------
    # Tier application
    # ------------------------------------------------------------------

    def _apply_tier(self, tier: DriftTier) -> None:
        if tier == DriftTier.EMERGENCY:
            self._state = MonitorState.EMERGENCY
        elif tier == DriftTier.CRITICAL and self._state.value < MonitorState.CRITICAL.value:
            self._state = MonitorState.CRITICAL
        elif tier == DriftTier.WARNING and self._state.value < MonitorState.WARNING.value:
            self._state = MonitorState.WARNING
        elif tier == DriftTier.NORMAL and self._state == MonitorState.BURN_IN:
            self._state = MonitorState.ACTIVE

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _handle_warning(self, report: DriftReport, metrics: SessionMetrics) -> None:
        logger.warning(
            "Session %s: WARNING drift — %d metric(s) flagged",
            metrics.session_id,
            len(report.flagged_metrics),
        )
        for fm in report.flagged_metrics:
            logger.warning("  %s: value=%.1f mean=%.1f stdev=%.1f z=%.2f", fm.metric_name, fm.value, fm.baseline_mean, fm.baseline_stdev, fm.z_score)
        self._notifier.notify(DriftTier.WARNING, f"WARNING drift in session {metrics.session_id}", {"flagged_metrics": [asdict(fm) for fm in report.flagged_metrics]})

    def _handle_critical(self, report: DriftReport, metrics: SessionMetrics) -> None:
        logger.critical(
            "Session %s: CRITICAL drift — %d metric(s) flagged (slow_drip=%s)",
            metrics.session_id,
            len(report.flagged_metrics),
            report.slow_drip_triggered,
        )
        self._notifier.notify(
            DriftTier.CRITICAL,
            f"CRITICAL drift in session {metrics.session_id}. Checkpoint required before proceeding.",
            {
                "flagged_metrics": [asdict(fm) for fm in report.flagged_metrics],
                "slow_drip": report.slow_drip_triggered,
            },
        )

    def _handle_emergency(self, report: DriftReport, metrics: SessionMetrics) -> None:
        logger.critical("Session %s: EMERGENCY drift — initiating halt", metrics.session_id)
        forensics = self.preserve_forensics(report.events[0] if report.events else None)
        forensics.session_id = metrics.session_id
        forensics_path = self._write_forensics(forensics)
        report.forensics_url = forensics_path

        # Halt pipeline via error-policy (R1)
        self._halted = True
        self._state = MonitorState.HALTED
        self._error_policy.halt_pipeline(
            reason="EMERGENCY_DRIFT",
            forensics=asdict(forensics),
        )

        # Notify human with full context (R5)
        self._notifier.notify(
            DriftTier.EMERGENCY,
            f"EMERGENCY drift in session {metrics.session_id}. PIPELINE HALTED. Forensics: {forensics_path}",
            {
                "flagged_metrics": [asdict(fm) for fm in report.flagged_metrics],
                "events": [asdict(e) for e in report.events],
                "forensics_path": forensics_path,
            },
        )

    # ------------------------------------------------------------------
    # Live event evaluators (called during session execution)
    # ------------------------------------------------------------------

    def evaluate_phase_transition(self, event: Dict[str, Any]) -> Optional[DriftEvent]:
        """
        Called by phase-controller integration.

        Detects phase skipping: transition from phase N to N+k (k>1)
        without valid checkpoint/override.
        """
        from_phase = event.get("from", "")
        to_phase = event.get("to", "")
        valid = event.get("valid", True)
        skip_detected = event.get("skip_detected", False)

        if not valid or skip_detected:
            drift = DriftEvent(
                event_type="phase_skip",
                tier=DriftTier.EMERGENCY,
                description=f"Invalid phase transition from {from_phase} to {to_phase}",
                context=event,
            )
            self._live_events.append(drift)
            logger.critical("Phase skip detected: %s → %s", from_phase, to_phase)
            return drift
        return None

    def evaluate_skill_lifecycle(self, event: Dict[str, Any]) -> Optional[DriftEvent]:
        """
        Called by skill-registry integration.

        Detects UNLOADED skill reactivation.
        """
        skill_id = event.get("skill_id", "")
        event_type = event.get("event_type", "")
        current_state = event.get("current_state", "")

        if event_type == "ACTIVATE" and current_state == "UNLOADED":
            drift = DriftEvent(
                event_type="unloaded_reactivation",
                tier=DriftTier.EMERGENCY,
                description=f"Attempted activation of UNLOADED skill {skill_id}",
                context=event,
            )
            self._live_events.append(drift)
            logger.critical("UNLOADED skill reactivation: %s", skill_id)
            return drift
        return None

    def evaluate_policy_violation(self, event: Dict[str, Any]) -> DriftEvent:
        """
        Called by policy-engine integration.

        Every policy violation is an EMERGENCY drift event.
        """
        drift = DriftEvent(
            event_type="policy_violation",
            tier=DriftTier.EMERGENCY,
            description=f"Policy violation: {event.get('policy_id', 'unknown')}",
            context=event,
        )
        self._live_events.append(drift)
        logger.critical("Policy violation detected: %s", event.get("policy_id", "unknown"))
        return drift

    def evaluate_ipi_report(self, report: Dict[str, Any]) -> Optional[DriftEvent]:
        """
        Called by ipi-defender integration.

        Detects IPI detection rate changes or evasion signals.
        """
        count = report.get("detection_count", 0)
        evasion_signals = report.get("evasion_signals", 0)

        # Compare count to baseline if available
        if self._baseline is not None:
            z = self._baseline.z_score("ipi_detection_count", float(count))
            tier = self._tier_from_z(abs(z))
        else:
            # During burn-in, only evasion signals trigger WARNING
            tier = DriftTier.WARNING if evasion_signals > 0 else DriftTier.NORMAL

        if evasion_signals > 0:
            tier = max(tier, DriftTier.WARNING, key=lambda t: t.value)

        if tier.value > DriftTier.NORMAL.value:
            drift = DriftEvent(
                event_type="ipi_rate_change",
                tier=tier,
                description=f"IPI anomaly: count={count}, evasion_signals={evasion_signals}",
                context=report,
            )
            self._live_events.append(drift)
            logger.warning("IPI rate change detected: tier=%s", tier.name)
            return drift
        return None

    # ------------------------------------------------------------------
    # Forensics
    # ------------------------------------------------------------------

    def preserve_forensics(self, triggering_event: Optional[DriftEvent] = None) -> ForensicsPackage:
        """
        Capture full context for forensic analysis (R5).

        Calls memory/phase/skill hooks if wired; otherwise captures best-effort.
        """
        memory_state = {}
        if self._memory_snapshot_hook:
            try:
                memory_state = self._memory_snapshot_hook()
            except Exception as e:
                logger.error("Memory snapshot hook failed: %s", e)

        tool_call_history: List[Dict[str, Any]] = []
        if self._tool_call_history_hook:
            try:
                tool_call_history = self._tool_call_history_hook()
            except Exception as e:
                logger.error("Tool call history hook failed: %s", e)

        active_skills: List[str] = []
        if self._active_skills_hook:
            try:
                active_skills = self._active_skills_hook()
            except Exception as e:
                logger.error("Active skills hook failed: %s", e)

        current_phase = ""
        if self._current_phase_hook:
            try:
                current_phase = self._current_phase_hook()
            except Exception as e:
                logger.error("Current phase hook failed: %s", e)

        pkg = ForensicsPackage(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            session_id="",
            logs=["Forensics captured at halt"],
            memory_state=memory_state,
            tool_call_history=tool_call_history,
            metric_series=[asdict(m) for m in self._session_metrics],
            active_skills=active_skills,
            current_phase=current_phase,
            triggering_event=triggering_event,
        )
        return pkg

    def _write_forensics(self, pkg: ForensicsPackage) -> str:
        os.makedirs(self._forensics_dir, exist_ok=True)
        filename = f"forensics_{pkg.timestamp.replace(':', '-')}_{uuid.uuid4().hex[:8]}.json"
        path = os.path.join(self._forensics_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(pkg), f, indent=2, default=str)
        logger.info("Forensics written to %s", path)
        return path

    # ------------------------------------------------------------------
    # Human-only emergency clearance (R2)
    # ------------------------------------------------------------------

    def clear_emergency(self, human_auth_token: str) -> bool:
        """
        Clear HALTED state and allow pipeline resumption.

        This operation requires a human auth token and cannot be invoked
        by the LLM runtime (R2, R6).
        """
        if not self._halted:
            logger.info("clear_emergency called but state is not HALTED")
            return False

        # In a real ecosystem, validate human_auth_token against a
        # human-approval registry. Here we require non-empty token.
        if not human_auth_token or human_auth_token.strip() == "":
            logger.error("clear_emergency refused: empty auth token")
            return False

        self._halted = False
        self._state = MonitorState.ACTIVE
        self._live_events.clear()
        logger.critical("EMERGENCY state cleared by human. Pipeline may resume.")
        self._notifier.notify(
            DriftTier.NORMAL,
            "EMERGENCY cleared by human operator. Drift monitor resumed.",
            {"auth_token_prefix": human_auth_token[:4] + "****"},
        )
        return True

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def state(self) -> MonitorState:
        return self._state

    @property
    def session_count(self) -> int:
        return len(self._session_metrics)

    @property
    def baseline_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._baseline.to_dict() if self._baseline else None

    def summary(self) -> Dict[str, Any]:
        return {
            "state": self._state.name,
            "session_count": self.session_count,
            "burn_in_complete": self.burn_in_complete,
            "baseline": self.baseline_snapshot,
            "thresholds": {
                "warning_z": self._warning_z,
                "critical_z": self._critical_z,
                "emergency_z": self._emergency_z,
                "slow_drip_window": self._slow_drip_window,
                "slow_drip_threshold": self._slow_drip_threshold,
            },
        }


# ---------------------------------------------------------------------------
# Example / quick-test harness
# ---------------------------------------------------------------------------

def _demo() -> None:
    """Run a minimal demonstration of burn-in and drift detection."""
    import random

    monitor = DriftMonitor(
        error_policy_client=ErrorPolicyClient(),
        policy_engine_client=PolicyEngineClient(),
        notifier=Notifier(),
    )

    # Helper to build deterministic metrics
    def make_metrics(session_id: str, token_total: int, ipi_count: int, policy_violations: int = 0) -> SessionMetrics:
        return SessionMetrics(
            session_id=session_id,
            tokens=TokenMetrics(total=token_total),
            ipi=IPIMetrics(detection_count=ipi_count),
            policy_violations=PolicyViolationMetrics(count=policy_violations),
        )

    # ---- Burn-in: 10 sessions with stable metrics ----
    print("=== BURN-IN PHASE ===")
    for i in range(1, BURN_IN_SESSIONS + 1):
        m = make_metrics(f"session-{i:02d}", token_total=1000 + random.randint(-50, 50), ipi_count=2)
        report = monitor.record_session(m)
        print(f"  {m.session_id}: tier={report.tier.name} action={report.action.name}")

    print(f"\nBaseline: {json.dumps(monitor.baseline_snapshot, indent=2)}\n")

    # ---- Normal session ----
    print("=== NORMAL SESSION ===")
    normal = make_metrics("session-11", token_total=1050, ipi_count=3)
    report = monitor.record_session(normal)
    print(f"  {normal.session_id}: tier={report.tier.name} action={report.action.name}")

    # ---- WARNING session (2.5σ token spike) ----
    print("\n=== WARNING SESSION ===")
    # mean ~1000, stdev ~30-ish → 1150 is roughly 5σ (WARNING/CRITICAL border)
    warning = make_metrics("session-12", token_total=1150, ipi_count=2)
    report = monitor.record_session(warning)
    print(f"  {warning.session_id}: tier={report.tier.name} action={report.action.name}")
    for fm in report.flagged_metrics:
        print(f"    flagged: {fm.metric_name} z={fm.z_score:.2f}")

    # ---- CRITICAL session (3.5σ token spike) ----
    print("\n=== CRITICAL SESSION ===")
    critical = make_metrics("session-13", token_total=1250, ipi_count=2)
    report = monitor.record_session(critical)
    print(f"  {critical.session_id}: tier={report.tier.name} action={report.action.name}")

    # ---- EMERGENCY session (policy violation) ----
    print("\n=== EMERGENCY SESSION (policy violation) ===")
    emergency = make_metrics("session-14", token_total=1010, ipi_count=2, policy_violations=1)
    report = monitor.record_session(emergency)
    print(f"  {emergency.session_id}: tier={report.tier.name} action={report.action.name} forensics={report.forensics_url}")

    # ---- Slow-drip demonstration ----
    print("\n=== SLOW-DRIP TEST ===")
    # 5 sessions at ~2.1σ each to trigger cumulative threshold
    # We fabricate a baseline with mean=1000, stdev=50 for easy math
    # After previous sessions, baseline is already set; we'll just push repeated 2.1σ values.
    # For demo simplicity, we reset and use a synthetic path.
    monitor2 = DriftMonitor(
        error_policy_client=ErrorPolicyClient(),
        policy_engine_client=PolicyEngineClient(),
        notifier=Notifier(),
        slow_drip_window=5,
        slow_drip_threshold=10.0,
    )
    # Artificial burn-in with exactly mean=1000, stdev=50
    for i in range(1, 11):
        # spread values ±50 to get stdev ~30-35; to hit exact numbers is hard,
        # so we instead force a custom baseline after burn-in for the demo.
        monitor2.record_session(make_metrics(f"bi-{i}", 1000, 2))

    # Monkey-patch baseline for deterministic demo
    class FakeBaseline:
        def z_score(self, name: str, value: float) -> float:
            if name == "tokens_total":
                return (value - 1000.0) / 50.0
            return 0.0
        def mean(self, name: str) -> float:
            return 1000.0 if name == "tokens_total" else 0.0
        def stdev(self, name: str) -> float:
            return 50.0 if name == "tokens_total" else 1.0
    monitor2._baseline = FakeBaseline()  # type: ignore[assignment]
    monitor2._state = MonitorState.ACTIVE

    for i in range(15, 20):
        # 2.1σ → 1000 + 2.1*50 = 1105
        m = make_metrics(f"session-{i}", token_total=1105, ipi_count=2)
        report = monitor2.record_session(m)
        print(f"  {m.session_id}: tier={report.tier.name} slow_drip={report.slow_drip_triggered}")

    # Summary
    print("\n=== MONITOR SUMMARY ===")
    print(json.dumps(monitor.summary(), indent=2))


if __name__ == "__main__":
    _demo()
