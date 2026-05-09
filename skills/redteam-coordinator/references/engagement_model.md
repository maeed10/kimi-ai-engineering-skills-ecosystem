# Engagement Model

## Black-Box Rules

### 1. Information Boundary

The red team receives **only** the following:
- Public API documentation (endpoints, request/response schemas, rate limits)
- User-facing guides, SDK docs, and publicly available changelogs
- Public model cards or safety cards, if published
- Access credentials for the isolated test environment

The red team receives **none** of the following:
- Source code, internal repositories, or build pipelines
- Architecture diagrams, data-flow diagrams, or infra maps
- Internal wikis, runbooks, or incident post-mortems
- The existing 108-case adversarial suite or expected outputs
- Direct contact with internal engineers for clarification (all questions go through a single neutral liaison)

### 2. Neutral Liaison Protocol

A single internal liaison is appointed:
- Receives red team questions via a dedicated, monitored channel
- Answers only factual questions about public behavior (e.g., "Is this endpoint rate-limited?")
- Does not answer design-intent questions (e.g., "What filter do you use for category X?")
- Logs all questions and responses for audit trail

### 3. Independent Test Authorship

- Red team must write their own test cases, payloads, and harnesses
- Use of the internal adversarial suite is prohibited
- Red team may use open-source frameworks (e.g., Garak, PyRIT, PromptMap) but must disclose which ones
- Any overlap between red team cases and internal cases must be flagged as coincidence, not derivation

### 4. Environment Isolation

- Red team operates in a dedicated staging tenant
- Tenant contains synthetic, anonymized data only
- No connectivity to production databases, message queues, or identity providers
- Network egress is monitored; exfiltration of real data is impossible by design

## Scope Template

### Engagement Identifier
```
RT-YYYY-QN-<vendor>-<id>
Example: RT-2025-Q2-ACME-001
```

### In-Scope Surfaces

| Surface | Description | Test Constraints |
|---------|-------------|----------------|
| Chat Completion API | `/v1/chat/completions` | Rate limit: 60 RPM |
| File Upload API | `/v1/files` | Max file size: 100 MB |
| Plugin / Tool Interface | JSON-schema defined tools | Only pre-registered test tools |
| Streaming Response | SSE output channel | No persistent connection abuse |
| System Prompt Surface | Behavior observed via API | No prompt extraction via side channels |

### Out-of-Scope Surfaces

- Physical data centers or hardware
- Employee workstations or corporate SSO
- Third-party payment processors
- Customer production tenants (even with consent)

### Time Bounds

| Milestone | Days from Kickoff |
|-----------|-------------------|
| Kickoff & Environment Provisioning | Day 0 |
| Reconnaissance & Threat Model Review | Day 1–3 |
| Active Testing | Day 4–17 |
| Draft Report Delivery | Day 18 |
| Readout & Clarifications | Day 19–20 |
| Final Report Delivery | Day 21 |
| Remediation Window (if included) | Day 22–35 |
| Validation Re-Test | Day 36–42 |

### Safe Harbor Statement

> [Organization] authorizes [Red Team Vendor] to conduct security testing against the in-scope surfaces listed above, within the isolated staging environment, during the engagement period. This authorization is limited to good-faith research that does not exceed the defined scope, does not attempt to access out-of-scope systems, and does not degrade service for other tenants. [Organization] agrees not to pursue legal action for activity that falls within these bounds. Any activity outside these bounds must be reported immediately and may void safe harbor protection.

## Deliverables Checklist

### Executive Summary
- [ ] Overall risk rating (Critical / High / Moderate / Low)
- [ ] Count of bypasses by severity
- [ ] Comparison to previous engagement (if applicable)
- [ ] Top 3 systemic weaknesses
- [ ] Maturity rating against industry benchmarks

### Technical Findings Report
- [ ] Each bypass with unique identifier
- [ ] Step-by-step reproduction instructions
- [ ] Screenshots, logs, or video evidence
- [ ] Affected gates and failure mode
- [ ] Recommended remediation
- [ ] CVSS-style score or equivalent risk quantification

### Novel Test Cases
- [ ] Standalone test harness for each new category
- [ ] Definition of success/failure for the test
- [ ] Minimum 20 variations per new category
- [ ] Attribution note linking case to finding

### Coverage Delta
- [ ] Matrix mapping internal suite categories to red team coverage
- [ ] List of internal cases that were bypassed or evaded
- [ ] List of internal categories red team did not test (gaps)

### Remediation Validation Plan
- [ ] Re-test criteria for each finding
- [ ] Regression test proposals
- [ ] Recommended addition to adversarial-tester-expanded suite

## Timeline Template

```
Week 1
  Day 0   Kickoff, black-box rules briefing, environment handover
  Day 1   Red team reconnaissance: docs, SDK, public behavior
  Day 2   Threat model alignment with updated intelligence
  Day 3   Test plan submission (red team defines approach)

Week 2–3
  Day 4–10  Active testing: injection, evasion, multi-turn, tool misuse
  Day 11–17 Deep-dive on promising vectors, edge-case probing

Week 4
  Day 18  Draft report to internal liaison
  Day 19–20 Readout meeting, clarifications, evidence review
  Day 21  Final report delivered

Week 5–6 (if remediation included)
  Day 22–28 Internal team implements fixes
  Day 29–35 Internal regression testing
  Day 36–42 Red team re-tests confirmed findings, validates closure
```

## Environment Provisioning Checklist

- [ ] Isolated tenant created with synthetic data seed
- [ ] API keys generated with scoped permissions (no admin rights)
- [ ] Network ACLs enforce no egress to production
- [ ] Logging and monitoring enabled for audit trail
- [ ] Kill-switch IAM role prepared for instant revocation
- [ ] Red team VPN or zero-trust access provisioned
- [ ] Data retention policy set: all tenant data deleted 90 days post-engagement
