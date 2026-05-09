---
name: sandbox-integration-tester
description: Reproducible integration test suites for all sandbox-executor backends (Docker, nerdctl, E2B) that launch real containers and verify isolation via known escape vectors. Use in CI/CD pipelines, pre-release validation, or when adding new sandbox backends. Ensures container isolation invariants hold under test.
---

# Sandbox Integration Tester

## Overview

The `sandbox-integration-tester` skill provides hardened, reproducible integration tests for the three `sandbox-executor` backends: **Docker**, **nerdctl**, and **E2B**. Each test suite launches real containers (or cloud sandboxes), executes known escape vectors, and asserts that isolation invariants hold. The test runner is designed for CI/CD pipelines, pre-release validation, and backend acceptance gates.

## Architecture

```
sandbox-integration-tester/
├── SKILL.md                           # This file — architecture & test catalog
├── references/
│   ├── escape_vectors.md              # Known container escape vectors with payloads
│   └── isolation_invariants.md      # Formal isolation invariants per backend
└── scripts/
    └── run_isolation_tests.py         # Python test runner (CLI + CI matrix)
```

### Design Principles

1. **Real workloads, not mocks** — Every test launches an actual container or sandbox. Mocks hide kernel-level isolation bugs.
2. **Fail-closed** — If a test cannot determine whether isolation held (e.g., backend unreachable), it fails.
3. **Idempotent & parallel** — Tests create uniquely named resources and clean them up. The CI matrix runs backends in parallel jobs.
4. **Escape vectors as data** — Each escape vector is documented in `references/escape_vectors.md` with a concrete payload. The runner executes the payload and checks the expected failure mode.

## Test Catalog

### Docker Backend Tests (`--backend docker`)

| # | Test | What It Does | Invariant Checked |
|---|------|------------|-------------------|
| 1 | `test_container_launch` | Runs `alpine:latest`, waits for healthy exit | Container runtime is functional |
| 2 | `test_network_isolation` | Attempts `ping 8.8.8.8` inside default-bridge container | No unauthorized egress |
| 3 | `test_filesystem_readonly` | Writes to `/etc/passwd` inside `--read-only` container | Rootfs is read-only |
| 4 | `test_tmpfs_bounds` | Writes 110% of `--tmpfs size=...` limit to `/tmp` | Tmpfs size enforcement |
| 5 | `test_seccomp_enforcement` | Attempts `mount()` syscall inside container | Seccomp default profile blocks mount |
| 6 | `test_capability_drop` | Checks `/proc/self/status` for bounding set | All caps dropped except permitted subset |
| 7 | `test_privileged_escape` | Runs `--privileged` payload; verifies host namespace NOT entered | Privileged flag is rejected or neutered |
| 8 | `test_kernel_module_load` | Attempts `insmod` / `modprobe` inside container | `CAP_SYS_MODULE` is absent |
| 9 | `test_symlink_escape` | Follows symlink chain designed to escape chroot | `openat2` / `RESOLVE_NO_SYMLINKS` or equivalent blocks escape |
| 10 | `test_procfs_escape` | Accesses `/proc/1/root/` or `/proc/self/cwd` tricks | procfs mount hides host paths |
| 11 | `test_cgroup_breakout` | Exploits cgroup v1 `notify_on_release` in writable cgroupfs | Writable cgroupfs is not mounted or host path is sanitized |
| 12 | `test_no_host_devices` | Attempts `dd` of `/dev/sda`, `/dev/kmem`, `/dev/mem` | Host devices are absent or `mknod` is blocked |

### Nerdctl Backend Tests (`--backend nerdctl`)

| # | Test | What It Does | Invariant Checked |
|---|------|------------|-------------------|
| 1 | `test_container_launch` | Runs container via `nerdctl run` with containerd | containerd + nerdctl pipeline functional |
| 2 | `test_namespace_isolation` | Lists namespaces via `ctr namespace ls`; asserts sandbox != host | containerd namespace isolation |
| 3 | `test_network_isolation` | Same ping egress test via `nerdctl` CNI bridge | CNI bridge isolates egress |
| 4 | `test_filesystem_readonly` | Same read-only rootfs test | Snapshotter mounts read-only when requested |
| 5 | `test_seccomp_enforcement` | Same seccomp mount block test | containerd seccomp profile applied |
| 6 | `test_capability_drop` | Same bounding-set check | OCI spec capabilities dropped by containerd |
| 7–12 | `test_escape_vectors` | Re-runs Docker escape payloads via `nerdctl` | Isolation parity with Docker backend |

### E2B Backend Tests (`--backend e2b`)

| # | Test | What It Does | Invariant Checked |
|---|------|------------|-------------------|
| 1 | `test_sandbox_lifecycle` | Creates, runs a command, and destroys an E2B sandbox | Cloud sandbox API functional |
| 2 | `test_network_isolation` | Attempts outbound curl inside sandbox | Egress filtered or denied by default |
| 3 | `test_resource_limits` | Allocates memory / CPU in a tight loop until limit hit | OOM / throttling enforced |
| 4 | `test_filesystem_isolation` | Writes outside sandbox root, attempts `/host` or `/proc/1/root` | FS jail enforced |
| 5 | `test_procfs_escape` | Same procfs tricks tailored for E2B kernel namespace | Host PID namespace hidden |
| 6 | `test_environment_sanitization` | Dumps env; asserts no host secrets leaked | Host env not inherited |

## Escape Vector Definitions

All escape vectors are formally defined in [`references/escape_vectors.md`](references/escape_vectors.md). Each entry includes:

- **Vector ID** (e.g., `CVE-STYLE-001`)
- **Severity** (`CRITICAL`, `HIGH`, `MEDIUM`)
- **Affected Backends**
- **Prerequisites** (misconfigurations that enable it)
- **Test Payload** (copy-paste commands or Python code)
- **Expected Failure Mode** (what happens when isolation is correct)
- **Detection Method** (how the test runner verifies the failure)

## Isolation Invariants

Formal invariants per backend are maintained in [`references/isolation_invariants.md`](references/isolation_invariants.md). These are the ground-truth statements that every test maps to. Example:

> **D-INV-03**: A container launched without `--cap-add` must not possess `CAP_SYS_ADMIN` in its effective or bounding capability sets.

## CI/CD Integration

### GitHub Actions Matrix (example)

```yaml
strategy:
  fail-fast: false
  matrix:
    backend: [docker, nerdctl, e2b]
    runner: [ubuntu-22.04]
    include:
      - backend: nerdctl
        runner: ubuntu-22.04
        setup: ./hack/install-nerdctl-full.sh
      - backend: e2b
        runner: ubuntu-22.04
        setup: pip install e2b

steps:
  - uses: actions/checkout@v4
  - name: Setup backend
    run: ${{ matrix.setup }}
  - name: Run isolation tests
    run: |
      python scripts/run_isolation_tests.py \
        --backend ${{ matrix.backend }} \
        --fail-fast \
        --json-report isolation-report-${{ matrix.backend }}.json
  - name: Upload report
    uses: actions/upload-artifact@v4
    with:
      name: isolation-report-${{ matrix.backend }}
      path: isolation-report-${{ matrix.backend }}.json
```

### Local Usage

```bash
# Run all backends sequentially
python scripts/run_isolation_tests.py --backend all

# Run only Docker tests, stop on first failure
python scripts/run_isolation_tests.py --backend docker --fail-fast

# Run a specific escape vector across all backends
python scripts/run_isolation_tests.py --backend all --filter "test_privileged_escape"

# CI mode: JSON report, no interactive spinners
python scripts/run_isolation_tests.py --backend all --ci --json-report report.json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All tests passed; isolation invariants hold |
| `1` | One or more tests failed — isolation breach detected |
| `2` | Test runner internal error (backend not found, syntax error, etc.) |
| `3` | Backend unavailable (e.g., Docker daemon not running) |

## Contributing New Backends

When adding a fourth sandbox backend (e.g., Podman, gVisor, Firecracker):

1. Add a new backend class in `scripts/run_isolation_tests.py` inheriting from `BaseBackend`.
2. Document backend-specific invariants in `references/isolation_invariants.md`.
3. Add backend-specific escape vectors (if any) to `references/escape_vectors.md`.
4. Extend the CI matrix in this file and in your pipeline YAML.
5. Ensure all generic escape vectors (privileged escalation, procfs escape, etc.) have equivalent tests.

## Resources

### `scripts/run_isolation_tests.py`
The executable test runner. Supports CLI flags, parallel execution, JSON reporting, and cleanup. Can be invoked directly or imported as a module.

### `references/escape_vectors.md`
Canonical catalog of container escape techniques used as test payloads.

### `references/isolation_invariants.md`
Formal specification of what "isolation" means for each backend. Tests are derived from these invariants.
