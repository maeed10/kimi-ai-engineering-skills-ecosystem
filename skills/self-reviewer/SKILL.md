---
name: self-reviewer
description: >
  Deterministic AST-backed design and security review on agent-generated code before delivery. Replaces LLM-generated structural claims with reproducible AST metrics from Python ast module. Catches SOLID violations, cyclomatic complexity, code duplication, coupling, and security anti-patterns. Every structural claim backed by concrete metric. Trigger after Code Tester passes but before delivery. Integrates with Brownfield Intelligence, Boundary Enforcer, Style Enforcer, and Security Auditor.
---

# Self-Reviewer (v4.0 — Deterministic)

## What it does

Performs **deterministic** automated review on agent-generated code to catch design smells,
security anti-patterns, and maintainability problems before delivery. Every structural claim
is backed by a concrete AST-derived metric (e.g., cyclomatic complexity = 15, threshold = 10).
The LLM interprets and explains AST results; it **never** generates them heuristically.

Generates a structured review report with severity, location, concrete metric, threshold,
rationale, and fix suggestions. Acts as a merge gate: blocks delivery for critical findings,
warns for medium/low.

## When to use

- After **Code Tester** reports all tests passing, before final delivery
- When generating new modules, classes, or public APIs
- After **Refactoring Engine** produces a change set
- When **Boundary Enforcer** has flagged domain-crossing changes (verify coupling)
- Before **Documentation Synthesizer** writes final docs (findings may affect docs)
- When **Security Auditor** is unavailable or for preliminary security triage
- On any diff > 1 line — never skip review for "trivial" changes

## Key capabilities

1. **AST-based SOLID analysis** — Deterministic Single Responsibility, Open/Closed,
   Liskov Substitution, Interface Segregation, and Dependency Inversion checks using
   Python `ast.parse()`. Same code always produces the same findings.
2. **Complexity metrics from AST** — Cyclomatic complexity, function length, nesting depth,
   class size. Computed by tree traversal, not regex or guesswork.
3. **Code duplication detection** — Normalized AST subtree hash comparison identifies
   structurally identical blocks across files.
4. **Coupling analysis** — Import graph analysis detects excessive imports, cross-domain
   boundary violations, and circular dependencies.
5. **Security smell detection** — Missing input validation, insecure defaults,
   auth bypass risks, secret handling, injection vectors (AST + regex hybrid).
6. **Pattern consistency** — Naming conventions, error handling, logging/metrics
   against **Style Enforcer** norms and **Brownfield Intelligence** baselines
7. **Review report generation** — Structured Markdown + JSON report with severity,
   file, line, concrete metric, threshold, rationale, fix suggestion
8. **Merge gating** — Critical findings block delivery; medium/low append to
   delivery notes for human triage

## Architecture

```
Code files
    ↓
ast.parse()  ──→  AST tree  ──→  Metric extractors  ──→  Findings
    │                                                  ↑
    └────────  Deterministic, reproducible, no LLM ────┘
```

- **Metric extractors** walk the AST and emit raw numbers (complexity, counts, hashes).
- **Check engines** compare metrics against thresholds and emit `MetricFinding` objects.
- **LLM layer** (downstream) receives findings and writes human-readable rationale/fixes.
  It does NOT invent metrics.

## Workflow

### Step 1: Receive code changes

Accept input as one of:

- `diff` (unified diff or git diff)
- `files` list with before/after content
- `pr_context` with branch, files changed, and description

**Integration note**: Called by **Refactoring Engine** (post-change) or
**Code Generator** (post-generation) via orchestrator.

### Step 2: Load codebase context

Query **Brownfield Intelligence** for:

- Cyclomatic complexity baseline (per-file and per-function averages)
- Coupling norms (which domains may import which)
- Established error-handling patterns (exceptions vs Result types)
- Naming convention rules (from **Style Enforcer**)

Query **Boundary Enforcer** for:

- Domain boundary rules (which packages must not depend on which)
- Architecture constraints (hexagonal, layered, etc.)

### Step 3: Run deterministic AST analysis

Invoke `scripts/ast-analyzer.py` for each changed file. The analyzer produces
findings where every entry includes:

| Field | Example |
|-------|---------|
| `metric` | `cyclomatic_complexity` |
| `value` | `15` |
| `threshold` | `10` |
| `location` | `src/users/service.py:42` in function `create_user` |
| `ast_node_type` | `FunctionDef` |

#### SOLID checks (AST-derived)

| Principle | AST Metric | Threshold | Severity if violated |
|-----------|-----------|-----------|----------------------|
| **Single Responsibility** | `class_method_count` or `class_length_lines` | > 10 methods or > 500 lines | Medium |
| **Open/Closed** | `type_switch_chain_length` (isinstance / type checks in if/elif) | >= 2 branches | Medium |
| **Liskov Substitution** | `override_signature_change` (subclass narrows params) | any mismatch | Critical |
| **Interface Segregation** | `interface_method_count` or `interface_mixed_concerns` | > 5 methods or > 2 prefixes | Low |
| **Dependency Inversion** | `direct_concrete_instantiation` or `direct_concrete_instantiation_count` | any in high-level module, or > 3 per file | Medium / Critical |

#### Complexity checks (AST-derived)

| Metric | Threshold | Severity |
|--------|-----------|----------|
| `cyclomatic_complexity` | > 10 per function | Medium |
| `function_length_lines` | > 50 lines | Low |
| `nesting_depth` | > 4 levels | Medium |

#### Coupling checks (AST-derived)

| Metric | Threshold | Severity |
|--------|-----------|----------|
| `imports_per_file` | > 20 | Medium |
| `cross_domain_import` | any (high-level → low-level) | Critical |
| `circular_import` | any pair | Critical |

#### Duplication checks (AST-derived)

| Metric | Threshold | Severity |
|--------|-----------|----------|
| `duplicate_ast_subtree_lines` | >= 5 lines in 2+ locations | Medium |

**Scoring**: Each finding gets severity (Critical / Medium / Low). There is no
"uncertainty" field for AST-derived structural findings because the metric is objective.
Security heuristics (regex-based) retain uncertainty levels.

### Step 4: Run security heuristics

For each changed file, evaluate (regex + light AST hybrid):

| Smell | Detection pattern | Severity |
|-------|-------------------|----------|
| Missing input validation | Public function lacks null/empty/range/type checks on params | Critical |
| Insecure defaults | Boolean flag / config defaults to unsafe state | Critical |
| Auth bypass risk | Protected route/operation lacks auth check | Critical |
| Hardcoded secrets | Regex match for `api_key`, `password`, `secret`, `token` + high entropy | Critical |
| Sensitive data logging | Log statement includes password, token, PII | Critical |
| SQL injection | String concatenation or f-string in SQL query builder | Critical |
| Command injection | `os.system`, `subprocess.call`, `eval`, `exec` with user input | Critical |
| Path traversal | File path built from user input without sanitization | Critical |
| Unsafe deserialization | `pickle.loads`, `yaml.load`, `eval` on untrusted data | Critical |
| SSRF | HTTP request URL built from user input | Medium |
| Weak crypto | `MD5`, `SHA1`, `DES`, `RSA-1024`, `random` for security | Medium |
| Timing attack risk | String comparison for secrets (`==` instead of `hmac.compare_digest`) | Medium |
| CORS misconfiguration | `Access-Control-Allow-Origin: *` with credentials | Medium |
| Missing rate limiting | Public endpoint without throttling | Low |

### Step 5: Run pattern consistency checks

Cross-check against **Style Enforcer** norms and **Brownfield** baselines:

- **Naming**: Functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`;
  match repo-specific overrides from Style Enforcer
- **Error handling**: If repo uses `Result<T,E>` or custom exceptions, new code must
  follow same pattern; never silently swallow exceptions
- **Logging**: Use repo's logger (never `print`); include structured fields; never
  log secrets or PII
- **Metrics**: If repo emits custom metrics, new code should emit analogous metrics
  for equivalent operations
- **Comments**: No commented-out code blocks; docstrings on public APIs if repo norm

### Step 6: Generate structured review report

Produce two outputs simultaneously:

**Markdown** (human-readable, for PR comments / delivery notes):

```markdown
## Self-Review Report (Deterministic AST-backed)

### Summary
- Critical: 2 | Medium: 4 | Low: 3 | Total: 9
- Metrics collected: 8

### Critical Findings (Delivery Blocked)

#### A001 — Method 'process' in 'OrderProcessor' overrides base but changes parameter signature
- **File**: `src/orders/service.py:58`
- **Function**: `process`
- **Class**: `OrderProcessor`
- **Metric**: `override_signature_change = 4` (threshold = 3)
- **Severity**: CRITICAL
- **Category**: solid
- **AST node**: FunctionDef
- **Rationale**: LSP requires substitutability: subclass methods must accept the same arguments as the base.
- **Fix suggestion**: Redesign hierarchy to preserve base method contract, or use composition instead of inheritance.
```

**JSON** (machine-readable, for downstream tooling):

```json
{
  "summary": { "critical": 2, "medium": 4, "low": 3, "total": 9, "metrics_collected": 8 },
  "blocked": true,
  "findings": [
    {
      "id": "A001",
      "severity": "critical",
      "category": "solid",
      "metric": "override_signature_change",
      "value": 4,
      "threshold": 3,
      "location": { "file": "src/orders/service.py", "line": 58, "function": "process", "class_name": "OrderProcessor" },
      "message": "Method 'process' in 'OrderProcessor' overrides base but changes parameter signature",
      "rationale": "...",
      "fix_suggestion": "...",
      "ast_node_type": "FunctionDef"
    }
  ]
}
```

### Step 7: Merge gate decision

| Condition | Action |
|-----------|--------|
| Any Critical finding | **Block delivery**. Report to human with full Markdown report. Escalate security findings to **Security Auditor**. |
| Any Medium finding | **Warn**. Append findings to delivery notes / PR comments. Proceed with delivery but flag for human triage. |
| Only Low findings | **Info**. Append to delivery notes. Proceed normally. |
| Zero findings | **Pass**. No report needed; optionally emit "Self-review passed" one-liner. |

### Step 8: Hand off

- If blocked: return control to human; do **not** auto-apply fixes
- If warned: append findings to PR comments; proceed to **Documentation Synthesizer**
  and **Style Enforcer** with review annotations
- If passed: proceed to **Documentation Synthesizer** and **Style Enforcer**

## Safety highlights

- **ALWAYS** block delivery and escalate to human when critical findings are detected.
  Never silently downgrade critical severity.
- **ALWAYS** include a concrete fix suggestion with code or pseudocode, not just a
  complaint. The report must be actionable.
- **ALWAYS** distinguish between "this is objectively wrong" (e.g., missing auth check,
  AST metric = 15 > threshold = 10) and "this deviates from project norms" (e.g., naming
  mismatch). Label clearly.
- **ALWAYS** run review regardless of change size. Bugs and security flaws hide in
  one-line changes.
- **NEVER** auto-apply review findings without explicit human confirmation. The role
  is reviewer, not editor.
- **NEVER** treat heuristic findings as absolute truth. Use "flag", "suspect",
  "consider" language when uncertainty is high. **AST-derived structural findings**
  have low uncertainty by design; regex-based security findings retain medium/high
  uncertainty.
- **NEVER** contradict **Code Tester** findings. If tests pass but design smells exist,
  report as "works but consider refactoring" — not as a failure.
- **NEVER** skip the review pipeline for "trivial" or "hotfix" changes.
- **NEVER** emit the full JSON report into chat-visible output unless the user
  explicitly requests machine-readable format. Default to Markdown summary.
- **NEVER** log or include sensitive findings (e.g., detected hardcoded secrets) in
  cleartext logs or non-secure channels. Hash or redact the value.

## Deterministic Safety Rules (v4.0)

These rules are enforced by the `ast-analyzer.py` engine and must be respected by
all downstream interpretation:

1. **NEVER report a "design smell" without a concrete AST-derived metric.**
   Every structural finding must state: metric name, measured value, threshold,
   and code location. Example: `cyclomatic_complexity = 15`, `threshold = 10`,
   `file.py:42`.

2. **NEVER use LLM reasoning alone for structural analysis claims.**
   The LLM may summarize, explain, and suggest fixes. It may NOT invent complexity
   scores, method counts, or coupling degrees. All such numbers come from `ast.parse()`.

3. **ALWAYS reproduce the same findings on the same code.**
   `ast-analyzer.py` uses deterministic tree walks and normalized hashes. Re-running
   on identical source must yield identical findings (modulo ID ordering).

4. **ALWAYS include the AST metric, threshold, and code location in every finding.**
   The report format requires `metric`, `value`, `threshold`, `location.file`,
   `location.line` on every finding. Missing fields make the finding invalid.

5. **Prefer AST over regex for structural claims.**
   Regex may be used for security smells (secrets, injection vectors) where
   literal matching is appropriate. Design and coupling claims MUST use AST.

## Integration with other skills

| Skill | Direction | Purpose |
|-------|-----------|---------|
| **Code Tester** | Reads results from | Gate trigger: only run Self-Reviewer after tests pass |
| **Code Generator** | Receives code from | Review target: new code from generation |
| **Refactoring Engine** | Receives diffs from | Review target: refactored code |
| **Brownfield Intelligence** | Queries for baselines | Complexity norms, coupling norms, pattern norms |
| **Boundary Enforcer** | Queries for rules | Domain boundaries, architecture constraints |
| **Style Enforcer** | Queries for naming/patterns | Naming conventions, error-handling patterns |
| **Security Auditor** | Feeds findings to | Escalate security-critical findings for deep audit |
| **Documentation Synthesizer** | Runs after | Review findings may affect documentation scope |

**Execution order in v4.0 pipeline**:

```
Code Generator / Refactoring Engine
    ↓
Code Tester (must pass)
    ↓
Self-Reviewer ← YOU ARE HERE
    ↓
Style Enforcer (final polish)
    ↓
Documentation Synthesizer
    ↓
Delivery
```

## References

- `references/design-heuristics.md` — SOLID principles, common smell catalog, and
  complexity thresholds with rationale. Updated with deterministic metric definitions.

## Scripts

- `scripts/ast-analyzer.py` — **Primary deterministic analyzer**. AST-based checks
  for SOLID, complexity, coupling, duplication. Accepts `--files`, `--repo`, `--since`;
  outputs Markdown + JSON with `metric`, `value`, `threshold`, `location` on every
  finding. Intended for local execution, CI integration, and as the upstream data
  source for the LLM interpretive layer.
- `scripts/run-review.py` — Heuristic review runner (regex + light AST). Still
  used for security smell regex patterns and pattern consistency checks. Calls
  `ast-analyzer.py` as its deterministic structural engine when available.