# Rotation Policies Reference

Rotation schedules, zero-downtime handoff strategies, and emergency rotation procedures for production secrets.

---

## Rotation Schedule Framework

### Schedule by Secret Type

| Secret Type | Rotation Interval | Grace Period | Trigger Event |
|---|---|---|---|
| API key (external SaaS) | 90 days | 24 hours | Quarterly maintenance window |
| OAuth 2.0 / Bearer token | 30 days | 4 hours | Monthly cycle or scope change |
| Service account credential | 90 days | 48 hours | Quarterly or on team change |
| Database password | 30 days | 0 hours (dynamic) | Automatic via DB engine |
| TLS certificate | 80% of TTL | 7 days | Before expiry |
| Root CA / signing key | 1 year | 30 days | Annual audit |
| CI/CD token (`GITHUB_TOKEN`) | 90 days | 12 hours | Quarterly or on personnel change |
| Policy attestation key | 180 days | 24 hours | Semi-annual or on policy update |
| SSH host key | 1 year | 48 hours | Annual or on suspicion |
| Short-lived dynamic secret | 1–24 hours | N/A | Automatic, no grace period |

### Schedule by Risk Level

| Risk Level | Interval | Rationale |
|---|---|---|
| Critical — root keys, CA private keys | 90 days + on any access anomaly | Single compromise = total trust failure |
| High — production API keys, signing keys | 90 days | External exposure risk, hard to revoke globally |
| Medium — staging secrets, read-only tokens | 180 days | Lower blast radius, fewer consumers |
| Low — internal config, non-sensitive values | 365 days or never | Rotation cost > risk |

### Calendar-Driven Rotation Windows

Define fixed maintenance windows to reduce operational surprise:

```yaml
rotation_windows:
  - name: Q1
    start: "01-15T02:00:00Z"
    end: "01-15T05:00:00Z"
    timezone: "UTC"
  - name: Q2
    start: "04-15T02:00:00Z"
    end: "04-15T05:00:00Z"
  - name: Q3
    start: "07-15T02:00:00Z"
    end: "07-15T05:00:00Z"
  - name: Q4
    start: "10-15T02:00:00Z"
    end: "10-15T05:00:00Z"
```

All scheduled rotations must occur within these windows unless triggered by an emergency rotation event.

---

## Zero-Downtime Handoff

### Principle

Consumers must always have a valid secret. Rotation should never cause a consumer to fail because it holds an old value at the moment of switchover.

### Handoff Patterns

#### Pattern A: Versioned Backend with Grace Period (Vault KV v2, AWS SM)

1. **Create new version** (N+1) without changing the "current" pointer.
2. **Consumers continue reading** the current version via stable path (`latest` or `AWSCURRENT`).
3. **After propagation delay** (all pods restarted / cache TTL expired), mark N+1 as current.
4. **Grace period starts** (e.g., 24h). During this window, both N and N+1 are valid.
5. **After grace period**, revoke/destroy version N.

**Vault KV v2 example:**
```bash
# 1. Put new version (does not change latest pointer automatically in all setups)
vault kv put secret/prod/executor/e2b-api-key value="$NEW_KEY"

# 2. Verify both versions exist
vault kv get -version=1 secret/prod/executor/e2b-api-key
vault kv get -version=2 secret/prod/executor/e2b-api-key

# 3. If using explicit version pointers, update metadata to mark v2 as current
vault kv metadata put -custom-metadata=current-version=2 secret/prod/executor/e2b-api-key

# 4. Wait grace period (24h), then destroy v1
vault kv destroy -versions=1 secret/prod/executor/e2b-api-key
```

**AWS Secrets Manager example:**
```bash
# Rotation Lambda handles this automatically via AWSPENDING → AWSCURRENT
# Manual equivalent:
aws secretsmanager put-secret-value \
  --secret-id prod/executor/e2b-api-key \
  --secret-string '{"E2B_API_KEY":"'$NEW_KEY'"}' \
  --version-stages AWSPENDING

# Test new version
aws secretsmanager get-secret-value \
  --secret-id prod/executor/e2b-api-key \
  --version-stage AWSPENDING

# Promote to current
aws secretsmanager update-secret-version-stage \
  --secret-id prod/executor/e2b-api-key \
  --version-stage AWSCURRENT \
  --move-to-version-id <pending-version-id> \
  --remove-from-version-id <current-version-id>
```

#### Pattern B: Dual-Secret Consumer (Application-Level)

When the backend does not support versioning, the application must accept two secrets simultaneously:

1. Application config references `PRIMARY_KEY` and `SECONDARY_KEY`.
2. Backend stores both independently.
3. Rotation swaps the values: new key becomes PRIMARY, old becomes SECONDARY.
4. Application tries PRIMARY, falls back to SECONDARY on auth failure.
5. After grace period, SECONDARY is removed.

```yaml
env:
  - name: E2B_API_KEY_PRIMARY
    valueFrom:
      secretKeyRef:
        name: e2b-api-key-primary
  - name: E2B_API_KEY_SECONDARY
    valueFrom:
      secretKeyRef:
        name: e2b-api-key-secondary
```

#### Pattern C: Dynamic Secrets (Database, Vault PKI)

No handoff needed — every consumer gets a unique, short-lived credential:

```bash
# Vault issues a unique DB credential per pod
vault read database/creds/executor
# Returns: username=v-token-executor-xxx  password=yyy  lease_id=zzz
```

- Each pod renews or reissues its own lease.
- Old leases expire automatically via TTL.
- No global secret version to coordinate.

---

## Emergency Rotation (Compromise Response)

### Trigger Events

- Secret value found in public repository, pastebin, or log leak
- Suspicious access pattern detected by `audit_secrets.py` (e.g., reads from unknown IP, spike in read rate)
- Employee with secret access departs under adverse circumstances
- Vendor notifies of potential breach affecting API key scope
- Security scanner flags secret in container image layer

### Emergency Rotation Runbook

#### Step 1: Triage (0–5 minutes)

1. Identify affected secret(s) from alert or scan.
2. Determine blast radius: which services, which environments, which consumers.
3. Open incident channel / page on-call.

#### Step 2: Contain (5–15 minutes)

1. **Revoke old secret at source** (e.g., rotate key in SaaS dashboard, revoke OAuth grant).
2. **Delete/disable old secret in backend** without waiting for propagation.
3. **Block anomalous source** if IP-based anomaly detected (WAF, security group, NACL).

```bash
# Vault — delete immediately
vault kv delete secret/prod/executor/e2b-api-key

# AWS SM — force delete without recovery
aws secretsmanager delete-secret \
  --secret-id prod/executor/e2b-api-key \
  --force-delete-without-recovery

# Azure KV — purge (permanently delete)
az keyvault secret delete --vault-name prod-secrets --name prod-executor-e2b-api-key
az keyvault secret purge --vault-name prod-secrets --name prod-executor-e2b-api-key
```

#### Step 3: Rotate & Inject (15–30 minutes)

1. Generate new secret value at source.
2. Create new secret in backend with **new path name** or **new version**.
3. Force all consumers to reload:
   - Kubernetes: rolling restart of affected Deployments / StatefulSets
   - VMs: restart Vault Agent or reload systemd service
   - Lambda: publish new version to trigger cold starts

```bash
# K8s rolling restart
kubectl rollout restart deployment/executor -n prod
kubectl rollout status deployment/executor -n prod

# Lambda version publish
aws lambda publish-version --function-name executor
aws lambda update-alias --function-name executor --name prod --function-version $NEW_VERSION
```

#### Step 4: Verify (30–45 minutes)

1. Confirm all pods healthy and reading new secret.
2. Run smoke tests against services using the secret.
3. Check audit logs for any continued attempts to read old secret path/version.

```bash
# Check for old version reads (Vault)
vault audit hash $(cat /var/log/vault/audit.log | jq -r 'select(.request.operation=="read") | .request.path') | grep "secret/data/prod/executor/e2b-api-key"

# Check CloudTrail for old secret ARN reads
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=GetSecretValue \
  --max-results 50 | jq '.Events[] | select(.CloudTrailEvent | contains("prod/executor/e2b-api-key"))'
```

#### Step 5: Post-Incident (1–24 hours)

1. Update secret registry with new version/path.
2. Run `scripts/audit_secrets.py` across full window to identify any missed anomalies.
3. Document timeline and improve detection rules.
4. If old secret was leaked externally, engage vendor to revoke at their edge.

---

## Rotation Automation

### GitOps-Driven Rotation

Store rotation policies alongside infrastructure code:

```yaml
# secrets-policies.yaml
policies:
  - secret_path: prod/executor/e2b-api-key
    backend: vault
    schedule: "0 2 15 */3 *"  # 02:00 on 15th of every quarter
    grace_period: 24h
    trigger: cron
    auto_approve: false  # requires human approval for production
    notification_channel: "#security-ops"

  - secret_path: prod/executor/github-token
    backend: aws-sm
    schedule: "0 2 1 * *"  # 02:00 on 1st of every month
    grace_period: 12h
    trigger: cron
    auto_approve: true  # low-risk, auto-approve

  - secret_path: prod/executor/policy-attestation-key
    backend: vault
    schedule: "0 2 15 1,7 *"  # Semi-annual
    grace_period: 24h
    trigger: manual  # requires explicit operator trigger
    auto_approve: false
```

### Rotation Health Metrics

Track these metrics to ensure rotation hygiene:

| Metric | Target | Alert Threshold |
|---|---|---|
| Secrets within rotation window | 100% | < 95% |
| Emergency rotations per quarter | 0 | > 1 |
| Consumers using `latest` / stable stage | 100% | < 90% |
| Average time from rotation trigger to completion | < 30 min | > 1 hour |
| Failed rotation events per week | 0 | > 0 |

---

## Policy Templates

### Vault Policy: Rotation Operator

```hcl
# rotation-operator.hcl
path "secret/data/prod/executor/*" {
  capabilities = ["create", "update", "read"]
}

path "secret/metadata/prod/executor/*" {
  capabilities = ["read", "update", "delete"]
}

path "secret/delete/prod/executor/*" {
  capabilities = ["update"]
}

path "secret/destroy/prod/executor/*" {
  capabilities = ["update"]
}

path "sys/leases/*" {
  capabilities = ["update"]
}
```

### AWS IAM Policy: Emergency Rotator

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:PutSecretValue",
        "secretsmanager:UpdateSecretVersionStage",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetSecretValue",
        "secretsmanager:DeleteSecret",
        "secretsmanager:RotateSecret"
      ],
      "Resource": "arn:aws:secretsmanager:*:*:secret:prod/executor/*"
    }
  ]
}
```

### Azure RBAC: Key Vault Crypto Officer

```bash
az role assignment create \
  --assignee $ROTATOR_SP_OBJECT_ID \
  --role "Key Vault Secrets Officer" \
  --scope $KEYVAULT_RESOURCE_ID
```
