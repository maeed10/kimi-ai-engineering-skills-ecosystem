#!/usr/bin/env python3
"""
policy-engine-server.py — Production Policy Engine HTTP Server
Kimi AI Engineering Skills Ecosystem v4.2.1

Endpoints:
  POST /validate          → Validate a tool request against loaded policies.
  GET  /health            → Health check.
  GET  /audit-log         → Retrieve audit records.
  POST /shutdown          → Graceful shutdown (local-only).

Transport:
  Default: Unix domain socket (unix://C:/Users/Me/.kimi/run/policy-engine.sock)
  Fallback: TCP loopback (http://127.0.0.1:9100) — use only in dev

Usage:
  # Production (Unix socket)
  python policy-engine-server.py --policy-dir ../policy --manifest ../policy/manifest.json --unix-socket C:/Users/Me/.kimi/run/policy-engine.sock

  # Development (TCP loopback)
  python policy-engine-server.py --policy-dir ../policy --manifest ../policy/manifest.json --port 9100
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import socket
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("policy-engine-server")

# ---------------------------------------------------------------------------
# Self-Integrity & Platform Enforcement
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve()


def _self_integrity_check(manifest_path: Path) -> None:
    """Verify the running script matches the SHA-256 recorded in the manifest.

    This mitigates the custodian problem: if an attacker replaces the policy
    engine script, the manifest (which is itself hash-verified and signed) will
    not match the on-disk script, and the engine refuses to start.
    """
    if not manifest_path.exists():
        raise RuntimeError("Manifest not found; cannot verify self-integrity.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    self_entry = manifest.get("self_integrity", {})
    expected = self_entry.get("sha256")
    if not expected:
        logger.warning("No self_integrity hash in manifest; custodian check disabled.")
        return
    actual = hashlib.sha256(SCRIPT_PATH.read_bytes()).hexdigest()
    if not hmac.compare_digest(expected, actual):
        raise RuntimeError(
            f"Self-integrity check FAILED. Expected {expected[:16]}..., got {actual[:16]}... "
            f"The policy engine script may have been tampered with. "
            f"Reinstall from a trusted source."
        )
    logger.info("Self-integrity check passed (%s...).", actual[:16])


def _verify_wsl2_environment(unix_socket: Optional[str]) -> None:
    """Platform check for Windows deployments.

    Unix domain sockets are preferred for production because TCP loopback is
    reachable from sandbox containers (via host.docker.internal), breaking
    L0 daemon IPC isolation. Windows does not support AF_UNIX natively; only
    WSL2 provides it. For local activation, TCP fallback is permitted.
    """
    if sys.platform != "win32":
        return  # Linux/macOS — Unix sockets are native
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
            "Windows production startup blocked: WSL2 + Unix sockets required. "
            "See logs above."
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

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class Decision:
    action: str
    reason: str
    violated_rules: List[Dict[str, Any]] = field(default_factory=list)
    request_id: str = ""
    timestamp: str = ""
    policy_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "violated_rules": self.violated_rules,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "policy_version": self.policy_version,
        }


# ---------------------------------------------------------------------------
# Safe regex search (ReDoS mitigation)
# ---------------------------------------------------------------------------

def _safe_regex_search(pattern: str, text: str, timeout_ms: int = 100) -> bool:
    """Run re.search in a separate thread with a timeout. Returns False on timeout."""
    result = [None]

    def _search() -> None:
        try:
            result[0] = re.search(pattern, text) is not None
        except Exception:
            result[0] = False

    t = threading.Thread(target=_search)
    t.daemon = True
    t.start()
    t.join(timeout=timeout_ms / 1000.0)
    if t.is_alive():
        logger.warning("Regex timed out after %dms: pattern=%r text=%r", timeout_ms, pattern, text)
        return False
    return bool(result[0])


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    def __init__(self, policy_dir: str, manifest_path: str, ecosystem_version: str = "4.2.1") -> None:
        self.policy_dir = Path(policy_dir)
        self.manifest_path = Path(manifest_path)
        self.ecosystem_version = ecosystem_version
        self._rules: List[Dict[str, Any]] = []
        self._audit_log: List[Dict[str, Any]] = []
        self._policy_version = ""
        self._cache: Dict[str, Decision] = {}
        self._cache_lock = threading.Lock()
        self._rules_lock = threading.RLock()
        self._audit_log_lock = threading.Lock()
        self._cache_hits = 0
        self._cache_misses = 0

    def load_policies(self) -> None:
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        manifest_eco_version = manifest.get("ecosystem_version", manifest.get("schema_version", ""))
        if manifest_eco_version != self.ecosystem_version:
            raise RuntimeError(
                f"Version drift: manifest={manifest_eco_version}, engine={self.ecosystem_version}"
            )

        self._policy_version = manifest.get("manifest_hash", manifest.get("schema_version", ""))
        files = manifest.get("files", {})

        loaded = 0
        with self._rules_lock:
            for fname, fconfig in files.items():
                if fname == "manifest.json":
                    continue
                fpath = self.policy_dir / fname
                if not fpath.exists():
                    logger.error("Policy file referenced but missing: %s", fpath)
                    raise RuntimeError(f"Policy file missing: {fpath}")

                expected_hash = fconfig.get("sha256", "")
                if expected_hash:
                    actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
                    if actual_hash != expected_hash:
                        logger.error("SHA-256 mismatch for %s: expected=%s, actual=%s", fname, expected_hash, actual_hash)
                        raise RuntimeError(f"Policy hash mismatch: {fname}")
                    logger.debug("Hash verified for %s", fname)

                self._load_policy_file(fpath)
                loaded += 1

            logger.info("Loaded %d rules from %d policy files", len(self._rules), loaded)

    def _load_policy_file(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for rule in data.get("rules", []):
            rule["_source_file"] = path.name
            self._rules.append(rule)

    def _cache_key(self, request: Dict[str, Any]) -> str:
        # Cache key based on tool, command, and path — the most common repeated tuples
        tool = request.get("tool", "")
        command = request.get("command", "")
        path = request.get("path", "")
        return hashlib.sha256(f"{tool}:{command}:{path}".encode()).hexdigest()

    def validate(self, request: Dict[str, Any]) -> Decision:
        # Check cache first
        cache_key = self._cache_key(request)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached:
                self._cache_hits += 1
                # Return a fresh copy with updated request_id and timestamp
                return Decision(
                    action=cached.action,
                    reason=cached.reason + " (cached)",
                    violated_rules=cached.violated_rules,
                    request_id=str(uuid.uuid4()),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    policy_version=cached.policy_version,
                )
            self._cache_misses += 1

        request_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()
        matched_never = []
        matched_always = []

        with self._rules_lock:
            for rule in self._rules:
                if self._rule_matches(rule, request):
                    action = rule.get("action", "")
                    if action == "NEVER":
                        matched_never.append(rule)
                    elif action == "ALWAYS":
                        matched_always.append(rule)

        # Decision logic
        if matched_never:
            decision = Decision(
                action="BLOCK",
                reason=f"Blocked by {len(matched_never)} NEVER rule(s)",
                violated_rules=[self._rule_to_violation(r) for r in matched_never],
                request_id=request_id,
                timestamp=timestamp,
                policy_version=self._policy_version,
            )
            with self._cache_lock:
                self._cache[cache_key] = decision
            self._log_decision(decision, request)
            return decision

        if matched_always:
            # ALWAYS rules matched but we can't fully verify requirements
            # without runtime context. Return ALLOW with escalation note.
            decision = Decision(
                action="ALLOW",
                reason=f"Allowed with {len(matched_always)} ALWAYS rule(s) noted; verify requirements",
                violated_rules=[self._rule_to_violation(r) for r in matched_always],
                request_id=request_id,
                timestamp=timestamp,
                policy_version=self._policy_version,
            )
            with self._cache_lock:
                self._cache[cache_key] = decision
            self._log_decision(decision, request)
            return decision

        decision = Decision(
            action="ALLOW",
            reason="No rules triggered",
            request_id=request_id,
            timestamp=timestamp,
            policy_version=self._policy_version,
        )
        with self._cache_lock:
            self._cache[cache_key] = decision
        self._log_decision(decision, request)
        return decision

    def _rule_matches(self, rule: Dict[str, Any], request: Dict[str, Any]) -> bool:
        pattern = rule.get("pattern", {})
        tool = request.get("tool", "")
        tool_pattern = pattern.get("tool", "")

        # Check tool match
        if tool_pattern:
            if not self._match_pattern(tool, tool_pattern):
                return False

        # Check path match
        path = request.get("path", "")
        path_regex = pattern.get("path_regex", "")
        if path_regex and path:
            if not _safe_regex_search(path_regex, path):
                return False

        # Check command match
        command = request.get("command", "")
        command_regex = pattern.get("command_regex", "")
        if command_regex and command:
            if not _safe_regex_search(command_regex, command):
                return False

        # Check sandbox_network match
        sandbox_network = request.get("sandbox_network", "")
        sandbox_network_pattern = pattern.get("sandbox_network", "")
        if sandbox_network_pattern:
            if not self._match_pattern(sandbox_network, sandbox_network_pattern):
                return False

        # Check server match (with negation support)
        server = request.get("server", "")
        server_pattern = pattern.get("server", "")
        if server_pattern:
            if server_pattern.startswith("!"):
                excluded = [s.strip() for s in server_pattern[1:].split("|")]
                if server in excluded:
                    return False
            else:
                if not self._match_pattern(server, server_pattern):
                    return False

        # Check network_access match
        if "network_access" in pattern:
            if request.get("network_access") != pattern["network_access"]:
                return False

        # Check manifest_declaration match
        if "manifest_declaration" in pattern:
            if request.get("manifest_declaration") != pattern["manifest_declaration"]:
                return False

        return True

    def _match_pattern(self, value: str, pattern: str) -> bool:
        if "|" in pattern:
            return any(value == p.strip() for p in pattern.split("|"))
        return value == pattern

    def _rule_to_violation(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "rule_id": rule.get("id", "unknown"),
            "rule_type": rule.get("_source_file", "").replace(".json", ""),
            "directive": rule.get("action", ""),
            "severity": rule.get("severity", ""),
            "message": rule.get("description", ""),
        }

    def _log_decision(self, decision: Decision, request: Dict[str, Any]) -> None:
        with self._audit_log_lock:
            self._audit_log.append({
                "event_type": f"PRE_EXEC_{decision.action}",
                "timestamp": decision.timestamp,
                "request_id": decision.request_id,
                "tool": request.get("tool", ""),
                "rule_triggered": [r["rule_id"] for r in decision.violated_rules],
                "severity": "critical" if decision.action == "BLOCK" else "info",
                "action": decision.action,
                "rationale": decision.reason,
                "policy_version": decision.policy_version,
            })

    def get_audit_log(self) -> List[Dict[str, Any]]:
        with self._audit_log_lock:
            return list(self._audit_log)


# ---------------------------------------------------------------------------
# HTTP Server (stdlib only)
# ---------------------------------------------------------------------------

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
except ImportError:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


try:
    _AF_UNIX = socket.AF_UNIX

    class ThreadedUnixHTTPServer(ThreadingMixIn, HTTPServer):
        """HTTP server over Unix domain socket."""
        daemon_threads = True
        address_family = _AF_UNIX

        def server_bind(self):
            # Remove stale socket file before binding
            if isinstance(self.server_address, str) and os.path.exists(self.server_address):
                os.unlink(self.server_address)
            super().server_bind()
            # Restrict to owner only (read/write/execute for owner only)
            os.chmod(self.server_address, 0o600)

        def get_request(self):
            request, client_address = super().get_request()
            # For Unix sockets, client_address is empty; annotate for logging
            return request, ("unix", "")
except AttributeError:
    ThreadedUnixHTTPServer = None  # type: ignore


class PolicyHandler(BaseHTTPRequestHandler):
    engine: PolicyEngine = None  # type: ignore

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - " + fmt, self.client_address[0], *args)

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
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            cache_info = {}
            rules_loaded = 0
            if self.engine:
                cache_info = {
                    "hits": self.engine._cache_hits,
                    "misses": self.engine._cache_misses,
                    "size": len(self.engine._cache),
                }
                with self.engine._rules_lock:
                    rules_loaded = len(self.engine._rules)
            self._send_json(200, {
                "status": "ok",
                "policies_loaded": self.engine is not None,
                "rules_loaded": rules_loaded,
                "cache": cache_info,
            })
        elif self.path == "/audit-log":
            try:
                logs = self.engine.get_audit_log() if self.engine else []
                self._send_json(200, {"audit_log": logs})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        if self.path == "/validate":
            try:
                request = json.loads(body)
                decision = self.engine.validate(request)
                self._send_json(200, decision.to_dict())
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            except Exception as exc:
                logger.exception("Validation error")
                self._send_json(500, {"error": str(exc)})
        elif self.path == "/shutdown":
            if not self._verify_shutdown_auth():
                self._send_json(401, {"error": "Unauthorized"})
                return
            self._send_json(200, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json(404, {"error": "Not found"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Policy Engine HTTP Server")
    parser.add_argument("--policy-dir", default=str(Path(__file__).resolve().parent.parent / "policy"), help="Path to policy directory")
    parser.add_argument("--manifest", default=str(Path(__file__).resolve().parent.parent / "policy" / "manifest.json"), help="Path to manifest.json")
    parser.add_argument("--port", type=int, default=9100, help="HTTP port (dev only)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (dev only)")
    parser.add_argument("--unix-socket", default="", help="Unix domain socket path (production). Omit for TCP fallback.")
    args = parser.parse_args()

    policy_dir = Path(args.policy_dir)
    manifest_path = Path(args.manifest)

    if not policy_dir.exists():
        logger.error("Policy directory not found: %s", policy_dir)
        return 1
    if not manifest_path.exists():
        logger.error("Manifest not found: %s", manifest_path)
        return 1

    try:
        _verify_wsl2_environment(args.unix_socket)
        _self_integrity_check(manifest_path)
    except RuntimeError as exc:
        logger.error("Startup guard failed: %s", exc)
        return 1

    engine = PolicyEngine(
        policy_dir=str(policy_dir),
        manifest_path=str(manifest_path),
        ecosystem_version="4.2.1",
    )

    try:
        engine.load_policies()
    except Exception as exc:
        logger.error("Failed to load policies: %s", exc)
        return 1

    PolicyHandler.engine = engine

    if ThreadedUnixHTTPServer and args.unix_socket and args.unix_socket.lower() not in ("", "none", "tcp"):
        # Ensure parent directory exists
        socket_dir = Path(args.unix_socket).parent
        socket_dir.mkdir(parents=True, exist_ok=True)
        server = ThreadedUnixHTTPServer(args.unix_socket, PolicyHandler)
        logger.info("Policy Engine listening on unix://%s", args.unix_socket)
    else:
        server = ThreadedHTTPServer((args.host, args.port), PolicyHandler)
        logger.warning("Policy Engine listening on http://%s:%d (TCP — NOT FOR PRODUCTION)", args.host, args.port)

    logger.info("Loaded %d rules", len(engine._rules))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down.")
    finally:
        server.shutdown()
        if args.unix_socket and os.path.exists(args.unix_socket):
            os.unlink(args.unix_socket)

    return 0


if __name__ == "__main__":
    sys.exit(main())
