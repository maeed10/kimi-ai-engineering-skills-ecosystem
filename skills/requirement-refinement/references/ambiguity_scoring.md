# Ambiguity Scoring Reference

## Scoring Dimensions

Five dimensions weighted by impact on implementation certainty.

### 1. Criteria Clarity (weight: 0.30)

Acceptance criteria must be verifiable by test. Score 1.0 if absent; 0.0 if fully quantified.

| Score | Signal | Example |
|-------|--------|---------|
| 0.0 | Quantifiable with bounds | "Response time < 200ms at p99 under 1000 concurrent users" |
| 0.25 | Quantifiable without bounds | "Response time should be fast" |
| 0.50 | Binary / presence only | "System should log errors" |
| 0.75 | Vague positive | "User-friendly error handling" |
| 1.0 | None | No acceptance criteria listed |

**Hedge word detection**: "appropriate", "relevant", "as needed", "user-friendly", "efficient", "robust", "flexible", "scalable" (without numbers), "fast", "easy", "intuitive", "comprehensive".

### 2. NFR Consistency (weight: 0.25)

Check for conflicting non-functional requirements on the same task or story.

**Common conflict pairs**:

| Conflict A | Conflict B | Why |
|------------|------------|-----|
| "real-time" | "eventual consistency" | Latency vs consistency model |
| "99.999% uptime" | "zero redundancy" | Availability requires redundancy |
| "sub-100ms response" | "deep audit logging" | I/O overhead contradicts latency |
| "stateless" | "session affinity" | Architectural contradiction |
| "no caching" | "high throughput" | Throughput often requires caching |
| "open to all users" | "strict RBAC" | Access model contradiction |

Score 1.0 if a conflict exists and is unresolved. Score 0.0 if all NFRs are compatible or explicitly prioritized (e.g., "latency over durability for this endpoint").

### 3. Domain Precision (weight: 0.20)

Every domain-specific term must be defined or resolvable from context.

| Score | Signal |
|-------|--------|
| 0.0 | All terms defined in glossary or codebase |
| 0.25 | Terms defined by inference from usage |
| 0.50 | One undefined term, context makes it guessable |
| 0.75 | Multiple undefined terms or one critical term undefined |
| 1.0 | Core domain concept has no definition anywhere |

**Detection method**: Extract all nouns/noun phrases that are not common vocabulary or technology names. Check against: (a) requirement glossary, (b) codebase identifiers, (c) `brownfield-intelligence` index. Missing from all three = undefined.

### 4. Scope Boundaries (weight: 0.15)

Clear delineation of what is in-scope, out-of-scope, and deferred.

| Score | Signal |
|-------|--------|
| 0.0 | Explicit in-scope, out-of-scope, and deferred lists |
| 0.33 | In-scope defined, out-of-scope implied |
| 0.66 | Only in-scope defined, no boundary discussion |
| 1.0 | No scope discussion; "we'll know it when we see it" |

### 5. Dependency Clarity (weight: 0.10)

External and internal dependencies are identified with status.

| Score | Signal |
|-------|--------|
| 0.0 | All dependencies listed with owner, status, and fallback |
| 0.33 | Dependencies listed, no status or fallback |
| 0.66 | Some dependencies missing |
| 1.0 | No dependency analysis |

## Threshold Definitions

| Threshold | Score Range | Action |
|-----------|-------------|--------|
| **GREEN** | 0.0 - 0.2 | Proceed to PLAN, minimal assumptions |
| **YELLOW** | 0.2 - 0.5 | Proceed with documented assumptions + examples |
| **RED** | 0.5 - 1.0 | BLOCK PLAN, requires resolution |

## Auto-Fail Triggers

Override computed score to 1.0 regardless of other dimensions:

1. **No acceptance criteria whatsoever** — task description only, zero verifiable statements
2. **Active NFR conflict** — two or more NFRs on the same task are contradictory and unprioritized
3. **Phantom reference** — task references a system/API/module that does not exist in codebase and is not marked greenfield
4. **Circular dependency** — task depends on itself through a chain, or depends on a task with higher ambiguity score
5. **Security requirement without threat model** — any auth/security/privacy requirement lacking threat actor or risk scenario

## Scoring Workflow

```
FOR each task_node:
  criteria = assess_criteria_clarity(task_node.ac)
  nfr = assess_nfr_consistency(task_node.nfrs)
  domain = assess_domain_precision(task_node.description, glossary, codebase)
  scope = assess_scope_boundaries(task_node.scope)
  deps = assess_dependency_clarity(task_node.dependencies)

  raw = criteria * 0.30 + nfr * 0.25 + domain * 0.20 + scope * 0.15 + deps * 0.10

  IF any_auto_fail_trigger(task_node):
    score = 1.0
  ELSE:
    score = raw

  emit(task_node.id, score, breakdown = {criteria, nfr, domain, scope, deps})
```

## Score Interpretation for User Communication

| Score | User Message |
|-------|-------------|
| 0.0 - 0.1 | "Clear and implementable" |
| 0.1 - 0.2 | "Minor assumptions, auto-documented" |
| 0.2 - 0.3 | "Needs example mapping" |
| 0.3 - 0.5 | "Needs examples + assumption sign-off" |
| 0.5 - 0.7 | "BLOCKED: clarify acceptance criteria or scope" |
| 0.7 - 1.0 | "BLOCKED: fundamental ambiguity, needs rewrite" |
