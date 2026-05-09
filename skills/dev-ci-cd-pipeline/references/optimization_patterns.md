# Optimization Patterns

Deep-dive reference for reducing CI/CD pipeline duration, cost, and flakiness. Covers caching strategies, parallelization techniques, artifact management, Docker optimization, and test acceleration.

---

## Caching Strategies

### 1. Dependency Caching

The most impactful optimization for most pipelines. Cache package manager directories and lockfiles.

#### Node.js / npm / yarn / pnpm

```yaml
# GitHub Actions
- uses: actions/cache@v4
  with:
    path: |
      ~/.npm
      node_modules
      .eslintcache
    key: ${{ runner.os }}-node-${{ hashFiles('**/package-lock.json') }}
    restore-keys: |
      ${{ runner.os }}-node-

# Prefer setup-node built-in cache when possible:
- uses: actions/setup-node@v4
  with:
    node-version: '20'
    cache: 'npm'  # handles npm, yarn, pnpm automatically
```

```yaml
# GitLab CI
cache:
  key:
    files:
      - package-lock.json
  paths:
    - node_modules/
    - .eslintcache/
  policy: pull-push
```

```yaml
# CircleCI
- restore_cache:
    keys:
      - v1-npm-deps-{{ checksum "package-lock.json" }}
      - v1-npm-deps-
- save_cache:
    key: v1-npm-deps-{{ checksum "package-lock.json" }}
    paths:
      - ~/.npm
      - node_modules
```

#### Python (pip / poetry / uv)

```yaml
# GitHub Actions
- uses: actions/cache@v4
  with:
    path: |
      ~/.cache/pip
      ~/.local/share/virtualenvs  # pipenv
      .venv                       # poetry/uv
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt', '**/pyproject.toml') }}
    restore-keys: |
      ${{ runner.os }}-pip-
```

```yaml
# GitLab CI with uv (fastest Python installer)
cache:
  key:
    files:
      - pyproject.toml
      - uv.lock
  paths:
    - .venv/
```

#### Java / Maven / Gradle

```yaml
# GitHub Actions
- uses: actions/cache@v4
  with:
    path: |
      ~/.m2/repository
      ~/.gradle/caches
      ~/.gradle/wrapper
    key: ${{ runner.os }}-java-${{ hashFiles('**/pom.xml', '**/*.gradle*', '**/gradle-wrapper.properties') }}
    restore-keys: |
      ${{ runner.os }}-java-
```

#### Rust (Cargo)

```yaml
# GitHub Actions
- uses: actions/cache@v4
  with:
    path: |
      ~/.cargo/registry/index
      ~/.cargo/registry/cache
      ~/.cargo/git/db
      target/
    key: ${{ runner.os }}-cargo-${{ hashFiles('**/Cargo.lock') }}
    restore-keys: |
      ${{ runner.os }}-cargo-
```

**Critical**: Include `target/` only if building incrementally. For release builds from scratch, cache registry only to avoid oversized caches.

#### Go

```yaml
# GitHub Actions
- uses: actions/cache@v4
  with:
    path: |
      ~/go/pkg/mod
      ~/.cache/go-build
    key: ${{ runner.os }}-go-${{ hashFiles('**/go.sum') }}
    restore-keys: |
      ${{ runner.os }}-go-
```

### 2. Build Artifact Caching

Cache compilation outputs to speed up incremental builds.

**TypeScript / Webpack / Vite:**
```yaml
- uses: actions/cache@v4
  with:
    path: |
      .turbo
      .next/cache
      dist/
    key: ${{ runner.os }}-build-${{ github.sha }}
    restore-keys: |
      ${{ runner.os }}-build-
```

**Android (Gradle):**
```yaml
path: |
  ~/.gradle/caches
  ~/.gradle/wrapper
  ~/.android/build-cache
```

### 3. Tool Caching

Cache installed CLI tools to avoid repeated downloads.

```yaml
# GitHub Actions - cache pre-commit hooks
- uses: actions/cache@v4
  with:
    path: ~/.cache/pre-commit
    key: pre-commit-${{ hashFiles('.pre-commit-config.yaml') }}

# Cache installed linters
- uses: actions/cache@v4
  with:
    path: |
      ~/.local/bin
      /usr/local/bin/golangci-lint
    key: tools-${{ hashFiles('Makefile', 'scripts/install-tools.sh') }}
```

### 4. Docker Layer Caching

**GitHub Actions with BuildKit:**
```yaml
- uses: docker/build-push-action@v5
  with:
    context: .
    push: false
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

**GitLab CI with Kaniko:**
```yaml
build:
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - /kaniko/executor
      --context "$CI_PROJECT_DIR"
      --dockerfile "$CI_PROJECT_DIR/Dockerfile"
      --destination "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
      --cache=true
      --cache-dir /cache
```

**CircleCI:**
```yaml
- setup_remote_docker:
    docker_layer_caching: true
```

**Cache Invalidation Strategy:**
- Use lockfile hash for dependency layers
- Use `CACHE_BUST` variable for force rebuilds
- Separate `COPY package*.json` before `COPY .` to maximize layer reuse

---

## Parallelization Techniques

### 1. Job-Level Parallelism

Split independent work into separate jobs that run concurrently.

```yaml
# GitHub Actions
jobs:
  lint:
    runs-on: ubuntu-latest
    steps: [...]
  unit-tests:
    runs-on: ubuntu-latest
    steps: [...]
  integration-tests:
    runs-on: ubuntu-latest
    steps: [...]
  e2e-tests:
    runs-on: ubuntu-latest
    steps: [...]
```

**Best practice**: Fan-out for parallel execution, then fan-in for deployment gates.

```yaml
jobs:
  [lint, unit-tests, integration-tests, build]  # parallel
  deploy-staging:
    needs: [lint, unit-tests, integration-tests, build]
```

### 2. Test Sharding / Splitting

Divide test suites across multiple workers using timing data.

**GitHub Actions + Jest:**
```yaml
test:
  runs-on: ubuntu-latest
  strategy:
    fail-fast: false
    matrix:
      shard: [1, 2, 3, 4]
  steps:
    - run: npx jest --shard=${{ matrix.shard }}/4
```

**CircleCI with timing-based split:**
```yaml
test:
  parallelism: 4
  steps:
    - run:
        command: |
          TEST_FILES=$(circleci tests glob "**/*.spec.ts" | circleci tests split --split-by=timings)
          npx jest $TEST_FILES
```

**GitLab CI with `parallel:matrix`:**
```yaml
test:
  parallel:
    matrix:
      - CI_NODE_TOTAL: [4]
        CI_NODE_INDEX: [0, 1, 2, 3]
  script:
    - npx jest --shard=$CI_NODE_INDEX/$CI_NODE_TOTAL
```

### 3. Matrix Builds

Test across multiple versions, OSes, or architectures simultaneously.

```yaml
# GitHub Actions
strategy:
  fail-fast: false
  matrix:
    os: [ubuntu-22.04, windows-latest, macos-latest]
    node: [18, 20, 22]
    include:
      - os: ubuntu-22.04
        node: 20
        experimental: true
    exclude:
      - os: macos-latest
        node: 18
```

**Optimization tips:**
- Use `fail-fast: false` to get full test results
- Exclude combinations that don't need coverage
- Set `max-parallel: 5` if hitting concurrency limits

### 4. Pipeline Stage Overlap (GitLab CI DAG)

Use `needs` to start jobs as soon as dependencies finish, not at stage boundaries.

```yaml
build-backend:
  stage: build
  script: ./build-backend.sh

build-frontend:
  stage: build
  script: ./build-frontend.sh

test-backend:
  stage: test
  needs: [build-backend]  # starts immediately after backend build

test-frontend:
  stage: test
  needs: [build-frontend]

deploy:
  stage: deploy
  needs: [test-backend, test-frontend]
```

---

## Artifact Management

### 1. Artifact Minimization

Only persist what downstream jobs or debugging require.

| Do Cache/Persist | Do NOT Cache/Persist |
|-------------------|----------------------|
| Compiled production assets | `node_modules` in Docker images (use multi-stage builds) |
| Test result XMLs | Local dev database files |
| Coverage reports | Temporary build logs |
| Docker image tarballs | OS package caches (outside container) |
| Documentation builds | Raw unprocessed source maps (if not needed) |

**GitHub Actions artifact upload:**
```yaml
- uses: actions/upload-artifact@v4
  with:
    name: coverage-${{ matrix.os }}-${{ matrix.node }}
    path: |
      coverage/
      reports/
    if-no-files-found: warn
    retention-days: 7  # short retention for PR artifacts
```

### 2. Artifact Consolidation

Merge artifacts from parallel jobs before final reporting.

```yaml
# Fan-in job to collect all coverage
report:
  needs: [test-ubuntu, test-windows, test-macos]
  runs-on: ubuntu-latest
  steps:
    - uses: actions/download-artifact@v4
      with:
        pattern: coverage-*
        merge-multiple: true
    - run: npx nyc merge coverage/ merged-coverage.json
    - uses: codecov/codecov-action@v4
```

### 3. Docker Image Optimization

**Multi-stage builds** reduce final image size and attack surface:

```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev
COPY . .
RUN npm run build

# Production stage
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
EXPOSE 3000
CMD ["node", "dist/main.js"]
```

**Key rules:**
- Use specific tags, never `latest`
- Combine RUN commands to reduce layers
- Use `.dockerignore` to prevent sending unnecessary files to daemon
- Use BuildKit for advanced features (`DOCKER_BUILDKIT=1`)

### 4. Workspace and Stash Patterns

**GitLab CI artifacts vs cache:**
- **Artifacts**: Pass data between jobs, downloadable, expire
- **Cache**: Persist data between pipeline runs, speeds up repeat work

```yaml
# Cache dependencies (reused across pipelines)
cache:
  paths:
    - node_modules/

# Artifact build output (passed to next job)
build:
  artifacts:
    paths:
      - dist/
    expire_in: 1 hour
```

**Jenkins stash/unstash:**
```groovy
stage('Build') {
    steps {
        sh 'npm run build'
        stash includes: 'dist/**/*', name: 'built-app'
    }
}
stage('Test') {
    steps {
        unstash 'built-app'
        sh 'npm test'
    }
}
```

---

## Build Time Reduction Patterns

### 1. Fail Fast

Order steps so cheap checks run before expensive ones.

```yaml
jobs:
  validate:
    steps:
      - run: npm run lint       # seconds
      - run: npm run type-check # seconds
      - run: npm run test:unit  # minutes
      - run: npm run build      # minutes
      - run: npm run test:e2e   # minutes
```

### 2. Shallow Clones

Avoid full git history unless needed for versioning or changelog.

```yaml
# GitHub Actions
- uses: actions/checkout@v4
  with:
    fetch-depth: 1

# GitLab CI
variables:
  GIT_DEPTH: 10
  GIT_SHALLOW_CLONE: "true"
```

Exception: SonarQube, semantic-release, or changelog generation need `fetch-depth: 0`.

### 3. Conditional Job Execution

Skip unnecessary work based on changed files.

**GitHub Actions with `paths`:**
```yaml
on:
  push:
    paths:
      - 'src/**'
      - 'package*.json'
      - '.github/workflows/**'
```

**GitHub Actions with `changed-files`:**
```yaml
- uses: tj-actions/changed-files@v44
  id: changed
- name: Run backend tests
  if: contains(steps.changed.outputs.all_changed_files, 'backend/')
  run: cd backend && npm test
```

**GitLab CI with `rules:changes`:**
```yaml
backend-test:
  rules:
    - changes:
        - backend/**/*
        - .gitlab-ci.yml
```

### 4. Self-Hosted Runners for Heavy Workloads

When cloud-hosted minutes are expensive or build times are prohibitive:

| Platform | Self-Hosted Option | Setup Complexity |
|----------|-------------------|------------------|
| GitHub Actions | `runs-on: self-hosted` or runner groups | Medium |
| GitLab CI | GitLab Runner on VM/K8s | Medium |
| Azure DevOps | Self-hosted agent pools | Low |
| Jenkins | Always self-hosted | Medium |
| CircleCI | Self-hosted runners | Low |

Trade-offs: You manage updates, security patches, and scaling. Best for:
- GPU builds (ML training)
- Large monorepos (full clone is slow)
- Proprietary hardware testing
- Network-restricted environments

### 5. Pre-built Development Containers

Use container images with dependencies pre-installed.

```yaml
# GitHub Actions
jobs:
  test:
    runs-on: ubuntu-latest
    container:
      image: myregistry/ci-runner:node20-java17
      credentials:
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
```

Update the image weekly via a scheduled pipeline to keep dependencies fresh.

### 6. Test Result Reporting

Always upload test results in a parseable format (JUnit XML). Enables:
- Timing-based test splitting
- Failure trend analysis
- PR annotations

```yaml
# Jest -> JUnit
- run: npx jest --reporters=default --reporters=jest-junit
  env:
    JEST_JUNIT_OUTPUT_DIR: reports

# Upload for platform parsing
- uses: actions/upload-artifact@v4
  with:
    name: test-results
    path: reports/*.xml
```

### 7. Pipeline as Code Validation

Validate CI configuration changes before committing.

| Platform | Validation Tool |
|----------|----------------|
| GitHub Actions | `actionlint` (Go binary) |
| GitLab CI | `gitlab-ci-linter` (API) or `glab ci lint` |
| Azure DevOps | REST API validation endpoint |
| Jenkins | `jenkins-cli` or replay in UI |
| CircleCI | `circleci config validate` CLI |

Add a pre-commit hook:
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/rhysd/actionlint
    rev: v1.6.27
    hooks:
      - id: actionlint
```

---

## Cost Optimization

### Runner Sizing

| Workload | Recommended Size | Notes |
|----------|-----------------|-------|
| Lint, type-check, small unit tests | Standard / Small | 2 CPU, 7 GB RAM |
| Medium builds, integration tests | Medium | 4 CPU, 15 GB RAM |
| Large compilation (Java/TypeScript) | Large | 8 CPU, 30 GB RAM |
| Android builds, heavy Docker | XLarge | 16 CPU |
| ML training, GPU workloads | GPU runners | Only when necessary |

### Time-of-Day Scheduling

Run heavy workloads during off-peak if using self-hosted runners:

```yaml
# GitHub Actions cron
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM UTC

# GitLab CI schedule
# Configured in UI: CI/CD > Schedules
```

### Artifact Retention

Set short retention for PR builds, long retention for releases:

```yaml
# GitHub Actions
- uses: actions/upload-artifact@v4
  with:
    retention-days: ${{ github.ref == 'refs/heads/main' && 30 || 5 }}
```

---

## Flakiness Reduction

### 1. Retry Configuration

```yaml
# GitHub Actions (wrapped step)
- uses: nick-fields/retry@v3
  with:
    timeout_minutes: 10
    max_attempts: 3
    command: npm run test:e2e

# GitLab CI
retry:
  max: 2
  when:
    - runner_system_failure
    - stuck_or_timeout_failure
```

### 2. Deterministic Ordering

Sort tests or file lists to prevent order-dependent failures:
```bash
circleci tests glob "**/*.test.js" | sort | circleci tests split
```

### 3. Service Health Checks

Wait for dependencies (databases, mock servers) before starting tests:

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_PASSWORD: test
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

### 4. Test Isolation

- Use unique database schemas per test worker
- Reset state between tests (not just between files)
- Avoid shared file system state in parallel workers
