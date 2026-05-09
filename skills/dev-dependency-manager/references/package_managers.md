# Package Managers Reference

Comprehensive reference for dependency file formats, lock file maintenance, update commands, and conflict resolution across all major ecosystems.

## Table of Contents
1. [Node.js / npm / Yarn / pnpm](#nodejs-npm-yarn-pnpm)
2. [Python / pip / poetry / uv](#python-pip-poetry-uv)
3. [Rust / Cargo](#rust-cargo)
4. [Go / Modules](#go-modules)
5. [Java / Maven / Gradle](#java-maven-gradle)
6. [Ruby / Bundler](#ruby-bundler)
7. [PHP / Composer](#php-composer)
8. [.NET / NuGet](#dotnet-nuget)
9. [Conflict Resolution Strategies](#conflict-resolution-strategies)

---

## Node.js / npm / Yarn / pnpm

### Manifest Files
| File | Purpose |
|------|---------|
| `package.json` | Primary manifest. Declares `dependencies`, `devDependencies`, `peerDependencies`, `optionalDependencies`, `resolutions` (Yarn), `overrides` (npm 8.3+). |
| `.npmrc` / `.yarnrc` | Registry config, auth tokens, resolution settings. |

### Lock Files
| Tool | Lock File | Format | Notes |
|------|-----------|--------|-------|
| npm | `package-lock.json` | JSON v2/v3 | Use `lockfileVersion: 3` (npm 9+). Commit to VCS. |
| Yarn 1 | `yarn.lock` | Custom flat text | Commit to VCS. |
| Yarn 2/3/4 | `yarn.lock` | YAML-like | PnP mode optional; `.pnp.cjs` if zero-install. |
| pnpm | `pnpm-lock.yaml` | YAML | Strictest resolution. Commit to VCS. |

### Update Commands
```bash
# npm
npm update                          # Respects semver ranges
npm outdated                      # List outdated packages
npm audit                         # Security audit
npm audit fix                     # Auto-fix where possible
npm install <pkg>@latest          # Major bump
npm install <pkg>@^x.y.z          # Explicit range
npm shrinkwrap                    # (Legacy, avoid)

# Yarn 1
yarn upgrade                      # Interactive or range-respecting
yarn upgrade-interactive          # TUI for selective updates
yarn outdated                     # List outdated
yarn audit                        # Security audit

# Yarn 2/3/4
yarn up <pkg>                     # Upgrade package
yarn up <pkg>@^x.y.z              # Upgrade to range
yarn npm audit                    # Audit via npm registry
yarn why <pkg>                    # Show why a package is present

# pnpm
pnpm update                       # Update all within ranges
pnpm update --interactive         # Interactive TUI
pnpm outdated                     # List outdated
pnpm audit                        # Security audit
pnpm audit --fix                  # Auto-fix
```

### Resolution Strategies
- **npm**: Uses `node_modules` nesting + hoisting. `overrides` (v8.3+) forces specific versions.
- **Yarn**: Flattened `node_modules` (v1), PnP (v2+). `resolutions` field in `package.json` overrides any version.
- **pnpm**: Content-addressable store + hard links. Strict resolution graph. `pnpm.overrides` in `package.json` or `.npmrc` `package-import-method`.

### Breaking Change Detection
- Read `CHANGELOG.md` or GitHub Releases for `BREAKING CHANGES`.
- Use `npm ls <pkg>` / `pnpm why <pkg>` to assess transitive exposure.
- Run `npm pack --dry-run` to verify publish-side effects.

---

## Python / pip / poetry / uv

### Manifest Files
| File | Purpose |
|------|---------|
| `requirements.txt` | Flat dependency list for pip. Supports `==`, `>=`, `~=`, `!=`, extras. |
| `requirements/*.txt` | Common pattern: `base.txt`, `dev.txt`, `prod.txt` layered with `-r`. |
| `pyproject.toml` | PEP 518/621 modern standard. `[project.dependencies]`, `[project.optional-dependencies]`. |
| `setup.py` / `setup.cfg` | Legacy; migrate to `pyproject.toml`. |
| `poetry.lock` | Poetry lock file. |
| `uv.lock` | uv lock file. |
| `Pipfile` / `Pipfile.lock` | pipenv (discouraged for libraries). |

### Lock Files
| Tool | Lock File | Notes |
|------|-----------|-------|
| pip + requirements.txt | None by default | Pin with `pip freeze > requirements.txt` or use `pip-tools`. |
| pip-tools | `requirements.txt` (compiled) | Source: `requirements.in`. Run `pip-compile`. |
| Poetry | `poetry.lock` | JSON-ish TOML. Commit to VCS. |
| uv | `uv.lock` | TOML-like. Commit to VCS. Extremely fast. |
| pipenv | `Pipfile.lock` | JSON. Commit to VCS. |

### Update Commands
```bash
# pip
pip install -r requirements.txt --upgrade
pip list --outdated
pip install <pkg> --upgrade

# pip-tools
pip-compile requirements.in --upgrade        # Regenerate lock
pip-compile requirements.in --upgrade-package <pkg>==x.y.z

# Poetry
poetry update                                # Update all within constraints
poetry update <pkg>                          # Update specific package
poetry show --outdated                       # List outdated
poetry add <pkg>@^x.y.z                      # Add with constraint
poetry lock                                  # Regenerate lock without install

# uv
uv pip compile requirements.in -o requirements.txt --upgrade
uv pip install -r requirements.txt --upgrade
uv add <pkg>==x.y.z                         # Add to pyproject.toml
uv lock                                      # Regenerate uv.lock
uv sync                                      # Install from uv.lock
uv tree                                      # Dependency tree
```

### Resolution Strategies
- **pip**: No native resolver for complex conflicts (improved resolver since pip 20.3). Pin everything for reproducibility.
- **pip-tools**: Compiles `requirements.in` + constraints into fully resolved `requirements.txt`.
- **Poetry**: SAT solver. `poetry.lock` is deterministic. Use `source` for private indexes.
- **uv**: Rust-based resolver. Compatible with `pip` and `poetry` metadata. Supports `tool.uv.pip` settings.

### Breaking Change Detection
- Check `CHANGELOG` / `HISTORY` files in PyPI source distributions.
- Use `pip show <pkg>` to inspect installed version and location.
- For libraries, test against minimum and maximum dependency versions (`tox` / `nox` matrix).

---

## Rust / Cargo

### Manifest Files
| File | Purpose |
|------|---------|
| `Cargo.toml` | Manifest. `[dependencies]`, `[dev-dependencies]`, `[workspace.dependencies]`. Semver with `=`, `>=`, `~`, `*`, caret (default). |
| `.cargo/config.toml` | Registry mirrors, credential providers, build settings. |

### Lock File
- `Cargo.lock`: TOML format. **Always commit for binaries.** Optional for libraries (but recommended for reproducible CI).

### Update Commands
```bash
cargo update                          # Update all within Cargo.toml constraints
cargo update -p <pkg>                 # Update specific package
cargo tree                            # Dependency tree
cargo tree -d                         # Show duplicates
cargo audit                           # Security audit (requires cargo-audit)
cargo outdated                        # List outdated (requires cargo-outdated)
cargo check                           # Fast compile check after update
cargo test                            # Full test validation
```

### Resolution Strategies
- Cargo uses minimal version selection by default (not maximal). This means it picks the oldest version satisfying constraints unless forced newer.
- Workspace inheritance: use `[workspace.dependencies]` to centralize versions across a workspace.
- `patch` table can override crates.io versions with git/path sources.

### Breaking Change Detection
- Check `CHANGELOG.md` or docs.rs release notes.
- `cargo semver-checks` (external tool) verifies API compatibility.
- `cargo test` + `cargo clippy -- -D warnings` after any update.

---

## Go / Modules

### Manifest Files
| File | Purpose |
|------|---------|
| `go.mod` | Module path, Go version, direct dependencies with `require`, `replace`, `exclude`. |
| `go.sum` | Cryptographic checksums of module content. **Always commit.** |

### Lock File
- `go.mod` + `go.sum` together act as lock. `go.sum` ensures integrity.

### Update Commands
```bash
go get -u ./...                     # Update all direct deps to latest
go get -u=patch ./...               # Update to latest patch only
go get <pkg>@latest                 # Update specific package
go get <pkg>@vX.Y.Z                 # Pin specific version
go mod tidy                         # Remove unused deps, add missing
go mod download                     # Pre-download modules
go list -u -m all                   # List outdated modules
 govulncheck ./...                   # Security scan (requires govulncheck)
```

### Resolution Strategies
- **MVS (Minimal Version Selection)**: Go selects the minimum version satisfying all requirements. Upgrading one module may not upgrade transitive deps unless explicitly requested.
- `replace` directives: local overrides. **Never commit `replace` pointing to local paths** in shared branches.
- `exclude` directives: emergency only. Prefer `require` with explicit version.

### Breaking Change Detection
- Check release notes on pkg.go.dev or project repo.
- Go does not enforce semantic versioning strictly beyond module path major suffix (`/v2`).
- Run `go test ./...` after any update; Go's static typing catches most API breaks at compile time.

---

## Java / Maven / Gradle

### Maven

#### Manifest Files
| File | Purpose |
|------|---------|
| `pom.xml` | Project Object Model. `<dependencies>`, `<dependencyManagement>`, `<properties>` for versions, `<repositories>`. |

#### Lock File
- No native lock file. Use `mvn dependency:resolve` to verify.
- Third-party: `maven-enforcer-plugin` with `dependencyConvergence`, `requireUpperBoundDeps`.

#### Update Commands
```bash
mvn versions:display-dependency-updates     # List outdated
mvn versions:use-latest-versions              # Auto-bump (caution)
 mvn versions:use-latest-releases            # Bump to latest release
mvn versions:set-property                     # Update <property> version
mvn dependency:tree                           # Tree view
mvn dependency:analyze                          # Unused declared / used undeclared
mvn dependency:resolve                        # Verify resolution
```

#### Resolution Strategies
- Maven uses "nearest definition" + dependency mediation. `<dependencyManagement>` in parent POM centralizes versions.
- `<scope>` (`compile`, `test`, `provided`, `runtime`) affects transitive inclusion.
- BOMs (Bill of Materials) like Spring Boot `spring-boot-dependencies` enforce compatible sets.

### Gradle

#### Manifest Files
| File | Purpose |
|------|---------|
| `build.gradle` / `build.gradle.kts` | Build script. `dependencies {}`, `implementation()`, `version catalogs`. |
| `settings.gradle` | Project structure, plugin management. |
| `gradle/libs.versions.toml` | **Version catalog** (recommended). Centralizes versions in TOML. |

#### Lock File
- **Gradle Dependency Locking**: `gradle.lockfile` per configuration. Enable with `locking { lockAllConfigurations() }`.

#### Update Commands
```bash
./gradlew dependencies --configuration runtimeClasspath   # Tree view
./gradlew dependencyUpdates                              # List outdated (requires plugin)
./gradlew classes                                        # Compile check
./gradlew test                                           # Test validation
```

#### Resolution Strategies
- **Default**: Newest version wins for transitive conflicts.
- **Force**: `force = true` or `resolutionStrategy.force`.
- **Version Catalogs**: Single source of truth for versions across a multi-project build.
- **Platforms / BOMs**: `platform('org.springframework.boot:spring-boot-dependencies:3.x.x')`.

---

## Ruby / Bundler

### Manifest Files
| File | Purpose |
|------|---------|
| `Gemfile` | Declares gems, sources, groups, git/path references. Uses `gem 'name', '~> x.y'`. |
| `.ruby-version` | Ruby version for rbenv/rvm/chruby. |

### Lock File
- `Gemfile.lock`: **Commit to VCS.** Records exact versions and Bundler version.

### Update Commands
```bash
bundle update                     # Update all within Gemfile constraints
bundle update <gem>               # Update specific gem
bundle outdated                   # List outdated
bundle outdated --strict          # Only direct dependencies
bundle audit                      # Security audit (requires bundler-audit)
bundle check                      # Verify lock consistency
bundle install                    # Install from lock
bundle lock --add-platform x86_64-linux  # Add platform support
```

### Resolution Strategies
- Bundler resolves full graph up front. `Gemfile.lock` ensures all environments resolve identically.
- `bundle update` regenerates the lock. `bundle install` respects the lock.
- Git sources: `:github`, `:git`, `:branch`, `:ref`, `:tag`. Prefer `:ref` or `:tag` for determinism.
- `resolutions` equivalent: `gem 'foo', path: '../foo'` for local override.

### Breaking Change Detection
- Check `CHANGELOG` or GitHub Releases for Ruby gems.
- Run `bundle exec rspec` / `bundle exec rake test` after updates.
- `bundle exec` ensures binstub compatibility.

---

## PHP / Composer

### Manifest Files
| File | Purpose |
|------|---------|
| `composer.json` | Manifest. `require`, `require-dev`, `autoload`, `repositories`, `config`. |
| `composer.lock` | Lock file. **Always commit for apps.** Libraries may omit but CI should validate. |

### Update Commands
```bash
composer update                   # Update all within constraints
composer update <vendor>/<pkg>    # Update specific package
composer outdated                 # List outdated
composer outdated --direct      # Only direct dependencies
composer audit                    # Security audit (built-in)
composer show --tree              # Dependency tree
composer require <vendor>/<pkg>  # Add / update package
composer validate                 # Validate schema
```

### Resolution Strategies
- Composer uses SAT solver. `composer.lock` ensures deterministic installs.
- `minimum-stability`: `stable`, `RC`, `beta`, `alpha`, `dev`.
- `prefer-stable: true` with `minimum-stability: dev` allows dev-only when required.
- `config.platform` fakes platform packages (PHP version, extensions) to ensure lock portability.

---

## .NET / NuGet

### Manifest Files
| File | Purpose |
|------|---------|
| `.csproj` / `.fsproj` / `.vbproj` | MSBuild project. `<PackageReference Include="Name" Version="X.Y.Z" />`. |
| `Directory.Packages.props` | Central package management (CPM). Single version source for solution. |
| `packages.lock.json` | Lock file per project. Enable with `<RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>`. |
| `nuget.config` | Feed sources, credentials, resolution settings. |

### Update Commands
```bash
dotnet list package --outdated                  # List outdated
dotnet list package --outdated --include-transitive
dotnet add package <Name> --version <X.Y.Z>     # Add / update
dotnet remove package <Name>                    # Remove
dotnet restore --locked-mode                    # Strict restore from lock
dotnet restore --force-evaluate                 # Regenerate lock
```

### Resolution Strategies
- **Central Package Management (CPM)**: Define versions in `Directory.Packages.props`. Projects use `<PackageReference Include="Name" />` without version.
- **Lock files**: `packages.lock.json` ensures reproducible restore across machines.
- **Transitive pinning**: `<DisableTransitiveProjectReferences>false</DisableTransitiveProjectReferences>` in SDK-style projects.

---

## Conflict Resolution Strategies

### 1. Diamond Dependency Problem
When two packages require different versions of the same transitive dependency:

| Ecosystem | Behavior | Override Mechanism |
|-----------|----------|-------------------|
| npm | Hoists one version, nests others | `overrides` / `resolutions` |
| pip | Fails or installs conflicting versions in different paths | Manual pinning, virtualenv isolation |
| Cargo | Compiles multiple versions (namespaced) | None needed (binary bloat possible) |
| Go | Minimal version selected (may not satisfy one branch) | `replace` or explicit `require` |
| Maven | Nearest definition / first-declared | `<dependencyManagement>` override |
| Gradle | Newest version wins | `resolutionStrategy` / `force` |
| Bundler | Fails if unsolvable | `gem 'dep', '= x.y.z'` in Gemfile |
| Composer | SAT solver resolves or fails | Explicit `require` of shared dep |
| NuGet | Lowest applicable version | Direct `PackageReference` override |

### 2. Peer Dependency Conflicts
Common in Node.js plugin ecosystems:

- **npm 7+**: Auto-installs peers. Fails on unresolvable conflicts.
- **Yarn**: `packageExtensions` in `.yarnrc.yml` to declare missing peers.
- **pnpm**: Strict peer resolution. `.pnpmfile.cjs` to read/modify resolution.

### 3. Version Pinning vs. Floating

| Strategy | When to Use |
|----------|-------------|
| **Pin exact** | Security-critical apps, reproducible builds, CI pipelines |
| **Caret `^x.y.z`** | Libraries respecting semver. Allows non-breaking updates. |
| **Tilde `~x.y.z`** | Conservative apps. Allows patch only. |
| **Range `>=x.y, <z`** | Complex compatibility requirements. |
| **Floating `*` / latest** | Prototyping only. Never in production. |

### 4. Emergency CVE Response

1. Identify vulnerable package and fixed version.
2. Check if fixed version is within current range. If yes: lock file refresh only.
3. If no: evaluate breaking change scope (semver major, API changes, runtime behavior).
4. Apply override / resolution / `replace` to force fixed version temporarily.
5. Run full test suite + integration tests.
6. File issue to upgrade properly and remove override.

### 5. Monorepo / Workspace Strategies

| Tool | Workspace File | Shared Lock |
|------|---------------|-------------|
| npm | `workspaces` in root `package.json` | Single `package-lock.json` |
| Yarn | `workspaces` in root | Single `yarn.lock` |
| pnpm | `pnpm-workspace.yaml` | Single `pnpm-lock.yaml` |
| Cargo | `[workspace]` in root `Cargo.toml` | Single `Cargo.lock` |
| Poetry | `poetry.toml` / `pyproject.toml` workspace | Single `poetry.lock` |
| uv | `[tool.uv.workspace]` in root `pyproject.toml` | Single `uv.lock` |
| Gradle | `settings.gradle` include projects | `gradle.lockfile` per config |

### 6. Platform-Specific Dependencies

- **Optional dependencies**: `optionalDependencies` (npm), `optional = true` (Cargo), `<scope>provided</scope>` (Maven).
- **Environment markers**: `sys_platform` / `python_version` in Python requirements.
- **Conditional compilation**: `[target.'cfg(unix)'.dependencies]` in Cargo.
- **Bundler platforms**: `bundle lock --add-platform` for multi-platform CI.
