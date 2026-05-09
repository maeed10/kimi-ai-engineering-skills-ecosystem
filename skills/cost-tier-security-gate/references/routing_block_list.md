# Routing Block List

This document enumerates tasks, skill types, and patterns that are **permanently blocked** from external LLM routing via `gemini-router`, regardless of cost-tier classification or latency optimization.

**Principle**: If a task matches any entry in this block list, the routing decision is `BLOCKED` before cost or latency considerations are evaluated.

## Block List Categories

### 1. Secret and Credential Management

Any task that creates, reads, updates, deletes, rotates, or validates secrets, credentials, passwords, tokens, or API keys.

**Blocked Skills** (by pattern or name):
- `secret-manager`
- `vault-*`
- `credential-*`
- `password-*`
- `token-*`
- `api-key-*`
- `kms-*`
- `hsm-*`
- `secrets-*`
- `*keystore*`
- `*cert-manager*`
- `*oauth*`

**Blocked Task Patterns**:
- `rotate.*credential`
- `generate.*password`
- `create.*api.*key`
- `renew.*token`
- `sign.*jwt`
- `validate.*secret`
- `read.*secret`
- `write.*secret`
- `backup.*vault`
- `unseal.*vault`

### 2. Cryptographic Operations

Any task that performs encryption, decryption, signing, verification, key generation, or cryptographic protocol handling.

**Blocked Skills**:
- `crypto-*`
- `encrypt-*`
- `decrypt-*`
- `sign-*`
- `verify-*`
- `pgp-*`
- `gpg-*`
- `tls-*`
- `ssl-*`
- `certificate-*`
- `keygen-*`
- `*cipher*`
- `*hash*`

**Blocked Task Patterns**:
- `encrypt.*file`
- `decrypt.*message`
- `sign.*document`
- `verify.*signature`
- `generate.*key.*pair`
- `create.*csr`
- `issue.*certificate`
- `rotate.*signing.*key`
- `derive.*key`

### 3. Policy Engine and Validation

Any task that enforces, validates, modifies, or audits security policies, guardrails, or compliance rules.

**Blocked Skills**:
- `policy-*`
- `guardrail-*`
- `compliance-*`
- `security-policy-*`
- `rules-engine-*`
- `validation-*`
- `audit-*`
- `*policy*engine*`
- `*compliance*check*`
- `*security*rule*`

**Blocked Task Patterns**:
- `validate.*policy`
- `enforce.*guardrail`
- `audit.*access`
- `check.*compliance`
- `modify.*security.*rule`
- `disable.*guardrail`
- `bypass.*policy`
- `review.*security.*config`
- `assess.*risk`

### 4. Sandbox and Code Execution (Untrusted Input)

Any task that executes code, commands, or scripts from untrusted sources, or manages sandbox boundaries.

**Blocked Skills**:
- `sandbox-*`
- `code-exec-*`
- `shell-*`
- `terminal-*`
- `eval-*`
- `*unsafe*`
- `*untrusted*`
- `*sandbox*escape*`

**Blocked Task Patterns**:
- `execute.*user.*code`
- `run.*untrusted.*script`
- `eval.*input`
- `escape.*sandbox`
- `breakout.*container`
- `privilege.*escalation`
- `exploit.*detection`
- `malware.*analysis`

### 5. Identity, Access Management, and RBAC

Any task that manages user identities, roles, permissions, access controls, or authentication configurations.

**Blocked Skills**:
- `iam-*`
- `rbac-*`
- `auth-*`
- `identity-*`
- `sso-*`
- `ldap-*`
- `permission-*`
- `access-control-*`
- `user-management-*`
- `*privilege*`

**Blocked Task Patterns**:
- `create.*role`
- `assign.*permission`
- `modify.*rbac`
- `grant.*access`
- `revoke.*privilege`
- `configure.*sso`
- `sync.*identity`
- `reset.*admin.*password`
- `elevate.*privilege`

### 6. Audit, Logging, and Security Monitoring

Any task that reads, modifies, or manages security audit logs, monitoring rules, or incident response data.

**Blocked Skills**:
- `audit-log-*`
- `security-monitor-*`
- `siem-*`
- `incident-response-*`
- `forensics-*`
- `log-*` (when security context is inferred)
- `*security*event*`
- `*intrusion*detection*`

**Blocked Task Patterns**:
- `read.*audit.*log`
- `delete.*security.*event`
- `modify.*monitor.*rule`
- `suppress.*alert`
- `tamper.*log`
- `exfiltrate.*audit.*data`
- `investigate.*breach`

### 7. Network Security and Firewall

Any task that modifies network security boundaries, firewall rules, or segmentation policies.

**Blocked Skills**:
- `firewall-*`
- `network-policy-*`
- `security-group-*`
- `waf-*`
- `vpn-*`
- `*network*segment*`
- `*traffic*filter*`

**Blocked Task Patterns**:
- `open.*firewall.*port`
- `allow.*inbound.*traffic`
- `modify.*security.*group`
- `disable.*waf.*rule`
- `bypass.*network.*policy`
- `reconfigure.*vpn`

### 8. Supply Chain and Artifact Signing

Any task that signs, verifies, or manages software artifacts, SBOMs, or supply chain integrity.

**Blocked Skills**:
- `artifact-sign-*`
- `sbom-*`
- `supply-chain-*`
- `notary-*`
- `sigstore-*`
- `checksum-*`
- `*artifact*verify*`

**Blocked Task Patterns**:
- `sign.*artifact`
- `verify.*checksum`
- `publish.*sbom`
- `attest.*build`
- `sign.*container.*image`
- `verify.*provenance`

## Block List Matching Rules

1. **Exact Match**: Skill name exactly matches a blocked skill name → BLOCKED
2. **Pattern Match**: Skill name matches a glob/wildcard pattern (e.g., `secret-*`) → BLOCKED
3. **Regex Match**: Task description matches a blocked task pattern (case-insensitive) → BLOCKED
4. **Metadata Match**: Skill metadata includes `security-sensitive: true` or tags `security-critical` → BLOCKED

## Exceptions and Escalation

If a legitimate use case requires routing a blocked skill or task pattern to Gemini, the exception must follow this process:

1. **File an exception request** with:
   - Task/skill name
   - Business justification
   - Risk assessment
   - Proposed mitigations (data masking, output filtering, etc.)
2. **Security review** by the security team.
3. **Temporary exception grant** with:
   - Expiration date (max 30 days)
   - Scoped to specific task IDs or environments
   - Logged in audit system as `BLOCK_LIST_OVERRIDE`
4. **No permanent exceptions** for SECURITY-CRITICAL tasks.

## Versioning

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | Initial | Baseline block list covering 8 security categories |

