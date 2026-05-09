---
name: egress-dpi-guard
description: Egress deep packet inspection skill that detects data exfiltration via DNS tunneling, HTTPS steganography, and protocol abuse within allowed network traffic. Use when sandbox-executor permits network access, when processing sensitive data, or when defending against advanced prompt injection exfiltration. Feeds findings to drift-monitor and policy-engine.
---

# Egress DPI Guard

## Overview

Inspect all outbound network traffic from sandboxes to detect data exfiltration attempts hidden within permitted protocols. Operates as a passive layer on the egress path, emitting alerts to `drift-monitor` and `policy-engine` when anomalies exceed thresholds.

## Core Capabilities

### 1. DNS Inspection

Detect DNS tunneling via:
- **High query rate**: >30 queries/minute to a single domain or >100 queries/minute total
- **Large TXT records**: response size >512 bytes or query name >100 characters
- **Unusual subdomain patterns**: base32/hex encoded subdomains, excessive subdomain depth (>5 labels)
- **Entropy analysis**: Shannon entropy >3.5 on subdomain labels indicates encoded data
- **NXDOMAIN flooding**: >10 NXDOMAIN responses/minute suggesting DGA or probing

When triggered: emit `{type: "dns_tunnel_alert", domain, entropy, query_rate, encoded_bytes_estimate}` to `drift-monitor`.

### 2. HTTPS Inspection

Detect steganography in TLS-encrypted traffic via:
- **Oversized headers**: HTTP headers >4KB total or single header >1KB
- **Padding anomalies**: TLS record length consistently at multiples of 16 or 32 bytes (indicative of padded covert channel)
- **Unusual user-agent**: non-standard UA strings, missing UA, or UA matching known exfil tools
- **Slowloris-style exfiltration**: request body chunks arriving slower than 1 byte/sec sustained for >30 seconds
- **SNI mismatch**: TLS SNI does not match Host header or certificate CN
- **Certificate pinning abuse**: unexpected CA issuers or self-signed certs on whitelisted domains

When triggered: emit `{type: "https_stego_alert", host, anomaly_type, bytes_exfiltrated_estimate}` to `drift-monitor`.

### 3. Connection Pattern Analysis

Track aggregate behavior:
- **Byte ratio anomaly**: upload/download ratio >0.5 on connections that should be download-heavy (e.g., GET requests)
- **Connection frequency**: >20 new connections/minute to unique destinations
- **Timing patterns**: connections at perfectly regular intervals (<1% jitter) suggesting automated beaconing
- **Duration clustering**: connection durations concentrated in narrow bands (e.g., all 30-31 seconds)

When triggered: emit `{type: "pattern_alert", pattern_type, connection_count, confidence}` to `policy-engine`.

### 4. Protocol-Aware Rules

| Protocol | Inspection Rule | Action on Trigger |
|----------|----------------|-------------------|
| HTTP | Inspect query params for base64/hex encoded data >100 chars | Log + alert to drift-monitor |
| HTTPS | Check certificate transparency, SNI validity, ALPN negotiation | Log + alert + optional block |
| DNS | Entropy + rate + subdomain depth analysis | Log + alert + rate-limit |
| WebSocket | Frame size analysis, masked payload entropy, unexpected binary frames | Log + alert + terminate |

### 5. Integration

Feed findings to downstream systems:
- **`drift-monitor`**: all alerts include `session_id`, `timestamp`, `severity` (low/medium/high/critical)
- **`policy-engine`**: medium+ alerts include recommended action (`log` / `rate_limit` / `block` / `terminate_session`)
- Alert format: `{alert_id, session_id, timestamp, severity, type, details, recommended_action}`

## Workflow

1. **Intercept**: capture all egress packets from sandbox network namespace
2. **Classify**: identify protocol (DNS/HTTPS/WS/HTTP) from port and payload heuristics
3. **Inspect**: run protocol-specific detection rules (see references/)
4. **Score**: aggregate anomaly scores per session; threshold = 50 points
   - DNS entropy >3.5: +15 pts
   - DNS query rate >100/min: +20 pts
   - HTTPS oversized header: +10 pts
   - Timing beaconing detected: +25 pts
   - SNI mismatch: +20 pts
5. **Escalate**: if score >= 50, emit alert to drift-monitor + policy-engine
6. **Act**: policy-engine decides: log, rate-limit, block, or terminate session

## Scripts

- `scripts/analyze_egress.py` — analyze pcap or live traffic for exfiltration patterns; returns JSON alert stream

## References

- `references/dns_tunneling_signatures.md` — complete DNS tunneling detection signatures with entropy thresholds
- `references/https_stego_signatures.md` — HTTPS steganography detection patterns and heuristics
