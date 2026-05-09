#!/usr/bin/env python3
"""
phase-controller-server.py — HTTP wrapper for PhaseStateMachine
Kimi AI Engineering Skills Ecosystem v4.2.1

Endpoints:
  POST /initialize        → Initialize state machine (fresh or resume)
  POST /transition        → Request a phase transition
  POST /force-escalation  → Human override for transition
  GET  /state             → Get current phase state
  GET  /health            → Health check
  POST /shutdown          → Graceful shutdown

Transport:
  Default: Unix domain socket (unix://C:/Users/Me/.kimi/run/phase-controller.sock)
  Fallback: TCP loopback (http://127.0.0.1:9101) — use only in dev

Usage:
  # Production (Unix socket)
  python phase-controller-server.py --state-dir ~/.kimi/state --unix-socket C:/Users/Me/.kimi/run/phase-controller.sock

  # Development (TCP loopback)
  python phase-controller-server.py --state-dir ~/.kimi/state --port 9101
"""

from __future__ import annotations

import argparse
import hmac
import hashlib
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

# Load phase-controller.py dynamically
_SCRIPT_DIR = Path(__file__).resolve().parent
_phase_controller_path = _SCRIPT_DIR / "phase-controller.py"

import importlib.util
_spec = importlib.util.spec_from_file_location("phase_controller", str(_phase_controller_path))
_phase_controller_mod = importlib.util.module_from_spec(_spec)
sys.modules["phase_controller"] = _phase_controller_mod
_spec.loader.exec_module(_phase_controller_mod)  # type: ignore

PhaseStateMachine = _phase_controller_mod.PhaseStateMachine
Phase = _phase_controller_mod.Phase
ArtifactRef = _phase_controller_mod.ArtifactRef

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("phase-controller-server")

# ---------------------------------------------------------------------------
# HTTP Server
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
            # Restrict to owner only
            os.chmod(self.server_address, 0o600)

        def get_request(self):
            request, client_address = super().get_request()
            # For Unix sockets, client_address is empty; annotate for logging
            return request, ("unix", "")
except AttributeError:
    ThreadedUnixHTTPServer = None  # type: ignore


class PhaseHandler(BaseHTTPRequestHandler):
    sm: PhaseStateMachine = None  # type: ignore

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - " + fmt, self.client_address[0], *args)

    def _send_json(self, status: int, data: Dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))

    def _read_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(body)

    def _require_auth(self) -> bool:
        secret = os.environ.get("KIMI_PHASE_SECRET") or os.environ.get("KIMI_L0_SECRET")
        if not secret:
            self._send_json(401, {"error": "Authentication required: secret not configured"})
            return False

        timestamp_str = self.headers.get("X-Kimi-Timestamp")
        signature = self.headers.get("X-Kimi-Signature")
        if not timestamp_str or not signature:
            self._send_json(401, {"error": "Missing authentication headers"})
            return False

        try:
            timestamp = int(timestamp_str)
        except ValueError:
            self._send_json(401, {"error": "Invalid timestamp"})
            return False

        now = int(time.time())
        if abs(now - timestamp) > 60:
            self._send_json(401, {"error": "Timestamp expired"})
            return False

        expected = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp_str}{self.path}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            self._send_json(401, {"error": "Invalid signature"})
            return False

        return True

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            state = self.sm.get_state() if self.sm else None
            self._send_json(200, {
                "status": "ok",
                "initialized": state is not None,
                "current_phase": state["current_phase"] if state else None,
            })
        elif self.path == "/state":
            try:
                if self.sm is None:
                    self._send_json(503, {"error": "State machine not initialized"})
                    return
                self._send_json(200, self.sm.get_state())
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_body()
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return

        if self.path == "/initialize":
            try:
                resume = body.get("resume", True)
                state = self.sm.initialize(resume_from_disk=resume)
                self._send_json(200, {"status": "initialized", "current_phase": state.current_phase.name})
            except Exception as exc:
                logger.exception("Initialize error")
                self._send_json(500, {"error": str(exc)})

        elif self.path == "/transition":
            try:
                target = body.get("target_phase", "")
                artifacts = body.get("artifacts", [])
                reason = body.get("reason", None)
                if not target:
                    self._send_json(400, {"error": "Missing target_phase"})
                    return
                target_phase = Phase[target]
                artifact_refs = [ArtifactRef(a["file"], a["sha256"]) for a in artifacts]
                result = self.sm.request_transition(target_phase, artifact_refs, reason=reason)
                self._send_json(200 if result["status"] == "APPROVED" else 403, result)
            except KeyError as exc:
                self._send_json(400, {"error": f"Invalid phase: {exc}"})
            except Exception as exc:
                logger.exception("Transition error")
                self._send_json(500, {"error": str(exc)})

        elif self.path == "/force-escalation":
            if not self._require_auth():
                return
            try:
                target = body.get("target_phase", "")
                ticket = body.get("human_ticket", "")
                justification = body.get("justification", "")
                authorized_by = body.get("authorized_by", "")
                if not all([target, ticket, justification, authorized_by]):
                    self._send_json(400, {"error": "Missing required fields"})
                    return
                target_phase = Phase[target]
                result = self.sm.force_escalation(target_phase, ticket, justification, authorized_by)
                self._send_json(200, result)
            except Exception as exc:
                logger.exception("Force escalation error")
                self._send_json(500, {"error": str(exc)})

        elif self.path == "/force-reset":
            if not self._require_auth():
                return
            try:
                reason = body.get("reason", "")
                authorized_by = body.get("authorized_by", "")
                if not reason:
                    self._send_json(400, {"error": "Missing reason"})
                    return
                # Reset state to INGEST with a forced recovery marker
                self.sm._state.current_phase = Phase.INGEST
                self.sm._state.completed_phases = []
                self.sm._state.artifacts = []
                self.sm._persist_state()
                self.sm._append_audit(f"FORCED_RECOVERY: state reset to INGEST by {authorized_by}: {reason}")
                self._send_json(200, {"status": "reset", "current_phase": "INGEST", "reason": reason})
            except Exception as exc:
                logger.exception("Force reset error")
                self._send_json(500, {"error": str(exc)})

        elif self.path == "/shutdown":
            if not self._require_auth():
                return
            self._send_json(200, {"status": "shutting_down"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json(404, {"error": "Not found"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Phase Controller HTTP Server")
    parser.add_argument("--state-dir", default=str(Path.home() / ".kimi" / "state"), help="Directory for state files")
    parser.add_argument("--port", type=int, default=9101, help="HTTP port (dev only)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (dev only)")
    parser.add_argument("--unix-socket", default=str(Path.home() / ".kimi" / "run" / "phase-controller.sock"), help="Unix domain socket path (production)")
    parser.add_argument("--force-reset", action="store_true", help="Force reset to INGEST on startup if state is corrupted")
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    sm = PhaseStateMachine(
        state_path=str(state_dir / "phase-state.json"),
        audit_log_path=str(state_dir / "phase-audit.log"),
    )

    # Auto-initialize on startup
    try:
        sm.initialize(resume_from_disk=True)
        logger.info("Phase controller initialized at phase %s", sm.get_state()["current_phase"])
    except Exception as exc:
        if args.force_reset:
            logger.warning("State corrupted (%s) — forcing reset to INGEST per --force-reset", exc)
            sm._state.current_phase = Phase.INGEST
            sm._state.completed_phases = []
            sm._state.artifacts = []
            sm._persist_state()
            sm._append_audit("FORCED_RECOVERY: state reset to INGEST due to corruption (--force-reset)")
            logger.info("Phase controller forced reset to INGEST")
        else:
            logger.warning("State corrupted (%s) — starting fresh. Use --force-reset to recover with audit trail.", exc)
            sm.initialize(resume_from_disk=False)
            logger.info("Phase controller fresh start at phase INGEST")

    PhaseHandler.sm = sm

    if ThreadedUnixHTTPServer and args.unix_socket and args.unix_socket.lower() not in ("", "none", "tcp"):
        # Ensure parent directory exists
        socket_dir = Path(args.unix_socket).parent
        socket_dir.mkdir(parents=True, exist_ok=True)
        server = ThreadedUnixHTTPServer(args.unix_socket, PhaseHandler)
        logger.info("Phase Controller listening on unix://%s", args.unix_socket)
    else:
        server = ThreadedHTTPServer((args.host, args.port), PhaseHandler)
        logger.warning("Phase Controller listening on http://%s:%d (TCP — NOT FOR PRODUCTION)", args.host, args.port)

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
