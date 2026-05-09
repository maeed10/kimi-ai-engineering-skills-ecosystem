---
name: config-profile-manager
description: Environment-specific configuration profile manager with validated dev/staging/production profiles for sandbox-executor and policy-engine. Use when setting up environments, promoting configs, or auditing security setting drift. Enforces inheritance model, validation gates, and security setting audits.
---

# config-profile-manager

Manages environment-specific configuration profiles (`development`, `staging`, `production`) with validated, version-controlled settings. Prevents manual derivation of production configs from development templates.

## Problem Statement

The original setup had a single `sandbox-executor.yaml` with inline comments like "change this for production." This pattern caused:

- **Production misconfiguration:** Operators manually edited dev templates and missed critical security toggles.
- **Configuration drift:** Staging and production configs diverged silently over time.
- **Untracked weakenings:** `verify_signatures: false` copied from dev into production during a midnight incident.
- **OBSIDIAN-001 violations:** Vault mount policies were left at dev defaults, granting production access to mock secrets.

This skill replaces the one-file-plus-comments anti-pattern with an inheritance-based, validated profile system.

---

## Directory Layout

```
config-profile-manager/
├── profiles/
│   ├── base.yaml               # Common settings; never edited per environment
│   ├── development.yaml        # Permissive, fast feedback
│   ├── staging.yaml              # Production-equivalent, isolated
│   └── production.yaml         # Strict, mTLS, verify_signatures, OBSIDIAN-001
├── references/
│   ├── profile_schemas.md       # YAML schemas and gate definitions
│   └── security_settings_matrix.md  # Per-environment settings + rationale
├── scripts/
│   └── validate_profile.py      # Validation gate (CI / pre-deploy)
└── SKILL.md                     # This file
```

---

## Profile Structure

### `profiles/base.yaml`

- Contains **common settings** shared by all environments.
- Defines the **security baseline** (e.g., `capability_drops: [ALL]`, `read_only_rootfs: true`).
- **Never** modified for a one-off environment change. Changes here require review because they affect every environment.

### `profiles/development.yaml`

- **Purpose:** Fast feedback loops, local debugging, rapid iteration.
- **Posture:** Permissive with documented risk acceptance.
- **Key weakenings (acceptable in dev only):**
  - `read_only_rootfs: false` (install dev tools at runtime)
  - `capability_additions: [SYS_PTRACE, DAC_READ_SEARCH]` (debuggers)
  - `network.egress_policy: unrestricted` (fetch dependencies)
  - `policy_engine.default_decision: allow` (warn-only)
  - `vault.obsidian.mount_policy.allow_mock_secrets: true`
- **Infrastructure safeguard:** Network segmentation prevents dev workloads from reaching staging/prod endpoints.

### `profiles/staging.yaml`

- **Purpose:** Validate promotion candidates in a production-equivalent, isolated environment.
- **Posture:** Same hardening as production, different trust boundaries.
- **Key hardening:**
  - `verify_signatures: true`
  - `client_auth_mode: require` (mTLS)
  - `tls_version_min: "1.3"`
  - `capability_additions: []` (all caps dropped)
- **Isolation controls:**
  - Separate vault socket (`vault-staging.sock`)
  - `vault.obsidian.mount_policy.denied_paths` blocks all `production/*` paths
  - `network.allowed_egress_hosts` excludes production endpoints
  - Dedicated staging CA (`staging-ca.crt`)

### `profiles/production.yaml`

- **Purpose:** Strict, audited, tamper-resistant runtime.
- **Posture:** Non-negotiable controls; any exception requires C-level sign-off.
- **Key hardening:**
  - `verify_signatures: true` (mandatory, dual-control signers)
  - `client_auth_mode: require` (mTLS)
  - `capability_additions: []` + `capability_drops: [ALL]`
  - `read_only_rootfs: true`, `no_new_privileges: true`
  - `hidepid: 2`, `proc_mount: default`
- **Network:** TLS 1.3 only, modern AEAD ciphers, HSTS, certificate pinning.
- **Vault (OBSIDIAN-001):** Explicit `mount_policy` with `mode: production`, dual-control approval, immutable audit logs, 4h TTL, 1h reauth.
- **Policy:** Signed policy bundles, deny-by-default.
- **Observability:** WARN logging, encrypted + integrity-hashed log forwarding to SIEM.

---

## Inheritance Model

### How Merging Works

1. Loader reads `base.yaml` into a base document.
2. Loader reads the environment overlay (e.g., `production.yaml`).
3. Overlay is **deep-merged** into the base:
   - Dictionaries are merged recursively.
   - Lists are **replaced**, not concatenated.
   - `null` in an overlay deletes the base key (use sparingly).
4. Metadata keys (`_inherits`, `_environment`) are copied directly.

### Why Inheritance?

- **DRY:** Common values live once in `base.yaml`.
- **Single source of truth:** A security fix in base propagates to all environments.
- **Diff clarity:** Environment overlays only show what differs.
- **Auditability:** `git diff` on an overlay reveals intentional environment-specific choices.

### Adding a New Environment

1. Copy `profiles/staging.yaml` as a template.
2. Rename `_environment` and adjust `description`.
3. Update trust boundaries (CA certs, endpoints, sockets).
4. Run validation:
   ```bash
   python scripts/validate_profile.py -p profiles/newenv.yaml -b profiles/base.yaml --strict
   ```

---

## Validation Gate

### `scripts/validate_profile.py`

Run before every deployment (CI pipeline, operator CLI, GitOps controller).

```bash
# Validate production profile
python scripts/validate_profile.py -p profiles/production.yaml -b profiles/base.yaml

# Validate with strict mode (warnings become errors)
python scripts/validate_profile.py -p profiles/staging.yaml -b profiles/base.yaml --strict

# JSON output for CI parsers
python scripts/validate_profile.py -p profiles/production.yaml -b profiles/base.yaml --json

# Debug: print merged configuration
python scripts/validate_profile.py -p profiles/development.yaml -b profiles/base.yaml --verbose
```

### Gates (in order)

| Gate | Checks | Failure Action |
|------|--------|--------------|
| **SYNTAX** | YAML is well-formed | Reject; do not deploy |
| **SCHEMA** | Required keys present; `_inherits` == `base.yaml`; `_environment` valid | Reject; do not deploy |
| **INHERITANCE** | Base keys preserved; merge succeeded | Reject; do not deploy |
| **SECURITY** | No weakening relative to base without annotation | Warn (dev) / Block (staging, prod) |
| **PRODUCTION** | All non-negotiable controls match hard requirements | Reject; do not deploy |
| **OBSIDIAN-001** | Production `vault.obsidian.mount_policy` explicitly defined and valid | Reject; do not deploy |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Validated successfully |
| 1 | Syntax / schema / inheritance error |
| 2 | Production gate failure |
| 3 | OBSIDIAN-001 gate failure |
| 4 | General validation error (e.g., missing PyYAML) |

---

## Security Setting Audit

### When to Audit

- Before promoting a config from dev → staging → production.
- After any edit to `base.yaml` (cascade check all environments).
- During quarterly configuration drift review.
- When onboarding a new operator or environment.

### Audit Procedure

1. **Load the matrix:**
   ```bash
   cat references/security_settings_matrix.md
   ```

2. **Run validation on every profile:**
   ```bash
   for env in development staging production; do
     echo "=== Auditing $env ==="
     python scripts/validate_profile.py -p profiles/${env}.yaml -b profiles/base.yaml --strict
   done
   ```

3. **Compare effective (merged) configs:**
   ```bash
   python scripts/validate_profile.py -p profiles/staging.yaml -b profiles/base.yaml --verbose | \
     diff - <(python scripts/validate_profile.py -p profiles/production.yaml -b profiles/base.yaml --verbose)
   ```
   Any unexpected delta is drift and must be explained.

4. **Check for exceptions without expiration:**
   Review `security-exceptions.yml` (external register). Flag any expired entries.

### Drift Detection Rules

The validator automatically flags these as drift:

- `security.read_only_rootfs` weakened from `true` to `false` in staging or production.
- `security.image_verification.verify_signatures` set to `false` in staging or production.
- `security.network.client_auth_mode` below `require` in staging or production.
- `policy_engine.default_decision` set to `allow` in staging or production.
- `vault.obsidian.mount_policy.allow_mock_secrets` set to `true` in staging or production.
- `observability.log_level` below `WARN` in production.
- `network.egress_policy` set to `unrestricted` in staging or production.

---

## Promotion Workflow

### dev → staging

1. Developer finalizes feature in `development.yaml`.
2. Security review: confirm no accidental hardening weakenings leaked into staging.
3. If base was changed, validate **all** environments.
4. Run CI gate:
   ```bash
   python scripts/validate_profile.py -p profiles/staging.yaml -b profiles/base.yaml --strict
   ```
5. Deploy to staging; run smoke tests with production-equivalent controls.

### staging → production

1. Staging tests pass with `verify_signatures: true` and mTLS.
2. Security sign-off on any base changes since last production deploy.
3. Validate production profile with all gates:
   ```bash
   python scripts/validate_profile.py -p profiles/production.yaml -b profiles/base.yaml --strict --json
   ```
4. If OBSIDIAN-001 or PRODUCTION gate fails, block deployment.
5. Deploy with immutable tag and dual-signed image.

---

## OBSIDIAN-001 Enforcement

**Requirement:** The production profile **explicitly defines** the vault mount policy. No fallback, no inheritance default, no placeholder.

### What the Validator Checks

In `profiles/production.yaml`, the following MUST be present under `vault.obsidian`:

```yaml
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
  require_approval: true
  dual_control_approval: true
  audit_reads: true
  audit_writes: true
  audit_immutable_log: true
  max_ttl: 4h
  reauth_interval: 1h
```

### Validation Errors

- `mount_policy` missing entirely → **OBSIDIAN-001 gate fails**
- `mode` not equal to `production` → **OBSIDIAN-001 gate fails**
- `allowed_paths` empty or missing → **OBSIDIAN-001 gate fails**
- `allow_mock_secrets` not `false` → **OBSIDIAN-001 gate fails**
- `audit_immutable_log` not `true` → **OBSIDIAN-001 gate fails**

---

## Key Behaviors Summary

1. **Three validated profiles:** `development.yaml` (permissive), `staging.yaml` (production-equivalent, isolated), `production.yaml` (strict).
2. **Inheritance model:** `base.yaml` + environment overrides. Common settings live once; diffs show intent.
3. **Validation gate:** `config-profile-manager` rejects invalid configs before deployment (CI/CLI).
4. **Security setting audit:** Flags any profile where security settings are weaker than base. Staging and production cannot be weakened without error.
5. **OBSIDIAN-001 enforcement:** Production profile explicitly defines vault mount policy; validator blocks deployment if missing or incorrect.

---

## References

- `references/profile_schemas.md` — YAML schemas, allowed weakenings, gate severity table.
- `references/security_settings_matrix.md` — Complete per-environment settings matrix with rationale and exception process.
- `scripts/validate_profile.py` — Source code for the validation gate.

---

## Maintenance

- Update `base.yaml` only for changes that apply globally.
- When adding a new security setting, add it to `base.yaml` first, then update the overlay schemas.
- Run the full validation suite before every release.
- Review `security_settings_matrix.md` quarterly for accuracy.
