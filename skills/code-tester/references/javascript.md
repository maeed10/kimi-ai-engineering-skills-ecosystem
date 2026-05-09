# JavaScript/TypeScript-Specific Testing Guide

Language-specific test patterns, anti-patterns, and tooling for JavaScript and TypeScript codebases.

## Test Patterns

### Jest Mocks vs. Manual Stubs
- **jest.mock()** for module-level mocking (auto-mocks entire module)
- **jest.spyOn()** for observing existing method calls without replacing implementation
- **jest.fn()** for creating standalone mock functions with assertion capabilities
- `mockImplementation` / `mockReturnValue` for controlling behavior
- `mockResolvedValue` / `mockRejectedValue` for Promise-returning functions

```javascript
// Good: spy to verify calls without changing behavior
const sendSpy = jest.spyOn(emailService, 'send').mockResolvedValue({ messageId: '123' });

// Good: mock a module entirely
jest.mock('../api/client', () => ({
  fetchUser: jest.fn().mockResolvedValue({ id: 1, name: 'Alice' })
}));

// Good: partial mock preserving rest of module
jest.spyOn(console, 'error').mockImplementation(() => {});
```

### Vitest-Specific Patterns
- Native ESM support — no babel transformation needed
- `vi` namespace instead of `jest`: `vi.fn()`, `vi.spyOn()`, `vi.mock()`
- `beforeAll`/`afterAll` from `vitest` import (not auto-global unless configured)
- Thread pool for faster execution: `pool: 'threads'` in config

```javascript
import { vi, describe, it, expect } from 'vitest';
import { renderUserProfile } from './profile';

vi.mock('./api', () => ({
  fetchUser: vi.fn()
}));
```

### Async Testing
- Always `await` async assertions; un awaited assertions silently pass
- Use `resolves` / `rejects` matchers for Promise assertions
- `waitFor` from Testing Library for async DOM updates

```javascript
// Good: await async assertions
await expect(fetchData()).resolves.toEqual(expected);
await expect(invalidRequest()).rejects.toThrow('Bad Request');

// Good: waitFor for async state changes
await waitFor(() => {
  expect(screen.getByText('Loaded')).toBeInTheDocument();
});
```

## Assertion Styles

| Style | When to Use | Example |
|-------|-------------|---------|
| `toBe` | Primitive equality (===) | `expect(x).toBe(42)` |
| `toEqual` | Deep object equality | `expect(obj).toEqual({ a: 1 })` |
| `toStrictEqual` | Deep equality + type checking | `expect(arr).toStrictEqual([1, 2])` |
| `toContain` | Substring / array item | `expect(text).toContain('hello')` |
| `toMatchObject` | Partial object match | `expect(obj).toMatchObject({ id: 1 })` |
| `toHaveBeenCalledWith` | Mock call verification | `expect(fn).toHaveBeenCalledWith(arg)` |
| `toThrow` | Exception testing | `expect(() => fn()).toThrow('msg')` |

### Snapshot Testing
- Use for complex output (API responses, error messages, generated HTML)
- Update snapshots intentionally: `jest -u` / `vitest -u`
- Review snapshot diffs in PR review — they are code changes
- Use inline snapshots for small, readable assertions

```javascript
expect(complexResponse).toMatchInlineSnapshot(`
  {
    "data": [
      { "id": 1, "name": "Alice" }
    ],
    "total": 1
  }
`);
```

## Common Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| Un awaited async assertions | Tests pass when they should fail | Always `await expect(...).resolves/rejects` |
| `setTimeout` / `sleep` in tests | Flaky, slow tests | Use `waitFor`, `fakeTimers`, or mock timers |
| Mocking internals of tested module | Brittle tests tied to implementation | Mock dependencies, not internal functions |
| Global test state (module-level vars) | Test order dependency | Use `beforeEach` to reset state |
| `.only` / `.skip` left in committed code | Hidden test gaps | ESLint `no-focused-tests` / `no-skipped-tests` |
| Testing implementation not behavior | Brittle, low-value tests | Test inputs/outputs, not internal call order |
| Deeply nested `describe` blocks | Hard to follow, slow setup | Flatten structure; use descriptive test names |
| `console.log` in tests | Clutters CI output | Mock `console` methods or use a logger spy |

## Coverage Tool Recommendations

### Jest with built-in coverage
```bash
# Basic usage
jest --coverage --coverageReporters=text-summary --coverageReporters=html

# JSON output for programmatic consumption
jest --coverage --coverageReporters=json-summary

# Fail if coverage below threshold
jest --coverage --coverageThreshold='{"global":{"lines":70}}'

# Collect from specific files only
jest --coverage --collectCoverageFrom='src/**/*.ts'
```

### Vitest with coverage
```bash
# Using @vitest/coverage-v8 (recommended)
npx vitest --coverage --reporter=json

# Config in vitest.config.ts
export default defineConfig({
  test: {
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      thresholds: { lines: 70, branches: 60 },
      exclude: ['node_modules/', 'tests/']
    }
  }
});
```

### c8 (lightweight alternative for Node.js)
```bash
c8 --reporter=text --reporter=json-summary npm test
c8 --check-coverage --lines 70 npm test
```

## Key Testing Libraries

| Library | Purpose | Install |
|---------|---------|---------|
| `jest` / `vitest` | Test runner | `npm install --save-dev jest` / `vitest` |
| `@testing-library/jest-dom` | Custom DOM matchers | `npm install --save-dev @testing-library/jest-dom` |
| `msw` (Mock Service Worker) | HTTP request mocking | `npm install --save-dev msw` |
| `sinon` | Standalone mocks/spies/stubs | `npm install --save-dev sinon` |
| `@faker-js/faker` | Fake data generation | `npm install --save-dev @faker-js/faker` |
| `testcontainers` | Docker-based integration tests | `npm install --save-dev testcontainers` |
