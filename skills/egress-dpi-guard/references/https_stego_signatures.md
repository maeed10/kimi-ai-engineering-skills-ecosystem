# HTTPS Steganography Detection Signatures

## Overview

HTTPS steganography hides data in TLS handshake parameters, HTTP headers, padding, or timing patterns. Since TLS payload is encrypted, detection relies on metadata analysis and side-channel inspection.

## Signatures

### SIG-HTTPS-001: Oversized HTTP Headers
- **Trigger**: HTTP request headers total size >4KB, OR any single header value >1KB
- **Severity**: medium
- **Targets**: `Cookie`, `X-*`, `Authorization`, `User-Agent`, custom headers
- **Rationale**: Normal headers are <1KB total; exfil tools embed data in padded headers

### SIG-HTTPS-002: TLS Record Padding Anomaly
- **Trigger**: >80% of TLS records in a connection have length divisible by 16 or 32
- **Severity**: high
- **Rationale**: Covert channels pad data to fixed block sizes to blend with normal encryption

### SIG-HTTPS-003: Suspicious User-Agent
- **Trigger**: UA string matches known patterns OR is missing/empty
- **Patterns**:
  - `curl/*`, `wget/*`, `python-requests/*` from sandboxed browser sessions
  - Empty or missing UA on HTTPS requests
  - UA length >200 characters with high entropy (>3.8)
- **Severity**: low (medium if combined with SIG-HTTPS-001)

### SIG-HTTPS-004: Slowloris-Style Exfiltration
- **Trigger**: Request body sent at <1 byte/sec sustained for >30 seconds
- **Severity**: high
- **Rationale**: Slow data drip avoids volume-based detection; legitimate streaming maintains higher throughput

### SIG-HTTPS-005: SNI/Host Mismatch
- **Trigger**: TLS SNI does not match HTTP Host header, OR neither matches certificate CN/SAN
- **Severity**: high
- **Rationale**: Domain fronting and misdirected tunnels cause SNI mismatches

### SIG-HTTPS-006: Certificate Anomaly
- **Trigger**: Any of:
  - Self-signed certificate on a whitelisted domain
  - Certificate from unknown/unexpected CA
  - Certificate validity period <7 days or >2 years
  - Missing Certificate Transparency SCT extensions
- **Severity**: medium (high for whitelisted domains)

### SIG-HTTPS-007: WebSocket Hijacking
- **Trigger**: WebSocket upgrade followed by:
  - Binary frames with entropy >4.0
  - Frame payload consistently at exact MTU boundaries
  - Unexpected binary frames when text was negotiated
- **Severity**: high

### SIG-HTTPS-008: ALPN/Protocol Downgrade
- **Trigger**: Client offers ALPN but server selects `http/1.1` when `h2` was available, on a known h2-supporting host
- **Severity**: low
- **Rationale**: Downgrade may indicate intercepting proxy or tunnel endpoint

### SIG-HTTPS-009: Session Resumption Abuse
- **Trigger**: >50 TLS session resumptions/minute to different hosts using same session ticket
- **Severity**: medium
- **Rationale**: Session tickets can embed encoded state; rapid reuse across hosts is anomalous

## Scoring Matrix

| Signature | Base Points | Multiplier Condition |
|-----------|-------------|---------------------|
| SIG-HTTPS-001 | 10 | x2 if Cookie header >1KB |
| SIG-HTTPS-002 | 25 | x2 if >95% records padded |
| SIG-HTTPS-003 | 5 | x3 if UA entropy >4.0 |
| SIG-HTTPS-004 | 25 | x2 if sustained >120 sec |
| SIG-HTTPS-005 | 20 | x2 if cert also anomalous |
| SIG-HTTPS-006 | 15 | x2 on whitelisted domain |
| SIG-HTTPS-007 | 25 | x2 if combined with SIG-HTTPS-004 |
| SIG-HTTPS-008 | 5 | x2 if repeated 5+ times |
| SIG-HTTPS-009 | 15 | x2 if >100 resumptions/min |

**Threshold**: Score >= 50 triggers alert to `drift-monitor`.

## Legitimate Bypasses

Do NOT alert on:
- Large `Authorization: Bearer` headers from OAuth flows (documented endpoints)
- Known API clients with large custom headers (e.g., AWS SigV4, GCP tokens)
- Certificate pinning by mobile SDKs with bundled certs
- WebRTC or video streaming traffic with naturally large frames
- Corporate proxy environments with统一 UA injection
