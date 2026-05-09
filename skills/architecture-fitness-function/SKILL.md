---
name: architecture-fitness-function
description: Continuous architectural constraint validation skill that defines measurable fitness functions from architecture plans and enforces them after every EXECUTE phase. Use when validating that code changes preserve architectural integrity, when defining new architecture constraints, or when evaluating fitness trends. Can auto-halt DELIVER phase on critical violations.
---

# Architecture Fitness Function

Continuously validate architectural constraints after every EXECUTE phase. Define measurable fitness functions from architecture plans, compute scores from codebase metrics, and enforce gates on the DELIVER phase.

## Trigger Conditions

Run this skill when:
- An EXECUTE phase completes and produces code changes
- `architecture-design` emits a new or updated architectural plan
- `boundary-enforcer` defines or revises bounded contexts
- `self-reviewer` flags structural or dependency changes
- `architecture-evolution` proposes a migration path
- Any module's import graph, public API surface, or complexity metrics change

## Core Workflow

### 1. Load Architecture Constraints

Read the active architecture constraint set from the nearest `.fitness/` directory or inline plan metadata. If no constraints exist, auto-generate a baseline set from the codebase structure using the DSL in `references/fitness_dsl.md`.

Load in this priority order:
1. `.fitness/constraints.yaml` — project-specific overrides
2. `.fitness/auto_gen.yaml` — auto-generated from architecture-design
3. Inline constraints from the current architecture plan metadata

### 2. Evaluate Fitness Functions

Execute `scripts/evaluate_fitness.py` against the codebase. The script computes per-constraint scores (0.0–1.0) and aggregates them into category scores.

**Evaluation order:**
1. Layering rules — verify allowed/disallowed cross-layer imports
2. Cyclic dependency prohibitions — detect cycles in module dependency graph
3. Coupling thresholds — measure afferent/efferent coupling per module
4. Complexity budgets — compute cyclomatic and cognitive complexity per function
5. API surface constraints — count public symbols vs. internal leakage

Each constraint produces:
```
score:        float  [0.0, 1.0]
weight:       float  [0.0, 1.0], sums to 1.0 per category
status:       PASS | WARNING | CRITICAL
violations:   list of {file, line, message, severity}
delta:        float  change from previous run (+/-)
```

### 3. Produce FITNESS_REPORT.md

Write the report to `FITNESS_REPORT.md` using the schema in `references/fitness_report_template.md`. The report MUST include:

- Overall fitness score (weighted average of all categories)
- Per-category scores with PASS/WARNING/CRITICAL status
- Trend delta vs. previous run
- Top 5 violations with file paths and remediation suggestions
- Explicit gate recommendation: `PROCEED | WARN | HALT`

**Score thresholds:**
| Score Range | Status   | Gate Action                          |
|-------------|----------|--------------------------------------|
| 0.80 – 1.00 | PASS     | Proceed to DELIVER unconditionally   |
| 0.60 – 0.79 | WARNING  | Attach FITNESS_REPORT.md to all downstream deliverables; DELIVER proceeds with advisory |
| 0.00 – 0.59 | CRITICAL | HALT DELIVER phase; block merge/release until violations resolved |

### 4. Phase Controller Integration

After producing FITNESS_REPORT.md, signal the phase controller:

```
IF overall_score >= 0.80:
    signal: PROCEED
    attach: none

IF 0.60 <= overall_score < 0.80:
    signal: WARN
    attach: FITNESS_REPORT.md to all PRs, release notes, and deploy artifacts

IF overall_score < 0.60:
    signal: HALT
    block: DELIVER phase
    require: explicit override from architecture-design or human approval
    log: violation details to fitness_audit.log
```

### 5. Evolution Support

When `architecture-evolution` proposes a migration:
1. Load the evolution plan's expected post-migration constraints
2. Run pre-migration fitness evaluation to establish baseline
3. After migration EXECUTE, run post-migration evaluation
4. Compute delta report: `post_score - pre_score`
5. If delta < -0.1 (regression > 10%), flag as CRITICAL regardless of absolute score
6. Evolution plan MUST include updated `constraints_delta` describing constraint additions, removals, or threshold changes

## Auto-Generation from Architecture Plans

When `architecture-design` produces a plan, derive constraints automatically:

**From layer definitions:**
```yaml
layer_rules:
  - name: domain_no_ui
    description: "Domain layer must not import UI layer"
    source_layers: ["domain"]
    forbidden_layers: ["ui", "presentation"]
    severity: critical
```

**From bounded contexts:**
```yaml
cycle_rules:
  - name: no_context_cycles
    description: "No cyclic dependencies between bounded contexts"
    scope: "context-boundary"
    severity: critical

coupling_rules:
  - name: context_coupling_limit
    description: "Each bounded context may depend on at most 3 others"
    max_outgoing: 3
    severity: warning
```

**From API contracts:**
```yaml
api_surface_rules:
  - name: stable_api_promise
    description: "Public API surface changes must be backward-compatible"
    stability_marker: "@stable"
    allow_breaking: false
    severity: critical
```

## Fitness Function Catalog

### 1. Layering (weight: 0.25)
Detect illegal cross-layer imports. Score = 1.0 - (violation_count / total_imports).

### 2. Cyclic Dependencies (weight: 0.25)
Detect cycles in module graph via DFS. Score = 1.0 if acyclic; 0.0 if any cycle exists. Cycles are binary — one violation is a full breach.

### 3. Coupling (weight: 0.20)
Measure average coupling per module. Score = 1.0 - (avg_coupling / threshold). Threshold defaults: efferent 20, afferent 30.

### 4. Complexity (weight: 0.15)
Measure per-function complexity. Score = 1.0 - (functions_over_budget / total_functions). Budget defaults: cyclomatic 10, cognitive 15.

### 5. API Surface (weight: 0.15)
Count public symbols leaking internals. Score = 1.0 - (leaked_symbols / total_public_symbols). Leaked = public but marked `@internal` or importing from `internal/` paths.

## Downstream Integration

- `self-reviewer`: Runs fitness evaluation as the final step of its structural analysis; feeds violation list into review comments
- `boundary-enforcer`: Provides bounded context definitions consumed by cycle_rules and coupling_rules
- `architecture-evolution`: Must emit `constraints_delta` section; fitness function validates migration against this delta
- DELIVER phase: Reads FITNESS_REPORT.md gate recommendation; enforces HALT by failing CI checks or blocking merge

## Audit Trail

Every evaluation appends a record to `.fitness/audit.log`:
```json
{
  "timestamp": "ISO-8601",
  "run_id": "uuid",
  "overall_score": 0.0,
  "categories": {"layering": 1.0, "cycles": 0.0, ...},
  "gate": "PROCEED|WARN|HALT",
  "trigger": "post-execute|evolution|manual",
  "violations_count": 0
}
```

Keep the last 100 runs. Rotate older records to `.fitness/audit.log.N`.
