---
name: sandbox-allowlist-enforcer
description: |
  Enforces process-level least privilege inside sandboxes by maintaining executable
  allowlists in sandbox-config.yaml and blocking unauthorized binaries via seccomp-BPF
  or minimal /bin mounts. Use whenever defining sandbox configurations, preparing
  container execution, or validating skill capability declarations. Ensures only
  approved commands run inside isolated environments.
---

# Sandbox Allowlist Enforcer

## Overview

The policy engine validates *what* the LLM can request (network, paths) but not *which*
binaries can execute. This skill closes that gap by extending `sandbox-config.yaml` with an
`executable_allowlist` block and enforcing it at the kernel boundary via seccomp-BPF
filters or minimal bind mounts of `/bin`.

Key outcomes:
- Every skill declares exactly which binaries it needs and their allowed argument patterns.
- The policy engine rejects execution requests that violate the declared allowlist.
- The sandbox executor loads a seccomp-BPF filter or read-only `/bin` mount that blocks
  any `execve` outside the allowlist.

## When to Use This Skill

- **Defining `sandbox-config.yaml` for any new or updated skill** — add the
  `executable_allowlist` block and validate it with `scripts/validate_allowlist.py`.
- **Preparing a sandbox container** (`sandbox-executor`) — before `docker run`, load
  the seccomp profile generated from the skill's allowlist, or assemble a minimal
  `/bin` directory containing only allowed symlinks.
- **Validating a sandbox execution request** (`policy-engine`) — reject the request if
  the requested command is not on the allowlist or uses disallowed arguments.
- **Reviewing skill configurations for least-privilege compliance** — run the
  validation script against the YAML and flag over-permissive entries (e.g.,
  `/bin/bash` with `args: ["*"]`).

## `executable_allowlist` Schema

The schema is a list under the top-level key `executable_allowlist` in
`sandbox-config.yaml`. Each entry specifies an absolute binary path, a list of allowed
argument patterns, optional syscall restrictions, and optional environment variable rules.

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

Full schema specification lives in `references/allowlist_schema.md`.

## Enforcement Mechanisms

### 1. seccomp-BPF Filter (Preferred)

Generate a seccomp-BPF profile from the allowlist and pass it to the container runtime.
The profile must:
- Allow `execve`/`execveat` only when the target path matches an allowlisted entry.
- Block `execve` with `errno=EPERM` for all other paths.
- Optionally restrict the argument vector against declared patterns.

Because seccomp-BPF cannot easily introspect string arguments at filter-load time, the
pattern enforcement is typically split:
- **Path enforcement** — seccomp-BPF (kernel, unavoidable).
- **Argument enforcement** — LSM/AppArmor or a lightweight userspace wrapper (e.g.,
  `libminijail` or a small preload) that validates `argv` before calling the real
  `execve`.

For pure seccomp, a practical compromise is to allow `execve` for the allowlisted
binary and rely on the policy engine (userspace) to pre-validate arguments before the
container starts.

See `references/seccomp_policy_examples.md` for ready-to-adapt JSON profiles.

### 2. Minimal `/bin` Bind Mount (Fallback)

When seccomp is unavailable or the environment uses a read-only rootfs:
1. Create a temporary directory `mini_bin/`.
2. For each allowlisted binary, create a symlink: `mini_bin/$(basename $path) -> $path`.
3. Also symlink any required shared libraries or interpreter paths (e.g., `/lib64`).
4. Bind-mount `mini_bin/` into the container as `/bin:ro`.
5. Set `PATH=/bin` inside the container.

This is coarser than seccomp (a symlink could be abused if the target is a shell) but
is portable and requires no kernel BPF support.

## Policy-Engine Integration Rules

Before creating a container, the policy engine must perform these checks in order:

1. **Allowlist Presence** — If `sandbox-config.yaml` lacks `executable_allowlist`, reject
   the request with `SANDBOX_CONFIG_MISSING_ALLOWLIST`.
2. **Path Match** — The requested command's absolute path must match an `executable_allowlist.path`
   entry exactly. No PATH resolution inside the sandbox; the policy engine resolves it.
3. **Argument Match** — The requested `argv[1:]` must match at least one `pattern` for that
   path. Literal strings are matched exactly; a trailing `"*"` wildcard in the pattern
   permits any additional arguments after the prefix.
4. **Process Limit** — The total number of concurrent processes must not exceed the sum of
   `max_processes` across all allowlisted entries (default 1 per entry if omitted).
5. **Syscall Audit** — If `allowed_syscalls` is present, the generated seccomp profile must
   drop all syscalls not explicitly listed (plus the mandatory baseline: `read`, `write`,
   `close`, `exit`, `exit_group`, `brk`, `mmap`, `munmap`, `mprotect`, `sigreturn`,
   `rt_sigreturn`, `rt_sigaction`).

If any check fails, the policy engine returns `EXECUTION_DENIED` with a structured reason
field:

```json
{
  "decision": "DENY",
  "reason_code": "ARGS_MISMATCH",
  "allowlist_entry": "/usr/bin/python3",
  "requested_args": ["-m", "pip", "install", "requests"],
  "message": "Requested args do not match any declared pattern for /usr/bin/python3"
}
```

## Example Configs for Common Skills

### code-tester

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

### security-auditor

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

### static-analyzer (clang-based)

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

## Validation Workflow

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
- `allowed_syscalls` includes a blocked syscall (`execveat` with no path restriction,
  `ptrace`, `personality`, `mount`, `umount2`).
- `--strict-syscalls` is set and the baseline mandatory syscalls are missing.

## Resources

| Path | Purpose |
|------|---------|
| `references/allowlist_schema.md` | Complete schema definition for `executable_allowlist` |
| `references/seccomp_policy_examples.md` | Example seccomp-BPF JSON profiles for Docker and containerd |
| `scripts/validate_allowlist.py` | CLI validator for sandbox-config.yaml allowlists |

## Remediation Checklist

- [ ] `sandbox-config.yaml` contains `executable_allowlist` with at least one entry.
- [ ] Every entry has an absolute `path` and at least one `args` pattern.
- [ ] No entry allows `/bin/sh`, `/bin/bash`, or `/usr/bin/python3` with unrestricted
      `args` (use `pattern` prefixes and `allow_extra_args` sparingly).
- [ ] Policy engine validates the requested command against the allowlist before creating
      the container.
- [ ] Sandbox executor loads a seccomp profile or minimal `/bin` mount derived from the
      allowlist.
- [ ] `scripts/validate_allowlist.py` passes in CI for every skill change.
