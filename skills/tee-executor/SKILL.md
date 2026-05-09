---
name: tee-executor
description: Trusted Execution Environment sandbox backend using AWS Nitro Enclaves or Intel SGX for hardware-level isolation of sensitive code. Use when processing cryptographic material, handling PII, running in regulated environments, or when security-auditor flags code requiring hardware isolation. Integrates with secret-manager and policy-engine for attestation verification. Falls back to Docker if TEE unavailable.
---

# tee-executor

Hardware-level isolated execution backend for the `sandbox-executor`. Runs sensitive agent code inside AWS Nitro Enclaves (preferred) or Intel SGX enclaves so that memory remains encrypted even if the host OS is compromised.

## When to Activate

- `security-auditor` marks code as `TEE-recommended` or `TEE-required`
- `policy-engine` flags code requiring hardware-level isolation
- Processing cryptographic material: key generation, signing, decryption
- Handling PII/PHI under GDPR, HIPAA, or similar regulations
- Running in regulated environments (finance, healthcare, government)
- `secret-manager` requests enclave-provisioned secrets

## Workflow Decision Tree

```
Incoming execution request
|
+-- Is TEE required by policy-engine? --YES--> Check TEE availability
|                                               |
|                                               +-- Nitro available? --YES--> Nitro path
|                                               |
|                                               +-- SGX available? --YES--> SGX path
|                                               |
|                                               +-- Neither? --> FAIL or fallback*
|
+-- Is TEE recommended? --YES--> Check TEE availability
|                                 |
|                                 +-- Available? --YES--> TEE path
|                                 |
|                                 +-- No? --> Standard Docker sandbox
|
+-- TEE not mentioned --> Standard Docker sandbox

* Fallback to Docker only if policy allows; fail closed otherwise
```

## Core Capabilities

### 1. AWS Nitro Enclaves Backend (Primary)

Preferred TEE backend. Uses `nitro-cli` to build and run EIF (Enclave Image Format) images.

**Prerequisites:**
- EC2 instance with Nitro Enclaves enabled (e.g., `m5.xlarge` + enclave-enabled)
- `nitro-cli` installed
- Enclave allocator configured (`/etc/nitro_enclaves/allocator.yaml`)

**EIF Build Flow:**
```
Dockerfile (minimal OS) + agent code
    |
    v
nitro-cli build-enclave --docker-uri ... --output-file agent.eif
    |
    v
EIF image (signed, measured)
```

**Run Flow:**
```
nitro-cli run-enclave --eif-path agent.eif --cpu-count 2 --memory 512
    |
    v
Enclave boots --> vsock proxy connects
    |
    v
Attestation document requested
    |
    v
policy-engine verifies attestation
    |
    v
Secrets provisioned via vsock (never touch host disk)
    |
    v
Agent code executes
```

**Critical constraints:**
- No shell, no SSH, no network stack inside enclave
- All I/O via vsock (CID 3, configurable port)
- Storage: `tmpfs` only; no persistent mounts
- Minimal attack surface: stripped OS, no unnecessary services

### 2. Intel SGX Backend (Fallback TEE)

Used when Nitro is unavailable but SGX hardware is present.

**Prerequisites:**
- SGX-capable CPU with FLC (Flexible Launch Control)
- Linux SGX driver and PSW (Platform Software) installed
- `aesm` service running

**Run Flow:**
```
Gramine / Occlum / EGraphene runtime
    |
    v
Sign enclave manifest (MRENCLAVE measurement)
    |
    v
Launch enclave with attestation
    |
    v
Verify quote with Intel Attestation Service (IAS) or DCAP
    |
    v
Execute agent code inside enclave
```

### 3. Attestation Verification

Every TEE execution **must** verify the attestation document before provisioning secrets.

**Nitro attestation document contents:**
| Field | Description | Verified By |
|-------|-------------|-------------|
| `module_id` | Enclave image hash (PCR0) | policy-engine |
| `timestamp` | Issuance time | policy-engine (freshness check) |
| `digest` | SHA384 of user data | secret-manager |
| `certificate` | AWS-signed attestation cert | AWS root PKI |
| `cabundle` | Certificate chain | policy-engine |
| `pcrs` | Platform configuration registers | policy-engine (whitelist) |

**Verification steps:**
1. Verify AWS signature on the attestation document using AWS Nitro Attestation PKI
2. Check PCR0 matches the expected EIF measurement (reproducible build)
3. Verify PCR1, PCR2 are within allowed values (OS version, kernel config)
4. Check timestamp is within clock skew window (default 5 minutes)
5. Compare `digest` field against expected user data hash
6. Only after all checks pass: provision secrets via vsock

### 4. vsock Proxy for Tool Access

The enclave has no network. External tools are accessed via a vsock proxy on the host.

**Architecture:**
```
+------------------------+         vsock         +------------------+
|  Host (untrusted)      |  <----------------->  |  Enclave (TEE)   |
|                        |    CID=3, port=8000   |                  |
|  vsock proxy           |                       |  agent runtime   |
|  - HTTP proxy to tools |                       |  - vsock client  |
|  - Secret manager      |                       |  - tool calls    |
|  - Model API           |                       |    over vsock    |
+------------------------+                       +------------------+
```

**Proxy responsibilities:**
- Forward HTTP requests from enclave to external tools
- Inject secrets from `secret-manager` only after attestation passes
- Log all requests (but not secret payloads)
- Enforce request timeouts and rate limits

### 5. Graceful Degradation

If TEE hardware is unavailable:

| Policy Flag | Behavior |
|-------------|----------|
| `TEE-required` | **Fail closed** — reject execution, log security event |
| `TEE-recommended` | Log warning, fallback to standard Docker sandbox |
| No TEE flag | Standard Docker sandbox |

**Degradation checklist:**
1. Log the fallback decision with reason (no Nitro, no SGX, resource exhausted)
2. Increment `tee_fallback_total` metric
3. Alert if `TEE-required` code falls back (security event)
4. Apply enhanced Docker restrictions: seccomp-bpf, AppArmor, no root, read-only rootfs

## Integration Points

| Component | Direction | Data |
|-----------|-----------|------|
| `sandbox-executor` | Calls tee-executor when TEE flagged | Code bundle, policy |
| `policy-engine` | tee-executor queries for attestation rules | PCR whitelist, clock skew |
| `secret-manager` | tee-executor requests secrets after attestation | Secret handles, vsock channel |
| `security-auditor` | tee-executor reports execution mode | Attestation result, fallback events |
| `metrics` | tee-executor emits | `tee_execution_total`, `tee_attestation_failures`, `tee_fallback_total` |

## Output Quality Bar

- EIF builds must be reproducible: same Dockerfile + code = same PCR0 measurement
- Attestation verification is mandatory before any secret provision
- All fallback events are logged and alerted
- Enclave has zero network access; all I/O via vsock
- No secret material touches host disk or host memory unencrypted
- Clock skew tolerance: 5 minutes default, configurable via `TEE_ATTESTATION_MAX_SKEW`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TEE_BACKEND` | `nitro` | `nitro`, `sgx`, or `auto` |
| `NITRO_ENCLAVE_CPUS` | `2` | vCPUs allocated to enclave |
| `NITRO_ENCLAVE_MEMORY_MB` | `512` | RAM allocated to enclave |
| `NITRO_VSOCK_PROXY_PORT` | `8000` | vsock port for tool proxy |
| `TEE_ATTESTATION_MAX_SKEW` | `300` | Max attestation age in seconds |
| `TEE_PCR0_WHITELIST` | (required) | Comma-separated allowed PCR0 hashes |
| `TEE_FALLBACK_DOCKER` | `false` | Allow Docker fallback when TEE unavailable |

## Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `tee_execution_total` | Counter | `backend=nitro\|sgx\|docker`, `result=success\|failure` | Total TEE executions |
| `tee_attestation_duration_ms` | Histogram | `backend=nitro\|sgx` | Attestation verification time |
| `tee_attestation_failures` | Counter | `reason=signature\|pcr_mismatch\|expired\|user_data` | Failed attestations |
| `tee_fallback_total` | Counter | `reason=no_hardware\|resource_exhausted\|config` | Fallback to Docker |
| `tee_secret_provision_total` | Counter | `result=success\|failure` | Secrets provisioned via vsock |
