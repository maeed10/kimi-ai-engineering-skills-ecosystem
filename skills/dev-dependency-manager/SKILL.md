---
name: dev-dependency-manager
description: Developer-facing dependency analyzer that detects outdated packages, security vulnerabilities, license conflicts, and dependency bloat. Use when updating dependencies, responding to CVEs, resolving version conflicts, auditing licenses, or maintaining lock files. Integrates with npm audit, safety, cargo audit, go vulncheck, and OSV.
---

# dev-dependency-manager

## Overview

Analyzes, updates, and secures project dependencies across all major software ecosystems. Detects outdated packages, vulnerability exposures, license conflicts, and dependency bloat. Generates update recommendations with impact analysis, semver compatibility checks, and automated report generation in Markdown, JSON, or SARIF.

**Ecosystems supported**: Node.js (npm/Yarn/pnpm), Python (pip/poetry/uv), Rust (Cargo), Go (modules), Ruby (Bundler), PHP (Composer), Java (Maven/Gradle), .NET (NuGet).

---

## Workflow Decision Tree

```
User asks about dependencies
|
├── "Outdated packages / updates needed"
│   └── → Outdated Detection → Update Recommendations → Impact Analysis
│
├── "Security vulnerability / CVE / audit"
│   └── → Vulnerability Scanning → Emergency Override (if needed) → Update → Verify
│
├── "License compliance / contamination"
│   └── → License Audit → Identify Conflicts → Recommend Replacements
│
├── "Dependency tree too large / slow install"
│   └── → Bloat Detection → Deduplication → Remove Unused
│
├── "Version conflict / diamond dependency"
│   └── → Parse Lock File → Identify Conflicting Requirements → Resolution Strategy
│
└── "Lock file mismatch / reproducible build issue"
    └── → Lock File Maintenance → Regenerate → Verify Consistency
```

---

## Core Capabilities

### 1. Outdated Detection

**When to use**: Dependencies have not been updated in months, CI flags deprecation warnings, or user explicitly asks to refresh packages.

**Approach**:
1. Identify ecosystem by manifest files (`package.json`, `requirements.txt`, `Cargo.toml`, etc.).
2. Use native tooling to list outdated packages:
   - **npm**: `npm outdated`
   - **pip**: `pip list --outdated` or `pip-audit`
   - **poetry**: `poetry show --outdated`
   - **Cargo**: `cargo outdated` (requires `cargo-outdated`)
   - **Go**: `go list -u -m all`
   - **Bundler**: `bundle outdated`
   - **Composer**: `composer outdated`
   - **Maven**: `mvn versions:display-dependency-updates`
   - **Gradle**: `./gradlew dependencyUpdates`
3. Cross-reference with `scripts/analyze_dependencies.py` for a unified view.
4. Evaluate semver bump type (patch / minor / major) for each outdated package.

**Breaking change assessment**:
- **Patch**: Typically safe. Review changelogs for security backports.
- **Minor**: Usually safe for well-maintained packages. Check for new feature deprecations.
- **Major**: High risk. Read migration guides, check for API removals, run full test suite.

**Transitive impact**: Use `npm ls`, `cargo tree`, `pipdeptree`, or `bundle viz` to see which direct dependencies pull in the outdated transitive package. If multiple direct deps require different versions, apply the Conflict Resolution Strategy.

---

### 2. Vulnerability Scanning

**When to use**: CVE disclosed in upstream dependency, security audit requested, pre-release checklist, or compliance requirement.

**Approach**:
1. Run ecosystem-native audit tool:
   - **npm/Yarn/pnpm**: `npm audit`, `yarn npm audit`, `pnpm audit`
   - **Python**: `pip-audit`, `safety check`, `osv-scanner`
   - **Rust**: `cargo audit`
   - **Go**: `govulncheck ./...`
   - **Ruby**: `bundler-audit`
   - **PHP**: `composer audit`
   - **Java**: OWASP Dependency-Check, Snyk, Sonatype
   - **.NET**: `dotnet list package --vulnerable`
2. Run `scripts/analyze_dependencies.py --check-vulns --format sarif` for OSV cross-ecosystem scanning.
3. Map every vulnerability to a fixed version.
4. If fixed version is within current semver range: refresh lock file only.
5. If fixed version requires major bump or is outside range: evaluate breaking changes and test impact.

**Emergency CVE Response (critical / high severity)**:
1. Identify minimal fixed version from advisory.
2. Check if `overrides`, `resolutions`, `replace`, `dependencyManagement`, or `force` can temporarily pin the safe version without waiting for upstream.
3. Apply override.
4. Run full test suite + integration tests.
5. Create ticket to remove override and upgrade properly.
6. Document in incident log.

**Severity filtering**:
- `critical`: CVSS >= 9.0 or actively exploited. Immediate response required.
- `high`: CVSS 7.0–8.9. Fix within current sprint.
- `moderate`: CVSS 4.0–6.9. Schedule in next maintenance window.
- `low`: CVSS < 4.0. Track, fix opportunistically.

---

### 3. Update Recommendations

**When to use**: After detecting outdated packages or vulnerabilities, generate a concrete update plan.

**Approach**:
1. For each outdated/vulnerable package, determine target version:
   - **Security fix**: minimum patched version.
   - **Feature need**: latest minor in current major.
   - **Tech debt reduction**: latest stable major (with migration plan).
2. Analyze semver compatibility:
   - **Patch** (`1.2.3` → `1.2.4`): Low risk. Apply directly.
   - **Minor** (`1.2.3` → `1.3.0`): Medium risk. Review deprecations. Run tests.
   - **Major** (`1.2.3` → `2.0.0`): High risk. Read migration guide. Plan phased rollout.
3. Check transitive impact:
   - Will upgrading this package force upgrades in other dependencies?
   - Does the new version add new transitive deps (bloat risk)?
   - Are there peer dependency implications (Node.js)?
4. Generate update batch:
   - Group independent patch updates together.
   - Isolate major updates into separate PRs.
   - Update lock file after each batch.

**Report generation**:
```bash
python scripts/analyze_dependencies.py --format markdown --output UPDATE_PLAN.md
```

---

### 4. Impact Analysis

**When to use**: Before applying any non-patch update, or when a user asks "will this break anything?"

**Approach**:
1. **Static analysis**:
   - For typed languages (Go, Rust, Java, .NET): compile after update. Type errors surface breaking API changes.
   - For dynamic languages (Python, Ruby, Node.js): use `mypy`, `pyright`, `sorbet`, or TypeScript compiler.
2. **Test coverage**:
   - Run unit tests: `pytest`, `jest`, `cargo test`, `go test`, `rspec`, `phpunit`, `mvn test`, `dotnet test`.
   - Run integration / E2E tests if package is used in critical paths.
   - Check code coverage for areas touching the dependency.
3. **Behavioral changes**:
   - Search changelog for "BREAKING", "DEPRECATED", "REMOVED".
   - Check for runtime behavior changes (default values, timing, encoding).
   - For Node.js: check `engines` field compatibility.
4. **Rollback plan**:
   - Ensure lock file is committed before update.
   - Tag release before merge.
   - Prepare revert command.

---

### 5. License Audit

**When to use**: Compliance review, open-source distribution preparation, acquisition due diligence, or GPL contamination concern.

**Approach**:
1. Identify licenses for all direct and transitive dependencies.
   - Node.js: `license-checker --summary`
   - Python: `pip-licenses`
   - Rust: `cargo license`
   - Go: `go-licenses`
   - Java: Maven `license-maven-plugin`
   - Ruby: `bundler-licenses` or `license_finder`
2. Flag problematic licenses:
   - **Copyleft (GPL-2/3, AGPL)**: May require open-sourcing derivative work.
   - **Weak copyleft (LGPL, MPL, EPL, CDDL)**: Boundaries matter; dynamic linking vs. static linking.
   - **Proprietary / custom**: Review terms of use.
3. Identify conflicts:
   - Mixing GPL-2 with GPL-3 incompatible code.
   - Proprietary code statically linking GPL libraries.
   - AGPL in server-side contexts.
4. Recommend replacements for copyleft-contaminated paths if needed.
5. Document findings in `LICENSE_AUDIT.md`.

---

### 6. Bloat Detection

**When to use**: Install times are slow, `node_modules` / target directory is massive, bundle size budget exceeded, or dependency tree is unmaintainable.

**Approach**:
1. **Duplicate detection**:
   - `npm ls <pkg>` — multiple versions of same package.
   - `cargo tree -d` — duplicate crates.
   - `bundle exec` inconsistencies.
2. **Unused dependency detection**:
   - Node.js: `depcheck`
   - Python: `vulture` + manual review for optional imports.
   - Rust: `cargo-udeps` (nightly required).
   - Go: `go mod graph` analysis.
3. **Size profiling**:
   - Node.js: `du -sh node_modules/* | sort -rh | head -20`
   - Python: `pip show <pkg>` for installed size.
   - Rust: `cargo bloat` (binary size, not crate size).
4. **Lock file bloat**:
   - Flag lock files > 2 MB (suggests excessive transitive resolution).
   - Run `scripts/analyze_dependencies.py --check-bloat`.
5. **Recommendations**:
   - Deduplicate via lock file refresh or `resolutions` / `overrides`.
   - Remove unused deps.
   - Replace large utility libraries with lighter alternatives.
   - Use `optionalDependencies` or feature flags to trim unused features.

---

### 7. Lock File Maintenance

**When to use**: Lock file conflicts in merge, CI reproducibility failures, or after manual manifest edits.

**Approach**:
1. **Consistency check**:
   - Verify manifest and lock file are in sync.
   - Node.js: `npm ci` (fails if mismatch).
   - Python: `poetry check` or `uv lock`.
   - Rust: `cargo update --workspace`.
   - Go: `go mod tidy`.
   - Ruby: `bundle check`.
   - PHP: `composer validate`.
2. **Format upgrade**:
   - npm: migrate `package-lock.json` to `lockfileVersion: 3`.
   - Yarn: use Yarn 4 with `yarn.lock` and `.yarnrc.yml`.
   - pnpm: keep `pnpm-lock.yaml` up to date.
3. **Merge conflict resolution**:
   - Preferred strategy: regenerate from manifest rather than resolving lock diffs manually.
   - `rm package-lock.json && npm install`
   - `rm poetry.lock && poetry lock`
   - `cargo generate-lockfile`
   - `bundle update`
   - `composer update --lock`
4. **Binary projects**: Ensure `Cargo.lock`, `composer.lock`, `Gemfile.lock`, `packages.lock.json` are committed.

---

### 8. Automated PR Generation

**When to use**: Setting up continuous dependency maintenance.

**Approach**:
1. **Dependabot** (GitHub):
   ```yaml
   # .github/dependabot.yml
   version: 2
   updates:
     - package-ecosystem: "npm"
       directory: "/"
       schedule:
         interval: "weekly"
       open-pull-requests-limit: 10
       versioning-strategy: auto
       allow:
         - dependency-type: "direct"
       ignore:
         - dependency-name: "internal-lib"
           update-types: ["version-update:semver-major"]
   ```
2. **Renovate** (cross-platform):
   - Highly configurable via `renovate.json`.
   - Supports grouping, auto-merge for patch updates, scheduling.
3. **Custom scripts**:
   - Use `scripts/analyze_dependencies.py --format markdown` to generate PR description with changelogs and risk assessment.
   - Attach SARIF report to PR for security visibility.

---

## Quick Reference: Commands by Ecosystem

| Task | Node.js | Python | Rust | Go | Ruby | PHP | Java |
|------|---------|--------|------|-----|------|-----|------|
| **List outdated** | `npm outdated` | `pip list --outdated` / `poetry show --outdated` | `cargo outdated` | `go list -u -m all` | `bundle outdated` | `composer outdated` | `mvn versions:display-dependency-updates` |
| **Audit security** | `npm audit` | `pip-audit` / `safety check` | `cargo audit` | `govulncheck` | `bundler-audit` | `composer audit` | OWASP Dep-Check |
| **Update all** | `npm update` | `poetry update` / `uv sync` | `cargo update` | `go get -u ./...` | `bundle update` | `composer update` | `mvn versions:use-latest-versions` |
| **Update single** | `npm install <pkg>@latest` | `poetry add <pkg>@^x.y` | `cargo update -p <pkg>` | `go get <pkg>@latest` | `bundle update <gem>` | `composer update <pkg>` | `mvn versions:update-parent` |
| **Show tree** | `npm ls` / `pnpm why` | `pipdeptree` / `uv tree` | `cargo tree` | `go mod graph` | `bundle viz` | `composer show --tree` | `mvn dependency:tree` |
| **Check lock** | `npm ci` | `poetry check` | `cargo generate-lockfile` | `go mod tidy` | `bundle check` | `composer validate` | `mvn dependency:resolve` |
| **Licenses** | `license-checker` | `pip-licenses` | `cargo license` | `go-licenses` | `license_finder` | `composer licenses` | `license-maven-plugin` |

---

## Resources

### scripts/
- **`analyze_dependencies.py`** — Cross-ecosystem dependency scanner. Parses manifests, queries OSV for vulnerabilities, generates update recommendations, detects bloat, and outputs Markdown/JSON/SARIF reports.

### references/
- **`package_managers.md`** — Per-manager lock file formats, update commands, resolution strategies, and conflict resolution patterns for all supported ecosystems.
- **`vulnerability_sources.md`** — OSV, GitHub Advisory, Snyk, npm audit, and ecosystem-specific tools (cargo-audit, govulncheck, bundler-audit, safety, pip-audit, composer audit). Includes SARIF reporting and CI/CD integration patterns.

---

## Example Usage Scenarios

### Scenario A: "Audit my repo for vulnerabilities"
```bash
python scripts/analyze_dependencies.py --root . --check-vulns --severity high --format markdown --output VULN_REPORT.md
```

### Scenario B: "Update everything safely"
1. Run `python scripts/analyze_dependencies.py --root . --format markdown`.
2. Review recommendations table for major/minor/patch classification.
3. Apply patch group first: `npm update` / `poetry update` / `cargo update`.
4. Run tests.
5. Apply minor updates one by one if tests pass.
6. Queue major updates for separate PRs with migration guides.

### Scenario C: "A critical CVE just dropped in lodash"
1. Check `npm audit` or run the scanner to confirm affected version.
2. Check if patched version is within current semver range.
3. If not, add temporary `overrides` in `package.json` to force safe version.
4. Run `npm install` and full test suite.
5. Commit with message: `security: force lodash@4.17.21 via override (CVE-XXXX-XXXX)`.
6. Create follow-up ticket to upgrade to non-override path.

### Scenario D: "License compliance check before release"
1. Run ecosystem license tool (see Quick Reference table).
2. Export CSV/SBOM.
3. Cross-reference with `vulnerability_sources.md` for policy guidance.
4. Flag GPL / AGPL / proprietary conflicts.
5. Recommend replacements or document exceptions.

---

*Version: 1.0.0 | Maintained as part of dev-dependency-manager skill.*
