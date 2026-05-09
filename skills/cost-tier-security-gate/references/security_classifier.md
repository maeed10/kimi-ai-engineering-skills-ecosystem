# Security Classifier Taxonomy and Heuristics

This document defines the task categorization taxonomy used by the `cost-tier-security-gate` and the heuristics that drive automatic classification.

## Classification Tiers

### SECURITY-CRITICAL

**Definition**: Tasks that directly handle secrets, credentials, cryptographic material, enforce security policies, or could compromise the confidentiality, integrity, or availability of the system if executed incorrectly or exposed to an external party.

**Routing Rule**: **PERMANENTLY BLOCKED** from external LLM routing. Always execute locally.

**Indicators**:
- Skill name contains: `secret`, `credential`, `password`, `token`, `key`, `cert`, `auth`, `vault`, `kms`, `hsm`, `encrypt`, `decrypt`, `sign`, `policy`, `guardrail`, `audit`, `rbac`, `iam`, `acl`
- Tags include: `secrets`, `cryptography`, `security-policy`, `authentication`, `authorization`
- Task description contains patterns: `rotate.*credential`, `generate.*key`, `validate.*policy`, `sign.*request`, `decrypt.*data`
- Accesses files under: `/secrets/`, `/etc/ssl/`, `~/.ssh/`, `*keystore*`, `*credential*`
- Environment variables accessed: `*_SECRET`, `*_TOKEN`, `*_KEY`, `*_PASSWORD`, `AWS_ACCESS_KEY_ID`, `PRIVATE_KEY`

**Examples**:
- Rotating AWS or database credentials
- Generating or signing TLS certificates
- Validating organization security policies
- Enforcing sandbox escape prevention
- Modifying IAM roles or RBAC bindings
- Accessing HashiCorp Vault or AWS KMS

**Confidence Boosters**:
- Multiple indicator categories match (skill name + file path + env var)
- Skill is explicitly listed in `routing_block_list.md`
- Prior manual classification exists in audit history

### SECURITY-RELEVANT

**Definition**: Tasks that operate on sensitive data, security-adjacent systems, or infrastructure that could indirectly impact security posture if mishandled. They do not directly handle secrets but touch systems or data where confidentiality matters.

**Routing Rule**: Allowed to Gemini **only if** all policy pre-checks pass. Otherwise local execution.

**Indicators**:
- Skill name contains: `database`, `backup`, `monitor`, `alert`, `infra`, `network`, `firewall`, `dns`, `compliance`, `scan`, `cve`, `patch`, `deploy`
- Tags include: `production`, `sensitive-data`, `infrastructure`, `compliance`, `monitoring`
- Task description contains patterns: `production.*database`, `backup.*sensitive`, `scan.*vulnerability`, `deploy.*infra`
- Accesses files under: `/prod/`, `/db/`, `/backup/`, `/infrastructure/`, `*production*`
- Environment variables accessed: `DATABASE_URL`, `PROD_*`, `*_HOST` in production context

**Examples**:
- Querying a production database schema (not credentials)
- Generating infrastructure-as-code templates for production
- Analyzing vulnerability scan results
- Reviewing compliance configuration drift
- Updating firewall rules or DNS records

**Policy Pre-Check Requirements**:
- Data residency check: No `no-external-transfer` labels on referenced data
- Output sensitivity check: Gemini output cannot be used to reconstruct internal topology
- Audit chain check: All inputs and outputs remain in the audit log

### NON-SECURITY

**Definition**: General-purpose tasks with no security implications. They do not handle secrets, sensitive infrastructure, or policy-enforcement functions.

**Routing Rule**: Allowed to Gemini subject to cost-tier and latency constraints.

**Indicators**:
- Skill name contains: `docs`, `search`, `summarize`, `translate`, `explain`, `code-review`, `test`, `lint`, `format`
- Tags include: `documentation`, `general`, `public-data`, `open-source`, `utility`
- Task description contains no sensitive keywords or patterns
- Accesses only public/open-source files or user-provided non-sensitive content
- No production environment variables or secret paths accessed

**Examples**:
- Summarizing public documentation
- Translating user-facing content
- Formatting or linting code in a non-production context
- Explaining open-source library usage
- General brainstorming or creative writing

## Classification Heuristics Engine

### Keyword Matching

The classifier maintains weighted keyword dictionaries per tier. A task receives a raw score per tier based on keyword matches.

```python
# Pseudocode for keyword scoring
scores = {
    "SECURITY-CRITICAL": 0,
    "SECURITY-RELEVANT": 0,
    "NON-SECURITY": 0
}

for word in tokenized(task_description + skill_name + tags):
    for tier in TIERS:
        if word in KEYWORDS[tier]:
            scores[tier] += KEYWORDS[tier][word].weight
```

Weights are tuned so that a single strong SECURITY-CRITICAL keyword (e.g., `vault`, `secret`) can dominate the score, but multiple SECURITY-RELEVANT keywords in combination can also elevate a task.

### Context Analysis

Beyond keyword matching, the classifier inspects:

1. **File Path Sensitivity**: Access to paths under `/secrets/`, `/etc/ssl/`, `~/.ssh/`, or containing `prod`, `production`, `sensitive` contributes to tier elevation.
2. **Environment Variable Inspection**: Access to variables matching sensitive patterns (`*_SECRET`, `*_TOKEN`, `PRIVATE_KEY`, etc.) is a strong SECURITY-CRITICAL signal.
3. **Skill Metadata**: If the skill's `SKILL.md` or manifest includes `security-sensitive: true` or tags like `secrets`, the classification is elevated regardless of task description.
4. **Conversation Context**: If the current session previously handled SECURITY-CRITICAL tasks, subsequent tasks are elevated by one tier (with a decay factor of 0.5 per turn).

### Confidence Scoring

The final confidence score reflects how unambiguous the classification is:

```
confidence = max_score / (max_score + second_best_score + epsilon)
```

- `confidence >= 0.90`: High confidence — proceed automatically
- `0.75 <= confidence < 0.90`: Medium confidence — allowed for SECURITY-RELEVANT and NON-SECURITY; BLOCKED for SECURITY-CRITICAL unless manual review flag is set
- `confidence < 0.75`: Low confidence — default to SECURITY-CRITICAL treatment (fail-closed)

### Classification Overrides

Manual overrides can be configured in the gateway configuration:

```yaml
classifier_overrides:
  - skill_name: "my-custom-secret-helper"
    force_tier: "SECURITY-CRITICAL"
    reason: "Handles user-provided credentials"
  - skill_name: "public-doc-search"
    force_tier: "NON-SECURITY"
    reason: "Only searches public documentation"
```

Overrides are themselves logged and audited.

## Versioning

The classifier taxonomy and heuristics are versioned. Changes to keyword weights, path patterns, or tier definitions increment the `classifier_version` field in audit logs.

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | Initial | Baseline taxonomy with keyword, path, and env-var heuristics |

