# Fail-Closed Test Catalog

This document catalogs every failure mode the standalone policy engine must survive or fail-closed on. Each entry includes the test procedure, expected behavior, and automated validation commands.

**Definition**: *Fail-closed* means the policy engine and/or the orchestrator treats any error, unavailability, or ambiguity as a `DENY` decision. The system defaults to safe.

---

## Test Harness Prerequisites

All integration tests run against a containerized policy engine to provide process and filesystem isolation.

```bash
# Build test image
docker build -t policy-engine:test -f Dockerfile .

# Run test harness
make test-integration   # Executes all tests in this catalog
```

**Test Network**:
```
┌─────────────────────────────────────────┐
│  test-net (bridge)                      │
│  ├── policy-engine (container)          │
│  ├── orchestrator-mock (container)      │
│  └── test-harness (host / container)    │
└─────────────────────────────────────────┘
```

---

## TC-01: Service Crash / OOM Kill

**Failure**: The policy engine process is terminated abruptly (`SIGKILL`, OOM killer, segfault).

**Rationale**: The orchestrator must not assume the engine is healthy if it cannot be reached. A dead engine is a denied engine.

### Procedure

```bash
# 1. Start engine
TEST_PID=$(docker run -d \
  --name pe-crash \
  --network test-net \
  -v $(pwd)/configs:/etc/policy:ro \
  policy-engine:test \
  --manifest-path=/etc/policy/manifest.yaml \
  --listen=tcp://0.0.0.0:50051)

# 2. Wait for ready
docker run --rm --network test-net curlimages/curl \
  --retry 30 --retry-delay 1 --fail \
  http://pe-crash:8080/readyz

# 3. Send a request that should ALLOW (baseline)
grpcurl -plaintext pe-crash:50051 policy.v1.PolicyEngine/Evaluate \
  -d '{"principal":"user:admin","action":"skill:deploy","resource":"namespace:prod"}'
# Expected: decision=ALLOW

# 4. Abruptly kill the engine process
kill -9 $(docker inspect -f '{{.State.Pid}}' pe-crash)

# 5. Orchestrator mock attempts evaluation
docker run --rm --network test-net curlimages/curl \
  -X POST http://orchestrator-mock:9090/proxy-to-engine \
  -d '{...}' -w "%{http_code}" --connect-timeout 2
```

### Expected Result

| Actor | Observation |
|-------|-------------|
| Policy Engine | Process gone. Socket/connection closed. |
| Orchestrator | gRPC/HTTP dial fails with `connection refused` or `no such host`. |
| Final Decision | `DENY` (default action). |
| Audit Log | `decision=DENY, reason=engine_unavailable, error=connection_refused` |

### Validation

```bash
# Check orchestrator audit log
grep "engine_unavailable" /var/log/orchestrator/audit.log
# Must return at least one line with decision=DENY
```

### Automated Test Code (Go pseudocode)

```go
func TestCrashFailClosed(t *testing.T) {
    engine := startEngine(t, goodManifest)
    assertAllow(t, engine, adminDeployRequest)

    engine.Kill(syscall.SIGKILL)
    engine.Wait() // ensure actually dead

    resp := orchestratorMock.Evaluate(adminDeployRequest)
    assert.Equal(t, Decision_DENY, resp.Decision)
    assert.True(t, resp.DefaultAction)
    assert.Contains(t, resp.Reason, "engine_unavailable")
}
```

---

## TC-02: Unix Socket Disappearance

**Failure**: The Unix domain socket file is deleted by an external actor (host cleanup script, accidental `rm`, filesystem rollback).

**Rationale**: The orchestrator and engine are co-located. If the local socket vanishes, there is no alternative path; traffic must be blocked.

### Procedure

```bash
# 1. Start engine with Unix socket
TEST_CID=$(docker run -d \
  --name pe-socket \
  -v $(pwd)/configs:/etc/policy:ro \
  -v /run:/run \
  policy-engine:test \
  --manifest-path=/etc/policy/manifest.yaml \
  --listen=unix:///run/policy-engine.sock)

# 2. Verify socket exists and is responsive
ls -l /run/policy-engine.sock
# srw------- 1 root root 0 Jun 14 10:00 /run/policy-engine.sock

# 3. Baseline ALLOW request
grpcurl -unix -plaintext /run/policy-engine.sock policy.v1.PolicyEngine/Evaluate \
  -d '{"principal":"user:admin",...}'
# Expected: ALLOW

# 4. Delete the socket file from the host
rm -f /run/policy-engine.sock

# 5. Attempt evaluation via orchestrator
grpcurl -unix -plaintext /run/policy-engine.sock policy.v1.PolicyEngine/Evaluate ...
```

### Expected Result

| Actor | Observation |
|-------|-------------|
| Policy Engine | Process still running, but no socket. gRPC server may log errors. |
| Orchestrator | Dial fails with `connection refused` or `no such file or directory`. |
| Final Decision | `DENY` (default action). |

### Recovery

Engine must detect socket loss and either:
- (Option A) Exit non-zero so the supervisor restarts it, recreating the socket.
- (Option B) Recreate the socket automatically and re-accept traffic (if implemented, log `WARN`).

**Recommended**: Option A (fail-closed explicit) unless restart latency is unacceptable.

---

## TC-03: Manifest Corruption on Reload

**Failure**: A valid running engine receives `SIGHUP` to reload, but the new manifest on disk is corrupted or invalid.

**Rationale**: The engine must not break existing traffic while attempting to load a bad update. Old rules stay active.

### Procedure

```bash
# 1. Start engine with good manifest
ENGINE_CID=$(docker run -d \
  --name pe-reload \
  -v $(pwd)/configs:/etc/policy:ro \
  policy-engine:test \
  --manifest-path=/etc/policy/manifest.yaml \
  --listen=tcp://0.0.0.0:50051)

# 2. Baseline: good request ALLOWs
curl -X POST http://pe-reload:8080/v1/evaluate -d '{"principal":"user:admin",...}'

# 3. Corrupt the manifest on disk (from host, volume mount)
echo "not: valid {{{ yaml" > configs/manifest.yaml

# 4. Send SIGHUP
docker kill --signal=HUP pe-reload

# 5. Immediate re-evaluation (should still use old rules)
curl -X POST http://pe-reload:8080/v1/evaluate -d '{"principal":"user:admin",...}'

# 6. Check /readyz (must still be 200)
curl -f http://pe-reload:8080/readyz

# 7. Check logs for reload error
docker logs pe-reload | grep "reload_error"
```

### Expected Result

| Step | Expected |
|------|----------|
| 5 | Decision `ALLOW` (old rules still active). |
| 6 | `HTTP 200` — readiness unaffected. |
| 7 | Log line present: `reload_error: yaml parse error at line 1`. |

**What must NOT happen**:
- The engine must not unload old rules before new rules are validated.
- The engine must not crash or become unready.
- The engine must not serve a mix of old and new rules.

### Validation

```bash
assert_equal "ALLOW" "$(evaluate_old_request)"
assert_equal "200" "$(curl -s -o /dev/null -w '%{http_code}' http://pe-reload:8080/readyz)"
assert_not_empty "$(docker logs pe-reload | grep reload_error)"
```

---

## TC-04: Rule Syntax Error at Startup

**Failure**: The manifest contains a rule with a syntax error in its source (e.g., invalid Rego, malformed CEL).

**Rationale**: The engine must never start with partially-validated rules. If any rule is broken, the entire bootstrap fails.

### Procedure

```bash
# 1. Prepare manifest with bad Rego
cat > /tmp/bad-manifest.yaml <<'EOF'
apiVersion: policy.engine/v1
kind: PolicyManifest
metadata:
  name: bad-policy
  version: "1.0.0"
spec:
  defaultDecision: deny
  rules:
    - name: broken-rule
      match:
        action: "skill:*"
      engine: rego
      source: |
        package broken
        allow { input.this_does_not_exist = 1 }  # syntax error: invalid operator
EOF

# 2. Sign it (or use --insecure-skip-verify for test harness)

# 3. Attempt to start engine
set +e
docker run --rm \
  -v /tmp/bad-manifest.yaml:/etc/policy/manifest.yaml:ro \
  policy-engine:test \
  --manifest-path=/etc/policy/manifest.yaml \
  --listen=tcp://0.0.0.0:50051
EXIT_CODE=$?
set -e
```

### Expected Result

| Observation | Value |
|-------------|-------|
| Exit code | `2` (or non-zero) |
| `/readyz` | Never served; process exits before binding ports. |
| Orchestrator | Init container fails; orchestrator never starts. |
| Audit log | No entries because engine never accepted traffic. |

### Kubernetes Context

```
Init container 'policy-engine-ready' restarts → CrashLoopBackOff
Pod 'orchestrator' never reaches Running
```

This is the **correct** fail-closed behavior: a bad policy prevents the system from serving traffic.

---

## TC-05: Signature Verification Failure at Startup

**Failure**: The manifest has been tampered with after signing, or the wrong public key is configured.

**Rationale**: A tampered manifest must not be trusted. The engine must refuse to start.

### Procedure

```bash
# 1. Start with valid signed manifest
# 2. Flip a single bit in the manifest file
printf '\x00' | dd of=/etc/policy/manifest.yaml bs=1 seek=100 count=1 conv=notrunc

# 3. Attempt to start engine
```

### Expected Result

- Exit code `2`.
- Log: `signature verification failed: ed25519 verification error`.
- Engine does not bind any port.

### Alternative: Wrong Public Key

```bash
# Use a completely different key pair
openssl genpkey -algorithm Ed25519 -out /tmp/wrong.pem
# Start engine with --pubkey-path=/tmp/wrong.pem
```

Same expected result: exit code `2`.

---

## TC-06: gRPC Timeout / Deadline Exceeded

**Failure**: The network or engine is slow, and the orchestrator's gRPC context deadline is reached before the engine responds.

**Rationale**: An unresponsive engine is an untrusted engine. The orchestrator must not wait forever.

### Procedure

```bash
# 1. Start engine with a rule that sleeps for 2 seconds
#    (Injected via WASM or a deliberately slow CEL extension)

# 2. Send request with 10ms timeout
grpcurl -plaintext -d '{"principal":"user:slow",...}' \
  -rpc-header "Grpc-Timeout: 10m" \
  pe:50051 policy.v1.PolicyEngine/Evaluate
```

Or via client code:
```go
ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
defer cancel()
resp, err := client.Evaluate(ctx, req)
```

### Expected Result

| Observation | Value |
|-------------|-------|
| gRPC status | `DEADLINE_EXCEEDED` |
| HTTP equivalent | `504 Gateway Timeout` (if via reverse proxy) |
| Orchestrator decision | `DENY` |
| Response reason | `evaluation_timeout` |
| `default_action` | `true` |

### Validation

```go
assert.Equal(t, codes.DeadlineExceeded, status.Code(err))
assert.Equal(t, Decision_DENY, resp.Decision)
```

---

## TC-07: Rule Evaluation Timeout (Infinite Loop)

**Failure**: A rule contains logic that runs indefinitely (infinite recursion, unbounded loop in WASM).

**Rationale**: The engine must protect itself from bad rules. A single bad rule must not stall the entire evaluator.

### Procedure

```yaml
# Manifest with infinite-loop rule
rules:
  - name: infinite-loop
    match:
      action: "skill:hang"
    engine: rego
    source: |
      package hang
      allow { allow }  # infinite recursion
```

```bash
# 1. Start engine with this manifest (it will pass syntax check but fail at runtime)
# 2. Send matching request
curl -X POST http://pe:8080/v1/evaluate -d '{"action":"skill:hang"}'
```

### Expected Result

| Observation | Value |
|-------------|-------|
| Engine behavior | Canceled after `--eval-timeout` (default 500ms). |
| Decision | `DENY` |
| Engine health | `/healthz` still `200`; engine remains alive. |
| Log | `rule_timeout rule=infinite-loop duration_ms=500 canceled=true` |

**Note**: Rego OPA and CEL both support query cancellation via `context.Context`. The engine must pass a deadline to every rule evaluation.

---

## TC-08: Partial Rule Engine Panic

**Failure**: A rule triggers a panic inside the rule engine (e.g., nil pointer in WASM runtime, bug in Rego built-in).

**Rationale**: One bad rule must not crash the entire service. All other rules must remain usable.

### Procedure

```yaml
# Manifest with panic rule (injected via WASM or test build tag)
rules:
  - name: panic-rule
    match:
      action: "skill:panic"
    engine: rego
    source: |
      package panic
      # In a test build, a custom built-in is registered that panics
      allow { panic() }
```

```bash
# 1. Send request matching panic rule
curl -X POST http://pe:8080/v1/evaluate -d '{"action":"skill:panic"}'

# 2. Immediately send request matching a normal rule
curl -X POST http://pe:8080/v1/evaluate -d '{"action":"skill:deploy"}'
```

### Expected Result

| Request | Expected |
|---------|----------|
| `skill:panic` | `DENY`, `default_action=true`, reason contains `evaluation_panic` |
| `skill:deploy` | Normal evaluation per manifest rules |

| Probe | Expected |
|-------|----------|
| `/healthz` | `200` — service did not crash |
| `/readyz` | `200` — still serving |

### Implementation Requirement

The engine must wrap every rule evaluation in `recover()`:

```go
func safeEvaluate(ctx context.Context, rule Rule, input Input) (Decision, error) {
    defer func() {
        if r := recover(); r != nil {
            log.Error("rule panic recovered", "rule", rule.Name, "panic", r)
            // Return DENY via out-parameter or channel
        }
    }()
    return rule.Evaluate(ctx, input)
}
```

---

## TC-09: Reload Success (Zero-Downtime)

**Failure**: Not a failure, but the positive control proving that normal reload works without breaking traffic.

### Procedure

```bash
# 1. Start engine with manifest v1 (allows skill:deploy)
# 2. Continuously send requests in a loop (5 req/sec)
# 3. While loop runs, atomically replace manifest with v2 (allows skill:deploy AND skill:delete)
# 4. Send SIGHUP
# 5. Continue loop for 10 seconds
```

### Expected Result

- Zero requests return `DENY` due to engine unavailability.
- After reload, `skill:delete` requests return `ALLOW`.
- `/readyz` never returns `503` during swap.
- No error logs about dropped connections.

### Metrics to Assert

```
policy_evaluations_total{decision="allow"} increases monotonically
policy_engine_reloads_total{status="success"} = 1
policy_engine_reloads_total{status="failure"} = 0
```

---

## TC-10: Manifest File Permission Escalation

**Failure**: An attacker modifies manifest permissions to make it writable by non-owner.

**Rationale**: Although the engine reads the manifest, an observable permission change signals tampering risk.

### Procedure

```bash
chmod 666 /etc/policy/manifest.yaml
# Start engine with --strict-perms
```

### Expected Result (if `--strict-perms` is enabled)

- Exit code `2`.
- Log: `manifest permissions too permissive: 0666, expected 0400 or 0444`.

---

## TC-11: Public Key Rotation Mismatch

**Failure**: The manifest is signed with a new key, but the engine still has the old public key.

### Procedure

```bash
# Sign manifest with key-v2
# Engine configured with --pubkey-path=/etc/policy/key-v1.pub
```

### Expected Result

- Exit code `2`.
- Log: `signature verification failed: key mismatch`.
- Operator must update `--pubkey-path` and restart engine.

---

## Test Execution Matrix

| ID | Test | Container | Host Interaction | Duration | Automated |
|----|------|-----------|-----------------|----------|-----------|
| TC-01 | Crash / OOM | Yes | `kill -9` | 10s | Yes |
| TC-02 | Socket loss | Yes | `rm` socket | 10s | Yes |
| TC-03 | Manifest corruption reload | Yes | File write + `kill -HUP` | 15s | Yes |
| TC-04 | Syntax error startup | Yes | None | 5s | Yes |
| TC-05 | Signature failure startup | Yes | File modify | 5s | Yes |
| TC-06 | gRPC timeout | Yes | Network proxy | 10s | Yes |
| TC-07 | Rule evaluation timeout | Yes | None | 10s | Yes |
| TC-08 | Rule panic recovery | Yes | None | 10s | Yes |
| TC-09 | Reload success | Yes | File swap + `kill -HUP` | 20s | Yes |
| TC-10 | Permission escalation | Yes | `chmod` | 5s | Yes |
| TC-11 | Key rotation mismatch | Yes | Key swap | 5s | Yes |

Run individual tests:

```bash
go test ./tests/integration -run TestCrashFailClosed -v
go test ./tests/integration -run TestSocketDisappearance -v
go test ./tests/integration -run TestManifestCorruptionReload -v
go test ./tests/integration -run TestSyntaxErrorStartup -v
go test ./tests/integration -run TestSignatureFailureStartup -v
go test ./tests/integration -run TestGRPCTimeout -v
go test ./tests/integration -run TestRuleEvaluationTimeout -v
go test ./tests/integration -run TestRulePanicRecovery -v
go test ./tests/integration -run TestReloadSuccess -v
go test ./tests/integration -run TestPermissionEscalation -v
go test ./tests/integration -run TestKeyRotationMismatch -v
```

---

## CI Integration

All tests run in CI with race detection and coverage:

```yaml
# .github/workflows/ci.yml (excerpt)
- name: Integration Tests
  run: |
    make test-integration
  env:
    POLICY_ENGINE_IMAGE: policy-engine:test
    TEST_TIMEOUT: 120s
```

**Coverage Requirement**: Integration tests must exercise the `failclosed` package recovery paths. `go test -cover` on the integration suite should report >60% coverage of `internal/failclosed/`.
