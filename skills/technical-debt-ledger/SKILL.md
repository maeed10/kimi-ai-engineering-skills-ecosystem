---
name: technical-debt-ledger
description: Cross-phase technical debt visibility and management skill. Integrates self-reviewer, blast-radius-calculator, and refactoring-engine to score debt by cost-of-delay, schedule repayments alongside features, and track trends over time. Use when reviewing code quality, planning sprints, making trade-off decisions, or prioritizing refactoring. Triggers on SOLID violations, complexity hotspots, duplication findings from self-reviewer; architectural trade-off annotations; structural anti-patterns from graphify; or when creating sprint/phase plans.
---

# Technical Debt Ledger

## Overview

Persist, score, and report technical debt across the codebase. Provide cost-of-delay scoring to prioritize repayment and integrate debt tasks into sprint/phase planning. Track trends via baselines stored in `.kimi/skills/memory-guard/`.

## When to Invoke

- `self-reviewer` flags SOLID violations, cyclomatic complexity >10, duplication >6 lines, or tight coupling
- `trade-off-analyzer` records deliberate architectural shortcuts (tag with `[TECHDEBT]`)
- `graphify` surfaces structural anti-patterns (god modules, circular deps)
- PLAN phase: factor existing debt into task estimates
- REFACTOR phase: output `DEBT_ROADMAP.md` with phased repayment plan

## Debt Entry Schema

Each debt item is a YAML record in `.kimi/skills/technical-debt-ledger/ledger.yml`:

```yaml
- id: TD-001
  created: "2024-01-15"
  updated: "2024-01-20"
  status: open          # open | scheduled | in_progress | resolved | accepted
  source: self-reviewer # self-reviewer | trade-off-analyzer | graphify | manual
  category: complexity  # complexity | duplication | coupling | architectural | test_coverage | documentation
  files:
    - src/core/auth.ts
  description: "Auth module cyclomatic complexity 34; deep nesting in validateToken()"
  blast_radius: 12      # number of call-site files affected
  change_frequency: 8   # commits touching this file in last 90 days
  complexity_trend: +15 # % change in complexity over last 30 days
  alignment: 2          # 1-5; 1=core domain, 5=peripheral
  remediation_hint: "Extract token validation strategies; apply Strategy pattern"
  scheduled_in: null    # sprint/phase id when scheduled
  resolved_by: null     # commit hash or task id
  cost_of_delay: 4.2    # computed score (see references/scoring_model.md)
```

## Workflow

### 1. Debt Detection & Ingestion

**From `self-reviewer` output:**
Parse review findings. Any severity >= `warning` with category `complexity`, `duplication`, `coupling`, or `maintainability` becomes a ledger entry. Auto-generate `id` as `TD-{next_seq}`.

**From `trade-off-analyzer`:**
When trade-offs produce `[TECHDEBT]` annotations, convert them to ledger entries with `source: trade-off-analyzer` and `category: architectural`.

**From `graphify`:**
Anti-patterns (god modules, circular dependencies) become entries with `category: coupling`. Set `blast_radius` from graph metrics.

**Ingestion rule:** Before adding, check for duplicates by `(files + category + description)` fuzzy match. Update existing entry if similarity > 0.8 rather than create duplicate.

### 2. Cost-of-Delay Scoring

Run `scripts/calculate_debt_score.py` against the ledger to compute `cost_of_delay` for each open item:

```bash
python3 scripts/calculate_debt_score.py ledger.yml --output ledger_scored.yml
```

The composite score (1.0 - 10.0) is a weighted product of four factors:

| Factor | Weight | Source |
|--------|--------|--------|
| Reach (blast radius) | 0.30 | blast-radius-calculator or `git grep` call-site count |
| Volatility (change frequency) | 0.25 | `git log --since="90 days ago" -- <file>` |
| Growth rate | 0.25 | `(current_complexity - baseline) / baseline * 100` |
| Architectural alignment | 0.20 | Manual 1-5 rating; 1=core domain, 5=peripheral |

See `references/scoring_model.md` for full formula, threshold tables, and calibration guidance.

**Interpretation:**
- `cost_of_delay >= 7.0`: Block feature work; repay in next sprint
- `5.0 - 6.9`: Schedule within current phase
- `3.0 - 4.9`: Queue for next phase
- `< 3.0`: Accept or address opportunistically (boy scout rule)

### 3. Repayment Scheduling

During PLAN phase, load `ledger_scored.yml` and create debt repayment tasks:

1. **High CoD (>=7.0):** Create dedicated refactoring tasks with explicit estimates (typically 2-4x the time of a feature task touching the same code). Insert before dependent feature tasks.
2. **Medium CoD (5.0-6.9):** Bundle as "debt repayment" sub-tasks within the feature task that touches the affected files. Apply "boy scout rule": leave the code cleaner than you found it.
3. **Low CoD (<5.0):** Add to a running `DEBT_BACKLOG` section in `DEBT_ROADMAP.md`. Address when opportune.

**Boy Scout Rule Automation:**
When a feature task modifies a file with an open low-severity debt entry, auto-append a sub-task:
```
- [ ] Boy-scout: <remediation_hint> (file: <path>, debt-id: TD-NNN)
```

### 4. Trend Analysis & Baselines

Store complexity/coupling/duplication baselines in `.kimi/skills/memory-guard/technical-debt-baseline.json`:

```json
{
  "timestamp": "2024-01-15T00:00:00Z",
  "metrics": {
    "avg_cyclomatic_complexity": 8.4,
    "max_cyclomatic_complexity": 34,
    "circular_dependencies": 3,
    "duplicated_blocks": 7,
    "avg_coupling_afferent": 4.2
  }
}
```

On each review cycle:
1. Load previous baseline
2. Compute current metrics (use `self-reviewer` or `graphify` output)
3. Calculate delta; update `complexity_trend` on matching ledger entries
4. Write new baseline with timestamp
5. Alert if any metric degrades >20% from baseline

### 5. Output: DEBT_ROADMAP.md

After scoring and scheduling, render the canonical debt roadmap:

```markdown
# Technical Debt Roadmap

Generated: 2024-01-20
Baseline: .kimi/skills/memory-guard/technical-debt-baseline.json

## Executive Summary
- Open debt items: 12
- High CoD (>=7.0): 2  -- blocking
- Medium CoD (5.0-6.9): 4 -- scheduled this phase
- Low CoD (<5.0): 6 -- backlog / boy-scout
- Trend vs baseline: +8% avg complexity (warning)

## Immediate Repayment (Next Sprint)
| ID | File | Description | CoD | Est. Effort | Owner |
|----|------|-------------|-----|-------------|-------|
| TD-001 | src/core/auth.ts | Auth complexity 34 | 8.2 | 3d | TBD |

## This Phase
| ID | File | Description | CoD | Bundled With | Boy-Scout Task |

## Backlog
| ID | File | Description | CoD | Trend |

## Trend Charts
<!-- ASCII sparklines or references to generated charts -->
Complexity: 8.4 -> 9.1 (+8%) ████████░░
Coupling:   4.2 -> 4.0 (-5%) ████░░░░░░
Duplication: 7 -> 9 (+29%) █████████░ ⚠️ threshold breach

## Resolved This Period
| ID | Resolved Date | Resolution | Verified By |
```

## Integration Points

| Skill | Direction | Data |
|-------|-----------|------|
| `self-reviewer` | ingest | Review findings (complexity, duplication, coupling) |
| `blast-radius-calculator` | ingest | Call-site reach for scoring |
| `trade-off-analyzer` | ingest | `[TECHDEBT]` annotations |
| `graphify` | ingest | Structural anti-patterns |
| `refactoring-engine` | trigger | Debt items marked `scheduled` or `in_progress` |
| `memory-guard` | persist | Baselines and ledger history |

## Quality Bar

- Every debt item has a computed `cost_of_delay` before scheduling
- No high-CoD item remains unscheduled for >1 sprint
- Trend baselines are updated every review cycle
- `DEBT_ROADMAP.md` is regenerated whenever the ledger changes
- Boy-scout sub-tasks are auto-generated for feature work touching indebted files
