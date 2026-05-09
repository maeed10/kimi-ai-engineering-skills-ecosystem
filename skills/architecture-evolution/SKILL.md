---
name: architecture-evolution
description: >
  Suggests and plans architectural migrations (monolith-to-microservice, framework upgrades,
  modularization) based on dependency graphs and codebase analysis. Uses migration patterns
  (Strangler Fig, Branch by Abstraction, Parallel Run) to generate phased, validated plans.
  Trigger when a codebase shows signs of structural debt, when integration with Graphify/Brownfield
  reveals coupling hotspots, or when a user requests migration planning.
---

# Architecture Evolution

## What it does
Analyzes dependency graphs and codebase metrics to detect modularization opportunities, selects appropriate migration patterns, and produces phased migration plans with rollback procedures and validation criteria. Coordinates with Refactoring Engine for execution and CI/CD Integrator for staged rollout.

## When to use
- Dependency analysis (Graphify/Brownfield) reveals tight coupling clusters or oversized modules
- User requests monolith-to-microservice, framework upgrade, or codebase modularization
- Architecture Design ADRs indicate planned structural changes requiring phased execution
- Brownfield Intelligence flags components with excessive inbound/outbound dependencies
- A new service boundary is identified and needs extraction planning

## Key capabilities
1. **Migration detection** — Identify high-cohesion clusters and low-coupling boundaries from dependency graphs
2. **Pattern selection** — Match situation to Strangler Fig, Branch by Abstraction, Parallel Run, or Big Bang
3. **Plan generation** — Produce phased plans with data migration strategy, rollback points, and communication plan
4. **Risk assessment** — Use Blast Radius Calculator to score each phase; block high-risk moves without human approval
5. **Execution coordination** — Delegate code transformations to Refactoring Engine
6. **Validation planning** — Define per-phase tests, contract checks, and performance baselines

## Workflow
1. **Load context** — Read dependency graph (Graphify), coupling metrics (Brownfield), ADRs (Architecture Design), and constraints (Boundary Enforcer)
2. **Detect candidates** — Run clustering heuristics on dependency graph to find extraction candidates; flag modules with >1 downstream consumer as shared-library risks
3. **Evaluate constraints** — Assess team size, risk tolerance, uptime SLA, data consistency requirements
4. **Select pattern** — Choose migration pattern with written justification; default to incremental (Strangler Fig or Branch by Abstraction)
5. **Generate phased plan** —
   - Phase 1: Boundary definition + abstraction layer
   - Phase 2: Dual implementation (old + new)
   - Phase 3: Traffic shifting / feature toggle
   - Phase 4: Old path deprecation
   - Phase 5: Cleanup
6. **Calculate blast radius** — Run Blast Radius Calculator per phase; annotate scores in plan
7. **Define validation criteria** — Per-phase: unit/integration tests, API contract tests (API Contract Tester), performance baselines (Performance Validator)
8. **Generate rollback procedures** — Write exact rollback steps for each phase with verification checkpoints
9. **Coordinate execution** — Pass code transformation specs to Refactoring Engine; feed pipeline stages to CI/CD Integrator
10. **Produce deliverables** — Migration plan document, risk register, validation checklist, rollback runbook

## Safety highlights
- **NEVER** recommend Big Bang migration without explicit human approval and a written risk analysis
- **ALWAYS** provide a rollback plan for every migration phase with a named verification checkpoint
- **NEVER** proceed with migration if Blast Radius score > 8 without human confirmation
- **ALWAYS** maintain data integrity guarantees during data migration phases; prefer CDC or dual-write over in-place mutation
- **NEVER** extract a module without verifying its external dependencies are well-defined and interface-contracted
- **ALWAYS** validate that the extracted module can be built and tested independently before integration
- **NEVER** schedule a cutover without a defined performance baseline and a comparison plan
- **ALWAYS** preserve backward compatibility during Phase 2–3; breaking changes only in Phase 4 with explicit approval

## Integration with other skills
| Skill | Direction | Usage |
|---|---|---|
| **Graphify** | Reads | Dependency graphs, module adjacency, call graphs |
| **Brownfield Intelligence** | Reads | Coupling metrics, hotspot detection, code smells |
| **Architecture Design** | Reads | ADRs, system context, constraint boundaries |
| **Boundary Enforcer** | Reads | Allowed/disallowed dependencies, module boundaries |
| **Blast Radius Calculator** | Uses | Impact scoring for each proposed phase |
| **Refactoring Engine** | Coordinates | Code transformation execution (extract module, rename, move) |
| **API Contract Tester** | Coordinates | Backward compatibility validation during dual-run |
| **CI/CD Integrator** | Feeds into | Staged rollout pipeline, feature toggle wiring |
| **Performance Validator** | Coordinates | Before/after performance comparison, regression detection |

## References
- `references/migration-patterns.md` — Pattern definitions, decision matrix, trade-off table (Strangler Fig, Branch by Abstraction, Parallel Run, Big Bang)

## Scripts
- `scripts/analyze-migration.py` — Dependency graph clustering and extraction-candidate scoring template
