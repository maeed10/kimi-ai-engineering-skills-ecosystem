# Isolation Invariants Per Backend

> **Purpose**: Formal statements of the security properties that each sandbox backend must guarantee. Every test in `scripts/run_isolation_tests.py` maps to one or more invariants in this document. If an invariant is violated, the test suite fails.

---

## Invariant Naming

- **D-INV-NNN** — Docker backend
- **N-INV-NNN** — nerdctl / containerd backend
- **E-INV-NNN** — E2B cloud sandbox backend
- **GEN-INV-NNN** — Generic invariant applying to all backends

---

## Generic Invariants (All Backends)

### GEN-INV-001 — Resource Lifecycle Bound
A sandbox resource (container, namespace, or cloud sandbox) created by the test suite must be fully destroyed by the test suite, even if the test fails or crashes. No orphaned resources may remain after `run_isolation_tests.py` exits.

### GEN-INV-002 — No Silent Privilege Escalation
If a payload attempts any action that would grant additional privileges compared to the sandbox's initial state (e.g., `setuid` binary execution, `CAP_SETUID` abuse, `unshare` with new user namespace + full caps), the action must fail or the new privileges must remain confined within the original sandbox boundaries.

### GEN-INV-003 — deterministic Isolation Result
For a given backend version, OCI image, and kernel version, the result of every isolation test must be deterministic: pass every time isolation holds, fail every time it does not. Non-deterministic failures (e.g., network timeouts in a perfectly isolated sandbox) must be handled via retries and clear logging, not ignored.

---

## Docker Backend Invariants

### D-INV-001 — Default Network Deny
A container started without explicit `--network` or port mappings must not be able to initiate outbound IP connections to addresses outside the container's own network namespace, except to the internal Docker bridge gateway. Egress to `8.8.8.8`, `1.1.1.1`, or the host's LAN must time out or be rejected.

### D-INV-002 — Read-Only Rootfs
When `--read-only` is passed to `docker run`, the container's root filesystem (`/`) must be mounted `MS_RDONLY`. Writes to `/bin`, `/etc`, `/usr`, or any path under `/` outside of explicitly declared writable volumes must fail with `EROFS`.

### D-INV-003 — Capability Bounding Set
A container started without `--cap-add` must have an empty effective capability set and a bounding set that does **not** include:
- `CAP_SYS_ADMIN` (bit 21)
- `CAP_SYS_MODULE` (bit 16)
- `CAP_SYS_PTRACE` (bit 19)
- `CAP_SYS_RAWIO` (bit 17)
- `CAP_MKNOD` (bit 27)

The runner verifies this by reading `/proc/self/status` inside the container and parsing the `CapBnd` hex mask.

### D-INV-004 — Seccomp Default Profile
The default seccomp profile must block at least the following syscalls when attempted from inside the container:
- `mount` (unless allow-listed via `unshare` + user namespace, which is not the default)
- `pivot_root`
- `open_by_handle_at`
- `kcmp`

The runner attempts these syscalls via `ctypes.CDLL(None).syscall()` and asserts `EPERM`.

### D-INV-005 — No Host Namespace Sharing (Default)
Unless explicitly requested with `--pid=host`, `--ipc=host`, `--net=host`, or `--uts=host`, a container must run in its own PID, IPC, network, and UTS namespaces. The runner checks:
- `/proc/1/status` `NSpid` line differs from container PID 1.
- `ip link show` does not list host physical interfaces.
- `hostname` inside the container differs from the Docker daemon host's hostname.

### D-INV-006 — Device Restrictions
The container's `/dev` directory must contain only pseudo-devices created by the runtime (`null`, `zero`, `random`, `urandom`, `tty`, `pts`, `shm`). Host block devices (`sda`, `nvme*`, `vda`) and character devices (`kmem`, `mem`, `port`) must be absent. `mknod` of such devices must fail with `EPERM`.

### D-INV-007 — Tmpfs Size Enforcement
When `--tmpfs /tmp:size=50m` is specified, the container must be unable to write more than 50 MiB (plus negligible filesystem overhead) into `/tmp`. The runner writes a sparse or dense file exceeding the limit and asserts `ENOSPC`.

### D-INV-008 — No New Privileges
Containers started with the default configuration must have `NoNewPrivs: 1` (or equivalent seccomp/apparmor profile). A `setuid` binary inside the container must not elevate the effective UID.

---

## Nerdctl / Containerd Backend Invariants

### N-INV-001 — Namespace Isolation
All containers created by the sandbox executor via nerdctl must reside in a containerd namespace that is **not** `default` and is isolated from the host's direct control plane. The runner asserts:
- `ctr -n <ns> containers ls` lists the test container.
- `ctr -n default containers ls` does **not** list the test container.

### N-INV-002 — CNI Network Isolation
When nerdctl creates a container with the default CNI bridge (`bridge`), the container must receive its own network namespace and veth pair. It must not see host interfaces (same as D-INV-001 and D-INV-005). The runner checks:
- `ip link` inside the container shows only `lo` and `eth0` (or `eth*`).
- No host bridges (`docker0`, `cni0`, `br-*`) are visible.

### N-INV-003 — Snapshotter Mount Isolation
The container rootfs must be mounted via the configured snapshotter (e.g., `overlayfs`, `native`, `stargz`) with the container's mount namespace. The runner verifies:
- `/proc/self/mountinfo` shows the rootfs as an overlay mount whose upper/work dirs are inside the snapshotter's metadata directory, not host paths.
- The container cannot remount the rootfs read-write if it was created read-only.

### N-INV-004 — OCI Spec Enforcement
nerdctl must translate CLI flags into the OCI runtime spec (`config.json`) correctly. The runner inspects the OCI spec via `nerdctl inspect` or by reading the runtime bundle if accessible, and asserts:
- `process.capabilities.bounding` is empty (or minimal) when no `--cap-add` is given.
- `linux.seccomp` is present and not `null` when the default profile is used.
- `linux.namespaces` contains entries for `pid`, `ipc`, `mount`, and `network`.

### N-INV-005 — Containerd-Shim Isolation
The `containerd-shim` process managing the container must run as an unprivileged user or with dropped capabilities. The runner checks (on the host side, if permitted):
- `ps -eo user,comm | grep containerd-shim` shows a non-root user, or
- The shim's `/proc/<pid>/status` `CapEff` is `0000000000000000`.

### N-INV-006 — Equivalent Escape Resistance
All Docker-specific escape vectors (EV-001 through EV-008) that apply to OCI runtimes must yield the same blocking behavior under nerdctl + containerd + runc/crun. If a vector is blocked by Docker but passes under nerdctl, that is a **regression** and must fail the test suite.

---

## E2B Cloud Sandbox Backend Invariants

### E-INV-001 — Sandbox Process Isolation
The E2B sandbox must present a root filesystem and process tree that are independent of the host orchestrator. The runner asserts:
- `ps aux` inside the sandbox shows PID 1 as the sandbox init, not `systemd` or `containerd`.
- `/proc/1/comm` reads as the sandbox entrypoint, not a host daemon.

### E-INV-002 — Network Egress Control
By default, an E2B sandbox must block or strictly audit outbound connections. The runner attempts:
- `curl https://example.com` → must fail or return a proxy block page.
- DNS resolution of external domains → must timeout or return NXDOMAIN.
If the E2B backend is configured with an explicit allow-list, only the allow-listed destinations may succeed.

### E-INV-003 — Filesystem Jail
The sandbox's working directory must be a chroot-like jail. The runner attempts:
- `cd / && ls /proc/1/root` → must fail or show sandbox-only paths.
- `cd /host` → must return `ENOENT` or `EACCES`.
- Writing to `/etc/passwd` inside the sandbox must fail if the filesystem is read-only, or succeed only inside a temporary overlay that is discarded on sandbox destruction.

### E-INV-004 — Resource Limits
The sandbox must enforce hard limits on CPU time, memory, and disk. The runner asserts:
- A memory-allocation loop exceeding the sandbox memory limit is killed by OOM or throttled, not allowed to exhaust the host.
- CPU throttling is observable via `cgroups` or `ulimit` inside the sandbox.

### E-INV-005 — Environment Sanitization
Host environment variables must not be automatically inherited. The runner checks:
- `os.environ` inside the sandbox does not contain keys like `AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, `E2B_API_KEY`, or other known host secrets.
- `PATH` is reset to a sandbox-safe default.
- `HOME` points inside the sandbox root.

### E-INV-006 — Sandbox Lifetime Bound
An E2B sandbox must have a maximum lifetime enforced by the platform. The runner creates a sandbox and asserts that the `timeout` or `maxDuration` metadata is non-zero and that the sandbox is terminated (not leaked) after that duration.

### E-INV-007 — No Persistent Host Mutation
Any filesystem changes made inside the sandbox must be transient. After the sandbox is destroyed:
- Host filesystem paths must be unmodified.
- Host process list must contain no orphaned sandbox processes.
- Host network configuration must be unchanged.

---

## Invariant ↔ Test Mapping

| Invariant | Test Function(s) in Runner |
|-----------|------------------------------|
| GEN-INV-001 | `cleanup_*` fixtures, `tearDown` in each backend class |
| GEN-INV-002 | `test_capability_drop`, `test_no_new_privs` |
| GEN-INV-003 | Retry wrappers with exponential backoff in `run_isolation_tests.py` |
| D-INV-001 | `test_network_isolation` |
| D-INV-002 | `test_filesystem_readonly` |
| D-INV-003 | `test_capability_drop` |
| D-INV-004 | `test_seccomp_enforcement` |
| D-INV-005 | `test_container_launch` (hostname check), `test_network_isolation` |
| D-INV-006 | `test_no_host_devices` |
| D-INV-007 | `test_tmpfs_bounds` |
| D-INV-008 | `test_privileged_escape` (setuid sub-test) |
| N-INV-001 | `test_namespace_isolation` |
| N-INV-002 | `test_network_isolation` |
| N-INV-003 | `test_filesystem_readonly` (mountinfo inspection) |
| N-INV-004 | `test_container_launch` (inspect OCI spec) |
| N-INV-005 | Host-side check in `test_container_launch` (optional, skipped if no host access) |
| N-INV-006 | `test_escape_vectors` (re-runs EV-001..008) |
| E-INV-001 | `test_sandbox_lifecycle` (process tree inspection) |
| E-INV-002 | `test_network_isolation` |
| E-INV-003 | `test_filesystem_isolation` |
| E-INV-004 | `test_resource_limits` |
| E-INV-005 | `test_environment_sanitization` |
| E-INV-006 | Metadata check inside `test_sandbox_lifecycle` |
| E-INV-007 | Host-side audit after `test_sandbox_lifecycle` teardown |

---

## Updating Invariants

When a backend changes its default security posture (e.g., Docker changes the default seccomp profile, or E2B introduces a new allow-list mode):

1. Update the relevant invariant in this file.
2. Update the corresponding test in `scripts/run_isolation_tests.py`.
3. Add a changelog entry to `SKILL.md`.
4. Bump the skill version tag if versioning is used.
