# Invariant Pattern Reference

Domain-specific invariant templates for property-based testing. Select 2-4 per function under test.

---

## Sorting & Ordering

| # | Invariant | Template |
|---|-----------|----------|
| 1 | Idempotence | `sort(sort(xs)) == sort(xs)` |
| 2 | Length preservation | `len(sort(xs)) == len(xs)` |
| 3 | Permutation | `sorted(xs)` is a permutation of `xs` (multiset equal) |
| 4 | Monotonicity | `all(sort(xs)[i] <= sort(xs)[i+1])` |
| 5 | Stability (if stable sort) | Equal elements retain relative order |
| 6 | Min/Max | `sort(xs)[0] == min(xs)` (if non-empty) |

### Example: Python
```python
@given(st.lists(st.integers()))
def test_sort_properties(xs):
    result = sorted(xs)
    # Idempotence
    assert sorted(result) == result
    # Length preservation
    assert len(result) == len(xs)
    # Monotonicity
    assert all(result[i] <= result[i+1] for i in range(len(result)-1))
    # Multiset equality
    assert Counter(result) == Counter(xs)
```

---

## Parsing & Serialization

| # | Invariant | Template |
|---|-----------|----------|
| 1 | Round-trip | `parse(serialize(x)) == x` |
| 2 | Round-trip reverse | `serialize(parse(s)) == normalize(s)` |
| 3 | No crash | `parse(any_string)` does not panic/throw |
| 4 | Error propagation | Invalid input yields error, not silent wrong output |
| 5 | Whitespace handling | `parse(trim(s)) == parse(s)` (if whitespace-insensitive) |
| 6 | Partial parse | Prefix of valid input produces prefix result or error |

### Example: Rust
```rust
proptest! {
    #[test]
    fn json_roundtrip(obj in arb_json_value()) {
        let serialized = serde_json::to_string(&obj).unwrap();
        let deserialized: Value = serde_json::from_str(&serialized).unwrap();
        prop_assert_eq!(obj, deserialized);
    }

    #[test]
    fn json_no_crash(s in "\\PC*") {
        let _ = serde_json::from_str::<Value>(&s); // must not panic
    }
}
```

---

## Collections & Data Structures

| # | Invariant | Template |
|---|-----------|----------|
| 1 | Size after add/remove | `size(add(x, s)) == size(s) + 1` (if not duplicate) |
| 2 | Contains after add | `contains(x, add(x, s))` |
| 3 | Not contains after remove | `not contains(x, remove(x, s))` |
| 4 | Empty identity | `union(empty, s) == s` |
| 5 | Commutativity (set ops) | `union(a, b) == union(b, a)` |
| 6 | Associativity | `union(a, union(b, c)) == union(union(a, b), c)` |
| 7 | Distributivity | `intersection(a, union(b, c)) == union(intersection(a,b), intersection(a,c))` |

### Example: JavaScript
```javascript
test('set union is commutative', () => {
  fc.assert(
    fc.property(fc.array(fc.nat()), fc.array(fc.nat()), (a, b) => {
      const setA = new Set(a), setB = new Set(b);
      expect(union(setA, setB)).toEqual(union(setB, setA));
    })
  );
});
```

---

## Arithmetic & Numerical

| # | Invariant | Template |
|---|-----------|----------|
| 1 | Commutativity | `add(a, b) == add(b, a)` |
| 2 | Associativity | `add(a, add(b, c)) == add(add(a, b), c)` (watch overflow) |
| 3 | Identity | `add(x, 0) == x` |
| 4 | Inverse | `sub(add(a, b), b) == a` |
| 5 | Distributivity | `mul(a, add(b, c)) == add(mul(a,b), mul(a,c))` |
| 6 | Non-negativity | `distance(a, b) >= 0` |
| 7 | Triangle inequality | `distance(a, c) <= distance(a, b) + distance(b, c)` |
| 8 | Monotonicity | `a <= b implies add(a, c) <= add(b, c)` |

### Overflow-Safe Pattern
```python
# Python: arbitrary precision, but test behavior with bounded ints
@given(st.integers(min_value=-2**31, max_value=2**31-1))
def test_add_commutative(a, b):
    assume(abs(a) < 10**9 and abs(b) < 10**9)  # prevent timeout on huge values
    assert add(a, b) == add(b, a)
```

```rust
// Rust: test wrapping vs checked behavior separately
proptest! {
    #[test]
    fn checked_add_commutative(a in -1000i32..=1000, b in -1000i32..=1000) {
        prop_assert_eq!(a.checked_add(b), b.checked_add(a));
    }
}
```

---

## State Machines

| # | Invariant | Template |
|---|-----------|----------|
| 1 | State validity | `state.invariant()` holds after every transition |
| 2 | Action preconditions | Precondition checked before action; postcondition after |
| 3 | Model equivalence | Real system state matches abstract model state |
| 4 | No crash on valid actions | Any valid action sequence does not panic |
| 5 | Idempotent transitions | Duplicate action has expected effect (e.g., idempotent PUT) |
| 6 | Rollback | Undo after action restores prior state (if applicable) |

### Example: Python Hypothesis Stateful
```python
class DatabaseMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.db = InMemoryDB()
        self.model = {}

    @rule(key=st.text(min_size=1), value=st.integers())
    def insert(self, key, value):
        self.db.put(key, value)
        self.model[key] = value

    @rule(key=st.sampled_from(['a', 'b', 'c']))
    def delete(self, key):
        self.db.delete(key)
        self.model.pop(key, None)

    @invariant()
    def keys_match(self):
        assert set(self.db.keys()) == set(self.model.keys())

    @invariant()
    def values_match(self):
        for k, v in self.model.items():
            assert self.db.get(k) == v
```

---

## String & Text Processing

| # | Invariant | Template |
|---|-----------|----------|
| 1 | Length bounds | `0 <= len(result) <= len(input) + C` |
| 2 | Empty input | `f('')` yields expected base case |
| 3 | Concatenation | `f(a + b)` relates to `f(a)`, `f(b)` (if applicable) |
| 4 | Unicode safety | `f(unicode_string)` does not crash |
| 5 | Surrogate safety | `f(string_with_surrogates)` handled correctly |
| 6 | Reversibility | `f(f(input)) == input` (if involutory) |

---

## Cryptographic & Hashing

| # | Invariant | Template |
|---|-----------|----------|
| 1 | Determinism | `hash(x) == hash(x)` (same input, same output) |
| 2 | Avalanche | Small input change yields large output change (statistical) |
| 3 | Fixed output size | `len(hash(x)) == EXPECTED_SIZE` |
| 4 | Non-zero | `hash(x) != all_zeros` |
| 5 | Prefix independence | `hash(a+b)` not predictable from `hash(a)` |

---

## Choosing Invariants

1. **Read the function signature and docstring** — infer expected behavior
2. **Check for mathematical structure** — is it a monoid? functor? equivalence relation?
3. **Look for symmetry** — commutative, associative, distributive properties
4. **Consider failure modes** — empty input, null, max values, malformed data
5. **Cross-reference blast-radius** — HIGH-RISK modules get more invariants + stateful PBT
6. **Start with 2, expand to 4** — add more only if initial PBT finds issues

## Anti-Patterns to Avoid

- **Tautological assertions**: `assert x == x` provides no value
- **Overly strict invariants**: `parse(serialize(x)) == x` may fail for lossy formats; use `== normalize(x)`
- **Unbounded generators**: Always set `max_size`, `maxLength`, or `min_value/max_value`
- **Stateful without preconditions**: Every `@rule` that mutates needs matching preconditions for validity
