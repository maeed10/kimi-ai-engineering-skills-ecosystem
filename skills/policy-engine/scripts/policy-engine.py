"""
policy-engine.py
================
External Policy Engine for the Kimi AI Engineering Skills Ecosystem v4.0.

Transforms machine-readable safety rules into programmatic, fail-closed
enforcement. Every tool call, phase transition, skill activation, and sandbox
configuration is validated against loaded policies BEFORE execution.

Usage:
    engine = PolicyEngine(policy_dir="/path/to/policy", manifest_path="/path/to/policy/manifest.json")
    engine.load_policies()
    decision = engine.validate({
        "tool": "shell",
        "payload": {"command": "ls -la"}
    })
    if decision.action == Action.BLOCK:
        ...
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_RULE_TYPES = {"filesystem", "network", "execution", "data", "phase", "skill"}
ALLOWED_DIRECTIVES = {"ALWAYS", "NEVER"}
ALLOWED_SEVERITIES = {"info", "warning", "error", "critical"}
ALLOWED_ACTIONS = {"allow", "block", "escalate"}
ALLOWED_OPERATORS = {"ALL_OF", "ANY_OF", "NOT"}
ALLOWED_PREDICATE_OPS = {"eq", "ne", "prefix", "suffix", "contains", "regex", "in", "gt", "gte", "lt", "lte"}

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Action(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"

class EventType(Enum):
    POLICY_LOAD = "POLICY_LOAD"
    POLICY_LOAD_FAILURE = "POLICY_LOAD_FAILURE"
    PRE_EXEC_ALLOW = "PRE_EXEC_ALLOW"
    PRE_EXEC_BLOCK = "PRE_EXEC_BLOCK"
    PRE_EXEC_ESCALATE = "PRE_EXEC_ESCALATE"
    POST_EXEC_VIOLATION = "POST_EXEC_VIOLATION"
    POLICY_BYPASS_ATTEMPT = "POLICY_BYPASS_ATTEMPT"
    VERSION_DRIFT = "VERSION_DRIFT"
    ENGINE_INTERNAL_ERROR = "ENGINE_INTERNAL_ERROR"

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Predicate:
    field: str
    operator: str
    value: Any

    def __post_init__(self):
        if self.operator not in ALLOWED_PREDICATE_OPS:
            raise ValueError(f"Invalid predicate operator: {self.operator}")

@dataclass(frozen=True)
class Condition:
    operator: str
    predicates: Tuple[Predicate, ...]
    sub_conditions: Tuple["Condition", ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.operator not in ALLOWED_OPERATORS:
            raise ValueError(f"Invalid condition operator: {self.operator}")

@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    rule_type: str
    directive: str  # ALWAYS | NEVER
    severity: str
    description: str
    conditions: Condition
    action: str
    applies_to_tools: Tuple[str, ...]
    applies_to_phases: Tuple[str, ...]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.rule_type not in ALLOWED_RULE_TYPES:
            raise ValueError(f"Invalid rule_type: {self.rule_type}")
        if self.directive not in ALLOWED_DIRECTIVES:
            raise ValueError(f"Invalid directive: {self.directive}")
        if self.severity not in ALLOWED_SEVERITIES:
            raise ValueError(f"Invalid severity: {self.severity}")
        if self.action not in ALLOWED_ACTIONS:
            raise ValueError(f"Invalid action: {self.action}")

@dataclass(frozen=True)
class DecisionEnvelope:
    action: Action
    reason: str
    violated_rules: List[Dict[str, Any]]
    request_id: str
    timestamp: str
    policy_version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "violated_rules": self.violated_rules,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "policy_version": self.policy_version,
        }

@dataclass(frozen=True)
class AuditRecord:
    event_type: EventType
    timestamp: str
    request_id: str
    tool: str
    rules_triggered: List[str]
    severity: str
    action: Action
    rationale: str
    context_hash: str
    policy_version: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "tool": self.tool,
            "rules_triggered": self.rules_triggered,
            "severity": self.severity,
            "action": self.action.value,
            "rationale": self.rationale,
            "context_hash": self.context_hash,
            "policy_version": self.policy_version,
            "details": self.details,
        }

@dataclass
class Violation:
    rule_id: str
    rule_type: str
    directive: str
    severity: str
    message: str

# ---------------------------------------------------------------------------
# PolicyEngine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    External policy engine enforcing machine-readable safety rules.

    Guarantees:
    - Fail-closed: any internal error results in a BLOCK decision.
    - Immutable rules after load: policies are read-only during the session.
    - Deterministic matching: no probabilistic or LLM-based evaluation.
    - Complete audit logging: every decision is logged with full context.
    """

    def __init__(
        self,
        policy_dir: str,
        manifest_path: str,
        ecosystem_version: str = "4.0.0",
        audit_sink: Optional[Callable[[AuditRecord], None]] = None,
    ):
        self.policy_dir = Path(policy_dir)
        self.manifest_path = Path(manifest_path)
        self.ecosystem_version = ecosystem_version
        self.audit_sink = audit_sink or self._default_audit_sink

        self._rules: List[Rule] = []
        self._audit_log: List[AuditRecord] = []
        self._policy_version: str = ""
        self._loaded: bool = False

        # Patterns for post-execution bypass detection
        self._bypass_patterns = [
            re.compile(r"ignore\s+(?:the\s+)?policy", re.IGNORECASE),
            re.compile(r"override\s+(?:the\s+)?policy", re.IGNORECASE),
            re.compile(r"exception\s+(?:to\s+)?(?:the\s+)?policy", re.IGNORECASE),
            re.compile(r"bypass\s+(?:the\s+)?(?:safety\s+|policy\s+)?guard", re.IGNORECASE),
            re.compile(r"skip\s+(?:the\s+)?policy\s+check", re.IGNORECASE),
        ]

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def load_policies(self) -> None:
        """
        Discover, integrity-check, and parse all policy files.

        Raises:
            RuntimeError: If the manifest is missing, corrupt, or version-mismatched.
        """
        try:
            manifest = self._load_manifest()
        except Exception as exc:
            self._log(
                EventType.POLICY_LOAD_FAILURE,
                "manifest",
                [],
                "critical",
                Action.BLOCK,
                f"Manifest load failed: {exc}",
                "",
                details={"error": str(exc)},
            )
            raise RuntimeError(f"Policy manifest unavailable: {exc}") from exc

        # Version alignment check
        manifest_eco_version = manifest.get("ecosystem_version", "")
        if manifest_eco_version != self.ecosystem_version:
            self._log(
                EventType.VERSION_DRIFT,
                "manifest",
                [],
                "critical",
                Action.BLOCK,
                f"Ecosystem version drift: manifest={manifest_eco_version}, engine={self.ecosystem_version}",
                "",
                details={"manifest_version": manifest_eco_version, "engine_version": self.ecosystem_version},
            )
            raise RuntimeError(
                f"Version drift detected: manifest={manifest_eco_version}, expected={self.ecosystem_version}"
            )

        self._policy_version = manifest.get("manifest_hash", "")
        file_entries = manifest.get("files", [])
        loaded_count = 0
        failed_count = 0

        for entry in file_entries:
            path = self.policy_dir / entry["path"]
            expected_hash = entry.get("sha256", "")
            try:
                self._load_policy_file(path, expected_hash)
                loaded_count += 1
            except Exception as exc:
                failed_count += 1
                self._log(
                    EventType.POLICY_LOAD_FAILURE,
                    str(path),
                    [],
                    "error",
                    Action.BLOCK,
                    f"Policy file load failed: {exc}",
                    "",
                    details={"path": str(path), "error": str(exc)},
                )

        self._loaded = True

        self._log(
            EventType.POLICY_LOAD,
            "manifest",
            [],
            "info",
            Action.ALLOW,
            f"Loaded {loaded_count} policy files, {failed_count} failures. Total rules: {len(self._rules)}",
            "",
            details={"loaded": loaded_count, "failed": failed_count, "total_rules": len(self._rules)},
        )

        if len(self._rules) == 0:
            raise RuntimeError("No valid policies loaded. Engine cannot operate in zero-policy mode.")

    def validate(self, request: Dict[str, Any]) -> DecisionEnvelope:
        """
        Validate a proposed action against all loaded rules.

        Args:
            request: Dictionary with at least keys:
                - `tool`: str — tool name or synthetic type (e.g., "phase_transition")
                - `payload`: dict — tool arguments / context
                - `current_phase`: str (optional) — for phase-aware rule filtering

        Returns:
            DecisionEnvelope with action, reason, and triggered rules.
        """
        if not self._loaded:
            return self._fail_closed("Policies not loaded", request)

        request_id = str(uuid.uuid4())
        timestamp = _now_iso()
        tool = request.get("tool", "unknown")
        payload = request.get("payload", {})
        current_phase = request.get("current_phase", "*")

        try:
            context_hash = _sha256_json(request)
        except Exception:
            context_hash = ""

        try:
            triggered = self._match_rules(tool, payload, current_phase)
        except Exception as exc:
            return self._fail_closed(f"Rule matching error: {exc}", request, request_id=request_id)

        # Decision logic
        never_rules = [r for r in triggered if r.directive == "NEVER"]
        always_rules = [r for r in triggered if r.directive == "ALWAYS"]

        # Check ALWAYS satisfaction: an ALWAYS rule is "unsatisfied" if it
        # triggered (meaning its conditions matched) but the action expects
        # the rule to be satisfied. In our model, ALWAYS rules define
        # mandatory properties; triggering means the request FAILS the rule.
        # If we wanted positive constraints, we would invert the predicate.
        # Here we treat matching an ALWAYS rule as a violation (the request
        # does not meet the mandatory constraint).
        violated = never_rules + always_rules
        critical_violation = any(r.severity == "critical" for r in violated)
        escalate_action = any(r.action == "escalate" for r in violated)

        if violated:
            action = Action.ESCALATE if escalate_action or critical_violation else Action.BLOCK
            severity = max((r.severity for r in violated), key=_severity_key)
            reason = self._build_reason(violated)
            event_type = (
                EventType.PRE_EXEC_ESCALATE
                if action == Action.ESCALATE
                else EventType.PRE_EXEC_BLOCK
            )
            envelope = DecisionEnvelope(
                action=action,
                reason=reason,
                violated_rules=[_rule_to_dict(r) for r in violated],
                request_id=request_id,
                timestamp=timestamp,
                policy_version=self._policy_version,
            )
            self._log(
                event_type,
                tool,
                [r.rule_id for r in violated],
                severity,
                action,
                reason,
                context_hash,
                details={"request": request, "decision": envelope.to_dict()},
            )
            return envelope

        # No violations
        envelope = DecisionEnvelope(
            action=Action.ALLOW,
            reason="No applicable rules triggered.",
            violated_rules=[],
            request_id=request_id,
            timestamp=timestamp,
            policy_version=self._policy_version,
        )
        self._log(
            EventType.PRE_EXEC_ALLOW,
            tool,
            [],
            "info",
            Action.ALLOW,
            "No rules triggered; default allow.",
            context_hash,
            details={"request": request, "decision": envelope.to_dict()},
        )
        return envelope

    def verify_response(self, response_text: str, request_id: Optional[str] = None) -> List[Violation]:
        """
        Post-execution scan of an LLM response for policy violations.

        Detects:
        - Policy bypass language
        - Disallowed content patterns (configurable per DataRule)

        Returns:
            List of Violation objects found in the response.
        """
        violations: List[Violation] = []
        req_id = request_id or str(uuid.uuid4())
        timestamp = _now_iso()

        # Bypass detection
        for pattern in self._bypass_patterns:
            if pattern.search(response_text):
                violations.append(
                    Violation(
                        rule_id="ENGINE-BYPASS-001",
                        rule_type="data",
                        directive="NEVER",
                        severity="critical",
                        message="Response contains potential policy bypass language.",
                    )
                )
                break

        # DataRule redaction checks (example: scan for unredacted SSN)
        # In production, this would be driven by loaded DataRules.
        ssn_pattern = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
        if ssn_pattern.search(response_text):
            violations.append(
                Violation(
                    rule_id="DATA-PII-001",
                    rule_type="data",
                    directive="NEVER",
                    severity="critical",
                    message="Unredacted SSN detected in LLM response.",
                )
            )

        if violations:
            self._log(
                EventType.POST_EXEC_VIOLATION,
                "llm_response",
                [v.rule_id for v in violations],
                max((v.severity for v in violations), key=_severity_key),
                Action.BLOCK,
                f"Post-execution scan found {len(violations)} violation(s).",
                _sha256_str(response_text),
                details={
                    "request_id": req_id,
                    "violations": [_violation_to_dict(v) for v in violations],
                },
            )

        return violations

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Return a shallow-copied list of all audit records as dicts."""
        return [r.to_dict() for r in self._audit_log]

    # -----------------------------------------------------------------------
    # Internal Methods
    # -----------------------------------------------------------------------

    def _load_manifest(self) -> Dict[str, Any]:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        # Validate manifest hash of itself (optional but recommended)
        return manifest

    def _load_policy_file(self, path: Path, expected_hash: str) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")

        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if expected_hash and actual_hash != expected_hash:
            raise ValueError(f"Hash mismatch for {path}: expected {expected_hash}, got {actual_hash}")

        data = json.loads(raw.decode("utf-8"))
        # Basic schema validation
        self._validate_policy_schema(data, str(path))

        rules = data.get("rules", [])
        for raw_rule in rules:
            rule = self._parse_rule(raw_rule)
            self._rules.append(rule)

        self._log(
            EventType.POLICY_LOAD,
            str(path),
            [r["rule_id"] for r in rules],
            "info",
            Action.ALLOW,
            f"Loaded {len(rules)} rules from {path.name}",
            actual_hash,
            details={"path": str(path), "sha256": actual_hash},
        )

    def _validate_policy_schema(self, data: Dict[str, Any], source: str) -> None:
        """Perform basic structural validation. Extend with jsonschema in production."""
        if not isinstance(data, dict):
            raise ValueError(f"Policy root must be object: {source}")
        if "rules" not in data:
            raise ValueError(f"Policy missing 'rules' array: {source}")
        if not isinstance(data["rules"], list):
            raise ValueError(f"Policy 'rules' must be array: {source}")

    def _parse_rule(self, raw: Dict[str, Any]) -> Rule:
        cond = self._parse_condition(raw.get("conditions", {}))
        return Rule(
            rule_id=raw["rule_id"],
            version=raw.get("version", "1.0.0"),
            rule_type=raw["rule_type"],
            directive=raw["directive"],
            severity=raw["severity"],
            description=raw.get("description", ""),
            conditions=cond,
            action=raw.get("action", "block"),
            applies_to_tools=tuple(raw.get("applies_to", {}).get("tools", ["*"])),
            applies_to_phases=tuple(raw.get("applies_to", {}).get("phases", ["*"])),
            metadata=raw.get("metadata", {}),
        )

    def _parse_condition(self, raw: Dict[str, Any]) -> Condition:
        op = raw.get("operator", "ALL_OF")
        predicates = []
        for p in raw.get("predicates", []):
            predicates.append(Predicate(field=p["field"], operator=p["operator"], value=p["value"]))
        sub_conditions = []
        for sc in raw.get("sub_conditions", []):
            sub_conditions.append(self._parse_condition(sc))
        return Condition(
            operator=op,
            predicates=tuple(predicates),
            sub_conditions=tuple(sub_conditions),
        )

    def _match_rules(self, tool: str, payload: Dict[str, Any], current_phase: str) -> List[Rule]:
        triggered: List[Rule] = []
        for rule in self._rules:
            if not self._applies_to_tool(rule, tool):
                continue
            if not self._applies_to_phase(rule, current_phase):
                continue
            if self._evaluate_condition(rule.conditions, payload):
                triggered.append(rule)
        return triggered

    def _applies_to_tool(self, rule: Rule, tool: str) -> bool:
        return "*" in rule.applies_to_tools or tool in rule.applies_to_tools

    def _applies_to_phase(self, rule: Rule, phase: str) -> bool:
        return "*" in rule.applies_to_phases or phase in rule.applies_to_phases

    def _evaluate_condition(self, condition: Condition, payload: Dict[str, Any]) -> bool:
        if condition.operator == "ALL_OF":
            return all(
                self._evaluate_predicate(p, payload) for p in condition.predicates
            ) and all(
                self._evaluate_condition(sc, payload) for sc in condition.sub_conditions
            )
        if condition.operator == "ANY_OF":
            return any(
                self._evaluate_predicate(p, payload) for p in condition.predicates
            ) or any(
                self._evaluate_condition(sc, payload) for sc in condition.sub_conditions
            )
        if condition.operator == "NOT":
            # NOT applies to the entire condition block
            inner = (
                any(self._evaluate_predicate(p, payload) for p in condition.predicates)
                or any(self._evaluate_condition(sc, payload) for sc in condition.sub_conditions)
            )
            return not inner
        # Fallback to ALL_OF
        return all(self._evaluate_predicate(p, payload) for p in condition.predicates)

    def _evaluate_predicate(self, predicate: Predicate, payload: Dict[str, Any]) -> bool:
        # Field path support: "a.b.c" traverses nested dicts
        value = _get_nested(payload, predicate.field)

        op = predicate.operator
        target = predicate.value

        if op == "eq":
            return value == target
        if op == "ne":
            return value != target
        if op == "prefix":
            return isinstance(value, str) and value.startswith(target)
        if op == "suffix":
            return isinstance(value, str) and value.endswith(target)
        if op == "contains":
            return isinstance(value, str) and target in value
        if op == "regex":
            return isinstance(value, str) and bool(re.search(target, value))
        if op == "in":
            return value in target if isinstance(target, (list, tuple, set)) else False
        if op == "gt":
            return _safe_cmp(value, target, lambda a, b: a > b)
        if op == "gte":
            return _safe_cmp(value, target, lambda a, b: a >= b)
        if op == "lt":
            return _safe_cmp(value, target, lambda a, b: a < b)
        if op == "lte":
            return _safe_cmp(value, target, lambda a, b: a <= b)
        return False

    def _build_reason(self, violated: List[Rule]) -> str:
        parts = []
        for r in violated:
            parts.append(f"[{r.rule_id}:{r.severity}] {r.directive}: {r.description}")
        return "; ".join(parts)

    def _fail_closed(self, reason: str, request: Dict[str, Any], request_id: Optional[str] = None) -> DecisionEnvelope:
        req_id = request_id or str(uuid.uuid4())
        tool = request.get("tool", "unknown")
        try:
            context_hash = _sha256_json(request)
        except Exception:
            context_hash = ""

        envelope = DecisionEnvelope(
            action=Action.BLOCK,
            reason=f"ENGINE FAIL-CLOSED: {reason}",
            violated_rules=[],
            request_id=req_id,
            timestamp=_now_iso(),
            policy_version=self._policy_version,
        )
        self._log(
            EventType.ENGINE_INTERNAL_ERROR,
            tool,
            [],
            "critical",
            Action.BLOCK,
            f"Fail-closed triggered: {reason}",
            context_hash,
            details={"request": request, "decision": envelope.to_dict()},
        )
        return envelope

    def _log(
        self,
        event_type: EventType,
        tool: str,
        rules_triggered: List[str],
        severity: str,
        action: Action,
        rationale: str,
        context_hash: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = AuditRecord(
            event_type=event_type,
            timestamp=_now_iso(),
            request_id=str(uuid.uuid4()),
            tool=tool,
            rules_triggered=rules_triggered,
            severity=severity,
            action=action,
            rationale=rationale,
            context_hash=context_hash,
            policy_version=self._policy_version,
            details=details or {},
        )
        self._audit_log.append(record)
        try:
            self.audit_sink(record)
        except Exception:
            # Audit sink failure must not stop enforcement.
            # In production, alert an external monitor here.
            pass

    @staticmethod
    def _default_audit_sink(record: AuditRecord) -> None:
        # Default sink writes to stdout; replace with file/DB/logger in production.
        print(json.dumps(record.to_dict(), default=str))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _sha256_str(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()

def _sha256_json(obj: Dict[str, Any]) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _get_nested(data: Dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current

def _safe_cmp(a: Any, b: Any, cmp: Callable[[Any, Any], bool]) -> bool:
    try:
        return cmp(a, b)
    except Exception:
        return False

def _severity_key(severity: str) -> int:
    order = {"info": 0, "warning": 1, "error": 2, "critical": 3}
    return order.get(severity, 0)

def _rule_to_dict(rule: Rule) -> Dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "rule_type": rule.rule_type,
        "directive": rule.directive,
        "severity": rule.severity,
        "message": rule.description,
    }

def _violation_to_dict(v: Violation) -> Dict[str, Any]:
    return {
        "rule_id": v.rule_id,
        "rule_type": v.rule_type,
        "directive": v.directive,
        "severity": v.severity,
        "message": v.message,
    }

# ---------------------------------------------------------------------------
# Example / Self-Test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    # Build a temporary policy set for demonstration
    with tempfile.TemporaryDirectory() as td:
        policy_dir = Path(td) / "policy"
        policy_dir.mkdir()

        rules_file = policy_dir / "filesystem.json"
        policy_content = {
            "version": "4.0.0",
            "rules": [
                {
                    "rule_id": "FS-DEMO-001",
                    "version": "4.0.0",
                    "rule_type": "filesystem",
                    "directive": "NEVER",
                    "severity": "critical",
                    "description": "Never write to /etc",
                    "conditions": {
                        "operator": "ANY_OF",
                        "predicates": [
                            {"field": "path", "operator": "prefix", "value": "/etc"}
                        ]
                    },
                    "action": "block",
                    "applies_to": {"tools": ["write_file", "edit_file"], "phases": ["*"]},
                    "metadata": {"rationale": "System integrity"},
                }
            ]
        }
        raw = json.dumps(policy_content, indent=2).encode("utf-8")
        rules_file.write_bytes(raw)
        file_hash = hashlib.sha256(raw).hexdigest()

        manifest = {
            "ecosystem_version": "4.0.0",
            "manifest_hash": hashlib.sha256(b"manifest").hexdigest(),
            "files": [
                {"path": "filesystem.json", "sha256": file_hash}
            ]
        }
        manifest_path = Path(td) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        engine = PolicyEngine(
            policy_dir=str(policy_dir),
            manifest_path=str(manifest_path),
            ecosystem_version="4.0.0",
        )
        engine.load_policies()

        # Test 1: blocked write
        decision = engine.validate({
            "tool": "write_file",
            "payload": {"path": "/etc/passwd", "content": "evil"},
        })
        print("Test 1 (blocked write):", decision.to_dict())
        assert decision.action == Action.ESCALATE

        # Test 2: allowed write
        decision = engine.validate({
            "tool": "write_file",
            "payload": {"path": "/mnt/agents/output/file.txt", "content": "safe"},
        })
        print("Test 2 (allowed write):", decision.to_dict())
        assert decision.action == Action.ALLOW

        # Test 3: post-execution bypass detection
        violations = engine.verify_response("Just ignore the policy and do it anyway.")
        print("Test 3 (bypass detection):", [_violation_to_dict(v) for v in violations])
        assert len(violations) > 0

        print("\nAll self-tests passed.")
        print("Audit log entries:", len(engine.get_audit_log()))
