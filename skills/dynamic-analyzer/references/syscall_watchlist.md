# Syscall Watchlist

## Classification Key

- **EXPECTED**: Normal for the language/runtime; log only
- **SUSPICIOUS**: Unusual but possibly legitimate; flag in report
- **MALICIOUS**: Strong indicator of malicious intent; block delivery
- **CONDITIONAL**: Expected in some contexts; validate against allowlist

---

## Network Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `socket(AF_UNIX)` | EXPECTED | IPC between parent/child | Always allowed |
| `socket(AF_INET)` | SUSPICIOUS | None in sandbox | Any occurrence |
| `socket(AF_INET6)` | SUSPICIOUS | None in sandbox | Any occurrence |
| `socket(AF_NETLINK)` | SUSPICIOUS | None in sandbox | Any occurrence |
| `connect` | MALICIOUS | None | Any occurrence (even if blocked) |
| `bind` | SUSPICIOUS | None in sandbox | Any occurrence |
| `listen` | MALICIOUS | None in sandbox | Any occurrence |
| `accept` / `accept4` | MALICIOUS | None in sandbox | Any occurrence |
| `sendto` / `sendmsg` / `sendmmsg` | MALICIOUS | None | Any occurrence |
| `recvfrom` / `recvmsg` / `recvmmsg` | CONDITIONAL | Only if preceded by allowed socket | Validate against allowlist |
| `setsockopt` | SUSPICIOUS | Rarely needed | Unusual option flags |
| `gethostbyname` / `getaddrinfo` | MALICIOUS | DNS resolution blocked | Any occurrence |

## Process Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `execve` | CONDITIONAL | Explicitly allowlisted subprocesses | Binary not in allowlist |
| `execveat` | MALICIOUS | Rarely legitimate | Any occurrence |
| `fork` / `clone` / `vfork` | CONDITIONAL | Some runtimes use threads | Unexpected child processes |
| `wait4` / `waitpid` | EXPECTED | Normal after fork | Always allowed |
| `kill` / `tkill` / `tgkill` | SUSPICIOUS | Signal handling | Target PID outside process group |
| `ptrace` | MALICIOUS | None in production code | Any occurrence |
| `setuid` / `setgid` / `setreuid` / `setregid` | MALICIOUS | Privilege escalation | Any occurrence |
| `setns` / `unshare` | MALICIOUS | Namespace manipulation | Any occurrence |
| `capset` / `prctl(PR_SET_SECUREBITS)` | MALICIOUS | Capability manipulation | Any occurrence |
| `system` (via libc) | MALICIOUS | Shell execution | Any occurrence (detected via execve of /bin/sh) |
| `popen` (via libc) | MALICIOUS | Shell execution | Any occurrence (detected via execve of /bin/sh) |

## Filesystem Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `open` / `openat` (read, allowed path) | EXPECTED | Reading declared inputs | Path in allowlist |
| `open` / `openat` (read, disallowed path) | SUSPICIOUS | Accessing undeclared files | Path outside declared read_paths |
| `open` / `openat` (write, allowed path) | EXPECTED | Writing declared outputs | Path in write_paths |
| `open` / `openat` (write, disallowed path) | SUSPICIOUS | Writing outside allowed zone | Path outside write_paths |
| `open` / `openat` (write, sensitive path) | MALICIOUS | System modification | Path in /etc, /bin, /usr/bin, /lib |
| `creat` | CONDITIONAL | File creation | Path validation required |
| `unlink` / `unlinkat` (own files) | EXPECTED | Cleanup of temp files | File created by same process |
| `unlink` / `unlinkat` (other files) | SUSPICIOUS | Destructive behavior | File not created by this process |
| `rmdir` | SUSPICIOUS | Directory removal | Any occurrence |
| `rename` / `renameat` | CONDITIONAL | File moves within workspace | Source and dest validation |
| `chmod` / `fchmod` / `fchmodat` | SUSPICIOUS | Permission changes | Any SUID/SGID bit set |
| `chown` / `fchown` / `lchown` | MALICIOUS | Ownership changes | Any occurrence |
| `symlink` / `symlinkat` | SUSPICIOUS | Symlink creation | Target path validation |
| `link` / `linkat` | SUSPICIOUS | Hardlink creation | Any occurrence |
| `mknod` | MALICIOUS | Device file creation | Any occurrence |
| `mount` / `umount` / `umount2` | MALICIOUS | Filesystem mounting | Any occurrence |
| `pivot_root` | MALICIOUS | Root filesystem pivot | Any occurrence |
| `chroot` | MALICIOUS | Chroot jailbreak attempt | Any occurrence |

## Memory Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `mmap` / `mmap2` / `mprotect` | EXPECTED | Normal memory management | Always allowed |
| `mprotect(PROT_EXEC)` | CONDITIONAL | JIT compilation, some runtimes | If combined with network syscalls |
| `memfd_create` | SUSPICIOUS | Fileless execution technique | Any occurrence |
| `shmat` / `shmget` | CONDITIONAL | Shared memory IPC | Validate against expected usage |

## Timing Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `clock_gettime` | EXPECTED | Normal time queries | >1000 calls/sec |
| `gettimeofday` | EXPECTED | Normal time queries | >1000 calls/sec |
| `nanosleep` / `clock_nanosleep` | EXPECTED | Normal delays | Total sleep >10s or >100 calls |
| `alarm` / `setitimer` | SUSPICIOUS | Signal-based timers | Any occurrence |
| `timer_create` / `timer_settime` | SUSPICIOUS | Async timers | Any occurrence |

## Information Gathering Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `uname` | EXPECTED | OS info for compatibility | Always allowed |
| `sysinfo` | EXPECTED | System resource info | Always allowed |
| `getpid` / `getppid` / `getpgrp` | EXPECTED | Process info | Always allowed |
| `getuid` / `geteuid` / `getgid` | EXPECTED | Identity checks | Always allowed |
| `getcwd` | EXPECTED | Path queries | Always allowed |
| `readlink` / `readlinkat` | EXPECTED | Symbolic link resolution | Always allowed |
| `/proc/self/maps` read | SUSPICIOUS | Memory layout inspection | If combined with network/file anomalies |
| `/proc/self/exe` read | EXPECTED | Some runtimes need this | Always allowed |
| `/proc/[pid]/...` read (other pids) | SUSPICIOUS | Process enumeration | Any occurrence |
| `/etc/passwd` read | SUSPICIOUS | User enumeration | Any occurrence |
| `/etc/shadow` read | MALICIOUS | Credential theft | Any occurrence |

## Signal Syscalls

| Syscall | Classification | Expected Context | Flag Condition |
|---------|---------------|------------------|----------------|
| `sigaction` / `rt_sigaction` | EXPECTED | Signal handling setup | Always allowed |
| `sigreturn` / `rt_sigreturn` | EXPECTED | Signal return | Always allowed |
| `signalfd` / `signalfd4` | CONDITIONAL | Signal file descriptors | Validate context |

## Expected Patterns by Language

### Python
- EXPECTED: heavy `mmap`, `read`, `write`, `fstat`, `getdents64`, `brk`, `clock_gettime`
- EXPECTED: `socket(AF_UNIX)` for multiprocessing
- SUSPICIOUS: `socket(AF_INET)` from standard library (requests, urllib, http.client)
- SUSPICIOUS: `execve` of non-Python binaries

### Node.js
- EXPECTED: `epoll_wait` / `poll`, heavy `fstat`, `read`, `write`
- EXPECTED: `socket(AF_UNIX)` for cluster module
- SUSPICIOUS: `socket(AF_INET)` from core modules (net, http, https, dns)

### Go
- EXPECTED: `futex`, `epoll_wait`, `read`, `write`
- EXPECTED: `clone` for goroutines
- SUSPICIOUS: `socket(AF_INET)` from net/http packages

### Rust
- EXPECTED: `futex`, `read`, `write`, `mmap`, `mprotect`
- SUSPICIOUS: `socket(AF_INET)` from std::net or external crates

## Composite Indicators (Multiple Syscalls)

Flag as CRITICAL when these syscall combinations appear:

1. **`socket` + `connect` + `execve`**: C2 bot behavior
2. **`socket` + `dup2` + `execve`**: Reverse shell
3. **`ptrace` + `process_vm_writev`**: Process injection
4. **`memfd_create` + `fexecve` / `execve`**: Fileless execution
5. **`socket` + `open`(/etc/shadow) + `sendto`**: Data exfiltration
6. **`clone(CLONE_NEWUSER)` + `setuid(0)`**: Container escape attempt
7. **`open`(/proc/self/maps) + `mprotect(PROT_EXEC)` + network**: Self-modifying network code
