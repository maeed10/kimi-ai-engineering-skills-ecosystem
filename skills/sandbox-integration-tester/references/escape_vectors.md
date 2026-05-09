# Container Escape Vectors — Test Payload Catalog

> **Purpose**: Each entry defines a known container escape technique, the exact payload used to trigger it, and the expected behavior when isolation is correctly enforced. The test runner (`scripts/run_isolation_tests.py`) executes these payloads inside real containers and asserts the expected failure mode.

---

## Legend

- **Severity**: `CRITICAL` = full host compromise; `HIGH` = host info leak or partial breakout; `MEDIUM` = DoS or resource abuse.
- **Backends**: `D` = Docker, `N` = nerdctl, `E` = E2B.
- **Prerequisites**: Misconfigurations that make the vector exploitable.
- **Expected Failure**: What a properly isolated container or sandbox must do when the payload runs.

---

## EV-001 — Privileged Container Escape

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-001` |
| **Severity** | `CRITICAL` |
| **Backends** | D, N |
| **Prerequisites** | Container started with `--privileged` or `securityContext.privileged: true` |

### Description
A privileged container shares the host's devices, has full capabilities, and often runs in the host's namespaces. An attacker can mount the host root filesystem and chroot into it.

### Test Payload
```bash
# Inside the container
mkdir -p /host && mount /dev/sda1 /host 2>/dev/null || mount /dev/vda1 /host 2>/dev/null
ls /host/etc/shadow 2>/dev/null && echo "HOST_ROOT_VISIBLE"
```

Alternative Python payload (used by runner when `sh` is unavailable):
```python
import os, subprocess, sys
for dev in ("/dev/sda1", "/dev/vda1", "/dev/nvme0n1p1"):
    rc = subprocess.call(["mount", dev, "/host"], stderr=subprocess.DEVNULL)
    if rc == 0:
        if os.path.exists("/host/etc/shadow"):
            sys.stdout.write("HOST_ROOT_VISIBLE\n")
            sys.exit(0)
sys.stdout.write("MOUNT_BLOCKED\n")
sys.exit(1)
```

### Expected Failure Mode
- `mount` must return `EPERM` or `ENODEV`.
- The string `HOST_ROOT_VISIBLE` must **not** appear in stdout.
- Exit code must be non-zero.

### Detection Method
Test runner asserts:
1. Payload exit code != 0.
2. Stdout does not contain `HOST_ROOT_VISIBLE`.

---

## EV-002 — Kernel Module Loading

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-002` |
| **Severity** | `CRITICAL` |
| **Backends** | D, N |
| **Prerequisites** | Container retains `CAP_SYS_MODULE` |

### Description
If a container can load kernel modules, it can inject arbitrary code into the host kernel, bypassing all container boundaries.

### Test Payload
```bash
modprobe nonexistent_module_12345 2>&1 || insmod /dev/null 2>&1
echo "EXIT_CODE=$?"
```

Python payload:
```python
import subprocess, sys, os
# Try modprobe first
r1 = subprocess.run(["modprobe", "__sandbox_test"], capture_output=True)
# Fallback: try to open /proc/sys/kernel/modules_disabled
if os.path.exists("/proc/sys/kernel/modules_disabled"):
    with open("/proc/sys/kernel/modules_disabled") as f:
        val = f.read().strip()
        if val == "1":
            sys.stdout.write("MODULES_DISABLED\n")
            sys.exit(1)
sys.stdout.write(f"MODPROBE_RC={r1.returncode}\n")
sys.exit(0 if r1.returncode == 0 else 1)
```

### Expected Failure Mode
- `modprobe` / `insmod` fail with `EPERM` or `ENOENT`.
- `/proc/sys/kernel/modules_disabled` may be `1` (defense-in-depth).
- Container must not be able to influence host kernel modules.

### Detection Method
Runner asserts `MODPROBE_RC` is not `0` and `MODULES_DISABLED` is preferred but not required.

---

## EV-003 — Symlink / Mount Escape (FollowSymlink In The Middle)

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-003` |
| **Severity** | `HIGH` |
| **Backends** | D, N |
| **Prerequisites** | Container has a writable directory and can create symlinks; host path resolver follows symlinks |

### Description
An attacker creates a symlink inside the container that points to a host path. If a later host operation (e.g., `docker cp`, volume mount resolution) follows the symlink, the attacker can write to arbitrary host locations. This is the classic *FollowSymlinkInTheMiddle* class of bugs.

### Test Payload
```bash
# Inside container: create a bait symlink
mkdir -p /tmp/escape
ln -s /host_etc /tmp/escape/link
# Attempt to traverse it and read a host file
ls -la /tmp/escape/link/shadow 2>/dev/null && echo "FOLLOWED"
```

Python payload (runner internal):
```python
import os, tempfile, sys
with tempfile.TemporaryDirectory() as td:
    link = os.path.join(td, "link")
    os.symlink("/proc/1/root/etc", link)
    try:
        os.listdir(link)
        sys.stdout.write("FOLLOWED\n")
    except PermissionError:
        sys.stdout.write("BLOCKED_BY_SECCOMP_OR_PERMS\n")
    except OSError:
        sys.stdout.write("BLOCKED\n")
```

### Expected Failure Mode
- `readlink`, `openat`, or `listdir` on the symlink must fail with `EPERM`, `EACCES`, or `ENOENT`.
- The string `FOLLOWED` must not appear.

### Detection Method
Runner asserts no `FOLLOWED` in stdout and that `PermissionError` or `OSError` is raised.

---

## EV-004 — procfs Escape (`/proc/[pid]/root` & `/proc/self/cwd`)

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-004` |
| **Severity** | `HIGH` |
| **Backends** | D, N, E |
| **Prerequisites** | `/proc` is mounted without `hidepid=2` or namespace separation is weak |

### Description
`/proc/[pid]/root` is a magic symlink that resolves to the root directory of the process's mount namespace. If a container can access a host PID's `/proc/1/root`, it can traverse the host filesystem. Similarly, `/proc/self/cwd` tricks can be used to escape chroot-like jails.

### Test Payload
```bash
# Try to read host root via PID 1 (should be host init or containerd-shim)
ls /proc/1/root/etc/shadow 2>/dev/null && echo "PROCFS_ESCAPE"
# Try /proc/self/cwd escape
cd /tmp && ln -s /proc/self/cwd/../../../../etc/shadow leak
 cat leak 2>/dev/null && echo "CWD_ESCAPE"
```

Python payload:
```python
import os, sys
host_targets = ["/proc/1/root/etc/shadow", "/proc/1/root/etc/passwd"]
for t in host_targets:
    if os.path.exists(t):
        with open(t) as f:
            if "root:" in f.read(128):
                sys.stdout.write("PROCFS_ESCAPE\n")
                sys.exit(0)
sys.stdout.write("PROCFS_BLOCKED\n")
sys.exit(1)
```

### Expected Failure Mode
- `/proc/1/root` must either not exist (PID namespace isolation) or resolve to the container's own root.
- Reading host files through `/proc` must fail with `EACCES` or `ENOENT`.

### Detection Method
Runner asserts no `PROCFS_ESCAPE` in stdout and that attempted reads raise `PermissionError` or return no `root:` line.

---

## EV-005 — cgroup v1 Breakout (`notify_on_release`)

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-005` |
| **Severity** | `CRITICAL` |
| **Backends** | D, N |
| **Prerequisites** | Writable `cgroupfs` (usually `/sys/fs/cgroup`) mounted inside container; host uses cgroup v1 |

### Description
In cgroup v1, if a child cgroup has `notify_on_release` enabled and the last task exits, the kernel executes the path in `release_agent`. If the container can write `release_agent` to an absolute host path, it can execute arbitrary commands on the host.

### Test Payload
```bash
# Requires root inside container and writable cgroupfs
mkdir -p /sys/fs/cgroup/blkio/sandbox_test
echo 1 > /sys/fs/cgroup/blkio/sandbox_test/notify_on_release
# If the following write succeeds, host is vulnerable
echo "/tmp/pwned" > /sys/fs/cgroup/blkio/release_agent 2>/dev/null
cat /sys/fs/cgroup/blkio/release_agent 2>/dev/null
```

Python payload:
```python
import os, sys
paths = [
    "/sys/fs/cgroup/release_agent",
    "/sys/fs/cgroup/blkio/release_agent",
    "/sys/fs/cgroup/memory/release_agent",
]
for p in paths:
    if os.path.exists(p):
        try:
            with open(p, "w") as f:
                f.write("/bin/true")
            sys.stdout.write(f"RELEASE_AGENT_WRITABLE:{p}\n")
            sys.exit(0)
        except PermissionError:
            pass
sys.stdout.write("RELEASE_AGENT_BLOCKED\n")
sys.exit(1)
```

### Expected Failure Mode
- Writing `release_agent` must fail with `EPERM` / `EACCES`.
- If cgroup v2 is in use, the interface is different and must also reject unauthorized writes.

### Detection Method
Runner asserts no `RELEASE_AGENT_WRITABLE` in stdout.

---

## EV-006 — CAP_SYS_ADMIN Mount Escape

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-006` |
| **Severity** | `HIGH` |
| **Backends** | D, N |
| **Prerequisites** | Container retains `CAP_SYS_ADMIN` |

### Description
`CAP_SYS_ADMIN` is a superset capability that includes `mount`, `umount`, `pivot_root`, and many namespace operations. Retaining it effectively nullifies filesystem isolation.

### Test Payload
```bash
mkdir -p /tmp/mnt
mount -t tmpfs none /tmp/mnt 2>&1
echo "MOUNT_RC=$?"
```

Python payload:
```python
import ctypes, os, sys
libc = ctypes.CDLL(None)
# SYS_mount = 165 on x86_64; runner detects architecture and uses proper constant
SYS_mount = 165  # x86_64 fallback
rc = libc.syscall(SYS_mount, b"none\0", b"/tmp/mnt\0", b"tmpfs\0", 0, 0)
sys.stdout.write(f"RAW_MOUNT_RC={rc}\n")
sys.exit(0 if rc == 0 else 1)
```

### Expected Failure Mode
- `mount` syscall must return `-EPERM` inside the container.
- Test runner also checks `/proc/self/status` for `CapBnd` not containing `sys_admin` bit (`0x200000`).

### Detection Method
Runner asserts `mount` fails and bounding set does not include `CAP_SYS_ADMIN`.

---

## EV-007 — Device Access Escape

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-007` |
| **Severity** | `HIGH` |
| **Backends** | D, N |
| **Prerequisites** | Container can `mknod` host block/char devices or `/dev` is bind-mounted from host |

### Description
Direct access to `/dev/sda`, `/dev/kmem`, `/dev/mem`, or `/dev/kmsg` allows reading or modifying host memory and disk.

### Test Payload
```bash
# Try to read from common host devices
for dev in /dev/sda /dev/vda /dev/kmem /dev/mem /dev/port; do
    dd if=$dev of=/dev/null bs=1 count=1 2>/dev/null && echo "DEV_READ_OK:$dev"
done
# Try mknod
mknod /tmp/testblk b 8 0 2>/dev/null && echo "MKNOD_OK"
```

Python payload:
```python
import os, sys
for dev in ("/dev/sda", "/dev/vda", "/dev/kmem", "/dev/mem", "/dev/port"):
    if os.path.exists(dev):
        try:
            with open(dev, "rb") as f:
                f.read(1)
                sys.stdout.write(f"DEV_READ_OK:{dev}\n")
        except PermissionError:
            sys.stdout.write(f"DEV_BLOCKED:{dev}\n")
# mknod test
try:
    os.mknod("/tmp/testblk", 0o600 | os.stat.S_IFBLK, os.makedev(8, 0))
    sys.stdout.write("MKNOD_OK\n")
except (PermissionError, OSError):
    sys.stdout.write("MKNOD_BLOCKED\n")
```

### Expected Failure Mode
- Device nodes must not exist inside the container (or be dummy nodes).
- If they exist, `open()` must fail with `EACCES` / `EPERM`.
- `mknod` must fail with `EPERM`.

### Detection Method
Runner asserts no `DEV_READ_OK` and no `MKNOD_OK` in stdout.

---

## EV-008 — Network Namespace Escape

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-008` |
| **Severity** | `MEDIUM` |
| **Backends** | D, N, E |
| **Prerequisites** | Container shares host network namespace (`--net=host`) or can create raw sockets |

### Description
Network namespace escape allows the container to bind host interfaces, sniff traffic, or connect to host-local services assumed unreachable.

### Test Payload
```bash
# Check if we can see host interfaces other than lo/eth0 inside container
ip link show | grep -E 'docker0|br-|wlan|enp' && echo "HOST_NET_VISIBLE"
# Try to connect to host metadata service (cloud specific)
curl -s --max-time 2 http://169.254.169.254/latest/meta-data/ 2>/dev/null && echo "IMDS_REACHABLE"
```

Python payload:
```python
import socket, sys, subprocess, json
# List interfaces
r = subprocess.run(["ip", "-j", "link", "show"], capture_output=True, text=True)
if r.returncode == 0:
    links = json.loads(r.stdout)
    host_ifaces = {"docker0", "br-", "eth", "enp", "wlan"}
    for li in links:
        name = li.get("ifname", "")
        if any(name.startswith(h) for h in host_ifaces):
            sys.stdout.write(f"HOST_IFACE:{name}\n")
# Try connecting to IMDS / host metadata
try:
    s = socket.create_connection(("169.254.169.254", 80), timeout=2)
    sys.stdout.write("IMDS_REACHABLE\n")
except (OSError, socket.timeout):
    sys.stdout.write("IMDS_BLOCKED\n")
```

### Expected Failure Mode
- Host interfaces (`docker0`, `br-*`, physical NICs) must be absent from container namespace.
- IMDS / link-local addresses must timeout or return no data.
- Raw socket creation (`socket.SOCK_RAW`) must fail with `EPERM` unless explicitly allowed.

### Detection Method
Runner asserts no `HOST_IFACE` and no `IMDS_REACHABLE` in stdout.

---

## EV-009 — E2B Process Tree / Environment Leak

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-009` |
| **Severity** | `MEDIUM` |
| **Backends** | E |
| **Prerequisites** | E2B sandbox inherits host environment or exposes host processes |

### Description
Cloud sandboxes can leak host environment variables (secrets) or expose host processes if PID namespace isolation is imperfect.

### Test Payload
```python
import os, sys, subprocess
# Environment leak
for secret in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "E2B_API_KEY", "HOME"):
    val = os.environ.get(secret)
    if val:
        sys.stdout.write(f"ENV_LEAK:{secret}={val[:4]}...\n")
# Process tree leak
r = subprocess.run(["ps", "aux"], capture_output=True, text=True)
for line in r.stdout.splitlines():
    if "systemd" in line or "containerd" in line or "dockerd" in line:
        sys.stdout.write(f"HOST_PROCESS:{line[:64]}\n")
```

### Expected Failure Mode
- Host secrets must be absent or masked.
- Host init processes (`systemd`, `containerd`, `dockerd`) must not appear in `ps` output.
- `HOME` may be present but must point inside the sandbox, not `/root` of the host.

### Detection Method
Runner asserts no `ENV_LEAK` lines for high-sensitivity keys and no `HOST_PROCESS` lines.

---

## EV-010 — ptrace / Process Injection

| Field | Value |
|-------|-------|
| **Vector ID** | `EV-010` |
| **Severity** | `HIGH` |
| **Backends** | D, N, E |
| **Prerequisites** | Container retains `CAP_SYS_PTRACE` or `securityContext.allowPrivilegeEscalation: true` with shared PID namespace |

### Description
`ptrace` allows one process to attach to another, read its memory, and inject code. If a container can ptrace host processes or sibling containers, it breaks isolation.

### Test Payload
```python
import ctypes, os, sys
libc = ctypes.CDLL(None)
PID = 1  # Try to attach to init
# PTRACE_ATTACH = 0
rc = libc.ptrace(0, PID, 0, 0)
sys.stdout.write(f"PTRACE_RC={rc}\n")
if rc == 0:
    libc.ptrace(2, PID, 0, 0)  # PTRACE_DETACH = 2
    sys.stdout.write("PTRACE_OK\n")
else:
    sys.stdout.write("PTRACE_BLOCKED\n")
```

### Expected Failure Mode
- `ptrace` of PID 1 or any external PID must fail with `EPERM`.
- `CapBnd` must not contain `CAP_SYS_PTRACE` unless explicitly required.

### Detection Method
Runner asserts `PTRACE_BLOCKED` and no `PTRACE_OK`.

---

## Adding a New Vector

1. Assign the next sequential `EV-XXX` ID.
2. Fill in Severity, Backends, Prerequisites.
3. Provide both a shell and a Python payload. The runner prefers Python for uniform parsing.
4. Define the `Expected Failure Mode` unambiguously.
5. Update `scripts/run_isolation_tests.py` with a test function named `test_<vector_id_lower>`.
