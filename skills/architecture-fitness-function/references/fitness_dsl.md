# Fitness Constraint Definition DSL

Schema and syntax for defining architectural fitness function constraints. Constraints are declared in YAML files under `.fitness/` and consumed by `scripts/evaluate_fitness.py`.

## File Structure

```
.fitness/
├── constraints.yaml      # human-authored overrides
├── auto_gen.yaml         # generated from architecture-design output
└── audit.log             # evaluation history
```

## Top-Level Schema

```yaml
version: "1.0"
project: string          # project name, used in reports
generated_at: ISO-8601   # timestamp of generation or last edit
generated_by: string     # skill or human that produced this file

categories:              # list of category blocks
  - name: string         # category identifier: layering | cycles | coupling | complexity | api_surface
    weight: float        # [0.0, 1.0], contribution to overall score
    constraints: []      # list of constraint definitions
```

Category weights must sum to 1.0. If they do not, normalize at load time.

## Constraint Schema (Base)

Every constraint shares these fields:

```yaml
- name: string                 # machine-friendly identifier, kebab-case
  description: string          # human-readable explanation
  severity: critical | warning # affects scoring: critical = binary pass/fail
  enabled: bool                # default true; set false to disable without deleting
  scope:                       # where the constraint applies
    type: file | module | context | project
    include: [glob]            # patterns to include (e.g., ["src/**/*.py"])
    exclude: [glob]            # patterns to exclude (e.g., ["**/*_test.py"])
```

## Constraint Types

### 1. layer_rule — Cross-Layer Import Control

Prevent disallowed imports between architectural layers.

```yaml
- name: domain_no_ui
  type: layer_rule
  description: "Domain layer must not import UI or presentation layers"
  severity: critical
  enabled: true
  scope:
    type: file
    include: ["src/**/*.py"]
  layers:                       # ordered from bottom to top
    - name: "infrastructure"
      paths: ["src/infra/", "src/db/", "src/cache/"]
    - name: "application"
      paths: ["src/app/", "src/services/"]
    - name: "domain"
      paths: ["src/domain/", "src/models/"]
    - name: "presentation"
      paths: ["src/api/", "src/ui/", "src/controllers/"]
  rules:
    - from: "domain"
      forbidden_to: ["presentation", "infrastructure"]
      allowed_to: ["application"]   # optional whitelist
    - from: "application"
      forbidden_to: ["presentation"]
  scoring:
    mode: ratio                  # ratio | binary
    # ratio: score = 1.0 - (violations / total_imports_in_scope)
    # binary: score = 0.0 if any violation, else 1.0
```

**Scoring modes:**
- `ratio`: linear penalty per violation. Use when gradual erosion is acceptable.
- `binary`: single violation = full score loss. Use for invariant rules.

### 2. cycle_rule — Cyclic Dependency Detection

Detect cycles in the dependency graph at module or bounded-context scope.

```yaml
- name: no_module_cycles
  type: cycle_rule
  description: "No cyclic dependencies between modules"
  severity: critical
  enabled: true
  scope:
    type: module
    include: ["src/**/*.py"]
  graph_source: imports          # imports | declarations
  # imports: build graph from import statements
  # declarations: build graph from class/function references
  granularity: module            # module | package | context
  allow_self_cycles: false       # whether a module importing itself is allowed
  scoring:
    mode: binary                 # cycles are always binary
```

### 3. coupling_rule — Afferent/Efferent Coupling Limits

Bound the number of incoming and outgoing dependencies per module.

```yaml
- name: coupling_budget
  type: coupling_rule
  description: "Keep per-module coupling within budget"
  severity: warning
  enabled: true
  scope:
    type: module
    include: ["src/**/*.py"]
  thresholds:
    ce_max: 20                   # max efferent coupling (outgoing)
    ca_max: 30                   # max afferent coupling (incoming)
    instability_range: [0.2, 0.8] # I = Ce / (Ca + Ce)
  scoring:
    mode: ratio
    penalty_per_excess: 0.05     # subtract 0.05 per unit over threshold
```

**Instability (I)**: I = Ce / (Ca + Ce). Range [0, 1]. A module with I=0 is fully stable (only incoming). I=1 is fully unstable (only outgoing). The `instability_range` rejects modules outside the bounds.

### 4. complexity_rule — Cyclomatic and Cognitive Complexity Budget

Limit per-function complexity.

```yaml
- name: function_complexity
  type: complexity_rule
  description: "Functions must stay within complexity budget"
  severity: warning
  enabled: true
  scope:
    type: file
    include: ["src/**/*.py"]
    exclude: ["**/*_test.py", "**/migrations/**"]
  metrics:
    - metric: cyclomatic
      max: 10
    - metric: cognitive
      max: 15
    - metric: lines_of_code
      max: 50
  scoring:
    mode: ratio
    budget_scope: per_function   # per_function | cumulative
    # per_function: each function evaluated individually
    # cumulative: sum of all excess across all functions
```

**Metric definitions:**
- `cyclomatic`: McCabe complexity (branches + 1)
- `cognitive`: nested control flow depth score
- `lines_of_code`: non-blank, non-comment lines in function body

### 5. api_surface_rule — Public API Surface Control

Control what symbols are exposed publicly and prevent internal leakage.

```yaml
- name: api_surface_control
  type: api_surface_rule
  description: "Public API must not leak internal implementation details"
  severity: warning
  enabled: true
  scope:
    type: module
    include: ["src/**/*.py"]
  rules:
    - pattern: "public_from_internal"
      description: "Public module exports must not reference internal paths"
      internal_markers:
        paths: ["**/internal/**", "**/_*.py"]
        decorators: ["@internal", "@experimental"]
    - pattern: "stable_api_promise"
      description: "Symbols marked @stable must retain signature"
      stability_marker: "@stable"
      allow_signature_change: false
    - pattern: "export_consistency"
      description: "__all__ must be defined and complete"
      require_all_defined: true
      allow_undefined_all: false
  scoring:
    mode: ratio
```

## Threshold Calibration Guide

Defaults are starting points. Calibrate per project using historical data.

**Procedure:**
1. Run `scripts/evaluate_fitness.py --baseline` to collect uncalibrated metrics
2. Compute the 75th percentile of each metric across the codebase
3. Set thresholds at the 90th percentile for `warning`, 95th for `critical`
4. After 5 evaluation runs, tighten thresholds by 10% if no violations occur
5. If violation rate exceeds 20% of modules, loosen by 15%

**Reference table:**

| Metric | Small Project (<10k LOC) | Medium (10k-100k) | Large (>100k) |
|--------|-------------------------|-------------------|---------------|
| cyclomatic max | 10 | 10 | 12 |
| cognitive max | 12 | 15 | 18 |
| ce_max | 15 | 20 | 25 |
| ca_max | 20 | 30 | 40 |
| layers | 3-4 | 4-5 | 5-7 |

## Composite Constraints

Combine multiple constraints with logical operators for advanced rules.

```yaml
- name: complex_composite
  type: composite
  description: "Either low coupling OR high test coverage per module"
  operator: OR
  constraints:
    - ref: coupling_budget
    - ref: test_coverage_threshold
  scoring:
    mode: binary
```

Supported operators: `AND`, `OR`, `NOT`.

## Migration: Versioning and Evolution

When `architecture-evolution` modifies constraints, emit a `constraints_delta`:

```yaml
constraints_delta:
  added: [list of new constraint names]
  removed: [list of retired constraint names]
  modified:
    - name: string
      field: string           # which field changed
      old_value: any
      new_value: any
  version_bump: major | minor | patch
```

- `major`: new critical constraint added or threshold significantly tightened
- `minor`: warning constraint added, threshold relaxed, or scope expanded
- `patch`: description change, no semantic difference
