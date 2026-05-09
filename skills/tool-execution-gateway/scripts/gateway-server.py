#!/usr/bin/env python3
"""
gateway-server.py — Tool Execution Gateway Server
Kimi AI Engineering Skills Ecosystem v4.2.1

Intercepts every tool call from skills, validates through security gates,
and returns ALLOW / BLOCK / ESCALATE with audit trail.

Endpoints:
  POST /execute     → Validate and authorize a tool request
  GET  /health      → Health check
  GET  /audit-log   → Retrieve audit records
  POST /shutdown    → Graceful shutdown

Transport:
  Default: Unix domain socket (unix://C:/Users/Me/.kimi/run/gateway.sock)
  Fallback: TCP loopback (http://127.0.0.1:9102)

Usage:
  python gateway-server.py --unix-socket C:/Users/Me/.kimi/run/gateway.sock
  python gateway-server.py --port 9102
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import re
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_CALLS_PER_TURN = 5
MAX_TOKENS_PER_ACTION = 10_000
RISK_AUTO_APPROVE = 7

# ---------------------------------------------------------------------------
# Platform Enforcement
# ---------------------------------------------------------------------------


def _verify_wsl2_environment(unix_socket: Optional[str]) -> None:
    """Platform check for Windows deployments.

    See policy-engine-server.py for full rationale. TCP loopback is reachable
    from sandbox containers, violating L0 daemon IPC isolation. For local
    activation, TCP fallback is permitted with a warning.
    """
    if sys.platform != "win32":
        return
    has_af_unix = hasattr(socket, "AF_UNIX")
    using_unix_socket = bool(unix_socket and unix_socket.lower() not in ("", "none", "tcp"))
    if using_unix_socket and not has_af_unix:
        logger.error("=" * 70)
        logger.error("PRODUCTION STARTUP BLOCKED")
        logger.error("=" * 70)
        logger.error("Windows detected without native Unix socket support.")
        logger.error("L0 daemons REQUIRE WSL2 for production deployments with Unix sockets.")
        logger.error("")
        logger.error("Options:")
        logger.error("  1. Install WSL2 and run this daemon inside WSL2.")
        logger.error("  2. Use --unix-socket inside WSL2 (native AF_UNIX).")
        logger.error("  3. For local activation, omit --unix-socket to use TCP fallback.")
        logger.error("=" * 70)
        raise RuntimeError(
            "Windows production startup blocked: WSL2 + Unix sockets required."
        )
    if not using_unix_socket:
        logger.warning("=" * 70)
        logger.warning("WINDOWS TCP FALLBACK ACTIVE")
        logger.warning("=" * 70)
        logger.warning("Running on Windows with TCP loopback (port mode).")
        logger.warning("This is acceptable for local development and activation,")
        logger.warning("but Unix sockets are strongly recommended for production.")
        logger.warning("=" * 70)
    else:
        logger.info("Windows WSL2 Unix socket environment verified.")


IDEMPOTENT_TOOLS = {
    "read_file", "grep", "glob", "fetch_url", "search_web",
    "get_file_contents", "list_issues", "get_issue", "get_pull_request",
    "list_commits", "query-docs", "resolve-library-id",
}

STATE_CHANGING_TOOLS = {
    "write_file", "str_replace_file", "shell", "create_or_update_file",
    "push_files", "create_pull_request", "merge_pull_request",
    "create_issue", "update_issue", "create_branch",
}

# Tools that are always non-idempotent regardless of arguments
NEVER_IDEMPOTENT = {"shell", "create_pull_request", "merge_pull_request", "create_or_update_file", "push_files"}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


@dataclass
class AuditEntry:
    entry_id: str
    timestamp: str
    calling_skill: str
    tool: str
    args_hash: str
    decision: str
    reason: str
    risk_score: int
    gate_failed: Optional[str] = None
    previous_hash: str = ""
    elapsed_ms: float = 0.0


@dataclass
class GatewayResponse:
    decision: str
    reason: str
    risk_score: int
    gate_failed: Optional[str] = None
    remediation: Optional[str] = None
    audit_ref: str = ""


# ---------------------------------------------------------------------------
# Hash-chained audit log
# ---------------------------------------------------------------------------

class AuditLog:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "gateway-audit.jsonl"
        self._last_hash = self._compute_last_hash()
        self._lock = threading.Lock()

    def _compute_last_hash(self) -> str:
        if not self.log_file.exists():
            return "0" * 64
        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return "0" * 64
        last = json.loads(lines[-1])
        return last.get("entry_hash", "0" * 64)

    def append(self, entry: AuditEntry) -> str:
        with self._lock:
            data = asdict(entry)
            data["previous_hash"] = self._last_hash
            payload = json.dumps(data, sort_keys=True)
            entry_hash = hashlib.sha256(payload.encode()).hexdigest()
            data["entry_hash"] = entry_hash
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
            self._last_hash = entry_hash
            return entry_hash

    def read_all(self) -> List[Dict[str, Any]]:
        if not self.log_file.exists():
            return []
        with open(self.log_file, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self) -> None:
        self._turn_calls: Dict[str, int] = {}
        self._lock = threading.Lock()

    def reset_turn(self, session_id: str) -> None:
        with self._lock:
            self._turn_calls[session_id] = 0

    def check(self, session_id: str) -> Tuple[bool, str]:
        with self._lock:
            count = self._turn_calls.get(session_id, 0) + 1
            if count > MAX_CALLS_PER_TURN:
                return False, f"Rate limit exceeded: {count}/{MAX_CALLS_PER_TURN} calls per turn"
            self._turn_calls[session_id] = count
            return True, ""


# ---------------------------------------------------------------------------
# Capability registry
# ---------------------------------------------------------------------------

class CapabilityRegistry:
    """Maps skills to their authorized tools."""

    DEFAULT_MANIFEST: Dict[str, List[str]] = {
        "code-tester": ["shell", "read_file", "write_file"],
        "security-auditor": ["shell", "read_file", "search_web"],
        "performance-validator": ["shell", "read_file"],
        "refactoring-engine": ["read_file", "write_file", "str_replace_file"],
        "documentation-synthesizer": ["read_file", "write_file", "search_web"],
        "schema-explorer": ["shell", "read_file"],
        "brownfield-intelligence": ["read_file", "grep", "glob"],
        "address-pr-comments": ["read_file", "write_file", "create_or_update_file", "create_pull_request"],
        "ci-cd-integrator": ["read_file", "write_file", "shell"],
        "infrastructure-as-code": ["read_file", "write_file", "shell"],
        "sandbox-executor": ["shell"],
        "policy-engine": ["read_file"],
        "phase-controller": ["read_file", "write_file"],
    }

    def __init__(self, manifest_path: Optional[Path] = None) -> None:
        self._manifest = dict(self.DEFAULT_MANIFEST)
        if manifest_path and manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                override = json.load(f)
            self._manifest.update(override)

    def is_authorized(self, skill: str, tool: str) -> bool:
        allowed = self._manifest.get(skill, [])
        return tool in allowed

    def is_known_skill(self, skill: str) -> bool:
        return skill in self._manifest


# ---------------------------------------------------------------------------
# Deterministic Skill Registry Enforcer
# ---------------------------------------------------------------------------

class SkillRegistryEnforcer:
    """Deterministic enforcement of skill lifecycle state.

    The prompt-integrated skill-registry skill provides ADVISORY guidance only.
    This class provides the actual CODE enforcement: any tool call from a skill
    that is not in the ACTIVE set is immediately blocked by the gateway.

    ACTIVE skills are hard-coded below. New skills must be explicitly added
    and their capabilities declared before they can invoke tools.
    """

    ACTIVE_SKILLS: set = {
        "code-tester",
        "security-auditor",
        "performance-validator",
        "refactoring-engine",
        "documentation-synthesizer",
        "schema-explorer",
        "brownfield-intelligence",
        "address-pr-comments",
        "ci-cd-integrator",
        "infrastructure-as-code",
        "sandbox-executor",
        "policy-engine",
        "phase-controller",
        "tool-execution-gateway",
    }

    @classmethod
    def is_active(cls, skill: str) -> bool:
        return skill in cls.ACTIVE_SKILLS


# ---------------------------------------------------------------------------
# Circuit Breaker (Deterministic error-policy enforcement)
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Deterministic circuit breaker for tool execution.

    The prompt-integrated error-policy skill provides ADVISORY guidance only.
    This class provides the actual CODE enforcement: after a threshold of
    consecutive failures, all further tool calls are blocked until a cooldown
    period expires. This prevents cascade failures and runaway retry loops.
    """

    def __init__(self, threshold: int = 5, cooldown_seconds: int = 30) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._last_failure_time = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.time()

    def is_open(self) -> bool:
        with self._lock:
            if self._failures < self.threshold:
                return False
            if self._last_failure_time is None:
                return False
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.cooldown_seconds:
                # Cooldown expired — reset to half-threshold (gradual recovery)
                self._failures = self.threshold // 2
                self._last_failure_time = None
                return False
            return True


# ---------------------------------------------------------------------------
# Secret scrubber (SEC-005)
# ---------------------------------------------------------------------------

class SecretScrubber:
    """Scrub secrets from strings/dicts before they enter audit logs or LLM context."""

    _SECRET_PATTERNS: List[re.Pattern] = [
        re.compile(r"(?i)(api[_-]?key|token|password|secret|private[_-]?key|auth|bearer)\s*[=:]\s*[\"']?[A-Za-z0-9_\-\+/=]{8,}[\"']?"),
        re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"),
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,})\b"),
    ]

    @staticmethod
    def _shannon_entropy(data: str) -> float:
        if not data:
            return 0.0
        freq: Dict[str, int] = {}
        for ch in data:
            freq[ch] = freq.get(ch, 0) + 1
        entropy = 0.0
        length = len(data)
        for count in freq.values():
            p = count / length
            entropy -= p * math.log2(p)
        return entropy / length

    @classmethod
    def _redact_high_entropy(cls, text: str) -> str:
        def replace(m: re.Match) -> str:
            token = m.group(0)
            if len(token) >= 16 and cls._shannon_entropy(token) > 3.5:
                return "[REDACTED]"
            return token
        return re.sub(r"[A-Za-z0-9_\-\+/=]{16,}", replace, text)

    @classmethod
    def scrub(cls, text: str) -> str:
        if not isinstance(text, str):
            return text
        result = text
        for pattern in cls._SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        result = cls._redact_high_entropy(result)
        return result

    @classmethod
    def scrub_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        scrubbed: Dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, str):
                scrubbed[k] = cls.scrub(v)
            elif isinstance(v, dict):
                scrubbed[k] = cls.scrub_dict(v)
            else:
                scrubbed[k] = v
        return scrubbed


# ---------------------------------------------------------------------------
# Gateway core
# ---------------------------------------------------------------------------

class ToolExecutionGateway:
    def __init__(
        self,
        policy_engine_endpoint: str = "unix://C:/Users/Me/.kimi/run/policy-engine.sock",
        audit_dir: Optional[Path] = None,
    ) -> None:
        self.policy_endpoint = policy_engine_endpoint
        self.audit_log = AuditLog(audit_dir or Path("~/.kimi/logs/gateway").expanduser())
        self.rate_limiter = RateLimiter()
        self.capabilities = CapabilityRegistry()
        self.circuit_breaker = CircuitBreaker(threshold=5, cooldown_seconds=30)

    def evaluate(self, request: Dict[str, Any]) -> GatewayResponse:
        start = time.perf_counter()
        skill = request.get("skill", "unknown")
        tool = request.get("tool", "unknown")
        args = request.get("args", {})
        session_id = request.get("session_id", "default")

        audit_id = str(uuid.uuid4())

        # Gate 0: Skill registry enforcement (deterministic — not prompt-integrated)
        if not SkillRegistryEnforcer.is_active(skill):
            return self._blocked(
                skill, tool, args, audit_id,
                gate="skill_registry",
                reason=f"Skill '{skill}' is not in the ACTIVE registry. Tool calls from unregistered skills are prohibited.",
                remediation="Register the skill in SkillRegistryEnforcer.ACTIVE_SKILLS and declare capabilities.",
            )

        # Gate 1: Circuit breaker (deterministic error-policy enforcement)
        if self.circuit_breaker.is_open():
            return self._blocked(
                skill, tool, args, audit_id,
                gate="circuit_breaker",
                reason="Circuit breaker is OPEN due to consecutive failures. All tool calls temporarily blocked.",
                remediation="Wait for cooldown period or restart gateway daemon.",
            )

        # Gate 2: Capability check
        if not self.capabilities.is_authorized(skill, tool):
            self.circuit_breaker.record_failure()
            return self._blocked(
                skill, tool, args, audit_id,
                gate="capability",
                reason=f"Skill '{skill}' is not authorized for tool '{tool}'",
                remediation="Request a temporary capability grant via /grant-capability",
            )

        # Gate 3: Rate limiting
        ok, msg = self.rate_limiter.check(session_id)
        if not ok:
            self.circuit_breaker.record_failure()
            return self._blocked(skill, tool, args, audit_id, gate="rate_limit", reason=msg)

        # Gate 4: Path traversal check
        if self._has_path_traversal(args):
            self.circuit_breaker.record_failure()
            return self._blocked(
                skill, tool, args, audit_id,
                gate="path_traversal",
                reason="Path traversal detected in arguments",
                remediation="Use absolute paths within the project root only",
            )

        # Gate 5: Shell sanitization
        if tool == "shell":
            cmd = args.get("command", "")
            if self._has_dangerous_shell(cmd):
                self.circuit_breaker.record_failure()
                return self._blocked(
                    skill, tool, args, audit_id,
                    gate="sanitization",
                    reason="Dangerous shell metacharacters detected",
                    remediation="Remove pipes, redirections, or command substitutions",
                )

        # Gate 6: Idempotency + risk scoring
        risk_score = self._compute_risk_score(skill, tool, args)

        if tool in NEVER_IDEMPOTENT or risk_score >= RISK_AUTO_APPROVE:
            elapsed = (time.perf_counter() - start) * 1000
            self._log(audit_id, skill, tool, args, "ESCALATE",
                      f"Non-idempotent or high-risk action (score={risk_score})",
                      risk_score, elapsed_ms=elapsed)
            return GatewayResponse(
                decision="PENDING_OVERRIDE",
                reason=f"Action requires human approval (risk score: {risk_score}/10)",
                risk_score=risk_score,
                gate_failed="risk_threshold",
                remediation="Confirm execution via human-in-the-loop",
                audit_ref=audit_id,
            )

        # Gate 7: Policy engine validation
        policy_result = self._call_policy_engine(request)
        if policy_result.get("action") == "BLOCK":
            self.circuit_breaker.record_failure()
            reason = policy_result.get("reason", "Blocked by policy engine")
            return self._blocked(skill, tool, args, audit_id, gate="policy", reason=reason)

        # ALLOW
        self.circuit_breaker.record_success()
        elapsed = (time.perf_counter() - start) * 1000
        self._log(audit_id, skill, tool, args, "ALLOW", "All gates passed", risk_score, elapsed_ms=elapsed)
        return GatewayResponse(
            decision="AUTO_APPROVED",
            reason="All security gates passed",
            risk_score=risk_score,
            audit_ref=audit_id,
        )

    def _blocked(self, skill: str, tool: str, args: Dict[str, Any], audit_id: str,
                 gate: str, reason: str, remediation: Optional[str] = None) -> GatewayResponse:
        self._log(audit_id, skill, tool, args, "BLOCK", reason, risk_score=10, gate=gate)
        return GatewayResponse(
            decision="BLOCKED",
            reason=reason,
            risk_score=10,
            gate_failed=gate,
            remediation=remediation,
            audit_ref=audit_id,
        )

    def _log(self, audit_id: str, skill: str, tool: str, args: Dict[str, Any],
             decision: str, reason: str, risk_score: int, gate: Optional[str] = None,
             elapsed_ms: float = 0.0) -> None:
        scrubbed_args = SecretScrubber.scrub_dict(args)
        args_hash = hashlib.sha256(json.dumps(scrubbed_args, sort_keys=True).encode()).hexdigest()
        scrubbed_reason = SecretScrubber.scrub(reason)
        entry = AuditEntry(
            entry_id=audit_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            calling_skill=skill,
            tool=tool,
            args_hash=args_hash,
            decision=decision,
            reason=scrubbed_reason,
            risk_score=risk_score,
            gate_failed=gate,
            elapsed_ms=elapsed_ms,
        )
        self.audit_log.append(entry)

    def _has_path_traversal(self, args: Dict[str, Any]) -> bool:
        for value in args.values():
            if isinstance(value, str):
                if ".." in value or value.startswith(("/etc/", "/usr/", "/root/", "~/.ssh")):
                    return True
        return False

    def _has_dangerous_shell(self, cmd: str) -> bool:
        dangerous = ["|", ";", "&", "$", "`", "$(", ">", "<", "||", "&&"]
        return any(d in cmd for d in dangerous)

    def _compute_risk_score(self, skill: str, tool: str, args: Dict[str, Any]) -> int:
        score = 0
        if tool in NEVER_IDEMPOTENT:
            score += 5
        elif tool in STATE_CHANGING_TOOLS:
            score += 3
        if tool == "shell":
            score += 2
        if "delete" in str(args).lower() or "rm " in str(args.get("command", "")).lower():
            score += 3
        return min(score, 10)

    def _call_policy_engine(self, request: Dict[str, Any]) -> Dict[str, Any]:
        try:
            payload = json.dumps(request).encode()
            endpoint = self.policy_endpoint
            if endpoint.startswith("unix://"):
                return self._call_policy_engine_unix(endpoint, payload)
            url = endpoint if endpoint.startswith("http") else "http://127.0.0.1:9100/validate"
            import urllib.request
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.warning("Policy engine unreachable: %s — failing closed", exc)
            return {"action": "BLOCK", "reason": "Policy engine unavailable"}

    def _call_policy_engine_unix(self, endpoint: str, payload: bytes) -> Dict[str, Any]:
        """Call policy engine via Unix domain socket."""
        socket_path = endpoint.replace("unix://", "").replace("unix:", "")
        import http.client
        conn = http.client.HTTPConnection("localhost")
        original_connect = conn.connect
        def _unix_connect():
            import socket
            conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn.sock.settimeout(5)
            conn.sock.connect(socket_path)
        conn.connect = _unix_connect
        conn.request("POST", "/validate", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return json.loads(data.decode())


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


try:
    _AF_UNIX = socket.AF_UNIX

    class ThreadedUnixHTTPServer(ThreadingMixIn, HTTPServer):
        address_family = _AF_UNIX

        def server_bind(self):
            if isinstance(self.server_address, str) and os.path.exists(self.server_address):
                os.unlink(self.server_address)
            super().server_bind()
            os.chmod(self.server_address, 0o600)
except AttributeError:
    ThreadedUnixHTTPServer = None  # type: ignore


class GatewayHandler(BaseHTTPRequestHandler):
    gateway: Optional[ToolExecutionGateway] = None

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _verify_shutdown_auth(self) -> bool:
        secret = os.environ.get("KIMI_GATEWAY_SECRET") or os.environ.get("KIMI_L0_SECRET")
        if not secret:
            return False
        timestamp_header = self.headers.get("X-Kimi-Timestamp")
        signature_header = self.headers.get("X-Kimi-Signature")
        if not timestamp_header or not signature_header:
            return False
        try:
            timestamp = int(timestamp_header)
        except (ValueError, TypeError):
            return False
        now = int(datetime.now(timezone.utc).timestamp())
        if abs(now - timestamp) > 60:
            return False
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp_header}{self.path}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        return json.loads(body.decode())

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "gateway": "active"})
        elif self.path == "/audit-log":
            entries = self.gateway.audit_log.read_all() if self.gateway else []
            self._send_json(200, {"entries": entries})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/execute":
            try:
                request = self._read_json()
                response = self.gateway.evaluate(request) if self.gateway else GatewayResponse(
                    decision="BLOCKED", reason="Gateway not initialized", risk_score=10
                )
                status = 200 if response.decision in ("AUTO_APPROVED", "PENDING_OVERRIDE") else 403
                self._send_json(status, asdict(response))
            except Exception as exc:
                logger.exception("Error processing /execute")
                self._send_json(500, {"error": str(exc)})
        elif self.path == "/shutdown":
            if not self._verify_shutdown_auth():
                self._send_json(401, {"error": "Unauthorized"})
                return
            self._send_json(200, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json(404, {"error": "Not found"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool Execution Gateway Server")
    parser.add_argument("--unix-socket", default="", help="Unix socket path. Omit for TCP fallback.")
    parser.add_argument("--port", type=int, default=9102, help="TCP port (dev fallback)")
    parser.add_argument("--host", default="127.0.0.1", help="TCP host (dev fallback)")
    parser.add_argument("--policy-endpoint", default="unix://C:/Users/Me/.kimi/run/policy-engine.sock")
    args = parser.parse_args()

    try:
        _verify_wsl2_environment(args.unix_socket)
    except RuntimeError as exc:
        logger.error("Startup guard failed: %s", exc)
        sys.exit(1)

    gateway = ToolExecutionGateway(policy_engine_endpoint=args.policy_endpoint)
    GatewayHandler.gateway = gateway

    if ThreadedUnixHTTPServer and args.unix_socket:
        socket_dir = Path(args.unix_socket).parent
        socket_dir.mkdir(parents=True, exist_ok=True)
        server = ThreadedUnixHTTPServer(args.unix_socket, GatewayHandler)
        logger.info("Gateway listening on unix://%s", args.unix_socket)
    else:
        server = ThreadedHTTPServer((args.host, args.port), GatewayHandler)
        logger.warning("Gateway listening on http://%s:%d (TCP — NOT FOR PRODUCTION)", args.host, args.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        server.shutdown()


if __name__ == "__main__":
    main()
