# DNS Tunneling Detection Signatures

## Overview

DNS tunneling encodes data in subdomain labels or TXT record payloads. This reference defines the complete detection signature set for the egress DPI guard.

## Signatures

### SIG-DNS-001: High Query Rate
- **Trigger**: >30 queries/minute to a single domain, OR >100 queries/minute total egress DNS
- **Severity**: medium
- **Rationale**: Legitimate applications rarely exceed 20 DNS queries/minute sustained

### SIG-DNS-002: Large TXT Response
- **Trigger**: DNS TXT response RDATA length >512 bytes
- **Severity**: high
- **Rationale**: TXT records are commonly used for tunneling; legitimate TXT records (SPF, DKIM) are typically <255 bytes

### SIG-DNS-003: Encoded Subdomain
- **Trigger**: subdomain label matches base32 (`^[A-Z2-7]{20,}$`) or hex (`^[0-9a-f]{40,}$`) pattern
- **Severity**: high
- **Rationale**: High-length alphanumeric strings in subdomains strongly indicate encoded exfiltration data

### SIG-DNS-004: Excessive Subdomain Depth
- **Trigger**: query name contains >5 labels (e.g., `a.b.c.d.e.target.com`)
- **Severity**: medium
- **Rationale**: Each label can carry ~63 bytes of encoded data; deep nesting maximizes throughput

### SIG-DNS-005: High Entropy Query Name
- **Trigger**: Shannon entropy of full query name (excluding TLD) >3.5 bits/character
- **Severity**: medium
- **Rationale**: Natural language domain names have entropy ~2.0-2.8; encoded data approaches 4.0+ (random)

### SIG-DNS-006: NXDOMAIN Flood
- **Trigger**: >10 NXDOMAIN responses/minute from unique query names
- **Severity**: low (elevate to medium if combined with SIG-DNS-005)
- **Rationale**: Domain Generation Algorithms (DGAs) and probing produce many NXDOMAIN responses

### SIG-DNS-007: Query Name Length Anomaly
- **Trigger**: query FQDN total length >200 characters
- **Severity**: medium
- **Rationale**: Maximum practical FQDN is 253 bytes; tunnelers push toward this limit

## Scoring Matrix

| Signature | Base Points | Multiplier Condition |
|-----------|-------------|---------------------|
| SIG-DNS-001 | 20 | x2 if same subdomain pattern |
| SIG-DNS-002 | 25 | x1.5 if multiple large TXT in session |
| SIG-DNS-003 | 25 | x2 if both base32 and hex seen |
| SIG-DNS-004 | 10 | x1.5 if >8 labels |
| SIG-DNS-005 | 15 | x2 if entropy >4.0 |
| SIG-DNS-006 | 5 | x3 if paired with SIG-DNS-005 |
| SIG-DNS-007 | 10 | x2 if length >400 |

**Threshold**: Score >= 50 triggers alert to `drift-monitor`.

## Entropy Calculation

```python
def shannon_entropy(data: str) -> float:
    from math import log2
    from collections import Counter
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    return -sum((c / length) * log2(c / length) for c in counts.values())
```

## Legitimate Bypasses

The following should NOT trigger alerts:
- DNS-SD (Service Discovery) queries (`_service._tcp.local.`)
- Certificate Transparency DNS queries (`_cloudflare-challenge.`)
- Large TXT records from known CDNs with documented large responses
- Queries to `localhost`, `*.internal`, `*.local` (internal zones)
