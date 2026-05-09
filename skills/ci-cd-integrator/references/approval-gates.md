# External Human Approval Gate Specifications

Reference for CI-native human approval gates that are **enforced by the platform** and **cannot be bypassed by the Kimi agent**.

These gates are critical for SEC-8.2 (severity 8/10) compliance: they guarantee that production deployment requires an independent human decision, even if all automated checks pass.

---

## Concept

The agent generates pipeline configurations that declare approval gates. The agent **does not** and **cannot** approve these gates programmatically because:

- GitHub Environments require a human with `repo` or `environment` write access to click "Approve".
- GitLab manual jobs require a human with `Developer` or `Maintainer` role to click "Play".
- Jenkins `input` steps pause the pipeline until a human with `Job/Build` permission responds.

> **Rule:** The agent CI user / service account must **NOT** be granted permissions that allow it to bypass these gates.

---

## GitHub Actions

### Environment Protection Rules

GitHub Actions uses **deployment environments** with protection rules to enforce human approval.

#### Repository Configuration (Manual Step)

1. Go to **Settings → Environments → New environment**.
2. Name the environment `production`.
3. Enable **Required reviewers** and add at least one human reviewer.
4. Optionally enable **Wait timer**, **Deployment branches**, and **Prevent self-review**.

#### Generated Pipeline Snippet

```yaml
jobs:
  production-plan:
    runs-on: ubuntu-latest
    needs: canary-100pct
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Generate Production Plan
        run: |
          echo "[PLAN] Generating deployment plan for production..."
          # e.g., terraform plan -out=tfplan
          echo "plan-artifact=tfplan" >> "$GITHUB_OUTPUT"

  production-apply:
    runs-on: ubuntu-latest
    needs: production-plan
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Human Approval Gate
        run: |
          echo "[GATE] This job only runs after a human approves the 'production' environment."
      - name: Deploy to Production
        run: |
          echo "[DEPLOY] Deploying to production environment"
```

> **Note:** Re-declaring `environment: production` on the apply job forces a second approval check if the environment is configured to require reviewers on every deployment job.

### Required Reviewers in Workflow (Declarative Hint)

While the actual reviewer list is configured in repository settings, the pipeline should include a comment block documenting the requirement:

```yaml
  production-apply:
    runs-on: ubuntu-latest
    needs: production-plan
    environment:
      name: production
      # REQUIRED_REVIEWERS: configured in repo Settings → Environments
      # The agent CANNOT bypass this gate.
    steps:
      ...
```

---

## GitLab CI

### Manual Job Stage with Protected Environment

GitLab CI uses `when: manual` combined with `protected` environments to enforce human approval.

#### Project Configuration (Manual Step)

1. Go to **Settings → CI/CD → Protected environments**.
2. Add `production` as a protected environment.
3. Ensure only `Maintainer` or `Owner` roles can deploy to protected environments.
4. Enable **Prevent approval by author** (requires GitLab Premium+).

#### Generated Pipeline Snippet

```yaml
stages:
  - plan
  - production

production-plan:
  stage: plan
  script:
    - echo "[PLAN] Generating deployment plan for production..."
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - tfplan

production-apply:
  stage: production
  needs: [production-plan]
  environment:
    name: production
    deployment_tier: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
  script:
    - echo "[GATE] Human must click 'Play' to trigger this job."
    - echo "[DEPLOY] Deploying to production environment"
    - terraform apply tfplan
```

### Multi-Stage Approval with Required Jobs

For stricter separation, add an intermediate `approval` stage:

```yaml
stages:
  - plan
  - approval
  - production

production-approval:
  stage: approval
  needs: [production-plan]
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  script:
    - echo "[APPROVAL] Waiting for human approval..."
    - echo "Approved by $GITLAB_USER_NAME"

production-apply:
  stage: production
  needs: [production-approval]
  environment:
    name: production
  script:
    - echo "[DEPLOY] Deploying to production environment"
```

> **Note:** `allow_failure: false` on the manual job prevents the pipeline from being considered successful until the human triggers production.

---

## Jenkins

### Input Step with Human Choice Parameter

Jenkins uses the `input` step to pause a pipeline until a human responds.

#### Generated Pipeline Snippet

```groovy
pipeline {
    agent any

    stages {
        stage('Production Plan') {
            steps {
                echo '[PLAN] Generating deployment plan for production...'
                sh 'terraform plan -out=tfplan'
                archiveArtifacts artifacts: 'tfplan', allowEmptyArchive: false
            }
        }

        stage('Human Approval Gate') {
            steps {
                script {
                    def approvers = input(
                        message: 'Approve production deployment?',
                        ok: 'Deploy',
                        submitterParameter: 'APPROVER',
                        parameters: [
                            choice(
                                name: 'DEPLOY_DECISION',
                                choices: ['NO', 'YES'],
                                description: 'Human confirmation required'
                            )
                        ]
                    )
                    if (approvers.DEPLOY_DECISION != 'YES') {
                        error('[BLOCKED] Production deployment was rejected by human.')
                    }
                    echo "[GATE] Approved by ${approvers.APPROVER}"
                }
            }
        }

        stage('Production Apply') {
            when {
                expression { currentBuild.result == null || currentBuild.result == 'SUCCESS' }
            }
            steps {
                echo '[DEPLOY] Deploying to production environment'
                sh 'terraform apply tfplan'
            }
        }
    }
}
```

### Timeout to Prevent Indefinite Blocking

Always wrap `input` in a `timeout` to prevent a runaway or forgotten pipeline from consuming an executor indefinitely:

```groovy
        stage('Human Approval Gate') {
            steps {
                timeout(time: 24, unit: 'HOURS') {
                    script {
                        def approvers = input(
                            message: 'Approve production deployment?',
                            ok: 'Deploy',
                            submitterParameter: 'APPROVER',
                            parameters: [
                                choice(
                                    name: 'DEPLOY_DECISION',
                                    choices: ['NO', 'YES'],
                                    description: 'Human confirmation required'
                                )
                            ]
                        )
                        if (approvers.DEPLOY_DECISION != 'YES') {
                            error('[BLOCKED] Production deployment was rejected by human.')
                        }
                    }
                }
            }
        }
```

### Role-Based Restriction

The Jenkins agent service account should **not** have `Job/Build` permission that allows it to programmatically submit inputs. Restrict `input` submitters via Jenkins role strategy:

```groovy
                    def approvers = input(
                        message: 'Approve production deployment?',
                        ok: 'Deploy',
                        submitter: 'prod-approvers',  // Jenkins group / role
                        submitterParameter: 'APPROVER',
                        ...
                    )
```

---

## Agent Bypass Prevention Matrix

| Platform | Gate Mechanism | Agent Bypass Risk | Mitigation |
|----------|---------------|-------------------|------------|
| GitHub Actions | Environment protection rules + required reviewers | Low | Agent service account lacks `repo` admin; `prevent self-review` enabled |
| GitLab CI | `when: manual` + protected environment | Low | Agent user is `Developer` or lower; protected env restricted to `Maintainer`+ |
| Jenkins | `input` step with `submitter` restriction | Low | Agent user lacks `Job/Build`; input restricted to human group |

---

## Approval Gate Checklist

- [ ] Production deploy stage is wrapped in a CI-native approval mechanism (environment protection, manual job, or input step)
- [ ] Agent service account does **not** have permissions to bypass the gate
- [ ] At least one independent human reviewer is required
- [ ] `prevent self-review` or equivalent is enabled where available
- [ ] Approval timeout is configured to prevent indefinite pipeline blocking
- [ ] Plan artifact is generated and visible to the human before they approve
- [ ] Pipeline logs clearly label `[GATE]`, `[PLAN]`, and `[DEPLOY]` stages
