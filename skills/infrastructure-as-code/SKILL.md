---
name: infrastructure-as-code
description: >
  Generates, validates, and manages Infrastructure-as-Code manifests (Terraform, CloudFormation, Kubernetes).
  Trigger when the user requests infrastructure provisioning, environment setup, IaC manifest generation,
  infrastructure validation, drift detection, cost estimation, or integration with deployment pipelines.
  Also trigger on mentions of terraform, kubernetes manifests, cloudformation, helm charts, or infrastructure state.
---

# Infrastructure As Code

## What it does
Generates production-ready IaC manifests (Terraform, Kubernetes, CloudFormation) from application
requirements, validates them with security and compliance scanners, enforces mandatory tagging and
naming conventions, estimates costs, and manages state/drift detection. Orchestrates with CI/CD pipelines
and requires **external human or CI-native approval gates** for all destructive or state-changing operations.
The agent itself **CANNOT** approve its own plans — approval must come from an external human reviewer
or a CI-native protected environment gate.

## When to use
- User asks to create, update, or destroy cloud infrastructure (AWS/GCP/Azure)
- User requests Kubernetes manifests (Deployments, Services, Ingress, ConfigMaps, Secrets)
- User mentions Terraform modules, CloudFormation templates, or Helm charts
- User needs environment provisioning (dev, staging, production)
- User requests infrastructure validation, security scanning, or compliance checks
- User asks for cost estimation of planned infrastructure
- Drift detection or state reconciliation is needed
- Integration with CI/CD deployment pipelines for infrastructure is requested

## Key capabilities
- **Manifest generation** — Terraform (AWS/GCP/Azure), Kubernetes manifests, CloudFormation templates
- **Validation** — Syntax (`terraform validate`, `kubeconform`, `cfn-lint`), security (Checkov, tfsec, kubesec), and compliance
- **Checkov pre-plan gate** — Run Checkov on generated manifests **before** plan generation; block on CRITICAL findings
- **State & drift** — Track state, detect drift, plan changes, reconcile infrastructure; enforce state locking via S3/DynamoDB or equivalent
- **Tagging compliance** — Enforce mandatory tags (environment, owner, cost-center, project) on all taggable resources
- **Secret management** — Integrate with Vault/1Password/external vaults for secret injection (never inline)
- **Cost estimation** — Generate cost estimates from planned infrastructure changes using `infracost` or cloud calculators
- **Plan review artifact** — Produce structured `PLAN_REVIEW.md` documents with human-readable summary, risk assessment, rollback procedure, and Checkov report
- **CI-native approval gates** — Generate GitHub Actions (or equivalent) workflows with protected environments and required reviewers; agent cannot self-approve

## Workflow

### Step 1: Read application requirements
- Read the Architecture Design and Spec Decomposer outputs (or user-provided requirements)
- Identify required infrastructure components: compute, storage, networking, databases, caches, load balancers
- Read SLO definitions from Performance Validator for resource sizing guidance (CPU/memory requests/limits)
- Determine target platform(s) and constraints (multi-region, VPC, compliance requirements)

### Step 2: Select IaC tool
- **Terraform** — Multi-cloud, complex stateful resources, team workflows. Default for AWS/GCP/Azure provisioning.
- **Kubernetes manifests** — Container workloads, microservices, service mesh. Default for container orchestration.
- **CloudFormation** — AWS-native, stack-based, when organization mandates AWS-native tooling.
- **Helm** — Templated Kubernetes deployments, when reusability and parameterization are critical.
- Decision matrix: prefer Terraform for cloud primitives; prefer K8s manifests for container workloads;
  use CloudFormation only when organizational policy requires it.

### Step 3: Generate manifests with security defaults
- Apply least-privilege IAM roles and security groups
- Enable encryption at rest and in transit for all storage, databases, and caches
- Apply network segmentation (subnets, VPCs, network policies)
- Enable audit logging and monitoring integration points for CloudWatch/Stackdriver/Prometheus
- Use modules and reusable patterns from `scripts/generate-terraform.py` when generating Terraform
- Use `references/security-checklist.md` as the source of truth for security requirements
- **ALWAYS include mandatory resource tagging** (owner, environment, cost-center) in generated manifests

### Step 4: Inject secrets via vault references
- NEVER embed secrets, API keys, credentials, or certificates inline in manifests
- Use environment variables, external secret stores (HashiCorp Vault, 1Password, AWS Secrets Manager,
  GCP Secret Manager, Azure Key Vault), or CSI secret drivers
- Reference secrets by path/key — document required secrets in a `SECRETS.md` file

### Step 5: Enforce mandatory tagging
- Add mandatory tags to all taggable resources BEFORE validation:
  - `environment` (dev/staging/prod)
  - `owner` (team or individual responsible)
  - `cost-center` (billing allocation)
  - `project` (project identifier)
- Reject manifests missing mandatory tags — do not proceed to validation until resolved
- Use `scripts/generate-terraform.py` default tags block for Terraform resources

### Step 6: Run Checkov security scan **before** plan generation
- Run Checkov on generated manifests **before** running `terraform plan`:
  - Terraform: `checkov --framework terraform -d .`
  - Kubernetes: `checkov --framework kubernetes -d .`
  - CloudFormation: `checkov --framework cloudformation -d .`
- **Block if Checkov finds CRITICAL issues.** Halt the workflow and require remediation.
- For HIGH findings, require documented risk acceptance or remediation before proceeding.
- Capture the Checkov report (JSON or CLI output) to include in the plan review artifact.
- This is a **hard gate** — no plan may be generated until Checkov passes the CRITICAL threshold.

### Step 7: Configure state backend with locking
- Generate backend configuration with remote state and mandatory locking:
  - **AWS**: S3 bucket with versioning, encryption (SSE-KMS), and DynamoDB table for state locking
  - **GCP**: GCS bucket with versioning, encryption (CMEK), and Object Administration for locking
  - **Azure**: Blob Storage with versioning, encryption (CMK), and lease-based locking
- Include state backup procedure documentation in `PLAN_REVIEW.md`
- NEVER allow local state files for production or shared environments
- The `scripts/generate-terraform.py` backend block must be updated with concrete S3/DynamoDB (or equivalent) settings

### Step 8: Generate Terraform plan
- Run `terraform plan -out=plan.tfplan` to produce a binary plan file
- Capture the plan output (text and/or JSON via `terraform show -json plan.tfplan`) for downstream processing
- Store `plan.tfplan` as a CI artifact; it is required for any subsequent `terraform apply`
- Do not proceed to review artifact generation if `terraform plan` exits with errors

### Step 9: Generate plan review artifact (`PLAN_REVIEW.md`)
- Use `scripts/generate-plan-review.py` to assemble a human-readable plan review document containing:
  1. **Plan summary** — resources to create / modify / destroy (parsed from `terraform show -json plan.tfplan`)
  2. **Cost estimate** — absolute and delta costs (from `infracost breakdown --path .` or cloud calculators)
  3. **Risk assessment** — blast radius of changes, affected services, SLO impact, data-loss potential
  4. **Checkov report** — summary of all Checkov findings (pass/fail counts, CRITICAL/HIGH items)
  5. **Tagging compliance check** — verification that all resources carry mandatory tags
  6. **State locking verification** — confirmation that backend locking is active
  7. **Rollback procedure** — step-by-step rollback instructions and state recovery steps
  8. **Required confirmations** — checklist for backup, rollback, SLO impact, and external approver signature
- Present this document to the user and **require external human or CI-native approval**
- **The agent itself CANNOT approve the plan.** Approval must come from:
  - An external human reviewer, OR
  - A CI-native protected environment gate (e.g., GitHub Actions `environment: production` with `required_reviewers: 1`)

### Step 10: Execute apply (post-external-approval only)
- After **external** human confirmation or CI-native gate approval, execute the apply operation
- For Terraform: `terraform apply plan.tfplan` (use the exact binary plan artifact)
- For Kubernetes: `kubectl apply --server-side` or `kubectl apply` with dry-run first
- For CloudFormation: `aws cloudformation deploy` with rollback triggers enabled
- Capture state/output and store reference for downstream skills
- If apply fails, capture error output and immediately initiate rollback or remediation

### Step 11: Feed provisioned details to downstream skills
- Provide infrastructure endpoints, ARNs, connection strings to CI/CD Integrator as deployment targets
- Feed provisioned resource list to Security Auditor for continuous scanning
- Feed infrastructure topology to Resilience Tester for chaos experiment target selection
- Feed provisioned resource identifiers to Blast Radius Calculator for future impact assessment

## CI-native approval gate specification

The skill MUST generate CI/CD configuration that enforces **external** approval. The agent cannot
self-approve because the same LLM generating the plan cannot be the same entity reviewing it.

### GitHub Actions example
Generate a workflow that uses GitHub Environments with required reviewers:

```yaml
jobs:
  terraform-plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Terraform Plan
        run: |
          terraform init
          terraform plan -out=plan.tfplan
      - name: Checkov Scan
        run: checkov --framework terraform -d . --soft-fail false --check CRITICAL
      - name: Upload Plan Artifact
        uses: actions/upload-artifact@v4
        with:
          name: plan.tfplan
          path: plan.tfplan

  terraform-apply:
    needs: terraform-plan
    runs-on: ubuntu-latest
    environment:
      name: production
      url: ${{ steps.apply.outputs.url }}
    # This environment MUST have required_reviewers: 1 configured in GitHub repo settings
    steps:
      - uses: actions/checkout@v4
      - name: Download Plan Artifact
        uses: actions/download-artifact@v4
        with:
          name: plan.tfplan
      - name: Terraform Apply
        id: apply
        run: terraform apply -auto-approve plan.tfplan
```

**Enforcement rules**:
- The `terraform-apply` job MUST target a GitHub Environment with `required_reviewers >= 1`
- The agent MUST NOT generate a workflow where the same job/plan step also performs apply without an external gate
- If the user requests a non-GitHub CI (GitLab, Azure DevOps, CircleCI), generate the equivalent protected-environment / manual-approval gate
- Document in the workflow YAML that "Approval must come from a human reviewer external to the agent; the agent cannot self-approve."

## Safety highlights
- **NEVER** run `terraform apply`, `kubectl delete`, `aws cloudformation delete-stack`, or any infrastructure
  destruction command without first generating a plan review artifact and receiving external approval.
- **NEVER** hardcode secrets, API keys, passwords, tokens, or credentials in generated manifests, variables
  files, or state files. Always use vault references, environment variables, or secret stores.
- **NEVER** delete infrastructure (entire stacks, persistent storage, databases) without explicit
  backup/rollback confirmation. Document the rollback strategy in the plan review.
- **NEVER** provision production infrastructure (`environment=prod`) from a local development context or
  personal workstation. Require CI/CD pipeline or remote execution environment.
- **ALWAYS** enforce mandatory resource tagging (`environment`, `owner`, `cost-center`, `project`) on every
  taggable resource before validation. Reject untagged manifests.
- **ALWAYS** validate manifests with security scanners (`checkov`, `tfsec`, `kubesec`, `cfn-lint`) before
  any `apply`, `deploy`, or `delete` operation. Block on HIGH/CRITICAL findings.
- **ALWAYS** run a dry-run or plan (`terraform plan`, `kubectl apply --dry-run=server`,
  `aws cloudformation create-change-set`) before destructive operations and include results in the plan review.
- **ALWAYS** produce a `PLAN_REVIEW.md` document and require external human/CI-native approval before state-changing
  operations. Maintain an audit trail of approved plans.
- **ALWAYS** check for infrastructure drift (`terraform plan -detailed-exitcode`, state comparisons)
  before applying changes and report drift in the plan review.
- **NEVER** store Terraform state files, `.tfvars` with sensitive values, or `kubeconfig` credentials
  in version control. Use remote state backends with encryption and state locking.
- **NEVER apply Terraform without generating a plan review artifact first.**
- **NEVER allow the agent to approve its own Terraform plan** — approval must be external human or CI-native gate.
- **ALWAYS run Checkov security scan on generated manifests before plan generation.**
- **ALWAYS generate rollback procedure alongside every plan.**
- **NEVER generate manifests without mandatory resource tagging** (owner, environment, cost-center).

## Integration with other skills
- **Architecture Design / Spec Decomposer** — Reads application component requirements, service
  boundaries, and database/cache needs to derive infrastructure components.
- **Performance Validator** — Reads SLO targets and load expectations to size compute, memory,
  storage, and network resources correctly.
- **CI/CD Integrator** — Provides provisioned infrastructure endpoints as deployment targets;
  receives pipeline triggers for infrastructure deployment stages. The CI/CD Integrator MUST
  configure protected-environment gates so the agent cannot self-approve.
- **Blast Radius Calculator** — Feeds resource dependency graph and provisioned resource identifiers
  for impact assessment of future changes.
- **Security Auditor** — Sends IaC manifests and provisioned resource lists for continuous
  security scanning (Checkov findings, compliance drift).
- **Resilience Tester** — Provides provisioned infrastructure topology and endpoints for chaos
  engineering experiments and failover testing.

## Plan review gate enforcement
All destructive or state-changing operations MUST pass through this gate:
1. Generate manifests with mandatory tagging
2. **Run Checkov scan** — block on CRITICAL findings
3. Configure backend with state locking
4. Generate plan (`terraform plan -out=plan.tfplan`)
5. **Generate plan review artifact** (`PLAN_REVIEW.md`) with summary, cost, risk, Checkov report, rollback procedure
6. Present artifact to user; explain that **external approval is required**
7. **HALT** — wait for external human confirmation or CI-native gate approval
8. Only after external approval received, execute apply (`terraform apply plan.tfplan`)
9. Capture state and feed to downstream skills

If the user attempts to shortcut this gate, re-present the plan review and refuse to proceed.
If the user asks the agent to "auto-approve" or "just apply it," explicitly refuse and cite
SEC-8.2: "The agent cannot self-approve. Approval must come from an external human or CI-native gate."

## State locking specification
- **AWS**: S3 bucket + DynamoDB table. S3 bucket must have versioning, server-side encryption (SSE-KMS),
  and block public access. DynamoDB table must have `PayPerRequest` billing and a partition key `LockID` (String).
- **GCP**: GCS bucket with versioning, encryption (CMEK), and a dedicated lock object or use Terraform Cloud.
- **Azure**: Blob Storage container with versioning, encryption (CMK), and lease-based locking.
- **State backup procedure**: Before any destructive plan, export a state snapshot:
  - `terraform state pull > state-backup-$(date +%s).json`
  - Store in a separate, versioned backup bucket/container
  - Document backup location and recovery command in `PLAN_REVIEW.md`
- **Concurrent modification prevention**: State locking MUST be active. If lock acquisition fails,
  halt and alert — do not proceed without resolving the lock.

## References
- `references/security-checklist.md` — IaC security best practices, Checkov rules reference,
  mandatory tagging requirements, state locking configuration, CI-native approval gate patterns,
  and compliance checklist for all supported platforms.

## Scripts
- `scripts/generate-terraform.py` — Template generator for Terraform modules with default security
  settings, tagging enforcement, vault-based secret injection patterns, and S3/DynamoDB backend locking.
- `scripts/generate-plan-review.py` — Human-readable plan review artifact generator. Parses Terraform plan
  JSON, Checkov report, and infracost output to produce `PLAN_REVIEW.md` with summary, cost estimate,
  risk assessment, rollback procedure, and tagging compliance check.
