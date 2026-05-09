---
name: ecosystem-integrator
description: User-facing discovery and navigation skill for the Kimi AI Engineering Skills Ecosystem. Helps developers find the right skill for their task by querying the skill-orchestrator, presents matching skills as choices, and guides the user through the 7-phase pipeline. Does NOT control, configure, or override any L0 safety skill — those load atomically at session start before this skill activates. Use when you need to discover which skill to use, understand what phase you're in, or navigate the ecosystem's capabilities. The user chooses their task; the ecosystem handles safety.
---

# ecosystem-integrator

A **user-facing discovery skill** that helps developers navigate the Kimi AI Engineering Skills Ecosystem. It finds the right skill for the user's task without ever controlling, configuring, or overriding the mandatory L0 safety layer.

## What This Skill Is NOT

This skill does NOT:
- Configure, enable, or disable any L0 safety skill (policy-engine, sandbox-executor, ipi-defender, etc.)
- Override phase transitions controlled by `phase-controller`
- Replace `skill-orchestrator` as the canonical router
- Manage skill lifecycles (that's `skill-registry`)
- Offer "permissive" or "reduced security" modes
- Skip hash-verified artifact checks at phase boundaries

## How This Skill Fits Into the Ecosystem

```
Session Start
    |
    v
L0 Safety Layer loads ATOMICALLY (mandatory, automatic)
    - policy-engine, ipi-defender, sandbox-executor, phase-controller
    - skill-registry, secret-manager, supply-chain-verifier
    - All 15 L0 skills — user has no control over these
    |
    v
L1 Gateway Layer loads (mandatory, automatic)
    - tool-execution-gateway, multi-model-router, cost-tier-security-gate
    |
    v
dev-* skills load ON-DEMAND (user-initiated, optional)
    - ecosystem-integrator, dev-code-generator, dev-test-automation, etc.
    - These are the ONLY skills the user chooses
    |
    v
skill-orchestrator routes intent (automatic)
    - Maps user task to canonical ecosystem skills
    |
    v
L2-L8 skills load PHASE-GATED (automatic)
    - architecture-design, code-tester, refactoring-engine, etc.
    - Only active for the current pipeline phase
```

## Core Principle

> **Safety is infrastructure, not a choice.**
> The user chooses their task. The ecosystem handles safety.

## Interactive Flow: Task Discovery

### Step 0: What Are You Working On?

```
Kimi AI Engineering Skills Ecosystem — 7 phases, 100 skills.

What would you like to work on?

  [1] Write or generate code
  [2] Test, debug, or validate code
  [3] Design architecture or APIs
  [4] Deploy, build CI/CD, or manage infrastructure
  [5] Monitor, observe, or respond to incidents
  [6] Secure, audit, or harden code
  [7] Document, review, or maintain project
  [8] Check ecosystem status or skill health
  [9] Describe your task in your own words

Your choice: _
```

### Step 1: Match Task to Skills (via skill-orchestrator)

```
You chose: "[user's choice]"

Querying skill-orchestrator for matching skills...

Recommended skills for your task:

  [1] dev-code-generator — Generate idiomatic code from description
  [2] dev-api-designer   — Design REST/GraphQL APIs with OpenAPI specs
  [3] dev-docs-maintainer — Generate READMEs, docstrings, diagrams

  [0] See more options
  [?] Explain what these skills do

Your choice: _
```

### Step 2: Skill Explanation (if user asks)

```
  dev-code-generator:
    Generates production-quality code with type hints, docstrings,
    and idiomatic patterns for Python, JavaScript/TypeScript, Go,
    Rust, Java, C#. Matches your project's existing style and
    conventions. Tests generated code via sandbox-executor.

  dev-api-designer:
    Designs REST or GraphQL APIs, generates OpenAPI 3.1 specs,
    creates mock servers, and produces client SDKs. Validates
    backward compatibility with api-version-guard.

  dev-docs-maintainer:
    Generates READMEs, changelogs, API documentation, and
    architecture diagrams (Mermaid/PlantUML). Syncs docs with
    code changes via documentation-synthesizer.

  [1] Use dev-code-generator
  [2] Use dev-api-designer
  [3] Use dev-docs-maintainer
  [0] Back to main menu

Your choice: _
```

### Step 3: Confirm and Proceed

```
You selected: [skill_name]

This skill will execute within the ecosystem's 7-phase pipeline:
  Current phase: [phase from phase-controller]
  Safety status: ALL L0 skills active
  Sandbox: Docker (network: none, read-only filesystem)

The skill will:
  1. Run in an isolated sandbox
  2. Pass through policy-engine validation on every action
  3. Have outputs verified by artifact-verifier
  4. Be recorded in the attestation chain

  [1] Proceed with [skill_name]
  [2] Choose a different skill
  [3] Cancel

Your choice: _
```

### Step 4: Execution (User Task, Not System Control)

```
[skill_name] is active. What would you like to do?

  Describe your task or paste your request:
  → _
```

The user describes their task in natural language. The skill executes it, with all actions passing through the safety stack automatically.

### Step 5: Results

```
[skill_name] completed.

Results:
  Files created: [list]
  Tests passed: [count]
  Policy decisions: [X] ALLOWED, [Y] BLOCKED

Phase transition: [current] → [next]
  Status: [verified by phase-controller / blocked / waiting for artifact]

  [1] Continue to [next phase]
  [2] Review what was done
  [3] Do something else
  [4] End session

Your choice: _
```

**IMPORTANT:** Phase transitions are determined by `phase-controller` based on hash-verified artifacts, NOT by user choice. The integrator REPORTS the transition status; it does not CONTROL it. If the phase-controller blocks the transition, the user sees:

```
Phase transition: EXECUTE → VALIDATE
  Status: BLOCKED by phase-controller
  Reason: artifact hash mismatch / required artifact missing
  Action: [skill_name] will retry or escalate per error-policy
```

## Safety Is Never a User Choice

The following are **NOT presented to the user** because they are mandatory infrastructure:

| What | Status | User Control |
|------|--------|--------------|
| policy-engine | Always running | NONE — mandatory L0 |
| sandbox-executor | Always running | NONE — mandatory L0 |
| ipi-defender | Always running | NONE — mandatory L0 |
| phase-controller | Always running | NONE — mandatory L0 |
| verify_signatures | Always true | NONE — enforced |
| secret handling | Always fd-injection | NONE — enforced |
| network isolation | Always none | NONE — enforced |
| artifact verification | Always hash-verified | NONE — enforced |
| fail-closed behavior | Always BLOCK on failure | NONE — enforced |

The ONLY things the user chooses:
1. Which **dev-*** skill to use for their task
2. What task to describe to that skill
3. Whether to proceed, retry, or try a different skill

## Integration with Ecosystem Components

| Ecosystem Component | Integrator's Role | Never Does |
|--------------------|-------------------|-----------|
| `skill-orchestrator` | QUERIES for routing recommendations | Replaces routing |
| `skill-registry` | REPORTS which skills are loaded | Manages lifecycles |
| `phase-controller` | REPORTS current phase and transition status | Controls transitions |
| `policy-engine` | REPORTS decisions (ALLOW/BLOCK) | Configures rules |
| `artifact-verifier` | REPORTS verification results | Skips verification |
| `sandbox-executor` | REPORTS sandbox status and backend | Chooses backend |
| `error-policy` | REPORTS failures and recovery status | Overrides recovery |
| `memory-guard` | REPORTS session memory state | Manages memory |

## Fast Paths (for experienced users)

Experienced users can bypass discovery with direct commands:

| Command | Loads | Phase |
|---------|-------|-------|
| `kimi generate [description]` | dev-code-generator | EXECUTE |
| `kimi test [file]` | dev-test-automation | VALIDATE |
| `kimi debug [error]` | dev-debug-assistant | VALIDATE |
| `kimi deploy [target]` | dev-ci-cd-pipeline + canary-orchestrator | DELIVER |
| `kimi scan` | dev-security-scanner | VALIDATE |
| `kimi profile` | dev-performance-profiler | VALIDATE |
| `kimi design-api [spec]` | dev-api-designer | PLAN |
| `kimi setup-monitor` | dev-observability-setup | DELIVER |
| `kimi status` | ecosystem-integrator (health report) | ANY |

All fast paths still route through `skill-orchestrator` and pass through all L0 safety gates.

## Health Check Report

When the user selects "Check ecosystem status":

```
Ecosystem Status Report:

L0 Enforcement Layer (all mandatory):
  policy-engine:        [healthy / degraded / unhealthy]
  sandbox-executor:     [healthy / degraded / unhealthy]
  ipi-defender:         [healthy / degraded / unhealthy]
  phase-controller:     [healthy / degraded / unhealthy]
  skill-registry:       [healthy / degraded / unhealthy]
  ... (all 15 L0 skills)

L1 Gateway Layer:
  tool-execution-gateway: [healthy / degraded]
  multi-model-router:     [healthy / degraded]

Active dev-* skills:
  [list of currently loaded dev skills]

Current pipeline phase: [phase from phase-controller]
Attestation chain: [N] entries, [valid / broken]

NOTE: L0 skill health is reported for transparency only.
      The user cannot disable or bypass any L0 skill.
```

## References

| Document | Purpose |
|----------|---------|
| `references/skill_catalog.md` | Full catalog of dev-* skills with triggers |
| `references/skill_orchestrator_map.md` | skill-orchestrator's canonical intent-to-skill routing |
| `references/phase_guide.md` | What happens in each of the 7 phases |
| `references/fast_paths.md` | Shortcut commands for experienced use