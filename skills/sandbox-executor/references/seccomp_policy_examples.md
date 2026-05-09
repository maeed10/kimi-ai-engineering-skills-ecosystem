# seccomp-BPF Policy Examples

## Document Purpose

This reference provides ready-to-adapt seccomp-BPF JSON profiles for Docker and
containerd. Each profile is derived from a skill's `executable_allowlist` and can be
generated programmatically with `scripts/validate_allowlist.py --emit-seccomp`.

## Profile Design Principles

1. **Default deny for execve** — `SCMP_ACT_ERRNO(EPERM)` unless the path is allowlisted.
2. **Baseline syscalls always allowed** — see `references/allowlist_schema.md` for the
   mandatory baseline set.
3. **Architecture-specific** — profiles target `SCMP_ARCH_X86_64` and `SCMP_ARCH_X86`
   by default. Add `SCMP_ARCH_AARCH64` for ARM64 images.
4. **No capabilities implied** — seccomp does not grant capabilities; it only restricts
   syscalls. Drop all capabilities in the container spec separately.

## Minimal Default-Deny Profile

This profile blocks everything except the baseline and a single allowlisted binary
(`/usr/bin/python3`). It uses an `execveat` rule with `SCMP_ACT_ALLOW` only for that
path, and a catch-all `execve` rule with `SCMP_ACT_ERRNO(EPERM)`.

> Note: Native seccomp-BPF cannot inspect string arguments inside the kernel. The
> `execve` path filter below relies on the userspace wrapper (e.g., `libminijail`,
> `bwrap --seccomp`, or a custom LD_PRELOAD) to normalize the path before the syscall.
> If you use pure Docker `--security-opt seccomp=...`, supplement it with AppArmor or
> the minimal `/bin` mount technique described in `SKILL.md`.

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "archMap": [
    {
      "architecture": "SCMP_ARCH_X86_64",
      "subArchitectures": [
        "SCMP_ARCH_X86"
      ]
    }
  ],
  "syscalls": [
    {
      "names": [
        "read",
        "write",
        "close",
        "exit",
        "exit_group",
        "brk",
        "mmap",
        "munmap",
        "mprotect",
        "sigreturn",
        "rt_sigreturn",
        "rt_sigaction",
        "futex",
        "clock_gettime",
        "gettimeofday"
      ],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": [
        "open",
        "openat",
        "fstat",
        "lseek",
        "pread64",
        "access",
        "getdents64",
        "getrandom",
        "clone",
        "wait4",
        "getpid",
        "getppid",
        "geteuid",
        "getgid",
        "arch_prctl",
        "set_tid_address",
        "set_robust_list",
        "prlimit64",
        "stat",
        "lstat",
        "ioctl"
      ],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": [
        "socket",
        "connect",
        "sendto",
        "recvfrom"
      ],
      "action": "SCMP_ACT_ALLOW",
      "includes": {
        "caps": ["NET_RAW"]
      }
    },
    {
      "names": [
        "execve",
        "execveat"
      ],
      "action": "SCMP_ACT_ERRNO",
      "args": [
        {
          "index": 0,
          "type": "SCMP_APATH",
          "op": "SCMP_CMP_NE",
          "value": "/usr/bin/python3"
        }
      ]
    },
    {
      "names": [
        "execve",
        "execveat"
      ],
      "action": "SCMP_ACT_ALLOW",
      "args": [
        {
          "index": 0,
          "type": "SCMP_APATH",
          "op": "SCMP_CMP_EQ",
          "value": "/usr/bin/python3"
        }
      ]
    }
  ]
}
```

## Python-Only Skill Profile

Use this when the skill only needs `python3` with no network access.

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "archMap": [
    {
      "architecture": "SCMP_ARCH_X86_64",
      "subArchitectures": [
        "SCMP_ARCH_X86"
      ]
    }
  ],
  "syscalls": [
    {
      "names": [
        "read",
        "write",
        "close",
        "exit",
        "exit_group",
        "brk",
        "mmap",
        "munmap",
        "mprotect",
        "sigreturn",
        "rt_sigreturn",
        "rt_sigaction",
        "rt_sigprocmask",
        "futex",
        "clock_gettime",
        "clock_nanosleep",
        "gettimeofday",
        "getpid",
        "getppid",
        "geteuid",
        "getgid",
        "getrandom",
        "arch_prctl",
        "set_tid_address",
        "set_robust_list",
        "prlimit64",
        "pread64",
        "lseek",
        "fstat",
        "stat",
        "lstat",
        "access",
        "open",
        "openat",
        "ioctl",
        "getdents64"
      ],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": [
        "execve",
        "execveat"
      ],
      "action": "SCMP_ACT_ALLOW",
      "args": [
        {
          "index": 0,
          "type": "SCMP_APATH",
          "op": "SCMP_CMP_EQ",
          "value": "/usr/bin/python3"
        }
      ]
    }
  ]
}
```

## Network-Auditor Skill Profile

Use this when the skill needs TCP scanning or network diagnostics.

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "archMap": [
    {
      "architecture": "SCMP_ARCH_X86_64",
      "subArchitectures": [
        "SCMP_ARCH_X86"
      ]
    }
  ],
  "syscalls": [
    {
      "names": [
        "read",
        "write",
        "close",
        "exit",
        "exit_group",
        "brk",
        "mmap",
        "munmap",
        "mprotect",
        "sigreturn",
        "rt_sigreturn",
        "rt_sigaction",
        "rt_sigprocmask",
        "futex",
        "clock_gettime",
        "clock_nanosleep",
        "gettimeofday",
        "getpid",
        "getppid",
        "geteuid",
        "getgid",
        "getrandom",
        "arch_prctl",
        "set_tid_address",
        "set_robust_list",
        "prlimit64",
        "pread64",
        "lseek",
        "fstat",
        "stat",
        "lstat",
        "access",
        "open",
        "openat",
        "ioctl",
        "getdents64",
        "clone",
        "wait4",
        "socket",
        "connect",
        "sendto",
        "recvfrom",
        "recvmsg",
        "sendmsg",
        "shutdown",
        "bind",
        "listen",
        "accept",
        "getsockname",
        "getpeername",
        "setsockopt",
        "getsockopt"
      ],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": [
        "execve",
        "execveat"
      ],
      "action": "SCMP_ACT_ALLOW",
      "args": [
        {
          "index": 0,
          "type": "SCMP_APATH",
          "op": "SCMP_CMP_EQ",
          "value": "/usr/bin/nmap"
        }
      ]
    }
  ]
}
```

## Git-Diff-Only Skill Profile

Use this for skills that only need `git diff --no-index` and `git log`.

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "archMap": [
    {
      "architecture": "SCMP_ARCH_X86_64",
      "subArchitectures": [
        "SCMP_ARCH_X86"
      ]
    }
  ],
  "syscalls": [
    {
      "names": [
        "read",
        "write",
        "close",
        "exit",
        "exit_group",
        "brk",
        "mmap",
        "munmap",
        "mprotect",
        "sigreturn",
        "rt_sigreturn",
        "rt_sigaction",
        "rt_sigprocmask",
        "futex",
        "clock_gettime",
        "gettimeofday",
        "getpid",
        "getppid",
        "geteuid",
        "getgid",
        "getrandom",
        "arch_prctl",
        "set_tid_address",
        "set_robust_list",
        "prlimit64",
        "pread64",
        "lseek",
        "fstat",
        "stat",
        "lstat",
        "access",
        "open",
        "openat",
        "ioctl",
        "getdents64",
        "pipe",
        "pipe2",
        "dup2",
        "clone",
        "wait4",
        "execve",
        "execveat"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

> For `git`, argument enforcement is more important than path enforcement because `git`
> itself can invoke arbitrary hooks and external commands. Always pair this profile with:
> - `GIT_CONFIG_GLOBAL=/dev/null` to disable user-level git config.
> - `GIT_EXEC_PATH=/usr/lib/git-core` pointing to a minimal, allowlisted git installation.
> - A policy-engine check that only permits `diff --no-index` and `log -1 --format=%H`.

## Containerd / CRI-O Usage

For Kubernetes or containerd, embed the JSON profile in a Pod Security Context:

```yaml
apiVersion: v1
kind: Pod
spec:
  securityContext:
    seccompProfile:
      type: Localhost
      localhostProfile: "sandbox-allowlists/python-only.json"
  containers:
    - name: sandbox
      image: python:3.11-slim
      command: ["/usr/bin/python3", "-m", "pytest"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
```

## Docker Usage

```bash
docker run \
  --security-opt seccomp=/path/to/profile.json \
  --cap-drop ALL \
  --read-only \
  --tmpfs /tmp:noexec,nosuid,size=100m \
  my-sandbox-image \
  /usr/bin/python3 -m pytest
```

## Generating Profiles from Configs

```bash
# Validate config and emit a seccomp profile
python scripts/validate_allowlist.py \
  --config ./sandbox-config.yaml \
  --emit-seccomp ./profile.json

# Validate and also write a minimal /bin overlay
python scripts/validate_allowlist.py \
  --config ./sandbox-config.yaml \
  --emit-minibin ./mini_bin/
```
