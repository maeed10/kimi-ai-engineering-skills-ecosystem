#!/usr/bin/env python3
"""
audit_secrets.py

Audit secret access logs for anomalies across HashiCorp Vault, AWS CloudTrail,
and Azure Monitor. Detects unknown IPs, rate spikes, off-hours access, failed
reads, and version/path anomalies.

Usage:
    python audit_secrets.py --backend vault --log /var/log/vault/audit.log
    python audit_secrets.py --backend aws --log cloudtrail.json.gz
    python audit_secrets.py --backend azure --log az-monitor.json
    python audit_secrets.py --backend vault --log audit.log --output report.json

Exit codes:
    0 - No anomalies detected
    1 - Anomalies detected (check output)
    2 - Runtime / parsing error
"""

import argparse
import gzip
import ipaddress
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("audit_secrets")


# ---------------------------------------------------------------------------
# Configuration / thresholds
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "rate_window_seconds": 300,
    "rate_threshold": 50,
    "off_hours_start": 22,
    "off_hours_end": 6,
    "unknown_ip_file": "known_ips.txt",
    "version_grace_hours": 24,
    "max_failed_attempts": 10,
}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class VaultAuditParser:
    """Parse HashiCorp Vault JSON audit logs (one JSON object per line)."""

    @staticmethod
    def parse_line(line: str) -> dict[str, Any] | None:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        if data.get("type") != "request":
            return None

        req = data.get("request", {})
        auth = data.get("auth", {})
        time_str = data.get("time", "")

        timestamp = None
        if time_str:
            try:
                timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        return {
            "backend": "vault",
            "timestamp": timestamp,
            "operation": req.get("operation"),
            "path": req.get("path"),
            "client_address": req.get("remote_address", "").split(":")[0],
            "client_token": auth.get("client_token"),
            "display_name": auth.get("display_name"),
            "data": req.get("data"),
            "failed": req.get("operation") == "read" and data.get("error") is not None,
            "error": data.get("error"),
            "raw": data,
        }


class AWSCloudTrailParser:
    """Parse AWS CloudTrail logs (JSON array or ndjson, possibly gzipped)."""

    @staticmethod
    def parse_file(file_path: Path) -> list[dict[str, Any]]:
        raw = ""
        if str(file_path).endswith(".gz"):
            with gzip.open(file_path, "rt", encoding="utf-8") as fh:
                raw = fh.read()
        else:
            with open(file_path, "r", encoding="utf-8") as fh:
                raw = fh.read()

        events = []
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "Records" in data:
                events = data["Records"]
            elif isinstance(data, list):
                events = data
        except json.JSONDecodeError:
            for line in raw.strip().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        results = []
        for ev in events:
            if ev.get("eventName") not in ("GetSecretValue", "PutSecretValue", "DescribeSecret", "DeleteSecret", "RotateSecret"):
                continue

            time_str = ev.get("eventTime", "")
            timestamp = None
            if time_str:
                try:
                    timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            results.append({
                "backend": "aws",
                "timestamp": timestamp,
                "operation": ev.get("eventName"),
                "path": ev.get("requestParameters", {}).get("secretId"),
                "client_address": None,
                "client_token": ev.get("userIdentity", {}).get("arn"),
                "display_name": ev.get("userIdentity", {}).get("sessionContext", {}).get("sessionIssuer", {}).get("userName"),
                "region": ev.get("awsRegion"),
                "failed": ev.get("errorCode") is not None,
                "error": ev.get("errorMessage"),
                "raw": ev,
            })
        return results


class AzureMonitorParser:
    """Parse Azure Monitor / Activity Log exports (JSON array)."""

    @staticmethod
    def parse_file(file_path: Path) -> list[dict[str, Any]]:
        with open(file_path, "r", encoding="utf-8") as fh:
            raw = fh.read()

        events = []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                events = data
            elif isinstance(data, dict) and "value" in data:
                events = data["value"]
        except json.JSONDecodeError:
            for line in raw.strip().splitlines():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        results = []
        for ev in events:
            op_name = ev.get("operationName", {}).get("value", "")
            if "vault/secrets" not in op_name.lower():
                continue

            time_str = ev.get("eventTimestamp", "")
            timestamp = None
            if time_str:
                try:
                    timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            claims = ev.get("claims", {})
            results.append({
                "backend": "azure",
                "timestamp": timestamp,
                "operation": op_name,
                "path": ev.get("properties", {}).get("secretName"),
                "client_address": None,
                "client_token": claims.get("oid"),
                "display_name": claims.get("name"),
                "failed": ev.get("status", {}).get("value", "") == "Failure",
                "error": ev.get("subStatus", {}).get("value"),
                "raw": ev,
            })
        return results


# ---------------------------------------------------------------------------
# Anomaly detectors
# ---------------------------------------------------------------------------

class AnomalyDetector:
    def __init__(self, config: dict[str, Any], known_ips: set[str]):
        self.config = config
        self.known_ips = known_ips
        self.anomalies: list[dict[str, Any]] = []

    def add(self, severity: str, category: str, message: str, evidence: dict[str, Any]) -> None:
        self.anomalies.append({
            "severity": severity,
            "category": category,
            "message": message,
            "evidence": evidence,
        })

    def check_unknown_ip(self, event: dict[str, Any]) -> None:
        ip = event.get("client_address")
        if not ip:
            return
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return
        if ip not in self.known_ips:
            self.add(
                "high",
                "unknown_ip",
                f"Access from unknown IP {ip} to {event.get('path')}",
                {"ip": ip, "path": event.get("path"), "identity": event.get("display_name"), "timestamp": str(event.get("timestamp"))},
            )

    def check_failed_reads(self, event: dict[str, Any]) -> None:
        if event.get("failed") and event.get("operation") in ("read", "GetSecretValue", "vault/secrets/get"):
            self.add(
                "medium",
                "failed_access",
                f"Failed secret read by {event.get('display_name')} on {event.get('path')}: {event.get('error')}",
                {"path": event.get("path"), "identity": event.get("display_name"), "error": event.get("error"), "timestamp": str(event.get("timestamp"))},
            )

    def check_off_hours(self, event: dict[str, Any]) -> None:
        ts = event.get("timestamp")
        if not ts:
            return
        hour = ts.hour
        if hour >= self.config["off_hours_start"] or hour < self.config["off_hours_end"]:
            self.add(
                "low",
                "off_hours",
                f"Off-hours access to {event.get('path')} by {event.get('display_name')} at {ts.isoformat()}",
                {"path": event.get("path"), "identity": event.get("display_name"), "hour": hour, "timestamp": str(ts)},
            )

    def check_rate_spike(self, events: list[dict[str, Any]]) -> None:
        buckets: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
        for ev in events:
            ts = ev.get("timestamp")
            if not ts:
                continue
            key = (ev.get("path", "unknown"), ev.get("client_address") or ev.get("client_token", "unknown"), ev.get("operation", "unknown"))
            buckets[key].append(ts)

        window = self.config["rate_window_seconds"]
        threshold = self.config["rate_threshold"]

        for (path, source, op), timestamps in buckets.items():
            if len(timestamps) < threshold:
                continue
            timestamps.sort()
            for i in range(len(timestamps)):
                j = i
                while j < len(timestamps) and (timestamps[j] - timestamps[i]).total_seconds() <= window:
                    j += 1
                count = j - i
                if count >= threshold:
                    self.add(
                        "high",
                        "rate_spike",
                        f"Rate spike: {count} requests in {window}s from {source} to {path} ({op})",
                        {"path": path, "source": source, "operation": op, "count": count, "window": window},
                    )
                    break

    def check_version_anomaly(self, events: list[dict[str, Any]]) -> None:
        """Detect reads of specific (non-latest) versions that may indicate stale consumers."""
        for ev in events:
            if ev.get("backend") != "vault":
                continue
            raw = ev.get("raw", {})
            req = raw.get("request", {})
            data = req.get("data", {})
            version = data.get("version") if isinstance(data, dict) else None
            if version is not None:
                self.add(
                    "low",
                    "version_pin",
                    f"Explicit version read (version={version}) on {ev.get('path')} by {ev.get('display_name')}",
                    {"path": ev.get("path"), "version": version, "identity": ev.get("display_name"), "timestamp": str(ev.get("timestamp"))},
                )

    def run(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.check_rate_spike(events)
        self.check_version_anomaly(events)
        for ev in events:
            self.check_unknown_ip(ev)
            self.check_failed_reads(ev)
            self.check_off_hours(ev)
        return self.anomalies


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

class Reporter:
    def __init__(self, anomalies: list[dict[str, Any]], events: list[dict[str, Any]]):
        self.anomalies = anomalies
        self.events = events

    def console(self) -> None:
        if not self.anomalies:
            print("\n✅ No anomalies detected.")
            return

        print(f"\n⚠️  {len(self.anomalies)} anomaly/ies detected:\n")
        by_severity = defaultdict(list)
        for a in self.anomalies:
            by_severity[a["severity"]].append(a)

        for sev in ("high", "medium", "low"):
            items = by_severity.get(sev, [])
            if not items:
                continue
            print(f"  [{sev.upper()}] ({len(items)})")
            for a in items:
                print(f"    - [{a['category']}] {a['message']}")
                if a["evidence"]:
                    for k, v in a["evidence"].items():
                        print(f"      {k}: {v}")
                print()

    def json_report(self, output_path: Path) -> None:
        summary = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "total_events": len(self.events),
            "anomaly_count": len(self.anomalies),
            "by_severity": dict(Counter(a["severity"] for a in self.anomalies)),
            "by_category": dict(Counter(a["category"] for a in self.anomalies)),
            "anomalies": self.anomalies,
            "statistics": {
                "unique_paths": len({e.get("path") for e in self.events if e.get("path")}),
                "unique_identities": len({e.get("display_name") for e in self.events if e.get("display_name")}),
                "time_range": {
                    "earliest": str(min(e["timestamp"] for e in self.events if e.get("timestamp"))),
                    "latest": str(max(e["timestamp"] for e in self.events if e.get("timestamp"))),
                } if any(e.get("timestamp") for e in self.events) else None,
            },
        }
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
        logger.info("JSON report written to %s", output_path)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def load_known_ips(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    ips = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    ipaddress.ip_address(line)
                    ips.add(line)
                except ValueError:
                    pass
    logger.info("Loaded %d known IPs from %s", len(ips), path)
    return ips


def read_vault_log(path: Path) -> list[dict[str, Any]]:
    events = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            ev = VaultAuditParser.parse_line(line)
            if ev:
                events.append(ev)
    return events


def read_aws_log(path: Path) -> list[dict[str, Any]]:
    return AWSCloudTrailParser.parse_file(path)


def read_azure_log(path: Path) -> list[dict[str, Any]]:
    return AzureMonitorParser.parse_file(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Audit secret access logs for anomalies")
    p.add_argument("--backend", required=True, choices=["vault", "aws", "azure"], help="Log source backend")
    p.add_argument("--log", required=True, type=Path, help="Path to log file")
    p.add_argument("--output", type=Path, help="Write JSON report to this path")
    p.add_argument("--known-ips", type=Path, help="File with known-good IPs (one per line)")
    p.add_argument("--rate-window", type=int, default=DEFAULT_CONFIG["rate_window_seconds"], help="Rate-spike window in seconds")
    p.add_argument("--rate-threshold", type=int, default=DEFAULT_CONFIG["rate_threshold"], help="Rate-spike threshold (requests)")
    p.add_argument("--off-hours-start", type=int, default=DEFAULT_CONFIG["off_hours_start"], help="Off-hours start hour (24h)")
    p.add_argument("--off-hours-end", type=int, default=DEFAULT_CONFIG["off_hours_end"], help="Off-hours end hour (24h)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.log.exists():
        logger.error("Log file not found: %s", args.log)
        return 2

    config = {
        "rate_window_seconds": args.rate_window,
        "rate_threshold": args.rate_threshold,
        "off_hours_start": args.off_hours_start,
        "off_hours_end": args.off_hours_end,
    }

    known_ips = load_known_ips(args.known_ips)

    logger.info("Reading %s log from %s", args.backend, args.log)
    if args.backend == "vault":
        events = read_vault_log(args.log)
    elif args.backend == "aws":
        events = read_aws_log(args.log)
    elif args.backend == "azure":
        events = read_azure_log(args.log)
    else:
        logger.error("Unknown backend: %s", args.backend)
        return 2

    logger.info("Parsed %d secret-related events", len(events))

    detector = AnomalyDetector(config, known_ips)
    anomalies = detector.run(events)

    reporter = Reporter(anomalies, events)
    reporter.console()

    if args.output:
        reporter.json_report(args.output)

    if anomalies:
        high = sum(1 for a in anomalies if a["severity"] == "high")
        if high:
            logger.error("%d HIGH severity anomaly/ies detected — immediate review recommended", high)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
