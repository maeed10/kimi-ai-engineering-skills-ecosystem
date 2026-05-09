# Profile Schemas

This document defines the YAML schema for each environment profile and the inheritance contract with `base.yaml`.

## Schema Overview

All profiles MUST declare:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | string | Yes | Schema version (must be `"1.0"`). |
| `description` | string | Yes | Human-readable purpose and risk posture. |
| `_inherits` | string | Yes | Must be `base.yaml`. |
| `_environment` | string | Yes | One of `development`, `staging`, `production`. |

## Inheritance Model

1. The profile loader reads `base.yaml` first.
2. The environment overlay is merged depth-first.
3. Lists are replaced, not merged, unless annotated with `!merge`.
4. `null` in an overlay deletes a base key (use sparingly).
5. The resulting document is validated against the profile schema.

## Base Schema (`base.yaml`)

```yaml
version: enum["1.0"]
description: string

sandbox:
  executor:
    image: string
    image_pull_policy: enum["Always", "IfNotPresent", "Never"]
    restart_policy: enum["always", "unless-stopped", "on-failure", "no"]
    graceful_shutdown_timeout: duration
    max_concurrent_jobs: integer(1..1000)
    job_queue_backend: enum["redis", "builtin", "sqs"]
    default_timeout: duration

security:
  sandbox_escape_prevention: boolean
  read_only_rootfs: boolean
  no_new_privileges: boolean
  seccomp_profile: string
  apparmor_profile: string
  capability_drops: list<enum[ALL | Linux capability names]>
  capability_additions: list<enum[Linux capability names]>  # overlay only
  image_verification:
    verify_signatures: boolean
    required_signers: list<string>  # email or SPIFFE ID
    cosign_keyring: path
    signature_retention: optional duration
    max_critical_cves: optional integer(0..)
    max_high_cves: optional integer(0..)
  network:
    tls_version_min: enum["1.2", "1.3"]
    client_auth_mode: enum["none", "optional", "require"]
    ca_cert_bundle: optional path
    allowed_ciphers: list<string>
    hsts_max_age: optional integer
    pin_prod_cert: optional boolean

vault:
  driver: enum["obsidian", "hashicorp", "aws"]
  obsidian:
    socket_path: path
    connection_timeout: duration
    max_retries: integer(0..10)
    mount_policy:
      mode: enum["development", "staging", "production"]
      allow_mock_secrets: boolean
      allowed_paths: list<string>
      denied_paths: optional list<string>
      require_approval: boolean
      dual_control_approval: optional boolean
      approval_timeout: duration
      audit_reads: boolean
      audit_writes: boolean
      audit_immutable_log: optional boolean
      max_ttl: duration
      reauth_interval: optional duration

policy_engine:
  endpoint: url
  decision_timeout: duration
  default_decision: enum["allow", "deny"]
  cache_ttl: duration
  policy_bundle_refresh: optional duration
  verify_policy_signatures: optional boolean
  policy_signer: optional string

observability:
  log_level: enum["DEBUG", "INFO", "WARN", "ERROR"]
  log_format: enum["json", "text"]
  metrics_enabled: boolean
  metrics_port: integer(1..65535)
  metrics_scrape_endpoint: optional url
  health_check_interval: duration
  tracing_enabled: boolean
  jaeger_endpoint: optional url
  alerting_log_level: optional enum["DEBUG", "INFO", "WARN", "ERROR"]
  log_forwarding:
    enabled: boolean
    endpoint: optional url
    buffer_size: optional integer
    tls_mutual_auth: optional boolean
    integrity_hash: optional enum["sha256", "sha384", "sha512"]

resource_limits:
  default:
    cpu_cores: number(0.1..128)
    memory_mb: integer(64..1048576)
    disk_mb: integer(128..1048576)
    ephemeral_storage_mb: integer(64..1048576)
    max_processes: integer(1..100000)

network:
  egress_policy: enum["unrestricted", "restricted", "deny-all"]
  dns_resolver: ipv4 | ipv6
  allowed_egress_hosts: list<string>
  proxy_mode: boolean
  proxy_endpoint: optional url
  proxy_tls: optional boolean
  dns_tls: optional boolean
```

---

## Development Overlay Schema

**Purpose:** Fast feedback, debuggability, local-only execution.

### Allowed Weakenings (relative to base)

| Key | Base Value | Allowed Dev Value | Rationale |
|-----|------------|-------------------|-----------|
| `security.read_only_rootfs` | `true` | `false` | Install dev tools at runtime. |
| `security.image_verification.verify_signatures` | `false` | `false` (same) | Dev builds are unsigned. |
| `security.network.client_auth_mode` | `optional` | `optional` (same) | No mTLS in local dev. |
| `policy_engine.default_decision` | `deny` | `allow` | Warn-only for rapid iteration. |
| `observability.log_level` | `INFO` | `DEBUG` | Verbose tracing. |
| `network.egress_policy` | `restricted` | `unrestricted` | Fetch any dependency. |
| `sandbox.executor.hot_reload` | absent | `true` | Code reload. |

### Required Dev Settings

```yaml
vault.obsidian.mount_policy:
  mode: development
  allow_mock_secrets: true
  allowed_paths: ["dev/*", "local/*"]
  require_approval: false
  audit_reads: false
  audit_writes: false
  max_ttl: 1h
```

### Security Annotations

- `capability_additions` MUST be limited to `SYS_PTRACE` and `DAC_READ_SEARCH`.
- `read_only_rootfs: false` MUST NOT be used in shared/multi-user environments.
- `network.egress_policy: unrestricted` MUST be blocked by network segmentation at the infrastructure layer.

---

## Staging Overlay Schema

**Purpose:** Production-equivalent hardening in an isolated namespace.

### Required Hardening (relative to base)

| Key | Base Value | Required Staging Value | Rationale |
|-----|------------|------------------------|-----------|
| `security.image_verification.verify_signatures` | `false` | `true` | Validate promotion candidate signatures. |
| `security.network.client_auth_mode` | `optional` | `require` | mTLS mandatory (prod-equivalent). |
| `security.network.tls_version_min` | `"1.2"` | `"1.3"` | Modern TLS only. |
| `policy_engine.default_decision` | `deny` | `deny` (same) | Strict enforcement. |
| `vault.obsidian.mount_policy.mode` | placeholder | `staging` | Explicit isolation mode. |

### Required Staging Settings

```yaml
security:
  capability_additions: []  # NONE
  image_verification:
    verify_signatures: true
    required_signers: [staging-ci@sandbox.internal, release-engineering@sandbox.internal]
  network:
    client_auth_mode: require
    tls_version_min: "1.3"

vault.obsidian.mount_policy:
  mode: staging
  allow_mock_secrets: false
  allowed_paths: ["staging/*"]
  denied_paths: ["production/*", "prod/*", "*production*"]
  require_approval: true
  audit_reads: true
  audit_writes: true
  max_ttl: 24h
```

### Isolation Requirements

- `vault.obsidian.socket_path` MUST differ from production.
- `policy_engine.endpoint` MUST resolve to staging-only infrastructure.
- `network.allowed_egress_hosts` MUST NOT include production endpoints.

---

## Production Overlay Schema

**Purpose:** Strict, hardened, fully audited runtime.

### Non-Negotiable Controls

The following values are HARD REQUIREMENTS. Any deviation fails validation.

| Key | Required Value | Failure Impact |
|-----|----------------|----------------|
| `security.capability_additions` | `[]` | Container escape risk. |
| `security.read_only_rootfs` | `true` | Persistence / tampering risk. |
| `security.no_new_privileges` | `true` | Privilege escalation risk. |
| `security.image_verification.verify_signatures` | `true` | Supply-chain compromise. |
| `security.network.client_auth_mode` | `require` | Unauthorized access risk. |
| `security.network.tls_version_min` | `"1.3"` | Downgrade attack risk. |
| `policy_engine.default_decision` | `deny` | Unauthorized action risk. |
| `vault.obsidian.mount_policy.mode` | `production` | Data leakage / incorrect vault. |
| `vault.obsidian.mount_policy.allow_mock_secrets` | `false` | Mock data in prod. |
| `vault.obsidian.mount_policy.require_approval` | `true` | Unapproved secret access. |
| `vault.obsidian.mount_policy.audit_reads` | `true` | Untracked secret access. |
| `vault.obsidian.mount_policy.audit_writes` | `true` | Untracked secret mutation. |
| `observability.log_level` | `WARN` or stricter | Excessive log volume / data leak. |
| `network.egress_policy` | `restricted` | Data exfiltration risk. |
| `sandbox.executor.hot_reload` | absent or `false` | Runtime code injection. |

### OBSIDIAN-001 Production Vault Mount Policy

Per Key Behavior #5, production MUST explicitly define:

```yaml
vault:
  driver: obsidian
  obsidian:
    mount_policy:
      mode: production
      allowed_paths:
        - "production/apps/*"
        - "production/infra/*"
        - "production/ci/*"
      denied_paths:
        - "*mock*"
        - "*dev*"
        - "*development*"
        - "*staging*"
      dual_control_approval: true
      audit_immutable_log: true
      max_ttl: 4h
      reauth_interval: 1h
```

### Audit Requirements

- `audit_immutable_log: true` — tamper-resistant append-only log.
- `log_forwarding.integrity_hash` — cryptographic checksum per batch.
- `policy_engine.verify_policy_signatures: true` — signed policy bundles.
- `security.network.pin_prod_cert: true` — certificate pinning.

### Capability Rules

- `capability_drops` MUST include `ALL`.
- `capability_additions` MUST be empty (`[]`).
- Any request to add capabilities requires C-level exception and security register entry.

---

## Validation Gate Schema

The `validate_profile.py` script enforces the following gates:

1. **Syntax Gate:** YAML is well-formed.
2. **Schema Gate:** All required keys present; types match schema.
3. **Inheritance Gate:** `_inherits` is `base.yaml`; `_environment` is valid.
4. **Security Gate:** No profile weakens base security without explicit annotation.
5. **Production Gate:** All non-negotiable controls pass.
6. **OBSIDIAN-001 Gate:** Production `mount_policy` is explicitly defined and valid.

### Gate Severity

| Gate | Failure Action |
|------|----------------|
| Syntax | Reject; do not deploy. |
| Schema | Reject; do not deploy. |
| Inheritance | Reject; do not deploy. |
| Security | Warn; block deployment until override approved. |
| Production | Reject; do not deploy. |
| OBSIDIAN-001 | Reject; do not deploy. |
