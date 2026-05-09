# FITNESS_REPORT.md Template

Report generated after each fitness evaluation. Filename: `FITNESS_REPORT.md`.

## Header Block

```markdown
# Fitness Report — {project_name}

| Field | Value |
|---|---|
| Run ID | `{uuid}` |
| Timestamp | `{ISO-8601}` |
| Trigger | `post-execute` | `evolution` | `manual` |
| Baseline Run | `{uuid or "first-run"}` |
| Overall Score | `{0.00-1.00}` |
| Gate | **PROCEED** | **WARNING** | **HALT** |
```

## Score Summary

```markdown
## Score Summary

| Category | Weight | Score | Status | Delta | Trend |
|---|---|---|---|---|---|
| Layering | 0.25 | 0.95 | PASS | +0.02 | improving |
| Cycles | 0.25 | 1.00 | PASS | 0.00 | stable |
| Coupling | 0.20 | 0.72 | WARNING | -0.08 | regressing |
| Complexity | 0.15 | 0.88 | PASS | +0.01 | improving |
| API Surface | 0.15 | 0.55 | CRITICAL | -0.15 | regressing |
| **Overall** | **1.00** | **0.84** | **WARNING** | **-0.03** | **regressing** |
```

**Trend rules:**
- `improving`: delta >= +0.01
- `stable`: delta in (-0.01, +0.01)
- `regressing`: delta <= -0.01

## Top Violations

List up to 5 violations ordered by severity (critical first), then by file path.

```markdown
## Top Violations

### 1. [CRITICAL] Cyclic dependency detected
- **Constraint**: `no_module_cycles`
- **Files**: `src/domain/order.py` -> `src/app/order_service.py` -> `src/domain/order.py`
- **Details**: 3-module cycle involving domain and application layers
- **Remediation**: Extract shared interface into `src/domain/interfaces/order_repo.py`; use dependency inversion.

### 2. [WARNING] Efferent coupling exceeds threshold
- **Constraint**: `coupling_budget`
- **File**: `src/app/checkout_service.py`
- **Details**: Ce=28, threshold=20, excess=8
- **Remediation**: Split into `CheckoutValidator` + `CheckoutProcessor`; move external service calls behind facade.

### 3. [WARNING] Internal path leaked in public API
- **Constraint**: `api_surface_control`
- **File**: `src/api/public/routes.py:45`
- **Details**: `from src.app.internal._pricing import _calculate_discount`
- **Remediation**: Move `_calculate_discount` to `src/domain/pricing.py` or expose via stable interface.
```

## Per-Category Detail

Expand each category with full violation lists.

```markdown
## Layering (score: 0.95)

| Status | Count | Detail |
|---|---|---|
| PASS | 120 imports | No violations detected |

### Rules Evaluated
- `domain_no_ui`: 0 violations of 45 imports — PASS
- `infra_no_domain`: 0 violations of 30 imports — PASS
```

```markdown
## Cycles (score: 0.00)

| Status | Count | Detail |
|---|---|---|
| CRITICAL | 1 cycle | 3 modules involved |

### Detected Cycles
1. `src/domain/order.py` -> `src/app/order_service.py` -> `src/domain/order.py`
   - Length: 3 modules
   - Layers crossed: domain, application
   - Suggested break point: `src/app/order_service.py`
```

```markdown
## Coupling (score: 0.72)

| Module | Ce | Ca | I | Status |
|---|---|---|---|---|
| `src/app/checkout_service.py` | 28 | 5 | 0.85 | WARNING |
| `src/domain/user.py` | 18 | 25 | 0.42 | PASS |

### Thresholds
- Ce max: 20 (penalty: -0.05 per excess)
- Ca max: 30
- Instability range: [0.20, 0.80]
```

```markdown
## Complexity (score: 0.88)

| Function | File | Cyclomatic | Cognitive | LOC | Status |
|---|---|---|---|---|---|
| `process_payment` | `src/app/payment.py:89` | 14 | 18 | 67 | WARNING |
| `validate_order` | `src/domain/order.py:34` | 8 | 10 | 42 | PASS |

### Budget
- Cyclomatic max: 10
- Cognitive max: 15
- LOC max: 50
- Functions over budget: 4 / 32 (12.5%)
```

```markdown
## API Surface (score: 0.55)

| Issue | File | Symbol | Status |
|---|---|---|---|
| Internal import leaked | `src/api/public/routes.py:45` | `_calculate_discount` | CRITICAL |
| Missing `__all__` | `src/domain/models.py` | — | WARNING |
| `@stable` signature changed | `src/api/client.py:22` | `create_order` | CRITICAL |

### Rules
- `public_from_internal`: 1 violation
- `export_consistency`: 3 violations
- `stable_api_promise`: 1 violation
```

## Trend Analysis

Show the last 5 runs for context.

```markdown
## Trend (Last 5 Runs)

| Run | Date | Overall | Layering | Cycles | Coupling | Complexity | API Surface |
|---|---|---|---|---|---|---|---|
| 5 (current) | 2024-01-15 | 0.84 | 0.95 | 1.00 | 0.72 | 0.88 | 0.55 |
| 4 | 2024-01-14 | 0.87 | 0.93 | 1.00 | 0.80 | 0.87 | 0.70 |
| 3 | 2024-01-13 | 0.89 | 0.94 | 1.00 | 0.82 | 0.86 | 0.75 |
| 2 | 2024-01-12 | 0.85 | 0.90 | 1.00 | 0.78 | 0.85 | 0.72 |
| 1 | 2024-01-11 | 0.82 | 0.88 | 0.00 | 0.75 | 0.84 | 0.80 |
```

## Remediation Plan

When overall score < 0.80, auto-generate a prioritized remediation plan.

```markdown
## Remediation Plan (Auto-Generated)

Priority is computed as: `(1 - score) * weight * severity_multiplier`
where severity_multiplier: critical=3, warning=1.

| Priority | Action | Category | Effort | Expected Impact |
|---|---|---|---|---|
| P0 | Break cycle via dependency inversion interface | Cycles | 2h | +0.25 overall |
| P1 | Extract facade for checkout_service external calls | Coupling | 3h | +0.05 overall |
| P2 | Refactor `process_payment` into 3 functions | Complexity | 1h | +0.02 overall |
| P3 | Add `__all__` to domain/models.py | API Surface | 15min | +0.03 overall |
```

## Gate Decision

Explicit decision block for phase controller consumption.

```markdown
## Gate Decision

```
RECOMMENDATION: WARN
OVERALL SCORE: 0.84
DELTA: -0.03

REASON: API Surface category is CRITICAL (0.55). Coupling category is WARNING (0.72).
        All other categories PASS.

ACTION: Proceed to DELIVER with FITNESS_REPORT.md attached to all artifacts.
        Address P0 and P1 items before next EXECUTE phase.
```
```

For HALT state:

```markdown
## Gate Decision

```
RECOMMENDATION: HALT
OVERALL SCORE: 0.52
DELTA: -0.18

REASON: Critical violations in Cycles (0.00) and API Surface (0.45).
        Regressions exceed 10% threshold from baseline.

ACTION: DELIVER phase BLOCKED. Resolve all CRITICAL violations.
        Required: architecture-design review or human override.
```
```

## Footer

```markdown
---
Report generated by `architecture-fitness-function` skill
Run ID: {uuid}
Next recommended evaluation: after next EXECUTE phase completion
```
