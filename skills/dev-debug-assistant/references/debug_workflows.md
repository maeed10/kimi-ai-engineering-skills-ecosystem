# Debug Workflows

Systematic debugging methodologies for isolating root causes efficiently. Choose the workflow that matches the failure pattern, available information, and system complexity.

---

## 1. Binary Search Debugging (Git Bisect Method)

Best for: **Regressions** — known good state in the past, broken now.

**Principle**: Narrow the failure window by testing the midpoint between known good and known bad commits.

**Steps**:
1. Identify `GOOD` commit (last known working) and `BAD` commit (current broken)
2. Check out midpoint: `git bisect start && git bisect bad && git bisect good <commit>`
3. Run reproduction test
4. Mark result: `git bisect good` or `git bisect bad`
5. Repeat until 1 commit remains — the regression introducer
6. Inspect that commit's changes for the root cause

**Tips**:
- Automate with `git bisect run <script>` if reproduction is scriptable
- If test is flaky, run multiple times per commit or use a more deterministic proxy test
- For large jumps, manually inspect midpoint if build is broken (skip with `git bisect skip`)

---

## 2. Divide and Conquer (Module Isolation)

Best for: **Complex systems** — unclear which layer or component is at fault.

**Principle**: Split the system in half, determine which half contains the bug, repeat.

**Steps**:
1. Draw boundary diagram of the system (input → [A] → [B] → [C] → output)
2. Test at the midpoint: inject known-good input directly into component B
3. If B produces bad output, bug is in B or earlier; if good, bug is in C or later
4. Repeat within the faulty half
5. Once component isolated, apply smaller-scope debugging workflow

**Techniques**:
- **Mock/stub downstream**: Test component in isolation with fixed inputs
- **Replay production traffic**: Capture and replay requests to local component
- **Feature flags**: Disable half the features to isolate offending change
- **Comment-out blocks**: Temporarily remove code paths (not for production)

---

## 3. Forward Tracing (Follow the Data)

Best for: **State corruption** — correct input produces wrong output.

**Principle**: Track a suspect value from its origin through every transformation until it becomes incorrect.

**Steps**:
1. Identify the first point where data is known to be correct (e.g., API request body, file read)
2. Log or breakpoint after each transformation: parsing, validation, mapping, computation
3. At each step, assert expected vs. actual value
4. The step where actual diverges from expected is the corruption point
5. Inspect that function's logic, side effects, and dependencies

**Tools**:
- Debugger watchpoints on variable mutation
- Structured logging with `trace_id` + variable snapshots
- `git blame` on the corrupting function to see recent changes
- Unit tests with parameterized inputs to isolate boundary

---

## 4. Backward Tracing (Follow the Error)

Best for: **Crashes and exceptions** — stack trace available, need origin.

**Principle**: Start from the exception site and walk backward through the call chain to find where bad state originated.

**Steps**:
1. Read bottom of stack trace (or top, depending on language convention) for exception site
2. Identify the immediate cause (e.g., `NullPointerException` at line 42)
3. Ask: "What value was null and why?"
4. Walk up stack frames to find where that value was assigned or passed
5. Continue until you find the source of invalid data or the violated invariant
6. Fix at the source, not just the symptom

**Key Questions**:
- Which function should have validated this input?
- What invariant was supposed to hold here?
- What changed recently in this call chain?
- Is this error a symptom of an earlier failure (check `caused by` chains)?

---

## 5. Hypothesis-Driven Debugging

Best for: **Novel failures** — no obvious pattern, need structured investigation.

**Principle**: Generate ranked hypotheses, design experiments to falsify them, update confidence.

**Steps**:
1. **Observe**: Collect error message, stack trace, logs, metrics, recent changes
2. **Hypothesize**: Brainstorm 3-5 independent causes with rough confidence (e.g., config bug 60%, race condition 30%, dependency change 25%)
3. **Prioritize**: Sort by confidence × ease of validation. Attack the easiest high-confidence hypothesis first.
4. **Experiment**: Design a minimal test or inspection that would disprove the hypothesis
5. **Evaluate**: If falsified, eliminate and move to next. If supported but not proven, increase confidence and gather more evidence.
6. **Converge**: When one hypothesis survives all experiments and explains all observations, treat as root cause.
7. **Fix and verify**: Apply fix, ensure reproduction now passes, monitor for regression.

**Anti-patterns**:
- Don't fall in love with your first hypothesis
- Don't change multiple things at once (invalidates experiment)
- Don't skip verification — "seems fixed" is not fixed

---

## 6. Temporal Debugging (Time-Based Correlation)

Best for: **Intermittent / environmental failures** — timing, load, or external state dependent.

**Principle**: Correlate failure times with system events, deployments, or external triggers.

**Steps**:
1. Plot failure frequency over time (histogram of error timestamps)
2. Mark events on timeline: deployments, config changes, traffic spikes, dependency releases
3. Look for step changes or spikes aligned with events
4. If correlated with deployment, use Binary Search Debugging on commits
5. If correlated with traffic, investigate resource limits, race conditions, or caching
6. If no correlation, investigate external dependencies (upstream APIs, DNS, certificates)

**Tools**:
- `git log --since=<date>` for changes in failure window
- Metrics dashboards overlaid with deployment markers
- Log aggregation with time-window correlation

---

## 7. Memory Debugging Workflow

Best for: **Memory leaks, OOMs, high heap usage**.

**Steps**:
1. **Confirm leak**: Observe memory growth over multiple load cycles; ensure GC is running (`jstat`, `gc_stats`)
2. **Capture heap/profile**:
   - JVM: `jmap -dump:format=b,file=heap.hprof <pid>`
   - Python: `tracemalloc.start()` + `tracemalloc.take_snapshot()`
   - Go: `pprof` heap profile at intervals
   - Node: `--heapsnapshot-near-heap-limit`
3. **Diff profiles**: Compare heap snapshots between baseline and growth state
4. **Identify retainers**: Find dominator tree — which object types grew and what holds references to them
5. **Trace allocation site**: Map retaining objects to allocation stack traces
6. **Fix pattern**: Missing `close()` / `dispose()`; cache without eviction; listener not deregistered; large object retained in closure
7. **Verify**: Re-run with fix, confirm memory flatlines after GC

---

## 8. Concurrency Debugging Workflow

Best for: **Race conditions, deadlocks, thread starvation**.

**Steps**:
1. **Reproduce**: Run under load; use stress testing (`stress`, `locust`, custom loops)
2. **Detect**:
   - Java: `-Djdk.includeInExceptions=true` for detailed NPE; use `jstack` thread dump
   - Go: `-race` detector (runtime overhead, run in CI)
   - Rust: `ThreadSanitizer` via `RUSTFLAGS="-Z sanitizer=thread"`
   - C/C++: ThreadSanitizer, AddressSanitizer
3. **Capture state**:
   - Thread dump: all threads with stack traces and lock monitors
   - Lock graph: which threads hold which locks and wait on which others
4. **Identify pattern**:
   - **Race**: Two threads access shared state, at least one writes, no synchronization
   - **Deadlock**: Circular lock dependency (A waits for B, B waits for A)
   - **Livelock**: Threads keep changing state in response to each other without progress
   - **Starvation**: One thread never acquires resource due to unfair scheduling
5. **Fix**:
   - Race: Atomic operations, mutex, or channel-based ownership
   - Deadlock: Consistent lock ordering, lock timeouts, avoid nested locks
   - Starvation: Fair semaphores, back off and retry with jitter
6. **Verify**: Run detector clean under 10x normal load for sustained period

---

## 9. Log-Based Triage (CI/CD & Production)

Best for: **Large log volumes, multiple services, unclear primary failure**.

**Steps**:
1. **Collect**: Gather logs from all services in failure window (±5 min of first error)
2. **Filter severity**: Start with ERROR, FATAL, PANIC — ignore INFO unless context needed
3. **Extract signatures**: Group identical/similar messages; count frequency
4. **Find first failure**: Sort by timestamp; the earliest unique error is often the trigger
5. **Trace causality**: Follow `trace_id` / `request_id` through service hops
6. **Correlate**: Match error spike with deployment events, config changes, or traffic patterns
7. **Summarize**: One-line root cause + affected services + user impact
8. **Escalate/Fix**: Assign to owning service; apply fix pattern from Error Catalog

**Log Query Patterns**:
```
# First error in window
{service="*"} |~ "(?i)error|exception|fatal|panic" 
  | line_format "{{.timestamp}} {{.service}} {{.message}}"
  | sort by timestamp asc
  | limit 20

# Error frequency by signature
{service="frontend"} |~ "ERROR" 
  | pattern `<_> <level> <message>` 
  | group by message
  | count()
```

---

## 10. Minimal Reproduction Workflow

Best for: **Complex bugs that only appear in full environment** — need to isolate for debugging.

**Steps**:
1. **Preserve state**: Save exact input, database state, config, and environment variables
2. **Strip dependencies**: Replace external services with mocks/stubs that return recorded responses
3. **Reduce data**: Use smallest dataset that triggers bug (binary search on input size)
4. **Reduce code**: Comment out code paths that don't affect reproduction
5. **Containerize**: Capture environment in Dockerfile so reproduction is portable
6. **Automate**: Create script that runs from clean state to failure in one command
7. **Validate**: Confirm reproduction on another machine; this is your regression test

**Benefits**:
- Faster iteration (seconds vs. minutes to reproduce)
- Enables `git bisect run`
- Becomes regression test after fix
- Allows handing off to another developer

---

## Workflow Selection Guide

| Failure Pattern | Recommended Workflow | Secondary |
|-----------------|----------------------|-----------|
| Worked yesterday, broken today | Binary Search Debugging | Temporal Debugging |
| Correct input, wrong output | Forward Tracing | Divide and Conquer |
| Crash with stack trace | Backward Tracing | Hypothesis-Driven |
| Intermittent / load-dependent | Concurrency Debugging | Temporal Debugging |
| Memory grows until crash | Memory Debugging | Forward Tracing |
| CI fails, logs noisy | Log-Based Triage | Binary Search Debugging |
| Novel, no obvious cause | Hypothesis-Driven | Backward Tracing |
| Only reproduces in production | Minimal Reproduction | Temporal Debugging |
