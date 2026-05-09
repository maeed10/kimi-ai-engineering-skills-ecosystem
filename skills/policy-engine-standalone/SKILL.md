---
name: policy-engine-standalone
description: Extracts policy-engine into a standalone auditable service with its own repository, CI pipeline, and proven fail-closed guarantees. Use when decoupling policy enforcement from the orchestrator, designing bootstrap sequences, or testing failure modes. Includes readiness probes, bootstrap validation, and simulated failure tests.
---

# policy-engine-standalone

A standalone, auditable, single-purpose policy engine service with its own repository, test suite, CI pipeline, and proven **fail-closed** guarantees under all failure conditions.

## Problem Statement

The entire safety model is currently documentation. The policy engine must exist as running, independently testable code. This skill extracts the `policy-engine` from a monolithic skill ecosystem into a decoupled service that can be audited, tested, and deployed independently.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Policy Engine                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │  gRPC Server    │  │  REST Server    │  │  Bootstrap Controller    │  │
│  │  :50051         │  │  :8080          │  │                          │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬─────────────┘  │
│           │                    │                        │                │
│           └────────────────────┴────────────────────────┘                │
│                              │                                          │
│                    ┌─────────▼──────────┐                               │
│                    │   Core Validator   │                               │
│                    │   (fail-closed)    │                               │
│                    └─────────┬──────────┘                               │
│           ┌──────────────────┼──────────────────┐                      │
│  ┌────────▼────────┐ ┌───────▼───────┐ ┌────────▼────────┐             │
│  │ Manifest Loader │ │ Rule Engine   │ │ Sig Verify      │             │
│  │ (YAML/JSON)     │ │ (Rego/CEL/WASM│ │ (cosign/gpg)    │             │
│  └─────────────────┘ └───────────────┘ └─────────────────┘             │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      Health & Readiness                          │   │
│  │  /healthz (liveness)  /readyz (readiness)  /metrics (prom)    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
    ┌─────────▼─────────┐ ┌────────▼────────┐ ┌────────▼────────┐
    │   Orchestrator    │ │   CI / Test     │ │   Admin CLI     │
    │   (client)        │ │   Harness       │ │   (ops)         │
    └───────────────────┘ └─────────────────┘ └─────────────────┘
```

### Design Principles

1. **Standalone Binary**: The policy engine is a single binary/service, NOT embedded in the orchestrator.
2. **Unix Socket Preferred**: Local deployments use Unix domain sockets for zero-overhead, file-system-mediated availability.
3. **Fail-Closed by Default**: Any error, crash, or unreachable state results in `DENY`.
4. **Bootstrap Before Serve**: No traffic is accepted until the manifest is loaded, signatures verified, and all rules validated.
5. **Independent Repository**: Own git repo, CI pipeline, release cycle, and versioning.

## Bootstrap Sequence

The policy engine follows a strict bootstrap sequence. Until completion, all probes report unhealthy and the orchestrator must not accept traffic.

```
┌─────────┐    ┌──────────────┐    ┌───────────────┐    ┌────────────┐
│  START  │───>│ Load Config  │───>│ Load Manifest │───>│  Verify    │
└─────────┘    └──────────────┘    └───────────────┘    │ Signatures │
                                                         └─────┬──────┘
                                                               │
    ┌──────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌─────────┐
│ Validate All │───>│ Compile Rules│───>│ Report Ready │───>│ ACCEPT  │
│ Rules        │    │ (Warm Cache) │    │ (/readyz UP) │    │ TRAFFIC │
└──────────────┘    └──────────────┘    └──────────────┘    └─────────┘
```

### Step-by-Step

| Step | Action | Failure Mode | Fail-Closed Behavior |
|------|--------|--------------|---------------------|
| 1 | Parse CLI flags / env vars | Invalid config | Exit non-zero, orchestrator init container fails |
| 2 | Load manifest from `--manifest-path` | File missing, unreadable | Exit non-zero |
| 3 | Verify manifest signatures | Invalid signature, key missing | Exit non-zero |
| 4 | Parse manifest YAML/JSON | Corrupted syntax | Exit non-zero |
| 5 | Validate each rule's syntax | Rego parse error, CEL type error | Exit non-zero |
| 6 | Compile rules into evaluation cache | Compilation failure | Exit non-zero |
| 7 | Run a self-test query against each rule | Self-test failure | Exit non-zero |
| 8 | Mark `/readyz` probe as `UP` | — | Traffic now accepted |

**Readiness Probe Contract**:
- **HTTP**: `GET /readyz` returns `200 OK` with body `{"status":"ready","rules_loaded":N}`
- **gRPC**: `CheckReady` returns `status = SERVING`
- **Unix Socket**: Socket file exists and responds to `SO_ERROR` with `0`

## Fail-Closed Guarantees

The policy engine is **fail-closed** (default-deny). Under every failure condition, the answer is `DENY`.

### Failure Mode Matrix

| Failure | Orchestrator Behavior | Policy Engine Response | Proof Test |
|---------|----------------------|------------------------|------------|
| Service crash / OOM | Request fails | `DENY` (no connection) | `kill -9` on PID, verify orchestrator blocks |
| Unix socket disappearance | Cannot dial | `DENY` (connection refused) | `rm /run/policy-engine.sock`, verify blocks |
| Manifest corruption on reload | Reload rejected, old rules retained | `DENY` for new rules, old rules continue | Corrupt manifest, send SIGHUP, verify `DENY` on new requests |
| Rule syntax error in manifest | Bootstrap halts at step 5 | Service exits non-zero, orchestrator init container fails | Start with bad Rego, verify exit code != 0 |
| Signature verification failure | Bootstrap halts at step 3 | Service exits non-zero | Tamper with manifest, verify exit code != 0 |
| gRPC timeout | Deadline exceeded | `DENY` | Set 1ms timeout, verify `DENY` |
| Rule evaluation timeout | Context deadline exceeded | `DENY` | Infinite loop rule, verify `DENY` |
| Partial rule engine crash | Panic in one rule | `DENY` overall, service stays up | Inject panic rule, verify `DENY` + service alive |

### Reload Behavior

Sending `SIGHUP` triggers a zero-downtime reload:

1. Load new manifest alongside old manifest.
2. Validate and compile new rules in a shadow evaluator.
3. If any step fails, log error, discard new rules, **keep old rules active**.
4. If all steps pass, atomically swap evaluator pointers.
5. Old evaluator garbage-collected after in-flight requests complete.

## API Specification

### gRPC (Primary)

```protobuf
syntax = "proto3";
package policy.v1;

service PolicyEngine {
  // Evaluate a single request against all matching rules.
  rpc Evaluate(EvaluateRequest) returns (EvaluateResponse);

  // Stream evaluations for batch processing.
  rpc EvaluateStream(stream EvaluateRequest) returns (stream EvaluateResponse);

  // Health and readiness.
  rpc CheckReady(ReadyRequest) returns (ReadyResponse);
}

message EvaluateRequest {
  string request_id = 1;
  string principal = 2;     // e.g., "user:alice"
  string action = 3;      // e.g., "skill:deploy"
  string resource = 4;      // e.g., "namespace:prod"
  map<string, string> context = 5;  // additional context key/value
}

message EvaluateResponse {
  enum Decision {
    DECISION_UNSPECIFIED = 0;  // treated as DENY
    ALLOW = 1;
    DENY = 2;
  }
  Decision decision = 1;
  string request_id = 2;
  repeated string matched_rules = 3;
  string reason = 4;         // human-readable explanation
  bool default_action = 5;   // true if DENY was due to fail-closed
}

message ReadyRequest {}

message ReadyResponse {
  enum Status {
    STATUS_UNSPECIFIED = 0;
    SERVING = 1;
    NOT_SERVING = 2;
  }
  Status status = 1;
  int32 rules_loaded = 2;
  string manifest_version = 3;
}
```

### REST (Fallback / Debug)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/evaluate` | Evaluate a single request (JSON body matching `EvaluateRequest`) |
| GET | `/healthz` | Liveness probe — returns `200` as long as process is up |
| GET | `/readyz` | Readiness probe — returns `200` only after bootstrap complete |
| GET | `/metrics` | Prometheus metrics: `policy_evaluations_total`, `policy_evaluation_duration_seconds`, `policy_rules_loaded` |

### Fail-Closed HTTP Status Codes

| Condition | HTTP Status | gRPC Status | Decision |
|-----------|-------------|-------------|----------|
| Service not ready | `503` | `UNAVAILABLE` | `DENY` |
| Request timeout | `504` | `DEADLINE_EXCEEDED` | `DENY` |
| Invalid request | `400` | `INVALID_ARGUMENT` | `DENY` |
| Internal error | `500` | `INTERNAL` | `DENY` |
| Rule evaluation panic | `500` | `INTERNAL` | `DENY` |

## Repository Layout

```
policy-engine/
├── cmd/
│   └── policy-engine/
│       └── main.go
├── internal/
│   ├── bootstrap/
│   │   ├── bootstrap.go          # Step 1-7 orchestration
│   │   └── bootstrap_test.go     # Unit tests for each phase
│   ├── engine/
│   │   ├── engine.go             # Core evaluator
│   │   ├── rego.go               # Rego rule backend
│   │   ├── cel.go                # CEL rule backend
│   │   └── engine_test.go        # Table-driven evaluation tests
│   ├── manifest/
│   │   ├── loader.go             # YAML/JSON manifest parser
│   │   ├── verifier.go           # Signature verification
│   │   └── loader_test.go        # Corruption tests
│   ├── server/
│   │   ├── grpc.go               # gRPC server
│   │   ├── http.go               # REST server
│   │   └── probes.go             # /healthz, /readyz, /metrics
│   └── failclosed/
│       ├── failclosed.go         # Default-deny wrapper
│       └── recover.go            # Panic recovery -> DENY
├── api/
│   └── policy/v1/policy.proto
├── configs/
│   └── example-manifest.yaml
├── scripts/
│   └── bootstrap_check.sh        # External readiness validator
├── tests/
│   ├── integration/
│   │   ├── crash_test.go         # kill -9 simulation
│   │   ├── socket_loss_test.go   # Unix socket disappearance
│   │   ├── manifest_reload_test.go # Corruption on SIGHUP
│   │   └── syntax_error_test.go  # Bad rule at startup
│   └── harness/
│       └── harness.go            # Shared test fixtures
├── .github/
│   └── workflows/
│       ├── ci.yml                # Unit + integration tests
│       └── release.yml           # Binary + container build
├── go.mod
├── Dockerfile
└── README.md
```

## CI Pipeline

### Required Checks

1. **Unit Tests** (`go test ./...`): Must cover `bootstrap`, `engine`, `manifest`, `failclosed` packages with >80% coverage.
2. **Integration Tests** (`go test ./tests/integration/...`): Must run all failure modes in isolated Docker containers.
3. **Lint & Vet** (`golangci-lint`, `go vet`): Zero warnings tolerated.
4. **Build** (`go build`, `docker build`): Multi-arch build for `linux/amd64`, `linux/arm64`.
5. **Static Analysis** (`gosec`, `semgrep`): Security-focused scanning.

### Release Cycle

- Versioned independently from orchestrator: `policy-engine/v1.2.3`.
- Container image: `ghcr.io/org/policy-engine:v1.2.3`.
- Helm chart subchart version pinned in orchestrator repo.

## Integration Test Matrix

All tests must be automated and runnable with `make test-integration`.

| Test | Setup | Action | Expected Result | Validation |
|------|-------|--------|-----------------|------------|
| Crash | `docker run` with PID 1, inject client request | `kill -9 <pid>` inside container | Client receives connection error, orchestrator treats as `DENY` | Check orchestrator audit log for `decision=DENY, reason=engine_unavailable` |
| Socket Loss | Start with `--socket=/run/pe.sock`, healthy client | `rm /run/pe.sock` from host | Next client dial fails, `DENY` | Client error matches `connection refused` |
| Manifest Corruption | Start with valid manifest, send `SIGHUP` | Replace manifest with malformed YAML | Service logs reload error, keeps old rules, `/readyz` stays `200` | Evaluate old request → still `ALLOW`; new request needing new rule → uses old rule set |
| Syntax Error | Place invalid Rego in manifest directory | Start service | Process exits with code `2` before binding port | Init container fails, orchestrator never reaches `Ready` |
| Signature Failure | Tamper with manifest bytes after signing | Start service | Exit code `2`, log shows `signature verification failed` | Init container fails |
| gRPC Timeout | Healthy engine, slow rule (1s sleep) | Client sets `timeout=10ms` | `DEADLINE_EXCEEDED`, decision `DENY` | Response `default_action=true` |
| Rule Panic | Healthy engine, rule with `panic("injected")` | Send matching request | Service stays alive, single request gets `DENY` | `/healthz` still `200`; subsequent requests succeed |
| Reload Success | Healthy engine, valid updated manifest | Send `SIGHUP` | Zero-downtime swap, new rules active | Request matching new rule evaluates correctly; old in-flight requests complete without error |

## Orchestrator Integration

### systemd Unit

```ini
[Unit]
Description=Policy Engine
After=network.target
Before=orchestrator.service

[Service]
Type=notify
ExecStart=/usr/local/bin/policy-engine --manifest-path=/etc/policy/manifest.yaml --socket=/run/policy-engine.sock
ExecStartPre=/usr/local/bin/policy-engine --validate-only --manifest-path=/etc/policy/manifest.yaml
Restart=on-failure
RestartSec=5
NotifyAccess=all

[Install]
WantedBy=multi-user.target
```

### Kubernetes

```yaml
# Init container ensures policy-engine ready before orchestrator starts
initContainers:
  - name: policy-engine-ready
    image: busybox:1.36
    command:
      - sh
      - -c
      - |
        until wget -qO- http://policy-engine:8080/readyz | grep -q '"status":"ready"'; do
          echo "Waiting for policy engine..."
          sleep 1
        done
    resources:
      limits:
        cpu: 100m
        memory: 64Mi

containers:
  - name: policy-engine
    image: ghcr.io/org/policy-engine:v1.2.3
    ports:
      - containerPort: 8080
        name: http
      - containerPort: 50051
        name: grpc
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /readyz
        port: 8080
      initialDelaySeconds: 2
      periodSeconds: 5
      failureThreshold: 30  # 150s max for manifest loading
```

## Quick Start

```bash
# 1. Build
go build -o policy-engine ./cmd/policy-engine

# 2. Validate manifest (dry-run)
./policy-engine --validate-only --manifest-path=./configs/example-manifest.yaml

# 3. Start service
./policy-engine --manifest-path=./configs/example-manifest.yaml --socket=/run/policy-engine.sock

# 4. Check readiness
./scripts/bootstrap_check.sh /run/policy-engine.sock

# 5. Evaluate (grpcurl)
grpcurl -unix -plaintext /run/policy-engine.sock policy.v1.PolicyEngine/CheckReady

# 6. Run all failure mode tests
make test-integration
```

## Security Considerations

- **Manifest immutability**: Manifest file should be on a read-only mount (`ro` in Kubernetes, `ReadOnlyDirectories` in systemd).
- **Signature chain**: Manifest must be signed at build time; the engine only verifies, never signs.
- **No dynamic code loading**: Rules are compiled at bootstrap; no runtime `eval()` or plugin loading.
- **Least privilege**: Service runs as non-root, with only `CAP_NET_BIND_SERVICE` if binding low ports.

## Operational Runbooks

### Policy Engine Fails to Start

1. Check init container logs: `kubectl logs pod/orchestrator-xxx -c policy-engine-ready`
2. Verify manifest signature: `./policy-engine --validate-only --manifest-path=/etc/policy/manifest.yaml`
3. Check manifest syntax: `yamllint /etc/policy/manifest.yaml`
4. Review rule compilation errors in service logs.

### Policy Engine Reload Fails

1. Check service logs for `reload_error` metric or log line.
2. Old rules remain active — service is still healthy.
3. Fix manifest, re-send `SIGHUP`, verify `policy_rules_loaded` metric increases.

### Need Emergency Deny-All

1. Replace manifest with empty `deny_all` rule set.
2. Send `SIGHUP`.
3. All evaluations return `DENY`.
4. If engine is down entirely, orchestrator already fails closed by default.
