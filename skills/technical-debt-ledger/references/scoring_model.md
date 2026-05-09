# Debt Scoring Model: Cost-of-Delay

## Composite Score Formula

```
cost_of_delay = 1 + 9 * normalize( reach^0.30 * volatility^0.25 * growth^0.25 * alignment_penalty^0.20 )
```

Where `normalize()` maps the raw product to a 1.0 - 10.0 scale using the reference maximum (see Calibration below). The `+1` floor ensures every debt item has a non-zero score.

## Factor Definitions

### 1. Reach (Blast Radius) — weight 0.30
Number of distinct files that depend on or call into the indebted module.

| Call-Sites | Raw Score | Tier |
|------------|-----------|------|
| 1-2 | 1 | isolated |
| 3-5 | 2 | local |
| 6-10 | 4 | component |
| 11-20 | 6 | subsystem |
| 21-50 | 8 | system |
| 51+ | 10 | widespread |

**Measurement:** Use `blast-radius-calculator` output, or run `git grep -l <symbol> | wc -l` for approximate reach.

### 2. Volatility (Change Frequency) — weight 0.25
Number of commits touching the file in the last 90 days.

| Commits (90d) | Raw Score | Tier |
|---------------|-----------|------|
| 0-1 | 1 | stable |
| 2-5 | 3 | occasional |
| 6-15 | 5 | frequent |
| 16-30 | 7 | volatile |
| 31-50 | 9 | hot |
| 51+ | 10 | churn |

**Measurement:** `git log --since="90 days ago" --oneline -- <file> | wc -l`

### 3. Growth Rate — weight 0.25
Percentage change in cyclomatic complexity (or duplication blocks) over the last 30 days.

| % Change | Raw Score | Trend |
|----------|-----------|-------|
| -20% or lower | 1 | improving |
| -19% to -5% | 2 | stable |
| -4% to +4% | 3 | flat |
| +5% to +15% | 5 | growing |
| +16% to +30% | 7 | accelerating |
| +31% or higher | 10 | exploding |

**Measurement:** Compare current `self-reviewer`/`graphify` output against `.kimi/skills/memory-guard/technical-debt-baseline.json`.

### 4. Architectural Alignment Penalty — weight 0.20
Inversely scored: core domain debt is more costly.

| Rating | Raw Score | Meaning |
|--------|-----------|---------|
| 1 (core domain) | 10 | business-critical path |
| 2 | 7 | important service |
| 3 | 5 | utility / infrastructure |
| 4 | 3 | peripheral feature |
| 5 (outer edge) | 1 | experimental / optional |

The alignment **penalty** uses the inverse: `alignment_penalty = 11 - alignment_rating`.

## Normalization (Calibration)

The raw product maximum (all factors at 10) is `10^1.0 = 10`. The normalize function is:

```
normalize(x) = clamp( log10(x) / log10(10), 0, 1 ) = clamp( log10(x), 0, 1 )
```

In practice, use a piecewise linear map against observed maximums in the current codebase to avoid score compression:

```python
def normalize(raw_product, ledger_max):
    if ledger_max <= 1.0:
        return 0.5
    return min(1.0, max(0.0, (raw_product - 1.0) / (ledger_max - 1.0)))
```

Recalibrate `ledger_max` after every scoring run (use the 95th percentile raw product across open items).

## Score Thresholds

| CoD Range | Priority | Action |
|-----------|----------|--------|
| >= 7.0 | Critical | Block feature work; dedicated sprint task |
| 5.0 - 6.9 | High | Schedule within current phase |
| 3.0 - 4.9 | Medium | Queue for next phase; boy-scout if touched |
| < 3.0 | Low | Accept or opportunistic cleanup |

## Complexity Trend Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Avg cyclomatic complexity | +10% from baseline | +20% |
| Max cyclomatic complexity | +15% from baseline | +30% |
| Circular dependencies | +1 new | +3 new |
| Duplicated blocks | +2 new | +5 new |

When a critical threshold is breached, auto-escalate all affected debt items by +1.0 CoD.

## Multi-File Debt Items

When a debt item spans multiple files, compute each factor as:
- **Reach:** Union of all call-sites across all files
- **Volatility:** Sum of commits across all files (deduplicate same-commit touches)
- **Growth:** Maximum growth rate among the files
- **Alignment:** Minimum alignment rating (most core) among the files
