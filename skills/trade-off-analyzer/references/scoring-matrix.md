# Weighted Scoring Matrix Template

## How to Use This Template

1. Select the project-type profile that best matches your context.
2. Copy the weights into the scoring matrix.
3. Score each alternative 1–5 (5 = best) against each attribute.
4. Multiply score × weight = weighted score.
5. Sum weighted scores per alternative. Highest total wins.
6. If the winning alternative is not the one the Architecture Design recommended, escalate to the human architect.

## Quality Attributes

| # | Attribute | Definition |
|---|-----------|------------|
| 1 | **Performance** | Latency, throughput, resource efficiency under expected load |
| 2 | **Cost** | Infrastructure, licensing, operational spend over 3 years |
| 3 | **Team Size** | Engineers required to build, run, and maintain |
| 4 | **Operational Complexity** | Monitoring, incident response, on-call burden, runbook count |
| 5 | **Time to Market** | Calendar time from decision to production for MVP scope |
| 6 | **Maintainability** | Ease of debugging, refactoring, onboarding new engineers |
| 7 | **Security Posture** | Attack surface, compliance coverage, auditability |

## Project-Type Profiles

### Profile A: Startup (Pre-Product-Market Fit)

**Priority**: Ship fast, learn faster. Optimize for speed and adaptability. Accept technical debt consciously.

| Attribute | Weight | Rationale |
|-----------|--------|-----------|
| Performance | 0.10 | Good enough is good enough |
| Cost | 0.15 | Burn rate matters; avoid heavy infra spend |
| Team Size | 0.15 | Small team; every headcount is precious |
| Operational Complexity | 0.10 | Prefer managed services over self-hosted |
| Time to Market | 0.30 | Fastest possible path to validated learning |
| Maintainability | 0.10 | Clean enough to iterate; perfection is a trap |
| Security Posture | 0.10 | Baseline hygiene; no SOC2 yet |

### Profile B: Enterprise (Revenue-Critical System)

**Priority**: Reliability, predictability, and cost control at scale. Long-term maintainability over short-term speed.

| Attribute | Weight | Rationale |
|-----------|--------|-----------|
| Performance | 0.15 | SLAs are contractual obligations |
| Cost | 0.15 | TCO drives budget approval |
| Team Size | 0.10 | Hiring is slow; prefer leverage over headcount |
| Operational Complexity | 0.15 | 24/7 ops; incident fatigue is a retention risk |
| Time to Market | 0.10 | Deadlines matter, but slip is better than outage |
| Maintainability | 0.20 | 5-year lifespan; turnover is inevitable |
| Security Posture | 0.15 | Compliance, audit, legal liability |

### Profile C: Regulated (Healthcare, Finance, Government)

**Priority**: Compliance, auditability, and defensibility. Every decision must be explainable to a regulator.

| Attribute | Weight | Rationale |
|-----------|--------|-----------|
| Performance | 0.10 | Must meet SLA, but not the primary driver |
| Cost | 0.10 | Secondary to compliance and risk |
| Team Size | 0.10 | Hiring constraints exist, but not dominant |
| Operational Complexity | 0.15 | Change management, approval gates, audit trails |
| Time to Market | 0.05 | Regulated release cycles are slow by design |
| Maintainability | 0.20 | Longevity, auditability, knowledge retention |
| Security Posture | 0.30 | Non-negotiable: encryption, access control, logging |

## Scoring Matrix Template

```markdown
### Trade-off Analysis: {decision_title}

**Project Profile**: {A | B | C | custom}
**Decision Date**: {YYYY-MM-DD}
**Review Date**: {YYYY-MM-DD}

| Alternative | Perf (w) | Cost (w) | Team (w) | Ops (w) | TTM (w) | Maint (w) | Sec (w) | **Total** |
|-------------|----------|----------|----------|---------|---------|-----------|---------|-----------|
| {alt_1} | {s}×{w}={ws} | ... | ... | ... | ... | ... | ... | **{sum}** |
| {alt_2} | {s}×{w}={ws} | ... | ... | ... | ... | ... | ... | **{sum}** |
| {alt_3} | {s}×{w}={ws} | ... | ... | ... | ... | ... | ... | **{sum}** |

**Legend**: s = raw score (1–5), w = weight, ws = weighted score

**Winner**: {alternative} with score {sum}
**Margin of victory**: {delta} points over second place
**Key differentiator**: {which attribute decided it}

### Justification for Each Score Divergence ≥2 Points

| Alternative | Attribute | Winner Score | This Score | Why the gap |
|-------------|-----------|--------------|------------|-------------|
| {alt} | {attr} | {win} | {this} | {reason} |

### Uncertainty Register

| Alternative | Primary Uncertainty | Label |
|-------------|---------------------|-------|
| {alt} | {claim} | [measured / estimated / assumed / unknown] |
```

## Example: Microservices vs Modular Monolith vs Do Nothing

**Context**: 6-engineer team building a B2B SaaS MVP. Startup profile (A).

| Alternative | Perf (0.10) | Cost (0.15) | Team (0.15) | Ops (0.10) | TTM (0.30) | Maint (0.10) | Sec (0.10) | **Total** |
|-------------|-------------|-------------|-------------|------------|------------|--------------|------------|-----------|
| Microservices | 4×0.10=0.40 | 2×0.15=0.30 | 1×0.15=0.15 | 1×0.10=0.10 | 2×0.30=0.60 | 2×0.10=0.20 | 3×0.10=0.30 | **2.05** |
| Modular Monolith | 3×0.10=0.30 | 4×0.15=0.60 | 4×0.15=0.60 | 4×0.10=0.40 | 4×0.30=1.20 | 3×0.10=0.30 | 3×0.10=0.30 | **3.70** |
| Do Nothing | 2×0.10=0.20 | 5×0.15=0.75 | 5×0.15=0.75 | 5×0.10=0.50 | 5×0.30=1.50 | 4×0.10=0.40 | 4×0.10=0.40 | **4.50** |

**Winner**: Do Nothing (4.50). In a 6-engineer startup, not building the feature yet outperforms building it the "right" way.

**Key insight**: The matrix forces the uncomfortable truth that the best architecture is often the one you don't build.
