# Platform Specifications

Reference guide for CI/CD platform YAML syntax, environment variables, secrets handling, runner configuration, and native features. Use this when authoring or translating pipeline configurations.

---

## GitHub Actions

### File Location
`.github/workflows/*.yml` (multiple workflow files supported)

### Core Syntax

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        default: 'staging'

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # full history for sonar
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: build-output
          path: dist/
```

### Environment Variables

| Context | Example | Scope |
|---------|---------|-------|
| `github` | `github.sha`, `github.ref`, `github.actor` | Workflow |
| `env` | `env.MY_VAR` | Job/Step (set at workflow, job, or step level) |
| `vars` | `vars.CLOUD_REGION` | Repository/organization variables |
| `secrets` | `secrets.GITHUB_TOKEN` | Repository/organization secrets |
| `runner` | `runner.os`, `runner.arch` | Execution environment |
| `job` | `job.status` | Current job |
| `steps` | `steps.step1.outputs` | Step outputs |
| `needs` | `needs.build.outputs` | Outputs from dependent jobs |

### Secrets Handling

- **Repository secrets**: Set in Settings > Secrets and variables > Actions
- **Organization secrets**: Shared across repos, can be limited to specific repositories
- **Environment secrets**: Tied to deployment environments, require approval rules
- **GITHUB_TOKEN**: Auto-generated per workflow run, permissions configurable in workflow

```yaml
permissions:
  contents: read
  packages: write
  security-events: write
```

### Reusable Workflows

```yaml
# Caller
jobs:
  call-workflow:
    uses: org/repo/.github/workflows/reusable.yml@main
    with:
      node-version: '20'
    secrets: inherit

# Called (reusable.yml)
on:
  workflow_call:
    inputs:
      node-version:
        required: true
        type: string
    secrets:
      API_KEY:
        required: true
```

### Matrix Strategy

```yaml
strategy:
  fail-fast: false
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
    node: [18, 20, 22]
    exclude:
      - os: windows-latest
        node: 18
```

### Native Features

| Feature | Implementation |
|---------|---------------|
| Caching | `actions/cache@v4` or built-in in setup-* actions |
| Artifacts | `actions/upload-artifact@v4`, `actions/download-artifact@v4` |
| Caching Docker layers | `docker/build-push-action` with `cache-from`/`cache-to` |
| Environments | `environment: production` with protection rules |
| Dependent jobs | `needs: [build, test]` |
| Conditional jobs | `if: github.ref == 'refs/heads/main'` |
| Composite actions | Reusable step sequences in `action.yml` |
| OIDC auth | `permissions: id-token: write` for cloud federation |

---

## GitLab CI

### File Location
`.gitlab-ci.yml` (single file, can include external templates)

### Core Syntax

```yaml
stages:
  - build
  - test
  - security
  - deploy

variables:
  NODE_VERSION: "20"
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: "/certs"

default:
  image: node:20-alpine
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/

build:
  stage: build
  script:
    - npm ci
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 1 hour

test:
  stage: test
  script:
    - npm test
  coverage: '/All files[^|]*\|[^|]*\s+([\d\.]+)/'
  parallel:
    matrix:
      - PROVIDER: [aws, gcp, azure]
        TEST_SUITE: [unit, integration]
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CI_COMMIT_SHA` | Commit revision |
| `CI_COMMIT_REF_NAME` | Branch or tag name |
| `CI_JOB_TOKEN` | Auth token for GitLab API, registry, and project access |
| `CI_PIPELINE_ID` | Pipeline instance ID |
| `CI_PROJECT_DIR` | Full path to checkout |
| `CI_REGISTRY` | Container registry address |
| `CI_REGISTRY_USER` / `CI_REGISTRY_PASSWORD` | Registry auth (user is `gitlab-ci-token`) |
| `CI_SERVER_URL` | GitLab instance URL |

### Secrets Handling (CI/CD Variables)

- **Project variables**: Settings > CI/CD > Variables, masked, protected, or environment-specific
- **Group variables**: Inherited by all projects in group
- **Instance variables**: Admin-level, global
- **File type variables**: Uploaded as files, available at path in `$VAR_NAME`
- **Masking**: Hidden in job logs if matches masking rules

```yaml
deploy:
  script:
    - echo "$SSH_PRIVATE_KEY" > key.pem
    - chmod 600 key.pem
  variables:
    SSH_PRIVATE_KEY: $SSH_KEY  # file type variable
```

### Includes and Templates

```yaml
include:
  - project: 'org/templates'
    file: '/ci/node-template.yml'
    ref: main
  - template: Jobs/Build.gitlab-ci.yml
  - local: '/templates/.security.yml'
```

### Native Features

| Feature | Implementation |
|---------|---------------|
| Caching | `cache:` keyword with `key`, `paths`, `policy` |
| Artifacts | `artifacts:` with `paths`, `reports`, `dependencies` |
| Docker layer caching | `CACHE_DIR` with BuildKit or Kaniko |
| Environments | `environment: name: production` with `url` |
| Dependent jobs | `needs: [build]` (DAG pipelines) |
| Parallel matrix | `parallel: matrix:` |
| Child pipelines | `trigger:` keyword with separate file |
| Pipeline schedules | CI/CD > Schedules in UI |
| Merge trains | Queue merge requests for sequential validation |
| Review apps | Dynamic environments for branches |
| Container registry | Built-in, auth via `CI_JOB_TOKEN` |

---

## Azure DevOps (Azure Pipelines)

### File Location
`azure-pipelines.yml` at repository root, or multiple pipelines in `.azure-pipelines/`

### Core Syntax

```yaml
trigger:
  branches:
    include:
      - main
      - release/*
  paths:
    exclude:
      - '*.md'

pr:
  branches:
    include:
      - main

variables:
  nodeVersion: '20'
  vmImage: 'ubuntu-latest'

stages:
- stage: Build
  jobs:
  - job: BuildJob
    pool:
      vmImage: $(vmImage)
    steps:
    - task: NodeTool@0
      inputs:
        versionSpec: $(nodeVersion)
      displayName: 'Install Node.js'
    - script: npm ci
      displayName: 'Install dependencies'
    - script: npm run build
      displayName: 'Build application'
    - task: PublishBuildArtifacts@1
      inputs:
        pathToPublish: '$(Build.SourcesDirectory)/dist'
        artifactName: 'drop'
```

### Environment Variables (Predefined)

| Variable | Description |
|----------|-------------|
| `Build.SourcesDirectory` | Local path to source |
| `Build.ArtifactStagingDirectory` | Staging area for artifacts |
| `Build.BuildId` | Unique build ID |
| `Build.SourceVersion` | Commit SHA |
| `Build.SourceBranchName` | Branch name |
| `Build.Repository.Name` | Repo name |
| `System.AccessToken` | OAuth token for Azure DevOps API access |

### Secrets Handling

- **Variable groups**: Shared across pipelines, can be linked to Azure Key Vault
- **Pipeline variables**: Set in UI, can be secret (hidden in logs)
- **Library**: Centralized secure file and variable storage
- **Service connections**: Pre-configured auth for Azure, AWS, Docker Hub, Kubernetes, etc.

```yaml
variables:
- group: my-variable-group
- name: mySecret
  value: $(secretFromKeyVault)  # Key Vault linked variable group

steps:
- task: AzureKeyVault@2
  inputs:
    azureSubscription: 'MyServiceConnection'
    KeyVaultName: 'my-kv'
    SecretsFilter: '*'
```

### Templates

```yaml
# template.yml
parameters:
- name: nodeVersion
  type: string
  default: '20'

steps:
- task: NodeTool@0
  inputs:
    versionSpec: ${{ parameters.nodeVersion }}

# caller.yml
jobs:
- job: Build
  steps:
  - template: template.yml
    parameters:
      nodeVersion: '18'
```

### Native Features

| Feature | Implementation |
|---------|---------------|
| Caching | `Cache@2` task with key patterns |
| Artifacts | `PublishBuildArtifacts@1`, `DownloadBuildArtifacts@0` |
| Environments | Pipelines > Environments with checks and approvals |
| Deployment jobs | `deployment:` job type with `strategy` (runOnce, rolling, canary, blueGreen) |
| Multi-stage pipelines | `stages:` with sequential or parallel jobs |
| Conditions | `condition: succeeded()` or `condition: eq(variables['Build.SourceBranch'], 'refs/heads/main')` |
| Agent pools | Microsoft-hosted or self-hosted agents |
| Service connections | Pre-configured auth for external services |
| Variable groups | Linked to Key Vault for secret injection |
| Board integration | Work item linking and status updates |

---

## Jenkins

### File Location
`Jenkinsfile` at repository root (Pipeline script from SCM), or configured directly in job UI

### Core Syntax (Declarative Pipeline)

```groovy
pipeline {
    agent any
    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }
    environment {
        NODE_VERSION = '20'
        REGISTRY = credentials('docker-registry-credentials')
    }
    stages {
        stage('Build') {
            steps {
                script {
                    def nodeHome = tool name: 'NodeJS-20', type: 'jenkins.plugins.nodejs.tools.NodeJSInstallation'
                    env.PATH = "${nodeHome}/bin:${env.PATH}"
                }
                sh 'npm ci'
                sh 'npm run build'
            }
        }
        stage('Test') {
            parallel {
                stage('Unit Tests') {
                    steps {
                        sh 'npm run test:unit'
                    }
                }
                stage('Integration Tests') {
                    steps {
                        sh 'npm run test:integration'
                    }
                }
            }
        }
        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                sh './deploy.sh'
            }
        }
    }
    post {
        always {
            junit 'reports/**/*.xml'
            archiveArtifacts artifacts: 'dist/**/*', fingerprint: true
        }
        failure {
            slackSend(channel: '#alerts', message: "Build failed: ${env.BUILD_URL}")
        }
    }
}
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BUILD_NUMBER` | Current build number |
| `BUILD_URL` | URL to build page |
| `JOB_NAME` | Name of job |
| `WORKSPACE` | Absolute path to workspace |
| `GIT_COMMIT` | Commit SHA |
| `GIT_BRANCH` | Branch name |
| `NODE_NAME` | Name of agent executing build |
| `JENKINS_URL` | URL to Jenkins instance |

### Secrets Handling

- **Credentials plugin**: Store secrets in Jenkins credential store
- **Binding**: Inject secrets via `withCredentials` or `credentials()` env helper
- **Kinds**: Username/password, secret file, secret text, SSH username with private key, certificate

```groovy
steps {
    withCredentials([string(credentialsId: 'api-key', variable: 'API_KEY')]) {
        sh 'echo $API_KEY | base64'
    }
    withCredentials([usernamePassword(credentialsId: 'db-creds', usernameVariable: 'DB_USER', passwordVariable: 'DB_PASS')]) {
        sh 'mysql -u $DB_USER -p$DB_PASS'
    }
}
```

### Shared Libraries

```groovy
@Library('my-shared-library@main') _

pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                buildDockerImage(imageName: 'my-app', tag: env.GIT_COMMIT)
            }
        }
    }
}
```

### Native Features

| Feature | Implementation |
|---------|---------------|
| Caching | Custom, or `cache` in Pipeline (post-2.400), or external plugins |
| Artifacts | `archiveArtifacts`, `stash` / `unstash` for inter-stage transfer |
| Parallel execution | `parallel` block in `stage` |
| Multi-branch | Multibranch Pipeline plugin scans branches/PRs |
| Blue Ocean | Modern UI for pipeline visualization |
| Agent labels | `agent { label 'docker && linux' }` |
| Docker pipelines | `agent { docker { image 'node:20' } }` |
| Input/Approval | `input` step for manual gates |
| Timestamps | `timestamps` option or wrapper |
| ANSI color | `ansiColor('xterm')` wrapper |

---

## CircleCI

### File Location
`.circleci/config.yml`

### Core Syntax

```yaml
version: 2.1

orbs:
  node: circleci/node@5
  docker: circleci/docker@2

executors:
  default:
    docker:
      - image: cimg/node:20.0

parameters:
  deploy-env:
    type: string
    default: staging

jobs:
  build:
    executor: default
    steps:
      - checkout
      - node/install-packages:
          pkg-manager: npm
      - run:
          name: Build application
          command: npm run build
      - persist_to_workspace:
          root: .
          paths:
            - dist
  test:
    executor: default
    parallelism: 4
    steps:
      - checkout
      - attach_workspace:
          at: .
      - node/install-packages:
          pkg-manager: npm
      - run:
          name: Run tests with timing split
          command: |
            TEST_FILES=$(circleci tests glob "**/*.test.js" | circleci tests split --split-by=timings)
            npm test -- $TEST_FILES
      - store_test_results:
          path: reports/junit
      - store_artifacts:
          path: coverage

workflows:
  build-and-deploy:
    jobs:
      - build
      - test:
          requires: [build]
      - deploy:
          requires: [test]
          filters:
            branches:
              only: main
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CIRCLE_SHA1` | Commit SHA |
| `CIRCLE_BRANCH` | Branch name |
| `CIRCLE_TAG` | Git tag (if triggered by tag) |
| `CIRCLE_JOB` | Current job name |
| `CIRCLE_WORKFLOW_ID` | Workflow instance ID |
| `CIRCLE_REPOSITORY_URL` | Repository URL |
| `CIRCLECI` | Always `true` when running in CircleCI |
| `CIRCLE_USERNAME` | GitHub/Bitbucket username of triggerer |

### Secrets Handling (Contexts and Project Settings)

- **Project Environment Variables**: Set in Project Settings > Environment Variables
- **Contexts**: Named collections of environment variables, restricted by security groups
- **Restricted contexts**: Limit access to specific user groups or GitHub teams
- **Masking**: Set "Mask" flag to hide in UI logs

```yaml
workflows:
  deploy:
    jobs:
      - deploy:
          context: production-deploy-context
```

### Native Features

| Feature | Implementation |
|---------|---------------|
| Caching | `restore_cache` / `save_cache` with key templates |
| Artifacts | `store_artifacts`, `persist_to_workspace` / `attach_workspace` |
| Docker layer caching | `docker_layer_caching: true` in `setup_remote_docker` |
| Parallelism | `parallelism: N` with `circleci tests split` |
| Orbs | Reusable packages of config (`circleci/node`, `circleci/aws-cli`) |
| Resource classes | `resource_class: large` for bigger compute |
| Self-hosted runners | `resource_class: <namespace>/<resource-class>` |
| IP ranges | `circleci_ip_ranges: true` for egress whitelisting |
| Scheduled pipelines | Triggers in UI or API with cron |

---

## Travis CI

### File Location
`.travis.yml`

### Core Syntax

```yaml
language: node_js
node_js:
  - "20"
  - "18"

os:
  - linux
  - osx

dist: jammy

cache:
  npm: true
  directories:
    - node_modules

jobs:
  include:
    - stage: test
      script: npm test
    - stage: build
      script: npm run build
    - stage: deploy
      if: branch = main AND type = push
      script: skip
      deploy:
        provider: script
        script: bash deploy.sh
        on:
          branch: main

env:
  global:
    - NODE_ENV=test
  jobs:
    - TEST_SUITE=unit
    - TEST_SUITE=integration
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `TRAVIS_BRANCH` | Branch name |
| `TRAVIS_COMMIT` | Commit SHA |
| `TRAVIS_JOB_ID` | Job ID |
| `TRAVIS_BUILD_ID` | Build ID |
| `TRAVIS_REPO_SLUG` | `owner/repo` format |
| `TRAVIS_TAG` | Tag name if tag build |
| `TRAVIS_PULL_REQUEST` | PR number or `false` |
| `TRAVIS_OS_NAME` | `linux`, `osx`, or `windows` |

### Secrets Handling

- **Repository settings**: Environment variables in UI, marked as "Display value in build log: OFF" for secrets
- **Encrypting files**: `travis encrypt-file` for sensitive files
- **Encrypting values**: `travis encrypt` for CLI-encrypted strings

```bash
travis encrypt MY_SECRET=value --add env.global
```

### Native Features

| Feature | Implementation |
|---------|---------------|
| Caching | `cache:` with `directories` or built-in per language |
| Artifacts | External (AWS S3, etc.) or custom deploy providers |
| Matrix builds | `language` versions + `os` combinations |
| Stages | Sequential `jobs:` with `stage` labels |
| Deploy providers | Built-in providers for Heroku, AWS, npm, PyPI, etc. |
| Cron jobs | Settings > Cron jobs in UI |
| Build matrix | Excludes, includes, allowed failures |

---

## Cross-Platform Secrets Comparison

| Platform | Secret Storage | Injection Method | Rotation Support | Scope |
|----------|--------------|-----------------|------------------|-------|
| GitHub Actions | Repository/Org/Environment settings | `secrets.NAME` context | Manual or API | Repository, Organization, Environment |
| GitLab CI | CI/CD Variables (Project/Group/Instance) | `$VAR_NAME` or file type | Manual | Project, Group, Instance, Environment |
| Azure DevOps | Variable Groups + Key Vault | `$(VariableName)` or task | Key Vault auto-rotation | Pipeline, Variable Group, Key Vault |
| Jenkins | Credentials plugin | `withCredentials` or `credentials()` | Manual or script | Global, Folder, Job |
| CircleCI | Project Settings + Contexts | `$VAR_NAME` | Manual | Project, Context (group-restricted) |
| Travis CI | Repository settings + encrypted | `$VAR_NAME` | Manual | Repository |

## Cross-Platform Artifact Handling

| Platform | Upload | Download | Retention | Size Limits |
|----------|--------|----------|-----------|-------------|
| GitHub Actions | `upload-artifact` | `download-artifact` | 90 days default | 500 MB per file (free) |
| GitLab CI | `artifacts` keyword | `dependencies` or `needs` | 30 days default (configurable) | 1 GB per job (configurable) |
| Azure DevOps | `PublishBuildArtifacts` | `DownloadBuildArtifacts` | Configurable (retention policies) | No hard limit |
| Jenkins | `archiveArtifacts` | Built-in UI or Pipeline | Job config / plugin | Limited by disk |
| CircleCI | `store_artifacts` / `persist_to_workspace` | `attach_workspace` | 30 days | 5 GB total per project |
| Travis CI | External upload (S3, etc.) | External | External | External |

## Cross-Platform Caching Comparison

| Platform | Cache Key | Scope | Policy | Notes |
|----------|-----------|-------|--------|-------|
| GitHub Actions | `key` + `restore-keys` | Repository, can be cross-workflow | Push on hit/miss | `actions/cache@v4` |
| GitLab CI | `key` (files or string) | Job or protected branch | Push on success only | `cache:policy: push` / `pull` |
| Azure DevOps | `key` in `Cache@2` | Pipeline or branch | Always push on miss | `Cache@2` task |
| Jenkins | Custom or `cache` step | Node-local | Configurable | Often plugin-dependent |
| CircleCI | `key` with checksum template | Branch-specific default | Push at `save_cache` | `restore_cache` / `save_cache` |
| Travis CI | Built-in per language or custom | Repository | Push on success | Language-specific defaults |
