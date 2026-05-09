---
name: multi-model-router
description: >
  Cost-tier dispatcher that routes low-complexity, non-security-sensitive tasks
  to external LLM providers (Gemini, Claude, local models) while enforcing
  user-selected cost preferences, billing thresholds, and daily caps.
  Acts as a Phase 1 Gateway Layer skill alongside tool-execution-gateway.
  All external model outputs are tagged with EXTERNAL trust score (0.3) before
  entering memory-guard. Integrates with ipi-defender, policy-engine,
  artifact-verifier, and post-gemini-validator. NEVER routes EXECUTE, VALIDATE,
  or ASSESS phase tasks to external providers. NEVER auto-switches from a
  zero-cost model to a paid model without explicit user consent.
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# multi-model-router — Multi-Provider Low-Cost Task Router

## Overview

`multi-model-router` intercepts low-complexity tasks before they reach Kimi, routes them to the user's selected external provider (Gemini, Claude, local Ollama, etc.), and enforces cost controls including daily caps, billing thresholds, and provider-specific security gates. Kimi remains the authoritative engine for all security-sensitive, complex, or side-effect-bearing tasks.

This skill replaces and extends `gemini-router` (v1.0.0) with multi-provider support, billing-linked limits, and user sovereignty over model selection.

> **Backward compatibility:** `gemini-router` remains as a stub that delegates to `multi-model-router` with `provider: gemini` locked.

## When to Use

- User requests task classification falls into: INGEST (parsing, summarization), PLAN (initial decomposition only), DELIVER (documentation drafting), or REMEMBER (summarization)
- Task has **no side effects** (no filesystem writes, no code generation, no subprocess execution)
- Task has **no security implications** (no secret handling, no policy decisions, no sandbox config)
- Selected provider's daily counter / billing threshold is not exhausted
- Task does not require judgment or complex reasoning
- User has explicitly selected or consented to the provider

**When NOT to use:**
- ASSESS, EXECUTE, or VALIDATE phase tasks
- Tasks requiring code generation, refactoring, or test execution
- Tasks involving secrets, credentials, or PII
- Tasks requiring architectural decisions or trade-off analysis
- Tasks where the selected provider's limit has been reached (auto-fallback to Kimi)
- Tasks where the user has not consented to the provider's cost profile

## Core Capabilities

### 1. Provider Plugin System

Each provider is declared as a plugin with cost, limit, and eligibility metadata:

```yaml
providers:
  gemini:
    backend: gemini-cli
    model: gemini-2.5-flash-lite
    daily_limit_requests: 950
    cost_per_1k_tokens: 0.0
    billing_category: free_tier
    security_classification: non_security_only

  claude:
    backend: anthropic-cli
    model: claude-sonnet-4
    daily_limit_requests: 500
    cost_per_1k_tokens: 3.00
    billing_category: paid
    security_classification: non_security_only

  local:
    backend: ollama
    model: qwen2.5-coder:14b
    daily_limit_requests: unlimited
    cost_per_1k_tokens: 0.0
    billing_category: self_hosted
    security_classification: non_security_only
```

### 2. User Sovereignty & Sticky Preferences

The provider selected by the user is treated as a **sticky preference** stored in `~/.kimi/state/user-provider-preference.json`:

```json
{
  "preferred_provider": "gemini",
  "preferred_model": "gemini-2.5-flash-lite",
  "cost_ceiling_usd_per_day": 5.00,
  "auto_fallback_allowed": false,
  "last_updated": "2026-05-07T09:00:00Z"
}
```

**Rules:**
- The router may **suggest** alternatives: "Claude may handle this reasoning task better, but it costs $3/1k tokens. Switch?"
- The router must **NEVER** auto-switch, auto-fallback to a paid provider, or override the user's cost preference without explicit per-request consent.
- If the user's preferred provider is a zero-cost model (e.g., Gemini Flash, local Ollama), the system must NEVER automatically change to a paid model.

### 3. Billing-Linked Dynamic Limits

Replaces the fixed 950/day cap with a billing-aware limit:

```yaml
billing:
  monthly_budget_usd: 100.00
  daily_budget_usd: 3.33
  alert_threshold: 0.80
  hard_stop_threshold: 1.00
  currency: USD
```

**Dynamic limit calculation:**
```
daily_limit_tokens = (daily_budget_usd / cost_per_1k_tokens) * 1000
```

When the billing threshold is reached, the system **HALTS** external routing and presents the user with three options:
1. Switch to a zero-cost provider (e.g., local Ollama, Gemini free tier if under its separate cap)
2. Increase the billing cap (requires explicit user action)
3. Continue with Kimi local execution

The system must NEVER silently route to a paid provider, upgrade the model tier, or charge the user without explicit per-decision consent.

### 4. Atomic Daily Request Counter (Per Provider)

Stored at `~/.kimi/state/multi-model-counter.json`:

```json
{
  "date": "2026-05-07",
  "providers": {
    "gemini": {"count": 120, "limit": 950, "status": "OK"},
    "claude": {"count": 45, "limit": 500, "status": "OK"}
  },
  "billing": {
    "daily_spend_usd": 1.35,
    "daily_budget_usd": 3.33,
    "status": "OK"
  }
}
```

### 5. Task Classification Gate

Deterministic eligibility check before any dispatch:

| Eligibility | Criteria | Example |
|-------------|----------|---------|
| **ELIGIBLE** | Read-only, no secrets, low complexity, non-security, eligible phase | "Summarize this spec", "Draft README section", "Parse requirements" |
| **INELIGIBLE** | Side effects, security, complex reasoning, code, blocked phase | "Write unit tests", "Refactor this module", "Validate architecture", "Run security scan" |

Classification checks:
1. Current pipeline phase (from `phase-controller`)
2. Tool types requested (from `tool-execution-gateway`)
3. Target file paths (from execution request)
4. Presence of secret/PII patterns (from `secret-manager` pre-scan)
5. User provider preference and consent status

## Safety Rules

### CRITICAL

| # | Rule | Enforcement |
|---|------|-------------|
| M1 | NEVER dispatch tasks with filesystem write side effects to external providers | Router checks tool request for write_file, edit_file, shell before classification |
| M2 | NEVER dispatch EXECUTE, VALIDATE, or ASSESS phase tasks to external providers | Hard phase blacklist; phase-controller state checked before every dispatch |
| M3 | NEVER dispatch tasks involving secrets or PII to external providers | secret-manager pre-scan blocks requests with detected secret patterns |
| M4 | NEVER bypass the daily counter or billing threshold check | Counter check is mandatory; no override flag exposed to LLM runtime |
| M5 | ALWAYS fall back to Kimi when limit is reached | Soft fallback, never fail; logged as EXTERNAL_LIMIT_FALLBACK |
| M6 | ALWAYS tag external outputs as EXTERNAL trust class before memory promotion | memory-guard integration: all outputs get source_class EXTERNAL, base_score 0.3 |
| M7 | NEVER allow external outputs to influence high-trust memory without verification | External outputs cannot be promoted to STRUCTURAL or INFERRED without independent verification |
| M8 | ALWAYS route external outputs through ipi-defender before entering context | Gate 0 scan applies to ALL external content, including model responses |
| M9 | NEVER auto-switch from a zero-cost provider to a paid provider | Sticky preference enforced; paid routing requires explicit user opt-in per request |
| M10 | ALWAYS present cost implications before routing to a paid provider | "This will use [provider] at $[cost]/1k tokens. Proceed? (yes/no)" |

## Integration Points

| Component | Integration Mechanism | Responsibility |
|-----------|----------------------|----------------|
| `tool-execution-gateway` | Receives execution requests after Gate 0 sanitization | Provides task classification inputs |
| `phase-controller` | Queries current phase before dispatch | Blocks ASSESS/EXECUTE/VALIDATE routing |
| `secret-manager` | Pre-scans requests for secret/PII patterns | Blocks sensitive data from reaching external providers |
| `memory-guard` | Tags all external outputs as EXTERNAL (0.3) | Prevents untrusted content from influencing high-trust memory |
| `ipi-defender` | Scans external responses before context entry | Applies Gate 0 defense to model outputs |
| `policy-engine` | Validates capability declarations | Enforces provider-specific exceptions and sandbox rules |
| `artifact-verifier` | Post-dispatch validation of external outputs | Checks structural integrity of decomposed specs, docs |
| `post-gemini-validator` | Deterministic validation of task outputs | Verifies atomicity, completeness, no secret leakage |
| `cost-tier-security-gate` | Security classification before routing | Blocks SECURITY-CRITICAL tasks from external dispatch |
| `slo-enforcer` | Monitors cost SLOs | Alerts when daily spend approaches threshold |

## Request Flow

```
User Request
    |
    v
skill-orchestrator
    |
    +-- [Task classifier]
    |       |
    |       +-- LOW complexity + no side effects + eligible phase + user consented provider
    |       |         |
    |       |         v
    |       |   multi-model-router
    |       |   +-- check provider daily counter / billing threshold
    |       |   +-- secret-manager pre-scan (clean?)
    |       |   +-- cost disclosure (if paid provider)
    |       |   +-- dispatch to selected provider CLI (sandboxed)
    |       |   +-- increment counter / billing ledger
    |       |   +-- ipi-defender scan response
    |       |   +-- post-gemini-validator check
    |       |   +-- tag as EXTERNAL (0.3)
    |       |   +-- return result
    |       |
    |       +-- IMPORTANT / complex / security / ineligible phase / limit reached
    |                 |
    |                 v
    |           [existing Kimi pipeline]
    |           phase-controller -> policy-engine -> ...
    v
tool-execution-gateway
```

## Configuration

```yaml
# multi-model-router.yaml
router:
  default_provider: gemini
  fallback_provider: local  # NEVER fallback to paid without user consent

  providers:
    gemini:
      backend: gemini-cli
      model: gemini-2.5-flash-lite
      daily_limit_requests: 950
      cost_per_1k_tokens: 0.0
      allowed_phases: [INGEST, PLAN, DELIVER, REMEMBER]

    claude:
      backend: anthropic-cli
      model: claude-sonnet-4
      daily_limit_requests: 500
      cost_per_1k_tokens: 3.00
      allowed_phases: [INGEST, PLAN, DELIVER, REMEMBER]

    local:
      backend: ollama
      model: qwen2.5-coder:14b
      daily_limit_requests: unlimited
      cost_per_1k_tokens: 0.0
      allowed_phases: [INGEST, PLAN, DELIVER, REMEMBER]

  billing:
    monthly_budget_usd: 100.00
    daily_budget_usd: 3.33
    alert_threshold: 0.80
    hard_stop_threshold: 1.00
    currency: USD

  on_limit_reached:
    action: FALLBACK_TO_KIMI
    notify: true
    log_level: WARN

  fallback_on_limit_exceeded: true
  fallback_model: kimi-full
```

## Resources

- `scripts/multi-model-router.py` — Core router with provider plugin system, billing ledger, and user preference store
- `references/multi-model-router-config.md` — Full configuration schema and deployment guide
- `references/provider-comparison.md` — Cost/latency/quality comparison matrix

## Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-07 | Initial release — multi-provider routing with billing-linked limits, user sovereignty rules, sticky preferences, and zero-cost model protection |
