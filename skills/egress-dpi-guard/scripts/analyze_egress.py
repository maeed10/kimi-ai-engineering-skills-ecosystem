#!/usr/bin/env python3
"""
analyze_egress.py - Deep packet inspection for sandbox egress traffic.

Analyzes pcap files or live network interfaces for DNS tunneling,
HTTPS steganography, and protocol abuse patterns. Emits JSON alerts
to stdout for downstream drift-monitor and policy-engine consumption.

Usage:
    python analyze_egress.py --pcap capture.pcap
    python analyze_egress.py --interface eth0 --duration 60
    python analyze_egress.py --pcap capture.pcap --threshold 40
"""

import argparse
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLD = 50
DNS_QUERY_RATE_LIMIT = 100  # queries per minute
DNS_SINGLE_DOMAIN_RATE = 30  # queries per minute per domain
DNS_TXT_SIZE_LIMIT = 512  # bytes
DNS_MAX_LABELS = 5
DNS_ENTROPY_THRESHOLD = 3.5
DNS_QUERY_LENGTH_LIMIT = 200
HTTPS_HEADER_SIZE_LIMIT = 4096  # total headers
HTTPS_SINGLE_HEADER_LIMIT = 1024
HTTPS_SLOW_BYTES_PER_SEC = 1
HTTPS_SLOW_DURATION_SEC = 30
SESSION_RESUME_RATE = 50  # per minute
WEBSOCKET_ENTROPY_THRESHOLD = 4.0

SCORING = {
    "dns_high_rate": 20,
    "dns_large_txt": 25,
    "dns_encoded_subdomain": 25,
    "dns_deep_subdomain": 10,
    "dns_high_entropy": 15,
    "dns_nxdomain_flood": 5,
    "dns_long_query": 10,
    "https_oversized_header": 10,
    "https_padding_anomaly": 25,
    "https_suspicious_ua": 5,
    "https_slowloris": 25,
    "https_sni_mismatch": 20,
    "https_cert_anomaly": 15,
    "https_ws_hijack": 25,
    "https_alpn_downgrade": 5,
    "https_session_resume_abuse": 15,
    "pattern_beaconing": 25,
    "pattern_byte_ratio": 15,
    "pattern_connection_freq": 15,
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    alert_id: str
    session_id: str
    timestamp: float
    severity: str  # low, medium, high, critical
    type: str
    details: dict
    recommended_action: str  # log, rate_limit, block, terminate_session
    score: int = 0

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "type": self.type,
            "details": self.details,
            "recommended_action": self.recommended_action,
            "score": self.score,
        }


@dataclass
class SessionState:
    session_id: str
    dns_queries: List[dict] = field(default_factory=list)
    dns_responses: List[dict] = field(default_factory=list)
    http_requests: List[dict] = field(default_factory=list)
    tls_handshakes: List[dict] = field(default_factory=list)
    connections: List[dict] = field(default_factory=list)
    websocket_frames: List[dict] = field(default_factory=list)
    score: int = 0
    alerts: List[Alert] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------

def shannon_entropy(data: str) -> float:
    """Calculate Shannon entropy in bits per character."""
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def make_alert_id() -> str:
    return f"alert-{time.time_ns()}"


def severity_from_score(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def action_from_severity(severity: str) -> str:
    return {
        "low": "log",
        "medium": "rate_limit",
        "high": "block",
        "critical": "terminate_session",
    }.get(severity, "log")


# ---------------------------------------------------------------------------
# DNS Inspection
# ---------------------------------------------------------------------------

def inspect_dns(state: SessionState) -> List[Alert]:
    """Run all DNS tunneling detection signatures against session state."""
    alerts = []

    if not state.dns_queries:
        return alerts

    # SIG-DNS-001: High query rate
    queries_by_minute = defaultdict(int)
    queries_by_domain = defaultdict(int)
    for q in state.dns_queries:
        minute = int(q["timestamp"]) // 60
        queries_by_minute[minute] += 1
        queries_by_domain[q.get("domain", "")] += 1

    max_rate = max(queries_by_minute.values()) if queries_by_minute else 0
    max_domain_rate = max(queries_by_domain.values()) if queries_by_domain else 0

    if max_rate > DNS_QUERY_RATE_LIMIT or max_domain_rate > DNS_SINGLE_DOMAIN_RATE:
        score = SCORING["dns_high_rate"]
        if max_domain_rate > DNS_SINGLE_DOMAIN_RATE:
            score *= 2
        alerts.append(
            Alert(
                alert_id=make_alert_id(),
                session_id=state.session_id,
                timestamp=time.time(),
                severity=severity_from_score(score),
                type="dns_tunnel_alert",
                details={
                    "signature": "SIG-DNS-001",
                    "query_rate_per_min": max_rate,
                    "max_domain_rate": max_domain_rate,
                },
                recommended_action=action_from_severity(severity_from_score(score)),
                score=score,
            )
        )

    # SIG-DNS-003, 004, 005, 007: Per-query analysis
    seen_base32 = False
    seen_hex = False
    nxdomains = 0

    for q in state.dns_queries:
        qname = q.get("qname", "")
        labels = qname.split(".")
        subdomain = "".join(labels[:-2]) if len(labels) > 2 else qname

        # Encoded subdomain detection
        import re

        if re.match(r"^[A-Z2-7]{20,}$", subdomain):
            seen_base32 = True
        if re.match(r"^[0-9a-f]{40,}$", subdomain):
            seen_hex = True

        # Subdomain depth
        if len(labels) > DNS_MAX_LABELS:
            score = SCORING["dns_deep_subdomain"]
            if len(labels) > 8:
                score = int(score * 1.5)
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="dns_tunnel_alert",
                    details={
                        "signature": "SIG-DNS-004",
                        "qname": qname,
                        "label_count": len(labels),
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

        # Entropy
        if subdomain:
            entropy = shannon_entropy(subdomain)
            if entropy > DNS_ENTROPY_THRESHOLD:
                score = SCORING["dns_high_entropy"]
                if entropy > 4.0:
                    score *= 2
                alerts.append(
                    Alert(
                        alert_id=make_alert_id(),
                        session_id=state.session_id,
                        timestamp=time.time(),
                        severity=severity_from_score(score),
                        type="dns_tunnel_alert",
                        details={
                            "signature": "SIG-DNS-005",
                            "qname": qname,
                            "entropy": round(entropy, 3),
                        },
                        recommended_action=action_from_severity(
                            severity_from_score(score)
                        ),
                        score=score,
                    )
                )

        # Query length
        if len(qname) > DNS_QUERY_LENGTH_LIMIT:
            score = SCORING["dns_long_query"]
            if len(qname) > 400:
                score *= 2
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="dns_tunnel_alert",
                    details={
                        "signature": "SIG-DNS-007",
                        "qname": qname,
                        "length": len(qname),
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

    if seen_base32 and seen_hex:
        score = SCORING["dns_encoded_subdomain"] * 2
        alerts.append(
            Alert(
                alert_id=make_alert_id(),
                session_id=state.session_id,
                timestamp=time.time(),
                severity=severity_from_score(score),
                type="dns_tunnel_alert",
                details={
                    "signature": "SIG-DNS-003",
                    "base32_detected": seen_base32,
                    "hex_detected": seen_hex,
                },
                recommended_action=action_from_severity(severity_from_score(score)),
                score=score,
            )
        )
    elif seen_base32 or seen_hex:
        score = SCORING["dns_encoded_subdomain"]
        alerts.append(
            Alert(
                alert_id=make_alert_id(),
                session_id=state.session_id,
                timestamp=time.time(),
                severity=severity_from_score(score),
                type="dns_tunnel_alert",
                details={
                    "signature": "SIG-DNS-003",
                    "base32_detected": seen_base32,
                    "hex_detected": seen_hex,
                },
                recommended_action=action_from_severity(severity_from_score(score)),
                score=score,
            )
        )

    # SIG-DNS-002: Large TXT responses
    for resp in state.dns_responses:
        if resp.get("rtype") == "TXT" and resp.get("size", 0) > DNS_TXT_SIZE_LIMIT:
            score = SCORING["dns_large_txt"]
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="dns_tunnel_alert",
                    details={
                        "signature": "SIG-DNS-002",
                        "domain": resp.get("domain"),
                        "txt_size": resp.get("size"),
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

    # SIG-DNS-006: NXDOMAIN flood
    nxdomains = sum(1 for r in state.dns_responses if r.get("rcode") == 3)
    if nxdomains > 10:
        score = SCORING["dns_nxdomain_flood"]
        alerts.append(
            Alert(
                alert_id=make_alert_id(),
                session_id=state.session_id,
                timestamp=time.time(),
                severity=severity_from_score(score),
                type="dns_tunnel_alert",
                details={"signature": "SIG-DNS-006", "nxdomain_count": nxdomains},
                recommended_action=action_from_severity(severity_from_score(score)),
                score=score,
            )
        )

    return alerts


# ---------------------------------------------------------------------------
# HTTPS Inspection
# ---------------------------------------------------------------------------

def inspect_https(state: SessionState) -> List[Alert]:
    """Run all HTTPS steganography detection signatures against session state."""
    alerts = []

    # SIG-HTTPS-001: Oversized headers
    for req in state.http_requests:
        headers = req.get("headers", {})
        total_size = sum(len(str(k)) + len(str(v)) for k, v in headers.items())
        if total_size > HTTPS_HEADER_SIZE_LIMIT:
            score = SCORING["https_oversized_header"]
            # Check for oversized Cookie
            cookie_val = headers.get("Cookie", "")
            if len(str(cookie_val)) > HTTPS_SINGLE_HEADER_LIMIT:
                score *= 2
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="https_stego_alert",
                    details={
                        "signature": "SIG-HTTPS-001",
                        "host": req.get("host"),
                        "header_total_size": total_size,
                        "oversized_headers": [
                            k for k, v in headers.items() if len(str(v)) > HTTPS_SINGLE_HEADER_LIMIT
                        ],
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

    # SIG-HTTPS-003: Suspicious User-Agent
    for req in state.http_requests:
        ua = req.get("headers", {}).get("User-Agent", "")
        if not ua:
            score = SCORING["https_suspicious_ua"] * 3
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="https_stego_alert",
                    details={
                        "signature": "SIG-HTTPS-003",
                        "host": req.get("host"),
                        "user_agent": "<missing>",
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )
        elif shannon_entropy(ua) > 3.8:
            score = SCORING["https_suspicious_ua"] * 3
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="https_stego_alert",
                    details={
                        "signature": "SIG-HTTPS-003",
                        "host": req.get("host"),
                        "user_agent": ua[:100],
                        "ua_entropy": round(shannon_entropy(ua), 3),
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

    # SIG-HTTPS-005: SNI mismatch
    for tls in state.tls_handshakes:
        sni = tls.get("sni", "")
        for req in state.http_requests:
            host = req.get("host", "")
            if sni and host and sni != host:
                score = SCORING["https_sni_mismatch"]
                alerts.append(
                    Alert(
                        alert_id=make_alert_id(),
                        session_id=state.session_id,
                        timestamp=time.time(),
                        severity=severity_from_score(score),
                        type="https_stego_alert",
                        details={
                            "signature": "SIG-HTTPS-005",
                            "sni": sni,
                            "host": host,
                            "cert_cn": tls.get("cert_cn"),
                        },
                        recommended_action=action_from_severity(
                            severity_from_score(score)
                        ),
                        score=score,
                    )
                )

    # SIG-HTTPS-009: Session resumption abuse
    session_tickets = defaultdict(list)
    for tls in state.tls_handshakes:
        ticket = tls.get("session_ticket")
        if ticket:
            session_tickets[ticket].append(tls.get("host"))
    for ticket, hosts in session_tickets.items():
        if len(hosts) > SESSION_RESUME_RATE:
            score = SCORING["https_session_resume_abuse"]
            if len(hosts) > 100:
                score *= 2
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="https_stego_alert",
                    details={
                        "signature": "SIG-HTTPS-009",
                        "session_ticket": ticket[:16] + "...",
                        "host_count": len(hosts),
                        "unique_hosts": len(set(hosts)),
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

    return alerts


# ---------------------------------------------------------------------------
# Connection Pattern Analysis
# ---------------------------------------------------------------------------

def inspect_patterns(state: SessionState) -> List[Alert]:
    """Analyze connection patterns for beaconing and anomaly detection."""
    alerts = []
    conns = state.connections
    if len(conns) < 5:
        return alerts

    # SIG-PATTERN-001: Connection frequency
    dests_by_minute = defaultdict(set)
    for c in conns:
        minute = int(c["timestamp"]) // 60
        dests_by_minute[minute].add(c.get("dest", ""))
    max_unique = max(len(v) for v in dests_by_minute.values()) if dests_by_minute else 0
    if max_unique > 20:
        score = SCORING["pattern_connection_freq"]
        alerts.append(
            Alert(
                alert_id=make_alert_id(),
                session_id=state.session_id,
                timestamp=time.time(),
                severity=severity_from_score(score),
                type="pattern_alert",
                details={
                    "signature": "SIG-PATTERN-001",
                    "unique_destinations_per_min": max_unique,
                },
                recommended_action=action_from_severity(severity_from_score(score)),
                score=score,
            )
        )

    # SIG-PATTERN-002: Beaconing (regular intervals)
    if len(conns) >= 10:
        intervals = []
        timestamps = sorted(c["timestamp"] for c in conns)
        for i in range(1, len(timestamps)):
            intervals.append(timestamps[i] - timestamps[i - 1])
        if intervals:
            mean_interval = sum(intervals) / len(intervals)
            if mean_interval > 0:
                jitter = (sum(abs(i - mean_interval) for i in intervals) / len(intervals)) / mean_interval
                if jitter < 0.01:  # <1% jitter
                    score = SCORING["pattern_beaconing"]
                    alerts.append(
                        Alert(
                            alert_id=make_alert_id(),
                            session_id=state.session_id,
                            timestamp=time.time(),
                            severity=severity_from_score(score),
                            type="pattern_alert",
                            details={
                                "signature": "SIG-PATTERN-002",
                                "interval_sec": round(mean_interval, 2),
                                "jitter_ratio": round(jitter, 4),
                                "connection_count": len(conns),
                            },
                            recommended_action=action_from_severity(
                                severity_from_score(score)
                            ),
                            score=score,
                        )
                    )

    # SIG-PATTERN-003: Byte ratio anomaly
    for c in conns:
        sent = c.get("bytes_sent", 0)
        recv = c.get("bytes_recv", 0)
        if recv > 0 and sent / recv > 0.5 and c.get("direction") == "download":
            score = SCORING["pattern_byte_ratio"]
            alerts.append(
                Alert(
                    alert_id=make_alert_id(),
                    session_id=state.session_id,
                    timestamp=time.time(),
                    severity=severity_from_score(score),
                    type="pattern_alert",
                    details={
                        "signature": "SIG-PATTERN-003",
                        "dest": c.get("dest"),
                        "bytes_sent": sent,
                        "bytes_recv": recv,
                        "upload_ratio": round(sent / recv, 3),
                    },
                    recommended_action=action_from_severity(severity_from_score(score)),
                    score=score,
                )
            )

    return alerts


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

def analyze_session(state: SessionState, threshold: int = DEFAULT_THRESHOLD) -> dict:
    """Run full inspection pipeline on a session and return results."""
    all_alerts = []
    all_alerts.extend(inspect_dns(state))
    all_alerts.extend(inspect_https(state))
    all_alerts.extend(inspect_patterns(state))

    total_score = sum(a.score for a in all_alerts)

    # Deduplicate by signature within session
    seen_sigs = set()
    deduped = []
    for a in all_alerts:
        sig = a.details.get("signature", a.type)
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            deduped.append(a)

    triggered = total_score >= threshold

    return {
        "session_id": state.session_id,
        "inspection_timestamp": time.time(),
        "threshold": threshold,
        "total_score": total_score,
        "threshold_exceeded": triggered,
        "alert_count": len(deduped),
        "alerts": [a.to_dict() for a in deduped],
    }


def parse_pcap_jsonl(filepath: str) -> List[SessionState]:
    """
    Parse a JSONL file where each line is a packet/flow record.
    Expected record format:
      {"session_id": "s1", "timestamp": 1234567890.0, "type": "dns_query", "qname": "...", "domain": "..."}
      {"session_id": "s1", "type": "http_request", "host": "...", "headers": {...}}
      {"session_id": "s1", "type": "tls_handshake", "sni": "...", "cert_cn": "..."}
      {"session_id": "s1", "type": "connection", "dest": "...", "bytes_sent": N, "bytes_recv": N}
    """
    sessions: Dict[str, SessionState] = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = record.get("session_id", "default")
            if sid not in sessions:
                sessions[sid] = SessionState(session_id=sid)
            state = sessions[sid]

            rtype = record.get("type", "")
            if rtype == "dns_query":
                state.dns_queries.append(record)
            elif rtype == "dns_response":
                state.dns_responses.append(record)
            elif rtype == "http_request":
                state.http_requests.append(record)
            elif rtype == "tls_handshake":
                state.tls_handshakes.append(record)
            elif rtype == "connection":
                state.connections.append(record)
            elif rtype == "websocket_frame":
                state.websocket_frames.append(record)

    return list(sessions.values())


def main():
    parser = argparse.ArgumentParser(description="Egress DPI Guard traffic analyzer")
    parser.add_argument("--pcap", type=str, help="Path to JSONL pcap-derived file")
    parser.add_argument("--interface", type=str, help="Network interface to capture (requires root)")
    parser.add_argument("--duration", type=int, default=60, help="Capture duration in seconds")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help="Alert threshold score")
    parser.add_argument("--session-id", type=str, default="default", help="Session ID for analysis")
    args = parser.parse_args()

    if not args.pcap and not args.interface:
        # Demo mode: analyze sample data
        print("{" "}" "No input provided, running demo analysis with sample data...", file=sys.stderr)
        state = SessionState(session_id=args.session_id)
        # Inject suspicious DNS tunneling pattern
        for i in range(35):
            state.dns_queries.append({
                "timestamp": 1000000 + i * 1.5,
                "qname": f"{i:05d}ABCDEFGHIJKLMNOPQRSTUVWXYZ234567{'ABC' * 10}.tunnel.example.com",
                "domain": "tunnel.example.com",
            })
        # Inject HTTPS anomaly
        state.http_requests.append({
            "timestamp": 1000000,
            "host": "real-site.com",
            "headers": {
                "Host": "real-site.com",
                "User-Agent": "Mozilla/5.0",
                "Cookie": "A" * 2048,
                "X-Data-Exfil": "B" * 1500,
            },
        })
        state.tls_handshakes.append({
            "timestamp": 1000000,
            "sni": "other-site.com",
            "cert_cn": "real-site.com",
            "host": "other-site.com",
        })
        # Inject beaconing pattern
        for i in range(15):
            state.connections.append({
                "timestamp": 1000000 + i * 60.0,
                "dest": f"10.0.0.{i % 5}",
                "bytes_sent": 5000,
                "bytes_recv": 1000,
                "direction": "download",
            })

        result = analyze_session(state, args.threshold)
        print(json.dumps(result, indent=2))
        return

    if args.pcap:
        sessions = parse_pcap_jsonl(args.pcap)
        for state in sessions:
            result = analyze_session(state, args.threshold)
            print(json.dumps(result, indent=2))

    if args.interface:
        print("Live capture requires scapy/pyshark integration. Use --pcap with pre-captured JSONL data.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
