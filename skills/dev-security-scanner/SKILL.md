---
name: dev-security-scanner
description: Developer-facing security scanner integrating SAST, secret detection, dependency vulnerability scanning, container scanning, and infrastructure misconfiguration detection. Use before commits, during PR review, responding to CVEs, or setting up CI security gates. Outputs SARIF, supports CodeQL, Semgrep, Trivy, Checkov, and truffleHog.
---

# Dev Security Scanner

Integrate security scanning into the developer workflow with SAST, secret detection, dependency auditing, container image scanning, and infrastructure misconfiguration detection. Produces unified SARIF output for CI gates and GitHub Advanced Security.

## When to Use

- Before committing code that adds credentials, parses input, or handles auth
- When a CVE is announced for a project dependency
- During PR review to catch security regressions or new secrets
- When scanning Terraform, CloudFormation, or Kubernetes manifests for misconfigurations
- When hardening Dockerfiles and base images before deployment
- When setting up or tuning security gates in CI/CD pipelines

## Workflow Decision Tree

```
What are you scanning?
├── Source code (application logic)
│   ├── Language-specific SAST → CodeQL, Semgrep, Bandit, ESLint security, gosec
│   └── Secret detection → truffleHog, gitleaks, git-secrets
├── Dependencies / lockfiles
│   └── Vulnerability audit → npm audit, pip-audit, cargo audit, Snyk, OSV
├── Container artifacts
│   ├── Dockerfile static analysis → Hadolint, Checkov
│   └── Image vulnerability scan → Trivy, Clair, Grype
├── Infrastructure as Code
│   └── Misconfiguration scan → Checkov, tfsec, cdk-nag
└── Unified CI gate
    └── Orchestrated multi-tool scan → scripts/run_security_scan.py
```

## Severity Classification

All findings are classified using a unified 4-level severity model mapped to CVSS v3.1 ranges:

| Severity | CVSS Score | Response Time | Action |
|----------|------------|---------------|--------|
| Critical | 9.0 - 10.0 | Immediate | Block merge / deployment; fix within 24h |
| High | 7.0 - 8.9 | Urgent | Block merge; fix within 72h |
| Medium | 4.0 - 6.9 | Soon | Track in backlog; fix within 2 weeks |
| Low | 0.1 - 3.9 | Planned | Address in next maintenance window |
| Info | 0.0 | N/A | Document; no fix required |

**Severity override rules**:
- A reachable RCE in production-facing code is at least **High** even if CVSS suggests Medium
- A secret for a dev/test-only service with no production access may be downgraded to **Medium** with documented justification
- A dependency vulnerability with no fixed version and no exploit code may be downgraded one level with risk acceptance

## Scanning Workflows

### Workflow 1: Pre-Commit Security Check

Run before every commit that touches sensitive areas (auth, parsing, networking, crypto).

1. **Detect secrets in staged changes**
   ```bash
   # truffleHog scans staged files
   trufflehog git file://. --since-commit=HEAD --only-verified
   ```

2. **Run fast SAST on changed files**
   ```bash
   # Semgrep with security-focused rules
   semgrep --config=p/security-audit --config=p/owasp-top-ten --config=p/cwe-top-25 \
           --error --severity=ERROR \
           $(git diff --cached --name-only --diff-filter=ACM)
   ```

3. **Audit changed lockfiles**
   ```bash
   # npm
   npm audit --audit-level=moderate

   # Python
   pip-audit --desc --format=json

   # Rust
   cargo audit
   ```

4. **Review findings**: If any Critical or High findings exist, block the commit and fix immediately.

### Workflow 2: Full Project Security Scan

Run weekly, before major releases, or when onboarding a new repository.

1. **SAST deep scan**
   - Generate CodeQL database and run queries for the project's language
   - Run Semgrep with `p/security-audit`, `p/owasp-top-ten`, `p/cwe-top-25`, `p/secrets`
   - Run language-specific tools (Bandit, gosec, ESLint security plugin)

2. **Secret scan full history**
   ```bash
   # Scan entire git history for unverified secrets
   trufflehog git file://. --branch=main --only-verified=false
   gitleaks detect --source . --verbose
   ```

3. **Dependency vulnerability scan**
   - Parse lockfiles and query OSV / Snyk / GitHub Advisory Database
   - Check transitive dependencies where possible
   - Identify fixed versions and upgrade paths

4. **Container scan** (if Dockerfile or built images exist)
   - Static analysis of Dockerfile with Checkov + Hadolint
   - Image scan with Trivy or Grype for OS and application vulnerabilities

5. **Infrastructure scan** (if IaC exists)
   - Terraform: `checkov -d . --framework terraform` + `tfsec`
   - CloudFormation: `checkov -d . --framework cloudformation`
   - Kubernetes: `checkov -d . --framework kubernetes`

6. **Aggregate and deduplicate** results with `scripts/run_security_scan.py`

### Workflow 3: CVE Response

Triggered when a CVE is published affecting a dependency.

1. **Identify affected scope**
   ```bash
   # Find which projects use the vulnerable package
   grep -r "vulnerable-package" */package-lock.json */Pipfile.lock */Cargo.lock
   ```

2. **Assess exploitability**
   - Is the vulnerable code path reachable? (SAST / call graph analysis)
   - Is there a fixed version? (`npm view <pkg> versions`, `pip index versions <pkg>`)
   - Is there a published exploit or POC?

3. **Determine severity and timeline**
   - Map CVSS to Critical/High/Medium/Low using the classification table above
   - Adjust for exploitability and blast radius

4. **Apply remediation**
   - Upgrade to patched version if available
   - Apply temporary mitigations (input validation, WAF rules, feature flags)
   - Document risk acceptance if no fix exists and risk is low

5. **Verify fix**
   - Re-run dependency scan to confirm vulnerability no longer reported
   - Run regression tests to ensure upgrade compatibility
   - Monitor for follow-up CVEs in the patched version

### Workflow 4: PR Security Review

Security-focused review checklist for pull requests.

**Code changes**:
- [ ] New secrets or credentials introduced? (scan with truffleHog)
- [ ] New user input paths without validation? (check with Semgrep `p/owasp-top-ten`)
- [ ] New SQL, shell, or template constructions? (injection risk)
- [ ] New dependencies added? (audit with `npm audit`, `pip-audit`, `cargo audit`)
- [ ] New auth or session handling? (SAST rules for auth best practices)
- [ ] Cryptographic operations using weak algorithms or RNG? (Semgrep crypto rules)

**Infrastructure changes**:
- [ ] New open security groups or firewall rules? (`0.0.0.0/0` to sensitive ports)
- [ ] Unencrypted storage or transit? (Checkov encryption rules)
- [ ] Overly permissive IAM roles or RBAC?
- [ ] Hardcoded secrets in Terraform/CloudFormation?

**Container changes**:
- [ ] Base image updated? (re-scan with Trivy)
- [ ] Running as root? (Checkov CKV_DOCKER_8)
- [ ] Sensitive build args or env vars in layers?

## False Positive Management

Suppressing findings requires documented justification. Never suppress without a reason.

### Suppression Methods

| Tool | Suppression Pattern | Location |
|------|---------------------|----------|
| Semgrep | `# nosemgrep: rule-id` | Inline comment on finding line |
| Semgrep | `.semgrepignore` + `triage.yaml` | Repo root |
| Bandit | `# nosec BXXX` | Inline comment on finding line |
| ESLint | `/* eslint-disable security/detect-object-injection */` | Inline or config |
| gosec | `# nosec GXXX` | Inline comment on finding line |
| CodeQL | `// lgtm[query-id]` or `codeql.yml` exclusion | Inline or `.github/codeql/codeql-config.yml` |
| Checkov | `# checkov:skip=CKV_XXX:justification` | Inline in IaC |
| tfsec | `# tfsec:ignore:AWSXXX` | Inline in Terraform |
| Trivy | `.trivyignore` with CVE and justification | Repo root |

### Justification Requirements

A valid suppression must include:
1. **Rule ID** being suppressed
2. **Justification**: Why is this a false positive in this context?
3. **Scope**: Single line, file, or global? Limit scope as much as possible.
4. **Expiry**: Review date for temporary suppressions (e.g., "revisit 2024-06-01")
5. **Approval**: For Critical/High suppressions, require security reviewer sign-off

**Example valid suppression**:
```python
# nosec B105: not a password — hardcoded test fixture used only in unit tests
TEST_PASSWORD = "fake-password-for-mock"
```

**Example invalid suppression**:
```python
# nosec
password = "production-secret-here"  # Wrong: no rule ID, no justification
```

## CI Integration

### GitHub Actions with SARIF

Upload SARIF output to GitHub Advanced Security for code scanning alerts:

```yaml
- name: Run security scan
  run: python scripts/run_security_scan.py --output-format sarif --output-file results.sarif

- name: Upload SARIF to GitHub
  uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: results.sarif
```

### GitLab CI SAST Integration

GitLab recognizes SARIF for its Vulnerability Report:

```yaml
security_scan:
  stage: test
  image: python:3.11-slim
  script:
    - pip install -r scripts/requirements.txt
    - python scripts/run_security_scan.py --output-format sarif --output-file gl-sast-report.sarif
  artifacts:
    reports:
      sast: gl-sast-report.sarif
    when: always
```

### Fail-on-Severity Gate

Use the script to enforce quality gates:

```bash
# Block CI if any Critical or High findings exist
python scripts/run_security_scan.py --fail-on critical,high

# Block CI only for Critical, allow High with manual review
python scripts/run_security_scan.py --fail-on critical
```

## Output Formats

| Format | Use Case | Consumed By |
|--------|----------|-------------|
| SARIF | Universal CI / dashboard ingestion | GitHub Advanced Security, GitLab, Azure DevOps, VS Code |
| JSON | Programmatic processing, custom dashboards | jq, Python, custom automation |
| HTML | Human review, executive summary | Browser, email reports |
| Markdown | PR comments, issue tickets | GitHub PR comments, Jira |

## Automation Scripts

Use `scripts/run_security_scan.py` to orchestrate multi-tool scanning with unified reporting:

```bash
# Full scan with SARIF output for CI
python scripts/run_security_scan.py --all --output-format sarif --output-file security.sarif

# Fast pre-commit scan (SAST + secrets only)
python scripts/run_security_scan.py --sast --secrets --output-format json

# Scan specific categories
python scripts/run_security_scan.py --dependencies --containers --fail-on high

# Scan IaC only
python scripts/run_security_scan.py --infrastructure --output-format markdown
```

The script performs:
1. **Auto-discovery**: Detects project type by files present (`package.json`, `Cargo.toml`, `Dockerfile`, `*.tf`)
2. **Tool dispatch**: Runs the appropriate scanners for discovered artifacts
3. **Result normalization**: Converts all tool outputs to a unified finding schema
4. **Deduplication**: Merges identical findings from multiple tools (e.g., Semgrep + CodeQL)
5. **Severity harmonization**: Maps per-tool severities to the unified Critical/High/Medium/Low scale
6. **Export**: Writes SARIF, JSON, HTML, or Markdown reports

## Resources

### scripts/
- `run_security_scan.py` — Multi-tool security scan orchestrator with unified SARIF/JSON/HTML output

### references/
- `security_tools.md` — Per-category tool catalog with installation, configuration, and CLI examples
- `sarif_integration.md` — SARIF schema details, GitHub/GitLab upload, suppression patterns, and custom properties
