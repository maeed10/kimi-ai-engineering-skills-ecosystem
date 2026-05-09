# SARIF Integration Guide

Reference for the Static Analysis Results Interchange Format (SARIF) v2.1.0, covering schema essentials, CI platform ingestion, suppression patterns, and unified reporting properties.

## SARIF Schema Essentials

SARIF is a JSON-based standard (OASIS SARIF v2.1.0) for exchanging static analysis results. A minimal valid SARIF log contains `version`, `$schema`, and `runs`.

### Top-Level Structure

```json
{
  "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "semgrep",
          "version": "1.50.0",
          "informationUri": "https://semgrep.dev"
        }
      },
      "results": [
        {
          "ruleId": "python.lang.security.audit.eval-dangerous.eval-dangerous",
          "message": {
            "text": "Detected the use of eval(). eval() can be dangerous if used to evaluate dynamic content."
          },
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {
                  "uri": "src/utils/parser.py",
                  "uriBaseId": "%SRCROOT%"
                },
                "region": {
                  "startLine": 42,
                  "startColumn": 10,
                  "endLine": 42,
                  "endColumn": 24,
                  "snippet": {
                    "text": "eval(user_input)"
                  }
                }
              }
            }
          ],
          "level": "error",
          "properties": {
            "cvssScore": 7.5,
            "cweId": "CWE-95"
          }
        }
      ]
    }
  ]
}
```

### Key Objects

| Object | Purpose | Required |
|--------|---------|----------|
| `tool.driver` | Identifies the scanner that produced the results | Yes |
| `results` | Array of individual findings | Yes |
| `result.ruleId` | Stable identifier for the rule that triggered | Yes |
| `result.message.text` | Human-readable description | Yes |
| `result.locations` | Where the finding occurs (file, line, column) | Yes |
| `result.level` | Severity: `note`, `warning`, `error`, `none` | No (default: `warning`) |
| `result.properties` | Key-value map for custom metadata | No |
| `result.relatedLocations` | Additional related code locations | No |
| `result.codeFlows` | Data-flow or control-flow traces | No |
| `result.fixes` | Suggested fixes with replacements | No |

### Severity Mapping to SARIF `level`

| Unified Severity | SARIF `level` | Rationale |
|------------------|---------------|-----------|
| Critical | `error` | Action required; blocks pipelines |
| High | `error` | Action required; blocks pipelines |
| Medium | `warning` | Review required; may block with policy |
| Low | `warning` or `note` | Review at discretion |
| Info | `note` | Informational only |

### Custom Properties for Unified Reporting

When aggregating findings from multiple tools, add normalized properties under `result.properties`:

```json
{
  "properties": {
    "unifiedSeverity": "high",
    "cvssScore": 7.5,
    "cvssVector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
    "cweId": "CWE-798",
    "cweName": "Use of Hard-coded Credentials",
    "category": "secret-scanning",
    "toolName": "trufflehog",
    "toolRuleId": "AWS",
    "suppressionState": "none",
    "exploitAvailable": false,
    "fixAvailable": true,
    "fixVersion": "2.3.1",
    "dependencyName": "requests",
    "dependencyVersion": "2.25.0",
    "transitive": true,
    "reachability": "reachable",
    "confidence": "high",
    "falsePositiveLikely": false
  }
}
```

## GitHub Advanced Security Integration

GitHub ingests SARIF via the `codeql-action/upload-sarif` action and displays findings in the Security tab under Code scanning alerts.

### Upload Action

```yaml
- name: Upload SARIF to GitHub
  uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: results.sarif
    category: security-scan  # Optional: groups alerts by category
```

### Requirements for GitHub Ingestion

1. **File size**: Maximum 1000 results per upload for free/private repos; 5000 for GitHub Enterprise Cloud
2. **Schema**: Must be valid SARIF 2.1.0
3. **`tool.driver.name`**: Required for alert grouping
4. **`result.ruleId`**: Required; used for alert deduplication across uploads
5. **`uri` in artifactLocation**: Must be relative to repository root; absolute URIs may be rejected
6. **Category**: Use `category` input to separate alerts from different scanners (e.g., `sast`, `secrets`, `dependencies`)

### Alert Lifecycle

- **Open**: First time a `ruleId + location` combination is uploaded
- **Fixed**: No longer present in a subsequent upload of the same category
- **Dismissed**: Manual dismissal with reason (false positive, won't fix, used in tests)
- **Reopened**: Re-appears after being fixed/dismissed

### GitHub-Specific SARIF Properties

GitHub recognizes specific SARIF properties for enhanced display:

```json
{
  "properties": {
    "precision": "high",
    "tags": ["security", "external/cwe/cwe-798"],
    "security-severity": 7.5
  }
}
```

- `precision`: `very-high`, `high`, `medium`, `low` — affects default sorting
- `security-severity`: Numeric score 0.0–10.0 used for severity sorting and filtering
- `tags`: Array of strings; `external/cwe/cwe-XXX` adds CWE links

### Example: Full GitHub Actions Workflow

```yaml
name: Security Scan

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  security:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      actions: read
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run unified security scan
        run: |
          python scripts/run_security_scan.py \
            --all \
            --output-format sarif \
            --output-file security-results.sarif \
            --fail-on critical
        continue-on-error: true

      - name: Upload SAST results
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: security-results.sarif
          category: unified-security-scan
```

## GitLab SAST Integration

GitLab Ultimate supports SARIF ingestion for its Vulnerability Report and Security Dashboard.

### CI Artifact Configuration

```yaml
security_scan:
  stage: test
  image: python:3.11-slim
  variables:
    SECURE_LOG_LEVEL: "debug"
  script:
    - pip install -r scripts/requirements.txt
    - python scripts/run_security_scan.py --all --output-format sarif --output-file gl-sast-report.sarif
  artifacts:
    reports:
      sast: gl-sast-report.sarif
    when: always
    expire_in: 1 week
  allow_failure: true
```

### GitLab-Specific Requirements

1. **Artifact name**: Must be `gl-sast-report.sarif` for automatic parsing, or declared explicitly
2. **Schema validation**: GitLab validates SARIF strictly; invalid uploads are rejected with pipeline warnings
3. **Vulnerability ID**: GitLab uses `ruleId + location` as the deduplication key
4. **Severity**: GitLab reads `result.level` and maps `error` → High, `warning` → Medium, `note` → Low
5. **Confidence**: Not directly used in SARIF, but can be placed in `properties.confidence`

### Enrichment for GitLab

GitLab displays `message.text`, `ruleId`, and `locations`. To add links and metadata:

```json
{
  "results": [
    {
      "ruleId": "CVE-2023-1234",
      "message": {
        "text": "Dependency 'requests' 2.25.0 is vulnerable to CVE-2023-1234. Upgrade to 2.31.0.",
        "markdown": "Dependency `requests` `2.25.0` is vulnerable to [CVE-2023-1234](https://nvd.nist.gov/vuln/detail/CVE-2023-1234). Upgrade to `2.31.0`."
      },
      "locations": [...],
      "properties": {
        "issueLinks": ["https://nvd.nist.gov/vuln/detail/CVE-2023-1234"],
        "solution": "Upgrade requests to >=2.31.0"
      }
    }
  ]
}
```

## Suppression Patterns in SARIF

SARIF supports explicit suppression states within the result object, separate from inline code comments.

### Inline Suppression in SARIF

```json
{
  "results": [
    {
      "ruleId": "CKV_AWS_20",
      "message": {
        "text": "S3 bucket has ACL which allows public access"
      },
      "locations": [...],
      "suppressions": [
        {
          "kind": "inSource",
          "justification": "Intentionally public: hosts open dataset for research"
        }
      ]
    }
  ]
}
```

### Suppression Kinds

| Kind | Meaning | Source |
|------|---------|--------|
| `inSource` | Developer added a suppression directive in code | Inline comment (`# nosemgrep`, `# checkov:skip`) |
| `external` | Suppressed by external system (issue tracker, dashboard) | GitHub/GitLab dismissal |

### External Suppression Example

```json
{
  "suppressions": [
    {
      "kind": "external",
      "justification": "Risk accepted: internal tool with no production exposure",
      "location": {
        "physicalLocation": {
          "artifactLocation": {
            "uri": "docs/SECURITY_EXCEPTIONS.md"
          }
        }
      }
    }
  ]
}
```

### Filtering Suppressed Results in Scripts

When reading SARIF for CI gating, respect `suppressions`:

```python
# Pseudologic for filtering
def is_active_finding(result):
    suppressions = result.get("suppressions", [])
    if not suppressions:
        return True
    # SARIF allows partial suppression; all entries must be external+accepted to hide
    for s in suppressions:
        if s.get("kind") == "inSource":
            return False  # In-source suppressions hide the finding
        if s.get("kind") == "external" and s.get("status") == "accepted":
            continue
        return True
    return False
```

## Multi-Tool SARIF Aggregation

When combining SARIF from multiple tools into a single file, use separate `run` objects within the `runs` array:

```json
{
  "version": "2.1.0",
  "runs": [
    {
      "tool": { "driver": { "name": "semgrep", "version": "1.50.0" } },
      "results": [...]
    },
    {
      "tool": { "driver": { "name": "trivy", "version": "0.48.0" } },
      "results": [...]
    }
  ]
}
```

GitHub accepts a single SARIF file with multiple runs and separates alerts by `tool.driver.name`.

### Deduplication Strategy

When aggregating, deduplicate findings that represent the same issue at the same location:

**Dedup key**: `(ruleId, location.uri, location.startLine, location.startColumn, normalizedMessage)`

1. Parse all SARIF runs
2. Build a dedup dictionary using the key above
3. When collisions occur, keep the finding with:
   - Higher severity (Critical > High > Medium > Low)
   - Higher confidence (if available)
   - More complete metadata (CVSS, CWE, fix version)
4. Emit a combined `runs` array or flatten into a single run with tool extensions

### Flattened Single-Run Aggregation

For tools that only accept one run per file, merge results into a single run and add tool provenance in `properties`:

```json
{
  "tool": {
    "driver": {
      "name": "unified-security-scanner",
      "version": "1.0.0",
      "informationUri": "https://github.com/org/security-scanner"
    },
    "extensions": [
      {
        "name": "semgrep",
        "version": "1.50.0"
      },
      {
        "name": "trivy",
        "version": "0.48.0"
      }
    ]
  },
  "results": [
    {
      "ruleId": "semgrep.python.lang.security.eval",
      "message": { "text": "..." },
      "locations": [...],
      "properties": {
        "originalTool": "semgrep"
      }
    }
  ]
}
```

## Converting Tool Output to SARIF

Many tools output native JSON or XML. Convert to SARIF for uniform CI ingestion.

### Conversion Tools

| Source Tool | Converter | Command |
|-------------|-----------|---------|
| Bandit | Native | `bandit -f sarif` |
| ESLint | Native | `--format sarif` |
| gosec | Native | `-fmt sarif` |
| Semgrep | Native | `--sarif` |
| Trivy | Native | `--format sarif` |
| Checkov | Native | `--output sarif` |
| tfsec | Native | `--format sarif` |
| npm audit | `npm-audit-to-sarif` | `npm-audit-to-sarif -i audit.json -o audit.sarif` |
| pip-audit | Native | `--format=sarif` |
| cargo-audit | `cargo-audit-sarif` | `cargo-audit-sarif -i audit.json -o audit.sarif` |
| Grype | Native | `-o sarif` |
| gitleaks | Native | `--report-format sarif` |
| truffleHog | jq script | Custom transformation (see below) |

### truffleHog to SARIF (jq)

```bash
trufflehog git file://. --json | jq -s '
{
  "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "truffleHog",
          "version": "3.0.0"
        }
      },
      "results": [
        .[] | select(.SourceMetadata.Data.Git) | {
          "ruleId": .DetectorName,
          "message": {
            "text": "Detected potential secret: \(.DetectorName)"
          },
          "locations": [
            {
              "physicalLocation": {
                "artifactLocation": {
                  "uri": .SourceMetadata.Data.Git.file,
                  "uriBaseId": "%SRCROOT%"
                },
                "region": {
                  "startLine": .SourceMetadata.Data.Git.line
                }
              }
            }
          ],
          "level": "error"
        }
      ]
    }
  ]
}' > trufflehog.sarif
```

## Validation

Validate SARIF before uploading to CI to avoid rejected uploads.

### Using the SARIF Validator

```bash
# Install npm package
npm install -g @microsoft/sarif-multitool

# Validate
sarif validate results.sarif

# Or use the online schema
python -c "
import json
import jsonschema
import requests
schema = requests.get('https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json').json()
data = json.load(open('results.sarif'))
jsonschema.validate(data, schema)
print('Valid SARIF')
"
```

### Common Validation Failures

| Error | Fix |
|-------|-----|
| `uri` is absolute | Strip prefix to make relative to repo root |
| `level` is missing | Add `level` field or accept default `warning` |
| `tool.driver.name` missing | Add scanner name |
| `result.message.text` missing | Add human-readable message |
| Duplicate `ruleId` without `ruleIndex` | Add `ruleIndex` or ensure `ruleId` uniqueness per run |
