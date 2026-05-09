---
name: property-tester-pro
description: Property-based testing integration skill that augments code-tester with generative testing using Hypothesis, fast-check, and proptest. Use when testing algorithms, parsers, state machines, or numerical code; when coverage targets are met but edge-case confidence is low; or during VALIDATE for safety-critical modules. Discovers invariant violations via random input generation and auto-adds minimized counterexamples as regression tests.
---

# Property Tester Pro

## Overview

Augment standard unit tests with property-based testing (PBT) to discover edge-case failures, invariant violations, and specification gaps that example-based tests miss. Integrates with `code-tester` during TEST and VALIDATE phases.

## Workflow Decision Tree

```
START: code-tester generates/validates test suite
  |
  +---> Target contains algorithm / parser / state machine / numerical code?
  |       YES --> Run PBT workflow
  |       NO  --> Skip PBT (monitor only)
  |
  +---> blast-radius-calculator flagged HIGH-RISK algorithmic module?
  |       YES --> Mandate stateful PBT + invariant suite
  |       NO  --> Standard PBT with 2-4 invariants
  |
  +---> VALIDATE phase for safety-critical code?
          YES --> Full PBT + coverage synergy + auto-regression
```

## Core Workflow

### 1. Invariant Inference

After reading the code under test, generate 2-4 invariant assertions that should hold for all inputs:

- **Round-trip**: `encode(decode(x)) == x`
- **Idempotence**: `f(f(x)) == f(x)`
- **Monoid/Associative**: `op(a, op(b, c)) == op(op(a, b), c)`
- **Ordering**: `sorted(xs) == sorted(sorted(xs))` and length preservation
- **Non-negativity**: `len(x) >= 0`, `distance >= 0`
- **State machine**: `action_sequence` leaves system in valid state

Use the reference `invariant_patterns.md` for domain-specific templates.

### 2. Language-Specific Backend Selection

| Language | Framework | Install | Key Module |
|----------|-----------|---------|------------|
| Python | Hypothesis | `pip install hypothesis` | `hypothesis`, `hypothesis.stateful` |
| JavaScript/TypeScript | fast-check | `npm install fast-check` | `fast-check`, `@fast-check/vitest` |
| Rust | proptest | `cargo add proptest` | `proptest::prelude::*`, `proptest_state_machine` |
| Go | gopter | `go get github.com/leanovate/gopter` | `gopter`, `gopter/prop`, `gopter/gen` |
| Java | jqwik | Maven/Gradle dependency | `net.jqwik.api.*` |
| C# | FsCheck.xUnit | NuGet | `FsCheck`, `FsCheck.Xunit` |

Load `references/pbt_backends.md` for framework setup, patterns, and full examples.

### 3. Test Generation Pattern

For each function under test:

1. **Read signatures**: extract parameter types, return type, side effects
2. **Select strategy**: `hypothesis.strategies`, `fc.*`, `any_*` macros
3. **Write property**: `@given` / `fc.property` / `proptest!` wrapping the invariant
4. **Run & shrink**: execute; on failure, framework auto-minimizes counterexample
5. **Auto-regress**: add minimized counterexample as `@example` / `examples:` / explicit unit test

### 4. Stateful PBT for State Machines

When the code under test is a state machine (database, cache, protocol handler, parser state):

**Python (Hypothesis RuleBasedStateMachine)**:
```python
class MyStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.state = MySystem()

    @rule(item=st.integers())
    def add_item(self, item):
        self.state.add(item)

    @invariant()
    def size_non_negative(self):
        assert self.state.size() >= 0

TestMyStateMachine = MyStateMachine.TestCase
```

**JavaScript (fast-check model-based)**:
```javascript
const modelBased = fc.modelRun(
  () => ({ real: new MySystem(), model: { size: 0 } }),
  [
    fc.command({ run: (r, m) => { r.add(1); m.size++; } }),
    fc.command({ run: (r, m) => assert.equal(r.size(), m.size); }),
  ]
);
```

**Rust (proptest_state_machine)**:
```rust
proptest_state_machine!([
    #[derive(Debug, Default, Clone)]
    struct MyState { items: Vec<u32> }
    // define transitions, invariants
]);
```

### 5. Coverage Synergy

Property tests run alongside unit tests in the same CI step. Requirements:

- Coverage report aggregates both: `--cov` (pytest) or `c8` (Node) captures PBT execution paths
- Output summary: `Properties passed: N | Edge cases discovered: K | Regression tests added: K`
- If PBT discovers a new code path not hit by unit tests, flag for unit test augmentation

### 6. Auto-Regression

When a counterexample is found and minimized:

1. Extract the minimized input tuple
2. Add as an explicit regression test with a comment: `# Regression: found by Hypothesis, GitHub-123`
3. For Python: add `@example(...)` decorator to the property
4. For Rust: add a `test_regression_N` unit test
5. For JS: add a `it('regression: ...')` block

### 7. Report Format

After PBT execution, produce:

```markdown
## Property-Based Testing Report

| Property | Status | Examples Run | Edge Cases Found |
|----------|--------|--------------|------------------|
| roundtrip_encode_decode | PASS | 200 | 3 (NaN, empty, unicode) |
| sort_idempotent | PASS | 200 | 0 |
| add_commutative | FAIL | 47 | 1 (overflow: MAX_INT + 1) |

### Counterexamples Added as Regression Tests
- `test_regression_add_overflow_max_int` in `test_math.py:89`

### Coverage Impact
- Lines covered before PBT: 142/200 (71%)
- Lines covered after PBT: 187/200 (93.5%)
- New paths discovered: 12
```

## Integration Points

| Skill / Phase | Integration |
|---------------|-------------|
| `code-tester` | PBT runs after unit test generation; invariants augment test file |
| `blast-radius-calculator` | HIGH-RISK algorithmic modules trigger mandatory stateful PBT |
| VALIDATE phase | Full PBT suite executed; report appended to validation output |
| `code-reviewer` | Invariants serve as executable specification for review |

## Resources

- `references/pbt_backends.md` — Per-language framework setup, strategies, examples
- `references/invariant_patterns.md` — Domain-specific invariant templates
