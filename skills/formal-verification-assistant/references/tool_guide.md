# Formal Verification Tool Guide

Quick-start reference for installing, configuring, and running each supported formal verification tool.

---

## Table of Contents

1. [Z3 / PySMT (Python, SMT-based)](#z3--pysmt)
2. [CBMC (C/C++, Bounded Model Checking)](#cbmc)
3. [Kani (Rust, Model Checking)](#kani)
4. [Go212 / GoKart (Go)](#go212)
5. [TLA+ (Protocols, State Machines)](#tla)

---

## Z3 / PySMT

**Best for:** Python function contracts, integer/real arithmetic, array bounds, algebraic equivalence checking.

### Installation

```bash
pip install z3-solver
# Optional higher-level wrapper
pip install pysmt
```

### Minimal Example: Array Bounds Verification

```python
from z3 import Solver, Int, ForAll, Implies, And, sat

def verify_array_bounds():
    solver = Solver()
    n = Int('n')
    i = Int('i')

    # forall i, (0 <= i < n) implies access is safe
    solver.add(ForAll([i], Implies(And(0 <= i, i < n), i >= 0)))
    solver.add(ForAll([i], Implies(And(0 <= i, i < n), i < n)))

    # Check consistency (should be sat)
    if solver.check() == sat:
        print("PASS: Array bounds property is satisfiable/valid")
    else:
        print("FAIL: Property violated")
```

### Verification Script

Use `scripts/verify_with_z3.py` for automated Python contract checking.

### Common Flags / API Patterns

| Task | API / Pattern |
|------|---------------|
| Integer overflow | `And(x >= MIN_INT, x <= MAX_INT)` |
| Division by zero | `y != 0` precondition |
| Array no-overflow | `idx >= 0, idx < len(arr)` |
| Function equivalence | Prove `f(x) == g(x)` for all valid `x` |
| Uninterpreted functions | `Function('f', IntSort(), IntSort())` |

---

## CBMC

**Best for:** C/C++ memory safety, buffer overflows, pointer safety, arithmetic overflow within loop bounds.

### Installation

```bash
# Ubuntu/Debian
sudo apt-get install cbmc

# macOS
brew install cbmc

# From source (latest)
git clone https://github.com/diffblue/cbmc.git
cd cbmc && mkdir build && cd build && cmake .. && make -j4
```

### Minimal Example: Buffer Bounds

```c
// file: check_bounds.c
#include <stdlib.h>

void process(const char *src, size_t len) {
    char buf[64];
    __CPROVER_assert(len < 64, "input fits in buffer");
    for (size_t i = 0; i < len; i++) {
        buf[i] = src[i];
    }
    buf[len] = '\0';
}

int main() {
    size_t len;
    char *src = malloc(len);
    __CPROVER_assume(len < 100);
    process(src, len);
    return 0;
}
```

```bash
cbmc check_bounds.c --bounds-check --pointer-check --unwind 10 --trace
```

### Recommended Flags for Safety-Critical Code

```bash
cbmc <file.c> \
  --bounds-check \
  --pointer-check \
  --div-by-zero-check \
  --signed-overflow-check \
  --unsigned-overflow-check \
  --unwind 10 \
  --unwinding-assertions \
  --timeout 300
```

| Flag | Purpose |
|------|---------|
| `--bounds-check` | Array/pointer out-of-bounds |
| `--pointer-check` | NULL dereference, invalid pointers |
| `--div-by-zero-check` | Division or modulo by zero |
| `--signed-overflow-check` | Signed integer overflow |
| `--unsigned-overflow-check` | Unsigned wrap-around (if undesired) |
| `--unwind N` | Unroll loops N times |
| `--unwinding-assertions` | Assert loop fully unwound (no remaining iterations) |
| `--timeout N` | Abort after N seconds |

### Handling Loops

- Start with `--unwind 10` and `--unwinding-assertions`
- If unwinding assertion fails, increase bound or refactor to bounded loops
- For unbounded loops, provide loop invariants with `__CPROVER_loop_invariant(expr)`

---

## Kani

**Best for:** Rust unsafe code verification, panic freedom, verifying `unsafe` blocks against contracts.

### Installation

```bash
cargo install --locked kani-verifier
cargo kani --setup
```

### Minimal Example: Panic Freedom + Bounds

```rust
// file: verify.rs
#[kani::proof]
fn check_indexing() {
    let idx: usize = kani::any();  // nondet value
    kani::assume(idx < 10);
    let arr = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
    let _ = arr[idx];  // Should never panic given assume
}
```

```bash
cargo kani --harness check_indexing
```

### Recommended Flags

```bash
cargo kani \
  --harness <function_name> \
  --unwind 10 \
  --timeout 300 \
  --enable-unstable \
  --coverage
```

### Kani Idioms

| Goal | Code Pattern |
|------|--------------|
| Nondet value | `let x: T = kani::any();` |
| Assumption | `kani::assume(condition);` |
| Assertion | `kani::assert(condition, "message");` |
| Proof harness | `#[kani::proof]` on test function |
| Unsafe verification | Wrap `unsafe` block, assume raw pointer invariants |

---

## Go212

**Best for:** Go channel safety, goroutine leak detection, select statement coverage.

### Installation

```bash
go install github.com/onsi/ginkgo/v2/ginkgo@latest
go get github.com/onsi/gomega/...
# Go212 is a research prototype; use GoKart + symbolic execution for similar coverage
go install github.com/praetorian-inc/gokart@latest
```

### Alternative: GoKart for Static Analysis + Z3 for Constraints

```bash
gokart scan ./...
```

For bounded verification of Go, the recommended pattern is:
1. Extract critical function to standalone package
2. Write `go test` with rapid/`testing/quick` for property-based fuzzing
3. Use Z3 via `go-smt` (bindings) to verify integer invariants outside fuzz loop

---

## TLA+

**Best for:** Distributed protocols, consensus algorithms, leader election, transaction isolation levels.

### Installation

```bash
# Toolbox (IDE + TLC model checker)
# Download from: https://github.com/tlaplus/tlaplus/releases

# CLI alternative (TLC)
git clone https://github.com/tlaplus/tlaplus.git
cd tlatools && ant jar
```

### Minimal Example: Mutual Exclusion (Two-Process)

```tla
---- MODULE Mutex ----
EXTENDS Naturals, TLC

VARIABLES pc, in_critical

ProcSet == {0, 1}

Init ==
  /\ pc = [i \in ProcSet |-> "ncs"]
  /\ in_critical = FALSE

Enter(i) ==
  /\ pc[i] = "ncs"
  /\ in_critical = FALSE
  /\ pc' = [pc EXCEPT ![i] = "cs"]
  /\ in_critical' = TRUE

Leave(i) ==
  /\ pc[i] = "cs"
  /\ pc' = [pc EXCEPT ![i] = "ncs"]
  /\ in_critical' = FALSE

Next == \E i \in ProcSet : Enter(i) \/ Leave(i)

Safety == \A i, j \in ProcSet : (pc[i] = "cs" /\ pc[j] = "cs") => i = j

====
```

### Model Checking Command

```bash
java -cp tla2tools.jar tlc2.TLC Mutex.tla -config Mutex.cfg
```

### TLA+ Property Patterns

| Property | Formula Pattern |
|----------|-----------------|
| Mutual exclusion | `\A i, j : (pc[i] = "cs" /\ pc[j] = "cs") => i = j` |
| Liveness | `\A i : pc[i] = "try" ~> pc[i] = "cs"` |
| Agreement | `\A i, j : decided[i] /\ decided[j] => value[i] = value[j]` |
| Bounded retry | `\A i : retry_count[i] < MaxRetry` |

### Tips for Protocol Verification

- Start with small models (2 processes, small data sets)
- Use ` symmetry` reduction when processes are identical
- Use `VIEW` to collapse equivalent states and reduce state space
- Check both `Safety` and `Liveness` properties
- Add `TypeOK` invariant to catch type-level bugs early

---

## Tool Selection Quick Reference

| Language / Domain | Primary Tool | Secondary Tool |
|-------------------|--------------|----------------|
| Python (numeric, algorithms) | Z3 / PySMT | - |
| C/C++ (embedded, kernels) | CBMC | Frama-C / WP |
| Rust (unsafe, panic-free) | Kani | Miri (dynamic) |
| Go (concurrency) | GoKart + Z3 | Static analysis |
| Distributed protocols | TLA+ | Ivy / Verdi |
| Numerical algorithms | Z3 (real arithmetic) | CBMC (C) / Kani (Rust) |
