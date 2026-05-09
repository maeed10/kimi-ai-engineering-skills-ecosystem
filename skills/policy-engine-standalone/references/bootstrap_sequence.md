# Bootstrap Sequence and Health Checks

This document describes the exact bootstrap sequence that the standalone policy engine must execute before it reports healthy and accepts validation requests. Any deviation or failure at any step results in a fail-closed state: the service exits non-zero and the orchestrator must not accept traffic.

## Sequence Overview

```
START
  |
  v
[1] Load Configuration (env + flags)
  |
  v
[2] Acquire Resources (socket, ports, locks)
  |
  v
[3] Load Manifest from Disk
  |
  v
[4] Verify Manifest Signatures
  |
  v
[5] Parse Manifest Structure
  |
  v
[6] Validate Rule Syntax
  |
  v
[7] Compile Rules into Evaluator
  |
  v
[8] Execute Self-Test Queries
  |
  v
[9] Mark Ready and Accept Traffic
```

---

## Step 1: Load Configuration

**Purpose**: Resolve all runtime parameters before allocating resources.

**Inputs**:
- CLI flags (highest priority)
- Environment variables
- Defaults compiled into binary (lowest priority)

**Required Parameters**:

| Parameter | Flag | Env Var | Default | Validation |
|-----------|------|---------|---------|------------|
| Manifest path | `--manifest-path` | `POLICY_MANIFEST_PATH` | `/etc/policy/manifest.yaml` | Must be absolute path, file must exist at startup |
| Public key path | `--pubkey-path` | `POLICY_PUBKEY_PATH` | `/etc/policy/pubkey.pem` | Must be absolute path, file must exist |
| Listen address | `--listen` | `POLICY_LISTEN` | `unix:///run/policy-engine.sock` | Must be valid TCP `:PORT` or Unix `unix://PATH` |
| HTTP port | `--http-port` | `POLICY_HTTP_PORT` | `8080` | Valid port number, 0-65535 |
| gRPC port | `--grpc-port` | `POLICY_GRPC_PORT` | `50051` | Valid port number, 0-65535 |
| Evaluation timeout | `--eval-timeout` | `POLICY_EVAL_TIMEOUT` | `500ms` | Parsable duration, >0 |
| Rule engine | `--engine` | `POLICY_ENGINE` | `rego` | One of: `rego`, `cel`, `wasm` |

**Validation Rules**:
- If `--manifest-path` is not readable, log `FATAL` and exit code `2`.
- If `--pubkey-path` is not readable, log `FATAL` and exit code `2`.
- If both `--listen` (Unix) and `--http-port`/`--grpc-port` (TCP) are specified, Unix takes precedence for local deployments.

**Example**:

```bash
/usr/local/bin/policy-engine \
  --manifest-path=/etc/policy/manifest.yaml \
  --pubkey-path=/etc/policy/manifest.pub \
  --listen=unix:///run/policy-engine.sock \
  --eval-timeout=200ms
```

---

## Step 2: Acquire Resources

**Purpose**: Bind listening sockets and create runtime directories before loading heavy resources.

**Unix Socket Path**:
- Create parent directories if missing (`mkdir -p`).
- Remove stale socket file if it exists from a previous crash (`unlink`).
- Set permissions to `0600` (owner read/write only).
- Bind with `SO_REUSEADDR` equivalent for Unix: ignore `EADDRINUSE` if file is dead.

**TCP Ports**:
- Bind HTTP and gRPC ports immediately so systemd `Type=notify` or Kubernetes know the process is alive.
- Return `503` on all routes until Step 9 completes.

**File Locks**:
- Acquire an exclusive lock on the manifest file (`flock`) to prevent concurrent modification during bootstrap.
- If lock fails (another process holds it), retry with exponential backoff up to 10s, then exit code `2`.

**Health Check State After This Step**:
- `GET /healthz` returns `200` (process is alive).
- `GET /readyz` returns `503` with body `{"status":"booting","step":"acquire_resources"}`.

---

## Step 3: Load Manifest from Disk

**Purpose**: Read the policy manifest into memory for verification and parsing.

**Manifest Format**:
The manifest is a signed document containing rules and metadata.

```yaml
apiVersion: policy.engine/v1
kind: PolicyManifest
metadata:
  name: production-policy
  version: "2024.06.14-001"
  signedAt: "2024-06-14T09:00:00Z"
spec:
  defaultDecision: deny
  rules:
    - name: allow-deploy-prod
      match:
        principal: "user:*"
        action: "skill:deploy"
        resource: "namespace:prod"
      engine: rego
      source: |
        package skill.deploy
        allow { input.principal == "user:admin" }
    - name: block-dangerous-skills
      match:
        action: "skill:*"
      engine: cel
      source: |
        input.action != "skill:delete-namespace"
```

**Failure Modes**:
- File not found: exit code `2`.
- Permission denied: exit code `2`.
- File empty or >10MB: exit code `2`.
- I/O error during read: exit code `2`.

**Logging**:
```
INFO  bootstrap step=3 msg="loading manifest" path=/etc/policy/manifest.yaml size_bytes=15234
```

---

## Step 4: Verify Manifest Signatures

**Purpose**: Ensure the manifest was authored by a trusted party and has not been tampered with.

**Signature Format**:
The manifest file includes a detached or inline signature. Supported mechanisms:
- Ed25519 detached signature (`manifest.yaml.sig` alongside `manifest.yaml`).
- Minisign (`manifest.yaml.minisig`).
- Cosign/OIDC for containerized manifests (optional).

**Verification Steps**:
1. Read public key from `--pubkey-path`.
2. Decode signature file (if detached) or extract inline signature.
3. Verify signature covers the exact manifest bytes (not a hash-of-hash unless specified).
4. Check signature timestamp is within acceptable skew (+/- 5 minutes).

**Failure Modes**:
- Signature file missing: exit code `2`.
- Public key missing or malformed: exit code `2`.
- Signature verification fails: exit code `2`.
- Signature timestamp outside skew window: log `WARN`, still exit code `2` (configurable with `--strict-time`).

**Logging**:
```
INFO  bootstrap step=4 msg="signature verified" algorithm=ed25519 key_id=prod-policy-2024
```

---

## Step 5: Parse Manifest Structure

**Purpose**: Convert raw manifest bytes into an internal validated struct.

**Schema Validation**:
- `apiVersion` must be exactly `policy.engine/v1`.
- `kind` must be `PolicyManifest`.
- `metadata.name` must match DNS subdomain format.
- `metadata.version` must be semantic or ISO date string.
- `spec.defaultDecision` must be `allow` or `deny`.
- `spec.rules` must be a non-empty array.

**Rule Schema Validation** (per rule):
- `name`: unique within manifest, DNS label format.
- `match.principal`, `match.action`, `match.resource`: valid glob or exact string.
- `engine`: one of supported engines (`rego`, `cel`, `wasm`).
- `source`: non-empty string.

**Failure Modes**:
- YAML/JSON syntax error: exit code `2` with line number.
- Schema violation (missing required field): exit code `2` with JSON path.
- Duplicate rule names: exit code `2`.
- Unsupported engine: exit code `2`.

**Logging**:
```
INFO  bootstrap step=5 msg="manifest parsed" rules_count=14 engines="[rego, cel]"
```

---

## Step 6: Validate Rule Syntax

**Purpose**: Catch compile-time errors before the evaluator is warmed up.

**Per-Engine Validation**:

### Rego
- Parse with `opa parse` or equivalent.
- Check for undefined references.
- Ensure at least one rule named `allow` or `deny` exists per module.

### CEL
- Parse with `cel.NewEnv().Parse()`.
- Type-check against declared inputs (`principal`, `action`, `resource`, `context`).
- Ensure expression returns boolean.

### WASM
- Validate magic bytes (`\0asm`).
- Verify exports include `evaluate` function with correct signature.
- Optional: instantiate in a throwaway sandbox to ensure it loads.

**Failure Modes**:
- Any rule fails syntax validation: exit code `2` with rule name and error.
- No `allow`/`deny` entry point in Rego module: exit code `2`.
- CEL expression returns non-bool: exit code `2`.
- WASM module fails validation: exit code `2`.

**Logging**:
```
INFO  bootstrap step=6 msg="rule syntax validated" rego_rules=10 cel_rules=4 wasm_rules=0 duration_ms=45
```

---

## Step 7: Compile Rules into Evaluator

**Purpose**: Build the evaluation cache so runtime queries are fast and deterministic.

**Compilation Steps**:
1. Compile each Rego module into a prepared query.
2. Compile each CEL expression into an evaluable program.
3. Compile/validate each WASM module.
4. Build the rule index (a trie or map) for fast matching by `principal`, `action`, `resource` globs.

**Resource Limits**:
- Max compilation time: 30s per rule. Exceeding → exit code `2`.
- Max memory during compile: 256MB. Exceeding → exit code `2`.

**Failure Modes**:
- Compilation timeout: exit code `2`.
- Out of memory during compilation: exit code `2`.
- Rule index collision (two rules with identical match): log `WARN`, second rule wins (last-write-wins documented behavior).

**Logging**:
```
INFO  bootstrap step=7 msg="rules compiled" index_entries=14 compile_duration_ms=120
```

---

## Step 8: Execute Self-Test Queries

**Purpose**: Prove the evaluator actually works end-to-end before accepting production traffic.

**Self-Test Suite**:
For each rule, the engine automatically generates one positive and one negative test case based on the rule's `match` block:

| Test Case | Input | Expected Decision |
|-----------|-------|-------------------|
| Positive match | Principal/action/resource exactly match rule pattern | Rule's natural decision (`allow` or `deny`) |
| Negative match (default) | Principal/action/resource that matches no rule | `spec.defaultDecision` |
| Mismatch | Input that matches rule pattern but rule logic denies | `deny` |

**Example**:
For rule:
```yaml
match:
  principal: "user:*"
  action: "skill:deploy"
  resource: "namespace:prod"
```
Self-tests:
- `{principal:"user:admin", action:"skill:deploy", resource:"namespace:prod"}` → allow (if rule logic permits)
- `{principal:"user:admin", action:"skill:read", resource:"namespace:prod"}` → defaultDecision

**Failure Modes**:
- Any self-test returns unexpected decision: exit code `2` with rule name and expected vs actual.
- Self-test evaluation panics: exit code `2`.
- Self-test exceeds `--eval-timeout`: exit code `2`.

**Logging**:
```
INFO  bootstrap step=8 msg="self-tests passed" tests_run=28 tests_failed=0
```

---

## Step 9: Mark Ready and Accept Traffic

**Purpose**: Atomically transition from "booting" to "serving".

**Atomic Transition**:
1. Set internal atomic boolean `ready = true`.
2. Update `/readyz` handler to return `200`.
3. If using systemd `Type=notify`, send `READY=1` via sd-notify socket.
4. If using Kubernetes, the readiness probe was already polling `/readyz`; it will now pass.
5. Begin accepting evaluation requests on gRPC and HTTP.

**Probe Contracts**:

### /healthz (Liveness)

```
GET /healthz

200 OK
{"status":"alive","pid":12345,"uptime_seconds":42}
```

- Always returns `200` as long as the process is running.
- Used by Kubernetes liveness probe.
- If this fails, Kubernetes restarts the container.

### /readyz (Readiness)

Before Step 9:
```
GET /readyz

503 Service Unavailable
{"status":"booting","step":"compile_rules","rules_loaded":0}
```

After Step 9:
```
GET /readyz

200 OK
{"status":"ready","rules_loaded":14,"manifest_version":"2024.06.14-001","evaluator":"rego+cel"}
```

- Used by Kubernetes readiness probe and systemd init ordering.
- If this fails, the orchestrator must not send traffic.

### gRPC CheckReady

```protobuf
rpc CheckReady(ReadyRequest) returns (ReadyResponse);
```

Before Step 9:
```
status: NOT_SERVING
rules_loaded: 0
```

After Step 9:
```
status: SERVING
rules_loaded: 14
manifest_version: "2024.06.14-001"
```

---

## Orchestrator Bootstrap Integration

### systemd

Use `After=policy-engine.service` and `Requires=policy-engine.service` in the orchestrator unit. The orchestrator will not start until policy engine reports `READY=1` (if `Type=notify`) or the service is marked active.

### Kubernetes

Use the init container pattern to block orchestrator startup until the policy engine is ready.

```yaml
initContainers:
  - name: wait-for-policy
    image: busybox:1.36
    command:
      - sh
      - -c
      - |
        for i in $(seq 1 180); do
          if wget -qO- http://policy-engine:8080/readyz | grep -q '"status":"ready"'; then
            exit 0
          fi
          sleep 1
        done
        echo "Timed out waiting for policy engine"
        exit 1
```

The orchestrator container should not define its own readiness probe until the init container completes.

### Docker Compose

Use `depends_on` with `condition: service_healthy` (Compose v3+ with compatible runtime):

```yaml
services:
  policy-engine:
    image: ghcr.io/org/policy-engine:v1.2.3
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:8080/readyz"]
      interval: 2s
      timeout: 1s
      retries: 30
      start_period: 10s

  orchestrator:
    image: ghcr.io/org/orchestrator:v2.0.0
    depends_on:
      policy-engine:
        condition: service_healthy
```

---

## Bootstrap Timing Budget

| Step | Max Duration | Rationale |
|------|-------------|-----------|
| 1-2 (Config + Resources) | 5s | Fast local operations |
| 3 (Load Manifest) | 2s | Disk I/O bound |
| 4 (Verify Signature) | 5s | Crypto operations |
| 5-6 (Parse + Validate Syntax) | 10s | YAML parsing + type checking |
| 7 (Compile) | 30s | Rego/CEL/WASM compilation |
| 8 (Self-Test) | 10s | 2 tests per rule, parallelized |
| **Total Budget** | **~60s** | Kubernetes `initialDelaySeconds` + `failureThreshold` should accommodate |

Recommended Kubernetes probe settings:
- `initialDelaySeconds: 2`
- `periodSeconds: 3`
- `failureThreshold: 30`  (total grace = 2 + 3*30 = 92s)

---

## Failure Recovery

If bootstrap fails at any step, the service must:

1. Log the step number, error message, and relevant file paths.
2. Exit with a non-zero code (preferably `2` for bootstrap failures).
3. Release any acquired file locks.
4. Close any bound sockets.
5. Not restart automatically unless configured by external supervisor (systemd, Kubernetes).

**Retry Policy**:
- No automatic retry inside the binary. The external supervisor (systemd, kubelet) handles restart with backoff.
- This prevents flapping and allows operators to inspect the broken manifest.
