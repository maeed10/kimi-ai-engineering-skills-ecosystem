---
name: cross-cutting-concern-weaver
description: >
  Systematic cross-cutting concern enforcement skill that weaves security, logging, resilience, observability, and compliance as first-class design aspects into generated code. Use during architecture design, code generation, security auditing, or when ensuring operational concerns are not afterthoughts. Validates all aspects are addressed before DELIVER.
---

# Cross-Cutting Concern Weaver

## Overview

Treat security, logging, metrics, resilience, compliance, performance, and internationalization as **first-class design aspects** — not afterthoughts. This skill provides an aspect inventory, per-language weaving patterns, enforcement gates, and conflict resolution for weaving cross-cutting concerns into generated code.

> **Finding Arch-10 Origin:** Addresses "Cross-Cutting Concerns as Design Aspects" from the Security Remediation Report. Prevents operational concerns from being retrofitted.

## Core Capabilities

| Capability | Purpose |
|---|---|
| **Aspect Inventory** | Catalog of concern definitions with configuration schemas |
| **Code Weaving** | Inject aspects via AST manipulation (decorators, annotations, middleware, aspects) |
| **Enforcement Gates** | `aspect-audit` validates all aspects are addressed before DELIVER |
| **Conflict Resolution** | Trade-off analysis when aspects compete (security vs performance, etc.) |

## Pre-Defined Aspects

```yaml
aspects:
  - security:       { authn, authz, input validation, secrets management }
  - logging:        { structured logging, log levels, correlation IDs }
  - metrics:        { counters, histograms, gauges, health checks }
  - resilience:     { circuit breakers, retries, bulkheads, timeouts }
  - compliance:     { audit trails, PII handling, data retention }
  - performance:    { caching, connection pooling, async processing }
  - i18n:           { localization, timezone handling, encoding }
```

Full definitions, weaving rules, and configuration schemas: `references/aspect_catalog.md`

## When to Activate

Activate this skill when any of these conditions are met:
- `architecture-design` defines system boundaries or component interfaces
- `code-generator` produces new code (functions, classes, endpoints, handlers)
- `security-auditor` flags missing security controls
- `documentation-synthesizer` generates architecture docs requiring operational concerns
- Logging, metrics, or compliance requirements are defined
- Any DELIVER phase is reached (enforcement gate check)

## Workflow

### Phase 1: Aspect Discovery

1. Read the task context (architecture docs, code being generated, audit findings)
2. Load `references/aspect_catalog.md` — identify which aspects apply
3. For each applicable aspect, extract its **required joinpoints** (where it must be woven)

**Aspect applicability matrix (quick-check):**

| Context | Required Aspects |
|---|---|
| HTTP API endpoint | security, logging, metrics, resilience |
| Background worker | logging, metrics, resilience, compliance |
| Data access layer | security, logging, metrics, performance |
| CLI tool | logging, compliance, i18n |
| Event handler | security, logging, metrics, resilience, compliance |
| Scheduled job | logging, metrics, compliance |

### Phase 2: Weaving

1. Load `references/weaving_patterns.md` for the target language
2. For each joinpoint, select the appropriate weaving pattern
3. Inject aspect code using AST manipulation (never string concatenation)
4. Ensure aspect ordering: **security → logging → metrics → resilience → business logic**

**Weaving patterns by language:**

| Language | Weaving Mechanism |
|---|---|
| Python | Decorators + context managers |
| Java | Annotations + AspectJ / Spring AOP |
| JavaScript/TypeScript | Middleware + higher-order functions |
| Go | Middleware chains + struct embedding |
| C# | Attributes + middleware |
| Rust | Macros + middleware traits |

### Phase 3: Conflict Resolution

When aspects compete, apply this decision hierarchy:

```
Priority (highest first):
1. security    — never downgraded for other concerns
2. compliance  — legal/regulatory requirements
3. resilience  — system availability
4. performance — optimize only after 1-3 are satisfied
5. logging     — reduce verbosity if perf critical (use sampling)
6. i18n        — defer if blocking critical path
```

Trade-off resolution process:
1. Identify conflicting aspects
2. Apply priority hierarchy
3. If same priority: document both options, recommend default
4. Log decision with rationale as code comment

### Phase 4: Enforcement Gate (`aspect-audit`)

Before any DELIVER, run this checklist:

```
[ ] All applicable aspects identified (Phase 1)
[ ] Each aspect woven at required joinpoints (Phase 2)
[ ] No aspect conflicts unresolved (Phase 3)
[ ] Security controls present on all entry points
[ ] Structured logging with correlation IDs on all flows
[ ] Metrics emitted for all external calls
[ ] Resilience patterns on all network/IO operations
[ ] Compliance audit trail on sensitive operations
[ ] Aspect ordering correct (security outermost)
```

**If any check fails:** Block DELIVER, report gaps, return to Phase 2.

## Output Format

When weaving aspects, produce:
1. **Aspect summary** — which aspects applied, to which joinpoints
2. **Woven code** — the modified AST/code with aspects injected
3. **Conflict log** — any trade-offs made with rationale
4. **Audit report** — enforcement gate results

## Quality Bar

- Every public function/endpoint has at least security + logging + metrics
- Every external call has resilience patterns (timeout + retry/circuit breaker)
- Every sensitive data operation has compliance audit trails
- Aspects are composable — order must not break functionality
- Aspects must not swallow exceptions (log/propagate, never silently drop)
