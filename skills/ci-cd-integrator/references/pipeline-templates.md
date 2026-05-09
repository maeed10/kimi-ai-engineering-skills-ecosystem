# Pipeline Stage Templates

Reference for CI/CD stage templates across GitHub Actions, GitLab CI, and Jenkins.
Each template includes Kimi skill hook placeholders, dry-run gates, and rollback wiring.

---

## Stage 1: Build

### GitHub Actions

```yaml
  build:
    runs-on: ubuntu-latest
    container:
      image: <project-image>
    steps:
      - uses: actions/checkout@v4
      - name: Build
        run: |
          # <project-build-command>
      - name: Dry-Run Gate
        run: |
          if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] Skipping artifact publish"
            exit 0
          fi
      - uses: actions/upload-artifact@v4
        with:
          name: build-artifacts
          path: <artifact-path>
```

### GitLab CI

```yaml
build:
  image: <project-image>
  stage: build
  script:
    - echo '[BUILD] Starting build...'
    - <project-build-command>
  artifacts:
    paths:
      - <artifact-path>
```

### Jenkins

```groovy
stage('Build') {
    steps {
        echo '[BUILD] Starting build...'
        sh '<project-build-command>'
    }
    post {
        success {
            archiveArtifacts artifacts: '<artifact-path>**', allowEmptyArchive: true
        }
    }
}
```

---

## Stage 2: Test — Code Tester Hook

### GitHub Actions

```yaml
  code-tester:
    runs-on: ubuntu-latest
    needs: build
    # KIMI_HOOK: Code Tester — run tests and coverage
    steps:
      - uses: actions/checkout@v4
      - name: Run Tests
        run: |
          echo "[KIMI_HOOK] Trigger Code Tester"
          # Placeholder: invoke Code Tester skill / run test suite
```

### GitLab CI

```yaml
code-tester:
  stage: test
  needs: [build]
  script:
    - echo '[KIMI_HOOK] Trigger Code Tester'
    - echo 'Placeholder: run tests via Code Tester skill'
```

### Jenkins

```groovy
stage('Code Tester') {
    steps {
        echo '[KIMI_HOOK] Trigger Code Tester'
        echo 'Placeholder: run tests via Code Tester skill'
    }
}
```

---

## Stage 3: Security Scan — Security Auditor Hook

### GitHub Actions

```yaml
  security-auditor:
    runs-on: ubuntu-latest
    needs: code-tester
    # KIMI_HOOK: Security Auditor — pre-merge gate
    steps:
      - uses: actions/checkout@v4
      - name: Security Scan
        run: |
          echo "[KIMI_HOOK] Trigger Security Auditor"
          # Placeholder: SAST / dependency scan
```

### GitLab CI

```yaml
security-auditor:
  stage: security-scan
  needs: [code-tester]
  script:
    - echo '[KIMI_HOOK] Trigger Security Auditor'
    - echo 'Placeholder: SAST / dependency scan'
  allow_failure: false
```

### Jenkins

```groovy
stage('Security Auditor') {
    steps {
        echo '[KIMI_HOOK] Trigger Security Auditor'
        echo 'Placeholder: SAST / dependency scan'
    }
}
```

---

## Stage 4: Blast Radius — Blast Radius Calculator Hook

### GitHub Actions

```yaml
  blast-radius:
    runs-on: ubuntu-latest
    needs: build
    # KIMI_HOOK: Blast Radius Calculator — impact analysis on PR
    steps:
      - uses: actions/checkout@v4
      - name: Blast Radius Analysis
        run: |
          echo "[KIMI_HOOK] Trigger Blast Radius Calculator"
          echo "Analyze changed files for downstream impact"
```

### GitLab CI

```yaml
blast-radius:
  stage: blast-radius
  needs: [build]
  script:
    - echo '[KIMI_HOOK] Trigger Blast Radius Calculator'
    - echo 'Placeholder: analyze downstream impact of changes'
```

### Jenkins

```groovy
stage('Blast Radius') {
    steps {
        echo '[KIMI_HOOK] Trigger Blast Radius Calculator'
        echo 'Placeholder: analyze downstream impact'
    }
}
```

---

## Stage 5: Provision — Infrastructure-as-Code Hook

### GitHub Actions

```yaml
  infra-as-code:
    runs-on: ubuntu-latest
    needs: build
    # KIMI_HOOK: Infrastructure-as-Code — provision environment
    steps:
      - uses: actions/checkout@v4
      - name: Provision Environment
        run: |
          echo "[KIMI_HOOK] Trigger Infrastructure-as-Code provision"
          if [ "$DRY_RUN" = "true" ]; then
            echo "[DRY-RUN] terraform plan / pulumi preview"
          else
            echo "[EXECUTE] terraform apply / pulumi up"
          fi
```

### GitLab CI

```yaml
infra-as-code:
  stage: provision
  needs: [build]
  script:
    - echo '[KIMI_HOOK] Trigger Infrastructure-as-Code provision'
    - |
      if [ "$DRY_RUN" = "true" ]; then
        echo "[DRY-RUN] terraform plan / pulumi preview"
      else
        echo "[EXECUTE] terraform apply / pulumi up"
      fi
```

### Jenkins

```groovy
stage('Infrastructure-as-Code') {
    steps {
        echo '[KIMI_HOOK] Trigger Infrastructure-as-Code provision'
        script {
            if (params.DRY_RUN) {
                echo '[DRY-RUN] terraform plan / pulumi preview'
            } else {
                echo '[EXECUTE] terraform apply / pulumi up'
            }
        }
    }
}
```

---

## Stage 6: Performance Gate — Performance Validator Hook

### GitHub Actions

```yaml
  performance-validator:
    runs-on: ubuntu-latest
    needs: staging-deploy
    # KIMI_HOOK: Performance Validator — regression gate
    steps:
      - uses: actions/checkout@v4
      - name: Performance Regression Check
        run: |
          echo "[KIMI_HOOK] Trigger Performance Validator"
          # Placeholder: run load tests and compare metrics
```

### GitLab CI

```yaml
performance-validator:
  stage: performance-gate
  needs: [staging]
  script:
    - echo '[KIMI_HOOK] Trigger Performance Validator'
    - echo 'Placeholder: load tests and metric comparison'
```

### Jenkins

```groovy
stage('Performance Validator') {
    steps {
        echo '[KIMI_HOOK] Trigger Performance Validator'
        echo 'Placeholder: load tests and metric comparison'
    }
}
```

---

## Stage 7: Contract Check — API Contract Tester Hook

### GitHub Actions

```yaml
  api-contract-tester:
    runs-on: ubuntu-latest
    needs: performance-validator
    # KIMI_HOOK: API Contract Tester — backward-compatibility gate
    steps:
      - uses: actions/checkout@v4
      - name: API Contract Check
        run: |
          echo "[KIMI_HOOK] Trigger API Contract Tester"
          # Placeholder: run contract tests against staging
```

### GitLab CI

```yaml
api-contract-tester:
  stage: contract-check
  needs: [performance-gate]
  script:
    - echo '[KIMI_HOOK] Trigger API Contract Tester'
    - echo 'Placeholder: contract tests against staging'
  allow_failure: false
```

### Jenkins

```groovy
stage('API Contract Tester') {
    steps {
        echo '[KIMI_HOOK] Trigger API Contract Tester'
        echo 'Placeholder: contract tests against staging'
    }
}
```

---

## Stage 8: Staging Deploy

### GitHub Actions

```yaml
  staging-deploy:
    runs-on: ubuntu-latest
    needs: [api-contract-tester]
    steps:
      - uses: actions/checkout@v4
      - name: Dry-Run Plan
        run: |
          echo "[DRY-RUN] Deployment plan for staging"
          if [ "$DRY_RUN" = "true" ]; then
            echo "Simulation complete"
            exit 0
          fi
      - name: Deploy to Staging
        run: |
          echo "[DEPLOY] Deploying to staging environment"
```

### GitLab CI

```yaml
staging-deploy:
  stage: staging
  needs: [api-contract-tester]
  script:
    - echo '[DRY-RUN] Deployment plan for staging'
    - |
      if [ "$DRY_RUN" = "true" ]; then
        echo "Simulation complete"
        exit 0
      fi
    - echo '[DEPLOY] Deploying to staging environment'
```

### Jenkins

```groovy
stage('Staging Deploy') {
    steps {
        echo '[DRY-RUN] Deployment plan for staging'
        script {
            if (params.DRY_RUN) {
                echo 'Simulation complete'
            } else {
                echo '[DEPLOY] Deploying to staging environment'
            }
        }
    }
}
```

---

## Stage 9: Canary Deployment

### GitHub Actions

```yaml
  canary-5pct:
    runs-on: ubuntu-latest
    needs: staging-deploy
    env:
      CANARY_TRAFFIC: 5
    steps:
      - uses: actions/checkout@v4
      - name: Canary 5% Rollout
        run: |
          echo "[CANARY] Routing 5% traffic to new version"
      - name: Monitor Metrics
        run: |
          echo "[ROLLBACK_GATE] error_rate < $ROLLBACK_ERROR_RATE && p99 < $ROLLBACK_P99_MS ms"

  canary-25pct:
    runs-on: ubuntu-latest
    needs: canary-5pct
    env:
      CANARY_TRAFFIC: 25
    steps:
      - uses: actions/checkout@v4
      - name: Canary 25% Rollout
        run: |
          echo "[CANARY] Routing 25% traffic to new version"
      - name: Monitor Metrics
        run: |
          echo "[ROLLBACK_GATE] error_rate < $ROLLBACK_ERROR_RATE && p99 < $ROLLBACK_P99_MS ms"
```

### GitLab CI

```yaml
canary-5pct:
  stage: canary
  needs: [staging-deploy]
  variables:
    CANARY_TRAFFIC: "5"
  script:
    - echo '[CANARY] Routing 5% traffic to new version'
    - echo '[ROLLBACK_GATE] error_rate < $ROLLBACK_ERROR_RATE && p99 < $ROLLBACK_P99_MS ms'

canary-25pct:
  stage: canary
  needs: [canary-5pct]
  variables:
    CANARY_TRAFFIC: "25"
  script:
    - echo '[CANARY] Routing 25% traffic to new version'
    - echo '[ROLLBACK_GATE] error_rate < $ROLLBACK_ERROR_RATE && p99 < $ROLLBACK_P99_MS ms'
```

### Jenkins

```groovy
stage('Canary 5%') {
    environment {
        CANARY_TRAFFIC = '5'
    }
    steps {
        echo '[CANARY] Routing 5% traffic to new version'
        echo '[ROLLBACK_GATE] error_rate < 0.01 && p99 < 500 ms'
    }
}

stage('Canary 25%') {
    environment {
        CANARY_TRAFFIC = '25'
    }
    steps {
        echo '[CANARY] Routing 25% traffic to new version'
        echo '[ROLLBACK_GATE] error_rate < 0.01 && p99 < 500 ms'
    }
}
```

---

## Stage 10: Production Deploy (Plan / Apply + External Approval Gate)

All production deploy templates separate **plan** from **apply** and require an **external human approval gate** that the agent cannot bypass.

### GitHub Actions

```yaml
  production-plan:
    runs-on: ubuntu-latest
    needs: [canary-100pct]
    environment: production
    steps:
      - uses: actions/checkout@v4
      - name: Generate Production Plan
        run: |
          echo "[PLAN] Generating deployment plan for production..."
          # Placeholder: terraform plan -out=tfplan, helm diff, etc.
      - name: Upload Plan Artifact
        uses: actions/upload-artifact@v4
        with:
          name: production-plan
          path: "plan-artifact/"

  production-apply:
    runs-on: ubuntu-latest
    needs: production-plan
    environment:
      name: production
      # REQUIRED_REVIEWERS: configured in repo Settings -> Environments
      # The agent CANNOT bypass this gate.
    steps:
      - uses: actions/checkout@v4
      - name: Human Approval Gate
        run: |
          echo "[GATE] This job only runs after a human approves the production environment."
      - name: Dry-Run Check
        run: |
          echo "[DRY-RUN] DRY_RUN=${DRY_RUN}"
          if [ "$DRY_RUN" = "true" ]; then
            echo "Simulation complete. Set DRY_RUN=false to execute."
            exit 0
          fi
      - name: Deploy to Production
        run: |
          echo "[DEPLOY] Deploying to production environment"
          # Placeholder: actual production deploy command
```

### GitLab CI

```yaml
production-plan:
  stage: plan
  needs: [canary-100pct]
  script:
    - echo "[PLAN] Generating deployment plan for production..."
    - terraform plan -out=tfplan  # Placeholder: plan command
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
      allow_failure: false
  script:
    - echo "[GATE] Human must click Play to trigger this job. Agent CANNOT bypass."
    - echo "[DRY-RUN] DRY_RUN=$DRY_RUN"
    - |
      if [ "$DRY_RUN" = "true" ]; then
        echo "Simulation complete. Set DRY_RUN=false to execute."
        exit 0
      fi
    - echo "[DEPLOY] Deploying to production environment"
    - terraform apply tfplan
```

### Jenkins

```groovy
stage('Production Plan') {
    steps {
        echo '[PLAN] Generating deployment plan for production...'
        sh 'terraform plan -out=tfplan'
        archiveArtifacts artifacts: 'tfplan', allowEmptyArchive: false
    }
}

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
                echo "[GATE] Approved by ${approvers.APPROVER}"
            }
        }
    }
}

stage('Production Apply') {
    when {
        expression { !params.DRY_RUN }
    }
    steps {
        echo '[DEPLOY] Deploying to production environment'
        sh 'terraform apply tfplan'
    }
}
```

---

## Stage 11: Rollback (on Failure)

### GitHub Actions

```yaml
  rollback:
    runs-on: ubuntu-latest
    if: failure()
    steps:
      - uses: actions/checkout@v4
      - name: Execute Rollback
        run: |
          echo "[ROLLBACK] Reverting to last stable artifact"
          # Placeholder: kubectl rollout undo / ecs update-service / blue-green swap
      - name: Notify
        run: |
          echo "[ALERT] Rollback executed — notify on-call"
```

### GitLab CI

```yaml
rollback:
  stage: rollback
  when: on_failure
  script:
    - echo '[ROLLBACK] Reverting to last stable artifact'
    - echo 'Placeholder: kubectl rollout undo / ecs update-service / swap'
    - echo '[ALERT] Rollback executed — notify on-call'
```

### Jenkins

```groovy
post {
    failure {
        echo '[KIMI_HOOK] Trigger Log Analyzer on build failure'
        echo 'Placeholder: fetch logs and analyze root cause'
    }
    unstable {
        echo '[ROLLBACK] Reverting to last stable artifact'
        echo 'Placeholder: kubectl rollout undo / ecs update-service / swap'
        echo '[ALERT] Rollback executed — notify on-call'
    }
}
```

---

## Stage 12: Kimi Agent CI Invocation (always `--dry-run`)

All Kimi agent invocations triggered from CI must include the `--dry-run` flag.

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

---

## Dry-Run Gate Patterns

### GitHub Actions

Use a `workflow_dispatch` input defaulting to `true`, or an environment variable `DRY_RUN`:

```yaml
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Run in dry-run mode'
        required: true
        default: 'true'
```

In each stage, check `if: github.event.inputs.dry_run != 'true'` for execute branches.

### GitLab CI

Use `rules:if` or branch on `$DRY_RUN` in script blocks:

```yaml
  rules:
    - if: $DRY_RUN == "true"
      when: manual
```

### Jenkins

Use a `booleanParam` with default `true`:

```groovy
parameters {
    booleanParam(name: 'DRY_RUN', defaultValue: true, description: 'Simulation only')
}
```

Wrap execute steps in `script { if (!params.DRY_RUN) { ... } }`.

---

## Feature Flag Coordination Templates

### LaunchDarkly (config-based)

```yaml
  - name: Feature Flag Ramp
    run: |
      echo "[FEATURE_FLAG] Enabling flag for canary slice: $CANARY_TRAFFIC%"
      # Placeholder: LD API call to target canary segment
      # curl -X PATCH https://app.launchdarkly.com/api/v2/flags/$LD_PROJECT/$FLAG_KEY \
      #   -H "Authorization: $LD_API_TOKEN" \
      #   -d '{...target canary segment...}'
```

### Unleash (config-based)

```yaml
  - name: Feature Flag Ramp
    run: |
      echo "[FEATURE_FLAG] Enabling flag for canary slice: $CANARY_TRAFFIC%"
      # Placeholder: Unleash API call to update strategy
      # curl -X PUT "$UNLEASH_URL/api/admin/features/$FLAG_NAME" \
      #   -H "Authorization: $UNLEASH_API_TOKEN" \
      #   -d '{...canary strategy...}'
```

### Config-based fallback (`feature-flags.yml`)

```yaml
  - name: Update Feature Flags
    run: |
      echo "[FEATURE_FLAG] Updating feature-flags.yml for canary $CANARY_TRAFFIC%"
      sed -i "s/canary_traffic: .*/canary_traffic: $CANARY_TRAFFIC/" feature-flags.yml
      # Commit and push via automated PR, or apply via configmap reload
```

---

## Secret Masking by Platform

### GitHub Actions

```yaml
  - name: Mask Secret
    run: echo "::add-mask::${{ secrets.MY_TOKEN }}"
```

NEVER echo secrets. Use `secrets.*` context only.

### GitLab CI

```yaml
variables:
  MY_TOKEN:
    value: "<from CI/CD variables UI>"
    masked: true
```

Set `masked: true` and `protected: true` in project CI/CD variable settings.

### Jenkins

```groovy
withCredentials([string(credentialsId: 'my-token', variable: 'MY_TOKEN')]) {
    sh 'echo $MY_TOKEN | base64'  // still masked in console log
}
```

Use `withCredentials` or `usernamePassword` blocks. NEVER inline credentials in `Jenkinsfile`.

---

## Secret-Free Template Rules (v4.0)

When generating any pipeline template, the generator **must**:

1. **Never** emit plaintext API keys, tokens, passwords, or private keys.
2. **Always** use platform-native secret placeholders:
   - GitHub Actions: `${{ secrets.SECRET_NAME }}`
   - GitLab CI: `"${SECRET_NAME}"` (value defined in CI/CD Variables, `masked: true`)
   - Jenkins: `withCredentials([string(credentialsId: 'secret-name', variable: 'SECRET_NAME')])`
3. **Always** run `scan-secrets.py` on generated output before delivery.
4. **Block** generation if any secret pattern is detected; surface findings to the user for remediation.

---

## Updated Template Checklist (v4.0)

- [ ] Build stage includes dry-run gate before artifact publish
- [ ] Test and security scan stages include Kimi skill hook placeholders
- [ ] Staging deploy uses plan/apply separation with dry-run default `true`
- [ ] Canary stages include metric-based rollback gate
- [ ] Production deploy has **separate plan and apply stages**
- [ ] Production apply requires **external human approval** (environment protection, manual job, or input step)
- [ ] Agent CI invocation includes `--dry-run` flag
- [ ] No plaintext secrets embedded in YAML; all secrets use platform-native placeholders
- [ ] Secret scan (`scan-secrets.py`) passes on generated output
