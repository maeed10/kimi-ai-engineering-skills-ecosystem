# Full Skill Routing Matrix

Complete routing matrix for all 59+ skills in the Kimi AI Engineering Skills Ecosystem v4.2.1.

## Legend

| Column | Meaning |
|--------|---------|
| **User Intent Pattern** | Canonical phrase(s) that trigger this route |
| **Primary Skill** | First skill loaded with full content |
| **Secondary Skill** | Second skill loaded if needed (counts toward 3-skill limit) |
| **Never Load** | Skills that conflict with or are irrelevant to this intent |
| **Prerequisite** | What must be available before activation |
| **Gemini Eligible** | Whether this intent can be routed to a low-cost external model |
| **Ambiguous Resolution** | How to handle ambiguous variants of this intent |

---

## L0 Enforcement Layer (Always Loaded)

These skills are loaded automatically by `ecosystem-integrator` and do not appear in user-intent routing.

| Skill | Phase | Purpose |
|-------|-------|---------|
| `policy-engine` | ALL | Policy validation |
| `ipi-defender` | ALL | Indirect prompt injection defense |
| `sandbox-executor` | ALL | Sandbox execution |
| `phase-controller` | ALL | Phase state machine |
| `skill-registry` | ALL | Skill lifecycle management |
| `error-policy` | ALL | Error recovery |
| `memory-guard` | ALL | Memory trust scoring |
| `drift-monitor` | ALL | Behavioral anomaly detection |
| `dependency-resolver` | ALL | Dependency verification |
| `adversarial-tester` | ALL | Adversarial validation |
| `secret-manager` | ALL | Secret lifecycle |
| `supply-chain-verifier` | ALL | Supply chain integrity |
| `tee-executor` | ALL | TEE sandbox backend |
| `egress-dpi-guard` | ALL | Egress deep packet inspection |
| `runtime-taint-tracker` | ALL | Data provenance tracking |

---

## L1 Gateway Layer (Always Loaded)

| Skill | Phase | Purpose |
|-------|-------|---------|
| `tool-execution-gateway` | ALL | Tool call authorization |
| `multi-model-router` | INGEST, PLAN, DELIVER, REMEMBER | Low-cost external model routing |
| `cost-tier-security-gate` | INGEST, PLAN, DELIVER, REMEMBER | Security gate for external routing |

---

## L2 Intent & Analysis

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "Refine requirements" / "Clarify this spec" | `requirement-refinement` | `spec-decomposer` | Any execution skill | SPEC.md or PRD.md loaded | Yes — read-only parsing | If ambiguous: present up to 3 clarification options |
| "Reconcile conflicting requirements" | `requirement-reconciler` | `requirement-refinement` | Any execution skill | Multiple source documents detected | Yes — read-only comparison | If no contradictions found: skip and route to refinement |
| "Analyze this codebase structure" | `brownfield-intelligence` | `graphify` | Style Enforcer | None | No — requires structural DB | If ambiguous ("analyze" vs "map"): default to Brownfield |
| "Build a knowledge graph" / "Map relationships" | `graphify` | `brownfield-intelligence` | Style Enforcer | None | No — requires tree-sitter | If ambiguous: ask "structural or semantic?" |
| "Hybrid analysis" / "Full code audit" | `hybrid-code-analyzer` | `brownfield-intelligence` | Style Enforcer | Graphify or Brownfield index | No | If ambiguous: clarify scope (static vs dynamic) |
| "Check domain boundaries" / "Boundary violations" | `dynamic-boundary-validator` | `boundary-enforcer` | Code Tester | Architecture map loaded | No | If ambiguous: clarify runtime vs static check |

---

## L3 Architecture

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "Design this system" / "Architecture review" | `architecture-design` | `boundary-enforcer` | Code Tester | PLAN.md or AGENTS.md | No — requires trade-off reasoning | If ambiguous scope: present small/medium/large system options |
| "Evaluate architecture" / "Fitness check" | `architecture-fitness-function` | `architecture-design` | Code Tester | Architecture Design output | No | If ambiguous: clarify against which constraints |
| "Architecture decision gate" / "Approve this design" | `architecture-decision-gate` | `trade-off-analyzer` | Code Tester | Architecture Design output | No | If ambiguous: clarify decision criteria registry |
| "Evolve architecture" / "Migration plan" | `architecture-evolution` | `blast-radius-calculator` | Style Enforcer | Dependency graph indexed | No | If ambiguous: clarify target state |
| "Weave cross-cutting concerns" / "Add observability" | `cross-cutting-concern-weaver` | `architecture-design` | — | EXECUTE or VALIDATE phase | No | If ambiguous: present aspect catalog (security, logging, metrics, resilience, compliance, performance, i18n) |

---

## L4 Quality & Verification

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "Verify artifacts" / "Check completeness" | `artifact-verifier` | `spec-decomposer` | Any generation skill | Artifact files present | No | If ambiguous: clarify which artifact type |
| "Property-based tests" / "Generative testing" | `property-tester-pro` | `code-tester` | Style Enforcer | Source-under-test loaded | No | If ambiguous: clarify target (algorithms, parsers, state machines, numerical) |
| "Formal verification" / "Prove correctness" | `formal-verification-assistant` | `property-tester-pro` | Style Enforcer | Source-under-test loaded | No | If ambiguous: clarify tool (Z3, Coq, TLA+) |

---

## L5 Deployment & Release

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "Canary deploy" / "Progressive rollout" | `canary-orchestrator` | `blast-radius-calculator` | Code Tester | Deployment target configured | No | If ambiguous: clarify traffic split strategy |
| "Manage configs" / "Environment profiles" | `config-profile-manager` | `sandbox-executor` | Code Tester | None | Yes — read-only config review | If ambiguous: clarify environment (dev/staging/prod) |
| "Health check" / "Endpoint standard" | `health-endpoint-standard` | `slo-enforcer` | Code Tester | Service endpoints defined | No | If ambiguous: clarify L0 skill vs application health |

---

## L6 Operations

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "Chaos test" / "Resilience injection" | `chaos-engineering-suite` | `resilience-tester` | Code Tester | Staging/isolated environment | No | If ambiguous: clarify failure mode (network, CPU, memory, latency) |
| "Track tech debt" / "Debt ledger" | `technical-debt-ledger` | `self-reviewer` | Code Tester | Codebase indexed | Yes — read-only analysis | If ambiguous: clarify scope (file, module, system) |
| "Enforce SLOs" / "Latency budget" | `slo-enforcer` | `performance-validator` | Code Tester | SLO definitions loaded | No | If ambiguous: clarify which SLO (latency, error rate, throughput) |

---

## L7 Security & Compliance

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "API version check" / "Breaking changes" | `api-version-guard` | `api-contract-tester` | Code Tester | OpenAPI spec available | No | If ambiguous: clarify consumer vs provider perspective |
| "Secrets lifecycle" / "Rotate credentials" | `secrets-lifecycle-manager` | `secret-manager` | Any external routing | Vault configured | No — security-critical | If ambiguous: clarify rotate vs revoke vs audit |

---

## L8 External Integration

| User Intent Pattern | Primary Skill | Secondary | Never Load | Prerequisite | Gemini Eligible | Ambiguous Resolution |
|---|---|---|---|---|---|---|
| "Capture ADR" / "Machine-readable ADR" | `adr-machine-capture` | `architecture-design` | Code Tester | Decision context loaded | Yes — documentation drafting | If ambiguous: clarify MADR vs other format |
| "Publish calibration" / "Benchmark results" | `calibration-publisher` | `code-tester` | Code Tester | Dataset + protocol ready | Yes — read-only publishing | If ambiguous: clarify new release vs update |

---

## dev-* Interface Skills (On-Demand UX Layer)

These are ephemeral UX wrappers activated by `skill-orchestrator` when user intent matches a specific developer workflow.

| User Intent Pattern | Primary Skill | Underlying Ecosystem Skill(s) | Gemini Eligible |
|---|---|---|---|
| "Design API" / "OpenAPI spec" | `dev-api-designer` | `api-contract-tester`, `architecture-design` | Yes — read-only |
| "CI/CD pipeline" / "GitHub Actions" | `dev-ci-cd-pipeline` | `ci-cd-integrator` | Yes — read-only |
| "Generate code" / "Boilerplate" | `dev-code-generator` | `refactoring-engine`, `code-tester` | No — code generation |
| "Containerize" / "Dockerfile" | `dev-container-builder` | `sandbox-executor` | No — image build |
| "Database migration" | `dev-database-migrator` | `schema-explorer`, `architecture-design` | No — schema change |
| "Debug this" / "Error analysis" | `dev-debug-assistant` | `log-analyzer`, `hybrid-code-analyzer` | No — requires source context |
| "Check dependencies" / "CVE scan" | `dev-dependency-manager` | `dependency-manager`, `dependency-resolver` | No — live CVE feed |
| "Update docs" / "Generate README" | `dev-docs-maintainer` | `documentation-synthesizer` | Yes — documentation drafting |
| "Git workflow" / "Commit message" | `dev-git-workflow` | `style-enforcer`, `address-pr-comments` | Yes — read-only git history |
| "Incident response" / "On-call runbook" | `dev-incident-responder` | `runbook-generator`, `error-policy` | No — requires production context |
| "Infrastructure code" / "Terraform" | `dev-infrastructure-coder` | `infrastructure-as-code` | No — IaC generation |
| "Setup observability" / "Metrics" | `dev-observability-setup` | `dev-performance-profiler`, `slo-enforcer` | No — requires runtime |
| "Profile performance" / "Bottleneck" | `dev-performance-profiler` | `performance-validator` | No — requires execution |
| "Security scan" / "SAST" | `dev-security-scanner` | `security-auditor` | No — security-critical |
| "Generate tests" / "Test coverage" | `dev-test-automation` | `code-tester`, `property-tester-pro` | No — test execution |

---

## Fallback Behaviors

### Ambiguous Intent Resolution

When user intent matches multiple patterns with confidence below threshold:

```yaml
ambiguous_intent:
  action: PRESENT_OPTIONS
  max_options: 3
  fallback: ESCALATE_HUMAN
  presentation: |
    Your request could mean several things:
    1. [Option A] — Load [Skill A]
    2. [Option B] — Load [Skill B]
    3. [Option C] — Load [Skill C]
    Please clarify, or type "help" for more details.
```

### Skill-Not-Found Fallback

When no skill matches the intent:

```yaml
skill_not_found:
  action: NEAREST_NEIGHBOR
  threshold: 0.72
  fallback: INGEST_REPARSE
  behavior: |
    No skill matches "[user intent]". Did you mean:
    - [Nearest neighbor 1] (similarity: 0.81)
    - [Nearest neighbor 2] (similarity: 0.76)
    If none match, I can re-parse your request as a general task.
```

### Conflicting Skill Recommendations

When two skills claim the same intent:

```yaml
conflicting_recommendations:
  resolution: PRIORITY_BY_PHASE
  priority_order:
    - L0_ENFORCEMENT   # Safety > all
    - L1_GATEWAY       # Security gates
    - L2_INTENT        # Analysis
    - L3_ARCHITECTURE  # Design
    - L4_QUALITY       # Verification
    - L5_DEPLOYMENT    # Release
    - L6_OPERATIONS    # Ops
    - L7_SECURITY      # Compliance
    - L8_EXTERNAL      # Integration
    - DEV_UX           # Developer interface
  tiebreaker: HIGHEST_CONFIDENCE
```

### Gemini Eligibility Classification

Per the User Sovereignty Rule, eligibility is deterministic and NEVER overrides user cost preferences:

```yaml
gemini_eligible:
  phases: [INGEST, PLAN, DELIVER, REMEMBER]
  blocklist:
    - security_*
    - blast_radius
    - *_executor
    - secret_*
    - policy_*
  requires:
    - no_side_effects: true
    - no_secrets: true
    - no_code_generation: true
    - complexity: low
  fallback_on_ineligible: KIMI_LOCAL
```
