# Security Settings Matrix

Reference table for every security-relevant setting across environments. Use this when auditing configuration drift, onboarding operators, or evaluating exception requests.

## Legend

| Symbol | Meaning |
|--------|---------|
| 🔒 | Hardened / enforced |
| ⚠️ | Weakened for operational need |
| 🔓 | Permissive (dev only) |
| ❌ | Forbidden in this environment |
| ✅ | Required in this environment |

---

## Core Security Settings

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `sandbox_escape_prevention` | ✅ true | ✅ true | ✅ true | ✅ true | Fundamental guardrail; never disabled. |
| `read_only_rootfs` | ✅ true | ⚠️ false | ✅ true | ✅ true | Dev needs runtime package installation. |
| `no_new_privileges` | ✅ true | ✅ true | ✅ true | ✅ true | Prevents `setuid` escalation via `prctl(PR_SET_NO_NEW_PRIVS, 1)`. |
| `seccomp_profile` | `runtime/default` | `runtime/default` | `runtime/default` | `runtime/default` | Block dangerous syscalls. Custom profiles require security review. |
| `apparmor_profile` | `sandbox-executor-default` | `sandbox-executor-default` | `sandbox-executor-default` | `sandbox-executor-default` | Mandatory access control for file/network operations. |
| `hidepid` | absent | absent | absent | ✅ 2 | Hide other users' processes in `/proc` (infoleak prevention). |
| `proc_mount` | absent | absent | absent | ✅ default | Restrict `/proc` to default view only. |

## Capabilities

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `capability_drops` | `[ALL]` | `[ALL]` | `[ALL]` | `[ALL]` | Drop all Linux capabilities by default. |
| `capability_additions` | `[]` | `[SYS_PTRACE, DAC_READ_SEARCH]` | `[]` | `[]` | Dev only: debuggers and fast file traversal. Staging/Prod: NONE. |

### Capability Detail: Development Exceptions

- `SYS_PTRACE` — Required for `gdb`, `delve`, `strace` in dev containers.
- `DAC_READ_SEARCH` — Bypasses file read permission checks; speeds up large monorepo operations.

**Risk acceptance:** Dev runs on local workstations with no sensitive data. Network segmentation prevents lateral movement. Reviewed Q1-2024; expires Q1-2025.

---

## Image Verification

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `verify_signatures` | false | 🔓 false | ✅ true | ✅ true | Dev builds are unsigned local artifacts. |
| `required_signers` | `[]` | `[]` | 2 signers | 2 signers | Dual-control signing (release-eng + sec-ops). |
| `cosign_keyring` | `/etc/sandbox/cosign.pub` | dev keyring | staging keyring | prod keyring | Environment-specific trust roots prevent cross-env trust escalation. |
| `max_critical_cves` | absent | absent | 0 | 0 | Block images with any critical CVEs. |
| `max_high_cves` | absent | absent | 2 | 2 | Allow up to 2 high CVEs with documented compensating controls. |

---

## Network Security

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `tls_version_min` | 1.2 | 1.2 | 1.3 | 1.3 | Staging/Prod require TLS 1.3 to eliminate downgrade vectors. |
| `client_auth_mode` | optional | optional | require | require | mTLS mandatory in staging and production for mutual authentication. |
| `ca_cert_bundle` | absent | absent | staging CA | prod CA | Isolated certificate authorities per environment. |
| `allowed_ciphers` | AEAD + CBC | AEAD + CBC | AEAD-only | AEAD-only | Remove CBC modes in staging/prod (Lucky13, padding oracle risks). |
| `hsts_max_age` | absent | absent | absent | 31536000 | HTTP Strict Transport Security in prod. |
| `pin_prod_cert` | absent | absent | absent | true | Pin expected server certificate to detect MITM. |

### Cipher Suite Evolution

**Base / Development (broader compatibility):**
- `TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256`
- `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`
- `TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256`
- `TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384`

**Staging / Production (modern only):**
- `TLS_AES_128_GCM_SHA256`
- `TLS_AES_256_GCM_SHA384`
- `TLS_CHACHA20_POLY1305_SHA256`

---

## Vault (OBSIDIAN Driver)

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `driver` | obsidian | obsidian | obsidian | obsidian | Unified vault driver across environments. |
| `socket_path` | `/run/obsidian/vault.sock` | mock path | `/run/obsidian/vault-staging.sock` | `/run/obsidian/vault-prod.sock` | Isolated sockets prevent cross-environment mount. |
| `mount_policy.mode` | placeholder | development | staging | production | OBSIDIAN-001: explicit mode per environment. |
| `allow_mock_secrets` | absent | 🔓 true | ✅ false | ✅ false | Dev uses mock secrets for offline work. |
| `allowed_paths` | absent | `["dev/*", "local/*"]` | `["staging/*"]` | `["production/apps/*", "production/infra/*", "production/ci/*"]` | Exact allow-lists per environment. |
| `denied_paths` | absent | absent | `["production/*", ...]` | `["*mock*", "*dev*", "*staging*"]` | Defense-in-depth deny lists. |
| `require_approval` | absent | 🔓 false | ✅ true | ✅ true | Prevents automated/unattended secret access. |
| `dual_control_approval` | absent | absent | absent | ✅ true | Production requires two human approvers. |
| `approval_timeout` | absent | absent | 15m | 30m | Prod: longer timeout for on-call paging latency. |
| `audit_reads` | absent | 🔓 false | ✅ true | ✅ true | Every secret read is logged. |
| `audit_writes` | absent | 🔓 false | ✅ true | ✅ true | Every secret write/rotation is logged. |
| `audit_immutable_log` | absent | absent | absent | ✅ true | Append-only, tamper-resistant log storage. |
| `max_ttl` | absent | 1h | 24h | 4h | Prod: shorter TTL for blast-radius reduction. |
| `reauth_interval` | absent | absent | absent | 1h | Prod: force re-authentication every hour. |

### OBSIDIAN-001 Compliance Check

Production `mount_policy` MUST:
1. Be explicitly defined (no inheritance default).
2. Use `mode: production`.
3. List `allowed_paths` with only `production/*` prefixes.
4. Set `allow_mock_secrets: false`.
5. Enable `audit_reads`, `audit_writes`, and `audit_immutable_log`.

---

## Policy Engine

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `default_decision` | deny | 🔓 allow | ✅ deny | ✅ deny | Dev warn-only to unblock iteration. |
| `decision_timeout` | 2s | 10s (relaxed) | 2s | 2s | Dev: longer timeout for local policy engine. |
| `policy_bundle_refresh` | absent | absent | 5m | 2m | Prod refreshes policies more frequently. |
| `verify_policy_signatures` | absent | absent | absent | ✅ true | Prod verifies policy bundle signatures. |
| `policy_signer` | absent | absent | absent | `security-operations@sandbox.internal` | Only sec-ops can sign prod policies. |

---

## Observability & Audit

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `log_level` | INFO | 🔓 DEBUG | INFO | WARN | Prod: WARN reduces volume; ERROR+ is alerted. |
| `alerting_log_level` | absent | absent | ERROR | ERROR | ERROR and above trigger paging. |
| `tracing_enabled` | false | ✅ true | ✅ true | ✅ true | Always-on tracing for request path analysis. |
| `log_forwarding.enabled` | absent | absent | ✅ true | ✅ true | Centralized log aggregation. |
| `log_forwarding.tls_mutual_auth` | absent | absent | absent | ✅ true | mTLS to SIEM to prevent log injection. |
| `log_forwarding.integrity_hash` | absent | absent | absent | ✅ sha256 | Detect tampering in transit. |

---

## Network Egress

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `egress_policy` | restricted | 🔓 unrestricted | ✅ restricted | ✅ restricted | Dev: broad access for package managers. |
| `allowed_egress_hosts` | `[]` | `["*"]` | staging domains | prod domains | Explicit allow-list in staging/prod. |
| `proxy_mode` | false | false | ✅ true | ✅ true | All egress through audited proxy. |
| `proxy_tls` | absent | absent | absent | ✅ true | Encrypt proxy tunnel in prod. |
| `dns_tls` | absent | absent | absent | ✅ true | DNS-over-TLS for all lookups. |
| `dns_resolver` | `8.8.8.8` | `8.8.8.8` | `10.0.1.10` | `10.0.0.10` | Internal DNS in staging/prod. |

---

## Resource Limits

| Setting | Base | Development | Staging | Production | Rationale |
|---------|------|-------------|---------|------------|-----------|
| `cpu_cores` | 1.0 | 4.0 | 2.0 | 1.0 | Prod: conservative sizing for density. |
| `memory_mb` | 512 | 4096 | 2048 | 1024 | Prod: limit per-job memory. |
| `disk_mb` | 2048 | 8192 | 4096 | 2048 | Prod: standard disk quota. |
| `ephemeral_storage_mb` | 1024 | 4096 | 2048 | 512 | Prod: minimal ephemeral storage. |
| `max_processes` | 100 | 500 | 200 | 50 | Prod: tight fork-bomb prevention. |

---

## Exception Process

Any deviation from this matrix in staging or production requires:

1. **Risk Assessment** — Document attack scenario and compensating controls.
2. **Security Review** — Approved by Security Engineering.
3. **C-level Sign-off** — For production weakening of non-negotiable controls.
4. **Register Entry** — Logged in `security-exceptions.yml` with expiration date.
5. **Automated Flagging** — `validate_profile.py` flags exceptions during CI.

### Exception Expiration

- Temporary exceptions: 30 days, renewable once.
- Long-term exceptions: 90 days, requires re-review.
- Permanent exceptions: Not permitted for non-negotiable controls.
