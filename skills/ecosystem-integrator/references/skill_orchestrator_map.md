# skill-orchestrator Intent Routing Map

This document shows the canonical intent-to-skill mappings defined by the ecosystem's `skill-orchestrator` (L2). The ecosystem-integrator QUERIES this mapping — it does not replace it.

## Canonical Routing Table

| User Intent | Primary Skill | Secondary | Guard |
|-------------|---------------|-----------|-------|
| "Understand this codebase" | `brownfield-intelligence` | `graphify`, `log-analyzer` | `tool-execution-gateway` |
| "Design the architecture" | `architecture-design` | `trade-off-analyzer`, `boundary-enforcer` | `blast-radius-calculator` |
| "Check dependencies" | `dependency-resolver` | `blast-radius-calculator` | `tool-execution-gateway` |
| "Run tests" | `code-tester` | `api-contract-tester` | `tool-execution-gateway` |
| "Refactor this" | `refactoring-engine` | `blast-radius-calculator`, `code-tester` | `tool-execution-gateway` |
| "Write docs" | `documentation-synthesizer` | `graphify` | `obsidian-setup` |
| "Address PR feedback" | `address-pr-comments` | `style-enforcer`, `code-tester` | `tool-execution-gateway` |
| "Check database schema" | `schema-explorer` | `architecture-design` | `tool-execution-gateway` |
| "Save session memory" | `obsidian-setup` | — | `obsidian-setup` |

## dev-* Skill Extensions

The dev-* skills wrap and extend the canonical routing:

| User Intent | dev-* Skill | Wraps Orchestrator Routing |
|-------------|-------------|---------------------------|
| "Generate code" | `dev-code-generator` | → `code-tester` + `security-auditor` + `style-enforcer` |
| "Write tests" | `dev-test-automation` | → `code-tester` + `property-tester-pro` |
| "Debug error" | `dev-debug-assistant` | → `log-analyzer` + `error-policy` + `drift-monitor` |
| "Set up CI/CD" | `dev-ci-cd-pipeline` | → `ci-cd-integrator` + `canary-orchestrator` |
| "Audit dependencies" | `dev-dependency-manager` | → `dependency-resolver` + `supply-chain-verifier` |
| "Profile performance" | `dev-performance-profiler` | → `performance-validator` + `drift-monitor` |
| "Scan security" | `dev-security-scanner` | → `security-auditor` + `adversarial-tester` |
| "Design API" | `dev-api-designer` | → `api-contract-tester` + `documentation-synthesizer` |
| "Migrate database" | `dev-database-migrator` | → `schema-explorer` + `refactoring-engine` |
| "Set up monitoring" | `dev-observability-setup` | → `drift-monitor` + `log-analyzer` |
| "Respond to incident" | `dev-incident-responder` | → `error-policy` + `log-analyzer` |
| "Generate IaC" | `dev-infrastructure-coder` | → `infrastructure-as-code` |
| "Write documentation" | `dev-docs-maintainer` | → `documentation-synthesizer` |
| "Git workflow" | `dev-git-workflow` | → `self-reviewer` + `address-pr-comments` |
| "Build containers" | `dev-container-builder` | → `sandbox-executor` |

## What the Integrator Does

When a user describes their task, the integrator:
1. **Queries** `skill-orchestrator` with the user's intent
2. **Receives** the canonical routing (primary + secondary skills)
3. **Maps** to dev-* equivalents if available (for user-friendly naming)
4. **Presents** the matched skills to the user
5. **Delegates** execution to the chosen skill via `tool-execution-gateway`

The integrator NEVER:
- Overrides the orchestrator's routing
- Skips the canonical safety guards
- Adds skills not recommended by the orchestrator
