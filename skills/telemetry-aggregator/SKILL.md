---
name: telemetry-aggregator
description: >
  L1.5 session-level performance observability skill. Wraps every skill
  invocation and emits structured JSON telemetry records aggregated per
  session: skill name, phase, duration ms, token_in, token_out, exit_status,
  error_class. Writes session summary to ~/.kimi/logs/session-{id}-telemetry.json.
  Integrates with skill-orchestrator, drift-monitor, phase-controller, and
  performance-validator. Co-loaded with drift-monitor and production-drift-bridge.
license: MIT
compatibility: Kimi Code CLI v1.0+
type: standard
---

# telemetry-aggregator — Session-Level Performance Observability

## Overview

`telemetry-aggregator` is the unified observability substrate for the Kimi AI Engineering Skills Ecosystem. It subscribes to execution events from `skill-orchestrator`, `phase-controller`, and `drift-monitor`, aggregates them into a per-session telemetry record, and persists it as structured JSON.

This skill closes the production blind spot identified in the "way forward — 2.00" analysis: without telemetry-aggregator, no component can answer "which skill is slowest?", "which phase fails most?", or "how many tokens did this session consume?"

## When to Use

- Always loaded (L1.5) during any session that uses the full ecosystem
- Consumed by `drift-monitor` for statistical baseline computation
- Consumed by `performance-validator` for latency SLO enforcement
- Consumed by `kimi-trace` (Wave 5) for session replay visualization
- Consumed by operators for capacity planning and cost attribution

## Activation Rules

| Rule | Description |
|------|-------------|
| **Always-on (L1.5)** | Loads at session start after L0 enforcement and L1 gateway layers |
| **Co-loaded** | Loaded atomically with `drift-monitor` and `production-drift-bridge` |
| **Zero-blocking** | Async append to JSONL; never blocks skill execution on I/O |
| **Rotation** | Per-session files rotate at 10MB; older files compressed to `.jsonl.gz` |

## Input Event Stream

The aggregator subscribes to three event sources:

### 1. skill-orchestrator events (`~/.kimi/telemetry/sessions.jsonl`)

```json
{"timestamp":"2026-05-07T09:12:34Z","event_type":"skill_activate","session_id":"sess_abc123","skill":"code-tester","token_cost":5800}
{"timestamp":"2026-05-07T09:12:40Z","event_type":"tool_call","session_id":"sess_abc123","skill":"code-tester","tool":"pytest","risk_score":0.15}
{"timestamp":"2026-05-07T09:13:02Z","event_type":"skill_deactivate","session_id":"sess_abc123","skill":"code-tester","reason":"phase_complete","token_freed":5800}
```

### 2. phase-controller events (`~/.kimi/logs/phase-audit.log`)

```json
{"timestamp":"2026-05-07T09:12:30Z","session_id":"sess_abc123","from":"PLAN","to":"ASSESS","status":"APPROVED","transition_id":"tx-..."}
```

### 3. drift-monitor metrics (in-memory API)

- `session.tokens.total`
- `session.tokens.per_skill[]`
- `session.tool_calls.count_by_skill[]`

## Aggregation Model

For every session, the aggregator maintains an in-memory accumulator:

```python
@dataclass
class SessionAccumulator:
    session_id: str
    start_time: datetime
    phases: List[PhaseSlice]
    skills: Dict[str, SkillSlice]
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    exit_status: str = "IN_PROGRESS"  # IN_PROGRESS | SUCCESS | FAILURE | HALTED
    error_class: Optional[str] = None
```

### PhaseSlice

```python
@dataclass
class PhaseSlice:
    phase: str
    entered_at: datetime
    exited_at: Optional[datetime]
    duration_ms: int
    tokens_in: int
    tokens_out: int
    skills_active: List[str]
    transition_id: str
```

### SkillSlice

```python
@dataclass
class SkillSlice:
    skill: str
    activations: int
    total_duration_ms: int
    total_tokens_in: int
    total_tokens_out: int
    tool_calls: int
    exit_status: str  # SUCCESS | FAILURE | HALTED
    error_class: Optional[str]
```

## Output Format

When the session ends (detected by `skill-orchestrator` END event or 30s idle timeout), the aggregator writes:

```json
{
  "session_id": "sess_abc123",
  "aggregated_at": "2026-05-07T09:45:00Z",
  "start_time": "2026-05-07T09:12:00Z",
  "end_time": "2026-05-07T09:44:30Z",
  "total_duration_ms": 1950000,
  "phases": [
    {
      "phase": "INGEST",
      "duration_ms": 2100,
      "tokens_in": 1240,
      "tokens_out": 620,
      "skills": ["spec-decomposer", "requirement-refinement"]
    },
    {
      "phase": "PLAN",
      "duration_ms": 4800,
      "tokens_in": 3820,
      "tokens_out": 2100,
      "skills": ["architecture-design", "boundary-enforcer"]
    },
    {
      "phase": "ASSESS",
      "duration_ms": 1200,
      "tokens_in": 890,
      "tokens_out": 450,
      "skills": ["blast-radius-calculator"]
    },
    {
      "phase": "EXECUTE",
      "duration_ms": 12400,
      "tokens_in": 8100,
      "tokens_out": 3200,
      "skills": ["code-tester", "cross-cutting-concern-weaver"]
    },
    {
      "phase": "VALIDATE",
      "duration_ms": 3100,
      "tokens_in": 2200,
      "tokens_out": 980,
      "skills": ["security-auditor", "artifact-verifier"]
    },
    {
      "phase": "REMEMBER",
      "duration_ms": 800,
      "tokens_in": 410,
      "tokens_out": 180,
      "skills": ["obsidian-setup"]
    }
  ],
  "skills": [
    {
      "skill": "code-tester",
      "activations": 1,
      "total_duration_ms": 12400,
      "total_tokens_in": 8100,
      "total_tokens_out": 3200,
      "tool_calls": 4,
      "exit_status": "SUCCESS",
      "error_class": null
    }
  ],
  "total_tokens": 16660,
  "exit_status": "SUCCESS",
  "error_class": null,
  "version": "1.0.0"
}
```

**Output path:** `~/.kimi/logs/session-{session_id}-telemetry.json`

## Safety Rules

| # | Rule | Enforcement |
|---|------|-------------|
| T1 | **NEVER block skill execution on telemetry I/O** | Async append-only writer; skill events are queued and flushed by a background thread |
| T2 | **NEVER mutate telemetry records after write** | File is written once at session end; immutability enforced by read-only mode after close |
| T3 | **ALWAYS handle missing event sources gracefully** | If `skill-orchestrator` events are absent, fall back to `phase-controller` + tool-call heuristics |
| T4 | **NEVER include secrets or PII in telemetry** | `secret-manager` pre-scan strips credential patterns before aggregation |
| T5 | **ALWAYS rotate output files to prevent disk exhaustion** | 10MB rotation, 7-day retention, gzip compression for files >1 day old |

## Integration Points

| Consumer | Data Used | Mechanism |
|----------|-----------|-----------|
| `drift-monitor` | `total_tokens`, `duration_ms`, `tool_calls` per session | Reads `session-*-telemetry.json` at session end |
| `performance-validator` | Per-skill `duration_ms`, per-phase latency | Queries accumulator via in-memory API |
| `kimi-trace` | Full session timeline | Reads `session-*-telemetry.json` on demand |
| `slo-enforcer` | `exit_status`, `error_class` | Subscribes to session-end event stream |

## Scripts

- `scripts/telemetry-aggregator.py` — Reference implementation (`SessionAccumulator`, `AsyncWriter`, `EventSubscriber`)
- `scripts/telemetry-export.py` — Export session telemetry to Splunk/Datadog/ELK compatible JSON

## References

- `references/telemetry-schema.md` — Complete JSON schema for session telemetry output
- `references/event-subscription.md` — Event source APIs and filtering rules

## Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-07 | Initial release — session-level telemetry aggregation, async JSONL output, drift-monitor integration |
