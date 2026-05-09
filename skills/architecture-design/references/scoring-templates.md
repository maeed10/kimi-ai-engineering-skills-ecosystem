# Architecture Alternative Scoring Templates

Comprehensive templates and worksheets for generating, scoring, and documenting architectural alternatives. Used by the Architecture Design skill's "Alternative Generation & Scoring" section.

---

## 1. Alternative Generation Worksheet

### Step 1: Frame the Decision
| Field | Value |
|-------|-------|
| Decision title | |
| Problem statement | |
| Constraints (hard) | |
| Constraints (soft) | |
| Quality attribute priorities (ranked) | |

### Step 2: Generate Alternatives

For each alternative, capture:
- **Name**: Short identifier
- **Description**: 1-2 sentences
- **Pattern(s) used**: Named architectural pattern(s)
- **Key trade-off**: What is sacrificed?
- **Assumptions**: List of unverified assumptions with confidence levels

Minimum set:
1. **Status Quo** — keep current architecture, document its limits
2. **Alternative A** — evolutionary change (low risk, incremental)
3. **Alternative B** — transformative change (higher risk, higher reward)
4. *(Optional)* **Alternative C** — radical change (exploratory, may violate constraints)

### Step 3: Filter Absurd Options

Apply a hard-constraint filter before scoring:
- Violates compliance mandate (PCI DSS, GDPR, HIPAA)? → Eliminate
- Exceeds budget by >2x? → Eliminate or rescope
- Requires team size >2x current? → Eliminate or phase
- Uses deprecated/unmaintained technology? → Eliminate

---

## 2. Scoring Matrix Template

### Quality Attributes Library

Select ≥6 from this library based on stakeholder priorities:

| # | Attribute | Definition | Typical Measurement |
|---|-----------|------------|---------------------|
| 1 | Performance | Response time under load | p50/p95/p99 latency (ms) |
| 2 | Throughput | Requests processed per second | RPS at saturation |
| 3 | Scalability | Ability to handle growth | Max concurrent users / data volume |
| 4 | Availability | Uptime percentage | SLA (99.9%, 99.99%) |
| 5 | Reliability | Mean time between failures | MTBF / MTTR |
| 6 | Security | Defense against threats | OWASP coverage, audit pass rate |
| 7 | Maintainability | Ease of modification | Cyclomatic complexity, test coverage |
| 8 | Operability | Ease of deployment and monitoring | Deployment frequency, mean recovery time |
| 9 | Cost | Total cost of ownership | Infra + personnel + licensing ($/month) |
| 10 | Time-to-market | Speed of delivery | Weeks to first production deploy |
| 11 | Testability | Ease of verifying correctness | Unit test coverage, integration test count |
| 12 | Modifiability | Ease of extending functionality | Change lead time, refactoring frequency |

### Weighted Scoring Matrix

```markdown
| Alternative | Attr 1 (w%) | Attr 2 (w%) | Attr 3 (w%) | Attr 4 (w%) | Attr 5 (w%) | Attr 6 (w%) | Weighted Score |
|-------------|-------------|-------------|-------------|-------------|-------------|-------------|----------------|
| Status Quo  | x (score)   | x           | x           | x           | x           | x           | Σ(score×w)     |
| Alt A       | x           | x           | x           | x           | x           | x           | Σ(score×w)     |
| Alt B       | x           | x           | x           | x           | x           | x           | Σ(score×w)     |
```

**Scoring rubric** (1-10 scale):
- 1-3: Poor — significant risk or known anti-pattern
- 4-5: Fair — viable but with notable weaknesses
- 6-7: Good — solid fit with manageable trade-offs
- 8-9: Excellent — strong fit, minor concerns only
- 10: Exceptional — ideal fit, negligible risk

### Scoring Justification Template

For every score cell, document:
```
Score: N
Rationale: [2-3 sentences explaining why this alternative scores N on this attribute]
Evidence: [Measured data, benchmark result, or cited reference]
Assumption: [What must be true for this score to hold]
```

---

## 3. Sensitivity Analysis Worksheet

Identify which weight changes would flip the winner.

```markdown
| Scenario | Weight Change | New Winner | Impact |
|----------|--------------|------------|--------|
| Security weight +10% | Security: 30% → 40% | | |
| Cost weight +15% | Cost: 10% → 25% | | |
| Performance weight −10% | Performance: 25% → 15% | | |
```

If a single attribute weight change flips the winner, the decision is **sensitive** and requires additional stakeholder alignment before proceeding.

---

## 4. Silent Debt Documentation Template

Every architectural recommendation contains assumptions that lack evidence. Document them explicitly.

```markdown
| # | Assumption | Confidence | Validation Path | Owner | Due Date |
|---|------------|------------|-----------------|-------|----------|
| 1 | | High / Medium / Low | | | |
| 2 | | | | | |
```

**Confidence levels**:
- **High**: Supported by measurement, benchmark, or production evidence
- **Medium**: Supported by analogy or expert judgment; requires validation
- **Low**: Speculative; must be validated before implementation proceeds

---

## 5. Decision Record Template (Post-Scoring)

After scoring, document the final decision:

```markdown
# ADR-NNNN: [Decision Title]

## Status
Proposed / Accepted

## Context
[Problem statement and forces]

## Options Considered
| Option | Weighted Score | Key Strength | Key Weakness |
|--------|----------------|--------------|--------------|
| Status Quo | | | |
| Alternative A | | | |
| Alternative B | | | |

## Decision
[Selected option and rationale]

## Consequences
[Positive and negative consequences, including trade-offs]

## Silent Debt
[Assumptions documented from worksheet above]

## Validation Plan
[How and when assumptions will be validated]
```

---

## 6. Example: API Gateway Selection

### Alternatives
1. **Status Quo**: No gateway; direct service-to-service calls
2. **Alternative A**: Kong (open-source, self-hosted)
3. **Alternative B**: AWS API Gateway (managed, cloud-native)
4. **Alternative C**: Envoy + Istio (service mesh, Kubernetes-native)

### Scoring Matrix

| Alternative | Performance (20%) | Security (20%) | Operability (20%) | Cost (15%) | Scalability (15%) | Time-to-market (10%) | Score |
|-------------|-------------------|----------------|-------------------|------------|-------------------|----------------------|-------|
| Status Quo  | 7 | 4 | 5 | 9 | 3 | 9 | 5.75 |
| Kong        | 8 | 8 | 6 | 7 | 8 | 6 | 7.15 |
| AWS APIGW   | 7 | 9 | 9 | 5 | 9 | 8 | 7.95 |
| Envoy+Istio | 9 | 8 | 5 | 5 | 9 | 4 | 7.10 |

**Winner**: AWS API Gateway (7.95)

**Sensitivity analysis**: If Cost weight increases to 25% and Scalability drops to 10%, Kong wins (7.30 vs 7.25). Decision is moderately sensitive to cost priority.

---

*Version: 1.0 | Last updated: 2026-07*
