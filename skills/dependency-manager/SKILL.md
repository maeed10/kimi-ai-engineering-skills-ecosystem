---
name: dependency-manager
description: Analyzes package manifests (package.json, requirements.txt, go.mod, Cargo.toml) for outdated dependencies, CVEs, license conflicts, and version incompatibilities. Blocks execution if critical vulnerabilities or GPL contamination detected. Feeds into Blast Radius (dependency changes = high risk) and Architecture Design (outdated deps = tech debt).
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# Dependency & Environment Manager

Systematic dependency risk analysis, vulnerability auditing, license governance, and supply-chain security for software projects. Operates across all major package ecosystems with deterministic gating and SBOM compliance.

## Overview

Modern software is assembled, not authored. The average Node.js application depends on over 1,000 transitive packages; Python and Go projects routinely exceed 100 direct dependencies. Each dependency introduces trust, legal, and operational risk. This skill provides a rigorous, multi-phase framework for analyzing package manifests, surfacing vulnerabilities, enforcing license policy, and blocking high-risk changes before they reach production.

Key research foundations:
- Snyk, Dependabot, Renovate, and OWASP Dependency-Check form the dominant SCA tool landscape. Reachability analysis reduces noise by up to 97% by tracing whether vulnerable functions are actually callable [^404^].
- The XZ Utils backdoor (CVE-2024-3094, CVSS 10.0) demonstrated that social engineering campaigns can compromise even foundational system libraries — and standard static analysis would not have caught it [^395^].
- No single vulnerability database has complete coverage: NVD covers 89%, OSV 93%, GHSA 87%, but their union reaches 98% [^267^].
- Over 53% of audited codebases contain open-source license conflicts, typically involving GPL contamination [^280^].
- SBOMs are now mandated by US EO 14028, EU Cyber Resilience Act (enforced 2026-2027), FDA medical devices, and US Army directives [^269^][^271^][^275^].
- Lockfiles (package-lock.json, Cargo.lock, poetry.lock) ensure deterministic, reproducible builds and must be committed for applications [^276^][^268^].
- AI-powered migration tools have demonstrated 6x speedups for major version upgrades (e.g., Python 3.8 to 3.12 in one week versus six) [^265^].
- Semantic Versioning (SemVer) governs compatibility: `^4.18.0` fixes MAJOR and allows MINOR/PATCH; `~4.17.21` fixes MAJOR+MINOR; exact pins ensure reproducibility [^387^].
- npm uses tree-based resolution with hoisting, which can create phantom dependencies — packages importing dependencies they do not directly declare [^387^].

For detailed CVE database comparison, SBOM format guidance, and tool integration specifics, see [references/cve-databases.md](references/cve-databases.md).

## Operational Guidelines & Rules

### Always
- Generate a fresh SBOM in CycloneDX and SPDX formats before every dependency analysis session. SBOMs are the baseline for traceability.
- Scan using the union of at least two vulnerability databases (NVD + OSV, or NVD + GHSA, or all three). Single-source scanning misses 11-13% of known CVEs [^267^].
- Verify lockfile presence and integrity before any dependency analysis. A missing lockfile is a `BLOCKING` finding for applications (acceptable for published libraries with caveats).
- Perform reachability analysis when available — flag only vulnerabilities in code paths the application can actually execute.
- Check every dependency against the organizational license allow-list. Flag GPL contamination, ambiguous licenses, and missing license metadata.
- Cross-reference dependency changelogs and release notes before recommending any upgrade. Breaking changes in MAJOR versions must be explicitly documented.
- Report dependency age as a risk factor: unupdated for >12 months is a warning, >24 months is a critical tech-debt flag.
- Generate a Blast Radius assessment for any proposed dependency change. Dependency changes affect compilation, runtime behavior, transitive closure, and CI pipelines.
- Produce a machine-readable report (JSON/SARIF) alongside human-readable summaries for CI/CD integration.
- Prefer ecosystem-native tools first (npm audit, cargo audit, pip-audit, go vulncheck) before cross-platform scanners for speed and precision.

### Never
- Auto-update, auto-merge, or auto-apply dependency changes without human review and CI validation. The agent proposes; humans approve.
- Ignore or dismiss a CVE with CVSS >= 7.0 without explicit documented justification and user sign-off. Critical and high-severity vulnerabilities are blocking.
- Generate or execute dependency changes without first generating an SBOM. SBOM generation is mandatory, not optional.
- Recommend a dependency with known maintainer-account compromise, typosquatting history, or behavioral red flags (network calls, filesystem access, obfuscated code).
- Trust a single vulnerability database as authoritative. NVD alone misses 11% of known vulnerabilities [^267^].
- Skip license scanning for "internal" or "test-only" dependencies. GPL contamination in test frameworks or build tools can still create legal exposure.
- Use `npm install` in CI pipelines. Always use `npm ci` or equivalent lockfile-strict install commands for reproducible builds [^276^].
- Propose upgrades across multiple MAJOR versions in a single batch. Upgrade one MAJOR boundary at a time with intermediate validation.
- Execute dependency commands (install, update, audit) without first inspecting and understanding the current manifest and lockfile state.
- Downplay supply-chain risk by citing "we're not a target." The XZ backdoor affected every Linux distribution; indiscriminate impact is the norm [^395^].

## Tool Ecosystem & Integration Matrix

| Tool | Role | Languages | Key Strength | Integration Notes |
|------|------|-----------|--------------|-------------------|
| npm audit / pip-audit / cargo audit | Native scanner | Node, Python, Rust | Zero-config, fast | Run first; baseline findings |
| Snyk | Commercial SCA | 10+ ecosystems | Reachability, license, SBOM | Enterprise policy enforcement |
| Dependabot | GitHub-native | 30+ ecosystems | Auto-PR, zero setup | GitHub only; no SBOM |
| Renovate | Universal updater | 60+ managers | Broad support, automerge | Pair with Snyk for security |
| OWASP Dependency-Check | OSS scanner | Java, .NET, Node, Python, Ruby | NVD-based, SBOM, license | CI plugin; slower scans |
| Trivy | Multi-scanner | All major | Vuln + misconfig + secret | Container + repo scanning |
| FOSSA | License governance | All | 99.8% license detection accuracy | CI gate for license policy |
| Syft / cdxgen | SBOM generation | All | CycloneDX-native | Integrate into build pipeline |
| Socket | Behavioral analysis | npm | Detects malicious package behavior | Early warning for typosquats |
| osv.dev API | Public vuln DB | All (OSV ecosystem) | PURL-based, precise | Free API for custom tooling |

**Tool selection strategy by team profile**:
- **GitHub-only teams**: Dependabot for zero-config alerts + OWASP Dependency-Check for license/SBOM. No additional cost, covers 80% of needs.
- **Multi-platform teams**: Renovate for dependency updates (broader ecosystem, automerge) + Snyk or Trivy for security scanning with reachability analysis.
- **Enterprise teams**: Snyk, Mend, or JFrog Xray for centralized governance, policy enforcement, and compliance reporting across all repositories.

**Academic adoption data**: npm audit (34.19%) and Dependabot (32.26%) are the most commonly adopted tools among npm developers, with Snyk at 12.26% and OWASP at 5.81% [^355^]. Native tools dominate because they require zero configuration.

## Workflow: Five-Phase Dependency Analysis

### Phase 1 — Scan

**Objective**: Discover and inventory all dependencies across the project.

1. Identify all package manifests in the repository: `package.json`, `requirements.txt`, `go.mod`, `Cargo.toml`, `Pipfile`, `poetry.lock`, `yarn.lock`, `Gemfile`, `composer.json`, `pom.xml`, etc.
2. Verify lockfile presence and integrity. A missing lockfile is a `BLOCKING` finding for applications (acceptable for published libraries with caveats).
3. Run ecosystem-native scans: `npm audit`, `pip-audit`, `cargo audit`, `go vulncheck`. Record raw output with timestamps.
4. Generate SBOM in CycloneDX (JSON) and SPDX (TV/JSON) formats using Syft, cdxgen, or Trivy. Attach to session artifacts with SHA-256 hashes.
5. Extract dependency tree depth, transitive count, and maximum depth. Deep trees (>5 levels) flag for dependency simplification.
6. Check for phantom dependencies — packages importing transitive deps without direct declaration. These break when tree topology changes [^387^].

**Output**: Dependency inventory, SBOM, native scan baseline, lockfile status, phantom dependency report.

### Phase 2 — Audit

**Objective**: Cross-reference discovered dependencies against vulnerability and license databases.

1. Query union of vulnerability databases: NVD (CPE identifiers), OSV (PURL identifiers), GHSA (human-reviewed ranges). Map findings by package name, version, and CVSS score.
2. Run license scan: extract SPDX identifiers from SBOM, flag GPL/AGPL/SSPL in proprietary contexts, flag missing or ambiguous licenses.
3. Perform reachability analysis if tooling supports it (Snyk, Endor Labs, Rafter). Mark reachable vs. unreachable CVEs separately. Reachability can reduce noise by up to 97% [^404^].
4. Check for supply-chain red flags: typosquatting risk (e.g., `crossenv` vs `cross-env`), recent maintainer changes, behavioral anomalies (Socket-style analysis of network calls and filesystem access).
5. Cross-reference with advisory publication dates. GHSA often publishes 10+ days before NVD; prioritize GHSA for recency [^272^]. During the delay window, NVD only has imprecise CPE mappings.

**Output**: CVE list with CVSS, exploitability, reachability status; license conflict report; supply-chain risk flags.

### Phase 3 — Score

**Objective**: Compute composite risk scores per dependency and per project.

**Scoring formula**:
| Factor | Weight | Data Source |
|--------|--------|-------------|
| Max CVSS (reachable) | 40% | NVD + OSV + GHSA |
| Days since last update | 20% | Registry API |
| Transitive depth | 15% | Dependency tree |
| License risk | 15% | SPDX classification |
| Supply-chain flags | 10% | Socket / manual review |

**Reachability weighting**: When reachability analysis is available, reachable CVEs receive their full CVSS weight. Unreachable CVEs are downweighted by 50% — they are still documented but do not drive the aggregate score as aggressively. This reflects research showing that up to 97% of CVE alerts are noise when the vulnerable function is not in the application's call graph [^404^].

**Severity thresholds**:
- CRITICAL: CVSS >= 9.0, or GPL contamination in proprietary code, or confirmed active exploitation
- HIGH: CVSS 7.0-8.9, or dependency unmaintained >24 months, or reachable vulnerability with PoC
- MEDIUM: CVSS 4.0-6.9, or dependency unmaintained >12 months, or license ambiguity
- LOW: CVSS 0.1-3.9, or cosmetic / non-security updates

**Output**: Scored dependency list, project aggregate risk score, prioritized remediation queue.

### Phase 4 — Report

**Objective**: Communicate findings to humans and CI/CD systems.

1. Generate human-readable markdown report: executive summary, detailed findings per dependency, upgrade recommendations, license conflicts, SBOM location.
2. Generate machine-readable output: SARIF for CVEs, SPDX for license compliance, CycloneDX for SBOM exchange. Machine-readable outputs enable CI pipeline integration and automated policy enforcement.
3. Feed findings to Blast Radius: every dependency change triggers a high-risk path analysis. Document affected transitive packages, compilation changes, test surface, deployment impact, and environment-specific risks (staging vs production configurations).
4. Feed outdated dependencies to Architecture Design as tech-debt items. Catalog them by subsystem with estimated migration effort, breaking change risk, and priority based on security exposure.
5. For AI-assisted migration candidates (Python major versions, framework upgrades, deprecated library replacements), generate a migration plan with rollback strategy. AI migration tools have shown 6x speedups on major version upgrades, but human review remains mandatory [^265^].
6. Include a changelog summary for each recommended upgrade: what changed, why it matters, and what could break. This reduces the activation energy for maintainers to approve updates.

**Output**: Multi-format report, Blast Radius assessment, Architecture Design tech-debt feed.

### Phase 5 — Gate

**Objective**: Block or approve changes based on scored risk.

**Blocking conditions** (execution stops; human override required):
- Any reachable CVE with CVSS >= 7.0 and known exploit / PoC
- GPL/AGPL/SSPL contamination in a proprietary commercial context
- Missing lockfile for an application deployment
- Dependency with confirmed maintainer compromise or active typosquatting campaign
- SBOM generation failure or tampered SBOM hash

**Warning conditions** (reported, non-blocking):
- CVE CVSS 4.0-6.9, unreachable
- Dependency unmaintained 12-24 months
- License ambiguity (no SPDX identifier detected)
- Transitive tree depth >5 levels

**Approval conditions** (proceed with documentation):
- All reachable CVEs < CVSS 7.0, with remediation timeline
- Clean license scan or documented exceptions
- SBOM generated and hash-verified
- Upgrade plan includes rollback strategy and CI validation

**Output**: Gate decision (PASS / WARN / BLOCK), documented rationale, required actions for remediation.

## Safety & Security Boundaries

Safety constraints are absolute, non-negotiable, and enforced without exception fatigue.

### Prohibited Actions
- Auto-applying dependency patches or upgrades to any branch without human review.
- Ignoring CVSS >= 7.0 without explicit user acknowledgment and documented risk acceptance.
- Installing packages from unverified sources, private registries without authentication, or tarball URLs without integrity verification.
- Generating or modifying lockfiles during automated scans (read-only analysis only).
- Recommending packages with behavioral red flags (network calls in build scripts, obfuscated minified code, filesystem traversal).

### Required Practices
- Validate all findings against the union of NVD, OSV, and GHSA. Never rely on a single source.
- Include security considerations in every dependency recommendation: attack surface, trust boundaries, data flows, defense in depth.
- Generate SBOMs before and after any dependency change. Use VEX (Vulnerability Exploitability eXchange) to communicate exploitability status.
- Apply query count budgets and CI gating: dependency changes must pass the full test suite, SAST, and DAST pipeline.
- Maintain an organizational allow-list/deny-list for licenses and package authors. Block-list takes precedence.

## Supply-Chain Attack Awareness

The XZ Utils backdoor (CVE-2024-3094) demonstrated that even foundational libraries with decades of trust can be compromised through sustained social engineering. Key lessons:
- **Behavioral analysis matters**: Standard CVE scanning would not have caught XZ because it was not in any database until after discovery. Tools like Socket analyze what packages actually do.
- **Performance anomalies are signals**: The backdoor was discovered because an engineer noticed a 500ms SSH delay. Monitor CI and runtime performance regressions.
- **Maintainer health is a factor**: Evaluate bus factor, commit frequency, and foundation backing when selecting dependencies.
- **Lockfiles are not enough**: Lockfiles prevent version drift but do not prevent malicious code in a pinned version. Behavioral analysis is the second line of defense.

Additional attack vectors to monitor:
- **Typosquatting / dependency confusion**: Over 500 typosquatted packages were identified on PyPI in a single 2023 campaign [^356^]. Attackers publish packages with names nearly identical to popular ones (e.g., `crossenv` vs `cross-env`, `reqeusts` vs `requests`).
- **Compromised maintainer accounts**: ua-parser-js (2021, 8M weekly downloads) and event-stream (2018, Copay Bitcoin wallet targeting) demonstrate scale of impact.
- **Malicious release tarballs**: The XZ backdoor was hidden in release tarballs, not the Git repository. Verify source-to-binary provenance with SLSA attestations where available.
- **Build script injection**: Malicious `postinstall` or `preinstall` hooks execute during dependency installation with full user privileges. Review all lifecycle scripts in new dependencies.

**Detection strategy beyond CVE databases**: Standard SCA tools check against known vulnerability databases, which means they catch typosquats only after someone reports them. Behavioral analysis tools (Socket, Phylum) analyze package behavior in real-time: network connections, filesystem modifications, obfuscated code, and unusual build steps. These tools provide early warning before a package enters any CVE database.

## Lockfile & Reproducibility Standards

Lockfiles ensure deterministic, reproducible builds by recording exact dependency versions, integrity hashes, and resolved URLs [^276^][^268^].

| Lockfile | Ecosystem | Key Function |
|----------|-----------|--------------|
| `package-lock.json` | npm/Node.js | Records exact versions, resolved URLs, integrity hashes of entire dependency tree |
| `Cargo.lock` | Rust/Cargo | Describes exact dependency versions at time of successful build |
| `poetry.lock` | Python/Poetry | Exact resolution of all dependencies with content hashes |
| `yarn.lock` | Yarn | Similar to package-lock.json with yarn-specific metadata |
| `go.sum` | Go | Cryptographic checksums of module content for verification |

**Critical practices**:
- Commit lockfiles for applications; never commit for libraries (with exceptions for CLI tools that need deterministic installs).
- Use `npm ci` in CI/CD pipelines rather than `npm install` — it reads the lockfile, is faster, and fails if the lockfile is out of sync.
- Audit lockfiles for security continuously; a compromised lockfile is a supply-chain attack vector.
- For npm libraries published to the registry, lockfiles are NOT published. Consumers get versions resolved from `package.json` ranges. Pin exact versions in `package.json` if deterministic consumer installs are required.
- Cargo recommends committing `Cargo.lock` for binaries but NOT for libraries, because a library should not deterministically recompile for all users [^268^].

## SemVer & Dependency Resolution

Semantic Versioning (SemVer) governs compatibility expectations across ecosystems [^387^]:
- `^4.18.0` — Fixed MAJOR, allows MINOR and PATCH (up to but not including 5.0.0)
- `~4.17.21` — Fixed MAJOR and MINOR, allows PATCH only
- `4.18.0` — Exact version only
- `>=4.0.0` — That version and higher (risky for automatic updates)

**Resolution mechanics**:
- npm uses tree-based resolution with hoisting. If multiple packages depend on the same version of a library, it installs once at the top-level `node_modules`. Different versions cause duplicates in nested directories.
- **Phantom dependencies** arise from hoisting — a package may import a dependency it does not directly declare, leading to breakages when the dependency tree changes.
- Cargo, Poetry, and npm all resolve SemVer constraints using constraint satisfaction, but algorithms differ. Cargo uses a SAT-like resolver; npm uses tree-based resolution.

**Mitigation**: Explicitly declare all direct dependencies. Never rely on transitive packages being hoisted to top-level.

## Integration with Other Skills

| Skill | Direction | Data |
|-------|-----------|------|
| Blast Radius | Feed INTO | Dependency changes = high-risk path; transitive impact assessment |
| Architecture Design | Feed INTO | Outdated dependencies cataloged as tech-debt with migration effort estimates |
| Architecture Design | Feed FROM | Current dependency versions inform technology selection and framework compatibility |
| Security Auditor | Feed INTO | CVE findings, license conflicts, SBOMs for security review sessions |
| CI/CD Engineer | Feed INTO | SARIF/SPDX/CycloneDX outputs for pipeline gating and compliance dashboards |

## SBOM & Compliance Requirements

SBOM generation is mandatory, not optional. Compliance drivers:
- **US EO 14028**: All federal software procurement requires SBOMs [^270^].
- **CISA 2025 Guidance**: Three-tier maturity model with Component Hash, License, Tool Name as new required elements [^269^].
- **EU Cyber Resilience Act**: Effective 2026-2027; SBOMs required for all "products with digital elements" [^271^][^279^].
- **FDA Medical Devices**: SBOMs required for cyber devices since March 2023 [^279^].
- **US Army Directive (2024)**: Mandates SBOMs in most new software contracts effective February 2025 [^275^].

**SBOM Contents** (CISA baseline): Supplier name, Component name, Version, Unique identifiers (PURL, CPE, SWID), Cryptographic hash, Dependency relationships, License information [^274^].

**Dual-format generation**: Produce both CycloneDX (security-focused, compact, ECMA-424 standard) and SPDX (compliance-focused, ISO/IEC 5962:2021) for maximum compatibility [^405^].

**VEX companion documents**: Use VEX alongside SBOMs to communicate exploitability status. When a dependency has a CVE but your code does not use the vulnerable function, VEX documents "Not affected" with "vulnerable_code_not_in_execute_path" justification. This reduces noise for downstream consumers.

Gartner predicts 60% of organizations building critical infrastructure software will mandate SBOMs by 2025, up from less than 20% in 2022 [^274^].

---

**Document version:** 1.0 | **Last updated:** April 2026 | **Sources:** NVD, OSV, GHSA, OWASP, CISA, SBOM tool ecosystem analysis, supply-chain security research


## Context Management & Token Budget

This skill operates within Kimi K2.6 CLI's **262,100-token context window**.
Follow these principles for efficient token usage:

- **Progressive disclosure**: Load `references/` content only when needed. SKILL.md
  stays metadata-only (~500-700 tokens); full detail loads on-demand.
- **Budget awareness**: Typical skill activation costs ~5,000-8,000 tokens. Target
  keeping active skill content under **18,000 tokens** (3-skill average, ~6.9% of
  262.1K context). Hard ceiling: **25,000 tokens** (~9.5% of context).
- **Deactivate when done**: When this skill's phase completes, the Orchestrator
  deactivates it to free budget for the next phase.
- **Frugality over completeness**: Prefer targeted queries over broad analysis.
  Use Brownfield Intelligence's SQLite index or Graphify's graph for structural
  lookups instead of loading entire codebases into context.
