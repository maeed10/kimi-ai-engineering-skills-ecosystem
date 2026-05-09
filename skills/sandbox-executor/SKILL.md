---
name: sandbox-executor
description: >
  Mandatory sandbox wrapper for ALL subprocess execution across the ecosystem. Eliminates direct host-OS subprocess execution by orchestrating ephemeral, network-isolated Docker containers with read-only source mounts, writable tmpfs at /tmp, resource caps, seccomp profiles, and executable allowlist enforcement via seccomp-BPF or minimal /bin mounts. No script, tool, or test may execute outside the sandbox. Integrates with ALL Phase 4 skills: Code Tester, Refactoring Engine, Security Auditor, Performance Validator, Resilience Tester.
---

## 1. Purpose

**`sandbox-executor`** is the mandatory, universal sandbox wrapper for ALL subprocess execution across the Kimi AI Engineering Skills Ecosystem. It eliminates direct host-OS subprocess execution by orchestrating ephemeral, network-isolated Docker containers with strict filesystem, resource, and capability controls.

> **CRITICAL SAFETY RULE**: No tool, script, or test in the Phase 4 ecosystem may execute via bare `subprocess` on the host OS. ALL execution MUST flow through `sandbox-executor`.

---

## 2. Capabilities

### 2.1 Container Orchestration (Docker — default)
- Launch one ephemeral Docker container per execution request
- Pull and verify container image integrity (SHA-256) before execution
- Use fresh containers for every execution — no state leakage between runs
- Immediate container destruction after execution (fire-and-forget lifecycle)

### 2.1b Cloud Sandbox Orchestration (E2B — optional)
- Launch ephemeral, network-isolated cloud sandboxes via [E2B](https://e2b.dev)
- No local Docker daemon required — runs on E2B infrastructure
- Automatic sandbox teardown after execution
- Integrates via MCP server or direct Python SDK
- **Backend selection**: `docker` (default) or `e2b` via `sandbox-executor.yaml`

### 2.2 Resource Capping
- Memory limits via `--memory` and `--memory-swap`
- CPU limits via `--cpus`
- Optional pids-limit via `--pids-limit`
- Execution timeout enforcement (hard kill)

### 2.3 Filesystem Isolation
- Source code mounted as `--read-only` volume
- Writable scratch space provided as `--tmpfs` mounted at `/tmp` only
- No other host paths writable inside the container
- No state persistence between executions

### 2.4 Network Isolation
- Default: `--network none` (complete network isolation)
- Whitelisted domains only when explicitly declared in capability manifest and approved by `policy-engine`
- No outbound internet access unless policy-approved

### 2.5 Execution Audit
- Log every execution with:
  - Container image name and SHA-256 hash
  - Declared vs. granted capabilities
  - Resource limits applied
  - Exit code
  - Wall-clock execution time
  - Stdout/stderr (configurable retention)
- Audit logs forwarded to `policy-engine` for compliance

### 2.6 Capability Declaration
- Each skill declares required capabilities (network, FS write paths, syscalls, devices)
- `policy-engine` validates execution request against declared capabilities
- Over-declaration and under-declaration both trigger policy violations

---

## 3. Architecture & Workflow

### 3.1 Execution Request Format

```json
{
  "request_id": "uuid-v4",
  "skill_name": "code-tester",
  "command": ["python", "-m", "pytest", "-v"],
  "working_directory": "/workspace",
  "source_mounts": [
    {"host": "/repo/src", "container": "/workspace/src", "read_only": true}
  ],
  "environment": {"PYTHONDONTWRITEBYTECODE": "1"},
  "capabilities": {
    "network": false,
    "fs_write_paths": ["/tmp"],
    "max_memory_mb": 512,
    "max_cpus": 1.0,
    "timeout_seconds": 60,
    "allow_privileged": false
  },
  "image": "python:3.11-slim",
  "expected_sha256": "sha256:abc123..."
}
```

### 3.2 Execution Workflow

```
┌─────────────────┐
│  Phase 4 Skill  │ (code-tester, security-auditor, etc.)
│  requests exec  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│   1. Gateway: tool-execution-gateway  │
│      - Receives raw subprocess call   │
│      - Routes to SandboxExecutor      │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   2. Load sandbox-config.yaml   │
│      - Read skill capability    │
│        declaration              │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   3. PolicyEngine.validate()    │
│      - Check declared vs.       │
│        requested capabilities   │
│      - Validate command against │
│        executable_allowlist     │
│      - Approve / Deny / Escalate│
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   4. Image Verification         │
│      - Pull if absent             │
│      - Verify SHA-256             │
│      - Reject if mismatch         │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   5. Container Launch           │
│      --read-only source mounts  │
│      --tmpfs /tmp               │
│      --network none (or whitelist)
│      --memory, --cpus           │
│      --security-opt             │
│      seccomp=allowlist-derived  │
│      profile (or minimal /bin)  │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   6. Execute command            │
│      - Stream stdout/stderr     │
│      - Enforce timeout          │
│      - Monitor resource usage     │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   7. Capture & Destroy          │
│      - Collect exit code        │
│      - Destroy container        │
│      - Auto-clean /tmp          │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│   8. Return Result + Audit Log  │
│      {exit_code, stdout, stderr,│
│       execution_time,           │
│       container_hash}           │
└─────────────────────────────────┘
         │
         ▼ (on failure)
┌─────────────────────────────────┐
│   9. error-policy trigger       │
│      - Sandbox failure recovery │
│      - Retry / escalate / abort │
└─────────────────────────────────┘
```

---

## 4. Configuration

### 4.1 Skill-Level: `sandbox-config.yaml`

Each Phase 4 skill MUST provide a `sandbox-config.yaml` in its skill root. This declares the maximum capabilities the skill will ever need, including the `executable_allowlist` that defines exactly which binaries may run inside the sandbox.

```yaml
# Example: code-tester/sandbox-config.yaml
skill_name: code-tester
version: 4.0.0

runtime:
  image: python:3.11-slim
  expected_sha256: sha256:2f23d7...beef
  entrypoint: null  # use image default

capabilities:
  network:
    enabled: false
    # whitelisted_domains: []  # only if enabled: true

  filesystem:
    read_only_mounts:
      - host: "{REPO_ROOT}/src"
        container: "/workspace/src"
    write_paths:
      - "/tmp"           # MUST always include /tmp
    max_tmpfs_size: "256m"

  resources:
    max_memory_mb: 1024
    max_cpus: 2.0
    max_pids: 64
    timeout_seconds: 300

  security:
    privileged: false
    seccomp_profile: "default"   # default | none | custom:/path
    capabilities_drop: ["ALL"]
    capabilities_add: []
    no_new_privileges: true

# executable_allowlist is REQUIRED — see Section 5
executable_allowlist:
  - path: /usr/bin/python3
    args:
      - pattern: ["-m", "pytest"]
        allow_extra_args: true
      - pattern: ["-m", "unittest"]
        allow_extra_args: true
    max_processes: 4
  - path: /usr/bin/pip3
    args:
      - pattern: ["install", "--dry-run"]
      - pattern: ["freeze"]
    max_processes: 1

audit:
  log_level: INFO
  retain_stdout: true
  retain_stderr: true
  max_log_size_mb: 10
  forward_to_policy_engine: true
```

### 4.2 System-Level: `sandbox-executor.yaml`

Global configuration for the executor itself.

```yaml
# /etc/kimi/skills/sandbox-executor.yaml
version: 4.0.0

# Backend selection: "docker" (default) or "e2b"
backend: docker

docker:
  socket: /var/run/docker.sock
  default_timeout_pull_seconds: 120
  max_concurrent_executions: 10
  container_prefix: "kimi-sandbox"

# E2B cloud sandbox configuration (used when backend: e2b)
e2b:
  api_key: "${E2B_API_KEY}"          # Loaded from environment
  timeout_seconds: 60
  # E2B sandboxes are always ephemeral and network-isolated
  # Resource limits are enforced by E2B infrastructure

backend_failover:
  primary: e2b
  fallback: docker
  failover_conditions:
    e2b_api_timeout_ms: 10000
    e2b_http_5xx_count: 3
    e2b_connection_refused: true
  auto_failback: false              # require human ack after E2B recovery
  failback_probe_command: ["echo", "probe"]  # command to verify E2B health
  failback_probe_timeout: 30

defaults:
  memory_mb: 512
  cpus: 1.0
  pids_limit: 32
  timeout_seconds: 60
  tmpfs_size: "128m"
  seccomp_profile_path: "/etc/kimi/skills/seccomp-default.json"

images:
  trusted_registries:
    - "docker.io/library"
    - "ghcr.io/kimi-ai"
  image_pull_policy: "if-not-present"  # always | if-not-present | never
  verify_signatures: true  # CHANGED: default true as of v4.2.1. Set false only in dev with KIMI_INSECURE_SKIP_SIGNATURE_VERIFY=1

logging:
  level: INFO
  destination: "file:///var/log/kimi/sandbox-executor.log"
  json_format: true

policy_engine:
  endpoint: "unix:/var/run/kimi/policy-engine.sock"  # Primary: Unix socket (not reachable from sandboxes)
  fallback_endpoint: "https://127.0.0.1:9100"         # Fallback: loopback mTLS for remote monitoring
  enforce_strict_mode: true
  reject_on_capability_mismatch: true
  mTLS:
    enabled: true
    ca_cert: "~/.kimi/certs/policy-ca.pem"
    client_cert: "~/.kimi/certs/sandbox-client.pem"
    client_key: "~/.kimi/certs/sandbox-client.key"
  network_isolation:
    block_policy_engine_from_sandboxes: true
    iptables_drop_rules:
      - dst: "127.0.0.1/32"
        dport: 9100
        proto: "tcp"
```

### 4.3 E2B MCP Server Configuration

The E2B MCP server exposes cloud sandbox execution via the Model Context Protocol. This allows Kimi Code CLI (and other MCP clients) to execute code in E2B sandboxes directly.

**Step 1 — Get a free API key**
1. Visit https://e2b.dev and sign up
2. Generate an API key from your dashboard
3. The free tier includes generous sandbox hours

**Step 2 — Install the E2B MCP server**
```bash
npm install -g @e2b/mcp-server@0.2.3
```
> Note: `@e2b/mcp-server` is deprecated but functional. Future versions may migrate to `smart-e2b`.

**Step 3 — Configure Kimi Code CLI**
Add to `~/.kimi/mcp.json`:
```json
{
  "mcpServers": {
    "e2b-sandbox": {
      "command": "npx",
      "args": ["-y", "@e2b/mcp-server@0.2.3"],
      "env": {
        "E2B_API_KEY": "YOUR_E2B_API_KEY_HERE"
      }
    }
  }
}
```

**Step 4 — Verify connection**
```bash
kimi mcp test e2b-sandbox
```

The MCP server exposes one tool:
- **`run_code`** — Execute Python code in an ephemeral E2B cloud sandbox using Jupyter Notebook syntax.

### 4.4 Backend Selection Guide

| Factor | Docker | E2B |
|:---|:---|:---|
| **Requires local runtime** | Yes (Docker daemon) | No |
| **Network isolation** | `--network none` | Built-in |
| **Resource caps** | `--memory`, `--cpus` | Enforced by E2B infra |
| **Startup latency** | ~1-3s (image cached) | ~2-5s (sandbox creation) |
| **Multi-language support** | Any container image | Python-first (extensible) |
| **Host filesystem access** | Read-only bind mounts | Limited (upload/download API) |
| **Best for** | CI/CD, local dev, multi-lang | Cloud-native, no Docker installs |

---

## 5. Executable Allowlist Enforcement

### 5.1 Purpose

The policy engine validates *what* the LLM can request (network, paths) but not *which* binaries can execute. This section closes that gap by extending `sandbox-config.yaml` with an `executable_allowlist` block and enforcing it at the kernel boundary via seccomp-BPF filters or minimal bind mounts of `/bin`.

Key outcomes:
- Every skill declares exactly which binaries it needs and their allowed argument patterns.
- The policy engine rejects execution requests that violate the declared allowlist.
- The sandbox executor loads a seccomp-BPF filter or read-only `/bin` mount that blocks any `execve` outside the allowlist.

### 5.2 `executable_allowlist` Schema

The schema is a list under the top-level key `executable_allowlist` in `sandbox-config.yaml`. Each entry specifies an absolute binary path, a list of allowed argument patterns, optional syscall restrictions, and optional environment variable rules.

Minimal example:

```yaml
executable_allowlist:
  - path: /usr/bin/python3
    args:
      - pattern: ["-m", "pytest"]
      - pattern: ["-c"]
        allow_extra_args: true
    env:
      - name: PYTHONDONTWRITEBYTECODE
        value: "1"
      - name: PYTHONPATH
        value_regex: "^/workspace/.*$"
    max_processes: 4
    allowed_syscalls:
      - read
      - write
      - exit
      - exit_group
```

The full schema specification lives in [`references/allowlist_schema.md`](./references/allowlist_schema.md).

### 5.3 Enforcement Mechanisms

#### 5.3.1 seccomp-BPF Filter (Preferred)

Generate a seccomp-BPF profile from the allowlist and pass it to the container runtime. The profile must:
- Allow `execve`/`execveat` only when the target path matches an allowlisted entry.
- Block `execve` with `errno=EPERM` for all other paths.
- Optionally restrict the argument vector against declared patterns.

Because seccomp-BPF cannot easily introspect string arguments at filter-load time, the pattern enforcement is typically split:
- **Path enforcement** — seccomp-BPF (kernel, unavoidable).
- **Argument enforcement** — LSM/AppArmor or a lightweight userspace wrapper (e.g., `libminijail` or a small preload) that validates `argv` before calling the real `execve`.

For pure seccomp, a practical compromise is to allow `execve` for the allowlisted binary and rely on the policy engine (userspace) to pre-validate arguments before the container starts.

See [`references/seccomp_policy_examples.md`](./references/seccomp_policy_examples.md) for ready-to-adapt JSON profiles.

#### 5.3.2 Minimal `/bin` Bind Mount (Fallback)

When seccomp is unavailable or the environment uses a read-only rootfs:
1. Create a temporary directory `mini_bin/`.
2. For each allowlisted binary, create a symlink: `mini_bin/$(basename $path) -> $path`.
3. Also symlink any required shared libraries or interpreter paths (e.g., `/lib64`).
4. Bind-mount `mini_bin/` into the container as `/bin:ro`.
5. Set `PATH=/bin` inside the container.

This is coarser than seccomp (a symlink could be abused if the target is a shell) but is portable and requires no kernel BPF support.

### 5.4 Policy-Engine Integration Rules

Before creating a container, the policy engine must perform these checks in order:

1. **Allowlist Presence** — If `sandbox-config.yaml` lacks `executable_allowlist`, reject the request with `SANDBOX_CONFIG_MISSING_ALLOWLIST`.
2. **Path Match** — The requested command's absolute path must match an `executable_allowlist.path` entry exactly. No PATH resolution inside the sandbox; the policy engine resolves it.
3. **Argument Match** — The requested `argv[1:]` must match at least one `pattern` for that path. Literal strings are matched exactly; a trailing `"*"` wildcard in the pattern permits any additional arguments after the prefix.
4. **Process Limit** — The total number of concurrent processes must not exceed the sum of `max_processes` across all allowlisted entries (default 1 per entry if omitted).
5. **Syscall Audit** — If `allowed_syscalls` is present, the generated seccomp profile must drop all syscalls not explicitly listed (plus the mandatory baseline: `read`, `write`, `close`, `exit`, `exit_group`, `brk`, `mmap`, `munmap`, `mprotect`, `sigreturn`, `rt_sigreturn`, `rt_sigaction`).

If any check fails, the policy engine returns `EXECUTION_DENIED` with a structured reason field:

```json
{
  "decision": "DENY",
  "reason_code": "ARGS_MISMATCH",
  "allowlist_entry": "/usr/bin/python3",
  "requested_args": ["-m", "pip", "install", "requests"],
  "message": "Requested args do not match any declared pattern for /usr/bin/python3"
}
```

### 5.5 Example Configs for Common Skills

#### code-tester

```yaml
executable_allowlist:
  - path: /usr/bin/python3
    args:
      - pattern: ["-m", "pytest"]
        allow_extra_args: true
      - pattern: ["-m", "unittest"]
        allow_extra_args: true
    max_processes: 4
  - path: /usr/bin/pip3
    args:
      - pattern: ["install", "--dry-run"]
      - pattern: ["freeze"]
    max_processes: 1
```

#### security-auditor

```yaml
executable_allowlist:
  - path: /usr/bin/python3
    args:
      - pattern: ["-m", "bandit"]
        allow_extra_args: true
      - pattern: ["-m", "safety"]
        allow_extra_args: true
    max_processes: 2
  - path: /usr/bin/nmap
    args:
      - pattern: ["-sT", "-p", "*"]
    max_processes: 1
    allowed_syscalls:
      - socket
      - connect
      - read
      - write
      - close
      - exit
      - exit_group
```

#### static-analyzer (clang-based)

```yaml
executable_allowlist:
  - path: /usr/bin/clang
    args:
      - pattern: ["--analyze", "*"]
    max_processes: 2
  - path: /usr/bin/python3
    args:
      - pattern: ["-c"]
        allow_extra_args: true
    max_processes: 1
```

### 5.6 Validation Workflow

Run the bundled validator against any `sandbox-config.yaml` before merging:

```bash
python scripts/validate_allowlist.py \
  --config ./sandbox-config.yaml \
  --strict-syscalls \
  --max-entries 10
```

The script exits non-zero if:
- `executable_allowlist` is missing or empty.
- Any `path` is relative or contains `..`.
- Any `args` pattern contains shell metacharacters.
- `allowed_syscalls` includes a blocked syscall (`execveat` with no path restriction, `ptrace`, `personality`, `mount`, `umount2`).
- `--strict-syscalls` is set and the baseline mandatory syscalls are missing.

#### Remediation Checklist

- [ ] `sandbox-config.yaml` contains `executable_allowlist` with at least one entry.
- [ ] Every entry has an absolute `path` and at least one `args` pattern.
- [ ] No entry allows `/bin/sh`, `/bin/bash`, or `/usr/bin/python3` with unrestricted `args` (use `pattern` prefixes and `allow_extra_args` sparingly).
- [ ] Policy engine validates the requested command against the allowlist before creating the container.
- [ ] Sandbox executor loads a seccomp profile or minimal `/bin` mount derived from the allowlist.
- [ ] `scripts/validate_allowlist.py` passes in CI for every skill change.

---

## 6. Safety Rules (Hard Constraints)

| Rule | Severity | Enforcement |
|:---|:---|:---|
| **NEVER execute subprocess directly on host OS** | CRITICAL | `tool-execution-gateway` blocks bare `subprocess` calls; `sandbox-executor` is the only authorized executor |
| **NEVER allow network access unless explicitly declared and policy-approved** | CRITICAL | `--network none` default; `policy-engine` gatekeeps any whitelist |
| **NEVER mount host filesystem writable except `/tmp` inside container** | CRITICAL | `--read-only` on all source mounts; only `--tmpfs` at `/tmp` |
| **ALWAYS use a fresh container for each execution** | CRITICAL | One-shot container lifecycle; explicit `--rm` equivalent |
| **ALWAYS verify container image integrity (SHA-256) before execution** | HIGH | Pull + verify; mismatch raises `SecurityException` |
| **NEVER allow `--privileged` or `seccomp=unconfined` without human approval** | HIGH | Requires `security.privileged: true` AND `policy-engine` escalation to human |
| **ALWAYS drop all Linux capabilities before selectively adding** | HIGH | `--cap-drop ALL` default; additive capability model |
| **ALWAYS set `no_new_privileges: true`** | MEDIUM | Prevents privilege escalation within container |
| **ALWAYS declare `executable_allowlist` in `sandbox-config.yaml`** | HIGH | Missing allowlist causes `SANDBOX_CONFIG_MISSING_ALLOWLIST` rejection |
| **NEVER allow unrestricted shell interpreters in the allowlist** | HIGH | `/bin/sh`, `/bin/bash`, `/usr/bin/python3` with `args: ["*"]` are rejected by the validator |

---

## 4.5 Startup Guard — Signature Verification Enforcement

On initialization, `SandboxExecutor` MUST validate the `verify_signatures` setting:

```python
class SandboxExecutor:
    def __init__(self, config_path: str = "/etc/kimi/skills/sandbox-executor.yaml"):
        self.config = load_config(config_path)
        self._enforce_signature_guard()
        ...

    def _enforce_signature_guard(self) -> None:
        """
        Fail-closed guard: if verify_signatures is false,
        require explicit KIMI_INSECURE_SKIP_SIGNATURE_VERIFY=1.
        """
        if not self.config.images.verify_signatures:
            if os.getenv("KIMI_INSECURE_SKIP_SIGNATURE_VERIFY") != "1":
                raise ConfigError(
                    "verify_signatures is false but "
                    "KIMI_INSECURE_SKIP_SIGNATURE_VERIFY is not set. "
                    "Set it to 1 only for local development with unsigned images."
                )
            logger.warning(
                "INSECURE: verify_signatures=false and "
                "KIMI_INSECURE_SKIP_SIGNATURE_VERIFY=1 is active. "
                "Do NOT use in production."
            )
```

**Behavior:**
- `verify_signatures: true` → startup proceeds normally.
- `verify_signatures: false` + `KIMI_INSECURE_SKIP_SIGNATURE_VERIFY=1` → startup proceeds with WARNING log.
- `verify_signatures: false` + env var missing/absent → `ConfigError`, startup aborted.

This guard is integrated into `sandbox-integration-tester` as a negative test case.

---

## 7. API Reference

### 7.1 `SandboxExecutor` Class

```python
class SandboxExecutor:
    """
    Mandatory executor for all subprocess operations in Kimi Phase 4.
    """

    def __init__(self, config_path: str = "/etc/kimi/skills/sandbox-executor.yaml"):
        """
        Initialize executor with global configuration.
        """
        ...

    def run(self, request: ExecutionRequest) -> ExecutionResult:
        """
        Execute a command inside an ephemeral, isolated container.

        Steps:
          1. Load skill's sandbox-config.yaml (including executable_allowlist)
          2. PolicyEngine.validate(request, declared_capabilities)
          3. Validate requested command against executable_allowlist
          4. Pull/verify image (SHA-256)
          5. Build docker run args (read-only, tmpfs, network, resources, seccomp)
          6. Launch container and execute
          7. Capture stdout/stderr/exit_code
          8. Destroy container
          9. Log audit record
          10. Return ExecutionResult

        Raises:
          PolicyViolationError:     capability mismatch, policy denial, or allowlist violation
          ImageVerificationError:   SHA-256 mismatch or untrusted registry
          ResourceExhaustedError:   memory/CPU/pids limit hit
          TimeoutExceededError:     wall-clock timeout exceeded
          SandboxRuntimeError:      unexpected Docker/container failure
        """
        ...

    def validate_capabilities(self, skill_name: str,
                              requested: CapabilitySet) -> bool:
        """
        Check requested capabilities against skill's declared manifest.
        Returns True only if policy approves; raises PolicyViolationError otherwise.
        """
        ...

    def verify_image(self, image: str, expected_sha256: str | None) -> str:
        """
        Pull image if missing, verify SHA-256, return resolved digest.
        Raises ImageVerificationError on mismatch.
        """
        ...

    def build_docker_args(self, request: ExecutionRequest,
                          declared: CapabilitySet) -> list[str]:
        """
        Construct the full `docker run` argument list enforcing safety rules.
        Includes seccomp profile or minimal /bin mount derived from executable_allowlist.
        """
        ...
```

### 7.2 Data Classes

```python
@dataclass
class ExecutionRequest:
    request_id: str
    skill_name: str
    command: list[str]
    working_directory: str
    source_mounts: list[Mount]
    environment: dict[str, str]
    capabilities: CapabilitySet
    image: str
    expected_sha256: str | None

@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    execution_time_ms: int
    container_hash: str
    audit_log_id: str

@dataclass
class CapabilitySet:
    network: bool
    whitelisted_domains: list[str]
    fs_write_paths: list[str]
    max_memory_mb: int
    max_cpus: float
    timeout_seconds: int
    allow_privileged: bool
    seccomp_profile: str
```

---

## 8. Integration Points

### 8.1 Downstream Consumers (ALL Phase 4 Skills)

| Skill | Image | Typical Capabilities |
|:---|:---|:---|
| `code-tester` | `python:3.11-slim` | network=false, memory=1GB, timeout=300s |
| `refactoring-engine` | `python:3.11-slim` | network=false, memory=2GB, timeout=120s |
| `security-auditor` | `python:3.11-slim` + bandit/safety | network=false, memory=512MB, timeout=600s |
| `performance-validator` | `python:3.11-slim` + profiling tools | network=false, memory=2GB, timeout=300s |
| `resilience-tester` | `python:3.11-slim` + chaos tools | network=false, memory=1GB, timeout=600s |

### 8.2 Upstream Dependencies

| Component | Role |
|:---|:---|
| `tool-execution-gateway` | Intercepts raw `subprocess` calls and routes to `SandboxExecutor.run()` |
| `policy-engine` | Validates `ExecutionRequest.capabilities` against skill's `sandbox-config.yaml` and enforces `executable_allowlist` |
| `error-policy` | Receives `SandboxRuntimeError`, `TimeoutExceededError`, etc., and triggers retry/escalate/abort |

---

## 9. Error Handling & Recovery

| Exception | Trigger | Recovery via `error-policy` |
|:---|:---|:---|
| `PolicyViolationError` | Capability mismatch, over-request, allowlist violation, or policy denial | **Abort** — log and escalate to human |
| `ImageVerificationError` | SHA-256 mismatch, untrusted registry | **Abort** — security incident, do not retry |
| `ResourceExhaustedError` | OOM, CPU throttling, pids limit | **Retry** with 2× resource limit (once), then escalate |
| `TimeoutExceededError` | Wall-clock timeout hit | **Retry** with 2× timeout (once), then escalate |
| `SandboxRuntimeError` | Docker daemon failure, container start failure | **Retry** (max 2×), then escalate |

---

## 10. Testing

### 10.1 Unit Tests
- Mock Docker client to verify argument construction
- Capability validation matrix (approve/deny cases)
- Image verification success and failure paths
- Allowlist pattern matching (exact, prefix, wildcard, extra args)

### 10.2 Integration Tests
- Launch real containers, verify `--read-only` enforcement
- Verify network isolation (`curl` to internet fails)
- Verify `/tmp` writability and auto-cleanup
- Verify resource caps (memory bomb OOMs, not host)
- Verify seccomp default blocks dangerous syscalls
- Verify allowlist enforcement blocks unauthorized binaries
- Verify minimal `/bin` mount only exposes allowlisted binaries

### 10.3 Negative Tests
- Attempted `--privileged` escalation (must fail without human approval)
- Attempted writable host mount outside `/tmp` (must fail)
- Attempted network access without declaration (must fail)
- SHA-256 mismatch (must fail before container start)
- Missing `executable_allowlist` (must fail at policy gate)
- Disallowed binary path or args (must fail at policy gate)
- Forbidden shell interpreter in allowlist (validator must reject)

---

## 11. File Layout

```
/mnt/agents/output/sandbox-executor/
├── SKILL.md                          # This file
├── scripts/
│   ├── sandbox-executor.py           # Executor implementation template
│   ├── run-skill-sandboxed.py        # Sandboxed runner helper
│   ├── sandboxed_runner.py           # Sandboxed runner implementation
│   └── validate_allowlist.py         # CLI validator for sandbox-config.yaml allowlists
├── references/
│   ├── capability-manifest.md        # Capability declaration format spec
│   ├── allowlist_schema.md           # Complete schema definition for executable_allowlist
│   └── seccomp_policy_examples.md    # Example seccomp-BPF JSON profiles for Docker and containerd
├── examples/
│   ├── sandbox-config.python.yaml    # Example config for Python skill
│   └── sandbox-config.node.yaml      # Example config for Node.js skill
└── tests/
    └── test_executor.py              # Unit + integration test scaffold
```

---

## 12. Multi-Model Router Integration

The `multi-model-router` skill requires a controlled persistent mount for its atomic daily request counter and billing ledger. This is implemented as a policy exception:

```yaml
# sandbox-executor.yaml — multi-model-router exception
special_mounts:
  - skill: "multi-model-router"
    host: "~/.kimi/state"
    container: "/var/lib/kimi/multi-model-counter"
    mode: "rw"
    max_size_bytes: 1048576  # 1MB cap
    allowed_files:
      - "multi-model-counter.json"
      - "user-provider-preference.json"
    audit: true
```

The mount is:
- **Size-capped** at 1MB
- **File-restricted**: Only `multi-model-counter.json` and `user-provider-preference.json` may be written
- **Audit-logged**: Every write is recorded in the policy-engine audit trail
- **Skill-scoped**: Only `multi-model-router` receives this mount; other skills do not

This exception is governed by policy rule `MULTI-MODEL-001` (see `multi-model-router/SKILL.md`).

## 13. Changelog

| Version | Date | Change |
|:---|:---|:---|
| 4.0.0 | 2025-01 | Initial release — containerized execution replaces all bare `subprocess` (IMP-3, ARC-4.4) |
| 4.1.0 | 2025-05 | E2B cloud sandbox backend added — Docker-less execution via MCP server or Python SDK (INF-5, ARC-7.2) |
| 4.2.0 | 2025-05 | Executable allowlist enforcement merged from `sandbox-allowlist-enforcer` — seccomp-BPF filter generation, minimal `/bin` mount assembly, and `scripts/validate_allowlist.py` (SEC-8, ARC-7.3) |

---

## 13. References

- [capability-manifest.md](./references/capability-manifest.md)
- [allowlist_schema.md](./references/allowlist_schema.md)
- [seccomp_policy_examples.md](./references/seccomp_policy_examples.md)
- [sandbox-executor.py](./scripts/sandbox-executor.py)
- [validate_allowlist.py](./scripts/validate_allowlist.py)
- Docker Security: https://docs.docker.com/engine/security/
- E2B Docs: https://e2b.dev/docs
- E2B MCP Server: https://github.com/e2b-dev/mcp-server
- seccomp profiles: https://docs.docker.com/engine/security/seccomp/
