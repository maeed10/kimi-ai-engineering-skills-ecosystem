# Sandbox Capability Manifest Reference

| | |
|:---|:---|
| **Version** | 4.0.0 |
| **Status** | Mandatory for ALL Phase 4 skills |
| **Enforced By** | `policy-engine` via `sandbox-executor` |

---

## 1. Overview

Every Phase 4 skill **MUST** provide a `sandbox-config.yaml` file in its skill root directory. This file declares the **maximum capabilities** that the skill will ever request from `sandbox-executor`.

> **Principle**: *Declare the maximum, request the minimum.*
>
> The manifest sets an upper bound. Individual `ExecutionRequest`s may ask for less, but never more. Over-declaration is a policy violation (unused attack surface). Under-declaration with later over-request is also a policy violation.

---

## 2. File Location & Naming

| Convention | Path |
|:---|:---|
| Standard skill root | `/mnt/agents/output/{skill_name}/sandbox-config.yaml` |
| Loaded by | `SandboxExecutor._load_skill_config(skill_name)` |
| Hot-reload | No — parsed once per execution batch. Skill version bump required for manifest changes. |

---

## 3. Schema

### 3.1 Top-Level Keys

```yaml
skill_name: string         # MUST match the skill's registered name
version: semver            # Manifest schema version (e.g., 4.0.0)

runtime: RuntimeBlock      # Container image and entrypoint
capabilities: CapabilityBlock   # Maximum capability bounds
audit: AuditBlock          # Logging and retention preferences
```

### 3.2 `runtime` Block

```yaml
runtime:
  image: string            # Docker image reference, e.g. "python:3.11-slim"
  expected_sha256: string  # Full repo digest, e.g. "sha256:abc123..."
  entrypoint: string|null  # Override image entrypoint; null = use image default
```

| Field | Required | Description |
|:---|:---|:---|
| `image` | **Yes** | Base image. Must be from a `trusted_registries` entry in `sandbox-executor.yaml`. |
| `expected_sha256` | **Yes** | Immutable digest for verification. If the resolved digest does not match, execution is **aborted**. |
| `entrypoint` | No | Path to executable inside container. Usually `null` to use the image's default. |

#### Example

```yaml
runtime:
  image: python:3.11-slim
  expected_sha256: sha256:e523d0f9a2e8a7f03394f7880c6c20e9f5c3c0c5b9c9e4f8d2a1b0c7d6e5f4a3b
  entrypoint: null
```

---

### 3.3 `capabilities` Block

```yaml
capabilities:
  network: NetworkBlock
  filesystem: FilesystemBlock
  resources: ResourceBlock
  security: SecurityBlock
```

#### 3.3.1 `network` Block

```yaml
network:
  enabled: boolean                    # Default: false
  whitelisted_domains: list<string>   # Only valid if enabled: true
```

| Field | Default | Description |
|:---|:---|:---|
| `enabled` | `false` | If `false`, container runs with `--network none`. |
| `whitelisted_domains` | `[]` | DNS names allowed for outbound connections. Requires `enabled: true`. Policy-engine may further restrict this list. |

**Validation rules**:
- If `enabled: false`, `whitelisted_domains` MUST be empty or omitted.
- Domains MUST be valid DNS names (no IP addresses, no wildcards).
- Maximum 10 domains per skill.

#### 3.3.2 `filesystem` Block

```yaml
filesystem:
  read_only_mounts:
    - host: string        # Absolute path on host OS
      container: string   # Absolute path inside container
      read_only: true     # MUST be true; enforced by executor
  write_paths:
    - string              # ONLY "/tmp" is universally allowed
  max_tmpfs_size: string   # Memory-backed tmpfs size, e.g. "256m", "1g"
```

| Field | Default | Description |
|:---|:---|:---|
| `read_only_mounts` | `[]` | Source code, config, or asset directories. Always mounted `--read-only`. |
| `write_paths` | `["/tmp"]` | Paths inside the container where writing is permitted. The ONLY host-independent write path is `/tmp` (backed by `--tmpfs`). |
| `max_tmpfs_size` | `"128m"` | Size limit for the in-memory `/tmp` volume. |

**Validation rules**:
- `read_only_mounts` entries MUST use absolute paths.
- `write_paths` MAY include `/tmp` plus additional declared paths if the skill genuinely requires them (rare; requires justification).
- Any path outside `write_paths` MUST be read-only or absent.

#### 3.3.3 `resources` Block

```yaml
resources:
  max_memory_mb: integer      # Default: 512
  max_cpus: float           # Default: 1.0
  max_pids: integer         # Default: 32
  timeout_seconds: integer  # Default: 60
```

| Field | Default | Hard Ceiling | Description |
|:---|:---|:---|:---|
| `max_memory_mb` | 512 | 16384 | RAM limit. Mapped to `--memory` and `--memory-swap`. |
| `max_cpus` | 1.0 | 16.0 | CPU quota. Mapped to `--cpus`. |
| `max_pids` | 32 | 4096 | PID limit. Mapped to `--pids-limit`. Prevents fork-bombs. |
| `timeout_seconds` | 60 | 3600 | Wall-clock timeout per execution. Hard kill on expiry. |

**Validation rules**:
- An `ExecutionRequest` MAY request less than these values.
- Requesting **equal** values is allowed.
- Requesting **greater** values triggers `PolicyViolationError`.

#### 3.3.4 `security` Block

```yaml
security:
  privileged: boolean              # Default: false
  seccomp_profile: string            # "default" | "none" | "custom:/path"
  capabilities_drop: list<string>    # Default: ["ALL"]
  capabilities_add: list<string>   # Default: []
  no_new_privileges: boolean       # Default: true
```

| Field | Default | Description |
|:---|:---|:---|
| `privileged` | `false` | `--privileged` flag. **NEVER** set to `true` without human approval. Setting `true` always escalates to human review. |
| `seccomp_profile` | `"default"` | seccomp filter profile. `"default"` uses `/etc/kimi/skills/seccomp-default.json`. `"none"` requires human approval. `"custom:/path"` loads a custom profile. |
| `capabilities_drop` | `["ALL"]` | Linux capabilities to drop. Should always start with `ALL`. |
| `capabilities_add` | `[]` | Capabilities to selectively add back. Examples: `NET_BIND_SERVICE` for low-port binding, `SYS_PTRACE` for debugging. Each addition requires policy-engine approval. |
| `no_new_privileges` | `true` | Sets `no-new-privileges:true`. Prevents `setuid` binaries from gaining privileges. |

**Validation rules**:
- `privileged: true` MUST be accompanied by a human approval ticket ID in the `ExecutionRequest` metadata (production integration).
- `seccomp_profile: none` MUST also have human approval.
- `capabilities_add` is additive only after `capabilities_drop ALL`. Direct removal of `ALL` is rejected.

---

### 3.4 `audit` Block

```yaml
audit:
  log_level: string          # DEBUG | INFO | WARNING | ERROR
  retain_stdout: boolean     # Default: true
  retain_stderr: boolean     # Default: true
  max_log_size_mb: integer   # Default: 10
  forward_to_policy_engine: boolean  # Default: true
```

| Field | Default | Description |
|:---|:---|:---|
| `log_level` | `INFO` | Minimum level for audit events. |
| `retain_stdout` | `true` | Include stdout preview in audit log. |
| `retain_stderr` | `true` | Include stderr preview in audit log. |
| `max_log_size_mb` | 10 | Per-execution log cap. Prevents audit log DoS via massive stdout. |
| `forward_to_policy_engine` | `true` | Stream audit entries to `policy-engine` for compliance aggregation. |

---

## 4. Complete Example

### 4.1 Python Testing Skill

```yaml
# /mnt/agents/output/code-tester/sandbox-config.yaml
skill_name: code-tester
version: 4.0.0

runtime:
  image: python:3.11-slim
  expected_sha256: sha256:e523d0f9a2e8a7f03394f7880c6c20e9f5c3c0c5b9c9e4f8d2a1b0c7d6e5f4a3b
  entrypoint: null

capabilities:
  network:
    enabled: false
    whitelisted_domains: []

  filesystem:
    read_only_mounts:
      - host: "{REPO_ROOT}/src"
        container: "/workspace/src"
        read_only: true
      - host: "{REPO_ROOT}/tests"
        container: "/workspace/tests"
        read_only: true
    write_paths:
      - "/tmp"
    max_tmpfs_size: "256m"

  resources:
    max_memory_mb: 1024
    max_cpus: 2.0
    max_pids: 64
    timeout_seconds: 300

  security:
    privileged: false
    seccomp_profile: "default"
    capabilities_drop: ["ALL"]
    capabilities_add: []
    no_new_privileges: true

audit:
  log_level: INFO
  retain_stdout: true
  retain_stderr: true
  max_log_size_mb: 10
  forward_to_policy_engine: true
```

### 4.2 Node.js Build Skill (with network for npm install)

```yaml
# /mnt/agents/output/node-builder/sandbox-config.yaml
skill_name: node-builder
version: 4.0.0

runtime:
  image: node:20-slim
  expected_sha256: sha256:7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9
  entrypoint: null

capabilities:
  network:
    enabled: true
    whitelisted_domains:
      - registry.npmjs.org
      - npm.pkg.github.com

  filesystem:
    read_only_mounts:
      - host: "{REPO_ROOT}"
        container: "/workspace"
        read_only: true
    write_paths:
      - "/tmp"
    max_tmpfs_size: "512m"

  resources:
    max_memory_mb: 2048
    max_cpus: 2.0
    max_pids: 128
    timeout_seconds: 600

  security:
    privileged: false
    seccomp_profile: "default"
    capabilities_drop: ["ALL"]
    capabilities_add: []
    no_new_privileges: true

audit:
  log_level: INFO
  retain_stdout: true
  retain_stderr: true
  max_log_size_mb: 20
  forward_to_policy_engine: true
```

### 4.3 Security Auditor (minimal privileges)

```yaml
# /mnt/agents/output/security-auditor/sandbox-config.yaml
skill_name: security-auditor
version: 4.0.0

runtime:
  image: ghcr.io/kimi-ai/secscan:v2.1
  expected_sha256: sha256:deadbeef0000111122223333444455556666777788889999aaaabbbbccccdddd
  entrypoint: "/usr/local/bin/secscan"

capabilities:
  network:
    enabled: false

  filesystem:
    read_only_mounts:
      - host: "{REPO_ROOT}"
        container: "/scan/target"
        read_only: true
    write_paths:
      - "/tmp"
    max_tmpfs_size: "128m"

  resources:
    max_memory_mb: 512
    max_cpus: 1.0
    max_pids: 32
    timeout_seconds: 600

  security:
    privileged: false
    seccomp_profile: "default"
    capabilities_drop: ["ALL"]
    capabilities_add: []
    no_new_privileges: true

audit:
  log_level: INFO
  retain_stdout: true
  retain_stderr: true
  max_log_size_mb: 5
  forward_to_policy_engine: true
```

---

## 5. Capability Inheritance & Override Rules

### 5.1 Inheritance
- A skill manifest is **static** for the skill version.
- Child tasks or sub-invocations **do not** re-declare; they reuse the parent skill manifest.
- If a sub-component needs broader capabilities, it must be a separate skill with its own manifest.

### 5.2 Runtime Override (Request < Manifest)
- `ExecutionRequest.capabilities` MAY be **strictly less restrictive** than the manifest — wait, no: it may request **less** of a resource, but the **same or fewer** permissions.
  - ✅ `max_memory_mb: 512` request against manifest `max_memory_mb: 1024`
  - ❌ `max_memory_mb: 2048` request against manifest `max_memory_mb: 1024`
  - ✅ `network: false` request against manifest `network: true`
  - ❌ `network: true` request against manifest `network: false`

### 5.3 Emergency Override (Human Approval)
- Human operators MAY issue a **time-bound approval token** to exceed the manifest for a specific `request_id`.
- The token is logged, audited, and expires after single use or timeout.
- `policy-engine` checks the token before granting the override.

---

## 6. Validation Matrix

| Manifest declares | Request asks | Policy verdict | Executor action |
|:---|:---|:---|:---|
| `network: false` | `network: false` | ✅ Approve | `--network none` |
| `network: false` | `network: true` | ❌ Deny | `PolicyViolationError` |
| `network: true`, whitelist `a.com` | `network: true`, whitelist `b.com` | ❌ Deny | `PolicyViolationError` (domain not declared) |
| `network: true`, whitelist `a.com` | `network: true`, whitelist `a.com` | ✅ Approve | Custom bridge + DNS allow |
| `privileged: false` | `privileged: true` | ❌ Deny | `PolicyViolationError` (human approval required) |
| `privileged: true` + human token | `privileged: true` | ✅ Approve | `--privileged` (rare, audited) |
| `seccomp: default` | `seccomp: none` | ❌ Deny | `PolicyViolationError` |
| `seccomp: default` | `seccomp: default` | ✅ Approve | `--security-opt seccomp=default.json` |
| `max_memory_mb: 512` | `max_memory_mb: 256` | ✅ Approve | `--memory 256m` |
| `max_memory_mb: 512` | `max_memory_mb: 1024` | ❌ Deny | `PolicyViolationError` |
| `write_paths: ["/tmp"]` | `write_paths: ["/tmp", "/var/log"]` | ❌ Deny | `PolicyViolationError` |
| `write_paths: ["/tmp", "/var/log"]` | `write_paths: ["/tmp"]` | ✅ Approve | Only `/tmp` mounted writable |

---

## 7. Common Mistakes & Anti-Patterns

| Mistake | Risk | Correct Approach |
|:---|:---|:---|
| Over-declaring `network: true` "just in case" | Increases attack surface | Set `network: false` unless absolutely necessary |
| Declaring `privileged: true` for convenience | Complete container escape | Never use privileged; redesign to avoid need |
| Omitting `expected_sha256` | Supply-chain attack | Always pin immutable digests |
| Using large `max_memory_mb` as "catch-all" | Resource exhaustion, OOM on host | Profile actual usage; set tight bounds |
| Adding capabilities without justification | Privilege escalation | Start with `capabilities_drop: ["ALL"]` and add only when proven necessary |
| Mounting host directories read-write | Host filesystem corruption | All source mounts MUST be `read_only: true`; only `/tmp` is writable |

---

## 8. Version History

| Version | Date | Change |
|:---|:---|:---|
| 4.0.0 | 2025-01 | Initial capability manifest schema for Phase 4 sandbox-executor |

---

## 9. References

- [SKILL.md](../SKILL.md) — Main `sandbox-executor` skill documentation
- [sandbox-executor.py](../scripts/sandbox-executor.py) — Executor implementation
- Docker Security: https://docs.docker.com/engine/security/
- seccomp default profile: https://github.com/moby/moby/blob/master/profiles/seccomp/default.json
