# Phase Transitions Reference

Single source of truth for the `phase-controller` finite state machine.

**Version**: 4.0.0  
**Aligned with**: Kimi AI Engineering Skills Ecosystem v4.0  
**ARC Reference**: ARC-2.1 (severity 9/10)

---

## Phase Enum

| Value | Name | Canonical Color |
|------:|------|-----------------|
| 0 | `INGEST` | 🔵 |
| 1 | `UNDERSTAND` | 🟣 |
| 2 | `PLAN` | 🟡 |
| 3 | `ASSESS` | 🟠 |
| 4 | `EXECUTE` | 🔴 |
| 5 | `DELIVER` | 🟢 |
| 6 | `VALIDATE` | ⚪ |
| 7 | `REMEMBER` | ⚫ |

---

## Allowed Transitions Matrix

This matrix is **immutable** and **hard-coded** in `phase-controller.py`.  
No configuration file, no LLM prompt, and no runtime parameter can override it.

```
                 TO
              0    1    2    3    4    5    6    7
           +----+----+----+----+----+----+----+----+
        0  |    | ✅ |    |    |    |    |    |    |  INGEST
        1  |    |    | ✅ |    |    |    |    |    |  UNDERSTAND
FROM    2  |    |    |    | ✅ |    |    |    |    |  PLAN
        3  |    |    |    |    | ✅ |    |    |    |  ASSESS
        4  |    |    |    |    |    | ✅ |    |    |  EXECUTE
        5  |    |    |    |    |    |    | ✅ |    |  DELIVER
        6  |    |    |    |    |    |    |    | ✅ |  VALIDATE
        7  |    |    |    |    |    |    |    |    |  REMEMBER (terminal)
           +----+----+----+----+----+----+----+----+
```

### Key Properties

- **Linear**: Every phase has exactly one legal next phase (or none for terminal).
- **No skips**: You cannot move from `PLAN` (2) directly to `EXECUTE` (4); you must pass through `ASSESS` (3).
- **No reversions**: There is no backward arrow. Once in `EXECUTE`, you cannot return to `PLAN`.
- **No loops**: The graph is a directed acyclic path. The only way to "restart" is a full state machine reset (treated as a new session).
- **Terminal**: `REMEMBER` (7) has no outgoing edges. A new session must be initialized.

---

## Precondition Catalog

Every transition **into** a target phase requires specific completion artifacts to be present on disk, with SHA-256 hashes that match the files.

| Target Phase | Required Artifacts | Description | Validation Rule |
|--------------|-------------------|-------------|-----------------|
| **INGEST** | *(none)* | Starting state | Always valid |
| **UNDERSTAND** | `ingest-manifest.json` | Manifest of ingested inputs | File exists, JSON parseable |
| **PLAN** | `domain-model.md` | Domain model and clarified intent | File exists, non-empty |
| **ASSESS** | `task-plan.json` | Decomposed task plan with skill roles | File exists, JSON parseable, contains `tasks[]` |
| **EXECUTE** | `adr-*.md` **AND** `blast-radius-report.json` | Architecture Decision Record + blast radius analysis | Both files exist; ADR basename matches `adr-*.md`; blast radius JSON contains `risk_level` and `affected_systems[]` |
| **DELIVER** | `build-manifest.json` **AND** test exit code `0` | Build artifacts + passing tests | Manifest exists; test log exists with `exit_code: 0` |
| **VALIDATE** | `delivery-package/` **AND** `delivery-notes.md` | Packaged deliverable + handoff notes | Directory exists and non-empty; notes file exists |
| **REMEMBER** | `validation-report.json` with `status: passed` | Signed-off validation report | File exists, JSON parseable, top-level `status == "passed"` |

---

## Critical Enforcement Rules (ARC-2.1)

| Rule ID | Rule | Failure Mode |
|---------|------|--------------|
| R1 | `EXECUTE` cannot begin without `ASSESS` completion proof | **BLOCKED** + HITL escalation |
| R2 | `DELIVER` cannot begin without `EXECUTE` artifact manifest + tests passing | **BLOCKED** + HITL escalation |
| R3 | `REMEMBER` cannot begin without `VALIDATE` sign-off (`status: passed`) | **BLOCKED** + HITL escalation |
| R4 | No retroactive phase completion — `completed_phases` is append-only | **STATE CORRUPTION** → escalate |
| R5 | No phase value >= current phase may appear in `completed_phases` | **STATE CORRUPTION** → escalate |
| R6 | State must be persisted to disk **before** transition is confirmed to LLM | **DISK FAILURE** → retry once, then escalate |
| R7 | Every transition attempt (approved or blocked) is logged with artifact SHA-256s | Audit log append failure → escalate |

---

## Artifact Hash Verification

During `request_transition`, the controller:

1. Receives `proposed_artifacts: [{file, sha256}, ...]` from the orchestrator
2. For each required precondition artifact:
   - Checks that the file exists on disk
   - Recomputes `SHA-256(file)`
   - Compares to the provided `sha256`
3. **Mismatch** → transition **BLOCKED**, tamper warning logged
4. **Match** → artifact hash added to transition audit record

### Example Artifact Reference

```yaml
proposed_artifacts:
  - file: /mnt/agents/artifacts/adr-042.md
    sha256: "sha256:7a3f9e2b..."
  - file: /mnt/agents/artifacts/blast-radius-report.json
    sha256: "sha256:9e2b7a3f..."
```

---

## Human Override (HITL Escalation)

The only mechanism that can bypass the matrix is `force_escalation`, which requires:

- A valid `human_ticket` ID (e.g., `HITL-2047`)
- A written `justification`
- An `authorized_by` identity

The forced transition is still:
- Persisted to disk
- Logged in the audit trail with `status: FORCED`
- Annotated with the human ticket and authorizer

There is **no** API to retroactively mark a skipped phase as completed.

---

## State File Schema (`phase-state.json`)

```json
{
  "current_phase": "PLAN",
  "completed_phases": ["INGEST", "UNDERSTAND"],
  "artifacts": {
    "INGEST": [
      { "file": "/mnt/agents/artifacts/ingest-manifest.json", "sha256": "sha256:abc123..." }
    ],
    "UNDERSTAND": [
      { "file": "/mnt/agents/artifacts/domain-model.md", "sha256": "sha256:def456..." }
    ]
  },
  "transition_history": [
    {
      "transition_id": "tx-20250115-092317-INGEST-UNDERSTAND-a1b2c3d4",
      "from_phase": "INGEST",
      "to_phase": "UNDERSTAND",
      "timestamp": "2025-01-15T09:23:17Z",
      "artifact_hashes": ["sha256:abc123..."],
      "status": "APPROVED",
      "reason": null,
      "forced_by": null
    }
  ],
  "initialized_at": "2025-01-15T09:20:00Z",
  "version": "4.0.0"
}
```

---

## Audit Log Schema (`phase-audit.log`)

JSON Lines format. One JSON object per line.

```json
{"timestamp":"2025-01-15T09:23:17Z","event":"APPROVED","current_phase":"UNDERSTAND","target_phase":"UNDERSTAND","transition_id":"tx-20250115-092317-INGEST-UNDERSTAND-a1b2c3d4","detail":"Transition INGEST -> UNDERSTAND","artifact_hashes":["sha256:abc123..."],"forced_by":null}
{"timestamp":"2025-01-15T09:45:03Z","event":"BLOCKED","current_phase":"PLAN","target_phase":"EXECUTE","transition_id":null,"detail":"Illegal transition: PLAN -> EXECUTE is not in allowed_transitions[PLAN]=['ASSESS']","artifact_hashes":[],"forced_by":null}
```

---

## Change Log

| Version | Date | Change |
|---------|------|--------|
| 4.0.0 | 2025-01-15 | Initial release aligned with Ecosystem v4.0; ARC-2.1 enforcement |
