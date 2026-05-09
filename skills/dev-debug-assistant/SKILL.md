---
name: dev-debug-assistant
description: Developer-facing debugging assistant that analyzes stack traces, logs, and errors to identify root causes and suggest fixes. Use when tests fail, runtime errors occur, investigating memory leaks, analyzing CI failures, or debugging race conditions. Supports structured and unstructured log parsing, breakpoint suggestions, and ranked fix hypotheses.
---

# Dev Debug Assistant

## Overview

The Dev Debug Assistant is a systematic debugging companion for everyday software engineering. It analyzes stack traces, logs, error messages, and code context to identify root causes, generate ranked hypotheses, and suggest concrete fixes. It integrates with common debugging workflows across languages and frameworks.

## When to Use This Skill

- A test fails with a stack trace or assertion error
- A runtime exception or crash occurs in development, staging, or production
- Application logs show anomalies, repeated errors, or degraded performance
- Investigating memory leaks, high CPU usage, or latency spikes
- Debugging race conditions, deadlocks, or concurrency issues
- A CI/CD pipeline fails and logs need rapid analysis
- A service mesh or distributed system shows correlated failures

## Core Capabilities

### 1. Stack Trace Analysis

Parse stack traces to identify:
- **Failing function/method** and exact line number
- **Exception type** and message semantics
- **Root cause vs. symptom frames** (distinguish library noise from user code)
- **Caused-by chains** in nested/wrapped exceptions
- **Thread context** in multi-threaded dumps

**Workflow:**
1. Receive stack trace → 2. Sanitize and normalize frames → 3. Identify user vs. library frames → 4. Locate error origin → 5. Cross-reference with code context → 6. Rank hypotheses

### 2. Log Parsing

Analyze logs in any format:
- **Structured (JSON)**: Parse `level`, `timestamp`, `message`, `trace_id`, `span_id`, `service`, `error.*` fields
- **Unstructured (plain text)**: Extract timestamps, severity, error signatures via regex patterns
- **Multi-service correlation**: Link errors across services using trace IDs or temporal proximity
- **Log frequency analysis**: Detect spikes, repeated patterns, or cascading failures

### 3. Error Pattern Matching

Match errors against known issue databases:
- **Stack Overflow patterns**: Common questions for exception types
- **GitHub issues**: Known bugs in libraries/frameworks by version
- **Framework-specific catalogs**: Built-in knowledge from `references/error_catalog.md`
- **Language-specific idioms**: Null pointer vs. None vs. nil root causes

### 4. Breakpoint Suggestions

Recommend strategic breakpoints based on:
- **Error location**: Just before the failing line to inspect state
- **Data flow entry**: Where suspicious input enters the system
- **State mutation**: Where shared state is modified (race conditions)
- **Boundary crossings**: API boundaries, serialization points, I/O barriers
- **Precondition checks**: Where invariants should hold but might not

### 5. Variable State Analysis

Trace variable values through the call stack:
- **Parameter inspection**: Identify unexpected nulls, empty collections, malformed data
- **Mutation tracking**: Find where correct input becomes corrupted
- **Scope analysis**: Detect use-after-free, closure capture issues, or stale references
- **Type mismatches**: Implicit conversions, generics erasure, dynamic typing surprises

### 6. Root Cause Hypothesis

Generate ranked hypotheses with confidence scores:

| Rank | Confidence | Hypothesis | Validation Step |
|------|-----------|------------|-----------------|
| 1 | 85% | Null pointer from unvalidated API response | Add null check + unit test |
| 2 | 60% | Race condition on non-thread-safe collection | Review concurrent access points |
| 3 | 30% | Framework bug in v2.3.1 | Check changelog, upgrade to v2.3.2 |

**Hypothesis generation rules:**
- Prioritize code in user-controlled frames over library internals
- Weight recent changes higher (version control recency)
- Flag environmental causes (config, secrets, resource limits)
- Consider input validation failures before algorithmic bugs

### 7. Fix Suggestions

Propose code fixes in diff-style output:

```diff
  def process_order(order):
-     total = order.subtotal + order.tax
+     if order is None:
+         raise ValueError("Order cannot be None")
+     total = (order.subtotal or 0) + (order.tax or 0)
      return total
```

Fix categories:
- **Defensive coding**: null checks, boundary validation, type guards
- **Resource management**: close files, release locks, dispose connections
- **Concurrency fixes**: synchronization, atomic operations, immutability
- **Configuration**: environment variable defaults, feature flags, timeouts
- **Algorithmic**: off-by-one, comparison logic, sort ordering

### 8. Reproduction Steps

Generate minimal reproduction cases from error context:
- Extract input parameters that triggered the failure
- Create unit test scaffolding with mocked dependencies
- Suggest environment conditions (load, timing, state)
- Provide minimal `curl` commands for API failures
- Build containerized reproductions for environment-specific bugs

## Debugging Methodology

### The R.A.P.I.D. Cycle

1. **R**eceive — Capture the error, stack trace, logs, and surrounding code context
2. **A**nalyze — Parse structure, identify frames, extract variables, correlate events
3. **P**rioritize — Rank hypotheses by confidence, impact, and ease of validation
4. **I**nvestigate — Validate top hypotheses via inspection, breakpoints, or tests
5. **D**eliver — Propose fix with diff, reproduction case, and prevention strategy

### Input Gathering Checklist

Always request or extract:
- [ ] Full stack trace or exception message
- [ ] Relevant log lines (ERROR, WARN, FATAL) within +/- 30 seconds
- [ ] Code around the failing line (±10 lines minimum, ±50 preferred)
- [ ] Language and framework versions
- [ ] Environment details (OS, runtime, container, CI job)
- [ ] Recent changes (last commit, deployment, dependency update)
- [ ] Input data or request payload that triggered the error
- [ ] Frequency (one-off, intermittent, consistent after change)

## Integration with Workflows

### Local Development Debug Loop
1. Capture exception in IDE/terminal
2. Run `analyze_error.py` or manual analysis on stack trace
3. Review breakpoint suggestions
4. Apply fix suggestion
5. Run targeted test to verify

### CI/CD Failure Response
1. Download failing job logs
2. Extract error signatures and frequency
3. Cross-reference with recent commits in failure window
4. Generate minimal reproduction test
5. Apply fix and re-run pipeline

### Production Incident Response
1. Collect logs from affected services/time window
2. Correlate errors across trace IDs
3. Identify first failing service in cascade
4. Generate hypotheses with environmental factors
5. Propose mitigation (config change, rollback, patch)

## Language-Specific Notes

### Python
- Use `traceback` module formatting; handle exception chains via `__cause__`
- Watch for `NoneType` errors, `KeyError` vs `AttributeError`, `ImportError` nuances
- Memory: `tracemalloc` for leaks, `gc` module for circular references

### JavaScript/TypeScript
- Unhandled promise rejections vs synchronous throws
- `undefined` vs `null` vs missing property distinction
- Async stack trace reconstruction across event loop boundaries

### Java/Kotlin
- Checked vs unchecked exception semantics
- NullPointerException from autounboxing, Optional misuse, or stream operations
- Memory: heap dumps, `jmap`, `jstack` for thread analysis

### Go
- Error wrapping with `%w` and `errors.Is`/`errors.As` chains
- Panic recovery patterns and goroutine leak detection
- Race detector (`-race`) output interpretation

### Rust
- `Result`/`Option` propagation vs `unwrap()` panic sites
- Borrow checker errors and lifetime annotation fixes
- `RUST_BACKTRACE=1` vs `=full` frame resolution

## Resources

- `references/error_catalog.md` — Common error patterns by language/framework
- `references/debug_workflows.md` — Systematic debugging workflows (binary search, divide and conquer, forward/backward tracing)
- `scripts/analyze_error.py` — Stack trace and log parsing utility
