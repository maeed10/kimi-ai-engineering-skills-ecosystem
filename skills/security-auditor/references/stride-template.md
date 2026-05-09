# STRIDE Threat Model Template

Use this template to record STRIDE analysis results for each ADR-reviewed component.
One section per component / trust boundary.

## Component: <Name>

**ADR reference:** `<ADR-NNN>`  
**Data flows:** `<list flows>`  
**Trust boundaries crossed:** `<list boundaries>`  
**Reviewer:** `<name>`  
**Date:** `<YYYY-MM-DD>`

---

### Spoofing
| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Example: Attacker spoofs service identity | mTLS + certificate pinning | Low |

### Tampering
| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Example: Attacker modifies request payload in transit | Request signing + TLS 1.3 | Low |

### Repudiation
| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Example: Attacker denies performing an action | Immutable audit logs with non-repudiation | Low |

### Information Disclosure
| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Example: Attacker reads sensitive data in logs | Log redaction + field-level encryption | Medium |

### Denial of Service
| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Example: Attacker floods authentication endpoint | Rate limiting + CAPTCHA + WAF | Low |

### Elevation of Privilege
| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Example: Attacker escalates from user to admin | RBAC + least privilege + MFA | Low |

---

## Summary

| Category | Threats identified | Mitigated | Open |
|----------|-------------------|-----------|------|
| Spoofing | 0 | 0 | 0 |
| Tampering | 0 | 0 | 0 |
| Repudiation | 0 | 0 | 0 |
| Information Disclosure | 0 | 0 | 0 |
| Denial of Service | 0 | 0 | 0 |
| Elevation of Privilege | 0 | 0 | 0 |

**Overall residual risk:** `<Low / Medium / High / Critical>`  
**Decision:** `<Proceed / Mitigate before proceed / Block>`
