# Skill Catalog — Complete Reference for Interactive Flow

This document lists all **100 skills** in the ecosystem repository, organized by layer for the `ecosystem-integrator` interactive recommendation flow.

## Layer 0: Enforcement (15 skills) — Always On, User Cannot Disable

| # | Skill | What It Does | User Sees |
|---|-------|-------------|-----------|
| 1 | `policy-engine` | 144 ALWAYS/NEVER rules, fail-closed | All tool calls validated |
| 2 | `policy-version-manager` | Semantic versioning for policy files | Policy versions tracked |
| 3 | `policy-attestation-layer` | Ed25519 chain of custody for decisions | Audit trail maintained |
| 4 | `policy-engine-standalone` | Standalone policy service with CI | Policy engine is robust |
| 5 | `sandbox-executor` | Docker/nerdctl/E2B/K8s isolation | Code runs in sandbox |
| 6 | `sandbox-allowlist-enforcer` | Executable allowlists + seccomp-BPF | Commands restricted |
| 7 | `sandbox-integration-tester` | CI tests for all sandbox backends | Isolation validated |
| 8 | `ipi-defender` | 4-layer IPI defense (pattern + entropy + ensemble + probe) | External content scanned |
| 9 | `ipi-embedding-hardened` | Ensemble embeddings + behavioral probe | IPI hardened against attacks |
| 10 | `phase-controller` | 7-phase FSM with hash-verified transitions | Pipeline phases enforced |
| 11 | `phase-controller-external` | External FSM with persistence layer | Phase state persisted |
| 12 | `phase-iterate-controller` | ITERATE/RETRY transitions with audit | Iteration governed safely |
| 13 | `artifact-verifier` | Semantic + hash artifact validation | Artifacts verified |
| 14 | `adversarial-tester` | 108/108 adversarial test cases | Security tests passed |
| 15 | `adversarial-tester-expanded` | 100+ cases across 10 categories | Expanded adversarial coverage |
| 16 | `runtime-taint-tracker` | Data provenance tainting | Data flow tracked |
| 17 | `secret-manager` | Secret lifecycle + output scrubbing | Secrets protected |
| 18 | `secrets-lifecycle-manager` | Vault/K8s/AWS secret management | Production-grade secrets |
| 19 | `supply-chain-verifier` | TUF/Sigstore signature verification | Packages verified |
| 20 | `tee-executor` | AWS Nitro Enclaves TEE execution | Hardware isolation available |
| 21 | `egress-dpi-guard` | Deep packet inspection for egress | Outbound traffic inspected |
| 22 | `drift-monitor` | Behavioral anomaly detection (3-tier) | Drift detected |
| 23 | `drift-statistical-validator` | Statistical validation for baselines | Baselines validated |
| 24 | `error-policy` | Error recovery, circuit breaker, HITL | Errors handled gracefully |
| 25 | `memory-guard` | 4-layer memory with trust scoring | Memories scored and tracked |
| 26 | `dependency-resolver` | Dependency verification + CVE scanning | Dependencies verified |
| 27 | `skill-registry` | Lifecycle: REGISTERED→LOADED→ACTIVE→UNLOADED→PURGED | Skills managed |
| 28 | `health-endpoint-standard` | Standardized /health /ready /metrics | Health visible |
| 29 | `config-profile-manager` | Dev/staging/prod validated profiles | Environments configured |
| 30 | `cost-tier-security-gate` | SECURITY-CRITICAL blocks external routing | External routing secured |

## Layer 1: Gateway (3 skills) — Always On

| # | Skill | What It Does |
|---|-------|-------------|
| 31 | `tool-execution-gateway` | Gate 0 content sanitization, MCP trust, PII pre-scan |
| 32 | `multi-model-router` | Cost-tier dispatcher for multiple LLM models (v4.2.1) |
| 33 | `post-gemini-validator` | Deterministic validation of external model outputs |

## Layer 2: Analysis & Intelligence (8 skills)

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 34 | `spec-decomposer` | Decompose specs into task nodes | "Break down this spec" |
| 35 | `requirement-refinement` | Ambiguity scoring, example mapping | "Clarify these requirements" |
| 36 | `requirement-reconciler` | Reconcile conflicting requirements | "Resolve requirement conflicts" |
| 37 | `brownfield-intelligence` | SQLite-based brownfield analysis | "Analyze this codebase" |
| 38 | `hybrid-code-analyzer` | Static + dynamic call graph merge | "Deep analysis of this code" |
| 39 | `graphify` | Knowledge graph from tree-sitter + LLM | "Map this codebase" |
| 40 | `log-analyzer` | Error log ingestion, stack trace tracing | "Analyze these logs" |
| 41 | `blast-radius-calculator` | Risk scores, impact analysis | "What's the impact of this change?" |

## Layer 3: Architecture & Design (10 skills)

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 42 | `architecture-design` | Pattern selection, ADRs, ATAM, fitness functions | "Design the architecture" |
| 43 | `architecture-decision-gate` | Bias-checking HITL gate for ADRs | "Review this architecture decision" |
| 44 | `architecture-fitness-function` | Fitness DSL, coupling, cycle detection | "Check architecture health" |
| 45 | `architecture-evolution` | Migration patterns, phased plans | "Plan architecture migration" |
| 46 | `trade-off-analyzer` | Weighted scoring, alternatives, debt tracking | "Analyze trade-offs" |
| 47 | `technical-debt-ledger` | Cost-of-delay scoring, repayment tracking | "Track technical debt" |
| 48 | `boundary-enforcer` | DDD bounded context enforcement | "Enforce boundaries" |
| 49 | `dynamic-boundary-validator` | Trace-based boundary staleness detection | "Validate boundaries" |
| 50 | `adr-machine-capture` | MADR-JSON standard with constraint derivation | "Capture this decision" |
| 51 | `cross-cutting-concern-weaver` | Aspect-oriented concern management | "Weave in security/logging" |

## Layer 4: Code Generation & Execution (8 skills)

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 52 | `code-tester` | Unit/integration test generation (pytest/jest/vitest) | "Generate tests" |
| 53 | `property-tester-pro` | Property-based testing with invariants | "Run property tests" |
| 54 | `refactoring-engine` | AST-based transformation, blast radius check | "Refactor this code" |
| 55 | `formal-verification-assistant` | Z3/TLA+ bounded verification for Risk >= 9 | "Verify this formally" |
| 56 | `dynamic-analyzer` | Runtime behavioral anomaly detection (strace) | "Monitor behavior" |
| 57 | `self-reviewer` | AST-backed design/security review | "Review this code" |
| 58 | `style-enforcer` | Commit style analysis and enforcement | "Enforce style" |
| 59 | `address-pr-comments` | Autonomous PR review response | "Address PR feedback" |

## Layer 5: Validation & Quality (7 skills)

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 60 | `security-auditor` | SAST, dependency CVE, STRIDE analysis | "Audit security" |
| 61 | `performance-validator` | Load tests, benchmarks, SLO validation | "Validate performance" |
| 62 | `resilience-tester` | Failure injection, circuit breaker validation | "Test resilience" |
| 63 | `api-contract-tester` | Runtime API contract validation | "Test API contracts" |
| 64 | `api-version-guard` | OpenAPI backward compatibility check | "Check API compatibility" |
| 65 | `canary-orchestrator` | Progressive delivery with health gating | "Deploy with canary" |
| 66 | `ci-cd-integrator` | CI/CD pipeline generation, rollback | "Generate CI/CD config" |

## Layer 6: Production & Operations (6 skills)

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 67 | `production-drift-bridge` | Production-to-staging drift correlation | "Check production drift" |
| 68 | `slo-enforcer` | Latency/availability/error budget SLOs | "Enforce SLOs" |
| 69 | `chaos-engineering-suite` | Chaos tests for cascades/races/OOM | "Run chaos experiments" |
| 70 | `redteam-coordinator` | Independent red-team exercise orchestration | "Commission red-team" |
| 71 | `calibration-publisher` | Trust score dataset/methodology publishing | "Publish benchmarks" |
| 72 | `runbook-generator` | Failure mode runbooks per skill | "Generate runbooks" |

## Layer 7: Infrastructure & Memory (8 skills)

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 73 | `infrastructure-as-code` | Terraform/CF/K8s with human approval gates | "Generate infrastructure code" |
| 74 | `obsidian-setup` | Obsidian Zettelkasten knowledge vault | "Save to knowledge vault" |
| 75 | `federated-memory-mesh` | Cross-instance procedural memory sharing | "Share across instances" |
| 76 | `documentation-synthesizer` | README, OpenAPI, docstrings, ADR updates | "Generate documentation" |
| 77 | `schema-explorer` | Database schema inspection, migrations | "Explore database schema" |
| 78 | `skill-orchestrator` | Routes tasks to correct skills (L2 meta) | (automatic) |
| 79 | `telemetry-aggregator` | Aggregates telemetry from all skills | (automatic) |
| 80 | `kimi-trace` | Session/activity tracing across skills | (automatic) |

## Layer 8: Developer-Facing Interface (15 skills) — User-Initiated Only

| # | Skill | What It Does | User Trigger |
|---|-------|-------------|--------------|
| 81 | `ecosystem-integrator` | Discovery, navigation, session coordination | "Start ecosystem" |
| 82 | `dev-code-generator` | Code generation with type hints, idiomatic patterns | "Generate code" |
| 83 | `dev-test-automation` | Test generation, coverage analysis, mocks | "Write tests" |
| 84 | `dev-debug-assistant` | Stack trace analysis, root cause, fix suggestions | "Debug this" |
| 85 | `dev-ci-cd-pipeline` | GitHub Actions/GitLab CI/Jenkins generation | "Set up CI/CD" |
| 86 | `dev-dependency-manager` | Outdated packages, CVEs, license audit | "Audit dependencies" |
| 87 | `dev-performance-profiler` | CPU/memory flame graphs, DB query analysis | "Profile performance" |
| 88 | `dev-security-scanner` | SAST, secret scanning, container scanning | "Scan security" |
| 89 | `dev-api-designer` | OpenAPI/GraphQL spec, mock servers, SDKs | "Design API" |
| 90 | `dev-database-migrator` | Schema migrations, rollback, seeding | "Migrate database" |
| 91 | `dev-observability-setup` | Prometheus/Grafana/OpenTelemetry/Jaeger | "Set up monitoring" |
| 92 | `dev-incident-responder` | Alert triage, runbooks, post-mortems | "Respond to incident" |
| 93 | `dev-infrastructure-coder` | Terraform/CloudFormation/Pulumi with cost estimation | "Generate IaC" |
| 94 | `dev-docs-maintainer` | READMEs, API docs, changelogs, diagrams | "Generate docs" |
| 95 | `dev-git-workflow` | PR review, merge conflicts, conventional commits | "Git workflow" |
| 96 | `dev-container-builder` | Multi-stage Docker, scanning, BuildKit | "Build containers" |

## Back-Propagation & Error Handling (4 skills)

| # | Skill | What It Does | When Activated |
|---|-------|-------------|----------------|
| 97 | `back-propagation-protocol` | Failure feedback loop with delta manifests | On VALIDATE failure |
| 98 | `error-policy` | Error recovery, circuit breaker, HITL escalation | On any error |
| 99 | `memory-guard` | Trust-scored memory with cryptographic attestation | On memory operations |
| 100 | `policy` | (Legacy) Policy rule definitions — now part of policy-engine | (deprecated, use policy-engine) |

## Total: 100 Skills

- **30** L0 Enforcement (always on, mandatory)
- **3** L1 Gateway (always on)
- **8** L2 Analysis (phase-gated)
- **10** L3 Architecture (phase-gated)
- **8** L4 Code Execution (phase-gated)
- **7** L5 Validation (phase-gated)
- **6** L6 Production (phase-gated)
- **8** L7 Infrastructure/Memory (phase-gated)
- **15** L8 Developer Interface (user-initiated only)
- **4** Cross-cutting (error + memory + back-prop + legacy)

**The user can only directly choose L8 skills. All other layers are automatic.**
