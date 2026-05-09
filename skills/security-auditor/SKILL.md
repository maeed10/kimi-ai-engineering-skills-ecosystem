---
name: security-auditor
description: >
  Runs automated security analysis on agent-generated or existing codebase as a mandatory
  quality gate in the EXECUTE phase. Performs SAST (Semgrep, CodeQL, Bandit, ESLint security),
  dependency CVE scanning via live OSV and GitHub Advisory Database, STRIDE threat modeling
  from Architecture Design ADRs, insecure pattern detection, and merge gating. Trigger after
  Code Tester passes, before Refactoring Engine or Delivery. NEVER skip CVE scan even if
  SAST passes clean.
---

# security-auditor

## What it does
Runs automated security analysis on agent-generated or existing codebase before commit or merge.
Acts as a mandatory quality gate in the EXECUTE phase, blocking delivery for critical findings.
Performs **SAST** with multi-tool fallback, **dependency CVE scanning** against live vulnerability
databases (OSV, GitHub Advisory), **STRIDE threat modeling**, and insecure pattern detection.

## When to use
- After Code Tester passes and before Refactoring Engine or Delivery phase begins.
- When the agent generates new code files, modifies auth/payment/encryption modules, or introduces input handling.
- When ADRs from Architecture Design are available and a STRIDE threat model is required.
- Before any merge/promotion decision when Blast Radius Calculator flags high-risk files.
- When updating Documentation Synthesizer with security considerations.
- **Always** when `dependency-resolver` produces a manifest, SBOM, or lockfile — CVE scan is mandatory.

## Key capabilities
- **SAST** — Run Semgrep (general, primary), with multi-tool fallback: CodeQL → Bandit (Python) → ESLint security (JS/TS). All tools can run inside `sandbox-executor` isolation.
- **Dependency CVE scanning** — Query live OSV API and GitHub Advisory Database for vulnerabilities in declared dependencies. Read SBOM or manifest from `dependency-resolver`. Cache results locally; update daily.
- **Dependency vulnerability gate** — Run AFTER SAST but BEFORE merge decision. Block merge for CRITICAL CVEs (CVSS ≥ 9.0) with same blocking behavior as SAST critical findings.
- **STRIDE threat modeling** — Perform automated STRIDE analysis using ADR inputs from Architecture Design.
- **Insecure pattern detection** — Input validation flaws, auth bypass, injection risks, secret leakage.
- **Merge gating** — Block merge/promotion for critical SAST findings AND critical CVEs.
- **Structured reporting** — Produce JSON and Markdown reports with severity, CWE ID, CVE ID, file location, and remediation.

## Workflow

### 1. Receive and prepare code context
- Accept file paths, diffs, or full codebase references.
- ALWAYS request the full file content for any file in the scan scope; diffs alone are insufficient.
- Classify each file as `agent-generated` or `human-written` and record this in the report.

### 2. Prioritize files by risk
- Read Blast Radius Calculator output if available.
- Sort scan queue: auth → payment → encryption → input handling → data access → other.
- Mark prioritized files with `priority: critical` in the scan manifest.

### 3. Verify SAST tool availability
- Check Semgrep binary exists (via `dependency-resolver` or `shutil.which`).
- If Semgrep missing, record error and proceed to fallback tools.
- Multi-tool fallback chain:
  1. **Semgrep** — primary general-purpose SAST
  2. **CodeQL** — deep semantic analysis (requires pre-built database or `--codeql-create-db`)
  3. **Bandit** — Python-specific security linter
  4. **ESLint security** — JS/TS-specific security plugin
- **ALWAYS run SAST tools inside `sandbox-executor`** when available. SAST processes untrusted code; sandbox isolation is mandatory.

### 4. Run SAST tools
- Run Semgrep with the rulesets in `references/semgrep-rules.md`.
- If Python files exist and Semgrep/CodeQL unavailable or as supplement, run Bandit (`bandit -r . -f json`).
- If JS/TS files exist and Semgrep/CodeQL unavailable or as supplement, run ESLint with security plugins (`eslint-plugin-security`).
- NEVER execute the code being analyzed; static analysis only.
- ALWAYS scan the FULL file, never just the diff, because vulnerabilities exist in surrounding context.

### 5. Run dependency CVE scan
- **NEVER skip this step even if SAST passes clean.** Dependencies are a separate attack surface.
- Read SBOM or dependency manifests from `dependency-resolver` output location.
- Supported manifests: `package.json`, `package-lock.json`, `requirements.txt`, `Pipfile.lock`, `Cargo.toml`, `Cargo.lock`, `go.mod`, `go.sum`, `pom.xml`, `build.gradle`, CycloneDX/SPDX SBOM JSON.
- Query **OSV API** (`api.osv.dev/v1/querybatch`) for declared dependencies.
- Query **GitHub Advisory Database** (`api.github.com/advisories`) for additional CVSS context and descriptions.
- Cache results locally (default 24h TTL); override with `--no-cache` or `--clear-cache`.
- **NEVER rely on LLM internal knowledge for CVE identification.** Always query live database.

### 6. Run STRIDE threat modeling (if ADR available)
- Read Architecture Design ADRs from the agreed location (e.g., `docs/adrs/`).
- For each ADR describing a new component, data flow, or trust boundary:
  - Map assets and data flows.
  - Apply STRIDE categories: Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege.
  - Record threats, mitigations, and residual risk in `references/stride-template.md` format.

### 7. Aggregate findings into structured report
- Merge SAST, CVE, and STRIDE results into one consolidated report.
- Each finding MUST include:
  - `severity`: critical / high / medium / low
  - `cwe_id`: CWE identifier or "CWE-UNKNOWN"
  - `cve_id`: CVE identifier (for dependency findings) or "N/A"
  - `file`: absolute or repo-relative path
  - `line`: line number(s)
  - `tool`: Semgrep / CodeQL / Bandit / ESLint / OSV / GitHub Advisory / STRIDE
  - `rule_id`: rule or STRIDE category
  - `message`: concise description
  - `remediation`: specific actionable fix
  - `source`: agent-generated | human-written
- Produce `security-report.json` and `security-report.md`.
- Produce separate `cve-report.json` and `cve-report.md` from `scripts/run-cve-scan.py`.

### 8. Merge gate decision
- **Critical SAST findings** (`severity: critical`) → block delivery, escalate to human, STOP.
- **Critical CVEs** (`CVSS >= 9.0`) → block delivery, escalate to human, STOP.
- **High findings** (`severity: high` or `CVSS >= 7.0`) → block merge, escalate to human, STOP unless explicitly waived.
- **Medium/Low findings** → generate fix suggestions in `security-fixes.md`, continue with warnings, DO NOT auto-apply fixes.
- If no critical/high findings from **both SAST and CVE scans** → permit continuation to Refactoring Engine or Delivery.

### 9. Update Documentation Synthesizer
- Feed the security report (summary + critical/high findings) to Documentation Synthesizer.
- Ensure security considerations section is updated in relevant docs.

## Safety highlights
- NEVER auto-fix security vulnerabilities without explicit human review. Flag only.
- NEVER suppress findings based on "it's just test code", "it's temporary", or "it's a prototype".
- ALWAYS run SAST on the FULL file, not just the diff. Vulnerabilities exist in context.
- ALWAYS generate a structured security report with severity, CWE ID, file location, and remediation guidance.
- NEVER execute potentially malicious code during analysis. Static analysis only.
- ALWAYS distinguish between agent-generated code and human-written code in findings.
- ALWAYS escalate critical and high findings to human review before any merge or delivery.
- NEVER downgrade severity based on perceived exploitability; use the tool's rating.
- ALWAYS include both JSON and Markdown report outputs for machine and human consumption.
- NEVER run security tools against untrusted remote endpoints or URLs; scan local files only.
- **NEVER skip CVE scan even if SAST passes clean.** Dependencies are a different attack surface.
- **NEVER rely on LLM internal knowledge for CVE identification.** Always query live OSV / GitHub Advisory Database.
- **ALWAYS run SAST tools inside sandbox** (`sandbox-executor`) when available. They process untrusted code.
- **NEVER suppress a critical CVE finding without human review and documented exception.**

## Integration with other skills

| Skill | Direction | Integration point |
|-------|-----------|-------------------|
| Code Tester | Input | Runs **after** Code Tester passes. Receives list of files under test. |
| Architecture Design | Input | Reads ADRs for STRIDE threat model inputs. |
| Blast Radius Calculator | Input | Reads risk scores to prioritize scan queue. |
| dependency-resolver | Input | Reads SBOM / manifests for CVE scanning. Tool location hints for SAST binaries. |
| sandbox-executor | Execution | Runs Semgrep, CodeQL, Bandit, ESLint inside isolated container. |
| Refactoring Engine | Output | Blocks transformation if critical/high findings exist. Pre-transform risk assessment. |
| Delivery | Output | Blocks Style Enforcer and Address PR Comments if critical findings exist. |
| Documentation Synthesizer | Output | Feeds security findings for security section updates. |

## References
- `references/semgrep-rules.md` — Curated Semgrep rules for common vulnerability classes.
- `references/stride-template.md` — Template for recording STRIDE threat model results.
- `references/cwe-mapping.md` — Mapping from tool rule IDs to CWE identifiers.
- `references/cve-sources.md` — OSV API, GitHub Advisory Database, SBOM formats, cache behavior, CVSS thresholds.

## Scripts
- `scripts/run-sast.py` — Multi-tool SAST runner (Semgrep → CodeQL → Bandit → ESLint security) with sandbox integration and structured JSON/Markdown output.
- `scripts/run-cve-scan.py` — Dependency vulnerability scanner using OSV API and GitHub Advisory Database. Supports SBOM and multiple manifest formats. Local cache with daily TTL. Blocks merge for critical CVEs (CVSS ≥ 9.0).
