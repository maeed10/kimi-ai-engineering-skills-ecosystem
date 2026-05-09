---
name: skill-registry
description: >
  Skill lifecycle manager that controls which skills are active, loaded, or purged. Orchestrator composes LLM prompts ONLY from ACTIVE skills for the current phase. Prevents stale skills from persisting in context window. Manages REGISTERED, LOADED, ACTIVE, UNLOADED, PURGED states with integrity verification and reference tracking. Integrates with phase-controller, policy-engine, tool-execution-gateway, and sandbox-executor.
---

# skill-registry

Skill lifecycle manager that controls which skills are active, loaded, or purged. The Orchestrator composes LLM prompts ONLY from ACTIVE skills for the current phase. Prevents stale skills from persisting in context window, eliminating a validated HIGH-severity attack vector (ARC-2.2, severity 8/10).

---

## Metadata

| Field | Value |
|-------|-------|
| **Name** | `skill-registry` |
| **Version** | `4.0.0` |
| **Type** | `core-infrastructure` |
| **Author** | `kimi-ai-engineering` |
| **Maintainer** | `kimi-ai-engineering` |
| **Status** | `stable` |
| **Supported Kimi Versions** | `kimi-k2` and above |
| **Severity Addressed** | `ARC-2.2: HIGH (8/10)` |

---

## Quick Start

```python
from skill_registry import SkillRegistry

# Initialize at session start
registry = SkillRegistry(skills_dir=".kimi/skills/", policy_engine=policy_engine)

# Phase change: orchestrator requests active skills for current phase
active_skills = registry.get_active_skills_for_phase("code_review")

# Compose LLM prompt from ONLY active skills
prompt = orchestrator.compose_prompt(active_skills)

# When phase ends, transition skills out
registry.transition_phase("testing")
```

---

## Overview

The `skill-registry` is the central authority for skill lifecycle management within the Kimi AI Engineering Skills Ecosystem v4.0. It maintains explicit state machines for every discovered skill, enforces integrity checks, validates policy compliance, and ensures that **only ACTIVE skills are ever injected into the LLM context window**.

Without this registry, skills remain in the context window indefinitely, allowing the LLM to re-activate "deactivated" skills at will — a confirmed HIGH-severity vulnerability (ARC-2.2, severity 8/10). The registry closes this gap by making skill state explicit, programmatic, and non-bypassable.

---

## Core Concepts

### Lifecycle States

Every skill exists in exactly one of five states at any time:

| State | Description | In LLM Context? | Tools Callable? |
|-------|-------------|-----------------|-----------------|
| **REGISTERED** | Discovered on disk; manifest parsed and validated | No | No |
| **LOADED** | Integrity verified; dependencies resolved; ready for activation | No | No |
| **ACTIVE** | Approved for current phase; injected into LLM context | **Yes** | **Yes** |
| **UNLOADED** | No longer needed for current phase; removed from context | No | No |
| **PURGED** | Permanently removed from session; cannot be reactivated | No | No |

State transitions are **unidirectional except for UNLOADED → LOADED**, which requires full re-verification. A PURGED skill must be rediscovered from disk to re-enter the lifecycle.

### Transition Diagram

```
                    ┌──────────────────┐
                    │   [Discovery]    │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
              ┌─────│   REGISTERED     │
              │     └────────┬─────────┘
              │              │
              │    ┌─────────▼──────────┐     ┌────────────────┐
              │    │  Integrity Check   │─────│  FAIL (block)  │
              │    │  (SHA-256 verify)  │     └────────────────┘
              │    └─────────┬──────────┘
              │              │
              │              ▼
              │     ┌──────────────────┐
              └─────│    LOADED        │◄─────────────────┐
                    └────────┬─────────┘                  │
                             │                           │
                    ┌────────▼────────┐                  │
              ┌─────│ Phase + Policy  │──────┐           │
              │     │   Validation    │      │           │
              │     └────────┬────────┘      │           │
              │              │               │           │
              │              ▼               ▼           │
              │     ┌──────────────────┐  ┌─────────────┐ │
              │     │     ACTIVE       │  │ FAIL (hold) │ │
              │     └────────┬─────────┘  │  LOADED     │ │
              │              │            └─────────────┘ │
              │              │                            │
              │    ┌───────┴──────────┐                  │
              │    │  Phase ends /    │                  │
              │    │  Policy revokes  │                  │
              │    └────────┬─────────┘                  │
              │              │                            │
              │              ▼                            │
              │     ┌──────────────────┐                  │
              │     │    UNLOADED      │──────────────────┘
              │     └────────┬─────────┘   (full re-verify)
              │              │
              │    ┌───────┴──────────┐
              │    │  No future phases  │
              │    │  need this skill   │
              │    └────────┬─────────┘
              │              │
              │              ▼
              │     ┌──────────────────┐
              └────►│    PURGED        │ (terminal)
                    └──────────────────┘
```

### Capability Manifests

Every skill MUST declare a machine-readable `manifest.json` (or equivalent frontmatter in `SKILL.md`). The manifest describes:

- **Allowed phases**: Which workflow phases may activate this skill
- **Required permissions**: Policy gates that must be satisfied
- **Tools**: Exact tool set the skill may invoke
- **Side effects**: File, network, or state mutations the skill may perform
- **Dependencies**: Other skills required to be ACTIVE for this skill to function
- **Integrity hash**: SHA-256 of the skill's canonical source files

The Orchestrator queries the registry for ACTIVE skills; the registry filters by `allowed_phases`, validates against `policy-engine`, verifies integrity, and returns only the approved set.

### Reference Tracking

The registry logs every time the LLM references a skill by name in its response. If the referenced skill is not ACTIVE, the registry flags a **violation**:

- **UNLOADED skill referenced**: Logged as `LLM_REACTIVATION_ATTEMPT`. The Orchestrator must reject the output and instruct the LLM to use only ACTIVE skills.
- **PURGED skill referenced**: Logged as `RESURRECTION_ATTEMPT`. The skill must go through full discovery and verification to become LOADED again.
- **Non-existent skill referenced**: Logged as `HALLUCINATED_SKILL`. The Orchestrator must ignore the reference.

This prevents the LLM from bypassing the registry by "pretending" a skill is still available.

---

## Integration Points

### phase-controller

The `phase-controller` determines the current workflow phase (e.g., `requirements`, `design`, `implementation`, `testing`, `review`). The registry:

1. Receives `phase_change` events from the controller
2. Filters skills where `current_phase ∈ allowed_phases`
3. Transitions matching skills: REGISTERED → LOADED → ACTIVE
4. Transitions skills no longer allowed: ACTIVE → UNLOADED
5. Transitions skills not needed for remaining phases: UNLOADED → PURGED

**Interface**:
```python
registry.on_phase_change(new_phase: str, remaining_phases: List[str])
```

### policy-engine

Before any LOADED → ACTIVE transition, the registry validates the skill against `policy-engine` rules:

- Is the skill on the `allowlist`?
- Are `required_permissions` granted for the current session?
- Does the skill violate any `denylist` patterns (e.g., network access in air-gapped mode)?
- Is the skill's `risk_level` acceptable for the current `trust_zone`?

If validation fails, the skill remains in LOADED state (or moves to UNLOADED if already ACTIVE) and the Orchestrator is notified.

**Interface**:
```python
policy_engine.validate(skill_manifest: dict, context: dict) -> ValidationResult
```

### tool-execution-gateway

The `tool-execution-gateway` intercepts all tool calls from the LLM. It queries the registry to confirm:

- Is the calling skill in ACTIVE state?
- Is the requested tool declared in the skill's manifest `tools` list?
- Are the tool arguments within the declared `parameter_constraints`?

If any check fails, the gateway blocks the call and returns an error to the LLM.

**Interface**:
```python
registry.assert_tool_allowed(skill_name: str, tool_name: str, args: dict)
```

### sandbox-executor

When a skill requires sandboxed execution, the registry forwards the skill's `required_capabilities` (from manifest) to the `sandbox-executor` to configure the sandbox profile (e.g., filesystem restrictions, network policies, resource limits).

**Interface**:
```python
registry.get_sandbox_profile(skill_name: str) -> SandboxConfig
```

---

## Safety Rules

The following rules are **invariant** and enforced at every code path:

1. **NEVER include a skill in LLM context unless it is in ACTIVE state.**
   - The Orchestrator must query `registry.get_active_skills()` and compose prompts exclusively from the returned set.
   - Any direct skill loading by the Orchestrator is a critical bug.

2. **NEVER allow a skill to transition to ACTIVE if its integrity check fails.**
   - SHA-256 verification is mandatory for every REGISTERED → LOADED and LOADED → ACTIVE transition.
   - If the skill file has been modified since manifest generation, the transition is blocked.

3. **NEVER let LLM "reactivate" an UNLOADED skill.**
   - If the LLM references an UNLOADED skill, the Orchestrator must reject the output.
   - Reactivation requires explicit registry transition: UNLOADED → LOADED (with re-verification) → ACTIVE (with policy check).

4. **ALWAYS verify SHA-256 of skill files before every LOADED → ACTIVE transition.**
   - Even if previously verified, the registry re-verifies on every activation to detect tampering.

5. **NEVER allow a skill's tools to be called if the skill is not ACTIVE.**
   - The `tool-execution-gateway` must check state via the registry before executing any tool.

6. **ALWAYS log every lifecycle transition with timestamp, phase, and justification.**
   - Log format: `[TIMESTAMP] [PHASE] SKILL_NAME: OLD_STATE → NEW_STATE | REASON | POLICY_RESULT | INTEGRITY_HASH`
   - Logs are append-only and stored in `session_logs/skill_lifecycle.log`.

7. **NEVER transition a skill to ACTIVE if it has unmet dependencies.**
   - All skills in `manifest.dependencies` must be ACTIVE before the dependent skill can become ACTIVE.

8. **ALWAYS purge skills that are not needed for any remaining phase.**
   - This minimizes context window pressure and attack surface.

---

## Workflow

### Session Start (Discovery)

1. The Orchestrator instantiates `SkillRegistry` with the skills directory path.
2. The registry scans `.kimi/skills/` and subdirectories for `SKILL.md` files.
3. For each discovered skill:
   a. Parse `manifest.json` (or extract frontmatter from `SKILL.md`).
   b. Validate manifest schema against `skill-manifest-schema.md`.
   c. Compute SHA-256 of the skill's canonical files.
   d. Set initial state: **REGISTERED**.
   e. Log: `[START] SKILL: NULL → REGISTERED | discovered at path/to/skill`.

### Phase-Based Activation

When the Orchestrator needs skills for the current phase:

1. The Orchestrator calls `registry.get_active_skills_for_phase(phase)`.
2. The registry filters skills where `phase ∈ skill.manifest.allowed_phases`.
3. For each matching skill in REGISTERED state:
   a. Compute SHA-256 of skill files.
   b. Compare against `manifest.integrity_hash`.
   c. If match: transition to **LOADED**.
   d. If mismatch: log integrity failure; skill remains REGISTERED (blocked).
4. For each matching skill in LOADED state:
   a. Query `policy-engine.validate(skill.manifest, context)`.
   b. If policy allows and dependencies are ACTIVE: transition to **ACTIVE**.
   c. If policy blocks: log violation; skill remains LOADED.
5. For skills currently ACTIVE but NOT in the filtered set:
   a. Transition to **UNLOADED**.
   b. Remove from LLM context.
6. For skills in UNLOADED that are not needed for any remaining phase:
   a. Transition to **PURGED**.
   b. Free memory and context references.
7. Return list of ACTIVE skills to Orchestrator.

### Prompt Composition

The Orchestrator composes the LLM prompt:

1. Query `registry.get_active_skills()`.
2. For each ACTIVE skill, inject its prompt fragment (from `SKILL.md` or compiled prompt).
3. **Never** include UNLOADED or PURGED skills, even if the LLM "requests" them.
4. Include a system preamble: "Active skills for this phase: [list]. You may only use tools declared by these skills."

### LLM Response Processing

After receiving the LLM response:

1. The Orchestrator calls `registry.scan_for_skill_references(llm_output)`.
2. The registry extracts all skill name mentions.
3. For each referenced skill:
   - If ACTIVE: log normal usage.
   - If UNLOADED: flag `LLM_REACTIVATION_ATTEMPT`; Orchestrator must reject and remind LLM of active set.
   - If PURGED: flag `RESURRECTION_ATTEMPT`; block and log.
   - If unknown: flag `HALLUCINATED_SKILL`; ignore.

### Phase Change

When `phase-controller` signals a phase change:

1. Registry receives `on_phase_change(new_phase, remaining_phases)`.
2. Re-evaluate all skills against new phase and remaining phases.
3. Execute the Phase-Based Activation workflow (above).
4. Log summary: `[PHASE_CHANGE] old_phase → new_phase | active_count=X | unloaded_count=Y | purged_count=Z`.

### Session End

1. All remaining ACTIVE skills transition to UNLOADED.
2. All UNLOADED skills transition to PURGED.
3. Final log entry: `[SESSION_END] all skills purged`.
4. Registry writes lifecycle audit log to disk.

---

## Error Handling

| Error Condition | Registry Action | Orchestrator Response |
|-----------------|-----------------|----------------------|
| Manifest schema violation | Log; skill remains UNREGISTERED | Ignore skill; alert user |
| Integrity check failure | Block transition; skill stays at current state | Do not include in context; alert user |
| Policy validation failure | Block ACTIVE transition; keep LOADED | Do not include in context; log reason |
| Dependency not ACTIVE | Block ACTIVE transition; keep LOADED | Wait for dependency or skip skill |
| LLM references UNLOADED skill | Flag violation; log | Reject output; re-prompt with active set |
| LLM references PURGED skill | Flag violation; log | Reject output; warn of invalid reference |
| Tool called by non-ACTIVE skill | Block tool call; log | Return error to LLM |
| Tool not in skill manifest | Block tool call; log | Return error to LLM |
| Missing integrity hash in manifest | Treat as integrity failure | Require manifest update |

---

## Files and Directory Structure

```
.kimi/skills/
├── skill-registry/
│   ├── SKILL.md                          # This file
│   ├── manifest.json                       # Skill capability manifest
│   ├── scripts/
│   │   └── skill-registry.py               # Core SkillRegistry class
│   └── references/
│       └── skill-manifest-schema.md        # JSON Schema for manifests
│
session_logs/
└── skill_lifecycle.log                     # Append-only transition audit log
```

---

## Dependencies

- `phase-controller` (receives phase change events)
- `policy-engine` (validates activation policy)
- `tool-execution-gateway` (validates tool calls against manifest)
- `sandbox-executor` (receives sandbox capability requirements)
- Python 3.10+ (for `match` statements and type hints)
- `hashlib` (SHA-256 verification)
- `json` and `jsonschema` (manifest validation)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 4.0.0 | 2024-01-15 | Initial release. Addresses ARC-2.2 HIGH severity. Introduces explicit lifecycle states, integrity verification, and reference tracking. |

---

## See Also

- `phase-controller` — Workflow phase management
- `policy-engine` — Policy and permission validation
- `tool-execution-gateway` — Tool call interception and validation
- `sandbox-executor` — Sandboxed execution environment
- `references/skill-manifest-schema.md` — JSON Schema for skill manifests