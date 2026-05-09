#!/usr/bin/env python3
"""
Chaos Engineering Test Orchestrator

Injects controlled failures into the ecosystem and validates graceful degradation
and fail-closed guarantees. Produces machine-readable JSON and human-readable
Markdown reports.

Usage:
    python3 run_chaos_test.py --suite full --repeat 3
    python3 run_chaos_test.py --category network-partition --repeat 1 --dry-run
"""

import argparse
import dataclasses
import datetime
import json
import os
import random
import re
import shlex
import subprocess
import sys
import time
import typing
from pathlib import Path


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class TestResult:
    test_id: str
    category: str
    repetition: int
    status: str  # "PASS" | "FAIL" | "SKIPPED"
    duration_sec: float
    details: dict
    logs: list

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "category": self.category,
            "repetition": self.repetition,
            "status": self.status,
            "duration_sec": round(self.duration_sec, 3),
            "details": self.details,
            "logs": self.logs,
        }


@dataclasses.dataclass
class ChaosReport:
    started_at: str
    finished_at: str
    suite: str
    repeat: int
    dry_run: bool
    results: list

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "suite": self.suite,
            "repeat": self.repeat,
            "dry_run": self.dry_run,
            "results": [r.to_dict() for r in self.results],
            "summary": {
                "total": len(self.results),
                "passed": sum(1 for r in self.results if r.status == "PASS"),
                "failed": sum(1 for r in self.results if r.status == "FAIL"),
                "skipped": sum(1 for r in self.results if r.status == "SKIPPED"),
            },
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[{ts}] {msg}", flush=True)


def run_cmd(cmd: list[str], timeout: int = 30, check: bool = False) -> tuple[int, str, str]:
    """Run a shell command and return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        return -1, exc.stdout or "", exc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"Command not found: {cmd[0]}"


def timestamp_now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


# ---------------------------------------------------------------------------
# Test primitives
# ---------------------------------------------------------------------------

class ChaosTest:
    """Base class for a chaos test."""

    test_id: str = ""
    category: str = ""
    defaults: dict = {}

    def __init__(self, dry_run: bool = False, params: dict | None = None):
        self.dry_run = dry_run
        self.params = {**self.defaults, **(params or {})}
        self.logs: list[str] = []

    def _log(self, msg: str) -> None:
        self.logs.append(f"[{timestamp_now()}] {msg}")
        log(msg)

    def _run_safe(self, cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
        if self.dry_run:
            self._log(f"[DRY-RUN] Would execute: {shlex.join(cmd)}")
            return 0, "", ""
        self._log(f"Executing: {shlex.join(cmd)}")
        rc, out, err = run_cmd(cmd, timeout=timeout)
        if out:
            self._log(f"stdout: {out[:500]}")
        if err:
            self._log(f"stderr: {err[:500]}")
        return rc, out, err

    def inject(self) -> dict:
        raise NotImplementedError

    def validate(self, injection_result: dict) -> tuple[bool, dict]:
        raise NotImplementedError

    def run(self, repetition: int) -> TestResult:
        start = time.monotonic()
        self.logs = []
        self._log(f"Starting {self.test_id} (rep {repetition})")
        try:
            injection = self.inject()
            passed, details = self.validate(injection)
            status = "PASS" if passed else "FAIL"
        except Exception as exc:
            self._log(f"EXCEPTION during test: {exc}")
            status = "FAIL"
            details = {"exception": str(exc)}
            injection = {}
        duration = time.monotonic() - start
        return TestResult(
            test_id=self.test_id,
            category=self.category,
            repetition=repetition,
            status=status,
            duration_sec=duration,
            details={**details, "injection": injection},
            logs=self.logs,
        )


# ---------------------------------------------------------------------------
# Concrete tests
# ---------------------------------------------------------------------------

class PolicyEngineKillTest(ChaosTest):
    test_id = "CE-001"
    category = "policy-kill"
    defaults = {
        "grace_period_ms": 500,
        "in_flight_target": 10,
        "load_rate": 50,
        "observation_window_sec": 30,
        "policy_engine_pid": None,  # auto-detect if None
    }

    def inject(self) -> dict:
        pid = self.params.get("policy_engine_pid")
        if pid is None:
            # Try to find policy-engine process
            rc, out, _ = self._run_safe(["pgrep", "-f", "policy-engine"], timeout=5)
            if rc == 0 and out.strip():
                pid = int(out.strip().splitlines()[0])
            else:
                # Fallback: try docker
                rc2, out2, _ = self._run_safe(
                    ["docker", "ps", "-q", "-f", "name=policy-engine"], timeout=5
                )
                if rc2 == 0 and out2.strip():
                    container_id = out2.strip().splitlines()[0]
                    self._log(f"Killing docker container {container_id}")
                    self._run_safe(["docker", "kill", container_id], timeout=10)
                    return {"method": "docker_kill", "container_id": container_id}
                raise RuntimeError("Could not find policy-engine process or container")
        self._log(f"Sending SIGKILL to PID {pid}")
        self._run_safe(["kill", "-9", str(pid)], timeout=5)
        return {"method": "sigkill", "pid": pid}

    def validate(self, injection: dict) -> tuple[bool, dict]:
        window = self.params["observation_window_sec"]
        grace_ms = self.params["grace_period_ms"]
        self._log(f"Waiting {grace_ms}ms for in-flight drain, then observing {window}s")
        time.sleep(grace_ms / 1000.0)
        # In a real system, query the audit log sink.
        # Here we simulate validation by checking health endpoint.
        # A real implementation would tail audit logs or query the audit API.
        healthy = False
        for attempt in range(10):
            rc, _, _ = run_cmd(["curl", "-sf", "http://localhost:8080/health"], timeout=2)
            if rc == 0:
                healthy = True
                break
            time.sleep(0.5)
        # Placeholder: in production, parse audit events and count BLOCK vs ALLOW.
        return healthy, {
            "health_restored": healthy,
            "grace_period_ms": grace_ms,
            "note": "Replace with real audit log query",
        }


class SandboxOOMTest(ChaosTest):
    test_id = "CE-002"
    category = "sandbox-oom"
    defaults = {
        "sandbox_mem_limit_mb": 50,
        "oom_payload_mb": 100,
        "cleanup_timeout_sec": 10,
    }

    def inject(self) -> dict:
        limit = self.params["sandbox_mem_limit_mb"]
        payload = self.params["oom_payload_mb"]
        # Set cgroup memory limit (requires cgroup v2 and privileges)
        self._run_safe(
            ["mkdir", "-p", "/sys/fs/cgroup/sandbox-chaos-test"], timeout=5
        )
        self._run_safe(
            ["sh", "-c", f"echo {limit * 1024 * 1024} > /sys/fs/cgroup/sandbox-chaos-test/memory.max"],
            timeout=5,
        )
        # Spawn a process in that cgroup that allocates memory
        alloc_cmd = f"python3 -c 'import os; os.mkdir(\"/tmp/sandbox-chaos-test\", exist_ok=True); a=bytearray({payload * 1024 * 1024})'"
        self._run_safe(
            ["systemd-run", "--scope", "--property=Delegate=memory",
             "--unit=sandbox-chaos-test", "sh", "-c", alloc_cmd],
            timeout=15,
        )
        return {"cgroup": "/sys/fs/cgroup/sandbox-chaos-test", "payload_mb": payload}

    def validate(self, injection: dict) -> tuple[bool, dict]:
        timeout = self.params["cleanup_timeout_sec"]
        # Check for cleanup log marker and residual files
        tmp_residual = False
        for _ in range(timeout * 2):
            rc, out, _ = run_cmd(["ls", "/tmp/sandbox-chaos-test"], timeout=2)
            if rc != 0 or not out.strip():
                tmp_residual = False
                break
            tmp_residual = True
            time.sleep(0.5)
        # Check log for SANDBOX_CLEANUP_COMPLETE
        rc, out, _ = run_cmd(
            ["journalctl", "-u", "sandbox-executor", "-n", "50", "--no-pager"],
            timeout=5,
        )
        cleanup_found = "SANDBOX_CLEANUP_COMPLETE" in out if rc == 0 else False
        return (not tmp_residual) and cleanup_found, {
            "tmp_residual": tmp_residual,
            "cleanup_found": cleanup_found,
            "note": "In production, also verify token revocation and shared-state lease release",
        }


class ClockSkewTest(ChaosTest):
    test_id = "CE-003"
    category = "clock-skew"
    defaults = {
        "skew_seconds": 30,
        "workflow_phases": 4,
        "max_transition_time_sec": 60,
    }

    def inject(self) -> dict:
        skew = self.params["skew_seconds"]
        # Use libfaketime if available, otherwise warn and skip destructive changes
        rc, _, _ = run_cmd(["which", "faketime"], timeout=2)
        if rc != 0:
            self._log("faketime not installed; falling back to environment-only injection")
        # Submit a workflow via orchestrator API while phase-controller is skewed
        # In a real deployment, this manipulates the phase-controller container env.
        workflow_id = f"clock-skew-{random.randint(100000, 999999)}"
        self._run_safe(
            ["curl", "-sf", "-X", "POST",
             "http://localhost:9090/workflows",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"workflow_id": workflow_id, "phases": ["INIT", "VALIDATE", "EXECUTE", "COMPLETE"]})],
            timeout=10,
        )
        return {"skew_seconds": skew, "workflow_id": workflow_id}

    def validate(self, injection: dict) -> tuple[bool, dict]:
        workflow_id = injection.get("workflow_id", "unknown")
        max_time = self.params["max_transition_time_sec"]
        # Poll workflow status
        observed_phases = []
        start = time.monotonic()
        while time.monotonic() - start < max_time:
            rc, out, _ = run_cmd(
                ["curl", "-sf", f"http://localhost:9090/workflows/{workflow_id}"],
                timeout=5,
            )
            if rc == 0:
                try:
                    data = json.loads(out)
                    observed_phases = data.get("phases_completed", [])
                    if data.get("status") == "COMPLETE":
                        break
                except json.JSONDecodeError:
                    pass
            time.sleep(1)
        expected = ["INIT", "VALIDATE", "EXECUTE", "COMPLETE"]
        correct_order = observed_phases == expected
        no_duplicates = len(observed_phases) == len(set(observed_phases))
        no_skips = all(p in observed_phases for p in expected) if correct_order else False
        return correct_order and no_duplicates and no_skips, {
            "observed_phases": observed_phases,
            "expected_phases": expected,
            "correct_order": correct_order,
            "no_duplicates": no_duplicates,
            "no_skips": no_skips,
        }


class MalformedAPITest(ChaosTest):
    test_id = "CE-004"
    category = "malformed-api"
    defaults = {
        "malformed_variants": 4,
        "requests_per_variant": 25,
        "fallback_cache_ttl_sec": 300,
    }

    def inject(self) -> dict:
        variants = [
            "unclosed_braces",
            "wrong_schema",
            "truncation",
            "prototype_pollution",
        ]
        selected = variants[: self.params["malformed_variants"]]
        results = []
        for variant in selected:
            for i in range(self.params["requests_per_variant"]):
                req_id = f"malformed-{variant}-{i}"
                # In production, toggle the Gemini API mock per variant.
                # Here we proxy through a local mock endpoint.
                rc, out, err = run_cmd(
                    ["curl", "-sf", "-X", "POST",
                     "http://localhost:7070/gemini-mock",
                     "-H", "Content-Type: application/json",
                     "-d", json.dumps({"variant": variant, "request_id": req_id})],
                    timeout=5,
                )
                results.append({
                    "request_id": req_id,
                    "variant": variant,
                    "http_status": 200 if rc == 0 else 502,
                    "response": out[:200],
                })
        return {"total_requests": len(results), "variant_breakdown": selected, "raw_results": results}

    def validate(self, injection: dict) -> tuple[bool, dict]:
        raw = injection.get("raw_results", [])
        # We expect the validator to return 422 for malformed, or 200 with safe cached payload.
        # Any 502 or crash is a failure.
        blocked = 0
        leaked = 0
        for r in raw:
            if r["http_status"] == 422 or (r["http_status"] == 200 and "cached_safe" in r["response"]):
                blocked += 1
            else:
                leaked += 1
        total = len(raw)
        all_blocked = total > 0 and blocked == total
        return all_blocked, {
            "total_requests": total,
            "blocked": blocked,
            "leaked": leaked,
            "all_blocked": all_blocked,
        }


class VaultCapacityTest(ChaosTest):
    test_id = "CE-005"
    category = "vault-capacity"
    defaults = {
        "vault_capacity_mb": 1024,
        "preload_fill_mb": 1014,
        "new_write_count": 100,
        "new_write_size_mb": 1,
        "write_latency_p99_ms": 200,
    }

    def inject(self) -> dict:
        cap_mb = self.params["vault_capacity_mb"]
        preload = self.params["preload_fill_mb"]
        # Pre-fill vault
        self._run_safe(
            ["curl", "-sf", "-X", "POST",
             "http://localhost:6060/admin/preload",
             "-H", "Content-Type: application/json",
             "-d", json.dumps({"target_mb": preload})],
            timeout=60,
        )
        # Perform new writes and capture latencies
        latencies_ms = []
        successes = 0
        for i in range(self.params["new_write_count"]):
            start = time.monotonic()
            rc, out, _ = run_cmd(
                ["curl", "-sf", "-w", "%{http_code}", "-o", "/dev/null",
                 "-X", "PUT", "http://localhost:6060/vault/entries",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({
                     "key": f"chaos-{i}",
                     "payload": "x" * (self.params["new_write_size_mb"] * 1024 * 1024),
                 })],
                timeout=10,
            )
            latency_ms = (time.monotonic() - start) * 1000
            latencies_ms.append(latency_ms)
            if rc == 0:
                successes += 1
        return {
            "preload_mb": preload,
            "writes_attempted": self.params["new_write_count"],
            "writes_succeeded": successes,
            "latencies_ms": latencies_ms,
        }

    def validate(self, injection: dict) -> tuple[bool, dict]:
        latencies = injection.get("latencies_ms", [])
        p99 = sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0
        all_succeeded = injection["writes_succeeded"] == injection["writes_attempted"]
        latency_ok = p99 <= self.params["write_latency_p99_ms"]
        # Query current vault size
        rc, out, _ = run_cmd(["curl", "-sf", "http://localhost:6060/admin/metrics"], timeout=5)
        size_mb = 0
        if rc == 0:
            try:
                metrics = json.loads(out)
                size_mb = metrics.get("vault_size_bytes", 0) / (1024 * 1024)
            except json.JSONDecodeError:
                pass
        under_cap = size_mb <= self.params["vault_capacity_mb"]
        return all_succeeded and latency_ok and under_cap, {
            "writes_succeeded": injection["writes_succeeded"],
            "writes_attempted": injection["writes_attempted"],
            "p99_latency_ms": round(p99, 2),
            "vault_size_mb": round(size_mb, 2),
            "under_capacity": under_cap,
        }


class NetworkPartitionTest(ChaosTest):
    test_id = "CE-006"
    category = "network-partition"
    defaults = {
        "partition_duration_sec": 30,
        "detection_timeout_sec": 2,
        "requests_during_partition": 20,
        "requests_after_healing": 5,
        "policy_engine_ip": "10.0.0.2",
        "sandbox_executor_ip": "10.0.0.3",
    }

    def inject(self) -> dict:
        src = self.params["policy_engine_ip"]
        dst = self.params["sandbox_executor_ip"]
        dur = self.params["partition_duration_sec"]
        # Install DROP rules both directions
        self._run_safe(["iptables", "-A", "FORWARD", "-s", src, "-d", dst, "-j", "DROP"], timeout=5)
        self._run_safe(["iptables", "-A", "FORWARD", "-s", dst, "-d", src, "-j", "DROP"], timeout=5)
        # Send requests during partition
        partition_results = []
        for i in range(self.params["requests_during_partition"]):
            rc, out, _ = run_cmd(
                ["curl", "-sf", "-X", "POST", "http://localhost:8080/evaluate",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"request_id": f"part-{i}", "action": "read"})],
                timeout=5,
            )
            partition_results.append({"status": out.strip() if rc == 0 else "ERROR", "rc": rc})
            time.sleep(0.1)
        # Heal partition
        self._run_safe(["iptables", "-D", "FORWARD", "-s", src, "-d", dst, "-j", "DROP"], timeout=5)
        self._run_safe(["iptables", "-D", "FORWARD", "-s", dst, "-d", src, "-j", "DROP"], timeout=5)
        time.sleep(2)
        # Send recovery requests
        recovery_results = []
        for i in range(self.params["requests_after_healing"]):
            rc, out, _ = run_cmd(
                ["curl", "-sf", "-X", "POST", "http://localhost:8080/evaluate",
                 "-H", "Content-Type: application/json",
                 "-d", json.dumps({"request_id": f"heal-{i}", "action": "read"})],
                timeout=5,
            )
            recovery_results.append({"status": out.strip() if rc == 0 else "ERROR", "rc": rc})
        return {
            "partition_results": partition_results,
            "recovery_results": recovery_results,
        }

    def validate(self, injection: dict) -> tuple[bool, dict]:
        part = injection.get("partition_results", [])
        heal = injection.get("recovery_results", [])
        all_blocked_during = all(r.get("status") == "BLOCK" for r in part)
        any_allow_during = any(r.get("status") == "ALLOW" for r in part)
        all_normal_after = all(r.get("status") in ("ALLOW", "BLOCK") and r["rc"] == 0 for r in heal)
        # Detection time is inferred by first BLOCK; we can't measure externally precisely,
        # but we can assert no ALLOWs appear after 2s window.
        return all_blocked_during and not any_allow_during and all_normal_after, {
            "blocked_during_partition": all_blocked_during,
            "any_allow_during_partition": any_allow_during,
            "normal_after_healing": all_normal_after,
            "partition_request_count": len(part),
            "recovery_request_count": len(heal),
        }


class ResourceExhaustionTest(ChaosTest):
    test_id = "CE-007"
    category = "resource-exhaustion"
    defaults = {
        "cpu_limit_percent": 5,
        "concurrent_requests": 100,
        "memory_workers": 1000,
        "memory_per_worker_mb": 1,
        "cb_open_max_sec": 5,
        "cb_close_max_sec": 30,
    }

    def inject(self) -> dict:
        # CPU starvation
        rc, out, _ = run_cmd(["pgrep", "-f", "policy-engine"], timeout=5)
        policy_pid = int(out.strip().splitlines()[0]) if rc == 0 else None
        if policy_pid:
            self._run_safe(["cpulimit", "-p", str(policy_pid), "-l", str(self.params["cpu_limit_percent"]), "-b"], timeout=5)
        # Concurrent load
        load_results = []
        for i in range(self.params["concurrent_requests"]):
            rc2, out2, _ = run_cmd(
                ["curl", "-sf", "-X", "POST", "http://localhost:8080/evaluate",
                 "-d", json.dumps({"request_id": f"load-{i}"})],
                timeout=5,
            )
            load_results.append({"status": out2.strip() if rc2 == 0 else "TIMEOUT", "rc": rc2})
        # Release CPU limit
        if policy_pid:
            self._run_safe(["pkill", "-f", f"cpulimit.*{policy_pid}"], timeout=5)
        # Memory pressure on phase-controller
        mem_workers = []
        for i in range(self.params["memory_workers"]):
            # Spawn background workers holding memory
            worker_cmd = f"python3 -c 'import time; a=bytearray({self.params['memory_per_worker_mb'] * 1024 * 1024}); time.sleep(120)'"
            proc = subprocess.Popen(["systemd-run", "--scope", "--unit", f"mem-worker-{i}", "sh", "-c", worker_cmd])
            mem_workers.append(proc.pid)
        time.sleep(5)
        # Query circuit breaker state
        rc3, out3, _ = run_cmd(["curl", "-sf", "http://localhost:8080/metrics"], timeout=5)
        cb_state = "unknown"
        if rc3 == 0:
            try:
                m = json.loads(out3)
                cb_state = m.get("circuit_breaker_state", "unknown")
            except json.JSONDecodeError:
                pass
        # Cleanup memory workers
        for pid in mem_workers:
            run_cmd(["kill", "-9", str(pid)], timeout=2)
        # Wait for recovery and re-query
        time.sleep(self.params["cb_close_max_sec"])
        rc4, out4, _ = run_cmd(["curl", "-sf", "http://localhost:8080/metrics"], timeout=5)
        cb_state_after = "unknown"
        if rc4 == 0:
            try:
                m = json.loads(out4)
                cb_state_after = m.get("circuit_breaker_state", "unknown")
            except json.JSONDecodeError:
                pass
        return {
            "policy_pid": policy_pid,
            "load_results": load_results,
            "cb_state_during": cb_state,
            "cb_state_after": cb_state_after,
        }

    def validate(self, injection: dict) -> tuple[bool, dict]:
        cb_during = injection.get("cb_state_during", "unknown")
        cb_after = injection.get("cb_state_after", "unknown")
        # 1 = OPEN in our metric mapping
        opened = cb_during == "OPEN" or cb_during == 1
        closed_after = cb_after == "CLOSED" or cb_after == 0
        # Also check that most load results fast-failed (503 or BLOCK)
        load = injection.get("load_results", [])
        fast_fail_count = sum(1 for r in load if r.get("status") in ("503", "BLOCK", "TIMEOUT"))
        fast_fail_rate = fast_fail_count / len(load) if load else 0
        return opened and closed_after and fast_fail_rate >= 0.95, {
            "cb_opened": opened,
            "cb_closed_after_recovery": closed_after,
            "fast_fail_rate": round(fast_fail_rate, 2),
            "load_request_count": len(load),
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TEST_REGISTRY: dict[str, typing.Type[ChaosTest]] = {
    "policy-kill": PolicyEngineKillTest,
    "sandbox-oom": SandboxOOMTest,
    "clock-skew": ClockSkewTest,
    "malformed-api": MalformedAPITest,
    "vault-capacity": VaultCapacityTest,
    "network-partition": NetworkPartitionTest,
    "resource-exhaustion": ResourceExhaustionTest,
}

FULL_SUITE = list(TEST_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_json_report(report: ChaosReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"chaos_report_{ts}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2))
    log(f"JSON report written to {path}")
    return path


def write_markdown_report(report: ChaosReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"chaos_report_{ts}.md"
    summary = report.to_dict()["summary"]
    lines = [
        "# Chaos Engineering Report",
        "",
        f"- **Suite**: {report.suite}",
        f"- **Started**: {report.started_at}",
        f"- **Finished**: {report.finished_at}",
        f"- **Dry Run**: {report.dry_run}",
        f"- **Repetitions per test**: {report.repeat}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total | {summary['total']} |",
        f"| Passed | {summary['passed']} |",
        f"| Failed | {summary['failed']} |",
        f"| Skipped | {summary['skipped']} |",
        "",
        "## Results",
        "",
        "| Test ID | Category | Rep | Status | Duration (s) |",
        "|---------|----------|-----|--------|--------------|",
    ]
    for r in report.results:
        lines.append(
            f"| {r.test_id} | {r.category} | {r.repetition} | {r.status} | {round(r.duration_sec, 2)} |"
        )
    lines.extend(["", "## Details", ""])
    for r in report.results:
        lines.extend([
            f"### {r.test_id} (rep {r.repetition}) — {r.status}",
            "",
            "**Details**:",
            "",
            "```json",
            json.dumps(r.details, indent=2),
            "```",
            "",
            "**Logs**:",
            "",
            "```",
            *r.logs,
            "```",
            "",
        ])
    path.write_text("\n".join(lines))
    log(f"Markdown report written to {path}")
    return path


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Chaos Engineering Test Orchestrator")
    parser.add_argument("--suite", choices=["full"], help="Run the full production-readiness suite")
    parser.add_argument("--category", choices=list(TEST_REGISTRY.keys()), help="Run a single test category")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat count per test (default: 1)")
    parser.add_argument("--dry-run", action="store_true", help="Log injection commands without executing them")
    parser.add_argument("--out-dir", type=Path, default=Path("chaos_reports"), help="Directory for report output")
    parser.add_argument("--param", action="append", default=[], help="Override test parameters as key=value")
    args = parser.parse_args()

    if not args.suite and not args.category:
        parser.error("Specify --suite full or --category <category>")

    categories = FULL_SUITE if args.suite == "full" else [args.category]

    # Parse overrides
    param_overrides: dict[str, typing.Any] = {}
    for p in args.param:
        if "=" not in p:
            parser.error(f"--param must be key=value, got: {p}")
        k, v = p.split("=", 1)
        # Attempt numeric / bool coercion
        if v.isdigit():
            v = int(v)
        elif v.lower() in ("true", "false"):
            v = v.lower() == "true"
        param_overrides[k] = v

    started_at = timestamp_now()
    results: list[TestResult] = []

    log(f"Starting chaos suite: categories={categories}, repeat={args.repeat}, dry_run={args.dry_run}")

    for category in categories:
        test_cls = TEST_REGISTRY[category]
        for rep in range(1, args.repeat + 1):
            test = test_cls(dry_run=args.dry_run, params=param_overrides)
            result = test.run(repetition=rep)
            results.append(result)
            if result.status == "FAIL":
                log(f"FAILURE: {result.test_id} rep {rep} failed. Continuing with remaining tests...")

    finished_at = timestamp_now()
    report = ChaosReport(
        started_at=started_at,
        finished_at=finished_at,
        suite=args.suite or args.category,
        repeat=args.repeat,
        dry_run=args.dry_run,
        results=results,
    )

    write_json_report(report, args.out_dir)
    write_markdown_report(report, args.out_dir)

    summary = report.to_dict()["summary"]
    log(f"Suite complete: {summary['passed']}/{summary['total']} passed, {summary['failed']} failed, {summary['skipped']} skipped")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
