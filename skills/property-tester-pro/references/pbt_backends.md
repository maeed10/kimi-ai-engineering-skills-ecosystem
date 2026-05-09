# PBT Backend Reference

Per-language framework setup, generator strategies, and canonical patterns.

---

## Python: Hypothesis

### Install
```bash
pip install hypothesis
```

### Core Imports
```python
from hypothesis import given, strategies as st, settings, example, Phase
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, Bundle
```

### Common Strategies

| Type | Strategy | Notes |
|------|----------|-------|
| int | `st.integers(min_value=0, max_value=100)` | Always bound to prevent timeouts |
| float | `st.floats(allow_nan=True, allow_infinity=True)` | Include edge cases explicitly |
| str | `st.text(alphabet=st.characters(), min_size=0, max_size=1000)` | Add `st.sampled_from(['', '\\x00', '\\uffff'])` |
| bytes | `st.binary(min_size=0, max_size=4096)` | |
| list | `st.lists(st.integers(), min_size=0, max_size=100)` | Compose with `unique=True` for sets |
| dict | `st.dictionaries(st.text(), st.integers())` | |
| datetime | `st.datetimes(min_value=datetime(1970,1,1))` | Avoid year 1-999 edge noise |
| composite | `@st.composite` | Build domain-specific generators |

### Pattern: Property with Example
```python
from hypothesis import given, example, strategies as st

@given(st.text())
@example('')           # explicit regression case
@example('\x00')       # null byte
@example('\ud800')     # lone surrogate
@example('a' * 10000)  # large input
def test_my_function_does_not_crash_on_any_text(s):
    result = my_function(s)
    assert isinstance(result, str)
```

### Pattern: Stateful Machine
```python
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant, precondition
import hypothesis.strategies as st

class QueueMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.queue = Queue()
        self.model = []

    @rule(item=st.integers())
    def enqueue(self, item):
        self.queue.put(item)
        self.model.append(item)

    @rule()
    @precondition(lambda self: len(self.model) > 0)
    def dequeue(self):
        expected = self.model.pop(0)
        assert self.queue.get() == expected

    @invariant()
    def size_matches_model(self):
        assert self.queue.qsize() == len(self.model)

    @invariant()
    def size_non_negative(self):
        assert self.queue.qsize() >= 0

TestQueue = QueueMachine.TestCase
```

### Settings for CI
```python
from hypothesis import settings

# Fast for dev, thorough for CI
@settings(max_examples=200, deadline=None, phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink])
def test_ci_property():
    ...
```

---

## JavaScript / TypeScript: fast-check

### Install
```bash
npm install fast-check
# With vitest:
npm install @fast-check/vitest
```

### Core Imports
```javascript
import fc from 'fast-check';
// or for vitest:
import { testProp, fc } from '@fast-check/vitest';
```

### Common Arbitraries

| Type | Arbitrary | Notes |
|------|-----------|-------|
| number | `fc.integer()`, `fc.float()`, `fc.double()` | Use `fc.maxSafeInteger()` for int edge |
| string | `fc.string()`, `fc.unicodeString()`, `fc.hexaString()` | Add `fc.constant('')`, `fc.constant('\x00')` |
| array | `fc.array(fc.anything(), { minLength: 0, maxLength: 100 })` | Control size to prevent timeouts |
| object | `fc.object()`, `fc.json()` | |
| oneof | `fc.oneof(a, b, c)` | Union types |
| option | `fc.option(arb, { nil: undefined })` | Nullable |
| record | `fc.record({ name: fc.string(), age: fc.nat() })` | Struct-like |

### Pattern: Property Test
```javascript
import fc from 'fast-check';
import { test, expect } from 'vitest';

test('encode/decode roundtrip', () => {
  fc.assert(
    fc.property(
      fc.string(),
      (s) => {
        expect(decode(encode(s))).toBe(s);
      }
    ),
    { numRuns: 200 }
  );
});
```

### Pattern: Model-Based Testing
```javascript
import fc from 'fast-check';

test('counter state machine', () => {
  const commands = [
    fc.constant({ run: (r, m) => { r.inc(); m.count++; } }),
    fc.constant({ run: (r, m) => { r.dec(); m.count--; } }),
    fc.constant({ check: (r, m) => expect(r.get()).toBe(m.count) }),
  ];

  fc.assert(
    fc.modelRun(
      () => ({ real: new Counter(), model: { count: 0 } }),
      commands
    ),
    { numRuns: 100 }
  );
});
```

### Pattern: Async Property
```javascript
test('async fetch does not throw', async () => {
  await fc.assert(
    fc.asyncProperty(fc.webUrl(), async (url) => {
      const result = await fetchWithTimeout(url, 1000);
      expect(result).toBeDefined();
    }),
    { numRuns: 50 }
  );
});
```

---

## Rust: proptest

### Install
```toml
[dev-dependencies]
proptest = "1.0"
proptest-state-machine = "0.1"
```

### Core Imports
```rust
use proptest::prelude::*;
use proptest_state_machine::{ReferenceStateMachine, StateMachineTest};
```

### Common Strategies

| Type | Strategy | Notes |
|------|----------|-------|
| i32 | `any::<i32>()`, `i32::MIN..=i32::MAX` | Use ranges to avoid overflow noise |
| String | `".*"` (regex), `any::<String>()` | `"[a-z]{1,20}"` for bounded |
| Vec | `prop_vec(any::<u32>(), 0..100)` | Always size-bounded |
| Option | `prop_option(".*")` | |
| Custom | `prop_compose!` | Compose domain generators |

### Pattern: Property Macro
```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn sort_idempotent(mut vec: Vec<i32>) {
        let once = { vec.sort(); vec.clone() };
        vec.sort();
        prop_assert_eq!(once, vec);
    }

    #[test]
    fn reverse_reverse_is_identity(vec: Vec<u8>) {
        let cloned = vec.clone();
        prop_assert_eq!(cloned.into_iter().rev().rev().collect::<Vec<_>>(), vec);
    }
}
```

### Pattern: Custom Strategy with prop_compose
```rust
use proptest::prelude::*;

prop_compose! {
    fn valid_email()(name in "[a-z]{1,10}", domain in "[a-z]{1,5}") -> String {
        format!("{}@{}.com", name, domain)
    }
}

proptest! {
    #[test]
    fn parse_email(email in valid_email()) {
        prop_assert!(Email::parse(&email).is_ok());
    }
}
```

### Pattern: Stateful Testing
```rust
use proptest::prelude::*;
use proptest_state_machine::{ReferenceStateMachine, StateMachineTest};
use std::collections::VecDeque;

#[derive(Debug, Clone)]
enum Transition { Push(i32), Pop }

#[derive(Debug, Default, Clone)]
struct RefState(Vec<i32>);

impl ReferenceStateMachine for RefState {
    type State = RefState;
    type Transition = Transition;

    fn init_state() -> BoxedStrategy<Self::State> {
        Just(RefState(vec![])).boxed()
    }

    fn transitions(_state: &Self::State) -> BoxedStrategy<Self::Transition> {
        prop_oneof![
            any::<i32>().prop_map(Transition::Push),
            Just(Transition::Pop),
        ].boxed()
    }

    fn apply(mut state: Self::State, transition: &Self::Transition) -> Self::State {
        match transition {
            Transition::Push(x) => state.0.push(*x),
            Transition::Pop => { state.0.pop(); },
        }
        state
    }
}
```

---

## Go: gopter

### Install
```bash
go get github.com/leanovate/gopter
```

### Core Imports
```go
import (
    "github.com/leanovate/gopter"
    "github.com/leanovate/gopter/gen"
    "github.com/leanovate/gopter/prop"
)
```

### Common Generators

| Type | Generator | Notes |
|------|-----------|-------|
| int | `gen.IntRange(-1000, 1000)` | Always bounded in Go |
| string | `gen.AlphaString()`, `gen.UTF8String()` | |
| slice | `gen.SliceOf(gen.Int())` | |
| struct | `gopter.DeriveGen` | Custom derived generators |
| oneof | `gen.OneGenOf(a, b)` | Union |

### Pattern: Property Check
```go
import (
    "testing"
    "github.com/leanovate/gopter"
    "github.com/leanovate/gopter/gen"
    "github.com/leanovate/gopter/prop"
)

func TestReverseIdentity(t *testing.T) {
    parameters := gopter.DefaultTestParameters()
    parameters.MinSuccessfulTests = 200

    properties := gopter.NewProperties(parameters)

    properties.Property("reverse(reverse(x)) == x", prop.ForAll(
        func(s string) bool {
            runes := []rune(s)
            reversed := reverse(reverse(runes))
            return string(reversed) == s
        },
        gen.UTF8String(),
    ))

    properties.TestingRun(t)
}
```

### Pattern: Custom Generator
```go
func genBoundedInt(min, max int) gopter.Gen {
    return gen.IntRange(min, max).SuchThat(func(v int) bool {
        return v >= min && v <= max
    })
}

properties.Property("addition is commutative", prop.ForAll(
    func(a, b int) bool {
        return add(a, b) == add(b, a)
    },
    genBoundedInt(-1000, 1000),
    genBoundedInt(-1000, 1000),
))
```

---

## Java: jqwik

### Setup (Gradle)
```groovy
testImplementation 'net.jqwik:jqwik:1.8.0'
```

### Pattern: Property
```java
import net.jqwik.api.*;

class StringProperties {
    @Property
    boolean concatenationLength(@ForAll String a, @ForAll String b) {
        return (a + b).length() >= a.length();
    }

    @Property
    boolean reverseReverse(@ForAll String s) {
        return new StringBuilder(s).reverse().reverse().toString().equals(s);
    }

    @Provide
    Arbitrary<String> alphaStrings() {
        return Arbitraries.strings().withCharRange('a', 'z').ofMinLength(1).ofMaxLength(20);
    }
}
```

---

## C#: FsCheck.xUnit

### Setup
```bash
dotnet add package FsCheck.Xunit
```

### Pattern: Property
```csharp
using FsCheck.Xunit;
using Xunit;

public class StringProperties {
    [Property]
    public bool ReverseReverseIsIdentity(string s) {
        return new string(s.Reverse().Reverse().ToArray()) == s;
    }

    [Property(MaxTest = 200)]
    public bool SortIsIdempotent(List<int> xs) {
        var once = xs.OrderBy(x => x).ToList();
        var twice = once.OrderBy(x => x).ToList();
        return once.SequenceEqual(twice);
    }
}
```
