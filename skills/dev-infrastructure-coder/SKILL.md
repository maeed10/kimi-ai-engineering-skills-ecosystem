---
name: dev-infrastructure-coder
description: Developer-facing infrastructure-as-code generator for Terraform, CloudFormation, Pulumi, Ansible, and Kubernetes. Use when provisioning cloud resources, configuring K8s, managing state, or optimizing costs. Includes security hardening, Infracost integration, drift detection, and remote state management.
---

# dev-infrastructure-coder

Generate, validate, and manage Infrastructure-as-Code for everyday software engineering across AWS, Azure, GCP, and Kubernetes. This skill provides opinionated patterns, security guardrails, cost-aware defaults, and automated module generation.

## Workflow Decision Tree

1. **Identify target platform and tool**
   - Terraform → AWS/Azure/GCP provisioning with modules and remote state
   - CloudFormation → AWS-native stacks with nested templates
   - Pulumi → TypeScript/Python/Go programmatic infrastructure
   - Ansible → Configuration management and provisioning playbooks
   - Kubernetes → Manifests, Helm, or operator-based deployments

2. **Gather requirements**
   - Service topology (compute, networking, storage, databases)
   - Traffic patterns (ingress, egress, load balancing)
   - Security constraints (encryption, IAM, network policies)
   - Cost targets (instance families, reserved capacity, spot usage)
   - Operational needs (observability, backups, HA, DR)

3. **Generate IaC with defaults**
   - Use `scripts/generate_terraform.py` for Terraform scaffolding
   - Apply cloud patterns from `references/cloud_patterns.md`
   - Apply Kubernetes patterns from `references/k8s_patterns.md`
   - Inject security hardening checklist defaults

4. **Validate and estimate**
   - Run `terraform validate` / `plan` (Terraform)
   - Run `cfn-lint` / `cfn-nag` (CloudFormation)
   - Run `pulumi preview` (Pulumi)
   - Run `ansible-lint` (Ansible)
   - Run `kubeconform` / `kubescape` (Kubernetes)
   - Run `infracost breakdown` for cost estimates (Terraform)

5. **Review security checklist**
   - IAM least-privilege
   - Encryption at rest and in transit
   - Security group / NSG / firewall rules
   - Network policies and pod security standards
   - Secrets management (no plaintext in state or repos)

6. **Plan state and lifecycle**
   - Remote backend with locking and versioning
   - State encryption
   - Drift detection schedule
   - Import strategy for existing resources

7. **Output deliverables**
   - IaC files (modules, manifests, templates)
   - `README.md` with usage, inputs, outputs
   - Makefile or task runner with validate/plan/apply targets
   - CI/CD pipeline template for automated checks

---

## Terraform Generation

### Module Structure
```
modules/
  <name>/
    main.tf
    variables.tf
    outputs.tf
    versions.tf
    README.md
```

### Minimum Variable Set
- `environment` (default: `"dev"`)
- `region` / `location` (default: provider default)
- `tags` / `labels` (default: `{}`)
- `name_prefix` (default: `""`)

### Common Modules
| Module | Purpose | Key Outputs |
|--------|---------|-------------|
| `vpc` | Networking, subnets, NAT, IGW | `vpc_id`, `private_subnet_ids`, `public_subnet_ids` |
| `compute` | Auto Scaling Groups / VMSS / MIG | `instance_ids`, `launch_template_id` |
| `database` | RDS / Cloud SQL / Azure SQL | `endpoint`, `connection_string_secret_arn` |
| `storage` | S3 / Blob / GCS buckets | `bucket_id`, `bucket_arn` |
| `loadbalancer` | ALB / NLB / App Gateway / GLB | `dns_name`, `target_group_arns` |
| `iam` | Roles, policies, instance profiles | `role_arn`, `policy_arn` |
| `state` | Remote backend resources | `bucket_name`, `dynamodb_table_name` |

### Security Defaults for Terraform
- Enable `kms_key_id` for EBS/S3/RDS encryption; default to AWS managed CMK if not provided.
- Security groups: deny all ingress by default; add explicit `ingress_rules` list.
- S3 buckets: `block_public_acls = true`, `block_public_policy = true`, `ignore_public_acls = true`, `restrict_public_buckets = true`, versioning enabled.
- RDS: `storage_encrypted = true`, `publicly_accessible = false`, deletion protection in prod.
- IAM policies: use `data.aws_iam_policy_document` with explicit `sid` and `condition` blocks.
- Secrets: store in AWS Secrets Manager / Azure Key Vault / GCP Secret Manager; never in plain `.tfvars`.

### Infracost Integration
- Add `infracost-usage.yml` to define usage estimates for data transfer, requests, etc.
- Run `infracost breakdown --path .` before `terraform apply`.
- Gate applies on cost delta thresholds (e.g., >20% increase requires approval).

### State Management
- Remote backends:
  - AWS: S3 + DynamoDB locking
  - Azure: Blob Storage + lease locking
  - GCP: GCS + object versioning
- State versioning: enable versioning on backend bucket.
- State encryption: SSE-KMS (AWS), CMK (Azure), CMEK (GCP).
- Workspace strategy: one workspace per environment or one backend per environment.

---

## CloudFormation Generation

### Template Structure
```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: "..."
Parameters:
  Environment:
    Type: String
    Default: dev
    AllowedValues: [dev, staging, prod]
Resources:
  ...
Outputs:
  ...
```

### Nested Stacks
- Parent stack defines parameters and exports.
- Child stacks (network, compute, data) imported via `AWS::CloudFormation::Stack`.
- Pass outputs via `Fn::GetAtt` on nested stack resources.

### Security Defaults for CloudFormation
- Use `AWS::IAM::Role` with `AssumeRolePolicyDocument` restricted to known services.
- `AWS::EC2::SecurityGroupIngress` should not use `CidrIp: 0.0.0.0/0` unless explicitly justified.
- `AWS::RDS::DBInstance`: `PubliclyAccessible: false`, `StorageEncrypted: true`.
- `AWS::S3::Bucket`: `PublicAccessBlockConfiguration` set to block all public access.
- `AWS::KMS::Key` with rotation enabled for encryption keys.

### Validation
- `cfn-lint` for syntax and best-practice linting.
- `cfn-nag` for security rules (e.g., no wildcards in IAM, no open security groups).
- `aws cloudformation validate-template` for API-level validation.

---

## Pulumi Generation

### Program Structure (TypeScript)
```typescript
import * as pulumi from "@pulumi/pulumi";
import * as aws from "@pulumi/aws";

const config = new pulumi.Config();
const env = config.require("environment");

// Resources...
export const endpoint = cluster.endpoint;
```

### Security Defaults for Pulumi
- Use `pulumi.Config` for secrets; mark with `config.requireSecret()`.
- Enable default encryption on all storage and database resources.
- Use least-privilege IAM attachments via `aws.iam.RolePolicy`.
- Store state in Pulumi Cloud or self-managed S3/GCS/Azure Blob with passphrase or KMS.

### Preview and Cost
- Run `pulumi preview` before every update.
- Use Pulumi CrossGuard (OPA) policies to enforce cost and security rules.

---

## Ansible Generation

### Playbook Structure
```yaml
---
- name: Provision web tier
  hosts: webservers
  become: yes
  vars:
    app_version: "1.2.3"
  roles:
    - common
    - webserver
```

### Role Skeleton
```
roles/<name>/
  tasks/main.yml
  handlers/main.yml
  templates/
  files/
  vars/main.yml
  defaults/main.yml
```

### Security Defaults for Ansible
- Use `ansible-vault` for secrets; never commit plaintext credentials.
- `validate_certs: yes` on all URI tasks.
- Set `no_log: true` on tasks handling sensitive data.
- Use `become` with `become_method: sudo` and explicit `become_user`.

---

## Kubernetes Manifests

### Resource Checklist
- [ ] Namespace with labels and resource quotas
- [ ] Deployment with replicas, strategy, and pod template
- [ ] Service (ClusterIP / NodePort / LoadBalancer / ExternalName)
- [ ] ConfigMap for non-sensitive configuration
- [ ] Secret (Opaque / TLS / docker-registry) for sensitive data
- [ ] Ingress with TLS termination and rate limiting annotations
- [ ] HorizontalPodAutoscaler (HPA) for CPU/memory or custom metrics
- [ ] PodDisruptionBudget (PDB) for minimum availability during disruptions
- [ ] NetworkPolicy for namespace/pod-level traffic control
- [ ] SecurityContext (runAsNonRoot, readOnlyRootFilesystem, drop ALL capabilities)
- [ ] ServiceAccount with least-privilege RBAC bindings
- [ ] Resource limits and requests on every container

### Security Defaults for Kubernetes
- Pod Security Standard: `restricted` in prod; `baseline` in staging.
- `allowPrivilegeEscalation: false` on all containers.
- `readOnlyRootFilesystem: true` by default; use `emptyDir` for ephemeral writes.
- `seccompProfile: { type: RuntimeDefault }`.
- NetworkPolicy: default-deny all ingress/egress; explicitly allow required flows.
- RBAC: no cluster-admin for service accounts; prefer namespaced Roles/RoleBindings.
- Secrets: use external-secrets operator or sealed-secrets; never commit raw Secret YAML.

### Validation
- `kubeconform` for schema validation against multiple Kubernetes versions.
- `kubescape` for security posture scanning.
- `trivy config` for misconfiguration scanning.
- `helm lint` if using Helm charts.

---

## Security Hardening Checklist

### Identity & Access
- [ ] IAM roles/policies scoped to least privilege (no `*:*` unless justified)
- [ ] MFA enforced for root/admin accounts
- [ ] Service accounts / instance profiles separate per workload
- [ ] Regular access reviews (quarterly)

### Networking
- [ ] VPC / VNet isolation with private subnets for compute and data
- [ ] Security groups / NSGs are stateful and deny-by-default
- [ ] No public IPs on databases or internal services
- [ ] WAF / DDoS protection on public endpoints
- [ ] VPC/VNet flow logs and network monitoring enabled

### Encryption
- [ ] Encryption at rest for all storage (EBS, S3, RDS, Blob, GCS)
- [ ] Encryption in transit (TLS 1.2+ minimum)
- [ ] Key rotation enabled on customer-managed keys
- [ ] Secrets encrypted via platform secret manager or HashiCorp Vault

### Compute
- [ ] OS/images regularly patched (auto-updates or golden images)
- [ ] Container images scanned for CVEs before deployment
- [ ] Runtime security (Falco, Azure Defender, GCP Security Command Center)
- [ ] No privileged containers in Kubernetes

### Audit & Compliance
- [ ] CloudTrail / Activity Log / Audit Logs enabled
- [ ] Log retention aligned with compliance requirements
- [ ] Immutable backups stored in separate account/region
- [ ] GuardDuty / Security Center / SCC threat detection enabled

---

## Cost Estimation

### Terraform
1. Install Infracost: `infracost auth login`
2. Generate usage file: `infracost breakdown --path . --sync-usage-file --usage-file infracost-usage.yml`
3. Run breakdown: `infracost breakdown --path . --usage-file infracost-usage.yml`
4. Set budget thresholds in CI/CD; block applies that exceed them.

### Right-Sizing Guidelines
- Start with burstable families (t4g, B-series, e2-medium) for dev/non-prod.
- Use Compute Optimizer / Advisor recommendations for prod.
- Prefer Spot / Preemptible for fault-tolerant batch workloads.
- Use Graviton / ARM instances where software compatibility allows (20% cheaper).
- Enable auto-shutdown tags for dev environments outside business hours.

---

## Drift Detection

### Strategy
1. Schedule `terraform plan -detailed-exitcode` in CI/CD nightly.
2. Capture exit code 2 (drift present) and trigger alert.
3. Run `aws config rule` / `Azure Policy` / `Forseti` for non-Terraform resources.
4. Notify via Slack/email/SNS on drift with a summary of changed resources.

### Remediation
- Document drift in incident tracking.
- Determine if drift was emergency change or unauthorized.
- Reconcile via `terraform apply` after code update, or import if the change is desired.

---

## State Import / Adoption

When generating IaC for existing resources:
1. Use `terraform import` with generated resource addresses.
2. Run `terraform plan` to identify missing arguments.
3. Backfill resource blocks to match reality.
4. Commit and run apply to normalize.

### Bulk Import Script
- Use `terraformer` or `aztfexport` / `gcpterraformer` for bulk resource discovery.
- Post-process generated code through `terraform fmt` and module refactoring.

---

## Outputs & Documentation

Every generated module or manifest set must include:
- `README.md` with description, usage example, inputs table, outputs table.
- `Makefile` or `Taskfile.yml` with:
  - `make validate` (lint + format + validate)
  - `make plan` (dry-run)
  - `make cost` (Infracost / pricing API)
  - `make test` (unit / integration tests if applicable)
- `.gitignore` excluding `.terraform/`, `*.tfstate*`, `.pulumi/`, `crash.log`.

---

## CI/CD Integration Template

```yaml
# .github/workflows/iac-check.yml
name: IaC Validate
on: [pull_request]
jobs:
  terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - run: terraform fmt -check -recursive
      - run: terraform validate
      - uses: infracost/actions/setup@v2
      - run: infracost breakdown --path .
  kubernetes:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: kubeconform -kubernetes-version 1.29 manifests/
      - run: kubescape scan manifests/
```

Use this template as a baseline for all generated IaC repositories.
