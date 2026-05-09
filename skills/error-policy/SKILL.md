---
name: error-policy
description: >
  Universal error recovery and circuit breaker system for ALL skill scripts in the
  Kimi AI Engineering Skills Ecosystem v4.0. Defines retry logic, fallback
  strategies, HITL escalation, and pipeline halt policies. No script handles
  errors ad-hoc. Use this skill whenever a script fails, when designing new
  skills that must declare failure behavior, when configuring circuit breaker
  thresholds, or when defining degraded-mode fallbacks for critical paths.
---

# Error Policy

## Overview

The `error-policy` skill provides a **universal error recovery protocol** for the
entire Kimi AI Engineering Skills Ecosystem. It eliminates ad-hoc try/except
blocks in individual scripts by mandating that every skill execution returns a
standard `ScriptResult` and delegates recovery decisions to a centralized
`ErrorPolicy` engine.

**Key principle**: *Scripts report; ErrorPolicy decides.*

When any skill script fails, the ErrorPolicy engine evaluates the failure against
retry rules, fallback availability, criticality classification, and circuit
breaker state. It then orchestrates the appropriate response: retry with
exponential backoff, degraded fallback execution, human-in-the-loop (HITL)
escalation, or full pipeline halt.

This skill is **stateful and observable** — circuit breaker health feeds into the
`drift-monitor`, critical gate failures block `phase-controller` transitions, and
policy violations trigger `policy-engine` HALT signals.

---

## Core Capabilities

### 1. ScriptResult Standard — Universal Execution Contract

Every script in the ecosystem MUST return a `ScriptResult` dataclass. No
exceptions. No raw booleans. No silent `None` returns.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `exit_code` | `int` | `0` = success, `1` = handled failure, `2` = unhandled failure, `3` = policy violation |
| `findings` | `List[Dict]` | Structured output from the script (issues, metrics, artifacts) |
| `errors` | `List[Dict]` | Full error context: message, stack trace, input params, environment |
| `fallback_recommendation` | `Optional[str]` | Suggested fallback strategy ID if known |
| `escalate_to_human` | `bool` | True if script believes HITL is required |
| `execution_time` | `float` | Duration in seconds |
| `skill_id` | `str` | Originating skill identifier (e.g., `security-auditor`) |
| `operation` | `str` | Operation tag: `read`, `write`, `delete`, `apply`, `analyze`, `test` |

**Construction rules:**
- On success: `exit_code=0`, `errors=[]`, `findings` populated.
- On failure: `exit_code` > 0, `errors` MUST contain at minimum `message`,
  `exception_type`, `input_hash`, `timestamp`, `env_snapshot`.
- Destructive operations (`write`, `delete`, `apply`) MUST set
  `operation` accurately so retry policies can refuse automatic retries.

### 2. ErrorPolicy Enum — Four-State Recovery Machine

Recovery follows a strict ordered progression:

```
RETRY (3x exponential backoff)
   ↓  if exhausted or destructive
FALLBACK (degraded mode execution)
   ↓  if unavailable or fails
ESCALATE (HITL — human in the loop)
   ↓  if unresolved or critical gate
HALT (pipeline stop)
```

**States:**

| State | Code | Trigger Condition | Outcome |
|-------|------|-------------------|---------|
| `RETRY` | `retry` | Non-destructive, retry count < 3, circuit closed | Exponential backoff retry (1s, 2s, 4s) |
| `FALLBACK` | `fallback` | Retry exhausted OR destructive op, fallback defined | Execute degraded strategy; flag `degraded=True` |
| `ESCALATE` | `escalate` | Critical skill failure OR no fallback OR policy gate | HITL ticket with full context; block phase transition |
| `HALT` | `halt` | Unresolved escalation OR policy violation OR no fallback + critical | Stop pipeline; require human restart |

**State transition rules:**
- A destructive operation may be retried **at most once** and only if the first
  failure was a transient network/IO error. Second failure immediately goes to
  FALLBACK or ESCALATE.
- A script that sets `escalate_to_human=True` skips RETRY and goes directly to
  ESCALATE unless a viable fallback exists and policy permits fallback first.
- Policy violations (`exit_code=3`) are a special class: they bypass RETRY and
  FALLBACK entirely and go to HALT, notifying `policy-engine`.

### 3. Circuit Breaker — Per-Skill Failure Isolation

The circuit breaker tracks failure rates per `skill_id`. It prevents cascading
failures by refusing to execute a skill whose circuit is OPEN.

**Configuration:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `failure_threshold` | `5` | Failures required to open circuit |
| `time_window_seconds` | `600` | Rolling window (10 minutes) |
| `half_open_max_calls` | `1` | Test calls allowed in half-open state |

**States:**
- `CLOSED` — Normal execution. Failures are counted in the rolling window.
- `OPEN` — Execution blocked. All calls return `ScriptResult(exit_code=2, errors=[...])`
  with `circuit_open=True`.
- `HALF_OPEN` — After a cooldown of `cooldown_seconds` (default 60s), a single
  test call is permitted. Success closes the circuit; failure reopens it.

**Safety rule — NEVER auto-close**: A circuit moves from OPEN to HALF_OPEN on
a timer, but from HALF_OPEN to CLOSED **only** on a verified successful
`ScriptResult`. Human operators may also manually close a circuit via the
`force_close_circuit(skill_id)` API, but this is logged as an audit event.

**Integration with drift-monitor:** Circuit state changes (OPEN, HALF_OPEN,
CLOSED) are emitted as drift events with severity `warning` or `critical`
depending on the skill's criticality class.

### 3b. E2B Backend Circuit Breaker (v4.2.1)

In addition to per-skill circuit breakers, a dedicated circuit breaker tracks
E2B sandbox backend health:

**Configuration:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `e2b_failure_threshold` | `3` | E2B errors required to open circuit |
| `e2b_time_window_seconds` | `60` | Rolling window (1 minute) |
| `e2b_cooldown_seconds` | `300` | Cooldown before HALF_OPEN (5 minutes) |
| `e2b_half_open_max_calls` | `1` | Test calls allowed in half-open state |

**States:**
- `CLOSED` — E2B is primary backend; Docker is standby.
- `OPEN` — E2B calls blocked; automatic failover to Docker backend.
- `HALF_OPEN` — After 5-minute cooldown, single E2B probe permitted.
  - Probe success → remains HALF_OPEN; **manual failback required** (`auto_failback: false`)
  - Probe failure → reopen circuit, remain on Docker

**Failback protocol:**
1. Operator runs `kimi sandbox backend-set-primary e2b`
2. `sandbox-executor` executes `failback_probe_command`
3. On probe success, E2B circuit moves to CLOSED
4. On probe failure, circuit reopens; operator investigates

**Safety rule — NEVER auto-failback to E2B**: Even after probe success, E2B
does NOT automatically become primary. A human operator must explicitly promote
it, preventing flapping during intermittent E2B outages.

### 4. Fallback Strategies — Degraded Mode Registry

Every skill in the ecosystem MUST register one or more fallback strategies in
the `FallbackRegistry`. A fallback is a degraded but safe alternative execution
path that produces lower-fidelity results rather than failing completely.

**Example registrations:**

| Skill | Primary Mode | Fallback Mode | Fidelity |
|-------|--------------|---------------|----------|
| `security-auditor` | Semgrep SARIF scan | Static regex scan + file entropy check | Medium |
| `code-tester` | Pytest with coverage | Static import validation + AST smoke test | Low |
| `performance-validator` | Load test via Locust | Static complexity analysis (radon/cyclomatic) | Low |
| `dependency-resolver` | Full transitive lockfile | Direct-only requirements.txt parse | Low |
| `resilience-tester` | Chaos injection + recovery | Static fault-tree checklist | Low |

**Fallback rules:**
- Fallbacks MUST NOT silently reduce security. If the only available fallback
  is "less secure," it requires explicit `policy-engine` approval.
- Fallback execution is wrapped in its own `ErrorPolicy.run()` call but with
  `retry_count=0` to prevent infinite fallback loops.
- All fallback outputs are tagged `degraded=True` in `ScriptResult.findings`.

### 5. HITL Integration — Human Escalation Protocol

When ESCALATE or HALT is reached, the ErrorPolicy engine creates a HITL ticket
containing the full execution context.

**HITL payload:**
```json
{
  "ticket_id": "<uuid>",
  "skill_id": "security-auditor",
  "operation": "analyze",
  "phase_blocked": "validation",
  "error_policy_state": "ESCALATE",
  "script_result": { /* full ScriptResult JSON */ },
  "circuit_state": "OPEN",
  "fallback_attempted": false,
  "fallback_results": null,
  "retry_log": [
    {"attempt": 1, "wait": 1.0, "outcome": "timeout"},
    {"attempt": 2, "wait": 2.0, "outcome": "timeout"},
    {"attempt": 3, "wait": 4.0, "outcome": "timeout"}
  ],
  "environment": { /* snapshot */ },
  "timestamp": "2024-05-06T14:32:01Z"
}
```

**HITL rules:**
- Critical gates (`security-auditor`, `code-tester`, `gateway`, `phase-controller`)
  that reach FALLBACK failure always ESCALATE instead of degrading silently.
- HITL tickets block `phase-controller` phase transitions until resolved or
  explicitly bypassed with audit trail.
- If no human responds within `hitl_timeout_seconds` (default 30 minutes), the
  pipeline HALTs rather than auto-resuming.

---

## Safety Rules

These are **hard constraints**. Violations are treated as policy violations
(`exit_code=3`) and trigger HALT.

1. **NEVER silently swallow script errors** — always produce `ScriptResult` with
   full context. Empty `except: pass` is forbidden.
2. **NEVER retry a destructive operation** (`write`, `delete`, `apply`) more than
   once without human approval. One retry is permitted only for transient errors.
3. **ALWAYS log full error context** (stack trace, input params, environment)
   before any fallback or escalation.
4. **NEVER fall back to "less secure" mode** without explicit `policy-engine`
   approval. If the fallback is insecure, escalate instead.
5. **ALWAYS halt pipeline** if a critical gate (`security-auditor`,
   `code-tester`) fails and no safe fallback exists.
6. **NEVER allow circuit breaker auto-close** — requires human or
   verified-success signal.

---

## Integration Points

### With ALL Skills
Every script imports `ScriptResult` and `ErrorPolicy` from this skill. The
convention is:

```python
from error_policy import ScriptResult, ErrorPolicy, FallbackRegistry

def run_analysis(target_path: str) -> ScriptResult:
    try:
        findings = perform_analysis(target_path)
        return ScriptResult(exit_code=0, findings=findings, errors=[])
    except Exception as e:
        return ScriptResult.from_exception(
            e, skill_id="security-auditor", operation="analyze"
        )
```

The calling orchestrator (e.g., `phase-controller`) wraps execution:

```python
result = ErrorPolicy.run(
    lambda: run_analysis(target_path),
    skill_id="security-auditor",
    operation="analyze"
)
```

### With `phase-controller`
Critical failures may block phase transitions. When `ErrorPolicy` returns a
`ScriptResult` with `exit_code=1` and `degraded=True`, the phase controller may
optionally pause the transition and require sign-off. When `exit_code=2` or `3`,
the transition is blocked until HITL resolution or explicit override.

### With `policy-engine`
Policy violations are a special error class. If `policy-engine` itself fails, the
failure is tagged `exit_code=3`. `ErrorPolicy` routes this directly to HALT,
bypassing RETRY and FALLBACK, because a broken policy gate cannot be trusted to
approve its own fallback.

### With `drift-monitor`
Circuit breaker state changes and repeated fallback activations are published as
drift events. The `drift-monitor` consumes a stream of `CircuitStateChange`
events from this skill to detect systemic reliability degradation.

---

## Workflow

### Standard Recovery Flow

```
1. Script execution wraps in ErrorPolicy.run(script_call)
        ↓
2. If success → return ScriptResult with findings (exit_code=0)
        ↓
3. If failure → ErrorPolicy determines action:
   a. Is retry allowed?
      - Non-destructive operation? YES
      - Retry count < 3? YES
      - Circuit closed? YES
      → RETRY with exponential backoff (1s, 2s, 4s)
   b. Is fallback available?
      - Fallback registered for skill_id? YES
      - Fallback is security-approved? YES
      → FALLBACK: execute degraded mode, flag as degraded
   c. Is skill critical?
      - Skill in CRITICAL_GATES list? YES
      → ESCALATE: HITL ticket with full context
   d. No fallback + non-critical
      → Log warning, continue with degraded pipeline (exit_code=1)
4. Circuit breaker tracks failures per skill_id
   - Opens after 5 failures in 10 minutes
   - Emits drift event on state change
5. All decisions logged with full context
```

### Policy Violation Flow (Shortcut to HALT)

```
1. Script returns exit_code=3 (policy violation)
        ↓
2. ErrorPolicy routes directly to HALT
   - No retry
   - No fallback
   - Notify policy-engine
   - Create HITL ticket
   - Stop pipeline
```

### Circuit Breaker Flow

```
1. Skill call arrives
        ↓
2. Check circuit state
   OPEN → return immediate failure (circuit_open=True)
   HALF_OPEN → allow one test call, track result
   CLOSED → proceed
        ↓
3. Execute script
        ↓
4. On failure, increment rolling window counter
        ↓
5. If threshold reached → OPEN circuit, emit drift event
        ↓
6. After cooldown → HALF_OPEN
        ↓
7. On verified success → CLOSE circuit
   On failure → reopen, reset cooldown
```

---

## Configuration

Global defaults are overridden via environment variables or a JSON config file
at `~/.kimi/skills/error-policy/config.json`.

| Variable | Env Key | Default | Description |
|----------|---------|---------|-------------|
| `retry_max` | `KIMI_EP_RETRY_MAX` | `3` | Max retries for non-destructive ops |
| `retry_backoff_base` | `KIMI_EP_BACKOFF_BASE` | `1.0` | Base seconds for exponential backoff |
| `circuit_failure_threshold` | `KIMI_EP_CB_THRESHOLD` | `5` | Failures to open circuit |
| `circuit_time_window` | `KIMI_EP_CB_WINDOW` | `600` | Rolling window in seconds |
| `circuit_cooldown` | `KIMI_EP_CB_COOLDOWN` | `60` | Cooldown before half-open |
| `hitl_timeout` | `KIMI_EP_HITL_TIMEOUT` | `1800` | Seconds before auto-halt on unresolved HITL |
| `destructive_retry_max` | `KIMI_EP_DESTRUCTIVE_RETRY` | `1` | Max retries for write/delete/apply |

---

## File Structure

```
error-policy/
├── SKILL.md                          # This document
├── scripts/
│   └── error-policy.py               # ErrorPolicy engine, CircuitBreaker,
│                                     # ScriptResult, FallbackRegistry
└── references/
    └── fallback-strategies.md        # Per-skill fallback definitions
```

---

## Audit & Observability

Every `ErrorPolicy` decision is appended to a JSONL audit log at
`~/.kimi/logs/error-policy-audit.jsonl` with the following schema:

```json
{
  "timestamp": "2024-05-06T14:32:01Z",
  "event_type": "retry|fallback|escalate|halt|circuit_state_change",
  "skill_id": "security-auditor",
  "operation": "analyze",
  "from_state": "RETRY",
  "to_state": "FALLBACK",
  "script_result_hash": "sha256:abc123...",
  "context": { /* redacted snapshot */ }
}
```

**Log retention:** 90 days rolling. **Log sensitivity:** Error context may
contain file paths and input hashes; stack traces are retained; no secrets are
logged (scrubbed via `kimi_secrets_scrubber`).
