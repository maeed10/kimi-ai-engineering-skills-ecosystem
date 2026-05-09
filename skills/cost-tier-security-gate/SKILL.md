---
name: cost-tier-security-gate
description: Security gate for gemini-router cost-tier routing that prevents security-sensitive tasks from being sent to external LLM providers without full policy enforcement. Use when gemini-router classifies tasks, when configuring L1 Gateway Layer routing, or when auditing external routing decisions. Includes security sensitivity classifier, routing block list, and enhanced post-gemini validation.
---

# Cost-Tier Security Gate

Security gate for the `gemini-router` cost-tier fallback that prevents security-sensitive tasks from being routed to external LLM providers without full policy enforcement. Ensures the routing classifier respects safety boundaries and provides fail-closed behavior when classification is uncertain.

## When to Use

- When `gemini-router` classifies a task for cost-tier routing
- When a task involves security-sensitive operations (secret handling, policy validation, sandbox execution)
- When configuring routing rules for the L1 Gateway Layer
- When auditing which tasks were routed externally and why
- When `post-gemini-validator` processes outputs from Gemini

## Key Behaviors

### 1. Security Sensitivity Classifier

All tasks must be classified into one of three tiers before any routing decision is made:

| Classification | Description | Routing Allowed |
|---|---|---|
| `SECURITY-CRITICAL` | Tasks that handle secrets, credentials, cryptographic material, or enforce security policies | **NEVER** |
| `SECURITY-RELEVANT` | Tasks that operate on sensitive data or security-adjacent systems, but do not directly handle secrets | Conditional (requires policy pre-check) |
| `NON-SECURITY` | General-purpose tasks with no security implications | Yes (subject to cost-tier) |

The classifier uses a combination of:
- **Keyword heuristics**: Task description and skill name matching against sensitive terms
- **Skill metadata**: Tags, categories, and declared capabilities of the invoked skill
- **Context analysis**: File paths, environment variables, and prior conversation context
- **History correlation**: Past classifications for similar tasks (with decay)

**Confidence scoring**: Each classification includes a confidence score (0.0–1.0). Scores below `0.75` for `SECURITY-CRITICAL` or `SECURITY-RELEVANT` trigger manual review or default to `SECURITY-CRITICAL`.

### 2. Routing Block List

`SECURITY-CRITICAL` tasks are **NEVER** routed to Gemini regardless of cost-tier classification.

The block list covers:
- Secret/credential management skills
- Policy engine and validation skills
- Sandbox/code execution skills handling untrusted input
- Cryptographic key generation or signing skills
- IAM, RBAC, and access-control configuration skills
- Audit log and security monitoring skills

For the full block list, see `references/routing_block_list.md`.

### 3. Policy Engine Pre-Check

Before routing a `SECURITY-RELEVANT` or `NON-SECURITY` task to Gemini, the gate validates the task against a subset of non-negotiable policy rules:

- **Data residency**: Does the task data contain content marked `no-external-transfer`?
- **Classification ceiling**: Does the task involve data classified above the provider's clearance level?
- **Chain-of-trust**: Is the full execution chain (skills, tools, files) auditable and reproducible?
- **Output sensitivity**: Could Gemini output be used to infer sensitive internal state?
- **Rate-limit integrity**: Would external routing violate security-critical rate limits or circuit breakers?

Any policy rule that returns `BLOCK` causes immediate fallback to local execution.

### 4. Audit Logging

Every routing decision is logged with:

```yaml
audit_record:
  timestamp: ISO-8601
  task_id: uuid
  skill_name: string
  task_summary: string
  classification:
    tier: SECURITY-CRITICAL | SECURITY-RELEVANT | NON-SECURITY
    confidence: 0.0–1.0
    classifier_version: string
  routing_decision: LOCAL | GEMINI | BLOCKED
  policy_check:
    engine_version: string
    rules_evaluated: [rule_id]
    overall_result: PASS | BLOCK | REVIEW
    blocking_rule: rule_id | null
  gemini_request_id: string | null
  fallback_reason: string | null
  routing_metadata:
    cost_tier: string
    latency_budget_ms: number
    estimated_token_count: number
```

Logs are append-only, tamper-evident, and forwarded to the security monitoring pipeline.

### 5. Post-Gemini Security Validator

For outputs from Gemini that pass through the gate, enhanced validation is applied before the output is returned to the user or downstream skills:

- **IPI (Internal Proprietary Information) Scan**: Pattern matching and semantic detection for accidental disclosure of internal identifiers, architecture details, or non-public data.
- **Policy Validation**: Re-run policy rules on the generated output to detect policy violations in the response itself.
- **Semantic Drift Check**: Compare the semantic intent of the output against the original task to detect unexpected deviation that could indicate prompt injection or misalignment.

If any post-validation check fails, the output is quarantined and a local fallback is triggered with a security flag.

### 6. Fallback Safety

If the routing classifier fails (errors, timeout, or confidence below threshold), default to **local execution (fail-closed)**.

Failure modes that trigger fallback:
- Classifier timeout (> 500ms)
- Classifier error or exception
- Confidence score < 0.75 for SECURITY-CRITICAL or SECURITY-RELEVANT
- Missing or malformed skill metadata
- Policy engine unavailable or times out
- Audit logging system failure

The fallback is logged as `ROUTING_FAILURE → LOCAL` with the failure reason preserved.

## Usage

### Classifying a Task

```bash
python skills/cost-tier-security-gate/scripts/classify_security.py \
  --skill-name "secret-manager" \
  --task-description "Rotate AWS credentials for production cluster" \
  --tags "secrets,credentials,production" \
  --output json
```

Output:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "classification": "SECURITY-CRITICAL",
  "confidence": 0.97,
  "routing_decision": "BLOCKED",
  "policy_check": null,
  "reason": "Skill 'secret-manager' is in routing_block_list.md category 'secret/credential management'"
}
```

### Integrating with gemini-router

In the L1 Gateway Layer, wrap the `gemini-router` decision with the security gate:

```python
from skills.cost_tier_security_gate.scripts.classify_security import classify_task

def route_task(task):
    security_result = classify_task(task)
    
    if security_result["routing_decision"] == "BLOCKED":
        return execute_locally(task, reason=security_result["reason"])
    
    if security_result["routing_decision"] == "LOCAL":
        return execute_locally(task, reason=security_result.get("fallback_reason"))
    
    # Only proceed to gemini-router if explicitly allowed
    return gemini_router.route(task)
```

### Auditing Past Decisions

```bash
python skills/cost-tier-security-gate/scripts/classify_security.py \
  --audit-log /var/log/gateway/routing_audit.log \
  --query task_id=550e8400-e29b-41d4-a716-446655440000
```

## References

- `references/security_classifier.md` — Task categorization taxonomy and classification heuristics
- `references/routing_block_list.md` — Tasks and skill types permanently blocked from external routing

## Finding PR-9: Gemini Cost-Routing Trust Asymmetry

This skill addresses **Finding PR-9** from the Production Readiness Analysis, which identified that the `gemini-router` cost-tier fallback could inadvertently route security-sensitive tasks to an external LLM provider, creating a trust asymmetry: the router optimized for cost/latency without considering security boundaries.

**Mitigations applied by this skill:**
1. Security classification is a **prerequisite** to any routing decision, not an afterthought.
2. `SECURITY-CRITICAL` tasks are **hard-blocked**; the router cannot override.
3. Policy checks enforce **data residency and classification** rules before external transfer.
4. Audit logs provide **non-repudiable evidence** of routing decisions for compliance.
5. Post-Gemini validation catches **information leakage and semantic drift** in returned outputs.
6. Fail-closed behavior ensures that **any system failure** defaults to local, secure execution.
