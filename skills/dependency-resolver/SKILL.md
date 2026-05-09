---
name: dependency-resolver
description: >
  Dependency verification and vulnerability scanning backbone. Checks all required binaries and packages before pipeline start. Provides real CVE scanning via OSV API and GitHub Advisory Database with local caching. Generates SBOM and per-skill Dockerfiles. No skill executes with missing, outdated, or vulnerable dependencies. Integrates with ALL skills via manifest dependency declarations, skill-registry activation gates, security-auditor CVE feeds, and error-policy.
---

## 1. PURPOSE

The `dependency-resolver` skill is the **dependency verification and vulnerability scanning backbone** of the Kimi AI Engineering Skills Ecosystem v4.0. It ensures that **no skill ever executes with missing, outdated, or vulnerable dependencies**.

Before any pipeline starts, this skill performs a complete pre-flight check across:
- Required external binaries (`semgrep`, `k6`, `git`, `docker`, `tree-sitter`, etc.)
- Python packages (from `pyproject.toml` optional dependency groups)
- Language runtimes (Python 3.10+, Node 18+, Go 1.21+, etc.)
- CVE exposure via live OSV API and GitHub Advisory Database queries

It generates SBOMs, caches vulnerability data for offline operation, and produces actionable installation reports. It integrates with `skill-registry` to block skill activation until dependencies are satisfied, feeds CVE findings to `security-auditor` for merge-gate decisions, and triggers `error-policy` fallbacks when gaps are found.

---

## 2. CONTEXT & MOTIVATION

| Finding | ID | Severity | Validation |
|---------|----|----------|------------|
| Zero dependency specifications across 30 claimed scripts | IMP-4.1 | 8/10 | **VALID** — No `requirements.txt`, `pyproject.toml`, or `Dockerfiles` exist |
| Dependency Manager claims "CVE findings" with no OSV/NVD/GitHub Advisory connectivity | IMP-4.3 | 9/10 | **CRITICAL** — All CVE references are hallucinated; no live advisory database queries ever performed |

Without this skill, the ecosystem is **blind to its own supply chain**. Skills fail at runtime with opaque errors. Security claims are fabricated. This skill closes that gap with deterministic, cacheable, auditable dependency resolution.

---

## 3. KEY CAPABILITIES

### 3.1 Pre-flight Verification (`verify-deps.py`)

A single entry-point script that, given a target skill name or `--all` flag:

1. Parses the skill's `manifest.json` for `dependencies` declarations
2. Checks Python packages via `pip list` against version specs (PEP 440 compatible)
3. Checks external binaries via `shutil.which()` and `--version` invocation
4. Checks language runtime versions (Python, Node, Go, Rust)
5. Fails fast with a structured report if anything is missing or incompatible

**Usage:**
```bash
# Verify a single skill before execution
python scripts/verify-deps.py --skill security-auditor

# Verify the entire ecosystem
python scripts/verify-deps.py --all

# Generate SBOM and CVE report for session
python scripts/verify-deps.py --all --sbom --cve-scan
```

### 3.2 Dependency Manifest (`pyproject.toml`)

A root-level `pyproject.toml` defines per-skill optional dependency groups:

```toml
[project]
name = "kimi-ai-skills-ecosystem"
version = "4.0.0"
requires-python = ">=3.10"

[project.optional-dependencies]
security-auditor = ["semgrep>=1.50", "bandit>=1.7", "safety>=3.0"]
load-tester = ["k6-binary>=0.50; platform_system!='Windows'", "locust>=2.20"]
static-analysis = ["tree-sitter>=0.20", "pylint>=3.0"]
all = [
    "semgrep>=1.50",
    "bandit>=1.7",
    "tree-sitter>=0.20",
    "pylint>=3.0",
    "docker>=7.0",
    "requests>=2.31",
    "packaging>=23.0",
    "toml>=0.10",
    "pydantic>=2.0",
    "typer>=0.9",
]
```

Each skill's `manifest.json` references these groups and may declare additional binary/runtime requirements.

### 3.3 CVE Scanning (OSV + GitHub Advisory Database)

Real vulnerability scanning via live APIs:

- **OSV API** (`https://api.osv.dev/v1/querybatch`): Primary source for open-source package vulnerabilities. Supports batch queries.
- **GitHub Advisory Database** (GraphQL API `https://api.github.com/graphql`): Secondary source for CVE enrichment and exploitability metadata.

**Features:**
- Batch query all declared dependencies in a single API call (OSV supports up to 1,000 packages per batch)
- Cache responses locally in `/tmp/kimi-deps-cache/osv/` with TTL of 24 hours
- Update check runs daily; stale cache triggers a background refresh
- NEVER uses LLM internal knowledge for CVE identification — only live API data

**Cache Structure:**
```
/tmp/kimi-deps-cache/
├── osv/
│   ├── pypi-requests-2.31.0.json
│   ├── npm-semgrep-1.52.0.json
│   └── ...
├── github-advisory/
│   └── GHSA-xxxx-xxxx-xxxx.json
└── last-updated
```

### 3.4 SBOM Generation

Generate a SPDX-2.3 or CycloneDX 1.5 compatible Software Bill of Materials for any skill or the entire ecosystem.

**Contents:**
- All direct and transitive Python dependencies (via `pip inspect`)
- All declared external binaries with versions
- Language runtime versions
- CVE findings with severity scores
- License identifiers (via `pip show` or `license` field)

**Output formats:** JSON, TOML, or Markdown summary.

### 3.5 Environment Provisioning

Generate a `Dockerfile` per skill with all pre-installed tooling:

```dockerfile
# Generated for skill: security-auditor
FROM python:3.11-slim

# System binaries
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[security-auditor]"

# External tools
RUN npm install -g @semgrep/semgrep
RUN curl -sL https://github.com/grafana/k6/releases/download/v0.48.0/k6-v0.48.0-linux-amd64.tar.gz | tar -xz -C /usr/local/bin

WORKDIR /workspace
```

---

## 4. INTEGRATION POINTS

### 4.1 All Skills — `manifest.json` Dependency Declaration

Every skill in the ecosystem MUST declare dependencies in its `manifest.json`:

```json
{
  "name": "security-auditor",
  "dependencies": {
    "python_packages": ["semgrep>=1.50", "bandit>=1.7"],
    "binaries": ["semgrep", "git", "docker"],
    "runtimes": {
      "python": ">=3.10",
      "node": ">=18.0.0"
    },
    "pyproject_extras": ["security-auditor"]
  }
}
```

`verify-deps.py` reads this block before any skill code is imported or executed.

### 4.2 Skill Registry — Activation Gate

The `skill-registry` calls `verify-deps.py --skill <name>` before transitioning a skill from `REGISTERED` to `ACTIVE`. If the check returns non-zero exit code:
- The skill remains in `REGISTERED` state
- A dependency gap report is attached to the skill record
- The registry triggers `error-policy` with `action=install_or_halt`

### 4.3 Security Auditor — CVE Merge Gate

CVE findings from `dependency-resolver` feed directly into `security-auditor`:

- High/Critical CVEs in dependencies block merge gates
- The SBOM is attached to every security audit report
- Dependency vulnerabilities are treated as first-class findings (same severity scale as code vulnerabilities)

### 4.4 Error Policy — Fallback Trigger

When dependencies are missing, `dependency-resolver` emits a structured error to `error-policy`:

```json
{
  "error_code": "DEP_MISSING",
  "severity": "blocking",
  "target_skill": "security-auditor",
  "missing": {
    "binaries": ["semgrep"],
    "packages": ["bandit>=1.7"]
  },
  "recommended_action": "auto_install_packages_or_request_human_for_binaries",
  "auto_install_safe": true
}
```

`error-policy` decides:
- For Python packages: auto-install if `auto_install_safe=true` and source is PyPI
- For system binaries: ALWAYS flag for human approval; never auto-install

---

## 5. SAFETY RULES

| Rule | Enforcement |
|------|-------------|
| **NEVER allow a skill to run if any dependency is missing or version-incompatible** | `verify-deps.py` exits with code `1` before skill code executes; `skill-registry` blocks activation |
| **ALWAYS check for dependency updates weekly; flag outdated packages in session reports** | Weekly cron task writes to `outdated-report.json`; session startup appends flags to stdout |
| **NEVER rely on LLM's internal knowledge for CVE identification** | All CVE data sourced from OSV API and GitHub Advisory GraphQL; local cache is the single source of truth for the session |
| **ALWAYS cache CVE data locally to avoid API rate limits and enable offline operation** | 24-hour TTL cache in `/tmp/kimi-deps-cache/`; offline mode uses stale cache with `--offline` flag |
| **NEVER auto-install system-level binaries without human approval** | Binaries flagged as `requires_human: true` in reports; script exits with code `2` specifically for binary gaps |
| **ALWAYS include dependency check in session startup — fail fast before any code runs** | `.kimi/skills-loader.py` runs `verify-deps.py --skill <target>` as the very first import step |

---

## 6. WORKFLOW

### 6.1 Standard Session Startup

```
Session Start
    |
    v
[1] Read target skill manifest.json
    |
    v
[2] Extract declared dependencies (packages, binaries, runtimes)
    |
    v
[3] Check Python packages: pip list vs. required versions (PEP 440)
    |-- Missing or incompatible? --> Generate installation report
    |-- Python packages safe to auto-install? --> pip install (if --auto-install flag)
    |
    v
[4] Check external binaries: which <binary>, <binary> --version
    |-- Missing? --> Flag for human approval; exit code 2
    |
    v
[5] Check language runtimes: python --version, node --version
    |-- Missing? --> Flag for human approval; exit code 2
    |
    v
[6] CVE scan: query OSV API for all declared dependencies
    |-- Cache results locally (TTL 24h)
    |-- Update daily if cache stale
    |
    v
[7] Generate SBOM for the session
    |
    v
[8] Report: dependencies OK / missing / outdated / vulnerable
    |-- All OK? --> Skill executes
    |-- Any missing/vulnerable? --> Block execution, trigger error-policy
```

### 6.2 CVE Update Workflow (Daily Background)

```
Daily Trigger (or --cve-update flag)
    |
    v
[1] Load all manifests, extract (ecosystem, package, version) tuples
    |
    v
[2] Check cache freshness (mtime < 24h)
    |-- Fresh? --> Skip
    |
    v
[3] Build OSV batch query (max 1000 packages)
    |
    v
[4] POST to https://api.osv.dev/v1/querybatch
    |
    v
[5] Enrich with GitHub Advisory GraphQL (severity, CVSS, exploitability)
    |
    v
[6] Write to cache files; update last-updated timestamp
    |
    v
[7] Notify security-auditor of new findings
```

### 6.3 SBOM Generation Workflow

```
--sbom flag
    |
    v
[1] pip inspect --format=json (direct + transitive deps)
    |
    v
[2] Merge with manifest binary/runtime declarations
    |
    v
[3] Attach CVE findings from cache
    |
    v
[4] Attach license metadata (from pip show or license field)
    |
    v
[5] Output SPDX-2.3 JSON or CycloneDX 1.5 JSON
```

---

## 7. FILE STRUCTURE

```
dependency-resolver/
├── SKILL.md                          # This file
├── manifest.json                     # Skill self-manifest (dogfood)
├── scripts/
│   ├── verify-deps.py               # Main pre-flight verification script
│   ├── cve-update.py                # Background CVE cache updater
│   ├── sbom-generator.py            # SBOM SPDX/CycloneDX generator
│   └── docker-generator.py          # Per-skill Dockerfile generator
├── references/
│   ├── cve-sources.md               # OSV API & GitHub Advisory integration guide
│   ├── sbom-format.md               # SPDX-2.3 and CycloneDX 1.5 field mappings
│   └── manifest-schema.md           # Full manifest.json dependency block schema
├── templates/
│   ├── Dockerfile.template           # Jinja2 template for skill Dockerfiles
│   └── sbom-spdx.template          # SPDX JSON template
├── config/
│   └── default.toml                 # Default cache paths, API endpoints, TTLs
└── tests/
    ├── test_verify_deps.py
    ├── test_cve_update.py
    └── test_sbom_generator.py
```

---

## 8. API SPECIFICATION

### 8.1 verify-deps.py CLI

```
usage: verify-deps.py [-h] [--skill SKILL | --all] [--auto-install]
                      [--sbom] [--sbom-format {spdx,cyclonedx,markdown}]
                      [--cve-scan] [--cve-update] [--offline]
                      [--output-dir OUTPUT_DIR] [--verbose]

options:
  -h, --help            show this help message and exit
  --skill SKILL         Target skill name to verify
  --all                 Verify all skills in the ecosystem
  --auto-install        Auto-install missing Python packages (safe only)
  --sbom                Generate SBOM for target scope
  --sbom-format {spdx,cyclonedx,markdown}
                        SBOM output format (default: spdx)
  --cve-scan            Include CVE scan in verification report
  --cve-update          Force refresh of CVE cache before scanning
  --offline             Use only local cache; do not query APIs
  --output-dir OUTPUT_DIR
                        Directory for reports and SBOM output
  --verbose, -v         Enable verbose logging
```

**Exit Codes:**
| Code | Meaning |
|------|---------|
| `0` | All dependencies satisfied; no CVEs found (or --cve-scan not requested) |
| `1` | Missing or version-incompatible Python packages |
| `2` | Missing external binaries or language runtimes (requires human intervention) |
| `3` | CVEs found (with --cve-scan; still allows execution if error-policy permits) |
| `4` | Network error during CVE update (offline may fallback to stale cache) |
| `5` | Invalid manifest or configuration error |

### 8.2 Internal Python API

```python
from dependency_resolver import DependencyResolver

resolver = DependencyResolver(
    skills_dir="/mnt/agents/skills",
    cache_dir="/tmp/kimi-deps-cache",
    offline=False,
    auto_install=False,
)

# Verify single skill
report = resolver.verify_skill("security-auditor")
# report.ok: bool
# report.missing_packages: list[str]
# report.missing_binaries: list[str]
# report.outdated_packages: list[OutdatedInfo]
# report.cves: list[CVERecord]

# Generate SBOM
sbom = resolver.generate_sbom(format="spdx-json")

# Update CVE cache
resolver.update_cve_cache()
```

---

## 9. CONFIGURATION

`config/default.toml`:

```toml
[api]
osv_base_url = "https://api.osv.dev/v1"
github_graphql_url = "https://api.github.com/graphql"
github_token_env = "GITHUB_TOKEN"  # Required for GitHub Advisory GraphQL
request_timeout = 30
max_batch_size = 1000

[cache]
base_dir = "/tmp/kimi-deps-cache"
ttl_hours = 24
offline_fallback = true  # Use stale cache if API unreachable

[scan]
severity_threshold = "HIGH"  # HIGH, CRITICAL block execution; MEDIUM, LOW warn
cvss_block_score = 7.0
auto_install_safe = true     # Python packages only

[report]
output_dir = "/mnt/agents/output/dependency-resolver/reports"
session_report_name = "dependency-report.json"
weekly_outdated_name = "outdated-report.json"
```

---

## 10. INTEGRATION EXAMPLE

### skill-registry activation gate

```python
# In skill-registry/skill_loader.py
from dependency_resolver.scripts.verify_deps import DependencyResolver

def activate_skill(skill_name: str) -> ActivationResult:
    resolver = DependencyResolver()
    report = resolver.verify_skill(skill_name)
    
    if not report.ok:
        return ActivationResult(
            status="BLOCKED",
            reason="dependency_gap",
            report=report.to_dict(),
            next_action="trigger_error_policy"
        )
    
    if report.cves:
        # Feed to security-auditor
        security_auditor.ingest_dependency_cves(skill_name, report.cves)
    
    return ActivationResult(status="ACTIVE")
```

### security-auditor merge gate

```python
# In security-auditor/merge_gate.py
def check_dependencies(skill_name: str) -> GateResult:
    resolver = DependencyResolver()
    report = resolver.verify_skill(skill_name, cve_scan=True)
    
    critical_cves = [c for c in report.cves if c.severity in ("CRITICAL", "HIGH")]
    if critical_cves:
        return GateResult(
            passed=False,
            reason=f"{len(critical_cves)} critical/high CVEs in dependencies",
            findings=critical_cves
        )
    return GateResult(passed=True)
```

---

## 11. RESEARCH REFERENCES

| ID | Finding | Severity | Status |
|----|---------|----------|--------|
| IMP-4.1 | Zero dependency specifications across 30 claimed scripts | 8/10 | **VALID** — Closed by this skill via `pyproject.toml` and `manifest.json` dependency blocks |
| IMP-4.3 | Dependency Manager claims "CVE findings" with no OSV/NVD/GitHub Advisory connectivity | 9/10 | **CRITICAL** — Closed by this skill via live OSV API and GitHub Advisory GraphQL integration with mandatory local caching |

---

## 12. DEPENDENCIES (Self-Declared)

```json
{
  "python_packages": [
    "requests>=2.31",
    "packaging>=23.0",
    "toml>=0.10",
    "pydantic>=2.0",
    "typer>=0.9",
    "jinja2>=3.1"
  ],
  "binaries": ["python3", "pip"],
  "runtimes": {
    "python": ">=3.10"
  },
  "pyproject_extras": ["all"]
}
```

---

## 13. CHANGELOG

| Version | Date | Change |
|---------|------|--------|
| 4.0.0 | 2025-01-18 | Initial release. Pre-flight verification, OSV + GitHub Advisory CVE scanning, SBOM generation, Dockerfile provisioning, full ecosystem integration. |