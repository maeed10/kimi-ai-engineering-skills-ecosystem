---
name: ci-cd-integrator
description: >
  Generates, validates, and manages CI/CD pipeline configurations for GitHub Actions,
  GitLab CI, and Jenkins. Integrates Kimi agent skills at pipeline hooks, handles
  canary deployments with traffic splitting, feature flag coordination, automated
  rollback, dry-run gates, secret-free template generation, and external human
  approval gates. Triggers when the user asks to "set up CI/CD",
  "create pipeline", "add deployment pipeline", "configure GitHub Actions/GitLab CI/Jenkins",
  "promote to staging/production", "add canary deployment", or "configure rollback".
---

# CI/CD Integrator

## What it does
Generates production-ready CI/CD pipeline configurations with embedded Kimi skill hooks,
canary deployment strategies, feature flag coordination, automated rollback triggers,
**secret-free templates**, **external human approval gates**, and **dry-run enforcement**.
Validates syntax, scans for embedded secrets, and enforces dry-run gates between
promotion stages.

## When to use
- User asks to "set up CI/CD", "create a pipeline", "configure GitHub Actions", "configure GitLab CI", or "configure Jenkins"
- User requests canary deployment, feature flag integration, or automated rollback setup
- User needs to promote a service through build → test → staging → production stages
- A build failure or deployment failure requires pipeline remediation or rollback plan generation
- User asks to add agent skill triggers (Blast Radius, Code Tester, Security Auditor, etc.) to an existing pipeline
- Infrastructure-as-Code requires pipeline linkage for environment provisioning

## Key capabilities
- **Pipeline generation** — Produces `.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`, or updates existing configs
- **Skill hook integration** — Embeds Kimi skill triggers at CI events (PR open, build fail, scan, merge gate)
- **Canary deployment** — Generates traffic-split configs with metric-based promotion and auto-rollback
- **Feature flag coordination** — Injects LaunchDarkly, Unleash, or config-based flag toggles into canary stages
- **Automated rollback** — Defines SLO/error-rate/latency triggers that abort and roll back deployments
- **Secret-free generation** — Scans all generated YAML with `scan-secrets.py` (trufflehog/detect-secrets-style heuristics); blocks generation if secrets are detected and emits environment-variable placeholders instead
- **External approval gate specification** — Generates CI-native human approval gates that the agent **cannot** bypass:
  - GitHub Actions: `environment: production` with `required_reviewers` protection rules
  - GitLab CI: `rules` + `when: manual` stages requiring human trigger
  - Jenkins: `input` step with human choice parameter
- **Dry-run enforcement** — All CI-triggered agent runs default to `--dry-run` flag; pipelines separate **plan** and **apply** stages; human must explicitly approve the apply stage
- **Backward-compatibility gates** — Links to API Contract Tester before any production promotion

## Workflow

1. **Detect project type and CI platform**
   - Inspect repository root for `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, or ask user
   - Infer project type from `package.json`, `pom.xml`, `go.mod`, `requirements.txt`, `Cargo.toml`, `Dockerfile`
   - Determine primary language/runtime for stage template selection

2. **Generate or update pipeline config with skill-trigger hooks**
   - Map each Kimi skill to its CI hook point:
     - `PR opened` → Blast Radius Calculator + Code Tester
     - `Build failed` → Log Analyzer
     - `Dependency scan scheduled` → Dependency Manager
     - `Pre-merge gate` → Security Auditor
     - `Performance gate` → Performance Validator
     - `Pre-production gate` → API Contract Tester
   - Emit pipeline file(s) with comment blocks marking hook injection points

3. **Inject secret-free placeholders and scan**
   - Replace any detected high-entropy strings or credential-like values with platform-native secret references:
     - GitHub Actions: `${{ secrets.SECRET_NAME }}`
     - GitLab CI: `"${SECRET_NAME}"` (with `masked: true` / `protected: true` in UI)
     - Jenkins: `withCredentials([string(credentialsId: 'secret-name', variable: 'SECRET_NAME')])`
   - Run `scripts/scan-secrets.py` on every generated file; if findings > 0, abort generation and surface the file, line, and match type to the user
   - Never emit a file that contains plaintext credentials

4. **Define promotion stages with plan / apply separation**
   - Standard stage order:
     1. Build
     2. Test (unit + integration; Code Tester skill hook)
     3. Security scan (Security Auditor skill hook)
     4. Blast Radius analysis (Blast Radius Calculator skill hook)
     5. Performance regression gate (Performance Validator skill hook)
     6. API contract check (API Contract Tester skill hook)
     7. **Plan** stage — dry-run plan output (e.g., `terraform plan`, `helm diff`, `--dry-run`)
     8. Staging deploy (dry-run gate → execute gate)
     9. Canary deploy (traffic split + metric-based promotion)
     10. **Production plan** stage — human-visible plan artifact
     11. **Production apply** stage — external human approval gate + dry-run gate
   - Each stage produces artifacts consumed by the next stage
   - All Kimi agent invocations triggered from CI default to `--dry-run` flag

5. **Configure external human approval gates (CI-native, agent-unbypassable)**
   - GitHub Actions:
     - Use `environment: production` with repository **Environment protection rules**
     - Configure `required_reviewers: [1]` (or more) in repository Settings → Environments
     - The agent cannot dismiss or bypass these reviewers; they are enforced by GitHub platform mechanics
   - GitLab CI:
     - Use `when: manual` and `rules:if` in production jobs
     - Require `protected` branch + `protected_environment` settings
     - The agent cannot trigger a manual job without a human clicking "Play"
   - Jenkins:
     - Use `input` step with `choice` or `boolean` parameter
     - Wrap the input in a `timeout` to prevent indefinite blocking
     - The agent cannot programmatically submit the input unless explicitly granted `Job/Build` permission (which must NOT be granted to the agent user)

6. **Configure dry-run gates between each stage**
   - Insert a `dry-run` / `plan` job before every destructive or promotion job
   - Dry-run outputs a simulated plan; execute only proceeds after explicit confirmation or `DRY_RUN=false` env var
   - GitHub Actions: use `workflow_dispatch` input `dry_run` default `true`
   - GitLab CI: use `rules:if: $DRY_RUN == "true"` to route to dry-run jobs
   - Jenkins: use `input` step with `dryRun` parameter

7. **Set up automated rollback triggers**
   - Define rollback conditions: error rate > threshold, p99 latency > SLO, HTTP 5xx rate spike, custom metric breach
   - Rollback mechanism:
     - Kubernetes: `kubectl rollout undo` or Argo Rollouts automated promotion abort
     - ECS: circuit breaker + prior stable task definition
     - VM/static: blue/green swap or prior artifact redeploy
   - Generate rollback job/stage in pipeline config
   - Produce a `ROLLBACK.md` documenting manual rollback steps as fallback

8. **Generate feature flag coordination for canary stages**
   - Detect feature flag provider (LaunchDarkly SDK key env var, Unleash URL, or config file)
   - Generate stage that progressively enables flags for canary traffic slice (e.g., 5% → 25% → 50%)
   - Tie flag ramp to metric thresholds; auto-disable flag and abort rollout on regression
   - Default: config-based flag in repo (`feature-flags.yml`) if no provider detected

9. **Link to Infrastructure-as-Code for environment provisioning**
   - If IaC configs exist (`terraform/`, `cdktf/`, `pulumi/`, CloudFormation templates), add a `provision` stage before deploy
   - Pass environment name and artifact tag as outputs to IaC stage
   - Ensure IaC apply also respects dry-run gate (`terraform plan` before `terraform apply`)

10. **Validate pipeline config syntax**
    - GitHub Actions: run `actionlint` (if available) or validate YAML structure against workflow schema
    - GitLab CI: run `gitlab-ci-lint` API or validate YAML structure
    - Jenkins: validate `Jenkinsfile` declarative syntax using `jenkins-cli` or Groovy lint
    - Surface syntax errors with file path and line number

11. **Run secret scan as final gate**
    - Execute `python scripts/scan-secrets.py --directory <output-dir> --strict`
    - If any secrets are found, abort the workflow, list findings, and require user remediation
    - Only proceed to deliverables when scan exits `0`

12. **Output deliverables**
    - CI config file(s) written to appropriate repository paths
    - `PIPELINE_STAGES.md` documenting each stage, inputs, outputs, skill hooks, and approval gates
    - `ROLLBACK.md` documenting rollback triggers, procedures, and manual fallback steps
    - `FEATURE_FLAGS.md` documenting flag ramp plan and kill switch

## Safety highlights

- **ALWAYS** run in dry-run/simulation mode first (Phase 1 dry-run, Phase 2 execute). This is Gateway-enforced for all agent-triggered CI runs.
- **ALWAYS** generate a rollback plan with explicit triggers and manual fallback steps before any deployment stage.
- **ALWAYS** run the API Contract Tester backward-compatibility check before promoting to production.
- **ALWAYS** require human confirmation (interactive `input`, PR approval, or Slack/email checkpoint) before any production deploy.
- **ALWAYS** route security scan results (Security Auditor) to a human-accessible artifact before merge; never auto-dismiss failures.
- **ALWAYS** mask secrets in CI logs using platform-native secret masking (`::add-mask::` in GitHub Actions, `masked` in GitLab CI, `withCredentials` in Jenkins).
- **NEVER** auto-merge pull requests or bypass required reviews. Segregation of duties requires human approval.
- **NEVER** deploy to production without explicit human confirmation, even if all automated gates pass.
- **NEVER** expose secrets (tokens, keys, passwords) in pipeline logs, config files, or environment variable dumps.
- **NEVER** skip backward-compatibility checks when API changes are present in the diff.
- **NEVER** allow a canary rollout to proceed past the next traffic increment if any SLO breach or error-rate spike is detected in the current slice.
- **NEVER** store long-lived credentials inside pipeline configs; use platform-native secret stores (GitHub Secrets, GitLab Variables, Jenkins Credentials).

### v4.0 Safety Rules (Added)

- **NEVER** embed plaintext secrets in generated pipeline YAML.
- **ALWAYS** generate environment variable placeholders for secrets (e.g., `${{ secrets.API_KEY }}`, `"${API_KEY}"`, `withCredentials(...)`).
- **NEVER** generate a pipeline that auto-deploys to production without an external human approval gate that the agent cannot bypass.
- **ALWAYS** include `--dry-run` flag in CI-triggered agent invocations (e.g., `kimi-agent --dry-run deploy ...`).
- **ALWAYS** separate "plan" and "apply" stages in generated pipelines; the "apply" stage must require external human approval.
- **ALWAYS** run `scan-secrets.py` on generated output before returning it to the user; block generation on any findings.

## Integration with other skills

| Skill | Integration Point | Direction |
|---|---|---|
| **Spec Decomposer** | Reads decomposed task specs to generate pipeline stage lists and artifact outputs | Input |
| **Code Tester** | Triggered on PR open and build events; test results feed the promotion gate | Trigger + Input |
| **Blast Radius Calculator** | Triggered on PR open to assess impact before merge approval | Trigger |
| **Log Analyzer** | Triggered automatically when a build or deploy stage fails | Trigger |
| **Dependency Manager** | Triggered on scheduled scans (cron) and PR dependency changes | Trigger |
| **Security Auditor** | Runs as pre-merge gate; blocks merge on critical findings | Gate |
| **Performance Validator** | Runs as performance regression gate before staging promotion | Gate |
| **API Contract Tester** | Runs backward-compatibility check before production promotion | Gate |
| **Infrastructure-as-Code** | Provision stage linked to Terraform/Pulumi/CloudFormation before deploy | Linked Stage |

## References

- `references/pipeline-templates.md` — Stage templates for GitHub Actions, GitLab CI, and Jenkins with embedded skill hook placeholders
- `references/rollback-patterns.md` — Rollback patterns by deployment target (Kubernetes, ECS, VM, serverless)
- `references/feature-flag-patterns.md` — Feature flag ramp strategies and kill-switch implementations per provider
- `references/dry-run-gates.md` — Platform-specific dry-run gate implementations, plan/apply separation, and env var conventions
- `references/approval-gates.md` — Platform-specific external human approval gate specifications that the agent cannot bypass

## Scripts

- `scripts/generate-pipeline.py` — Template engine that generates CI config files and stage documentation from project metadata, platform selection, and enabled skill hook list. Integrates secret scanning and enforces plan/apply separation.
- `scripts/scan-secrets.py` — Secret scanner (trufflehog/detect-secrets-style) for generated YAML. Blocks generation if secrets are detected and can auto-remediate with placeholders.
