---
name: dev-ci-cd-pipeline
description: Developer-facing CI/CD pipeline generator and optimizer for GitHub Actions, GitLab CI, Azure DevOps, Jenkins, CircleCI. Use when setting up CI/CD, optimizing build times, adding security scanning stages, migrating platforms, or troubleshooting pipeline failures. Includes caching, parallelism, matrix builds, and deployment strategies.
---

# dev-ci-cd-pipeline

## Overview

This skill generates, optimizes, and maintains CI/CD pipeline configurations across GitHub Actions, GitLab CI, Azure DevOps, Jenkins, CircleCI, and Travis CI. It analyzes project structure to create idiomatic pipeline configs, applies caching and parallelization strategies, integrates security scanning stages, and provides deployment strategy templates.

Use this skill when:
- Setting up CI/CD for a new project from scratch
- Optimizing slow pipelines (excessive build times, test times, or artifact bloat)
- Adding new stages (security scan, performance test, deployment)
- Migrating from one CI platform to another
- Troubleshooting pipeline failures or intermittent build issues
- Creating reusable workflow templates for an organization

## Workflow Decision Tree

**What is the user's goal?**

| Goal | Entry Point |
|------|------------|
| New project needs CI/CD | Start at [Project Analysis](#step-1-project-analysis) |
| Existing pipeline is slow | Start at [Optimization Audit](#step-1-optimization-audit) |
| Add security scanning | Start at [Security Integration](#step-2-security-integration) |
| Migrate platforms | Start at [Platform Mapping](#step-1-platform-mapping) |
| Pipeline is failing | Start at [Troubleshooting](#step-1-troubleshooting) |
| Create reusable template | Start at [Template Design](#step-1-template-design) |

---

## Step 1: Project Analysis

When setting up CI/CD for a new project, analyze the repository structure to determine the correct pipeline type.

### Detect Project Type

| File/Pattern | Project Type | Default Platform Recommendations |
|-------------|--------------|--------------------------------|
| `package.json` | Node.js / JavaScript | GitHub Actions, CircleCI |
| `requirements.txt`, `pyproject.toml`, `setup.py` | Python | GitHub Actions, GitLab CI |
| `pom.xml`, `build.gradle` | Java (Maven/Gradle) | GitLab CI, Jenkins |
| `Cargo.toml` | Rust | GitHub Actions |
| `go.mod` | Go | GitHub Actions, GitLab CI |
| `Dockerfile` or `docker-compose.yml` | Containerized | All platforms |
| `*.csproj`, `*.sln` | .NET | Azure DevOps, GitHub Actions |
| `Gemfile` | Ruby | GitHub Actions, CircleCI |
| `pubspec.yaml` | Flutter/Dart | GitHub Actions |
| `ios/`, `android/`, `lib/` (Flutter layout) | Mobile | GitHub Actions |
| `terraform/`, `*.tf` | Infrastructure | GitHub Actions, GitLab CI |
| `helm/`, `k8s/` | Kubernetes | GitHub Actions, GitLab CI, Azure DevOps |

### Determine Pipeline Requirements

Ask or detect:
1. **Test framework**: Jest, pytest, JUnit, Go test, etc.
2. **Build artifacts**: Docker images, compiled binaries, npm packages, wheel files
3. **Deployment targets**: Kubernetes, AWS, Azure, GCP, Vercel, Netlify, bare metal
4. **Branching model**: trunk-based, GitFlow, GitHub Flow (affects when deployments trigger)
5. **Required checks**: How many PR approvals, required status checks
6. **Monorepo**: Multiple packages/apps in one repository (affects change detection and caching)

### Generate Base Configuration

Use `scripts/generate_pipeline.py` or manually construct the pipeline based on detected project type. Key principles:

- **Fail fast**: Lint and type-check before running full test suite
- **Parallelize**: Split test suites by directory or timing data
- **Cache aggressively**: Dependencies, build artifacts, and tool installations
- **Secure by default**: No secrets in logs, use platform secret management
- **Artifact discipline**: Only persist what's needed for downstream jobs or debugging

---

## Step 2: Security Integration

Add security scanning stages after the initial working pipeline is established.

### Recommended Security Stage Order

1. **Secret Detection** (gitleaks, truffleHog, GitHub secret scanning)
   - Runs on every push and PR
   - Fails pipeline if secrets detected

2. **Dependency Scanning** (Snyk, OWASP Dependency-Check, npm audit, pip-audit)
   - Runs on every PR and nightly
   - Blocks merge on critical vulnerabilities

3. **SAST** (SonarQube, Semgrep, CodeQL, bandit, eslint-security)
   - Runs on PR and main branch builds
   - Generates SARIF output for dashboard ingestion

4. **Container Scanning** (Trivy, Clair, Anchore)
   - Runs after Docker image build
   - Scan both OS packages and application dependencies

5. **DAST** (OWASP ZAP)
   - Runs against staging environment post-deployment
   - Scheduled nightly, not on every PR

### Security Gate Configuration

```yaml
# GitHub Actions example pattern
security-gate:
  needs: [build, test]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Run Trivy vulnerability scanner
      uses: aquasecurity/trivy-action@master
      with:
        image-ref: "my-app:${{ github.sha }}"
        format: "sarif"
        output: "trivy-results.sarif"
    - name: Upload to GitHub Security tab
      uses: github/codeql-action/upload-sarif@v2
      with:
        sarif_file: "trivy-results.sarif"
```

---

## Step 3: Build Optimization

Apply caching and parallelization strategies. See `references/optimization_patterns.md` for deep-dive patterns.

### Quick Optimization Checklist

- [ ] Dependency cache enabled (npm, pip, m2, cargo, go modules)
- [ ] Build layer cache enabled (Docker BuildKit, Kaniko)
- [ ] Tests parallelized across workers (sharding, timing-based split)
- [ ] Artifact size minimized (only production artifacts, no devDependencies in Docker)
- [ ] Unused stages removed (no redundant installs or builds)
- [ ] Self-hosted runners considered for heavy builds (if cloud minutes are expensive)
- [ ] Matrix builds use `fail-fast: false` when versions are independent

### Language-Specific Cache Keys

| Language | Cache Path | Key Pattern |
|----------|-----------|-------------|
| Node.js | `~/.npm`, `node_modules` | `npm-${{ hashFiles('package-lock.json') }}` |
| Python | `~/.cache/pip` | `pip-${{ hashFiles('requirements.txt') }}` |
| Java (Maven) | `~/.m2/repository` | `m2-${{ hashFiles('pom.xml') }}` |
| Java (Gradle) | `~/.gradle/caches` | `gradle-${{ hashFiles('**.gradle*', '**/gradle-wrapper.properties') }}` |
| Rust | `~/.cargo/registry`, `target` | `cargo-${{ hashFiles('Cargo.lock') }}` |
| Go | `~/go/pkg/mod` | `go-${{ hashFiles('go.sum') }}` |
| .NET | `~/.nuget/packages` | `nuget-${{ hashFiles('**/*.csproj') }}` |

---

## Step 4: Deployment Strategies

Configure deployment based on risk tolerance and infrastructure.

### Strategy Selection

| Strategy | When to Use | Complexity | Rollback Speed |
|----------|------------|------------|---------------|
| **Rolling** | Standard web apps, stateless services | Low | Slow (re-deploy previous version) |
| **Blue-Green** | Zero-downtime required, easy to swap traffic | Medium | Fast (flip traffic back) |
| **Canary** | High-traffic services, gradual risk exposure | High | Fast (shift traffic back) |
| **Recreate** | Dev/staging environments where brief downtime is OK | Low | Slow |

### Kubernetes Deployment Patterns

**Rolling Deployment** (default):
```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
```

**Blue-Green with Service selector swap:**
```bash
# After green deployment is healthy:
kubectl patch service my-app -p '{"spec":{"selector":{"version":"green"}}}'
```

**Canary with Flagger or Argo Rollouts:**
- Use Flagger (GitLab/Azure) or Argo Rollouts (GitHub/Flux) for automated canary analysis
- Integrate Prometheus metrics or smoke tests for go/no-go decisions

---

## Step 5: Platform Mapping (Migration)

When migrating between platforms, map concepts 1:1 then optimize for the target platform's strengths.

### Concept Mapping

| Concept | GitHub Actions | GitLab CI | Azure DevOps | Jenkins | CircleCI |
|---------|---------------|-----------|--------------|---------|----------|
| Workflow file | `.github/workflows/*.yml` | `.gitlab-ci.yml` | `azure-pipelines.yml` | `Jenkinsfile` | `.circleci/config.yml` |
| Job / Unit of work | `jobs.<job_id>` | `stages` + `jobs` | `jobs` | `stage()` in `node{}` | `jobs` |
| Step / Command | `steps` | `script` | `steps` | `steps` inside `stage` | `steps` |
| Runner | `runs-on` | `tags` or `image` | `pool` | agent label | `resource_class` + executor |
| Secrets | `secrets` context | CI/CD Variables | Library/Variable Groups | Credentials | Contexts + Project Settings |
| Artifacts | `actions/upload-artifact` | `artifacts` keyword | `PublishBuildArtifacts` | `archiveArtifacts` | `store_artifacts` |
| Caching | `actions/cache` | `cache` keyword | `Cache@2` task | Pipeline shared libs | `restore_cache` / `save_cache` |
| Reusable logic | `workflow_call` / composite actions | `include` templates | Template pipelines | Shared libraries | Orbs |

### Migration Order

1. Translate the structure 1:1 (same jobs, same steps)
2. Swap platform-specific syntax (secrets access, artifact upload)
3. Optimize for target platform (use native caching, native parallelism features)
4. Validate with a test branch before switching production default branch protection

---

## Step 6: Troubleshooting

When a pipeline fails, follow this diagnostic flow:

### 1. Categorize the Failure

| Failure Pattern | Likely Cause | Quick Fix |
|----------------|------------|-----------|
| Fails on one OS only | OS-specific path or behavior | Check `runner.os` conditionals, shell differences |
| Fails intermittently | Race condition, flaky test, network timeout | Add retries, increase timeouts, isolate tests |
| Fails after dependency update | Breaking change in dependency | Pin versions, lockfile drift, review changelog |
| Fails at download/install step | Cache miss, network issue, expired token | Verify cache keys, check secret expiry, retry |
| Fails at deploy step | Auth, misconfigured environment | Check service connections, kubeconfig, IAM roles |
| Succeeds locally, fails in CI | Environment difference | Use containers, check installed versions, locale |

### 2. Diagnostic Commands per Platform

**GitHub Actions**: Enable debug logging by setting secrets `ACTIONS_STEP_DEBUG` and `ACTIONS_RUNNER_DEBUG` to `true`.

**GitLab CI**: Add `CI_DEBUG_SERVICES: true` and use `after_script` to capture logs.

**Azure DevOps**: Set `system.debug=true` variable for verbose logs.

**Jenkins**: Use `set -x` in shell steps, or Blue Ocean visualization for pipeline stages.

**CircleCI**: Re-run job with SSH in UI, then SSH into container to debug interactively.

### 3. Common Fixes

- **Timeouts**: Increase job-level timeouts or add step-level retry logic
- **Disk space**: Clean up between steps, use shallow clones (`fetch-depth: 1`)
- **Memory**: Split large test suites, use larger runners, add swap
- **Permissions**: Ensure GITHUB_TOKEN / CI_JOB_TOKEN has required scopes

---

## Step 7: Notification Setup

Add notifications for pipeline events to keep teams informed without noise.

### Notification Matrix

| Event | Slack | Discord | Email | PagerDuty |
|-------|-------|---------|-------|-----------|
| Pipeline failed on main/release | Alert | Alert | Team lead | Page if critical |
| Pipeline failed on PR | Silent/Thread | Silent | Silent | Silent |
| Deployment completed | Success message | Success message | Optional | Resolve if recovered |
| Security scan critical finding | Alert | Alert | Security team | Page if exploitable |
| Nightly build failed | Morning digest | Morning digest | Daily digest | Only if repeated |

### Slack Webhook Pattern (GitHub Actions)

```yaml
- name: Notify Slack
  if: always()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    fields: repo,message,commit,author,action,eventName,ref,workflow
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

---

## Workflow Templates

### PR Validation

Triggers: `pull_request` (opened, synchronize, reopened)
Stages: Lint → Type Check → Unit Tests → Integration Tests → Build Artifact
Requirements: All checks must pass before merge

### Release Automation

Triggers: `push` to `main` or tag `v*`
Stages: Version Bump → Full Test Suite → Build → Security Scan → Deploy to Staging → Smoke Test → Deploy to Production
Requirements: Require manual approval for production deploy, auto-deploy to staging

### Nightly Builds

Triggers: `schedule` (cron: `0 2 * * *`)
Stages: Dependency Update Check → Full Matrix Build → Long-running Tests → Report Generation
Requirements: Notify on failure only, publish reports as artifacts

---

## Resources

### scripts/
- `generate_pipeline.py` — Analyzes project structure and generates a platform-specific CI/CD configuration file

### references/
- `platform_specs.md` — YAML syntax, environment variables, secrets handling, and native features per CI platform
- `optimization_patterns.md` — Caching strategies, parallelization techniques, artifact management, and build time reduction patterns
