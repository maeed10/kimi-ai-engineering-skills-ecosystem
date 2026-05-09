# Dry-Run Gate Implementations

Reference for platform-specific dry-run gate patterns and environment variable conventions.

---

## Concept

Every promotion stage that performs a destructive or externally visible action
(build artifact publish, infrastructure provision, deployment) MUST be preceded
by a dry-run gate.

- **Phase 1 (Dry-Run)**: The pipeline simulates the action, emits a plan, and pauses.
- **Phase 2 (Execute)**: Only proceeds when `DRY_RUN` is explicitly set to `false`.

All agent-triggered pipeline runs default to `DRY_RUN=true` (Gateway-enforced).

---

## Environment Variable Convention

| Variable | Type | Default | Meaning |
|----------|------|---------|---------|
| `DRY_RUN` | string/boolean | `true` | When `true`, simulate only; when `false`, execute |
| `DRY_RUN_DIFF_OUTPUT` | path | `./dry-run.diff` | Where to write the simulated plan diff |
| `GATE_APPROVAL` | string | `"pending"` | Human gate state: `pending`, `approved`, `rejected` |

---

## GitHub Actions

### Workflow Dispatch Input

```yaml
on:
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Run in dry-run mode (simulation only)'
        required: true
        default: 'true'
        type: choice
        options:
          - 'true'
          - 'false'

env:
  DRY_RUN: ${{ github.event.inputs.dry_run || 'true' }}
```

### Job-Level Gate

```yaml
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Dry-Run Plan
        run: |
          echo "[DRY-RUN] Generating deployment plan..."
          # Generate plan output (e.g., terraform plan, helm diff)
          echo "--- PLAN ---" > dry-run.diff
          cat dry-run.diff
      - name: Execute Gate
        if: ${{ env.DRY_RUN != 'true' }}
        run: |
          echo "[EXECUTE] DRY_RUN is false. Proceeding with deployment."
      - name: Deploy
        if: ${{ env.DRY_RUN != 'true' }}
        run: |
          echo "[DEPLOY] Running actual deployment..."
```

### Reusable Dry-Run Composite Action

```yaml
# .github/actions/dry-run-gate/action.yml
name: 'Dry-Run Gate'
description: 'Enforce dry-run before execute'
inputs:
  dry_run:
    description: 'Whether to run in dry-run mode'
    required: true
    default: 'true'
  plan_command:
    description: 'Command to generate the dry-run plan'
    required: true
  execute_command:
    description: 'Command to execute if dry_run is false'
    required: true
runs:
  using: 'composite'
  steps:
    - shell: bash
      run: |
        echo "[DRY-RUN] Running plan command..."
        ${{ inputs.plan_command }}
    - shell: bash
      if: ${{ inputs.dry_run != 'true' }}
      run: |
        echo "[EXECUTE] Dry run disabled. Executing..."
        ${{ inputs.execute_command }}
```

---

## GitLab CI

### Variable-Based Routing

```yaml
variables:
  DRY_RUN: "true"

stages:
  - plan
  - execute

dry-run-plan:
  stage: plan
  script:
    - echo "[DRY-RUN] Generating deployment plan..."
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - tfplan

execute-deploy:
  stage: execute
  rules:
    - if: $DRY_RUN == "false"
  script:
    - echo "[EXECUTE] DRY_RUN is false. Proceeding with deployment."
    - terraform apply tfplan
```

### Manual Gate with Dry-Run Default

```yaml
production-deploy:
  stage: production
  when: manual
  script:
    - echo '[DRY-RUN] Deployment plan for production'
    - |
      if [ "$DRY_RUN" = "true" ]; then
        echo "Simulation complete. Set DRY_RUN=false and re-run to execute."
        exit 0
      fi
    - echo '[DEPLOY] Deploying to production environment'
```

---

## Jenkins

### Parameter-Based Gate

```groovy
pipeline {
    parameters {
        booleanParam(
            name: 'DRY_RUN',
            defaultValue: true,
            description: 'Run in dry-run mode (simulation only)'
        )
    }
    stages {
        stage('Plan') {
            steps {
                echo '[DRY-RUN] Generating deployment plan...'
                sh 'terraform plan -out=tfplan'
            }
        }
        stage('Execute') {
            when {
                expression { !params.DRY_RUN }
            }
            steps {
                echo '[EXECUTE] DRY_RUN is false. Proceeding with deployment.'
                sh 'terraform apply tfplan'
            }
        }
    }
}
```

### Shared Library Step

```groovy
// vars/dryRunGate.groovy
def call(Map config) {
    def isDryRun = params.DRY_RUN ?: true
    stage('Dry-Run Plan') {
        echo "[DRY-RUN] Running: ${config.planCommand}"
        sh config.planCommand
    }
    if (!isDryRun) {
        stage('Execute') {
            echo "[EXECUTE] Running: ${config.executeCommand}"
            sh config.executeCommand
        }
    } else {
        echo "[SKIP] DRY_RUN=true. Execute stage skipped."
    }
}
```

Usage:

```groovy
dryRunGate(
    planCommand: 'terraform plan -out=tfplan',
    executeCommand: 'terraform apply tfplan'
)
```

---

## Kubernetes / Helm Dry-Run

```bash
# Helm dry-run + diff
helm diff upgrade my-app ./chart --namespace prod

# Kubernetes dry-run apply
kubectl apply -f manifest.yaml --dry-run=server

# Terraform plan (always dry-run first)
terraform plan -out=tfplan
```

---

## Terraform-Specific Gates

```bash
# Phase 1: Plan (always)
terraform plan -out=tfplan -var-file="$ENV.tfvars"

# Phase 2: Apply (gated)
if [ "$DRY_RUN" = "true" ]; then
  echo "[DRY-RUN] Plan saved to tfplan. Review and set DRY_RUN=false to apply."
else
  terraform apply tfplan
fi
```

---

## Pulumi-Specific Gates

```bash
# Phase 1: Preview (always)
pulumi preview --diff

# Phase 2: Up (gated)
if [ "$DRY_RUN" = "true" ]; then
  echo "[DRY-RUN] Preview complete. Set DRY_RUN=false to update."
else
  pulumi up --yes
fi
```

---

## AWS CloudFormation / CDK Dry-Run

```bash
# CloudFormation change set (dry-run)
aws cloudformation create-change-set \
  --stack-name my-stack \
  --template-body file://template.yaml \
  --change-set-name dry-run-$(date +%s) \
  --change-set-type UPDATE

# Review changes, then execute if DRY_RUN=false
if [ "$DRY_RUN" = "false" ]; then
  aws cloudformation execute-change-set \
    --stack-name my-stack \
    --change-set-name <change-set-name>
fi
```

---

## Dry-Run Gate Checklist

- [ ] `DRY_RUN` env var/parameter is defined with default `true`
- [ ] Plan stage runs unconditionally and produces human-readable diff
- [ ] Execute stage is wrapped in `if DRY_RUN != true`
- [ ] Secrets are NOT exposed in plan output (use `::add-mask::`, `masked: true`, `withCredentials`)
- [ ] Artifact from plan stage is passed to execute stage (e.g., `tfplan`, change set name)
- [ ] Pipeline logs clearly distinguish `[DRY-RUN]` vs `[EXECUTE]`
- [ ] Human approval gate exists between plan and execute for production

---

## Plan / Apply Separation (v4.0)

All generated pipelines must separate **plan** (simulation) from **apply** (execution).
The plan stage produces an artifact; the apply stage consumes it and requires explicit human approval.

### GitHub Actions — Plan / Apply

```yaml
jobs:
  production-plan:
    runs-on: ubuntu-latest
    needs: canary-100pct
    steps:
      - uses: actions/checkout@v4
      - name: Generate Plan
        run: |
          echo "[PLAN] Generating deployment plan..."
          terraform plan -out=tfplan
      - uses: actions/upload-artifact@v4
        with:
          name: production-plan
          path: tfplan

  production-apply:
    runs-on: ubuntu-latest
    needs: production-plan
    environment: production  # Human approval gate
    steps:
      - uses: actions/checkout@v4
      - name: Download Plan
        uses: actions/download-artifact@v4
        with:
          name: production-plan
      - name: Apply Gate
        if: ${{ env.DRY_RUN != 'true' }}
        run: |
          echo "[EXECUTE] DRY_RUN is false. Proceeding with apply."
          terraform apply tfplan
```

### GitLab CI — Plan / Apply

```yaml
stages:
  - plan
  - production

production-plan:
  stage: plan
  script:
    - echo "[PLAN] Generating deployment plan..."
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - tfplan

production-apply:
  stage: production
  needs: [production-plan]
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  script:
    - echo "[GATE] Human must click Play to trigger apply."
    - |
      if [ "$DRY_RUN" = "true" ]; then
        echo "Simulation complete. Set DRY_RUN=false to execute."
        exit 0
      fi
    - terraform apply tfplan
```

### Jenkins — Plan / Apply

```groovy
    stage('Production Plan') {
        steps {
            echo '[PLAN] Generating deployment plan...'
            sh 'terraform plan -out=tfplan'
            archiveArtifacts artifacts: 'tfplan', allowEmptyArchive: false
        }
    }

    stage('Human Approval Gate') {
        steps {
            timeout(time: 24, unit: 'HOURS') {
                input message: 'Approve production deployment?',
                      ok: 'Deploy',
                      submitterParameter: 'APPROVER',
                      parameters: [
                          choice(name: 'DEPLOY_DECISION', choices: ['NO', 'YES'], description: 'Human confirmation required')
                      ]
            }
        }
    }

    stage('Production Apply') {
        when {
            expression { !params.DRY_RUN }
        }
        steps {
            echo '[EXECUTE] DRY_RUN is false. Proceeding with apply.'
            sh 'terraform apply tfplan'
        }
    }
```

---

## CI-Triggered Agent Invocation — `--dry-run` Enforcement

All Kimi agent invocations triggered from CI pipelines **must** include the `--dry-run` flag.
This prevents the agent from performing unreviewed destructive actions inside a CI environment.

### GitHub Actions

```yaml
  kimi-agent-dry-run:
    runs-on: ubuntu-latest
    if: github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
      - name: Kimi Agent Dry-Run
        run: |
          echo "[AGENT] Invoking Kimi agent with --dry-run flag"
          # kimi-agent --dry-run deploy --env production
```

### GitLab CI

```yaml
kimi-agent-dry-run:
  stage: plan
  rules:
    - if: $CI_PIPELINE_SOURCE == 'web'
  script:
    - echo "[AGENT] Invoking Kimi agent with --dry-run flag"
    - echo "# kimi-agent --dry-run deploy --env production"
```

### Jenkins

```groovy
    stage('Kimi Agent Dry-Run') {
        steps {
            echo '[AGENT] Invoking Kimi agent with --dry-run flag'
            sh 'echo "kimi-agent --dry-run deploy --env production"'
        }
    }
```

> **Rule:** The agent **never** invokes itself without `--dry-run` when triggered by a CI event (`push`, `pull_request`, `schedule`, `workflow_dispatch`).
> A human must explicitly remove `--dry-run` during an interactive session to authorize execution.

---

## Updated Dry-Run Gate Checklist (v4.0)

- [ ] `DRY_RUN` env var/parameter is defined with default `true`
- [ ] Plan stage runs unconditionally and produces human-readable diff
- [ ] Execute stage is wrapped in `if DRY_RUN != true`
- [ ] Secrets are NOT exposed in plan output (use `::add-mask::`, `masked: true`, `withCredentials`)
- [ ] Artifact from plan stage is passed to execute stage (e.g., `tfplan`, change set name)
- [ ] Pipeline logs clearly distinguish `[DRY-RUN]` vs `[EXECUTE]`
- [ ] Human approval gate exists between plan and execute for production
- [ ] **Plan and apply are separate stages**; apply requires human approval
- [ ] **Agent invocations from CI always use `--dry-run`**
- [ ] **Secret scan (`scan-secrets.py`) runs on all generated YAML before delivery**
