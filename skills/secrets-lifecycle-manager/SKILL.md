---
name: secrets-lifecycle-manager
description: Production-grade secret lifecycle management with HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets, and Azure Key Vault integrations. Use when onboarding to production, configuring API keys/tokens, setting up rotation policies, or migrating from raw env vars. Covers creation, rotation, injection, revocation, and audit.
---

# Secrets Lifecycle Manager

## Overview

The **Secrets Lifecycle Manager** formalizes the full lifecycle of secrets — creation, rotation, injection, revocation, and audit — across HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets, and Azure Key Vault. It replaces raw environment variable exports and hardcoded credentials with production-grade secret management, ensuring secrets are encrypted at rest, injected at runtime, rotated on schedule, and fully auditable.

Use this skill when:
- Onboarding the ecosystem to a production environment
- Configuring sensitive keys such as `POLICY_ATTESTATION_KEY`, `E2B_API_KEY`, or `GITHUB_TOKEN`
- Setting up automatic or emergency secret rotation policies
- Auditing secret access patterns for anomalies or compliance
- Migrating from development mode (`.env` files) to production vaults

## Environment Progression

| Stage | Backend | Use Case | Risk Level |
|---|---|---|---|
| `dev` | `.env` file (gitignored) | Local development only | High — no audit, no rotation |
| `staging` | Vault dev server / AWS SM staging | Integration tests, preview deploys | Medium — encrypted at rest |
| `production` | Vault HA with auto-unseal / AWS SM / Azure KV | Live workloads | Low — full audit, rotation, IRSA |

**Migration path:** `dev` → `staging` → `production`. Never commit `.env` files. Use injection mechanisms from staging onward.

## Core Capabilities

### 1. Secret Creation

Every secret must be:
- **Encrypted at rest** using the backend's native encryption (AES-256-GCM, AWS KMS CMK, Azure SSE, etc.)
- **Tagged** with `environment`, `service`, `rotation-schedule`, and `owner`
- **Scoped** to the least-privilege access path (no global read access)
- **Versioned** so rotations and rollbacks are possible

**Example: Creating a secret in HashiCorp Vault**
```bash
vault kv put -mount=secret -format=json prod/e2b/api-key \
  value="$E2B_API_KEY" \
  environment="production" \
  service="executor" \
  rotation-schedule="90d" \
  owner="platform-team"
```

**Example: Creating a secret in AWS Secrets Manager**
```bash
aws secretsmanager create-secret \
  --name prod/executor/e2b-api-key \
  --description "E2B API key for production executor" \
  --secret-string '{"E2B_API_KEY":"'$E2B_API_KEY'"}' \
  --kms-key-id alias/prod-secrets \
  --tags Key=environment,Value=production Key=service,Value=executor Key=rotation-schedule,Value=90d
```

### 2. Secret Injection

Secrets must **never** be exported to shell history or committed to repositories. Use runtime injection.

**Mechanisms by platform:**

| Platform | Injection Mechanism | Pattern |
|---|---|---|
| Kubernetes | Vault Agent Sidecar Injector | Secret written to `vault/secrets/` volume |
| Kubernetes | External Secrets Operator | Syncs Vault/AWS SM to native K8s Secret |
| AWS ECS/EKS | IRSA / ECS Task Role | Secret fetched at container startup via SDK |
| Azure AKS | Azure Key Vault Provider for Secrets Store CSI Driver | Mounts secrets as pod volumes |
| Bare Metal / VM | Vault Agent | Auto-auth + templated env files |

**Example: Kubernetes Vault Agent Sidecar**
```yaml
annotations:
  vault.hashicorp.com/agent-inject: "true"
  vault.hashicorp.com/role: "executor"
  vault.hashicorp.com/agent-inject-secret-e2b-api-key: "secret/data/prod/e2b/api-key"
  vault.hashicorp.com/agent-inject-template-e2b-api-key: |
    {{- with secret "secret/data/prod/e2b/api-key" -}}
    export E2B_API_KEY="{{ .Data.data.value }}"
    {{- end }}
```

**Example: AWS IRSA (IAM Roles for Service Accounts)**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: executor
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/ExecutorSecretReader
```

### 3. Secret Rotation

Rotation must be **automatic**, **scheduled**, and **zero-downtime**.

**Rotation triggers:**
- **Scheduled:** Time-based (e.g., every 90 days for API keys, every 30 days for tokens)
- **Event-driven:** On employee departure, token scope change, or suspicion of compromise
- **Emergency:** Immediate rotation with forced revocation of old version

**Zero-downtime handoff:**
1. Backend creates new secret version (N+1)
2. Consumers read latest version by default (`version: latest` or dynamic path)
3. Grace period (e.g., 24h) allows in-flight requests using old version to complete
4. Old version marked `deprecated`, then `destroyed` after grace period

**Example: Vault KV v2 rotation with versioning**
```bash
# Step 1: Put new version
vault kv put secret/prod/e2b/api-key value="$NEW_E2B_API_KEY"

# Step 2: Verify two versions exist
vault kv get -version=1 secret/prod/e2b/api-key
vault kv get -version=2 secret/prod/e2b/api-key

# Step 3: After grace period, destroy old version
vault kv destroy -versions=1 secret/prod/e2b/api-key
```

### 4. Secret Revocation

Immediate revocation with propagation to all consumers.

**Revocation steps:**
1. Delete / disable secret in backend
2. Rotate dependent credentials (if the secret was a CA, rotate all leaf certs)
3. Force pod restarts or trigger config reloads to purge cached secrets
4. Verify no active references via audit log scan (use `scripts/audit_secrets.py`)

**Example: Emergency revocation in AWS Secrets Manager**
```bash
aws secretsmanager delete-secret \
  --secret-id prod/executor/e2b-api-key \
  --force-delete-without-recovery
```

### 5. Audit Logging

Every read, rotation, and injection must be logged to a **tamper-evident** destination (SIEM, WORM storage, or append-only audit device).

**Required audit events:**
- `secret_read` — who, when, which path/version, source IP
- `secret_rotated` — old version, new version, trigger (scheduled / emergency / manual)
- `secret_injected` — pod name, node, service account, secret path
- `secret_revoked` — revoked version, reason, propagated systems

**Example: Vault audit device setup**
```bash
vault audit enable file file_path=/var/log/vault/audit.log
# Or enable syslog for centralized SIEM ingestion
vault audit enable syslog tag="vault-audit"
```

**Example: AWS CloudTrail + Secrets Manager**
AWS CloudTrail automatically logs `GetSecretValue`, `PutSecretValue`, `RotateSecret`, and `DeleteSecret`. Ensure CloudTrail is organization-level and logs to a WORM S3 bucket.

## Workflow Decision Tree

### Onboarding a New Secret to Production

1. **Identify sensitivity level**
   - Low: Config value → use plaintext ConfigMap / Parameter Store
   - Medium: API key → use Vault KV v2 or AWS Secrets Manager with rotation
   - High: Signing key, root CA → use Vault Transit / Azure KV HSM-backed key

2. **Choose backend based on infrastructure**
   - On-prem / multi-cloud → HashiCorp Vault
   - AWS-native → AWS Secrets Manager + Parameter Store
   - Azure-native → Azure Key Vault
   - Kubernetes-centric → External Secrets Operator + any backend

3. **Create secret with metadata tags**
   - `environment`, `service`, `rotation-schedule`, `owner`

4. **Configure injection mechanism**
   - K8s sidecar / CSI driver / IRSA / Vault Agent

5. **Add rotation policy**
   - See `references/rotation_policies.md` for schedule templates

6. **Enable audit logging**
   - Point to SIEM or tamper-evident store

7. **Document in secret registry**
   - Maintain a registry (e.g., YAML or DB) mapping secret paths to services

### Migrating from `.env` to Vault

1. **Inventory existing env vars**
   - Parse `.env` and `.env.local` files
   - Classify by sensitivity

2. **Create corresponding vault paths**
   - Use naming convention: `<env>/<service>/<key-name>`
   - Example: `prod/executor/e2b-api-key`

3. **Rewrite application bootstrap**
   - Replace `os.environ.get("E2B_API_KEY")` with vault client or file read from injected volume

4. **Update deployment manifests**
   - Add sidecar annotations or CSI driver references
   - Remove `env:` blocks referencing raw secrets

5. **Rotate all migrated secrets**
   - Treat `.env` exposure as potential compromise; rotate after migration

6. **Delete `.env` files and add to `.gitignore`**

## Per-Backend Quick Reference

See `references/backend_integrations.md` for complete setup patterns, authentication methods, and deployment manifests for each backend.

| Backend | Best For | Auto-Rotation | HSM Support | K8s Native |
|---|---|---|---|---|
| HashiCorp Vault | Multi-cloud, on-prem, PKI | Yes (via agent) | Yes (Transit) | Excellent |
| AWS Secrets Manager | AWS-native, ECS/EKS | Built-in Lambda | No (KMS only) | Via IRSA / CSI |
| Azure Key Vault | Azure-native, AKS | Yes (via Event Grid) | Yes (Managed HSM) | Via CSI driver |
| Kubernetes Secrets | In-cluster only | No (manual) | No | Native |

## Secret Registry Template

Maintain a `secrets-registry.yaml` in your infrastructure repo (no values, only metadata):

```yaml
secrets:
  - path: prod/executor/e2b-api-key
    backend: vault
    mount: secret
    service: executor
    environment: production
    rotation_schedule: 90d
    last_rotated: "2025-01-15T00:00:00Z"
    owner: platform-team
    injection: vault-agent-sidecar
    consumers:
      - deployment: executor
        namespace: prod
```

## Resources

- `references/backend_integrations.md` — Full setup for Vault, AWS SM, K8s Secrets, Azure KV
- `references/rotation_policies.md` — Rotation schedules, zero-downtime handoff, emergency procedures
- `scripts/audit_secrets.py` — Audit log anomaly detection script
