# Property Encoding Patterns

Reference guide for translating common safety and correctness properties into formal logic for SMT solvers (Z3), bounded model checkers (CBMC, Kani), and protocol specification languages (TLA+).

---

## Table of Contents

1. [Function Contracts](#function-contracts)
2. [Bounds and Overflow Checking](#bounds-and-overflow)
3. [Memory and Pointer Safety](#memory-safety)
4. [Concurrency and Locking](#concurrency)
5. [State Machine Invariants](#state-machine)
6. [Algebraic Equivalence (Refactor Verification)](#equivalence)
7. [Numerical Algorithm Properties](#numerical)
8. [Protocol Invariants](#protocol)

---

## Function Contracts

### Precondition / Postcondition in Z3 (Python)

```python
from z3 import *

def verify_contract(f_impl, pre, post, domain_sort):
    """
    Prove: forall x, pre(x) implies post(f_impl(x), x)
    """
    x = Const('x', domain_sort)
    solver = Solver()
    # Negate: exists x where pre holds and post fails
    solver.add(pre(x))
    solver.add(Not(post(f_impl(x), x)))
    if solver.check() == unsat:
        print("PASS: Contract holds")
        return True
    else:
        print("FAIL: Counterexample found")
        print(solver.model())
        return False
```

### Precondition / Postcondition in CBMC (C)

```c
int add_sat(int a, int b)
  __CPROVER_requires(a >= 0 && b >= 0)
  __CPROVER_ensures(__CPROVER_return_value >= a && __CPROVER_return_value >= b)
{
    return a + b;
}
```

**Note:** `__CPROVER_requires` and `__CPROVER_ensures` are CBMC extensions. If unavailable, inline them:

```c
int add_sat(int a, int b) {
    __CPROVER_assert(a >= 0 && b >= 0, "precondition");
    int r = a + b;
    __CPROVER_assert(r >= a && r >= b, "postcondition");
    return r;
}
```

### Precondition / Postcondition in Kani (Rust)

```rust
#[kani::proof]
fn check_add_sat() {
    let a: i32 = kani::any();
    let b: i32 = kani::any();
    kani::assume(a >= 0 && b >= 0);
    let r = a.saturating_add(b);
    kani::assert(r >= a && r >= b, "postcondition");
}
```

---

## Bounds and Overflow

### Integer Overflow Prevention

**Python + Z3:**
```python
from z3 import *

x, y = Ints('x y')
MAX = 2**31 - 1
MIN = -2**31

# Property: x + y does not overflow 32-bit signed
no_overflow = And(x + y <= MAX, x + y >= MIN)
# Typically combined with assume on inputs
```

**CBMC (C):**
```c
__CPROVER_assert(a <= INT_MAX - b, "no signed overflow on add");
```

**Kani (Rust):**
```rust
let a: i32 = kani::any();
let b: i32 = kani::any();
kani::assume(a > 0 && b > 0 && a <= i32::MAX - b);
let r = a + b;
kani::assert(r > 0, "no overflow");
```

### Array / Buffer Bounds

**Python + Z3 (list with symbolic length):**
```python
from z3 import *

n, i = Ints('n i')
# Precondition: i is a valid index into length-n list
valid_index = And(i >= 0, i < n)
# Safety: accessing list[i] is safe
```

**CBMC (C):**
```c
char buf[64];
__CPROVER_assert(n < 64, "buffer size");
for (size_t i = 0; i < n; i++) {
    buf[i] = input[i];  // automatic bounds check with --bounds-check
}
```

---

## Memory and Pointer Safety

### Null Pointer Dereference

**CBMC (C):**
```c
void process_node(Node* n) {
    __CPROVER_assert(n != NULL, "non-null pointer");
    n->value = 0;
}
```

**Kani (Rust):**
```rust
fn process_node(n: Option<&mut Node>) {
    let node = n.unwrap();  // panic if None; Kani catches this
    node.value = 0;
}

#[kani::proof]
fn check_process_node() {
    let mut node = Node { value: 0 };
    process_node(Some(&mut node));
}
```

### Buffer Overrun on Heap

**CBMC (C):**
```c
void copy_data(char* dst, size_t dst_len, char* src, size_t src_len) {
    __CPROVER_assert(src_len <= dst_len, "no overflow");
    for (size_t i = 0; i < src_len; i++) {
        dst[i] = src[i];
    }
}
```

---

## Concurrency and Locking

### Deadlock Freedom (simplified two-lock)

**TLA+:**
```tla
\* No process holds lock A while waiting for B, and vice versa
DeadlockFree ==
  ~\E i, j \in ProcSet :
    /\ i /= j
    /\ holds[i] = "A" /\ waits_for[i] = "B"
    /\ holds[j] = "B" /\ waits_for[j] = "A"
```

**Kani (Rust) — check panic freedom in lock order:**
```rust
use std::sync::Mutex;

static A: Mutex<i32> = Mutex::new(0);
static B: Mutex<i32> = Mutex::new(0);

#[kani::proof]
fn check_lock_order() {
    let _a = A.lock().unwrap();
    let _b = B.lock().unwrap();  // Kani checks if this can panic/ deadlock
}
```

### Data Race Freedom

For C/C++, rely on **CBMC** with `--atomicity-check` or verify that all shared accesses are protected:

```c
__CPROVER_assert(lock_held_by_current_thread(), "data race guard");
shared_var = value;
```

For Rust, the borrow checker provides most guarantees; use **Kani** for `unsafe` code that bypasses it.

---

## State Machine Invariants

### State Validity

**Z3 (Python):**
```python
from z3 import EnumSort, Const, And, Or, Solver

State, states = EnumSort('State', ['Idle', 'Running', 'Error', 'Done'])
s = Const('s', State)

# Invariant: valid transition target
valid = Or(s == states[0], s == states[1], s == states[2], s == states[3])
```

**TLA+:**
```tla
TypeOK ==
  /\ state \in {"Idle", "Running", "Error", "Done"}
  /\ (state = "Running" => timer > 0)
```

### State Transition Validity

**TLA+:**
```tla
Next ==
  /\ state = "Idle"    => state' \in {"Running", "Done"}
  /\ state = "Running" => state' \in {"Running", "Error", "Done"}
  /\ state = "Error"   => state' = "Error"
  /\ state = "Done"    => state' = "Done"
```

---

## Algebraic Equivalence (Refactor Verification)

When `refactoring-engine` transforms code, prove the new implementation is equivalent to the old for all valid inputs.

### Z3 Equivalence Pattern

```python
from z3 import *

def prove_equivalence(f_old, f_new, pre, domain):
    """
    Prove forall x in domain: pre(x) => f_old(x) == f_new(x)
    """
    x = Const('x', domain)
    solver = Solver()
    solver.add(pre(x))
    solver.add(f_old(x) != f_new(x))
    return solver.check() == unsat
```

### Example: Refactored Sorting

```python
from z3 import *

Arr = ArraySort(IntSort(), IntSort())
a, b = Consts('a b', Arr)
n = Int('n')

# Precondition: inputs are length-n arrays
pre = And(n >= 0, n <= 10)

# Old and new implementations as uninterpreted functions for spec-level check
old_sort = Function('old_sort', Arr, IntSort(), Arr)
new_sort = Function('new_sort', Arr, IntSort(), Arr)

# Equivalence: same output for all inputs
solver = Solver()
solver.add(And(n >= 0, n <= 10))
solver.add(ForAll([a, n], old_sort(a, n) != new_sort(a, n)))
# Expect unsat if implementations are equivalent
```

For concrete function equivalence in CBMC/Kani, run both implementations on the same nondet input and assert outputs match.

---

## Numerical Algorithm Properties

### Monotonicity

```python
from z3 import *

x1, x2 = Reals('x1 x2')
f = Function('f', RealSort(), RealSort())

# f is monotonic increasing
monotonic = ForAll([x1, x2], Implies(x1 <= x2, f(x1) <= f(x2)))
```

### Fixed-Point Convergence

**TLA+ (iterative algorithm):**
```tla
Converged == abs(prev - curr) < epsilon
Termination == <>(Converged)
```

**CBMC (C loop):**
```c
float prev, curr;
unsigned iter = 0;
do {
    __CPROVER_loop_invariant(iter <= MAX_ITER);
    __CPROVER_loop_invariant(isfinite(prev) && isfinite(curr));
    prev = curr;
    curr = iterate(prev);
    iter++;
} while (fabs(curr - prev) >= EPSILON && iter < MAX_ITER);
__CPROVER_assert(iter < MAX_ITER, "converges within bound");
```

---

## Protocol Invariants

### Consensus Safety

**TLA+:**
```tla
\* No two correct nodes decide different values
Safety ==
  \A n1, n2 \in CorrectNodes :
    decided[n1] /\ decided[n2] => value[n1] = value[n2]
```

### Leader Election Uniqueness

**TLA+:**
```tla
\* At most one leader per term
LeaderUniqueness ==
  \A n1, n2 \in Nodes :
    /\ leader[n1] /\ leader[n2]
    /\ term[n1] = term[n2]
    => n1 = n2
```

### Request-Response Matching

**Z3 (message protocol):**
```python
from z3 import *

Msg = Datatype('Msg')
Msg.declare('req', ('id', IntSort()), ('payload', IntSort()))
Msg.declare('resp', ('id', IntSort()), ('payload', IntSort()))
Msg = Msg.create()

m1, m2 = Consts('m1 m2', Msg)
# Every response has a matching prior request
matching = ForAll([m2],
    Implies(Msg.is_resp(m2),
            Exists([m1],
                And(Msg.is_req(m1),
                    Msg.id(m1) == Msg.id(m2)))))
```

---

## Encoding Checklist

Before submitting a property to the solver:

- [ ] Identify all **input variables** and their types
- [ ] Write **preconditions** (assumptions) that bound inputs to realistic values
- [ ] State the **property** as a logical formula over inputs/outputs/state
- [ ] Check for **quantifier alternations** — minimize `ForAll(Exists(...))` patterns for SMT
- [ ] For loops: pick **unwinding bound** and add unwinding assertion
- [ ] For protocols: start with **small model** (2-3 processes, small data)
- [ ] Document **approximations** (floating-point as real, timeouts, stubs)
