# Security Tools Catalog

Per-category reference for security scanning tools, covering installation, configuration, and common CLI invocations.

## SAST (Static Application Security Testing)

### CodeQL

GitHub's semantic code analysis engine. Best for deep data-flow analysis and custom queries.

**Installation**:
```bash
# macOS
brew install codeql

# Linux / CI: download CLI bundle from GitHub releases
curl -L https://github.com/github/codeql-cli-binaries/releases/latest/download/codeql-linux64.zip -o codeql.zip
unzip codeql.zip
export PATH=$PWD/codeql:$PATH
```

**Basic workflow**:
```bash
# Create database
codeql database create --language=python --source-root=. ./codeql-db

# Run standard queries
codeql database analyze ./codeql-db \
  python-security-and-quality.qls \
  --format=sarif-latest --output=codeql-results.sarif

# Supported languages: cpp, csharp, go, java, javascript, python, ruby, swift
```

**Configuration** (`codeql.yml`):
```yaml
name: "Custom CodeQL Config"
queries:
  - uses: security-and-quality
paths-ignore:
  - tests/
  - vendor/
  - '**/*.test.js'
```

**CI snippet (GitHub Actions)**:
```yaml
- uses: github/codeql-action/init@v3
  with:
    languages: javascript, python
    config-file: ./.github/codeql/codeql-config.yml
- uses: github/codeql-action/analyze@v3
```

---

### Semgrep

Fast, lightweight static analyzer with an extensive rule registry. Excellent for PR scanning and pre-commit hooks.

**Installation**:
```bash
# macOS / Linux
brew install semgrep

# Python
pip install semgrep

# Docker
docker run --rm -v $(PWD):/src returntocorp/semgrep semgrep --config=auto /src
```

**Recommended rulesets**:
| Ruleset | Purpose | Command |
|---------|---------|---------|
| `p/security-audit` | General security audit | `--config=p/security-audit` |
| `p/owasp-top-ten` | OWASP Top 10 coverage | `--config=p/owasp-top-ten` |
| `p/cwe-top-25` | CWE Top 25 | `--config=p/cwe-top-25` |
| `p/secrets` | Secret detection | `--config=p/secrets` |
| `p/ci` | CI/CD misconfigurations | `--config=p/ci` |
| `p/supply-chain` | Dependency confusion, typosquatting | `--config=p/supply-chain` |

**CLI examples**:
```bash
# Scan with multiple rulesets, fail on error-level findings
semgrep --config=p/security-audit --config=p/owasp-top-ten --config=p/cwe-top-25 \
        --error --severity=ERROR .

# Scan only changed files in CI
semgrep --config=p/security-audit --baseline-commit=HEAD~1 --error

# Output SARIF for GitHub ingestion
semgrep --config=p/security-audit --sarif --output=semgrep.sarif .

# Scan specific paths
semgrep --config=p/security-audit src/ lib/
```

**Configuration** (`.semgrep.yml`):
```yaml
rules:
  - id: no-hardcoded-passwords
    pattern-regex: password\s*=\s*["'][^"']+["']
    languages: [python, javascript]
    severity: ERROR
    message: "Hardcoded password detected"
```

---

### Bandit (Python)

Security linter for Python code. Finds common issues like hardcoded passwords, weak crypto, and injection risks.

**Installation**:
```bash
pip install bandit
```

**Usage**:
```bash
# Scan a file or directory
bandit -r ./src

# Generate SARIF output
bandit -r ./src -f sarif -o bandit-results.sarif

# Exclude test directories
bandit -r ./src -x ./tests,./venv

# Set severity threshold (skip INFO and LOW)
bandit -r ./src -ll

# Show confidence and severity in output
bandit -r ./src -v
```

**Configuration** (`.bandit` or `bandit.yaml`):
```yaml
skips: [B101, B601]  # Skip assert-used and paramiko-host-key-missing
assert_used:
  skips: ["*/test_*.py", "*/tests/**"]
```

---

### ESLint Security Plugin

Security rules for JavaScript / TypeScript via ESLint.

**Installation**:
```bash
npm install --save-dev eslint-plugin-security
```

**Configuration** (`.eslintrc.js`):
```javascript
module.exports = {
  plugins: ['security'],
  extends: ['plugin:security/recommended'],
  rules: {
    'security/detect-object-injection': 'error',
    'security/detect-non-literal-regexp': 'warn',
    'security/detect-unsafe-regex': 'error',
    'security/detect-buffer-noassert': 'error',
    'security/detect-eval-with-expression': 'error',
    'security/detect-no-csrf-before-method-override': 'error',
    'security/detect-non-literal-fs-filename': 'warn',
    'security/detect-non-literal-require': 'warn',
    'security/detect-possible-timing-attacks': 'warn',
    'security/detect-pseudoRandomBytes': 'error',
  }
};
```

**SARIF output**:
```bash
npx eslint . --ext .js,.ts --format sarif --output-file eslint-security.sarif
```

---

### gosec (Go)

Security checker for Go by inspecting source code for security problems.

**Installation**:
```bash
go install github.com/securego/gosec/v2/cmd/gosec@latest
```

**Usage**:
```bash
# Scan all packages recursively
gosec ./...

# Exclude tests and generate SARIF
gosec -exclude-generated -fmt sarif -out gosec.sarif ./...

# Filter by severity
gosec -severity high ./...

# Exclude specific rules
gosec -exclude=G104,G304 ./...

# Scan with custom nosec tag
gosec -nosec-tag nosec ./...
```

**Rule categories**:
| ID | Category | Examples |
|----|----------|----------|
| G1xx | Injection | SQL injection, command injection |
| G2xx | Weak cryptography | Weak random, hardcoded secrets |
| G3xx | File system | Path traversal, file permissions |
| G4xx | Network | Insecure HTTP, TLS config |
| G5xx | Permissions | World-writable files, weak permissions |
| G6xx | Runtime | Unsafe, integer overflow |

---

### cargo-audit (Rust)

Scans `Cargo.lock` for crates with security vulnerabilities reported to the RustSec Advisory Database.

**Installation**:
```bash
cargo install cargo-audit
```

**Usage**:
```bash
# Basic audit
cargo audit

# Output JSON for automation
cargo audit --json

# Deny warnings and fail CI on yanked crates
cargo audit --deny warnings

# Ignore specific advisories with justification
cargo audit --ignore RUSTSEC-2021-0123
```

**CI integration**:
```bash
# Run in CI after build but before tests
cargo build
cargo audit --deny warnings
```

---

## Secret Scanning

### truffleHog

Scans git history and files for high-entropy strings and verified secrets using 800+ detectors.

**Installation**:
```bash
# macOS
brew install trufflesecurity/trufflehog/trufflehog

# Docker
docker run --rm -it -v "$PWD:/pwd" trufflesecurity/trufflehog:latest git file:///pwd
```

**Usage**:
```bash
# Scan entire git history
trufflehog git file://. --only-verified

# Scan only verified secrets (lower false positives)
trufflehog git file://. --branch=main --only-verified

# Scan filesystem (not just git history)
trufflehog filesystem . --only-verified

# Scan specific commits
trufflehog git file://. --since-commit=HEAD~10

# Output JSON
trufflehog git file://. --json

# Custom regex detector
trufflehog git file://. --config=trufflehog-config.yaml
```

**Configuration** (`trufflehog-config.yaml`):
```yaml
detectors:
  - name: custom-api-key
    regex:
      - 'apikey-[a-zA-Z0-9]{32}'
    verify: []
```

---

### gitleaks

Fast secret scanner with support for pre-commit hooks and CI integration.

**Installation**:
```bash
# macOS / Linux
brew install gitleaks

# Docker
docker run --rm -v "$PWD:/path" zricethezav/gitleaks:latest detect --source /path
```

**Usage**:
```bash
# Scan current directory
gitleaks detect --source . --verbose

# Scan with redacted output
gitleaks detect --source . --redact

# Generate SARIF report
gitleaks detect --source . --report-format sarif --report-path gitleaks.sarif

# Scan specific commits
gitleaks detect --source . --log-opts="--all --full-history"

# Check a single file
gitleaks protect --staged --verbose
```

**Pre-commit hook** (`.pre-commit-config.yaml`):
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

**Configuration** (`.gitleaks.toml`):
```toml
title = "Gitleaks Config"

[extend]
useDefault = true

[[rules]]
id = "custom-api-token"
description = "Custom API token"
regex = '''(?i)(custom_api_token)(.{0,20})?['"][0-9a-zA-Z]{32}['"]'''
tags = ["apikey"]

[allowlist]
description = "Ignore test fixtures"
paths = [
  '''tests\/.*\.py$''',
  '''test_.*\.py$''',
]
```

---

### git-secrets

Prevents committing secrets by scanning commit messages and staged files with hooks.

**Installation**:
```bash
# macOS
brew install git-secrets

# Manual
git clone https://github.com/awslabs/git-secrets.git
cd git-secrets && make install
```

**Setup per repository**:
```bash
git secrets --install
git secrets --register-aws  # Add AWS-specific patterns
git secrets --add 'api_key_[a-zA-Z0-9]{32}'
```

**Scan commands**:
```bash
# Scan all files
git secrets --scan

# Scan with recursive
git secrets --scan -r .

# Scan a specific file
git secrets --scan filename.txt
```

---

## Dependency Vulnerability Scanning

### npm audit

Built into npm. Scans Node.js dependencies against the npm advisory database.

**Usage**:
```bash
# Basic audit
npm audit

# Audit with JSON output
npm audit --json

# Only report moderate and above
npm audit --audit-level=moderate

# Attempt auto-fix
npm audit fix

# Fix but only update semver-compatible versions
npm audit fix --semver-major

# Dry-run fix
npm audit fix --dry-run
```

**CI enforcement**:
```bash
npm audit --audit-level=moderate
# Non-zero exit on findings; combine with `|| true` if you only want reporting
```

---

### pip-audit

Audits Python dependencies for known vulnerabilities using OSV and PyPI Advisory Database.

**Installation**:
```bash
pip install pip-audit
```

**Usage**:
```bash
# Audit current environment
pip-audit

# Audit requirements file
pip-audit -r requirements.txt

# Include descriptions and fix versions
pip-audit --desc --format=json

# Output SARIF
pip-audit --format=sarif --output=pip-audit.sarif

# Strict mode: fail on any vulnerability
pip-audit --strict

# Ignore specific vulnerability
pip-audit --ignore-vuln GHSA-xxxx-xxxx-xxxx
```

---

### Snyk CLI

Cross-platform dependency and container scanner with broad language support.

**Installation**:
```bash
npm install -g snyk
snyk auth
```

**Usage**:
```bash
# Test dependencies
snyk test

# Test with JSON output
snyk test --json

# Test specific manifest
snyk test --file=requirements.txt

# Monitor for regressions (pushes snapshot to Snyk dashboard)
snyk monitor

# Test Docker image
snyk container test myimage:tag

# Output SARIF
snyk test --sarif-file-output=snyk.sarif
```

**Configuration** (`.snyk` policy file):
```yaml
version: v1.25.0
ignore:
  'SNYK-PYTHON-REQUESTS-1234567':
    - '*':
        reason: 'Not exploitable in our usage — only used for internal health checks'
        expires: 2024-12-31T00:00:00.000Z
```

---

### OSV-Scanner

Google's scanner using the Open Source Vulnerabilities database. Supports multiple ecosystems.

**Installation**:
```bash
# macOS / Linux
brew install osv-scanner

# Go
 go install github.com/google/osv-scanner/cmd/osv-scanner@v1
```

**Usage**:
```bash
# Scan lockfiles in directory
osv-scanner -r .

# Scan specific lockfile
osv-scanner --lockfile=package-lock.json

# Output SARIF
osv-scanner -r . --format sarif --output osv.sarif

# Include git commit hash for base image scanning
osv-scanner --lockfile=/lib/os-release:22.04
```

---

## Container Scanning

### Trivy

Comprehensive scanner for OS packages, language dependencies, and misconfigurations in containers and IaC.

**Installation**:
```bash
# macOS / Linux
brew install aquasecurity/trivy/trivy

# Docker
docker run --rm -v "$PWD:/tmp" aquasec/trivy:latest fs /tmp
```

**Image scanning**:
```bash
# Scan a built image
trivy image myapp:latest

# Fail on high/critical
trivy image --severity HIGH,CRITICAL --exit-code 1 myapp:latest

# Output SARIF
trivy image --format sarif -o trivy.sarif myapp:latest

# Scan remote image without pulling
trivy image --skip-update --input image.tar
```

**Filesystem / repo scanning**:
```bash
# Scan source repo for vulnerabilities and misconfigurations
trivy fs --scanners vuln,misconfig,secret .

# Scan with SBOM generation
trivy fs --format cyclonedx -o sbom.json .
```

**Dockerfile scanning**:
```bash
trivy config Dockerfile
```

**Configuration** (`trivy.yaml`):
```yaml
severity:
  - HIGH
  - CRITICAL
scan:
  scanners:
    - vuln
    - misconfig
    - secret
    - license
output:
  format: sarif
  output: trivy-results.sarif
```

---

### Grype

Vulnerability scanner for container images and filesystems from Anchore.

**Installation**:
```bash
curl -sSfL https://raw.githubusercontent.com/anchore/grype/main/install.sh | sh -s -- -b /usr/local/bin
```

**Usage**:
```bash
# Scan image
grype myimage:latest

# Fail on medium and above
grype myimage:latest --fail-on medium

# Output SARIF
grype myimage:latest -o sarif

# Scan filesystem
grype dir:.

# Scan SBOM
grype sbom:./sbom.json

# Ignore specific vulnerabilities
grype myimage:latest --ignore .grype.yaml
```

**Configuration** (`.grype.yaml`):
```yaml
ignore:
  - vulnerability: CVE-2023-1234
    reason: "Not exploitable — requires local access"
```

---

### Hadolint

Dockerfile linter that enforces best practices and catches security-relevant Dockerfile issues.

**Installation**:
```bash
# macOS
brew install hadolint

# Docker
docker run --rm -i hadolint/hadolint < Dockerfile
```

**Usage**:
```bash
# Lint Dockerfile
hadolint Dockerfile

# Fail on warnings too
hadolint --failure-threshold=warning Dockerfile

# Output JSON
hadolint --format=json Dockerfile

# Ignore specific rules
hadolint --ignore=DL3008,DL3018 Dockerfile
```

**Configuration** (`.hadolint.yaml`):
```yaml
ignored:
  - DL3008  # Pin versions in apt-get install
  - DL3018  # Pin versions in apk add
trustedRegistries:
  - docker.io
  - my-registry.example.com
```

---

## Infrastructure Scanning

### Checkov

Scans Terraform, CloudFormation, Kubernetes, Docker, and more for misconfigurations against CIS benchmarks and custom policies.

**Installation**:
```bash
pip install checkov
```

**Usage**:
```bash
# Scan all frameworks in directory
checkov -d .

# Scan specific framework
checkov -d . --framework terraform
checkov -d . --framework cloudformation
checkov -d . --framework kubernetes
checkov -d . --framework dockerfile

# Output SARIF
checkov -d . --output sarif --output-file checkov.sarif

# Quiet mode (only failures)
checkov -d . --quiet

# Skip specific checks
checkov -d . --skip-check CKV_AWS_20,CKV_AWS_21

# Soft fail (report but don't exit with error)
checkov -d . --soft-fail

# Compact output for CI logs
checkov -d . --compact
```

**Configuration** (`checkov.yaml`):
```yaml
framework:
  - terraform
  - cloudformation
skip-check:
  - CKV_AWS_20
soft-fail: true
output:
  - sarif
  - cli
quiet: true
```

**Inline suppression**:
```hcl
resource "aws_s3_bucket" "logs" {
  # checkov:skip=CKV_AWS_20:Public access is intentional for public dataset
  acl = "public-read"
}
```

---

### tfsec

Terraform-focused security scanner with fast execution and clear output.

**Installation**:
```bash
# macOS
brew install tfsec

# GitHub release
curl -s https://raw.githubusercontent.com/aquasecurity/tfsec/master/scripts/install_linux.sh | bash
```

**Usage**:
```bash
# Scan Terraform directory
tfsec .

# Output SARIF
tfsec --format sarif --out tfsec.sarif .

# Exclude checks
tfsec --exclude aws-s3-enable-versioning,aws-s3-enable-logging .

# Minimum severity
tfsec --minimum-severity HIGH .

# Include passed rules in output
tfsec --include-passed .
```

**Configuration** (`.tfsec/config.yml`):
```yaml
severity_overrides:
  AWS002: HIGH
exclude:
  - aws-s3-enable-versioning
  - aws-vpc-no-excessive-port-access
```

**Inline suppression**:
```hcl
resource "aws_security_group" "allow_tls" {
  # tfsec:ignore:aws-vpc-no-public-ingress-sgr: Bastion requires 22 from VPN
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}
```

---

## Severity Mapping by Tool

| Tool | Critical | High | Medium | Low | Info |
|------|----------|------|--------|-----|------|
| CodeQL | `error` | `error` | `warning` | `warning` | `note` |
| Semgrep | `ERROR` | `ERROR` | `WARNING` | `WARNING` | `INFO` |
| Bandit | `HIGH` | `HIGH` | `MEDIUM` | `LOW` | `LOW` |
| gosec | `HIGH` | `HIGH` | `MEDIUM` | `LOW` | `LOW` |
| Trivy | `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` | `UNKNOWN` |
| Checkov | `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` | `INFO` |
| tfsec | `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` | — |
| npm audit | `critical` | `high` | `moderate` | `low` | `info` |
| pip-audit | — | — | — | — | Vulns only |
| cargo-audit | — | — | — | — | Advisories only |

Use the unified severity scale in `SKILL.md` when aggregating multi-tool output.
