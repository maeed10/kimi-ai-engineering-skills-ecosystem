---
name: runbook-generator
description: Automated failure-mode runbook generator for all L0 enforcement-layer skills. Use when onboarding to production, designing monitoring, responding to incidents, training operators, or updating skill failure modes. Documents symptoms, detection, degradation, and recovery per skill with cascade analysis.
---

# Runbook Generator

## Overview

This skill generates standardized, production-ready failure-mode runbooks for every L0 enforcement-layer skill in the Kimi CLI ecosystem. Each runbook documents: **symptoms → detection → impact assessment → recovery → verification → post-incident actions**, and includes cross-skill cascade analysis that maps how an L0 failure propagates to L1-L8 layers.

The skill is backed by a **failure taxonomy** (six primary failure mode categories with severity mapping rules), a **standard runbook template** (markdown with PagerDuty/OpsGenie integration stubs), and a **Python generation script** that consumes skill metadata and health endpoint schemas to produce per-skill runbooks automatically.

---

## When to Use This Skill

| Scenario | How This Skill Helps |
|----------|---------------------|
| **Production onboarding** | Generate the complete set of L0 runbooks before go-live; validate that every skill has detectable failure modes and documented recovery. |
| **Monitoring & alerting design** | Derive Prometheus/CloudWatch alert queries, health check thresholds, and PagerDuty severity rules directly from the taxonomy and metadata. |
| **Active incident response** | Load the affected skill's runbook to follow the step-by-step recovery procedure, verify remediation, and trigger post-incident tracking. |
| **Skill updates / releases** | Regenerate runbooks when a skill's health endpoints, config schema, deployment topology, or failure fingerprints change. |
| **SRE / operator training** | Use the taxonomy and canonical runbooks as training material so operators classify and remediate failures consistently. |

---

## Workflow Decision Tree

```
┌──────────────────────────────────────────────────────────────┐
│  Operator or Agent asks for runbook generation / update      │
└──────────────────┬─────────────────────────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │ Skill metadata and   │
         │ health schema        │
         │ available?           │
         └─────────┬────────────┘
                   │
      ┌────────────┼────────────┐
      ▼ No         ▼ Yes        ▼ Partial
┌──────────────┐ ┌──────────────┐ ┌─────────────────────────────┐
│ Guide user   │ │ Load         │ │ Load available metadata;    │
│ to collect   │ │ references/  │ │ infer missing fields from   │
│ metadata:    │ │ failure_       │ │ taxonomy defaults; flag     │
│ - skill.yaml │ │ taxonomy.md  │ │ placeholders for human      │
│ - health     │ │ +            │ │ review.                     │
│   endpoint   │ │ runbook_     │ │                             │
│   schema     │ │ template.md  │ │                             │
│ - deployment │ │              │ │                             │
│   topology   │ │              │ │                             │
└──────────────┘ └──────┬───────┘ └─────────────────────────────┘
                        │
         ┌──────────────▼──────────────┐
         │  Run scripts/generate_      │
         │  runbook.py against        │
         │  skill metadata            │
         └──────────────┬──────────────┘
                        │
         ┌──────────────▼──────────────┐
         │  Output generated per-skill│
         │  runbook + optional        │
         │  PagerDuty / OpsGenie JSON │
         └──────────────┬──────────────┘
                        │
         ┌──────────────▼──────────────┐
         │  Human review required?    │
         │  (placeholders, new         │
         │  fingerprints, edge cases)  │
         └──────────────┬──────────────┘
                        │
            ┌───────────┴───────────┐
            ▼ Yes                  ▼ No
┌──────────────────────┐  ┌──────────────────────┐
│ Present runbook in   │  │ Commit to            │
│ chat; operator       │  │ docs/runbooks/       │
│ fills missing        │  │ and update           │
│ recovery commands,   │  │ monitoring           │
│ canary tests,        │  │ dashboards.          │
│ contact info.        │  │                      │
└──────────────────────┘  └──────────────────────┘
```

---

## Key Behaviors

### 1. Per-Skill Runbook Template

Every generated runbook follows the exact section order below. Do not reorder or omit sections without documenting the rationale.

| Section | Purpose | Key Content |
|---------|---------|-------------|
| **1. Skill Overview** | Establish criticality and context | Purpose, blast radius, singleton vs. replicated, fail mode, compensating controls, architecture snapshot |
| **2. Failure Modes** | Symptom → Detection → Impact → Recovery → Verification → Post-Incident | One sub-section per failure mode (crash, hang, corruption, resource exhaustion, misconfiguration, dependency failure) |
| **3. Common Diagnostic Commands** | Accelerate MTTR with copy-paste commands | Quick status, log extraction, metric queries, dependency checks |
| **4. Escalation & Communication** | Ensure structured incident response | On-call rotations, PagerDuty/OpsGenie service keys, status update templates |
| **5. Revision History** | Audit trail for runbook changes | Version, date, author, what changed |

**References:**
- Full template markdown: `references/runbook_template.md`
- Example of a filled runbook: see any output of `scripts/generate_runbook.py`

---

### 2. Automated Generation from Skill Metadata

The script `scripts/generate_runbook.py` is the engine of this skill. It expects each skill to expose:

| Input | File Convention | Used For |
|-------|-----------------|----------|
| **Skill metadata** | `skills/<skill_id>/skill.yaml` or `metadata.yaml` | Names, ownership, deployment topology, fail mode, dependencies, on-call info |
| **Health endpoint schema** | Embedded in metadata under `observability.health_endpoint` | Detection section queries and thresholds |
| **Failure fingerprints** | Embedded in metadata under `failure_fingerprints` | Custom symptoms, log patterns, and recovery steps beyond taxonomy defaults |

**If metadata is missing fields**, the script falls back to taxonomy defaults and inserts `TBD` / `# not configured` placeholders so the operator knows what must still be defined.

**CLI examples:**
```bash
# Generate all runbooks in a directory
python scripts/generate_runbook.py \
  --skills-dir ./skills \
  --output-dir ./runbooks

# Generate for a single skill + PagerDuty + OpsGenie configs
python scripts/generate_runbook.py \
  --skill-id authz-engine \
  --skills-dir ./skills \
  --output-dir ./runbooks \
  --pagerduty \
  --opsgenie

# Generate with cross-skill cascade analysis
python scripts/generate_runbook.py \
  --skills-dir ./skills \
  --output-dir ./runbooks \
  --cascade-analysis ./runbooks/cascade_graph.json
```

---

### 3. Integration with PagerDuty / OpsGenie

Each generated runbook includes severity mapping and escalation rules that can be exported as integration configs.

**Severity mapping rules (enforced for all L0 skills):**

| Failure Mode Category | Default Severity | Override Condition |
|-----------------------|------------------|--------------------|
| Crash | SEV-1 | Always at least SEV-1 |
| Hang | SEV-1 | Always at least SEV-1 |
| Corruption | SEV-1 (or SEV-0) | SEV-0 if corruption inverts enforcement (e.g., allow-all instead of deny-list) |
| Resource Exhaustion | SEV-2 | SEV-1 if skill is singleton / no auto-scaling |
| Misconfiguration (startup) | SEV-2 | — |
| Misconfiguration (hot reload) | SEV-1 | Running config diverges from declared policy |
| Dependency (hard) | SEV-1 | Required by enforcement |
| Dependency (soft) | SEV-2 / SEV-3 | Depends on user impact |

**PagerDuty output:**
- One `service` object per L0 skill
- One `event_rule` per failure mode that maps alert payload fields to severity + annotation (runbook link)

**OpsGenie output:**
- One `alert_policy` per failure mode with team ownership, priority (`P1`–`P4`), and message filter conditions

---

### 4. Failure Mode Taxonomy

All failures are classified into six categories. The taxonomy defines subtypes, typical symptoms, severity floors, and degradation mode guidance.

| Category | Subtypes | Severity Floor | Degradation Mode Guidance |
|----------|----------|---------------|---------------------------|
| **Crash** | Panic, fatal signal, assertion failure, early exit | SEV-1 | Fail-closed preferred; fail-open requires documented compensating control |
| **Hang** | Deadlock, livelock, infinite loop, I/O block, zombie | SEV-1 | Process appears alive but makes no progress; health timeout is the key signal |
| **Corruption** | State, data, policy, silent skip, false positive | SEV-1 | Fail-alert until human validates state; do not silently continue with corrupted policy |
| **Resource Exhaustion** | Memory, CPU, disk, FD, network, thread exhaustion | SEV-2 (SEV-1 if singleton) | Fail-partial if subsystem isolation exists; otherwise fail-closed |
| **Misconfiguration** | Schema violation, missing field, cross-field inconsistency, env mismatch, secret error, hot-reload failure | SEV-2 (SEV-1 if hot reload) | Fail-alert; continue with last known good config if possible |
| **Dependency Failure** | Hard down, soft degraded, latency spike, contract break, split-brain | SEV-1 (hard) / SEV-2-3 (soft) | Fail-fixed (use cached state) for hard dependencies; fail-partial for soft dependencies |

**Degradation mode safety rule for L0 skills:**
- `fail-open` is **prohibited** for safety-critical enforcement unless accompanied by an explicit, reviewed compensating control.
- If a skill uses `fail-open`, the runbook must name the compensating control and link to its runbook.

**Reference:** `references/failure_taxonomy.md`

---

### 5. Cross-Skill Cascade Analysis

An L0 failure rarely stays isolated. The generator builds a cascade graph across all discovered skills to document downstream impact.

**How to use cascade analysis:**
1. When an L0 incident fires, load the runbook's **Appendix A** to see which L1-L8 skills are at risk.
2. Pre-emptively page or notify downstream on-call teams if the L0 skill's degradation mode has a wide blast radius.
3. During post-mortem, trace whether observed downstream failures were primary (independent bugs) or secondary (cascades from the L0 failure).

**Typical cascade patterns:**

| Downstream Layer | What Triggers the Cascade |
|------------------|---------------------------|
| L1 Orchestration | L0 policy engine fails closed → scheduling / ingress blocked |
| L2 Service Mesh | L0 identity provider down → sidecar mTLS validation fails |
| L3 Application | L0 secrets manager unavailable → apps cannot fetch credentials |
| L4 Data | L0 access control sync failed → database layer sees stale IAM |
| L5 Analytics | L0 audit log shipper down → compliance events lost |
| L6 ML / Inference | L0 model governance gate offline → unapproved models may deploy |
| L7 UI / API Gateway | L0 rate-limiter / WAF fails open → gateway overload |
| L8 Integration | L0 event bus policy engine offline → malformed events forwarded |

**Reference:** `references/failure_taxonomy.md` section 4 (Cascade Risk Matrix)

---

## Resources

### references/

#### `references/runbook_template.md`
Standard markdown template used by `generate_runbook.py`. Contains all required sections with placeholder tokens (`{skill_name}`, `{health_endpoint}`, `{recovery_steps}`, etc.). When loaded into context, use this template to:
- Validate that a generated runbook has not dropped sections.
- Manually author a runbook for a skill that lacks metadata (fill each placeholder).
- Compare an existing runbook against the canonical structure and identify gaps.

#### `references/failure_taxonomy.md`
Complete taxonomy of the six failure mode categories with subtypes, symptoms, severity definitions, degradation mode guidance, and cascade risk matrix. When loaded into context, use this to:
- Classify an ambiguous production anomaly into the correct category.
- Determine the correct severity floor before paging.
- Choose the appropriate degradation mode when modifying an L0 skill.
- Write the "Impact Assessment" section of a runbook.

### scripts/

#### `scripts/generate_runbook.py`
Production Python script for runbook generation. It can be executed directly, or read by the agent for patching, environment adjustments, or step-through debugging.

**Capabilities:**
- Discovers `skill.yaml` / `metadata.yaml` files in a directory tree.
- Parses skill metadata, health endpoints, and failure fingerprints.
- Synthesizes default failure modes from the taxonomy when fingerprints are absent.
- Renders per-skill runbooks from the standard template.
- Emits optional PagerDuty JSON and OpsGenie YAML integration stubs.
- Builds and exports the cross-skill cascade graph.

---

## Quick Start for Agents

When a user asks you to generate, update, or review an L0 runbook:

1. **Check inputs:** Ask (or search) for the skill's `skill.yaml` / `metadata.yaml` and health endpoint schema. If unavailable, guide the user to create them first.
2. **Load references:** Read `references/failure_taxonomy.md` and `references/runbook_template.md` into context.
3. **Generate:** Execute `scripts/generate_runbook.py` with the appropriate `--skills-dir` and `--output-dir`.
4. **Review:** Scan the generated runbook for `TBD` or `# not configured` placeholders. Prompt the user to supply missing recovery commands, canary tests, contact info, or custom log patterns.
5. **Deliver:** Present the final runbook markdown. If requested, also present the PagerDuty / OpsGenie JSON/YAML stubs and the cascade analysis appendix.
6. **Advise on updates:** If the skill's failure modes or deployment topology changed, recommend regenerating the runbook and updating monitoring dashboards.
