---
name: dev-test-automation
description: Developer-facing test automation skill that generates tests from source code, analyzes coverage gaps, creates mocks, and integrates with pytest, jest, vitest, go test, cargo test. Use when writing tests, filling coverage gaps, refactoring with regression protection, or analyzing test suite quality with mutation testing.
---

# Dev Test Automation

Automate test generation, execution, and coverage analysis. Generates unit, integration, and E2E tests from source code, analyzes coverage gaps, and integrates with popular test runners.

## When to Use

- When writing tests for new or existing code
- When coverage is below threshold and gaps need filling
- When refactoring and need regression tests
- When setting up testing infrastructure for a project
- When running test suites and analyzing failures

## Test Generation Workflow

### Step 1: Analyze Source Code

Before generating tests, analyze the code under test:

1. **Identify the test target**: function, class, module, or API endpoint
2. **Determine the language and test framework**: see `references/test_patterns.md`
3. **Extract the public interface**: signatures, return types, raised exceptions
4. **Identify dependencies**: external services, databases, file system, network calls
5. **Map execution paths**: branches, loops, error handling, edge cases

**Analysis checklist**:
- [ ] What are the happy-path inputs and expected outputs?
- [ ] What boundary values should be tested? (empty, zero, max, null, None)
- [ ] What exceptions or errors can be raised?
- [ ] Are there side effects (I/O, state mutation, external calls)?
- [ ] Are there concurrent or async behaviors?

### Step 2: Select Test Type

Choose the appropriate test category based on the target and goal:

| Goal | Test Type | Location |
|------|-----------|----------|
| Verify a pure function | Unit test | `tests/unit/` or `__tests__/` |
| Verify a class in isolation | Unit test with mocks | Same as above |
| Verify module interactions | Integration test | `tests/integration/` |
| Verify API endpoint | Integration / API test | `tests/api/` or `tests/e2e/` |
| Verify UI behavior | E2E / Component test | `tests/e2e/` or `cypress/` |
| Prevent regression after refactor | Unit + Integration | Existing test dirs |
| Fill coverage gaps | Targeted unit test | Adjacent to code under test |

### Step 3: Generate Test Scaffold

Use the language-specific pattern from `references/test_patterns.md` to create:

1. **Imports and fixtures**: test runner, mocks, test utilities
2. **Arrange phase**: setup data, mock dependencies, configure state
3. **Act phase**: invoke the function/method under test
4. **Assert phase**: verify return value, state changes, mock interactions
5. **Cleanup**: teardown resources, reset mocks

**Template (pytest example)**:
```python
import pytest
from unittest.mock import Mock, patch
from mymodule import process_order

def test_process_order_success():
    # Arrange
    order = {"id": 1, "items": [{"sku": "A", "qty": 2}]}
    mock_db = Mock()
    mock_db.get_inventory.return_value = 100

    # Act
    result = process_order(order, db=mock_db)

    # Assert
    assert result.status == "confirmed"
    mock_db.reserve_inventory.assert_called_once_with("A", 2)
```

### Step 4: Add Edge Cases and Parameterized Tests

Expand the scaffold with data-driven cases:

- **Boundary values**: min/max, empty collections, zero, negative
- **Type variations**: where applicable, test coercion and validation
- **Error paths**: exceptions, timeout, network failure, auth failure
- **Concurrency**: race conditions, shared state, re-entrancy

Use parameterized tests to avoid duplication:
```python
@pytest.mark.parametrize("input,expected", [
    ("hello", 5),
    ("", 0),
    ("1234567890", 10),
])
def test_string_length(input, expected):
    assert len(input) == expected
```

### Step 5: Generate Mocks and Stubs

For each external dependency identified in Step 1, create a mock or stub:

| Dependency Type | Mock Strategy | Tool |
|-----------------|---------------|------|
| HTTP API | Patch `requests` / `fetch` / `axios` | `responses`, `nock`, `msw` |
| Database | Mock connection / ORM session | `unittest.mock`, `jest.mock`, `sqlmock` |
| File system | Patch `open`, `pathlib`, `fs` | `tmp_path` (pytest), `mock-fs` |
| Environment | Patch `os.environ`, `process.env` | `monkeypatch`, `jest` |
| Time / UUID | Patch `datetime.now`, `uuid.uuid4` | `freezegun`, `jest` |
| Queue / Message bus | Mock producer/consumer | `unittest.mock`, `testcontainers` |

**Mock verification rules**:
- Verify the dependency was called the expected number of times
- Verify arguments match expectations
- Do not over-specify internal implementation details
- Prefer `Mock(spec=RealClass)` to catch interface drift

### Step 6: Run and Validate

Execute the generated tests against the code:

```bash
# Python
pytest tests/ -v --tb=short --strict-markers

# JavaScript / TypeScript
npx jest --verbose --coverage
npx vitest run --reporter=verbose

# Go
go test ./... -v -race -coverprofile=coverage.out

# Rust
cargo test --all-features --workspace
cargo tarpaulin --out Xml

# Java
./mvnw test
./gradlew test
```

**Validation checklist**:
- [ ] All new tests pass
- [ ] No existing tests broken (regression check)
- [ ] Tests are deterministic (run 3x to check flakiness)
- [ ] Mocks match real dependency behavior
- [ ] Assertions are specific and meaningful

## Coverage Gap Analysis

### Identifying Untested Code

1. **Run coverage collection** with the appropriate tool for the language
2. **Load the coverage report** (HTML, XML, or JSON)
3. **Filter to missing lines/branches**:
   - Lines never executed
   - Branches not taken (true/false)
   - Partial hits on compound conditions
4. **Map each gap** to a specific test scenario:
   - `if retry_count > 3:` → test with `retry_count = 2, 3, 4`
   - `except ConnectionError:` → test with mocked connection failure
   - `for item in items:` → test with empty list, single item, many items

### Gap Analysis Methodology

Follow the methodology in `references/coverage_thresholds.md`:

1. **Set thresholds by project type** (library, service, CLI, script)
2. **Prioritize gaps** by risk and frequency of execution:
   - Error handling > edge-case logic > logging
   - Public API > internal helpers > generated code
3. **Write targeted tests** for each prioritized gap
4. **Re-run coverage** and verify the gap is closed
5. **Document intentional omissions** with `# pragma: no cover` or equivalent

### Coverage Targets Summary

| Project Type | Line | Branch | Function | Mutation |
|--------------|------|--------|----------|----------|
| Critical library | 95% | 90% | 95% | 85% |
| Web service / API | 85% | 80% | 85% | 70% |
| CLI tool | 80% | 75% | 80% | 60% |
| Internal script | 70% | 60% | 70% | 50% |
| Prototype / spike | 60% | 50% | 60% | N/A |

## Test Runner Integration

### Supported Runners

| Language | Runners | Coverage Tool | Best For |
|----------|---------|---------------|----------|
| Python | pytest, unittest | coverage.py, pytest-cov | All project sizes |
| JavaScript | jest, vitest, mocha | built-in, c8 | Frontend, Node.js |
| TypeScript | jest, vitest | built-in, c8 | Frontend, Node.js |
| Go | go test | built-in (`-cover`) | Services, CLIs |
| Rust | cargo test | cargo-tarpaulin, llvm-cov | Systems, libraries |
| Java | JUnit, TestNG | JaCoCo | Enterprise, Spring |
| C# | xUnit, NUnit, MSTest | Coverlet, dotCover | .NET applications |

### Runner Configuration Patterns

**pytest (`pyproject.toml`)**:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short --strict-markers --cov=src --cov-report=term-missing"
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests as integration tests",
]
```

**jest (`jest.config.js`)**:
```javascript
module.exports = {
  testEnvironment: 'node',
  coverageDirectory: 'coverage',
  collectCoverageFrom: ['src/**/*.js'],
  coverageThreshold: {
    global: { branches: 80, functions: 80, lines: 80, statements: 80 }
  },
  testMatch: ['**/__tests__/**/*.test.js']
};
```

**vitest (`vitest.config.ts`)**:
```typescript
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      thresholds: { lines: 80, functions: 80, branches: 75 }
    }
  }
});
```

**Go (Makefile target)**:
```makefile
test:
	go test ./... -race -coverprofile=coverage.out -covermode=atomic
	go tool cover -html=coverage.out -o coverage.html
```

## Snapshot Testing

Use snapshot tests for stable, complex data structures and UI output.

### When to Snapshot

- API response shapes (JSON schemas)
- HTML / component render output
- CLI stdout / help text
- Generated configuration files
- Error message formatting

### When NOT to Snapshot

- Values that change on every run (timestamps, IDs)
- Numeric calculations with floating point
- External API responses with volatile data

### Snapshot Workflow

1. **Generate initial snapshot** on first run
2. **Review snapshot** in PR — treat as code
3. **Update snapshot** when behavior intentionally changes: `jest -u`, `vitest -u`, `pytest --snapshot-update`
4. **Delete obsolete snapshots** during cleanup

## Mutation Testing

Verify test suite quality by introducing artificial bugs and checking if tests catch them.

### Running Mutation Tests

| Language | Tool | Command |
|----------|------|---------|
| Python | mutmut | `mutmut run && mutmut results` |
| Python | cosmic-ray | `cosmic-ray init config.toml session.sqlite && cosmic-ray exec session.sqlite` |
| JavaScript | Stryker | `npx stryker run` |
| Java | PIT | `mvn org.pitest:pitest-maven:mutationCoverage` |
| C# | Stryker.NET | `dotnet stryker` |

### Interpreting Results

- **Mutation Score** = (killed mutants / total mutants) * 100
- **Goal**: score above the threshold in `references/coverage_thresholds.md`
- **Undetected mutants** indicate:
  - Missing assertions (test passes even with bug)
  - Weak assertions (only checking not-null)
  - Unused code (mutant in dead code)

**Remediation**:
1. For each surviving mutant, examine the mutated line
2. Write a targeted test that would fail with the mutation
3. Re-run mutation testing to confirm the fix

## Flaky Test Detection

### Identifying Flaky Tests

A test is flaky if it produces different outcomes across runs without code changes.

**Common causes**:
- Time dependencies (timeouts, `sleep`, `now()`)
- Randomness without seeded values
- Shared mutable state (global variables, static caches)
- Async races (unawaited promises, goroutine timing)
- External services (network, database, file system)
- Test order dependencies (leaked state between tests)

### Detection Protocol

1. **Run the full suite 5 times** and compare results
2. **Run targeted suspect tests in isolation** 10 times
3. **Shuffle test order** (`pytest --random-order`, `jest --randomize`)
4. **Run with resource stress** (`stress-ng`, limited CPU)

**Example (pytest flaky test rerun)**:
```bash
pytest tests/ -v --count=10 --cache-clear -x  # run each test 10 times
```

### Fixing Flaky Tests

| Cause | Fix |
|-------|-----|
| Time | Freeze time (`freezegun`, `jest.useFakeTimers`) |
| Random | Seed RNG in test setup |
| Shared state | Reset state in `setUp` / `beforeEach` |
| Async | Always await; use `asyncio.wait_for` |
| External | Mock or use testcontainers |
| Ordering | Isolate tests; avoid global fixtures |

## Automation Scripts

Use `scripts/generate_tests.py` to analyze source files and produce test scaffolds:

```bash
# Generate tests for a Python module
python scripts/generate_tests.py --source src/billing/calc.py --framework pytest --output tests/unit/test_calc.py

# Generate tests for a TypeScript file
python scripts/generate_tests.py --source src/utils/parser.ts --framework vitest --output src/utils/__tests__/parser.test.ts
```

The script performs static analysis to extract:
- Function/class signatures
- Raised exceptions
- Branch points
- External imports (for mock suggestions)

## Best Practices

- **One concern per test**: test a single behavior with a descriptive name
- **Arrange-Act-Assert**: structure tests clearly
- **Meaningful assertions**: avoid `assertTrue(True)` or `expect(x).toBeDefined()`
- **Test the contract, not the implementation**: refactor-safe tests target public behavior
- **Fast feedback**: unit tests should run in milliseconds; use markers for slow tests
- **Determinism**: tests must produce the same result every run
- **Maintainability**: update tests when requirements change, not when implementation changes

## Resources

### scripts/
- `generate_tests.py` — Analyze source code and generate test scaffolds

### references/
- `test_patterns.md` — Per-language test patterns, assertion libraries, mocking frameworks
- `coverage_thresholds.md` — Coverage targets by project type, gap analysis methodology
