# Allowlist Schema Definition

## Document Purpose

This reference defines the exact schema for the `executable_allowlist` block inside
`sandbox-config.yaml`. It is consumed by the policy engine, the sandbox executor, and
the validation script `scripts/validate_allowlist.py`.

## Top-Level Key

```yaml
executable_allowlist:
  - ...
  - ...
```

- **Type**: list of `AllowlistEntry`
- **Required**: yes (absence or empty list causes validation failure)
- **Max entries**: 10 (configurable in validator with `--max-entries`)

## AllowlistEntry

### `path`
- **Type**: string
- **Required**: yes
- **Format**: absolute path beginning with `/`. No relative segments (`..`) allowed.
- **Example**: `/usr/bin/python3`
- **Validation**: must exist in the container image at policy-check time or be a known
  interpreter path declared by the skill manifest.

### `args`
- **Type**: list of `ArgPattern`
- **Required**: yes (at least one pattern per entry)

#### ArgPattern

##### `pattern`
- **Type**: list of strings
- **Required**: yes
- **Semantics**: `argv[1:]` must match this sequence exactly, unless `allow_extra_args`
  is true, in which case extra trailing arguments are permitted.
- **Wildcard**: the literal string `"*"` in the last position matches any single token.
  Use `allow_extra_args` to match an arbitrary suffix.
- **Forbidden values**: no shell metacharacters (`;`, `|`, `&`, `$(`, `` ` ``, `>`, `<`).

##### `allow_extra_args`
- **Type**: boolean
- **Required**: no, default `false`
- **Semantics**: when `true`, the caller may append additional arguments after the
  `pattern` prefix. The prefix itself must still match exactly.

### `env`
- **Type**: list of `EnvRule`
- **Required**: no

#### EnvRule

##### `name`
- **Type**: string
- **Required**: yes
- **Validation**: must match `^[A-Z_][A-Z0-9_]*$`.

##### `value`
- **Type**: string
- **Required**: no
- **Semantics**: if present, the environment variable must equal this exact string.

##### `value_regex`
- **Type**: string (regex)
- **Required**: no
- **Semantics**: if present, the environment variable must match this regex. Mutually
  exclusive with `value`.

### `max_processes`
- **Type**: integer
- **Required**: no, default `1`
- **Range**: 1..64
- **Semantics**: maximum number of concurrent processes spawned by this binary. The
  sandbox executor enforces this via `pids.max` in the container cgroup or rlimit.

### `allowed_syscalls`
- **Type**: list of strings (syscall names as defined in `seccomp(2)`)
- **Required**: no
- **Semantics**: if provided, the seccomp profile drops every syscall except those
  listed plus the mandatory baseline. If omitted, the profile uses a broad default
  allowlist (read, write, network, file ops) instead of a restrictive one.

#### Mandatory Baseline (always allowed even if omitted from `allowed_syscalls`)
- `read`, `write`, `close`
- `exit`, `exit_group`
- `brk`, `mmap`, `munmap`, `mprotect`
- `sigreturn`, `rt_sigreturn`, `rt_sigaction`
- `futex`, `clock_gettime`, `gettimeofday`

#### Blocked Syscalls (never allowed, validator rejects configs that list them)
- `ptrace` — process tracing
- `personality` — change execution domain
- `mount`, `umount2` — filesystem mounting
- `reboot`, `kexec_load` — system control
- `open_by_handle_at` — direct handle access
- `init_module`, `finit_module` — kernel module loading

## Full Example

```yaml
executable_allowlist:
  - path: /usr/bin/python3
    args:
      - pattern: ["-m", "pytest", "-x"]
        allow_extra_args: true
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
      - open
      - openat
      - close
      - fstat
      - lseek
      - mmap
      - mprotect
      - munmap
      - brk
      - rt_sigaction
      - rt_sigprocmask
      - ioctl
      - pread64
      - access
      - getdents64
      - getrandom
      - exit
      - exit_group
      - clone
      - wait4
      - getpid
      - getppid
      - socket
      - connect
      - sendto
      - recvfrom
      - geteuid
      - getgid
      - arch_prctl
      - set_tid_address
      - set_robust_list
      - prlimit64
      - futex
      - clock_gettime
      - clock_nanosleep
      - stat
      - lstat

  - path: /usr/bin/git
    args:
      - pattern: ["diff", "--no-index"]
      - pattern: ["log", "-1", "--format=%H"]
    max_processes: 1
```

## JSON Schema (Pydantic-style pseudocode)

```python
class EnvRule(BaseModel):
    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    value: Optional[str] = None
    value_regex: Optional[str] = None

    @model_validator(mode="after")
    def check_exclusive(self):
        if self.value is not None and self.value_regex is not None:
            raise ValueError("env rule must have 'value' or 'value_regex', not both")
        return self

class ArgPattern(BaseModel):
    pattern: list[str]
    allow_extra_args: bool = False

class AllowlistEntry(BaseModel):
    path: str = Field(pattern=r"^/[^.]*$")
    args: list[ArgPattern] = Field(min_length=1)
    env: list[EnvRule] = []
    max_processes: int = Field(default=1, ge=1, le=64)
    allowed_syscalls: list[str] = []

class SandboxConfig(BaseModel):
    executable_allowlist: list[AllowlistEntry] = Field(min_length=1, max_length=10)
```

## Version

Schema version: `1.0.0`
