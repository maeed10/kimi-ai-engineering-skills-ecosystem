# Coverage Thresholds and Gap Analysis

Guidelines for setting coverage targets, analyzing coverage reports, and systematically closing gaps.

## Coverage Targets by Project Type

Use these targets as starting points. Adjust based on risk, team maturity, and regulatory requirements.

### Threshold Matrix

| Project Type | Line | Branch | Function | Statement | Mutation |
|--------------|------|--------|----------|-----------|----------|
| Critical library (crypto, auth, payments) | 95% | 90% | 95% | 95% | 85% |
| Public library / SDK | 90% | 85% | 90% | 90% | 75% |
| Web service / API | 85% | 80% | 85% | 85% | 70% |
| Microservice (internal) | 80% | 75% | 80% | 80% | 65% |
| CLI tool | 80% | 75% | 80% | 80% | 60% |
| Frontend application | 75% | 70% | 75% | 75% | 55% |
| Internal script / ETL | 70% | 60% | 70% | 70% | 50% |
| Prototype / spike | 60% | 50% | 60% | 60% | N/A |
| Generated code / boilerplate | Exempt | Exempt | Exempt | Exempt | Exempt |

### Rationale

- **Line coverage**: Percentage of executable lines hit. Easy to game; always pair with branch coverage.
- **Branch coverage**: Percentage of decision branches (true/false) taken. Catches missing `else` and untested error paths.
- **Function/method coverage**: Percentage of functions called at least once. Useful for identifying completely dead code.
- **Statement coverage**: Similar to line; counts individual statements. Some tools report this instead of lines.
- **Mutation coverage**: Quality metric. High line coverage with low mutation score means weak assertions.

## Gap Analysis Methodology

A systematic workflow for turning a coverage report into a closed gap list.

### Phase 1: Collect Coverage Data

1. Run the full test suite with coverage enabled:
   ```bash
   # Python
   pytest --cov=src --cov-report=term-missing --cov-report=html

   # JavaScript (jest)
   jest --coverage --coverageReporters=text-summary --coverageReporters=html

   # Go
   go test ./... -coverprofile=coverage.out
   go tool cover -html=coverage.out -o coverage.html

   # Rust
   cargo tarpaulin --out Html --out Lcov

   # Java (Maven)
   mvn jacoco:report
   ```

2. Generate both **summary** (CLI / CI) and **detailed** (HTML) reports.

3. Ensure the report excludes:
   - Third-party vendored code
   - Generated files (protobuf, OpenAPI client)
   - Type definitions / interface-only files
   - Migration scripts and seeders
   - `if __name__ == "__main__":` blocks (when appropriate)

### Phase 2: Parse the Report

Load the detailed report and extract untested regions:

**Missing lines**:
- Identify contiguous or scattered missing line numbers
- Group by function / method / branch

**Missing branches**:
- Note `if` conditions where only true or only false was taken
- Note `try/except` or `catch` blocks where error path is untested
- Note short-circuit logic (`A and B`, `A or B`) with partial evaluation

**Missing functions**:
- Functions never called by any test
- Decide if they are dead code (delete) or missing tests (add)

### Phase 3: Classify Gaps by Risk

For each untested region, assign a priority:

| Priority | Criteria | Action |
|----------|----------|--------|
| **P0 — Critical** | Error handling, security checks, input validation, payment logic | Must test before merge |
| **P1 — High** | Business logic branches, API contract enforcement, data transformations | Include in current sprint |
| **P2 — Medium** | Logging at different levels, metrics emission, caching logic | Backlog if time permits |
| **P3 — Low** | Debug utilities, admin-only commands, rarely used CLI flags | Document intentional skip |
| **P4 — Exempt** | Generated code, type-only files, simple passthrough delegates | Add exclusion pragma |

### Phase 4: Map Gaps to Test Scenarios

Convert each gap into a concrete test scenario using this mapping:

| Code Pattern | Missing Coverage | Test Scenario |
|--------------|-----------------|---------------|
| `if retry_count > 3:` | Branch false only | Test with `retry_count = 2` (true) and `retry_count = 4` (false) |
| `except ConnectionError:` | Exception path | Mock transport to raise `ConnectionError` |
| `for item in items:` | Empty list not tested | Test with `items = []` |
| `if user and user.is_active:` | Short-circuit branches | Test `user = None`, `user = inactive`, `user = active` |
| `raise ValueError(...)` | Error not triggered | Test with invalid input |
| `if config.debug:` | Debug false only | Test with `config.debug = True` (or mark exempt) |
| `try ... finally` | Finally not entered | Test normal path and exception path |
| `switch/case` or `match` | One arm untested | Add case for the missing variant |

### Phase 5: Write Targeted Tests

For each P0/P1 gap, write a minimal test that exercises exactly the missing path:

1. **Isolate the unit**: mock all dependencies
2. **Set preconditions**: inputs and state that lead to the missing branch
3. **Trigger execution**: call the function
4. **Assert outcomes**: return value, exception, state change, or mock interaction
5. **Verify coverage**: re-run coverage for the file; confirm the gap is closed

### Phase 6: Verify and Document

1. Re-run the full suite and confirm coverage meets the threshold
2. Add exclusion markers for intentional gaps:
   - **Python**: `# pragma: no cover` with comment explaining why
   - **JavaScript**: `/* istanbul ignore next */` or `/* c8 ignore next */`
   - **Go**: no built-in pragma; skip in coverage config or accept gap
   - **Rust**: `#[cfg(not(tarpaulin))]` or tarpaulin `ignore` attribute
   - **Java**: exclude in JaCoCo Maven plugin configuration
   - **C#**: `[ExcludeFromCodeCoverage]` attribute

3. Update CI gates (see below) to enforce the new threshold
4. Record exempted regions in project documentation

## Coverage in CI/CD

### Failing the Build on Coverage Drop

**Python (pytest-cov)**:
```bash
pytest --cov=src --cov-fail-under=85 --cov-report=xml
```

**Jest** (`jest.config.js`):
```javascript
coverageThreshold: {
  global: {
    branches: 80,
    functions: 80,
    lines: 85,
    statements: 85
  }
}
```

**Vitest** (`vitest.config.ts`):
```typescript
coverage: {
  thresholds: {
    lines: 85,
    functions: 80,
    branches: 75,
    statements: 85
  }
}
```

**Go (Makefile)**:
```makefile
coverage:
	go test ./... -coverprofile=coverage.out
	go tool cover -func=coverage.out | awk '/total:/ {if ($$3 < 80.0) exit 1}'
```

**Rust (tarpaulin in CI)**:
```yaml
# GitHub Actions example
- name: Run coverage
  run: cargo tarpaulin --fail-under 80 --out Xml
```

### Diff Coverage (New Code Only)

Enforce higher standards on changed code without blocking legacy gaps:

- **Python**: `diff-cover coverage.xml --compare-branch=main --fail-under=90`
- **JavaScript**: `jest --changedSince=main --coverage`
- **Go**: Not built-in; use custom scripts or third-party tools

### Coverage Trends

Track coverage over time to prevent regression:

| Tool | Trend Report |
|------|-------------|
| Codecov | Upload reports; track graphs per branch |
| Coveralls | Historical trends and PR comments |
| SonarQube | Quality gate with coverage as a condition |
| GitHub Actions | Store artifacts and compare in PR comments |

## Mutation Testing Integration

Use mutation scores to validate that coverage is meaningful, not just cosmetic.

### Interpreting Mutation Gaps

A surviving mutant means the test suite did not catch an artificial bug. This indicates:

| Surviving Mutant | Likely Cause | Fix |
|-----------------|--------------|-----|
| Arithmetic operator changed (`+` to `-`) | No assertion on numeric result | Add precise value assertion |
| Comparison flipped (`>` to `>=`) | Weak boundary test | Add boundary value case |
| Return value mutated | Missing assertion on return | Assert exact return value |
| Exception removed | No test for error path | Add error-path test |
| Conditional boundary changed | Branch only tested one way | Add branch for other condition |

### Target Scores

| Project Type | Minimum Mutation Score |
|--------------|----------------------|
| Critical library | 85% |
| Public library | 75% |
| Web service | 70% |
| CLI / internal | 60% |
| Prototype | N/A |

## Common Anti-Patterns to Avoid

1. **Testing implementation instead of behavior**: tests break on every refactor
2. **Over-mocking**: mock only external boundaries, not internal collaborators
3. **False confidence from high line coverage**: pair with branch and mutation metrics
4. **Excluding everything**: excessive `# pragma: no cover` defeats the purpose
5. **Ignoring flaky coverage**: coverage that oscillates between runs indicates flaky tests
6. **One giant test per function**: multiple small tests are easier to debug
7. **Asserting only not-null**: weak assertions that let mutants survive
