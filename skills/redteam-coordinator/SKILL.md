---
name: redteam-coordinator
description: Independent red-team exercise orchestration for the ecosystem. Use when commissioning external security audits, validating adversarial test suites, preparing for production certification, or expanding coverage based on threat intelligence. Enforces black-box engagement, bypass tracking, coverage expansion, and continuous quarterly re-engagement.
---

# Redteam Coordinator

## Overview

The `redteam-coordinator` skill orchestrates independent red-team exercises against the ecosystem to eliminate self-certification bias. The internal 108-case adversarial suite was designed by the same team that built the system; this skill commissions external adversarial testers who receive only public documentation and must discover bypasses independently.

Use this skill to:
- Commission an external security audit with true black-box constraints
- Validate that the adversarial-tester-expanded suite is comprehensive
- Prepare evidence for production security certification
- Expand adversarial test coverage based on new threat intelligence
- Respond to a disclosed vulnerability with independent reproduction and regression testing

## Engagement Model

### Black-Box Mandate

The red team operates with **zero internal access**:
- Public API documentation and user-facing guides only
- No source code, no architecture diagrams, no internal wikis
- No access to the existing 108-case adversarial suite or its expected outputs
- No pairing with internal engineers during the engagement
- The red team must construct their own test harnesses, prompts, and payloads

This rule is non-negotiable. Any deviation voids the independence guarantee and invalidates certification evidence.

### Scope Definition

For every engagement, define scope in writing:
1. **In-scope surfaces**: API endpoints, UI flows, file upload pipelines, prompt injection vectors, model cards, plugin interfaces
2. **Out-of-scope surfaces**: Physical infrastructure, third-party SaaS backends (unless explicitly included), social engineering of internal staff
3. **Time bounds**: Start date, end date, reporting deadline, remediation window
4. **Test environment**: Isolated staging tenant with anonymized synthetic data; no production traffic

### Deliverables

The red team must produce:
1. **Executive summary**: High-level risk posture, critical bypass count, coverage gaps
2. **Technical findings**: Reproduction steps, severity, affected gates, video or log evidence
3. **Novel test cases**: New adversarial categories with standalone test harnesses
4. **Coverage delta**: List of internal suite cases that were bypassed or evaded
5. **Remediation validation plan**: How to re-test after fixes

### Safe Harbor

- Red team activity is pre-authorized within the defined scope and timeframe
- Isolated environment: no customer data, no production systems, no billing impact
- Emergency kill switch: internal team can revoke access instantly if scope bleed is detected
- Legal safe harbor: red team is indemnified for good-faith research within bounds

## Bypass Tracking

### Capture Protocol

Every bypass discovered by the red team is recorded as a structured finding:

```yaml
bypass_id: RT-YYYY-QN-NNN
red_team: <external org name>
discovery_date: YYYY-MM-DD
surface: <in-scope surface>
affected_gate: <gate identifier or "multiple">
category: <classification from taxonomy>
severity: <critical | high | medium | low>
reproduction:
  steps: [...]
  payload: <exact input or base64 if binary>
  expected_defense: <what should have happened>
  actual_result: <what actually happened>
  evidence: <link to screen recording or log artifact>
regression_test:
  case_id: <new adversarial-tester-expanded case ID>
  merged_date: <date added to suite>
```

### Severity Matrix

| Severity | Definition | Example |
|----------|------------|---------|
| **Critical** | Complete control or policy violation with trivial reproduction | Jailbreak revealing system prompt; unauthorized action execution |
| **High** | Significant policy bypass requiring no specialized knowledge | Evading content filter on sensitive category with paraphrasing |
| **Medium** | Partial bypass or bypass requiring specific context | Bypassing a gate only in multi-turn conversations |
| **Low** | Information leak or minor robustness degradation | Marginally higher hallucination rate under adversarial prompt |

### Remediation Workflow

1. **Triage** (24 hours): Internal team reproduces the bypass in the isolated environment
2. **Acknowledge** (48 hours): Confirm severity, assign owner, set target fix date
3. **Fix & Regression Test** (target 7 days for Critical/High): Patch the gate, add red team's reproduction to adversarial-tester-expanded suite
4. **Validate** (post-fix): Red team re-tests the exact reproduction to confirm closure
5. **Close** (post-validation): Mark bypass resolved, archive evidence for audit trail

## Coverage Expansion

### New Category Integration

When the red team discovers a bypass that does not fit any existing category:
1. Assign a new category code (e.g., `RT-INJ-2025-Q2-001`)
2. Write a specification: attack vector, success criteria, boundary conditions
3. Generate 20+ synthetic test cases for the category
4. Merge into `adversarial-tester-expanded` with attribution to the red team
5. Update threat model documentation to include the new vector

### Quarterly Re-Engagement

- **Cadence**: Every quarter, or within 30 days of a major model or gate update
- **Evolving scope**: Update threat model with new intelligence (e.g., OWASP LLM Top 10 updates, disclosed vulnerabilities in comparable systems)
- **Regression emphasis**: Each re-engagement must re-test all previously reported Critical and High bypasses to ensure no regressions
- **Retainer option**: Preferred red team org maintains ongoing access to the isolated environment for rapid spot-checks

## Preventing Self-Certification Bias

The core anti-pattern this skill eliminates:

> "The 108-case adversarial suite was designed by the same team that built the system. An external red-team exercise must be commissioned."

Enforce independence through:
- **No suite sharing**: Internal cases are never disclosed before engagement ends
- **No hinting**: Internal staff do not suggest areas to probe
- **Independent authorship**: Red team writes their own test cases; overlapping cases are coincidence, not instruction
- **Blind validation**: If possible, a second external party validates the first red team's findings without access to the first party's report

## Workflow Decision Tree

```
Start: Need external red-team engagement?
│
├─> Commissioning new audit?
│   └─> Load references/engagement_model.md
│       └─> Define scope, environment, safe harbor
│           └─> Issue RFP / direct commission
│               └─> Kickoff with black-box rules briefing
│
├─> Red team reported bypass?
│   └─> Load references/bypass_tracking.md
│       └─> Record structured finding
│           └─> Triage → Acknowledge → Fix → Validate → Close
│               └─> Merge regression test into adversarial-tester-expanded
│
├─> Preparing for production certification?
│   └─> Ensure at least one full engagement completed within 6 months
│       └─> Compile bypass tracking registry as evidence
│           └─> Confirm all Critical/High findings resolved or accepted with risk sign-off
│
├─> Expanding coverage from threat intelligence?
│   └─> Update threat model
│       └─> Scope focused engagement on new vectors
│           └─> Integrate new categories into adversarial-tester-expanded
│
└─> Responding to disclosed vulnerability?
    └─> Task red team with independent reproduction
        └─> If reproduced, follow bypass tracking workflow
            └─> Schedule emergency re-engagement if systemic
```

## Resources

### references/engagement_model.md
Detailed black-box rules, scope templates, deliverables checklists, timeline templates, and safe harbor legal language.

### references/bypass_tracking.md
Bypass classification taxonomy, severity matrix definitions, structured finding template, remediation SLA table, and quarterly re-engagement checklist.
