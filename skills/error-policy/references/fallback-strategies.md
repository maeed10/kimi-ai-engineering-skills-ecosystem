# Fallback Strategies Reference

Kimi AI Engineering Skills Ecosystem v4.0 — Error Policy

This document defines the **degraded-mode fallback strategies** for every skill
in the ecosystem. Each skill MUST register at least one fallback in the
`FallbackRegistry` so that `error-policy` can execute a safe alternative when
the primary execution path fails.

**Fallback principles:**
- A fallback produces **lower-fidelity but safe** results.
- A fallback MUST NOT silently reduce security. If the only option is "less
  secure," it is tagged `requires_policy_approval=True` and will trigger
  ESCALATE rather than auto-execution.
- Fallback outputs are always tagged `degraded=True` in `ScriptResult.findings`.
- Fallbacks themselves are wrapped in `ErrorPolicy.run()` with `retry_count=0`
  to prevent infinite loops.

---

## Table of Contents

1. [security-auditor](#security-auditor)
2. [code-tester](#code-tester)
3. [performance-validator](#performance-validator)
4. [resilience-tester](#resilience-tester)
5. [dependency-resolver](#dependency-resolver)
6. [adversarial-tester](#adversarial-tester)
7. [architecture-evolution](#architecture-evolution)
8. [ci-cd-integrator](#ci-cd-integrator)
9. [infrastructure-as-code](#infrastructure-as-code)
10. [ipi-defender](#ipi-defender)
11. [memory-guard](#memory-guard)
12. [phase-controller](#phase-controller)
13. [policy-engine](#policy-engine)
14. [sandbox-executor](#sandbox-executor)
15. [self-reviewer](#self-reviewer)
16. [skill-registry](#skill-registry)
17. [spec-decomposer](#spec-decomposer)
18. [drift-monitor](#drift-monitor)
19. [error-policy](#error-policy)
20. [gateway](#gateway)

---

## security-auditor

**Critical gate**: YES — failures escalate to HITL if fallback fails.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `regex-static-scan` | Static regex + file entropy check | Medium | No |
| `dependency-only-audit` | Known-vulnerability DB lookup on requirements | Low | No |
| `manual-checklist` | Emit structured checklist for human review | Low | No |

**Primary failure modes addressed:**
- Semgrep binary unavailable or crashes
- SARIF parser fails on malformed output
- Network timeout pulling vulnerability DB

**Security rule**: The `regex-static-scan` fallback is intentionally **narrower**
than Semgrep but does not introduce new attack surface. It is the default
fallback. `manual-checklist` is used when even regex scanning fails.

---

## code-tester

**Critical gate**: YES — failures escalate to HITL if fallback fails.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `ast-smoke-test` | Parse AST, validate imports, check syntax | Low | No |
| `static-import-check` | Verify all imports resolve without execution | Low | No |
| `coverage-exempt-run` | Run tests without coverage (faster, less data) | Medium | No |

**Primary failure modes addressed:**
- Pytest crashes due to environment mismatch
- Coverage plugin corrupts test run
- Docker test runner unavailable

**Note**: `coverage-exempt-run` is only viable if the failure was in the
coverage subsystem, not the test framework itself.

---

## performance-validator

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `static-complexity` | Radon / cyclomatic complexity scan | Low | No |
| `dependency-weight` | Count dependency tree size as proxy | Low | No |
| `lint-timing-estimate` | Estimate cost from AST node counts | Low | No |

**Primary failure modes addressed:**
- Locust load-test infrastructure unavailable
- Benchmark runner OOM or timeout
- Network partition to test environment

---

## resilience-tester

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `fault-tree-checklist` | Static fault-tree analysis checklist | Low | No |
| `dependency-chaos-skip` | Skip live chaos; analyze redundancy from manifest | Low | No |

**Primary failure modes addressed:**
- Chaos injection framework (e.g., Chaos Mesh) not installed
- Kubernetes API unavailable for fault injection
- Test environment too fragile for disruption

---

## dependency-resolver

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `direct-only-parse` | Parse only direct dependencies, skip transitive lock | Low | No |
| `requirements-fallback` | Use existing requirements.txt without lockfile | Low | No |
| `offline-manifest` | Use cached manifest if network fails | Low | No |

**Primary failure modes addressed:**
- Package index (PyPI, npm) unreachable
- Resolver algorithm (Poetry, pip-tools) crashes on complex constraints
- Lockfile generation exceeds memory/time limits

---

## adversarial-tester

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `prompt-pattern-scan` | Static regex scan for known prompt-injection patterns | Low | No |
| `input-sanitize-check` | Verify sanitization layers are present in code | Low | No |
| `rule-based-jailbreak` | Run predefined jailbreak templates without LLM | Low | No |

**Primary failure modes addressed:**
- Target LLM API rate-limited or offline
- Adversarial test harness (e.g., Garak) crashes
- Evaluation scorer (GPT-4 judge) unavailable

---

## architecture-evolution

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `git-history-static` | Analyze commit history and file churn only | Low | No |
| `manual-review-trigger` | Generate architecture review checklist for human | Low | No |
| `heuristic-complexity` | Count LOC, cyclomatic, and coupling heuristics | Low | No |

**Primary failure modes addressed:**
- Structural analysis tool (e.g., pydeps, archunit) fails
- Git history too large to process
- Dependency graph generation OOM

---

## ci-cd-integrator

**Critical gate**: NO — pipeline may continue degraded, but deployment blocked.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `local-dry-run` | Run CI pipeline locally (pytest, lint) without remote | Medium | No |
| `manifest-validate` | Validate CI YAML/json syntax only | Low | No |
| `deployment-block` | Skip deployment, emit block notification | Low | No |

**Primary failure modes addressed:**
- CI platform (GitHub Actions, GitLab CI) API unavailable
- Runner registration fails
- Secrets injection mechanism broken

**Safety rule**: `deployment-block` is the **default** fallback if any CI/CD
execution fails, because an unvalidated deployment is worse than no deployment.

---

## infrastructure-as-code

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `plan-only` | Run `terraform plan` / `kubectl diff` but do not apply | Medium | No |
| `syntax-validate` | Validate HCL/YAML syntax without provider calls | Low | No |
| `state-read-only` | Read current state, skip mutation | Low | No |

**Primary failure modes addressed:**
- Terraform provider plugin crash
- Cloud API rate limit during apply
- Kubectl context misconfiguration

**Safety rule**: `plan-only` is always preferred over `syntax-validate` because
it still validates provider connectivity and state drift. `apply` operations
are destructive and never retried more than once without HITL.

---

## ipi-defender

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `rule-based-filter` | Static rule-based PII regex scan | Medium | No |
| `entropy-scan` | Detect high-entropy strings (keys, tokens) | Low | No |
| `manual-data-review` | Emit flagged data samples for human review | Low | No |

**Primary failure modes addressed:**
- ML-based PII classifier model unavailable
- Presidio / Microsoft IPI engine crashes
- GPU memory exhausted during inference

---

## memory-guard

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `static-context-audit` | Count tokens, estimate context window overflow | Low | No |
| `summarization-fallback` | Use lightweight summarizer instead of full recall | Low | No |
| `truncation-log` | Log what would be truncated for human review | Low | No |

**Primary failure modes addressed:**
- Vector DB (Chroma, Pinecone) query timeout
- Embedding model API failure
- Memory context compression algorithm error

---

## phase-controller

**Critical gate**: YES — failures escalate to HITL.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `manual-phase-signoff` | Emit phase checklist for human gate approval | Low | No |
| `read-only-state` | Read current phase state, do not transition | Low | No |

**Primary failure modes addressed:**
- State store (file/DB) corruption or lock
- Phase transition validation rule engine crash
- Dependency on another critical gate that failed

**Safety rule**: Phase transitions are **irreversible** in many cases. If the
controller cannot validate all gate conditions, it MUST NOT transition. The
`read-only-state` fallback keeps the system in the current phase and emits a
human signoff request.

---

## policy-engine

**Critical gate**: YES — policy violations bypass fallback and go to HALT.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `static-policy-list` | Evaluate against hardcoded baseline rules | Low | Yes |
| `manual-policy-audit` | Emit full context for human policy review | Low | No |

**Primary failure modes addressed:**
- Policy rule interpreter (e.g., OPA/Rego) crashes
- Policy DB unreachable
- Dynamic policy evaluation times out

**Security rule**: `static-policy-list` requires explicit policy approval
because it may be **stale** compared to the live policy DB. The default behavior
when the policy engine fails is ESCALATE, not fallback execution.

---

## sandbox-executor

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `restricted-local-run` | Run in local restricted subprocess without container | Medium | Yes |
| `static-analysis-only` | Skip execution; run static lint/type check | Low | No |
| `no-execution` | Skip execution entirely, log reason | Low | No |

**Primary failure modes addressed:**
- Docker daemon unavailable
- Sandbox timeout or OOM kill
- Security policy prevents container creation

**Security rule**: `restricted-local-run` requires policy approval because it
relaxes the sandbox boundary. Default is `static-analysis-only` or `no-execution`.

---

## self-reviewer

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `diff-stat-review` | Review only diff stats (lines changed, files touched) | Low | No |
| `checklist-review` | Run static review checklist against diff | Low | No |
| `defer-to-human` | Queue diff for human reviewer without AI review | Low | No |

**Primary failure modes addressed:**
- LLM reviewer API unavailable or rate-limited
- Review context exceeds token limit
- Review scoring pipeline crash

---

## skill-registry

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `cached-manifest` | Use last known good skill manifest | Low | No |
| `static-skill-list` | Read from hardcoded core skill list | Low | No |
| `no-skill-discovery` | Skip dynamic discovery, use explicit skill set | Low | No |

**Primary failure modes addressed:**
- Registry DB or file store unreachable
- Skill manifest schema mismatch after upgrade
- Network partition to remote registry

---

## spec-decomposer

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `heading-based-split` | Split spec by markdown headings only | Low | No |
| `manual-decomposition` | Emit spec for human decomposition | Low | No |
| `keyword-cluster` | Cluster requirements by keyword frequency | Low | No |

**Primary failure modes addressed:**
- LLM decomposer API failure
- Spec too large for decomposition context window
- Decomposed sub-tasks fail validation (cyclic dependencies)

---

## drift-monitor

**Critical gate**: NO — pipeline may continue degraded.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `timestamp-check` | Compare file timestamps as drift proxy | Low | No |
| `hash-snapshot` | Compare content hashes without semantic analysis | Low | No |
| `manual-drift-log` | Emit current snapshot for human comparison | Low | No |

**Primary failure modes addressed:**
- Semantic diff engine unavailable
- Baseline snapshot corrupted
- Monitoring collector (Prometheus, etc.) unreachable

---

## error-policy

**Critical gate**: YES — if the error policy engine itself fails, the system
must halt because there is no higher recovery layer.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `immediate-halt` | Stop all execution, require manual restart | N/A | N/A |
| `fail-fast-log` | Log failure and exit process | N/A | N/A |

**Primary failure modes addressed:**
- Audit log disk full
- Circuit breaker state corruption
- FallbackRegistry lookup infinite loop (defensive coding prevents this)

**Safety rule**: There is no safe fallback for the error-policy engine itself.
Any failure here is a **meta-failure** and triggers `immediate-halt`.

---

## gateway

**Critical gate**: YES — failures escalate to HITL.

| Strategy ID | Mode | Fidelity | Policy Approval |
|-------------|------|----------|-----------------|
| `bypass-auth-readonly` | Allow read-only traffic without auth validation | Medium | Yes |
| `static-response` | Return cached/static health responses | Low | No |
| `maintenance-mode` | Block all traffic, emit maintenance message | Low | No |

**Primary failure modes addressed:**
- Authentication provider (OAuth, SSO) outage
- Rate limiter (Redis) unavailable
- Gateway configuration reload fails

**Security rule**: `bypass-auth-readonly` requires explicit policy approval and
is logged as a critical security event. Default fallback is `maintenance-mode`.

---

## Fallback Registration Template

When implementing a new skill, register its fallback in the skill's main script:

```python
from error_policy import FallbackRegistry, ScriptResult

def my_fallback(params: dict) -> ScriptResult:
    # Degraded but safe execution
    findings = degraded_analysis(params["target"])
    return ScriptResult(
        exit_code=0,
        findings=[{"mode": "degraded", "data": findings}],
        degraded=True,
    )

FallbackRegistry.register(
    skill_id="my-new-skill",
    strategy_id="static-heuristic",
    fn=my_fallback,
    requires_policy_approval=False,
    description="Lightweight heuristic when primary analysis fails",
)
```

---

## Change Log

| Date | Version | Change |
|------|---------|--------|
| 2024-05-06 | v4.0.0 | Initial fallback strategy definitions for all v4.0 skills |
