# API Contract Tester — Contract Patterns & Reference

Extended reference for contract testing tools, patterns, environment setup, and fuzzing authorization.

---

## Pact Implementation Reference

### Consumer Test Phase

1. Consumer writes unit test defining expected request/response
2. Pact starts mock provider based on contract
3. Consumer code makes real request to mock
4. Mock compares actual vs. expected request
5. Consumer test confirms response handled correctly
6. Pact generates JSON contract file

### Provider Verification Phase

1. Provider test loads pact file(s)
2. `@TestTemplate` with `PactVerificationInvocationContextProvider` verifies each interaction
3. Real provider API receives requests from pact file
4. Responses compared against expected
5. Provider states set up test data preconditions

### Pact Broker Integration

- Central contract repository for tracking versions and compatibility
- Webhooks notify providers of new contracts
- `can-i-deploy` blocks deployments of incompatible versions
- Auto-generated documentation and network diagrams

### `can-i-deploy` Gate

```bash
# Check if consumer can deploy given current provider versions
pact-broker can-i-deploy \
  --pacticipant ConsumerService \
  --version $GIT_COMMIT \
  --to-environment production
```

Run in CI before deployment. Block on failure. No manual overrides without documented justification.

---

## Schemathesis Configuration

### CLI Invocation

```bash
# Basic spec compliance
schemathesis run openapi.yaml --base-url http://localhost:3000

# With auth and stateful testing
schemathesis run openapi.yaml \
  --base-url http://localhost:3000 \
  -H "Authorization: Bearer ${TOKEN}" \
  --stateful=links \
  --hypothesis-seed=42 \
  --junit-xml=report.xml

# Fuzz testing with custom data generation
schemathesis run openapi.yaml \
  --base-url http://localhost:3000 \
  --data-generation-method=all
```

### Pytest Integration

```python
import schemathesis

schema = schemathesis.from_path("openapi.yaml")

@schema.parametrize()
def test_api(case):
    case.call_and_validate()
```

### Hooks for Setup/Teardown

```python
import schemathesis

@schemathesis.hook
def after_init_cli(ctx):
    # Obtain auth token before test run
    ctx.config.headers["Authorization"] = f"Bearer {get_test_token()}"

@schemathesis.hook
def after_call(ctx, case, response):
    # Clean up created resources
    if response.status_code == 201 and "id" in response.json():
        cleanup_resource(response.json()["id"])
```

---

## HAR-to-Test Conversion Patterns

### vcrpy Pattern (Python)

```python
import vcr
import requests

my_vcr = vcr.VCR(
    cassette_library_dir='fixtures/cassettes',
    record_mode='once',
    filter_headers=['authorization', 'cookie'],
    filter_post_data_parameters=['password', 'token']
)

@my_vcr.use_cassette('api_get_user.yml')
def test_get_user():
    response = requests.get('http://api/users/123')
    assert response.status_code == 200
    assert response.json()['id'] == 123
```

### Playwright Pattern (Node.js)

```javascript
import { test, expect } from '@playwright/test';

test('API contract via HAR replay', async ({ page }) => {
  await page.routeFromHAR('fixtures/api.har', {
    url: '**/api/**',
    update: false
  });
  const response = await page.request.get('/api/users/123');
  expect(response.status()).toBe(200);
});
```

### Redaction Checklist

- [ ] Authorization headers removed or masked
- [ ] Cookie values replaced with placeholders
- [ ] Email addresses replaced with `user@example.com`
- [ ] Phone numbers replaced with `+1-555-0100`
- [ ] Credit card numbers removed entirely
- [ ] Internal hostnames/IP addresses replaced
- [ ] Stack traces in error responses truncated
- [ ] UUIDs/timestamps in URLs handled with matchers

---

## Mock Server Setup Reference

### Prism (Stoplight)

```bash
# Generate mock server from OpenAPI spec
prism mock openapi.yaml --port 4010

# Proxy mode: compare spec against live implementation
prism proxy openapi.yaml http://localhost:3000 --port 4010
```

### Mockoon (CLI)

```bash
# Run mock server from data file
mockoon-cli start --data ./mockoon.json --port 3001
```

### MSW (Browser/Node)

```javascript
import { rest } from 'msw';
import { setupServer } from 'msw/node';

const server = setupServer(
  rest.get('/api/users/:id', (req, res, ctx) => {
    return res(ctx.json({ id: req.params.id, name: 'Test User' }));
  })
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

---

## Fuzzing Authorization Protocol

### Required Documentation for Production Fuzzing

1. **Risk Assessment** — Documented analysis of side effects, data mutation risk, and DoS potential
2. **Scope Definition** — Exact endpoints, methods, and parameter sets approved for fuzzing
3. **Time Window** — Scheduled maintenance window with stakeholder notification
4. **Rate Limit** — Maximum requests/minute with circuit breaker
5. **Monitoring** — Real-time dashboard with abort capability
6. **Rollback Plan** — Steps to halt fuzzing and restore service if degradation detected
7. **Data Sanitization** — Confirmation that no production PII is present in test data
8. **Sign-off** — Written authorization from API owner and security team

### Fuzzing Safety Checklist (Pre-Flight)

- [ ] Target environment confirmed as isolated (not production)
- [ ] Rate limiting configured and tested
- [ ] Auth tokens scoped to test environment only
- [ ] Log redaction verified (no tokens or PII in output)
- [ ] Abort command tested and ready
- [ ] Stakeholders notified of fuzzing window
- [ ] Monitoring dashboard active
- [ ] Rollback procedure documented

---

## API Versioning Decision Tree

```
Is the change breaking?
  ├── YES → Major version bump required
  │         ├── New path: /api/v{new}/...
  │         ├── Deprecation notice (6-12 months)
  │         ├── Migration guide published
  │         └── oasdiff breaking check in CI
  └── NO → Minor or patch
            ├── Additive only: new optional fields, new endpoints
            ├── oasdiff changelog check
            └── Document in release notes
```

### Stripe Hybrid Model

- Evolution strategy for most changes: single version, non-breaking additive changes
- Explicit versioning only for breaking changes
- Consumers opt into breaking changes via API version header
- Maintains backward compatibility for all existing integrations

---

## Environment Isolation Matrix

| Environment | Live Data | Auth Scope | Fuzzing Allowed | Contract Testing | Notes |
|-------------|-----------|------------|---------------|------------------|-------|
| Local Dev | Synthetic | Test-only | Yes | Mock + Live | Developer workstation |
| CI / Test | Synthetic | Test-only | Yes | Mock + Replay | Ephemeral, isolated |
| Staging | Anonymized | Test-only | With approval | Live + Mock | Shared, schedule load tests |
| Production | Real | Production | NEVER | Read-only health only | NEVER fuzz, NEVER write test data |

---

## CI/CD Integration Reference

### GitHub Actions: Contract Test Pipeline

```yaml
name: Contract Tests
on: [pull_request]
jobs:
  contract-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Schemathesis
        run: schemathesis run openapi.yaml --base-url http://localhost:3000
      - name: Run oasdiff
        run: oasdiff breaking base.yaml revision.yaml
      - name: Run Pact Verification
        run: mvn test -P pact-verification
      - name: Upload JUnit Report
        uses: actions/upload-artifact@v4
        with:
          name: contract-test-results
          path: reports/
```

### Pre-Deployment Gate

```yaml
- name: can-i-deploy check
  run: |
    pact-broker can-i-deploy \
      --pacticipant MyService \
      --version ${{ github.sha }} \
      --to-environment production
```

Block deployment on failure. Require manual override with ticket reference.

---

**Reference version:** 1.0 | **Last updated:** April 2026
