---
name: formal-verification-assistant
description: Lightweight formal verification integration using Z3/SMT, CBMC, Kani, and TLA+ for high-risk refactors and safety-critical modules. Use when blast-radius-calculator scores Risk 9 or higher, when refactoring-engine transforms critical code, or when regulatory compliance requires formal assurance. Integrates bounded model checking and SMT assertion verification into the VALIDATE phase.
---

# Formal Verification Assistant

## Overview

Integrates lightweight formal verification tools into the VALIDATE phase for high-risk refactors and safety-critical modules. Provides bounded verification where unit tests are insufficient — using SMT solvers, bounded model checkers, and protocol specification languages to prove properties about code correctness, safety, and liveness.

## When to Use

- When `blast-radius-calculator` produces **Risk Score >= 9**
- When `refactoring-engine` transforms **safety-critical code (< 500 LOC)**
- When `property-tester-pro` discovers edge cases suggesting deeper invariants
- When code involves **concurrent logic**, **state machines**, or **numerical algorithms**
- When **regulatory compliance** (FDA, DO-178C, ISO 26262, IEC 61508) requires formal assurance
- When traditional unit/integration tests cannot exhaustively cover edge cases due to combinatorial explosion

## Workflow Decision Tree

```
┌─────────────────────────────────────┐
│  Trigger: High-risk refactor or     │
│  safety-critical module detected    │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  Step 1: Identify Target Module     │
│  - Extract < 500 LOC critical slice│
│  - Classify: sequential / concurrent│
│  - Identify invariants from tests   │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  Step 2: Select Verification Tool   │
│  C/C++  → CBMC (bounded model check)│
│  Rust   → Kani                       │
│  Go     → Go212 / GoKart + SMT      │
│  Python → Z3 / PySMT                │
│  Protocol/State Machine → TLA+      │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  Step 3: Encode Properties          │
│  - Function contracts (pre/post)  │
│  - Loop invariants                  │
│  - Safety / liveness assertions   │
│  - Protocol invariants              │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  Step 4: Run Bounded Verification  │
│  - Set loop unwinding bounds        │
│  - Set timeout (default: 300s)      │
│  - Check for counterexamples        │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  Step 5: Integrate with code-tester │
│  - Formal properties → regression   │
│  - Add to CI pipeline               │
│  - Document assumptions/limits      │
└─────────────────────────────────────┘
```

## Core Capabilities

### 1. Risk Score Trigger

Automatic formal verification is triggered when:
- `blast-radius-calculator` Risk Score >= 9
- Module touches memory management, concurrency primitives, cryptographic operations, or numerical stability
- Regulatory context requires formal evidence

**Action:** Immediately invoke the appropriate verifier based on language.

### 2. Bounded Model Checking

For compiled languages, verify properties within bounded execution depths.

| Language | Tool | Typical Use |
|----------|------|-------------|
| C/C++    | CBMC | Buffer bounds, pointer safety, arithmetic overflow |
| Rust     | Kani | Unsafe block verification, panic freedom |
| Go       | Go212 | Channel safety, goroutine leak freedom |

**Loop unwinding bounds:** Default 10 iterations. Increase only if property is expected to depend on deeper unrolling. Document chosen bound in verification report.

### 3. SMT-based Assertions

For Python and dynamic languages, encode function contracts and verify with Z3 via `verify_with_z3.py`.

**Supported property types:**
- Precondition/postcondition pairs
- Integer overflow/underflow checks
- Array/list index bounds
- Algebraic equivalence (refactored vs original)

### 4. TLA+ for Protocols

For distributed protocol invariants:
- Consensus safety (no two nodes commit different values)
- Leader election uniqueness
- State machine liveness (eventually progress)
- Transaction serializability

### 5. Integration with `code-tester`

All formal properties become part of the regression suite:
- Z3 contracts are extracted as runtime assertions in test builds
- CBMC checks run in CI on critical file changes
- TLA+ models are re-checked when protocol logic changes

## Scope Limits

| Constraint | Value | Rationale |
|------------|-------|-----------|
| LOC per verification unit | < 500 | Keeps SMT/MBMC tractable |
| Timeout per proof | 300s | Prevents CI blocking; split if exceeded |
| Loop unwinding default | 10 | Trade-off: coverage vs solver time |
| Larger modules | Modular decomposition | Verify leaf functions first, compose with stubs |

If a module exceeds 500 LOC, decompose into:
1. **Interface verification**: Prove contract compliance at module boundaries
2. **Leaf function verification**: Verify critical internal functions in isolation
3. **Assumption stubs**: Replace unverified sub-modules with non-deterministic stubs capturing their contracts

## Verification Report Template

Every formal verification run produces:

```markdown
## Verification Report: <module_name>

- **Tool**: <CBMC|Kani|Z3|TLA+>
- **Scope**: <file:line-range>
- **LOC**: <N>
- **Timeout**: <seconds>
- **Properties Checked**: <N>
- **Passed**: <N>
- **Failed**: <N>
- **Inconclusive**: <N>

### Properties
| ID | Property | Result | Bound/Assumptions |
|----|----------|--------|-------------------|
| P1 | No buffer overflow on input | PASS | unwinding 10 |

### Counterexamples
<If any failed, include minimized counterexample>

### Assumptions and Limitations
- Loop unwinding bound: 10
- Module X stubbed with contract C
- Floating-point reasoning is approximate
```

## Resources

### scripts/
- `verify_with_z3.py` — Python wrapper for Z3 function contract verification. See script docstring for usage.

### references/
- `tool_guide.md` — Per-tool setup (Z3, CBMC, Kani, TLA+) with installation, compilation flags, and minimal examples
- `property_encoding.md` — Patterns for encoding common properties as SMT/formulas: bounds checking, overflow, memory safety, protocol invariants
