# Design Heuristics Reference (v4.0 — Deterministic)

Comprehensive catalog of design heuristics, SOLID principles, and common code smells for the self-reviewer skill. All structural checks are backed by deterministic AST metrics from `ast-analyzer.py`. Use this as a decision-support reference when evaluating agent-generated code.

---

## 0. Determinism Policy

Every structural claim in this document maps to an AST metric that `ast-analyzer.py` computes deterministically:

| Metric | AST Computation | Reproducible |
|--------|-----------------|--------------|
| `cyclomatic_complexity` | Count of `If`, `For`, `While`, `ExceptHandler`, `BoolOp`, `comprehension` nodes | Yes |
| `function_length_lines` | `end_lineno - lineno - docstring_lines` | Yes |
| `class_length_lines` | `end_lineno - lineno` | Yes |
| `class_method_count` | Count of `FunctionDef` / `AsyncFunctionDef` in `ClassDef.body` | Yes |
| `interface_method_count` | Same as class method count, filtered for interface-ish classes | Yes |
| `type_switch_chain_length` | Count of contiguous `If` / `elif` nodes with `isinstance` or `type()` tests | Yes |
| `override_signature_change` | Compare `args.args`, `args.posonlyargs`, `args.kwonlyargs`, `vararg`, `kwarg` | Yes |
| `interface_mixed_concerns` | Count of distinct `_`-delimited prefixes in method names | Yes |
| `direct_concrete_instantiation` | Count of `Call` nodes where `func` is a `Name` starting uppercase | Yes |
| `imports_per_file` | Count of `Import` and `ImportFrom` nodes | Yes |
| `cross_domain_import` | `ImportFrom` where module path matches low-level indicator | Yes |
| `circular_import` | Bidirectional `ImportFrom` matches between two files | Yes |
| `duplicate_ast_subtree_lines` | Normalized structural hash (`_ASTHasher`) collision across files | Yes |

**Rule**: The LLM may interpret, explain, and suggest fixes. It may NOT invent metric values. All metric values come from the AST engine.

---

## 1. SOLID Principles

### 1.1 Single Responsibility Principle (SRP)

**Rule**: A class or module should have only one reason to change.

**Detection heuristics** (AST-derived):
- `class_method_count` > 10
- `class_length_lines` > 500
- Methods operate on disjoint sets of instance variables (future enhancement)
- Class name contains conjunctions: `And`, `With`, `Plus` (e.g., `UserAndOrderManager`) — text heuristic, low weight
- Class imports from > 3 unrelated domains — `imports_per_file` auxiliary

**AST metric**: `class_method_count`, `class_length_lines`

**Thresholds**: method count = 10; class length = 500 lines

**Fix strategies**:
- Extract classes by responsibility
- Move methods that touch disjoint data to separate classes
- Apply "feature envy" refactoring: method belongs where its data lives

**Uncertainty note**: Low for metric (count is objective). Medium for interpretation (cohesion is subjective). A utility class with many static methods may legitimately have broad scope.

---

### 1.2 Open/Closed Principle (OCP)

**Rule**: Modules should be open for extension, closed for modification.

**Detection heuristics** (AST-derived):
- `type_switch_chain_length` >= 2: contiguous `if/elif/elif` chains using `isinstance(...)` or `type(x) == ...`
- Modification of stable base class to add new variant (detected via git diff, not AST alone)
- New feature requires editing existing, well-tested files (detected via git diff)

**AST metric**: `type_switch_chain_length`

**Threshold**: 2 branches (i.e., at least one `if` + one `elif` both switching on type)

**Fix strategies**:
- Replace conditionals with polymorphism (Strategy pattern)
- Introduce abstraction (protocol/interface) for variation points
- Use dependency injection to wire variants externally

**Uncertainty note**: Low for detection (isinstance chains are unambiguous). Medium for interpretation — not all change is OCP violation; stable code that rarely changes does not need speculative abstraction.

---

### 1.3 Liskov Substitution Principle (LSP)

**Rule**: Subtypes must be substitutable for their base types without altering correctness.

**Detection heuristics** (AST-derived):
- `override_signature_change`: subclass method has different positional arg count, kw-only count, or `*args/**kwargs` presence compared to base method found in the same file
- Subclass weakens preconditions (accepts inputs base rejects) — future enhancement via type annotation comparison
- Subclass strengthens postconditions (returns narrower type) — future enhancement via return annotation comparison
- `isinstance` checks that special-case a subtype — auxiliary heuristic

**AST metric**: `override_signature_change`

**Threshold**: any mismatch (binary: 0 = pass, 1 = fail)

**Fix strategies**:
- Redesign inheritance hierarchy; favor composition over inheritance
- Extract shared behavior into mixin or utility
- Make base type more general or subtype more restrictive to match contract

**Uncertainty note**: Low. Signature mismatch is objectively detectable via AST comparison.

---

### 1.4 Interface Segregation Principle (ISP)

**Rule**: Clients should not be forced to depend on methods they do not use.

**Detection heuristics** (AST-derived):
- `interface_method_count` > 5 for interface-ish classes (ABC base, Protocol base, or all methods trivial: `pass` / `...` / `raise NotImplementedError`)
- `interface_mixed_concerns` > 2 distinct `_`-delimited naming prefixes among method names
- Client class implements interface but leaves methods as `pass` / `raise NotImplementedError` — auxiliary

**AST metrics**: `interface_method_count`, `interface_mixed_concerns`

**Thresholds**: method count = 5; mixed concerns = 2 prefixes

**Fix strategies**:
- Split fat interface into role-specific interfaces
- Use composition to assemble roles instead of single large inheritance

**Uncertainty note**: Low for counts. Medium for interpretation — threshold depends on domain; 10 methods may be fine for a data-access interface.

---

### 1.5 Dependency Inversion Principle (DIP)

**Rule**: High-level modules should not depend on low-level modules; both should depend on abstractions.

**Detection heuristics** (AST-derived):
- `direct_concrete_instantiation`: `Call` node where `func` is a `Name` starting with uppercase (indicating a class) in a high-level file path
- `direct_concrete_instantiation_count` > 3 per file (even if not high-level, excessive concrete coupling)
- Business-logic class imports concrete infrastructure (DB driver, HTTP client) — `cross_domain_import`
- Module in `domain/` imports from `infrastructure/` — `cross_domain_import`

**AST metrics**: `direct_concrete_instantiation`, `direct_concrete_instantiation_count`, `cross_domain_import`

**Thresholds**: any instantiation in high-level path; count = 3 per file

**Fix strategies**:
- Introduce port/interface in domain layer
- Implement adapter in infrastructure layer
- Use dependency injection container or factory at composition root

**Uncertainty note**: Low for concrete instantiation counts. Medium for domain classification (path-based heuristics).

---

## 2. Complexity Heuristics

### 2.1 Cyclomatic Complexity

**Threshold**: 10 per function (McCabe); flag at > 15; block at > 20.

**Rationale**: Complexity correlates with defect density. Testing requires covering all paths.

**Detection**: AST-based count of branching nodes: `If`, `For`, `While`, `ExceptHandler`, `BoolOp` (n-1 per operator), `comprehension` (1 + len(ifs)).

**AST metric**: `cyclomatic_complexity`

**Reproducibility**: Deterministic — same AST always yields same count.

**Fix strategies**:
- Extract helper functions for branches
- Replace nested conditionals with lookup tables or polymorphism
- Use guard clauses to flatten nesting

---

### 2.2 Cognitive Complexity

**Threshold**: 15 per function.

**Rationale**: Measures how hard code is to understand, not just test. Nesting increments multiplicatively.

**Detection**: Approximated by `nesting_depth` + `cyclomatic_complexity` composite (future metric). Currently use `nesting_depth` as proxy.

**AST metric**: `nesting_depth` (proxy)

**Fix strategies**:
- Same as cyclomatic complexity, but prioritize readability over testability
- Break nested logic into named steps

---

### 2.3 Function Length

**Threshold**: 50 lines (warning); 100 lines (critical).

**Rationale**: Long functions hide bugs and resist refactoring.

**Detection**: `end_lineno - lineno - docstring_lines` from AST.

**AST metric**: `function_length_lines`

**Fix strategies**:
- Extract cohesive blocks into named helpers
- Apply "extract till you drop": continue extracting until each function does one visible thing

---

### 2.4 Nesting Depth

**Threshold**: 4 levels (warning); 6 levels (critical).

**Rationale**: Deep nesting is hard to trace and often indicates missing abstraction.

**Detection**: Maximum depth of `If`, `For`, `While`, `With`, `Try`, `comprehension` nodes inside a function body via AST walk.

**AST metric**: `nesting_depth`

**Fix strategies**:
- Early returns / guard clauses
- Extract nested loops/conditionals into helper functions
- Use functional operations (map, filter, reduce) to flatten iteration

---

### 2.5 Class Length

**Threshold**: 300 lines (warning); 500 lines (critical).

**Rationale**: Large classes accumulate responsibilities and become change hotspots.

**Detection**: `end_lineno - lineno` from `ClassDef` AST node.

**AST metric**: `class_length_lines`

**Fix strategies**:
- Extract classes by behavior clusters
- Move stateless utility methods to module-level functions

---

## 3. Coupling & Cohesion

### 3.1 Afferent / Efferent Coupling

**Rule**: A module with high afferent (many depend on it) should have low efferent (it depends on few). Stable dependencies principle.

**Detection** (AST-derived):
- `imports_per_file` count from `Import` + `ImportFrom` nodes
- Circular imports between packages via bidirectional `ImportFrom` matching
- Domain-layer module imports infrastructure-layer module via `cross_domain_import`

**AST metrics**: `imports_per_file`, `circular_import`, `cross_domain_import`

**Fix strategies**:
- Introduce mediator or facade to break cycles
- Move shared types to a neutral `common/` or `types/` package
- Apply dependency inversion to decouple layers

---

### 3.2 Feature Envy

**Rule**: A method that uses more data from another class than from its own class.

**Detection heuristic** (future AST enhancement):
- Method body references `other.x`, `other.y`, `other.z` more than `self.*`

**Current status**: Not yet AST-automated; flagged via manual review only.

**Fix strategy**: Move method to the class that owns the data.

---

### 3.3 Law of Demeter

**Rule**: Object should only call methods on: itself, its fields, its parameters, or locally created objects.

**Detection heuristic** (future AST enhancement):
- Chain of > 2 dots: `obj.a.b.c.do_something()` detected via `Attribute` nesting depth

**Current status**: Not yet AST-automated; flagged via manual review only.

**Fix strategy**: Introduce delegating method or use Tell-Don't-Ask pattern.

---

## 4. Code Smell Catalog

### 4.1 Duplication

**Detection** (AST-derived):
- Normalized structural hash (`_ASTHasher`) of AST subtrees (`FunctionDef`, `ClassDef`, `For`, `While`, `If`, `With`, `Try`) compared across all analyzed files
- Blocks >= `duplicate_ast_subtree_lines` (default 5) in 2+ locations are flagged

**AST metric**: `duplicate_ast_subtree_lines`

**Threshold**: 5 lines

**Fix strategy**: Extract common abstraction (function, class, or template method).

**Severity**: Medium.

---

### 4.2 Magic Numbers / Strings

**Detection**:
- Numeric literals > 2 digits without named constant — regex + AST `Constant` node inspection
- String literals used for semantics (e.g., `"admin"`, `"pending"`, `"ERROR"`) — regex + AST

**Note**: Not fully AST-backed; literals are identifiable in AST but semantic meaning
requires domain knowledge.

**Fix strategy**: Extract to named constants or enums.

**Severity**: Low.

---

### 4.3 Primitive Obsession

**Detection**:
- Domain concepts represented as primitives (`str`, `int`, `float`) instead of types
- Functions taking > 3 primitives of same type (easy to swap argument order)

**Note**: Partially AST-backed (arg types via annotations if present). Full detection
requires type inference not available from AST alone.

**Fix strategy**: Introduce value objects (e.g., `Email`, `Money`, `UserId`).

**Severity**: Low to Medium.

---

### 4.4 Data Clumps

**Detection**:
- Same group of variables passed together repeatedly
- Parameters that are never used independently

**Note**: Requires cross-function AST analysis (future enhancement).

**Fix strategy**: Extract into parameter object or class.

**Severity**: Low.

---

### 4.5 Speculative Generality

**Detection**:
- Abstract classes / interfaces with only one implementation
- Unused parameters, hooks, or callbacks
- "Future-proof" code that has never been used

**Note**: Partially AST-backed (class hierarchy counts). Usage detection requires
static call graph analysis.

**Fix strategy**: YAGNI — delete unused abstraction. Reintroduce when actually needed.

**Severity**: Low.

---

### 4.6 Temporary Field

**Detection**:
- Instance variable only set and used by a subset of methods
- Variable is None for most of object's lifetime

**Note**: Requires data-flow analysis beyond standard AST.

**Fix strategy**: Move temporary state to method return value or extract class.

**Severity**: Low.

---

### 4.7 Message Chains

**Detection**:
- Sequence of > 3 getter calls to reach target data
- Client tightly coupled to object graph structure

**Note**: Detectable via `Attribute` chain depth in AST (future enhancement).

**Fix strategy**: Hide delegate or use facade to encapsulate traversal.

**Severity**: Low.

---

### 4.8 Inappropriate Intimacy

**Detection**:
- Class accessing private/protected members of another (via name mangling bypass or friend classes)
- Bidirectional associations that are not semantically required

**Note**: Name-mangled access is AST-detectable.

**Fix strategy**: Make one class observe the other, or merge if they are truly inseparable.

**Severity**: Medium.

---

## 5. Uncertainty Classification

Use these labels on every finding to communicate heuristic confidence. AST-derived
findings have fixed low uncertainty; other findings retain variable uncertainty.

| Level | Meaning | Example |
|-------|---------|---------|
| **Low** | High confidence, objectively detectable via AST | `cyclomatic_complexity = 15 > threshold = 10`; `class_method_count = 12 > threshold = 10` |
| **Medium** | Moderate confidence, pattern-based detection | Missing input validation (may use decorator); magic number (may be conventional) |
| **High** | Low confidence, requires domain knowledge | SRP interpretation of cohesion; OCP need for extension point |

**Rule of thumb**: When uncertainty is High, phrase finding as a question or suggestion,
not an assertion. E.g., "Consider whether this class has more than one responsibility"
rather than "This class violates SRP."

**v4.0 rule**: All structural findings (design, complexity, coupling, duplication)
are AST-derived and therefore Low uncertainty. They are stated as facts, not suggestions.
