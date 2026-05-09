---
name: adr-machine-capture
description: Machine-readable ADR capture skill using MADR-JSON standard. Use when architecture-design or trade-off-analyzer makes decisions, when documentation-synthesizer updates ADRs, or when deriving fitness function constraints from past decisions. Enables automated constraint extraction, decision traceability, and status lifecycle management.
---

# adr-machine-capture

## Overview

`adr-machine-capture` establishes the **MADR-JSON** (Markdown Any Decision Records - JSON) standard for encoding architecture decisions as structured, machine-readable artifacts. It enables automated constraint extraction for `architecture-fitness-function`, full downstream traceability via `policy-attestation-layer`, and queryable decision registries for `brownfield-intelligence` and `graphify`.

This skill is the **system of record** for architectural decisions. Every significant design choice, technology selection, or trade-off resolution is captured in a format that both humans and automation can consume.

---

## When to Use This Skill

| Trigger | Example |
|---------|---------|
| `architecture-design` makes a structural decision | "We will use event sourcing for the audit log subsystem" |
| `trade-off-analyzer` completes a comparison | "Selected PostgreSQL over MongoDB for ACID compliance" |
| `documentation-synthesizer` generates ADR updates | Converting narrative design doc into structured ADR |
| `architecture-fitness-function` needs constraints | Deriving "all writes to audit log must be append-only" from ADR-0042 |
| `architecture-evolution` needs historical context | Understanding why monolith boundaries were drawn in 2022 |
| Brownfield system discovery | Capturing implicit decisions as explicit ADRs for legacy code |

---

## Workflow: Decision Capture Lifecycle

### Step 1: Decision Trigger Detection

A decision event occurs. Identify:
- **Decision scope**: system, subsystem, cross-cutting concern
- **Stakeholders**: who must review/approve
- **Urgency**: hotfix path vs standard deliberation

### Step 2: Draft MADR-JSON

Populate a MADR-JSON document with:
- `meta.id`: unique identifier (e.g., `ADR-0042`)
- `meta.status`: `proposed`
- `context`: forces, constraints, assumptions
- `decision`: the chosen option
- `consequences`: positive, negative, neutral
- `alternatives`: rejected options with rationale

Reference `references/madr_json_schema.md` for full schema.

### Step 3: Validate Schema

Run the validator before submission:

```bash
python scripts/validate_adr.py --adr path/to/decision.json --strict
```

### Step 4: Review & Transition Status

| Transition | Condition | Required Action |
|------------|-----------|-----------------|
| `proposed` -> `accepted` | Approved by stakeholders | Merge to `decisions/` registry |
| `proposed` -> `rejected` | Rejected in review | Archive to `decisions/rejected/` |
| `accepted` -> `deprecated` | Decision no longer applicable | Mark with `deprecated.date` and `deprecated.reason` |
| `accepted` -> `superseded` | Replaced by new decision | Set `superseded.by` to new ADR ID, update new ADR's `supersedes` |

### Step 5: Extract Constraints

Automatically generate architectural constraints for `architecture-fitness-function`:

```bash
python scripts/validate_adr.py --adr path/to/decision.json --extract-constraints --output constraints.json
```

### Step 6: Link Traceability

Register the ADR with `policy-attestation-layer` to authorize code changes:
- Each commit referencing the ADR includes `Attestation-ADR: ADR-0042`
- CI/CD gates verify all structural changes have ADR attestation

---

## Core Capabilities

### 1. MADR-JSON Schema

Structured format capturing all decision metadata. See `references/madr_json_schema.md` for the complete schema.

Key sections:
- `meta`: ID, date, status, status transitions, authors
- `context`: problem statement, forces, constraints, assumptions
- `decision`: chosen option with rationale
- `consequences`: categorized impacts (positive/negative/neutral)
- `alternatives`: rejected options with explicit rationale
- `linked`: related ADRs, requirements, code paths

### 2. Constraint Derivation

Automatically extract machine-verifiable architectural constraints from ADR content. Examples:

| ADR Content | Derived Constraint | Fitness Function Target |
|-------------|-------------------|-------------------------|
| "All audit events must be immutable" | `audit_log.immutable_writes == true` | `architecture-fitness-function` |
| "Service boundaries align with bounded contexts" | `package.coupling_across_context < 0.1` | `architecture-fitness-function` |
| "API responses must complete within 200ms at p99" | `latency.p99 < 200ms` | `architecture-fitness-function` |

Constraint derivation rules:
1. Parse `decision.statement` and `consequences` for quantifiable assertions
2. Map qualitative statements to fitness function predicates
3. Emit constraints in a standard constraint schema (see schema reference)
4. Constraints inherit the ADR's `meta.id` for traceability

### 3. Traceability

Every code change is linked to the ADR that authorized it:

- **Git commits**: include `Attestation-ADR: <adr-id>` in commit message footer
- **Policy attestation**: `policy-attestation-layer` verifies ADR status is `accepted` (not `proposed`/`deprecated`/`superseded`)
- **Build gates**: CI blocks merges where structural changes lack ADR attestation
- **Graph traversal**: `graphify` can walk from code entity -> ADR -> requirements -> stakeholders

### 4. Status Lifecycle

ADRs transition through a defined state machine:

```
                    +-----------+
                    |  proposed |
                    +-----+-----+
                          |
          +---------------+---------------+
          | rejected      | accepted      | deprecated (rare)
          v               v               v
    +-----------+   +-----------+   +-----------+
    |  rejected |   |  accepted |   | deprecated|
    +-----------+   +-----+-----+   +-----------+
                          |
                          | superseded
                          v
                    +-----------+
                    | superseded|
                    +-----------+
```

**State rules:**
- `proposed`: Under review. Code changes SHOULD NOT be attested to proposed ADRs.
- `accepted`: Active decision. Constraints derived from accepted ADRs are active.
- `deprecated`: Decision no longer applies, but was not replaced. No new code attestation. Existing attestations remain valid.
- `superseded`: Decision replaced by another ADR. Attestations should migrate to the superseding ADR.
- `rejected`: Decision was not approved. Archived for historical record.

**Transition metadata:**
Every transition records:
- `date`: ISO 8601 timestamp
- `actor`: who made the transition
- `reason`: human-readable explanation

### 5. Registry API

The decision registry is a directory-based store enabling queryable access:

**Directory structure:**
```
decisions/
  accepted/
    ADR-0001.json
    ADR-0002.json
  proposed/
    ADR-0042.json
  superseded/
    ADR-0010.json
  deprecated/
    ADR-0005.json
  rejected/
    ADR-0003.json
```

**Query patterns for `brownfield-intelligence` and `graphify`:**

1. **By status**: List all `accepted` decisions affecting `subsystem:payments`
2. **By date range**: Decisions made during Q3 2024
3. **By tag**: Decisions tagged with `security`, `scalability`, or `data-model`
4. **By superseded chain**: Trace the evolution of authentication strategy across ADR-0001 -> ADR-0010 -> ADR-0045
5. **By constraint impact**: Find all ADRs that derive constraints checked by a specific fitness function

**JSON query interface (pseudocode):**
```json
{
  "query": {
    "status": "accepted",
    "scope.subsystem": "payments",
    "tags": ["security"],
    "date.after": "2024-01-01"
  },
  "output": ["meta.id", "decision.statement", "constraints"]
}
```

---

## Integration with Other Skills

| Skill | Integration Pattern |
|-------|---------------------|
| `architecture-design` | Outputs design candidates; `adr-machine-capture` records the selected design as ADR |
| `trade-off-analyzer` | Provides comparison matrices; `adr-machine-capture` captures the chosen alternative with full rationale |
| `documentation-synthesizer` | Consumes ADRs to generate human-readable architecture docs; also converts narrative decisions into MADR-JSON |
| `architecture-fitness-function` | Consumes derived constraints from `adr-machine-capture` to generate automated tests and gates |
| `architecture-evolution` | Queries decision registry to understand historical context before proposing changes |
| `policy-attestation-layer` | Verifies ADR status and links code changes to authorizing ADRs |
| `brownfield-intelligence` | Discovers implicit decisions in legacy code; produces ADRs for the registry |
| `graphify` | Traverses ADR-linked graph: code -> ADR -> requirements -> stakeholders |

---

## Quick Reference: MADR-JSON Minimal Example

```json
{
  "meta": {
    "id": "ADR-0042",
    "date": "2024-06-15",
    "status": "accepted",
    "authors": ["architect-team"]
  },
  "context": {
    "problem": "Audit log must be tamper-evident for compliance",
    "forces": ["compliance-sox", "performance", "operational-simplicity"],
    "constraints": ["must-use-existing-postgresql"]
  },
  "decision": {
    "statement": "Use append-only immutable audit tables with cryptographic hash chaining",
    "rationale": "Immutable storage satisfies tamper-evidence with minimal infrastructure change"
  },
  "consequences": {
    "positive": ["No additional database needed", "Cryptographic verification possible"],
    "negative": ["Table growth unbounded", "Cannot delete old records without archiving"],
    "neutral": []
  },
  "alternatives": [
    {
      "option": "Separate blockchain ledger",
      "rationale_rejected": "Operational complexity exceeds compliance benefit"
    }
  ],
  "linked": {
    "requirements": ["REQ-1105"],
    "supersedes": null,
    "superseded_by": null,
    "related_adrs": ["ADR-0030"]
  }
}
```

---

## Validation

Always validate MADR-JSON documents using the provided script:

```bash
# Basic validation
python scripts/validate_adr.py --adr decisions/accepted/ADR-0042.json

# Strict mode (requires all recommended fields)
python scripts/validate_adr.py --adr decisions/accepted/ADR-0042.json --strict

# Extract constraints
python scripts/validate_adr.py --adr decisions/accepted/ADR-0042.json --extract-constraints

# Bulk validate directory
python scripts/validate_adr.py --dir decisions/ --strict
```

---

## Best Practices

1. **One decision per ADR**: Do not bundle multiple unrelated choices
2. **Quantify consequences**: Prefer measurable impacts over vague statements
3. **Link rejected alternatives**: The rationale for rejection is as important as the chosen path
4. **Keep context self-contained**: A reader should understand the decision without reading 10 other docs
5. **Status hygiene**: Transition ADRs promptly; stale `proposed` ADRs create uncertainty
6. **Constraint review**: When an ADR is superseded, review whether derived constraints should be retired or transferred
