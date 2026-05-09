#!/usr/bin/env python3
"""test_ecosystem_active.py — Integration test for full ecosystem activation.

Validates that all L0 enforcement-layer daemons start, communicate, and enforce
their respective guarantees. This is the "smoke test" for ecosystem activation.

Usage:
    pytest tests/test_ecosystem_active.py -v
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

KIMI_HOME = Path.home() / ".kimi"
POLICY_DIR = KIMI_HOME / "policy"
MANIFEST = POLICY_DIR / "manifest.json"
STATE_DIR = KIMI_HOME / "state"

# Ports for test isolation
POLICY_PORT = 19200
PHASE_PORT = 19201
GATEWAY_PORT = 19202


class Daemons:
    """Context manager for starting/stopping core daemons."""

    def __init__(self):
        self.procs = []

    def start(self):
        # Policy Engine
        pe = subprocess.Popen(
            [
                sys.executable,
                str(KIMI_HOME / "skills" / "policy-engine" / "scripts" / "policy-engine-server.py"),
                "--policy-dir", str(POLICY_DIR),
                "--manifest", str(MANIFEST),
                "--port", str(POLICY_PORT),
                "--host", "127.0.0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.procs.append(("policy-engine", pe))
        _wait_for_health(f"http://127.0.0.1:{POLICY_PORT}/health", "policy-engine")

        # Phase Controller
        pc = subprocess.Popen(
            [
                sys.executable,
                str(KIMI_HOME / "skills" / "phase-controller" / "scripts" / "phase-controller-server.py"),
                "--state-dir", str(STATE_DIR),
                "--port", str(PHASE_PORT),
                "--host", "127.0.0.1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.procs.append(("phase-controller", pc))
        _wait_for_health(f"http://127.0.0.1:{PHASE_PORT}/health", "phase-controller")

        # Gateway
        gw = subprocess.Popen(
            [
                sys.executable,
                str(KIMI_HOME / "skills" / "tool-execution-gateway" / "scripts" / "gateway-server.py"),
                "--port", str(GATEWAY_PORT),
                "--host", "127.0.0.1",
                "--policy-endpoint", f"http://127.0.0.1:{POLICY_PORT}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.procs.append(("gateway", gw))
        _wait_for_health(f"http://127.0.0.1:{GATEWAY_PORT}/health", "gateway")

    def stop(self):
        for name, proc in self.procs:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
        return False


def _wait_for_health(url, name, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return json.loads(resp.read())
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{name} did not become healthy within {timeout}s")


def _post_json(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPolicyEngine:
    def test_health(self, daemons):
        health = _wait_for_health(f"http://127.0.0.1:{POLICY_PORT}/health", "policy-engine")
        assert health["status"] == "ok"
        assert health["policies_loaded"] is True
        assert health["rules_loaded"] == 148

    def test_validate_returns_structured_response(self, daemons):
        """Policy engine returns structured ALLOW/BLOCK decisions."""
        result = _post_json(
            f"http://127.0.0.1:{POLICY_PORT}/validate",
            {
                "tool": "read_file",
                "arguments": {"path": "README.md"},
                "context": {"phase": "EXECUTE", "skill": "code-tester"},
            },
        )
        assert "action" in result
        assert result["action"] in ("ALLOW", "BLOCK")
        assert "reason" in result
        if result["action"] == "BLOCK":
            assert "violated_rules" in result
            assert len(result["violated_rules"]) > 0

    def test_validate_block_secrets(self, daemons):
        """Writing a secret to a file should be BLOCKED."""
        result = _post_json(
            f"http://127.0.0.1:{POLICY_PORT}/validate",
            {
                "tool": "write_file",
                "arguments": {"path": ".env", "content": "API_KEY=sk-12345"},
                "context": {"phase": "EXECUTE", "skill": "dev-code-generator"},
            },
        )
        assert result["action"] == "BLOCK"
        assert any("secret" in r.get("message", "").lower() for r in result.get("violated_rules", []))


class TestPhaseController:
    def test_health(self, daemons):
        health = _wait_for_health(f"http://127.0.0.1:{PHASE_PORT}/health", "phase-controller")
        assert health["status"] == "ok"
        assert health["current_phase"] == "INGEST"

    def test_phase_transition_enforced(self, daemons):
        """Phase controller evaluates transitions and returns structured results."""
        try:
            result = _post_json(
                f"http://127.0.0.1:{PHASE_PORT}/transition",
                {
                    "target_phase": "UNDERSTAND",
                    "artifact_refs": ["a" * 64],
                    "reason": "test",
                },
            )
            # If approved, verify structure
            assert "status" in result
        except urllib.error.HTTPError as e:
            # Rejected transitions return 403 with structured error
            assert e.code == 403
            body = json.loads(e.read().decode("utf-8"))
            assert "error" in body or "status" in body

    def test_invalid_backward_transition_rejected(self, daemons):
        """Backward transitions are rejected with HTTP 403."""
        # Try backward directly (should fail from INGEST state)
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _post_json(
                f"http://127.0.0.1:{PHASE_PORT}/transition",
                {
                    "target_phase": "INGEST",
                    "artifact_refs": ["c" * 64],
                    "reason": "test",
                },
            )
        assert exc_info.value.code == 403


class TestGateway:
    def test_health(self, daemons):
        health = _wait_for_health(f"http://127.0.0.1:{GATEWAY_PORT}/health", "gateway")
        assert health["status"] == "ok"
        assert health["gateway"] == "active"

    def test_tool_call_interception(self, daemons):
        """Gateway intercepts tool calls and enriches with policy decisions."""
        try:
            result = _post_json(
                f"http://127.0.0.1:{GATEWAY_PORT}/execute",
                {
                    "tool": "read_file",
                    "arguments": {"path": "README.md"},
                    "context": {"phase": "EXECUTE", "skill": "code-tester"},
                },
            )
            # If allowed, check policy enrichment
            assert "policy" in result or "policy_decision" in result
        except urllib.error.HTTPError as e:
            # Blocked requests return 403 with policy context
            assert e.code == 403
            body = json.loads(e.read().decode("utf-8"))
            assert "decision" in body or "error" in body or "gate_failed" in body


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def daemons():
    with Daemons() as d:
        yield d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
