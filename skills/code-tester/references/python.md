# Python-Specific Testing Guide

Language-specific test patterns, anti-patterns, and tooling for Python codebases.

## Test Patterns

### pytest Fixtures vs. xUnit setUp
- **Prefer fixtures**: Named, composable, scoped (`function`, `class`, `module`, `package`, `session`)
- Use `@pytest.fixture(scope="module")` for expensive setup (database, containers)
- Fixture dependency injection: fixtures request other fixtures by parameter name
- `conftest.py` for shared fixtures across a directory tree

```python
# Good: composable fixtures with clear scope
@pytest.fixture(scope="session")
def docker_db():
    container = start_postgres()
    yield container
    container.stop()

@pytest.fixture
def db_session(docker_db):
    session = create_session(docker_db.url)
    yield session
    session.rollback()
```

### Mocking with unittest.mock
- **Patch at import location**: `@patch("module.under_test.ExternalClass")` not `@patch("external.ExternalClass")`
- Use `spec=` or `autospec=True` to ensure mocks match the real interface
- Prefer ` MagicMock` for general mocking, `Mock` for simpler cases
- `mock_call_args_list` for asserting call sequences

```python
# Good: patch at the point of use, with spec
@patch("payments.service.PaymentGateway", autospec=True)
def test_process_payment_calls_gateway(mock_gateway):
    mock_gateway.return_value.charge.return_value = {"status": "approved"}
    result = process_payment(order)
    mock_gateway.return_value.charge.assert_called_once_with(order.total)
```

### Parameterized Testing
- Use `@pytest.mark.parametrize` for boundary values, error cases, and equivalent inputs
- Combine with fixtures: parametrize can reference fixture values indirectly
- `pytest-cases` for more complex parameterization scenarios

```python
@pytest.mark.parametrize("amount,currency,expected", [
    (100, "USD", Decimal("100.00")),
    (0, "USD", Decimal("0.00")),        # boundary: zero
    (-1, "USD", None),                   # boundary: negative (error)
    (100, "INVALID", None),              # boundary: invalid currency
])
def test_format_currency(amount, currency, expected):
    ...
```

## Assertion Styles

| Style | When to Use | Example |
|-------|-------------|---------|
| Direct assertion | Simple equality | `assert result == expected` |
| pytest.raises | Exception testing | `with pytest.raises(ValueError, match="msg"):` |
| pytest.approx | Float comparison | `assert result == pytest.approx(3.1415, 0.001)` |
| assert dict subset | Partial dict match | `assert expected.items() <= result.items()` |
| list/dict helpers | Collection membership | `assert item in result` / `assert all(x > 0 for x in items)` |

### Snapshot Testing
- Use `syrupy` or `pytest-snapshot` for complex output verification (API responses, HTML)
- Commit snapshot files to version control
- Review snapshot diffs in PR review as carefully as code changes

## Common Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| `@patch` with wrong target path | Mock never applied | Patch where the name is used, not where defined |
| `time.sleep()` in tests | Flaky, slow tests | Mock `time` or use `freezegun` |
| Database in unit tests | Slow, non-isolated | Use in-memory SQLite or mock the repository layer |
| Global state mutation | Test order dependency | Reset state in fixture teardown; avoid globals |
| `assert True` (tautology) | No actual verification | Replace with specific, meaningful assertion |
| Hardcoded test data at module level | Shared mutable state | Use fixtures for fresh instances |
| Skipped assertions in loops | First failure hides others | Use `@pytest.mark.parametrize` instead |

## Coverage Tool Recommendations

### pytest-cov (primary)
```bash
# Basic usage
pytest --cov=src --cov-report=term-missing --cov-report=html

# JSON output for programmatic consumption
pytest --cov=src --cov-report=json

# Fail if coverage below threshold
pytest --cov=src --cov-fail-under=70

# Branch coverage (catches missed elif/else)
pytest --cov=src --cov-branch
```

### Configuration in pyproject.toml
```toml
[tool.coverage.run]
source = ["src"]
branch = true
omit = ["*/tests/*", "*/venv/*"]

[tool.coverage.report]
fail_under = 70
skip_covered = false
show_missing = true
```

## Key pytest Plugins

| Plugin | Purpose | Install |
|--------|---------|---------|
| `pytest-cov` | Coverage integration | `pip install pytest-cov` |
| `pytest-mock` | unittest.mock integration | `pip install pytest-mock` |
| `pytest-xdist` | Parallel test execution | `pip install pytest-xdist` |
| `freezegun` | Time mocking | `pip install freezegun` |
| `responses` | HTTP request mocking | `pip install responses` |
| `factory_boy` | Test data factories | `pip install factory_boy` |
| `faker` | Fake data generation | `pip install Faker` |
