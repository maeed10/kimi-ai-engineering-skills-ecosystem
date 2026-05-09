# 7-Phase Pipeline Guide

This document describes what happens in each phase of the Kimi ecosystem pipeline. The `phase-controller` (L0) controls all transitions. The `ecosystem-integrator` REPORTS phase state but never controls it.

## Phase Flow

```
INGEST → PLAN → ASSESS → EXECUTE → DELIVER → VALIDATE → REMEMBER
```

Each transition requires **hash-verified completion artifacts** from `artifact-verifier` (L0). The user cannot skip or jump phases.

## What Happens In Each Phase

### INGEST: Parse Requirements
- `spec-decomposer` breaks down PRDs and specs into task nodes
- `requirement-refinement` checks for ambiguity and feasibility
- **User sees:** "Parsing your requirements..."
- **Transition to PLAN:** When artifact hash is verified

### PLAN: Design Architecture
- `architecture-design` selects patterns, creates ADRs
- `architecture-decision-gate` adds HITL checkpoint for major decisions
- `trade-off-analyzer` evaluates alternatives
- `boundary-enforcer` defines domain boundaries
- **User sees:** "Designing architecture... [architecture-decision-gate may pause for human review]"
- **Transition to ASSESS:** When artifact hash is verified

### ASSESS: Validate the Plan
- `blast-radius-calculator` computes impact radius
- `self-reviewer` does AST-backed structural review
- `artifact-verifier` validates plan artifacts
- **User sees:** "Validating plan..."
- **Transition to EXECUTE:** When artifact hash is verified

### EXECUTE: Build the Code
- `code-tester` generates and runs tests
- `refactoring-engine` performs AST-based transforms
- `security-auditor` checks for vulnerabilities
- `performance-validator` benchmarks
- **User sees:** "Building... [progress updates]"
- **Transition to DELIVER:** When artifact hash is verified

### DELIVER: Polish and Document
- `documentation-synthesizer` generates docs
- `address-pr-comments` handles feedback
- `style-enforcer` applies style rules
- `api-version-guard` checks backward compatibility
- **User sees:** "Generating documentation..."
- **Transition to VALIDATE:** When artifact hash is verified

### VALIDATE: Final Verification
- `resilience-tester` injects failures
- `api-contract-tester` validates API contracts
- `adversarial-tester` runs security tests
- `property-tester-pro` does generative testing
- **User sees:** "Running final validation..."
- **Transition to REMEMBER:** When artifact hash is verified

### REMEMBER: Persist Knowledge
- `obsidian-setup` saves to vault
- `memory-guard` updates trust scores
- `federated-memory-mesh` shares cross-instance
- **User sees:** "Saving session..."
- **Session ends:** When persistence is confirmed

## Phase Transition Status (what the integrator shows)

```
[phase-controller reports:]
  Current: EXECUTE
  Status:  artifact hash VERIFIED
  Action:  Transitioning to DELIVER
  Next:    DELIVER (documentation, PR comments, style enforcement)
  Skills:  documentation-synthesizer, address-pr-comments, style-enforcer
```

If the phase-controller BLOCKS a transition:
```
[phase-controller reports:]
  Current: EXECUTE
  Status:  artifact hash MISMATCH — transition BLOCKED
  Action:  Retrying (error-policy: 1/3)
  Next:    EXECUTE (retry after fix)
  Error:   artifact hash does not match expected value
```

The integrator REPORTS this. The user sees the status. Neither the user nor the integrator can override the phase-controller's decision.
