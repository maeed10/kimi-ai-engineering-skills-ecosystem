# Backend Integration Reference

Complete setup patterns, authentication methods, and deployment manifests for HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets, and Azure Key Vault.

---

## HashiCorp Vault

### When to Use
- Multi-cloud or hybrid infrastructure
- Need for dynamic secrets (database credentials, PKI certs)
- Advanced secret engines (Transit, SSH, AWS)
- On-premise or self-managed deployments

### Deployment Patterns

#### Development: Vault Dev Server
```bash
vault server -dev -dev-root-token-id="dev-only-token"
export VAULT_ADDR='http://127.0.0.1:8200'
export VAULT_TOKEN='dev-only-token'
```
**Warning:** Dev server stores everything in memory. Never use for production.

#### Production: Vault HA with Auto-Unseal
```hcl
# /etc/vault/config.hcl
storage "raft" {
  path    = "/opt/vault/data"
  node_id = "node1"
}
listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_cert_file = "/opt/vault/tls/vault.crt"
  tls_key_file  = "/opt/vault/tls/vault.key"
}
seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unseal"
}
api_addr = "https://vault.prod.internal:8200"
cluster_addr = "https://vault.prod.internal:8201"
ui = true
```

**Auto-unseal options:** AWS KMS, Azure Key Vault, GCP CKM, Transit (another Vault cluster), or HSM (PKCS#11).

### Authentication Methods

| Method | Use Case | K8s Integration |
|---|---|---|
| Token | Bootstrapping, operators | Admin tokens only |
| Kubernetes Auth | Pod-to-Vault identity | Primary method for K8s workloads |
| AppRole | VM/bare-metal workloads | Requires secret delivery mechanism |
| JWT/OIDC | Human access, CI/CD pipelines | GitHub Actions, GitLab CI |
| AWS/IAM Auth | AWS-native workloads | Cross-cloud from AWS to Vault |

#### Kubernetes Auth Setup
```bash
# Enable Kubernetes auth
vault auth enable kubernetes

# Configure K8s API connection
vault write auth/kubernetes/config \
  token_reviewer_jwt="$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)" \
  kubernetes_host="https://$KUBERNETES_PORT_443_TCP_ADDR:443" \
  kubernetes_ca_cert="@/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

# Create policy
vault policy write executor-read - <<EOF
path "secret/data/prod/executor/*" {
  capabilities = ["read"]
}
EOF

# Create role
vault write auth/kubernetes/role/executor \
  bound_service_account_names=executor \
  bound_service_account_namespaces=prod \
  policies=executor-read \
  ttl=1h
```

#### AppRole Setup (VM/Bare-Metal)
```bash
vault auth enable approle
vault write auth/approle/role/executor \
  secret_id_ttl=24h \
  token_ttl=1h \
  token_max_ttl=4h \
  policies=executor-read

# Fetch RoleID and SecretID
vault read auth/approle/role/executor/role-id
vault write -f auth/approle/role/executor/secret-id
```

### Secret Engines

| Engine | Use Case | Rotation Support |
|---|---|---|
| KV v2 | Static secrets, API keys | Manual versioning |
| Database | Dynamic DB credentials | Built-in, automatic |
| Transit | Encryption-as-a-service | Key rotation |
| PKI | TLS certificates | Automatic TTL-based |
| AWS | Dynamic AWS credentials | Built-in STS |

#### KV v2 (Static Secrets)
```bash
vault secrets enable -version=2 -path=secret kv

# Write with metadata
vault kv put -mount=secret prod/executor/e2b-api-key \
  value="$E2B_API_KEY" environment="production" service="executor"

# Read latest
vault kv get secret/prod/executor/e2b-api-key

# Read specific version
vault kv get -version=2 secret/prod/executor/e2b-api-key
```

#### Database (Dynamic Secrets)
```bash
vault secrets enable database
vault write database/config/postgres \
  plugin_name=postgresql-database-plugin \
  allowed_roles="executor" \
  connection_url="postgresql://{{username}}:{{password}}@postgres:5432/" \
  username="vaultadmin" \
  password="$VAULT_ADMIN_PASSWORD"

vault write database/roles/executor \
  db_name=postgres \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
  default_ttl=1h \
  max_ttl=24h
```

### Kubernetes Agent Sidecar Injection

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: executor
  namespace: prod
spec:
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "executor"
        vault.hashicorp.com/agent-inject-secret-e2b-api-key: "secret/data/prod/executor/e2b-api-key"
        vault.hashicorp.com/agent-inject-template-e2b-api-key: |
          {{- with secret "secret/data/prod/executor/e2b-api-key" -}}
          export E2B_API_KEY="{{ .Data.data.value }}"
          {{- end }}
        vault.hashicorp.com/agent-pre-populate-only: "true"
    spec:
      serviceAccountName: executor
      containers:
        - name: executor
          image: executor:latest
          command: ["/bin/sh", "-c"]
          args: ["source /vault/secrets/e2b-api-key && ./run"]
```

---

## AWS Secrets Manager

### When to Use
- AWS-native infrastructure (EKS, ECS, Lambda)
- Need built-in rotation Lambda functions
- Want managed HA without running Vault
- Tight integration with CloudTrail, IAM, KMS

### Setup

#### Create Secret
```bash
aws secretsmanager create-secret \
  --name prod/executor/e2b-api-key \
  --description "E2B API key for production executor" \
  --secret-string '{"E2B_API_KEY":"'$E2B_API_KEY'"}' \
  --kms-key-id alias/prod-secrets \
  --tags Key=environment,Value=production Key=service,Value=executor
```

#### Read Secret
```bash
aws secretsmanager get-secret-value \
  --secret-id prod/executor/e2b-api-key \
  --version-stage AWSCURRENT
```

#### IAM Policy for Reading
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:123456789:secret:prod/executor/*"
    }
  ]
}
```

### EKS IRSA Integration

**Step 1: Create IAM Role with trust policy for OIDC**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::123456789:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E:sub": "system:serviceaccount:prod:executor",
          "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
```

**Step 2: Attach Secrets Manager read policy to role**

**Step 3: Annotate ServiceAccount**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: executor
  namespace: prod
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789:role/ExecutorSecretReader
```

**Step 4: Application code reads via SDK**
```python
import boto3
from botocore.exceptions import ClientError

def get_secret(secret_name, region="us-east-1"):
    client = boto3.client("secretsmanager", region_name=region)
    try:
        resp = client.get_secret_value(SecretId=secret_name)
        return resp["SecretString"]
    except ClientError as e:
        raise RuntimeError(f"Failed to fetch secret: {e}")
```

### Built-in Rotation

AWS provides managed Lambda rotation templates for RDS, DocumentDB, Redshift. For generic secrets, write a custom Lambda:

```bash
aws secretsmanager rotate-secret \
  --secret-id prod/executor/e2b-api-key \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:123456789:function:e2b-key-rotator \
  --automatically-rotate-after-days 90
```

**Rotation Lambda skeleton (Python):**
```python
def lambda_handler(event, context):
    import boto3
    arn = event["SecretId"]
    token = event["ClientRequestToken"]
    step = event["Step"]
    
    client = boto3.client("secretsmanager")
    
    if step == "createSecret":
        # Generate new secret value
        new_secret = generate_new_key()
        client.put_secret_value(SecretId=arn, ClientRequestToken=token, SecretString=new_secret, VersionStages=["AWSPENDING"])
    elif step == "setSecret":
        # Update the external system (e.g., rotate key in E2B dashboard)
        pass
    elif step == "testSecret":
        # Validate new secret works
        pass
    elif step == "finishSecret":
        # Move AWSCURRENT to new version
        metadata = client.describe_secret(SecretId=arn)
        current = next(v for v in metadata["VersionIdsToStages"] if "AWSCURRENT" in v["VersionStages"])
        client.update_secret_version_stage(SecretId=arn, VersionStage="AWSCURRENT", MoveToVersionId=token, RemoveFromVersionId=current["VersionId"])
```

---

## Kubernetes Secrets

### When to Use
- In-cluster only; never for multi-cluster or external consumers
- Non-sensitive config that happens to be base64-encoded
- Bootstrapping before External Secrets Operator is available
- **Not recommended for production secrets** — use Vault or cloud SM instead

### Creating Secrets

**Imperative (avoid in production):**
```bash
kubectl create secret generic e2b-api-key \
  --from-literal=E2B_API_KEY="$E2B_API_KEY" \
  --namespace=prod
```

**Declarative (preferred for GitOps):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: e2b-api-key
  namespace: prod
  annotations:
    reloader.stakater.com/auto: "true"  # triggers pod restart on change
type: Opaque
stringData:
  E2B_API_KEY: "<placeholder-sealed>"
```

Use **Sealed Secrets** (Bitnami) or **SOPS** (Mozilla) to encrypt Secret manifests for Git storage:

```bash
# With Sealed Secrets
kubeseal --controller-namespace=sealed-secrets \
  --controller-name=sealed-secrets \
  --format yaml < secret.yaml > sealed-secret.yaml
kubectl apply -f sealed-secret.yaml
```

### Mounting in Pods

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: executor
          env:
            - name: E2B_API_KEY
              valueFrom:
                secretKeyRef:
                  name: e2b-api-key
                  key: E2B_API_KEY
          volumeMounts:
            - name: secrets
              mountPath: "/etc/secrets"
              readOnly: true
      volumes:
        - name: secrets
          secret:
            secretName: e2b-api-key
```

### Encryption at Rest

Enable KMS encryption for the etcd Secret store:

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
      - secrets
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: <base64-encoded-32-byte-key>
      - identity: {}
```

Or use a KMS provider (AWS KMS, Azure Key Vault, GCP KMS) via the Kubernetes KMS plugin.

---

## Azure Key Vault

### When to Use
- Azure-native infrastructure (AKS, Azure Container Apps)
- Need for HSM-backed keys (Managed HSM)
- Regulatory requirements for FIPS 140-2 Level 3
- Integration with Azure AD conditional access

### Setup

#### Create Vault
```bash
az keyvault create \
  --name prod-secrets \
  --resource-group production \
  --location eastus \
  --enable-rbac-authorization true \
  --sku premium
```

#### Add Secret
```bash
az keyvault secret set \
  --vault-name prod-secrets \
  --name prod-executor-e2b-api-key \
  --value "$E2B_API_KEY" \
  --tags environment=production service=executor rotation-schedule=90d
```

#### RBAC Assignment
```bash
# Grant a managed identity read access
az role assignment create \
  --assignee-object-id $MANAGED_IDENTITY_OBJECT_ID \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets User" \
  --scope "/subscriptions/$SUB_ID/resourcegroups/production/providers/Microsoft.KeyVault/vaults/prod-secrets"
```

### AKS Integration: CSI Driver

Install the Azure Key Vault Provider for Secrets Store CSI Driver:

```bash
helm repo add csi-secrets-store-provider-azure https://azure.github.io/secrets-store-csi-driver-provider-azure/charts
helm install csi-secrets-store csi-secrets-store-provider-azure/csi-secrets-store-provider-azure \
  --namespace kube-system
```

**SecretProviderClass:**
```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: e2b-api-key
  namespace: prod
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    userAssignedIdentityID: ""
    keyvaultName: "prod-secrets"
    cloudName: ""
    objects: |
      array:
        - |
          objectName: prod-executor-e2b-api-key
          objectType: secret
    tenantId: "$AZURE_TENANT_ID"
  secretObjects:
    - secretName: e2b-api-key
      type: Opaque
      data:
        - objectName: prod-executor-e2b-api-key
          key: E2B_API_KEY
```

**Pod mounting:**
```yaml
spec:
  containers:
    - name: executor
      volumeMounts:
        - name: secrets-store-inline
          mountPath: "/mnt/secrets"
          readOnly: true
  volumes:
    - name: secrets-store-inline
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: e2b-api-key
```

### Auto-Rotation with Event Grid

Azure Key Vault can emit events to Event Grid when a secret is about to expire:

```bash
az eventgrid event-subscription create \
  --source-resource-id $(az keyvault show --name prod-secrets --query id -o tsv) \
  --name secret-near-expiry \
  --endpoint-type AzureFunction \
  --endpoint /subscriptions/$SUB_ID/resourceGroups/production/providers/Microsoft.Web/sites/secret-rotator/functions/rotate
```

The Azure Function receives the event and triggers rotation logic.

---

## Comparison Matrix

| Feature | Vault | AWS SM | K8s Secrets | Azure KV |
|---|---|---|---|---|
| Managed service | No (self-hosted) | Yes | No (K8s native) | Yes |
| Multi-cloud | Yes | No | No | No |
| Dynamic secrets | Yes | Limited | No | No |
| Built-in rotation | Agent-based | Lambda | No | Event Grid |
| K8s sidecar injection | Native | IRSA/CSI | Native | CSI driver |
| HSM support | Enterprise | KMS only | No | Managed HSM |
| Audit log | File/Syslog | CloudTrail | API audit | Azure Monitor |
| Cost model | License/hosting | Per secret + API | Free (cluster) | Per operation |
