#!/usr/bin/env python3
"""
run-chaos.py — Resilience Experiment Runner Template

Defines, executes, and validates chaos experiments with configurable fault injection.
Intended for staging/isolated environments ONLY. See safety checks below.

Usage:
    python run-chaos.py --config experiment.yaml --env staging

Exit codes:
    0 — All experiments passed
    1 — One or more experiments failed
    2 — Safety check blocked execution
    3 — Runtime / emergency stop error
"""

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

import yaml


class FaultType(str, Enum):
    HTTP_5XX = "http_5xx"
    TIMEOUT = "timeout"
    LATENCY = "latency"
    CONNECTION_DROP = "connection_drop"
    RESOURCE_CPU_PRESSURE = "resource_cpu_pressure"
    RESOURCE_MEMORY_PRESSURE = "resource_memory_pressure"
    NETWORK_PARTITION = "network_partition"


class Result(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ABORTED = "ABORTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ExperimentConfig:
    name: str
    target_service: str
    target_endpoints: List[str]
    fault_type: FaultType
    fault_duration_seconds: int = 60
    fault_percentage: int = 100  # 0-100, traffic affected
    fault_magnitude: Any = None  # e.g., latency_ms, http_code, cpu_percent
    hypothesis: str = ""
    expected_circuit_state: Optional[str] = None
    expected_fallback_hit_ratio_min: Optional[float] = None
    expected_max_latency_ms: Optional[int] = None
    expected_retry_attempts_max: Optional[int] = None
    expected_bulkhead_rejection_rate_max: Optional[float] = None
    recovery_timeout_seconds: int = 60
    notify_channel: Optional[str] = None


@dataclass
class MetricSnapshot:
    timestamp: str
    latency_p50_ms: float = 0.0
    latency_p99_ms: float = 0.0
    throughput_rps: float = 0.0
    error_rate_percent: float = 0.0
    circuit_state: Optional[str] = None
    fallback_hit_ratio: Optional[float] = None
    retry_attempts_avg: Optional[float] = None
    bulkhead_queue_depth: Optional[int] = None
    bulkhead_rejection_rate: Optional[float] = None


@dataclass
class ExperimentResult:
    experiment_name: str
    result: Result
    hypothesis: str
    baseline: MetricSnapshot
    during: List[MetricSnapshot] = field(default_factory=list)
    recovery: Optional[MetricSnapshot] = None
    findings: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    aborted_reason: Optional[str] = None


# ── Global emergency stop flag ───────────────────────────────────────────────
_emergency_stop = False


def _handle_signal(signum: int, frame: Any) -> None:
    global _emergency_stop
    print(f"[EMERGENCY STOP] Signal {signum} received. Aborting experiment.")
    _emergency_stop = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Safety layer ─────────────────────────────────────────────────────────────

SAFETY_RULES = [
    ("ENVIRONMENT_CHECK", "Production environment detected — execution blocked."),
    ("SCOPE_CHECK", "Missing explicit target_service or target_endpoints."),
    ("DURATION_CHECK", "fault_duration_seconds exceeds 300s (5m) maximum."),
    ("ROLLBACK_CHECK", "Rollback verification not completed in last 24h."),
]


def verify_environment(env_name: str) -> bool:
    """FAIL CLOSED: only allow staging or isolated."""
    allowed = {"staging", "isolated", "dev", "test"}
    normalized = env_name.lower().strip()
    if normalized in allowed:
        print(f"[SAFETY] Environment '{env_name}' approved.")
        return True
    print(f"[SAFETY ERROR] Environment '{env_name}' NOT in allowed set: {allowed}")
    return False


def verify_scope(config: ExperimentConfig) -> bool:
    if not config.target_service or not config.target_endpoints:
        print("[SAFETY ERROR] target_service and target_endpoints must be explicit.")
        return False
    if config.fault_duration_seconds > 300:
        print("[SAFETY ERROR] fault_duration_seconds exceeds 300s maximum.")
        return False
    if not (0 < config.fault_percentage <= 50):
        print("[SAFETY ERROR] fault_percentage must be >0 and <=50 for first runs.")
        return False
    print("[SAFETY] Scope and duration within limits.")
    return True


def verify_rollback_dry_run(log_dir: Path) -> bool:
    """Stub: check for recent rollback verification marker."""
    marker = log_dir / ".rollback_verified"
    if marker.exists():
        print("[SAFETY] Rollback verification marker found.")
        return True
    print("[SAFETY WARNING] Rollback verification marker not found. Run dry-run first.")
    # Template default: strict mode blocks; set to True for lenient staging
    return False


# ── Monitoring stubs ─────────────────────────────────────────────────────────

class MetricsCollector:
    """Pluggable collector for baseline, during, and recovery metrics.
    Replace stubs with real integrations (Prometheus, Datadog, etc.).
    """

    def __init__(self, prometheus_url: Optional[str] = None):
        self.prometheus_url = prometheus_url

    def snapshot(self, label: str = "") -> MetricSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        # --- STUB: replace with real queries ---
        # Example Prometheus queries to implement:
        #   latency_p50: histogram_quantile(0.5, rate(http_request_duration_seconds_bucket[1m]))
        #   latency_p99: histogram_quantile(0.99, ...)
        #   error_rate:  rate(http_requests_total{status=~"5.."}[1m]) / rate(http_requests_total[1m])
        #   circuit_state: resilience4j_circuitbreaker_state{name=...}
        #   fallback_hits: resilience4j_fallback_calls_total{name=...}
        #   retry_attempts: resilience4j_retry_calls_total{name=..., kind="failed_retry"}
        #   bulkhead_depth: resilience4j_bulkhead_available_concurrent_calls{name=...}
        print(f"[METRICS] {label} snapshot at {now} (stub)")
        return MetricSnapshot(timestamp=now)

    def poll_during(self, interval: int = 10) -> MetricSnapshot:
        """Call this repeatedly during fault injection."""
        return self.snapshot(label="during")


# ── Fault injection stubs ────────────────────────────────────────────────────

class FaultInjector:
    """Pluggable fault injector.
    Replace stubs with real tooling (Chaos Monkey, Toxiproxy, Litmus, Gremlin, etc.).
    """

    def __init__(self, config: ExperimentConfig, env: str):
        self.config = config
        self.env = env

    def inject(self) -> bool:
        ft = self.config.fault_type
        print(f"[INJECT] Applying {ft.value} to {self.config.target_service} "
              f"for {self.config.fault_duration_seconds}s @ {self.config.fault_percentage}%")
        # --- STUB: wire to actual chaos tooling ---
        if ft == FaultType.HTTP_5XX:
            # e.g., toxiproxy.update(toxic=...) or mesh fault
            pass
        elif ft == FaultType.TIMEOUT:
            # e.g., toxiproxy timeout toxic
            pass
        elif ft == FaultType.LATENCY:
            # e.g., toxiproxy latency toxic with jitter
            pass
        elif ft == FaultType.CONNECTION_DROP:
            # e.g., iptables / network policy / proxy reset
            pass
        elif ft == FaultType.RESOURCE_CPU_PRESSURE:
            # e.g., stress-ng --cpu ... or k8s cpu limit manipulation (read-only)
            pass
        elif ft == FaultType.RESOURCE_MEMORY_PRESSURE:
            # e.g., memory pressure sidecar (read-only, no OOM kill)
            pass
        elif ft == FaultType.NETWORK_PARTITION:
            # e.g., Calico/NetworkPolicy deny egress to dependency
            pass
        return True

    def remove(self) -> bool:
        print(f"[INJECT] Removing {self.config.fault_type.value} from {self.config.target_service}")
        # --- STUB: wire to cleanup hooks ---
        return True


# ── Hypothesis validator ─────────────────────────────────────────────────────

def validate_hypothesis(
    config: ExperimentConfig,
    baseline: MetricSnapshot,
    during: List[MetricSnapshot],
    recovery: Optional[MetricSnapshot],
) -> ExperimentResult:
    result = Result.PASS
    findings: List[str] = []

    if not during:
        findings.append("No 'during' metrics collected — experiment incomplete.")
        result = Result.FAIL
        return ExperimentResult(
            experiment_name=config.name,
            result=result,
            hypothesis=config.hypothesis,
            baseline=baseline,
            during=during,
            recovery=recovery,
            findings=findings,
        )

    last = during[-1]

    # Circuit breaker
    if config.expected_circuit_state:
        observed = last.circuit_state or "UNKNOWN"
        if observed.upper() != config.expected_circuit_state.upper():
            findings.append(
                f"Circuit breaker: expected {config.expected_circuit_state}, got {observed}"
            )
            result = Result.FAIL
        else:
            findings.append(f"Circuit breaker: correctly transitioned to {observed}")

    # Fallback
    if config.expected_fallback_hit_ratio_min is not None:
        ratio = last.fallback_hit_ratio or 0.0
        if ratio < config.expected_fallback_hit_ratio_min:
            findings.append(
                f"Fallback: hit ratio {ratio:.2%} below threshold "
                f"{config.expected_fallback_hit_ratio_min:.2%}"
            )
            result = Result.FAIL
        else:
            findings.append(f"Fallback: hit ratio {ratio:.2%} meets threshold")

    # Latency
    if config.expected_max_latency_ms is not None:
        p99 = last.latency_p99_ms or 0.0
        if p99 > config.expected_max_latency_ms:
            findings.append(
                f"Latency: P99 {p99:.1f}ms exceeds max {config.expected_max_latency_ms}ms"
            )
            result = Result.FAIL
        else:
            findings.append(f"Latency: P99 {p99:.1f}ms within SLO")

    # Retry storm
    if config.expected_retry_attempts_max is not None:
        retries = last.retry_attempts_avg or 0.0
        if retries > config.expected_retry_attempts_max:
            findings.append(
                f"Retry: avg attempts {retries:.1f} exceeds max {config.expected_retry_attempts_max}"
            )
            result = Result.FAIL
        else:
            findings.append(f"Retry: avg attempts {retries:.1f} within limit")

    # Bulkhead
    if config.expected_bulkhead_rejection_rate_max is not None:
        rej = last.bulkhead_rejection_rate or 0.0
        if rej > config.expected_bulkhead_rejection_rate_max:
            findings.append(
                f"Bulkhead: rejection rate {rej:.2%} exceeds max "
                f"{config.expected_bulkhead_rejection_rate_max:.2%}"
            )
            result = Result.FAIL
        else:
            findings.append(f"Bulkhead: rejection rate {rej:.2%} within limit")

    # Recovery
    if recovery:
        if recovery.error_rate_percent > baseline.error_rate_percent * 1.5:
            findings.append(
                f"Recovery: error rate {recovery.error_rate_percent:.2%} "
                f"not returned to baseline {baseline.error_rate_percent:.2%}"
            )
            result = Result.FAIL
        else:
            findings.append("Recovery: metrics returned toward baseline")
    else:
        findings.append("Recovery: no recovery snapshot collected")

    return ExperimentResult(
        experiment_name=config.name,
        result=result,
        hypothesis=config.hypothesis,
        baseline=baseline,
        during=during,
        recovery=recovery,
        findings=findings,
    )


# ── Reporter ─────────────────────────────────────────────────────────────────

def generate_report(results: List[ExperimentResult], output_path: Path) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r.result == Result.PASS),
            "fail": sum(1 for r in results if r.result == Result.FAIL),
            "aborted": sum(1 for r in results if r.result == Result.ABORTED),
        },
        "block_production_promotion": any(
            r.result == Result.FAIL for r in results
        ),
        "experiments": [asdict(r) for r in results],
    }
    output_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"[REPORT] Written to {output_path}")


# ── Main execution ─────────────────────────────────────────────────────────

def run_experiment(config: ExperimentConfig, env: str, collector: MetricsCollector) -> ExperimentResult:
    global _emergency_stop
    _emergency_stop = False

    injector = FaultInjector(config, env)
    start_time = time.time()
    during_snapshots: List[MetricSnapshot] = []

    # 1. Baseline
    print(f"\n[EXPERIMENT] {config.name}")
    print(f"[EXPERIMENT] Hypothesis: {config.hypothesis}")
    baseline = collector.snapshot(label="baseline")

    # 2. Notify
    if config.notify_channel:
        print(f"[NOTIFY] Would notify {config.notify_channel}: "
              f"experiment={config.name} duration={config.fault_duration_seconds}s")

    # 3. Inject
    if not injector.inject():
        return ExperimentResult(
            experiment_name=config.name,
            result=Result.ABORTED,
            hypothesis=config.hypothesis,
            baseline=baseline,
            aborted_reason="Fault injection failed to start",
        )

    # 4. Monitor during
    elapsed = 0
    interval = 10
    while elapsed < config.fault_duration_seconds:
        if _emergency_stop:
            injector.remove()
            return ExperimentResult(
                experiment_name=config.name,
                result=Result.ABORTED,
                hypothesis=config.hypothesis,
                baseline=baseline,
                during=during_snapshots,
                aborted_reason="Emergency stop triggered",
            )
        time.sleep(interval)
        elapsed += interval
        snap = collector.poll_during()
        during_snapshots.append(snap)
        # Auto-abort if error rate spikes uncontrollably (>10x baseline)
        if baseline.error_rate_percent > 0 and snap.error_rate_percent > baseline.error_rate_percent * 10:
            if snap.error_rate_percent > 50:  # absolute guard
                print("[AUTO-ABORT] Error rate spiked uncontrollably. Removing fault.")
                _emergency_stop = True

    # 5. Remove fault
    injector.remove()

    # 6. Recovery window
    recovery = None
    if config.recovery_timeout_seconds > 0:
        print(f"[RECOVERY] Waiting {config.recovery_timeout_seconds}s for steady state...")
        time.sleep(config.recovery_timeout_seconds)
        recovery = collector.snapshot(label="recovery")

    # 7. Validate
    duration = time.time() - start_time
    result = validate_hypothesis(config, baseline, during_snapshots, recovery)
    result.duration_seconds = round(duration, 1)

    print(f"[RESULT] {config.name}: {result.result.value}")
    for f in result.findings:
        print(f"  - {f}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Resilience Experiment Runner")
    parser.add_argument("--config", required=True, help="Path to experiment YAML config")
    parser.add_argument("--env", required=True, help="Target environment name")
    parser.add_argument("--prometheus-url", default=None, help="Prometheus base URL")
    parser.add_argument("--output", default="chaos-report.json", help="Report output path")
    parser.add_argument("--strict-rollback", action="store_true", help="Require rollback dry-run marker")
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}")
        return 2
    raw = yaml.safe_load(config_path.read_text())

    # Support single experiment or list
    experiments: List[Dict[str, Any]] = raw if isinstance(raw, list) else [raw]

    # Safety checks
    if not verify_environment(args.env):
        return 2

    log_dir = Path("/tmp/chaos-logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    if args.strict_rollback and not verify_rollback_dry_run(log_dir):
        return 2

    collector = MetricsCollector(prometheus_url=args.prometheus_url)
    results: List[ExperimentResult] = []

    for exp in experiments:
        cfg = ExperimentConfig(**exp)
        if not verify_scope(cfg):
            return 2
        result = run_experiment(cfg, args.env, collector)
        results.append(result)

    # Report
    output_path = Path(args.output)
    generate_report(results, output_path)

    # Summary
    fail_count = sum(1 for r in results if r.result == Result.FAIL)
    abort_count = sum(1 for r in results if r.result == Result.ABORTED)
    if abort_count:
        return 3
    if fail_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
