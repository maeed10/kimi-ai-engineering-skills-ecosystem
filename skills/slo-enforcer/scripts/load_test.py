#!/usr/bin/env python3
"""
slo-enforcer load testing harness.

Generates synthetic validation requests against the L0 enforcement layer to
measure latency distributions, throughput ceilings, and degradation knee-points.

Usage:
    python load_test.py --skill policy-engine --mode baseline --duration 300
    python load_test.py --skill sandbox-executor --mode candidate --duration 300
    python load_test.py --skill policy-engine --sweep-rules --max-rules 25000

Requires Python 3.10+ and `httpx` (or swap to `requests` if preferred).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import string
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_ENDPOINTS = {
    "policy-engine": "http://localhost:8080/v1/validate",
    "sandbox-executor": "http://localhost:8081/v1/sandbox/create",
    "phase-controller": "http://localhost:8082/v1/phase/transition",
    "memory-guard": "http://localhost:8083/v1/acl/check",
    "egress-dpi-guard": "http://localhost:8084/v1/flow/inspect",
}

DEFAULT_CONCURRENCY = {
    "policy-engine": 100,
    "sandbox-executor": 20,
    "phase-controller": 100,
    "memory-guard": 200,
    "egress-dpi-guard": 500,
}

DEFAULT_RPS = {
    "policy-engine": 10_000,
    "sandbox-executor": 120,
    "phase-controller": 1_000,
    "memory-guard": 50_000,
    "egress-dpi-guard": 100_000,
}

SLO_THRESHOLDS = {
    "policy-engine": {"p99_ms": 50, "error_rate": 0.001},
    "sandbox-executor": {"p99_ms": 5_000, "error_rate": 0.005},
    "phase-controller": {"p99_ms": 200, "error_rate": 0.0005},
    "memory-guard": {"p99_ms": 5, "error_rate": 0.0001},
    "egress-dpi-guard": {"p99_ms": 1, "error_rate": 0.001},
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LatencyHistogram:
    """Exponential-bucket histogram (base 2) for microsecond-scale accuracy."""

    buckets: dict[int, int] = field(default_factory=dict)
    total_count: int = 0
    total_sum_us: float = 0.0

    def record(self, latency_us: float) -> None:
        self.total_count += 1
        self.total_sum_us += latency_us
        if latency_us <= 0:
            bucket = 0
        else:
            bucket = int(math.ceil(math.log2(latency_us)))
        self.buckets[bucket] = self.buckets.get(bucket, 0) + 1

    def percentile(self, p: float) -> float:
        """Return latency in microseconds for the given percentile."""
        if self.total_count == 0:
            return 0.0
        target = int(math.ceil(p * self.total_count))
        cumulative = 0
        for bucket in sorted(self.buckets):
            cumulative += self.buckets[bucket]
            if cumulative >= target:
                return 2.0**bucket
        return 2.0**max(self.buckets.keys())

    def mean(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.total_sum_us / self.total_count

    def merge(self, other: LatencyHistogram) -> None:
        for bucket, count in other.buckets.items():
            self.buckets[bucket] = self.buckets.get(bucket, 0) + count
        self.total_count += other.total_count
        self.total_sum_us += other.total_sum_us


@dataclass
class SkillResult:
    skill: str
    mode: str
    duration_s: float
    histogram: LatencyHistogram
    errors: int
    total: int
    metadata: dict = field(default_factory=dict)

    @property
    def p50_ms(self) -> float:
        return self.histogram.percentile(0.50) / 1_000.0

    @property
    def p95_ms(self) -> float:
        return self.histogram.percentile(0.95) / 1_000.0

    @property
    def p99_ms(self) -> float:
        return self.histogram.percentile(0.99) / 1_000.0

    @property
    def throughput_rps(self) -> float:
        return self.total / self.duration_s if self.duration_s else 0.0

    @property
    def error_rate(self) -> float:
        return self.errors / self.total if self.total else 0.0

    def slo_ok(self) -> bool:
        slo = SLO_THRESHOLDS.get(self.skill, {})
        lat_ok = self.p99_ms <= slo.get("p99_ms", float("inf"))
        err_ok = self.error_rate <= slo.get("error_rate", float("inf"))
        return lat_ok and err_ok

    def to_dict(self) -> dict:
        return {
            "skill": self.skill,
            "mode": self.mode,
            "duration_s": self.duration_s,
            "total_requests": self.total,
            "errors": self.errors,
            "error_rate": self.error_rate,
            "throughput_rps": self.throughput_rps,
            "latency_ms": {
                "mean": self.histogram.mean() / 1_000.0,
                "p50": self.p50_ms,
                "p95": self.p95_ms,
                "p99": self.p99_ms,
            },
            "slo_passed": self.slo_ok(),
            "metadata": self.metadata,
        }

    def to_prometheus(self) -> str:
        lines = [
            f"# HELP loadtest_latency_microseconds Load-test latency histogram",
            f"# TYPE loadtest_latency_microseconds histogram",
        ]
        for bucket, count in sorted(self.histogram.buckets.items()):
            le = 2.0**bucket / 1_000_000.0  # convert µs → seconds for Prometheus convention
            lines.append(
                f'loadtest_latency_microseconds_bucket{{skill="{self.skill}",mode="{self.mode}",le="{le:.6f}"}} {count}'
            )
        lines.append(
            f'loadtest_latency_microseconds_count{{skill="{self.skill}",mode="{self.mode}"}} {self.histogram.total_count}'
        )
        lines.append(
            f'loadtest_latency_microseconds_sum{{skill="{self.skill}",mode="{self.mode}"}} {self.histogram.total_sum_us / 1_000_000.0}'
        )
        lines.append(
            f'loadtest_errors_total{{skill="{self.skill}",mode="{self.mode}"}} {self.errors}'
        )
        lines.append(
            f'loadtest_requests_total{{skill="{self.skill}",mode="{self.mode}"}} {self.total}'
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Payload generators
# ---------------------------------------------------------------------------

def _random_str(length: int = 12) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _generate_policy_payload(rule_count: int = 1) -> dict:
    rules = []
    for i in range(rule_count):
        rule_type = random.choice(["attribute", "regex", "composite"])
        if rule_type == "attribute":
            rules.append({
                "id": f"rule-{i}",
                "type": "attribute",
                "field": random.choice(["user_id", "tenant", "resource"]),
                "op": random.choice(["eq", "neq", "in"]),
                "value": _random_str(),
            })
        elif rule_type == "regex":
            rules.append({
                "id": f"rule-{i}",
                "type": "regex",
                "pattern": f"^.*{_random_str(4)}.*$",
                "field": "payload",
            })
        else:
            rules.append({
                "id": f"rule-{i}",
                "type": "composite",
                "logic": random.choice(["AND", "OR"]),
                "children": [f"rule-{max(0, i-1)}", f"rule-{max(0, i-2)}"],
            })
    return {
        "request_id": _random_str(24),
        "subject": {"user": _random_str(), "tenant": _random_str(6)},
        "action": random.choice(["read", "write", "delete"]),
        "resource": f"/api/v1/{_random_str()}/{_random_str()}",
        "rules": rules,
    }


def _generate_sandbox_payload() -> dict:
    return {
        "request_id": _random_str(24),
        "image": random.choice(["alpine:3.18", "ubuntu:22.04", "debian:12"]),
        "cmd": ["sh", "-c", "echo done"],
        "limits": {"cpu": "0.5", "memory": "128Mi"},
        "env": {f"VAR_{i}": _random_str() for i in range(random.randint(0, 20))},
    }


def _generate_phase_payload() -> dict:
    return {
        "request_id": _random_str(24),
        "pipeline_id": _random_str(16),
        "current_phase": random.choice(["build", "test", "package", "deploy"]),
        "proposed_artifact": {
            "digest": f"sha256:{_random_str(64)}",
            "size_bytes": random.randint(1_000, 1_000_000_000),
            "dependencies": [_random_str(32) for _ in range(random.randint(0, 50))],
        },
        "validate_depth": random.choice(["shallow", "deep"]),
    }


def _generate_memory_guard_payload() -> dict:
    return {
        "request_id": _random_str(24),
        "node_id": f"node-{random.randint(1, 100)}",
        "shard": random.randint(0, 255),
        "subject": _random_str(16),
        "action": random.choice(["read", "write", "admin"]),
        "resource": f"/mesh/shard/{random.randint(0, 255)}/{_random_str()}",
        "quota_context": {"current_usage_mb": random.randint(0, 10_000), "limit_mb": 10_000},
    }


def _generate_dpi_payload() -> dict:
    return {
        "request_id": _random_str(24),
        "flow_id": _random_str(20),
        "src_ip": f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}",
        "dst_ip": f"203.0.113.{random.randint(1,254)}",
        "dst_port": random.choice([80, 443, 8080, 53]),
        "payload_b64": _random_str(256),
        "tls_sni": random.choice([None, "example.com", "api.example.com", "cdn.example.com"]),
    }


PAYLOAD_GENERATORS: dict[str, Callable[[], dict]] = {
    "policy-engine": _generate_policy_payload,
    "sandbox-executor": _generate_sandbox_payload,
    "phase-controller": _generate_phase_payload,
    "memory-guard": _generate_memory_guard_payload,
    "egress-dpi-guard": _generate_dpi_payload,
}


# ---------------------------------------------------------------------------
# Client abstraction
# ---------------------------------------------------------------------------

class AsyncHttpClient:
    """Minimal async HTTP client wrapping httpx (fallback to aiohttp if needed)."""

    def __init__(self) -> None:
        self._client = None
        try:
            import httpx

            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
            self._impl = "httpx"
        except Exception:
            self._impl = None

    async def post(self, url: str, json_payload: dict) -> tuple[int, float]:
        """Return (status_code, latency_us)."""
        if self._client is None:
            raise RuntimeError("No HTTP client available. Install httpx: pip install httpx")
        t0 = time.perf_counter()
        try:
            resp = await self._client.post(url, json=json_payload)
            latency_us = (time.perf_counter() - t0) * 1_000_000.0
            return resp.status_code, latency_us
        except Exception:
            latency_us = (time.perf_counter() - t0) * 1_000_000.0
            return 0, latency_us

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


# ---------------------------------------------------------------------------
# Load-test engine
# ---------------------------------------------------------------------------

async def _worker(
    client: AsyncHttpClient,
    endpoint: str,
    payload_gen: Callable[[], dict],
    q: asyncio.Queue,
    histogram: LatencyHistogram,
    counters: dict,
    stop_event: asyncio.Event,
    rate_limiter: asyncio.Semaphore | None,
) -> None:
    while not stop_event.is_set():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.001)
            continue
        payload = payload_gen()
        if rate_limiter:
            async with rate_limiter:
                status, latency_us = await client.post(endpoint, payload)
        else:
            status, latency_us = await client.post(endpoint, payload)
        histogram.record(latency_us)
        counters["total"] += 1
        if status >= 500 or status == 0:
            counters["errors"] += 1


async def run_load_test(
    skill: str,
    mode: str,
    duration_s: float,
    concurrency: int,
    target_rps: float | None,
    rule_count: int | None,
    endpoint: str | None,
) -> SkillResult:
    """Execute the load test and return aggregated results."""

    url = endpoint or DEFAULT_ENDPOINTS.get(skill)
    if not url:
        raise ValueError(f"No endpoint configured for skill: {skill}")

    payload_gen_base = PAYLOAD_GENERATORS.get(skill, _generate_policy_payload)

    def payload_gen() -> dict:
        if skill == "policy-engine" and rule_count is not None:
            return _generate_policy_payload(rule_count=rule_count)
        return payload_gen_base()

    client = AsyncHttpClient()
    histogram = LatencyHistogram()
    counters: dict = {"total": 0, "errors": 0}
    q: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    # Fill the work queue so workers never starve
    for _ in range(concurrency * 100):
        q.put_nowait(1)

    # Refill task
    async def refill() -> None:
        while not stop_event.is_set():
            while q.qsize() < concurrency * 100:
                q.put_nowait(1)
            await asyncio.sleep(0.05)

    rate_limiter: asyncio.Semaphore | None = None
    if target_rps is not None:
        # Token-bucket-ish: limit concurrency so that expected latency caps RPS.
        # A simpler approach: one semaphore per expected request interval.
        max_in_flight = max(1, int(target_rps * 0.010))  # assume 10 ms avg latency
        rate_limiter = asyncio.Semaphore(max_in_flight)

    workers = [
        asyncio.create_task(
            _worker(client, url, payload_gen, q, histogram, counters, stop_event, rate_limiter)
        )
        for _ in range(concurrency)
    ]
    refiller = asyncio.create_task(refill())

    await asyncio.sleep(duration_s)
    stop_event.set()

    await asyncio.gather(*workers, return_exceptions=True)
    await refiller
    await client.close()

    return SkillResult(
        skill=skill,
        mode=mode,
        duration_s=duration_s,
        histogram=histogram,
        errors=counters["errors"],
        total=counters["total"],
        metadata={
            "concurrency": concurrency,
            "target_rps": target_rps,
            "endpoint": url,
            "rule_count": rule_count,
        },
    )


# ---------------------------------------------------------------------------
# Rule-count sweep (policy-engine knee-point detection)
# ---------------------------------------------------------------------------

async def run_rule_sweep(
    max_rules: int,
    step: int,
    duration_per_step: float,
    concurrency: int,
    endpoint: str | None,
) -> list[SkillResult]:
    results: list[SkillResult] = []
    for rule_count in range(step, max_rules + step, step):
        print(f"\n[SWEEP] Testing policy-engine with {rule_count} rules...")
        result = await run_load_test(
            skill="policy-engine",
            mode="sweep",
            duration_s=duration_per_step,
            concurrency=concurrency,
            target_rps=None,
            rule_count=rule_count,
            endpoint=endpoint,
        )
        print(
            f"  p99={result.p99_ms:.2f}ms  throughput={result.throughput_rps:.1f} RPS  "
            f"errors={result.errors}/{result.total}  slo_passed={result.slo_ok()}"
        )
        results.append(result)
        if not result.slo_ok():
            print("  >>> SLO BREACHED — stopping sweep early.")
            break
    return results


# ---------------------------------------------------------------------------
# CLI & main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synthetic load testing harness for the L0 enforcement layer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--skill",
        choices=list(DEFAULT_ENDPOINTS.keys()),
        required=True,
        help="Which enforcement-layer skill to exercise.",
    )
    parser.add_argument(
        "--mode",
        choices=["baseline", "candidate", "sweep"],
        default="baseline",
        help="Test mode: baseline = stable version; candidate = new version; sweep = rule-count sweep.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=300.0,
        help="Duration of the load test in seconds (default: 300).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Concurrent workers (default: skill-specific).",
    )
    parser.add_argument(
        "--target-rps",
        type=float,
        default=None,
        help="Target requests per second (default: skill-specific sustained RPS).",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="Override the default endpoint URL.",
    )
    parser.add_argument(
        "--sweep-rules",
        action="store_true",
        help="Run a rule-count sweep for policy-engine knee-point detection.",
    )
    parser.add_argument(
        "--max-rules",
        type=int,
        default=25_000,
        help="Maximum rules for sweep (default: 25000).",
    )
    parser.add_argument(
        "--sweep-step",
        type=int,
        default=1_000,
        help="Step size for rule sweep (default: 1000).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="loadtest_results.json",
        help="Path for JSON results output.",
    )
    parser.add_argument(
        "--prometheus-output",
        type=str,
        default=None,
        help="Optional path for Prometheus text-format output.",
    )
    return parser


def print_summary(result: SkillResult) -> None:
    print("\n" + "=" * 60)
    print(f"  Skill      : {result.skill}")
    print(f"  Mode       : {result.mode}")
    print(f"  Duration   : {result.duration_s:.1f}s")
    print(f"  Requests   : {result.total}")
    print(f"  Errors     : {result.errors} ({result.error_rate*100:.3f}%)")
    print(f"  Throughput : {result.throughput_rps:.1f} RPS")
    print("-" * 60)
    print(f"  Latency (ms)")
    print(f"    mean : {result.histogram.mean()/1_000:.3f}")
    print(f"    p50  : {result.p50_ms:.3f}")
    print(f"    p95  : {result.p95_ms:.3f}")
    print(f"    p99  : {result.p99_ms:.3f}")
    print("-" * 60)
    slo = SLO_THRESHOLDS.get(result.skill, {})
    print(f"  SLO p99 <= {slo.get('p99_ms', '?')} ms  =>  {'PASS' if result.p99_ms <= slo.get('p99_ms', float('inf')) else 'FAIL'}")
    print(f"  SLO err <= {slo.get('error_rate', '?')}   =>  {'PASS' if result.error_rate <= slo.get('error_rate', float('inf')) else 'FAIL'}")
    print(f"  OVERALL    :  {'PASS' if result.slo_ok() else 'FAIL'}")
    print("=" * 60)


async def main_async(args: argparse.Namespace) -> int:
    skill: str = args.skill
    mode: str = args.mode
    concurrency = args.concurrency or DEFAULT_CONCURRENCY.get(skill, 100)
    target_rps = args.target_rps or DEFAULT_RPS.get(skill)

    if args.sweep_rules and skill == "policy-engine":
        results = await run_rule_sweep(
            max_rules=args.max_rules,
            step=args.sweep_step,
            duration_per_step=args.duration,
            concurrency=concurrency,
            endpoint=args.endpoint,
        )
        output = {
            "sweep": True,
            "results": [r.to_dict() for r in results],
        }
    else:
        result = await run_load_test(
            skill=skill,
            mode=mode,
            duration_s=args.duration,
            concurrency=concurrency,
            target_rps=target_rps,
            rule_count=None,
            endpoint=args.endpoint,
        )
        print_summary(result)
        output = {"sweep": False, "results": [result.to_dict()]}
        if args.prometheus_output:
            prom_path = Path(args.prometheus_output)
            prom_path.write_text(result.to_prometheus())
            print(f"\nPrometheus textformat written to: {prom_path}")

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"\nJSON results written to: {out_path}")
    return 0 if all(r.slo_ok() for r in output["results"]) else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
