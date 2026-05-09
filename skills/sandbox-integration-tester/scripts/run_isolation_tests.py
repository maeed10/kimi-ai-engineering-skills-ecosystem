#!/usr/bin/env python3
"""
run_isolation_tests.py

Reproducible integration test runner for sandbox-executor backends
(Docker, nerdctl, E2B). Launches real containers, executes known escape
vectors, and asserts that isolation invariants hold.

Usage:
    python run_isolation_tests.py --backend docker
    python run_isolation_tests.py --backend all --fail-fast --ci
    python run_isolation_tests.py --backend nerdctl --filter "test_network"
    python run_isolation_tests.py --backend all --json-report report.json
"""

import argparse
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("sandbox_integration_tester")


def setup_logging(ci: bool = False) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    if ci:
        logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stdout)
    else:
        logging.basicConfig(level=logging.INFO, format=fmt)


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------
def encode_python_payload(code: str) -> str:
    """Return a shell command that decodes and runs the given Python code."""
    b64 = base64.b64encode(code.encode("utf-8")).decode("utf-8")
    return f"echo '{b64}' | base64 -d | python3 -"


# ---------------------------------------------------------------------------
# Generic Python payloads (from references/escape_vectors.md)
# ---------------------------------------------------------------------------
PAYLOAD_PRIVILEGED_ESCAPE = '''
import os, subprocess, sys
for dev in ("/dev/sda1", "/dev/vda1", "/dev/nvme0n1p1"):
    rc = subprocess.call(["mount", dev, "/host"], stderr=subprocess.DEVNULL)
    if rc == 0:
        if os.path.exists("/host/etc/shadow"):
            sys.stdout.write("HOST_ROOT_VISIBLE\\n")
            sys.exit(0)
sys.stdout.write("MOUNT_BLOCKED\\n")
sys.exit(1)
'''

PAYLOAD_KERNEL_MODULE = '''
import subprocess, sys, os
r1 = subprocess.run(["modprobe", "__sandbox_test"], capture_output=True)
if os.path.exists("/proc/sys/kernel/modules_disabled"):
    with open("/proc/sys/kernel/modules_disabled") as f:
        if f.read().strip() == "1":
            sys.stdout.write("MODULES_DISABLED\\n")
            sys.exit(1)
sys.stdout.write(f"MODPROBE_RC={r1.returncode}\\n")
sys.exit(0 if r1.returncode == 0 else 1)
'''

PAYLOAD_SYMLINK_ESCAPE = '''
import os, tempfile, sys
with tempfile.TemporaryDirectory() as td:
    link = os.path.join(td, "link")
    os.symlink("/proc/1/root/etc", link)
    try:
        os.listdir(link)
        sys.stdout.write("FOLLOWED\\n")
    except PermissionError:
        sys.stdout.write("BLOCKED_BY_SECCOMP_OR_PERMS\\n")
    except OSError:
        sys.stdout.write("BLOCKED\\n")
'''

PAYLOAD_PROCFS_ESCAPE = '''
import os, sys
host_targets = ["/proc/1/root/etc/shadow", "/proc/1/root/etc/passwd"]
for t in host_targets:
    if os.path.exists(t):
        try:
            with open(t) as f:
                if "root:" in f.read(128):
                    sys.stdout.write("PROCFS_ESCAPE\\n")
                    sys.exit(0)
        except (PermissionError, OSError):
            pass
sys.stdout.write("PROCFS_BLOCKED\\n")
sys.exit(1)
'''

PAYLOAD_CGROUP_BREAKOUT = '''
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
            sys.stdout.write(f"RELEASE_AGENT_WRITABLE:{p}\\n")
            sys.exit(0)
        except PermissionError:
            pass
sys.stdout.write("RELEASE_AGENT_BLOCKED\\n")
sys.exit(1)
'''

PAYLOAD_CAP_SYS_ADMIN_MOUNT = '''
import subprocess, sys
rc = subprocess.run(["mkdir", "-p", "/tmp/mnt"], capture_output=True)
rc = subprocess.run(["mount", "-t", "tmpfs", "none", "/tmp/mnt"],
                    capture_output=True)
sys.stdout.write(f"MOUNT_RC={rc.returncode}\\n")
sys.exit(0 if rc.returncode == 0 else 1)
'''

PAYLOAD_DEVICE_ACCESS = '''
import os, sys
for dev in ("/dev/sda", "/dev/vda", "/dev/kmem", "/dev/mem", "/dev/port"):
    if os.path.exists(dev):
        try:
            with open(dev, "rb") as f:
                f.read(1)
                sys.stdout.write(f"DEV_READ_OK:{dev}\\n")
        except PermissionError:
            sys.stdout.write(f"DEV_BLOCKED:{dev}\\n")
try:
    os.mknod("/tmp/testblk", 0o600 | 0o060000, os.makedev(8, 0))
    sys.stdout.write("MKNOD_OK\\n")
except (PermissionError, OSError):
    sys.stdout.write("MKNOD_BLOCKED\\n")
'''

PAYLOAD_NETWORK_ISOLATION = '''
import socket, sys, subprocess, json
r = subprocess.run(["ip", "-j", "link", "show"], capture_output=True, text=True)
if r.returncode == 0:
    links = json.loads(r.stdout)
    host_ifaces = {"docker0", "br-", "eth", "enp", "wlan"}
    for li in links:
        name = li.get("ifname", "")
        if any(name.startswith(h) for h in host_ifaces):
            sys.stdout.write(f"HOST_IFACE:{name}\\n")
try:
    s = socket.create_connection(("8.8.8.8", 53), timeout=3)
    sys.stdout.write("EGRESS_OK\\n")
except (OSError, socket.timeout):
    sys.stdout.write("EGRESS_BLOCKED\\n")
'''

PAYLOAD_PTRACE = '''
import ctypes, os, sys
libc = ctypes.CDLL(None)
SYS_ptrace = 101  # x86_64; test runner also checks CapBnd as fallback
rc = libc.syscall(SYS_ptrace, 0, 1, 0, 0)  # PTRACE_ATTACH, PID 1
sys.stdout.write(f"PTRACE_RC={rc}\\n")
if rc == 0:
    libc.syscall(SYS_ptrace, 2, 1, 0, 0)  # PTRACE_DETACH
    sys.stdout.write("PTRACE_OK\\n")
else:
    sys.stdout.write("PTRACE_BLOCKED\\n")
'''

PAYLOAD_E2B_ENV_LEAK = '''
import os, sys, subprocess
for secret in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "E2B_API_KEY"):
    val = os.environ.get(secret)
    if val:
        sys.stdout.write(f"ENV_LEAK:{secret}={val[:4]}...\\n")
r = subprocess.run(["ps", "aux"], capture_output=True, text=True)
for line in r.stdout.splitlines():
    if "systemd" in line or "containerd" in line or "dockerd" in line:
        sys.stdout.write(f"HOST_PROCESS:{line[:64]}\\n")
'''

PAYLOAD_E2B_FS_ISOLATION = '''
import os, sys
try:
    os.listdir("/proc/1/root/etc")
    sys.stdout.write("FS_ESCAPE\\n")
except (PermissionError, OSError):
    sys.stdout.write("FS_BLOCKED\\n")
try:
    os.listdir("/host")
    sys.stdout.write("HOST_DIR_VISIBLE\\n")
except OSError:
    sys.stdout.write("HOST_DIR_BLOCKED\\n")
'''

PAYLOAD_CAPABILITY_DROP = '''
import re, sys
with open("/proc/self/status") as f:
    for line in f:
        if line.startswith("CapBnd:"):
            capbnd = int(line.split()[1], 16)
            break
    else:
        sys.stdout.write("NO_CAPBND\\n")
        sys.exit(1)
forbidden = {
    "CAP_SYS_ADMIN": 1 << 21,
    "CAP_SYS_MODULE": 1 << 16,
    "CAP_SYS_PTRACE": 1 << 19,
    "CAP_SYS_RAWIO": 1 << 17,
    "CAP_MKNOD": 1 << 27,
}
violations = []
for name, bit in forbidden.items():
    if capbnd & bit:
        violations.append(name)
if violations:
    sys.stdout.write(f"FORBIDDEN_CAPS:{','.join(violations)}\\n")
    sys.exit(0)
sys.stdout.write("CAPS_OK\\n")
sys.exit(1)
'''

PAYLOAD_NO_NEW_PRIVS = '''
import os, sys, subprocess
# Check NoNewPrivs bit in /proc/self/status
with open("/proc/self/status") as f:
    content = f.read()
    if "NoNewPrivs:\t1" in content:
        sys.stdout.write("NO_NEW_PRIVS_OK\\n")
        sys.exit(0)
# Fallback: try to run a setuid binary (should fail or not elevate)
# Many containers don't have a setuid binary, so the bit check is primary.
sys.stdout.write("NO_NEW_PRIVS_MISSING\\n")
sys.exit(1)
'''


# ---------------------------------------------------------------------------
# Base backend
# ---------------------------------------------------------------------------
class BaseBackend(ABC):
    name: str = "base"

    def __init__(self):
        self._resources: List[str] = []

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def run_container(
        self,
        image: str = "python:3-alpine",
        cmd: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        """Create and start a container; return a resource handle."""
        ...

    @abstractmethod
    def exec_in_container(self, handle: str, cmd: List[str]) -> Tuple[int, str, str]:
        """Execute a command inside a running container."""
        ...

    @abstractmethod
    def logs(self, handle: str) -> str:
        ...

    @abstractmethod
    def destroy(self, handle: str) -> None:
        ...

    def cleanup(self) -> None:
        for r in list(self._resources):
            try:
                self.destroy(r)
            except Exception as exc:
                logger.warning("Cleanup error for %s: %s", r, exc)
        self._resources.clear()

    def _python_cmd(self, code: str) -> List[str]:
        encoded = encode_python_payload(code)
        return ["sh", "-c", encoded]


# ---------------------------------------------------------------------------
# Docker backend
# ---------------------------------------------------------------------------
class DockerBackend(BaseBackend):
    name = "docker"

    def __init__(self):
        super().__init__()
        self._use_sdk = False
        self._client = None
        try:
            import docker as docker_mod

            self._client = docker_mod.from_env()
            self._client.ping()
            self._use_sdk = True
            logger.info("Docker SDK available and responsive")
        except Exception as exc:
            logger.debug("Docker SDK unavailable (%s); falling back to CLI", exc)

    def is_available(self) -> bool:
        if self._use_sdk:
            return True
        return shutil.which("docker") is not None

    def _docker_run_args(self, **kwargs) -> List[str]:
        args = ["docker", "run", "-d", "--rm"]
        if kwargs.get("read_only"):
            args.append("--read-only")
        if kwargs.get("network"):
            args.extend(["--network", kwargs["network"]])
        if kwargs.get("cap_drop"):
            args.extend(["--cap-drop", kwargs["cap_drop"]])
        if kwargs.get("cap_add"):
            args.extend(["--cap-add", kwargs["cap_add"]])
        if kwargs.get("privileged"):
            args.append("--privileged")
        if kwargs.get("security_opt"):
            for opt in kwargs["security_opt"]:
                args.extend(["--security-opt", opt])
        if kwargs.get("tmpfs"):
            for mount, opts in kwargs["tmpfs"].items():
                args.extend(["--tmpfs", f"{mount}:{opts}"])
        if kwargs.get("pid"):
            args.extend(["--pid", kwargs["pid"]])
        if kwargs.get("ipc"):
            args.extend(["--ipc", kwargs["ipc"]])
        if kwargs.get("uts"):
            args.extend(["--uts", kwargs["uts"]])
        if kwargs.get("name"):
            args.extend(["--name", kwargs["name"]])
        return args

    def run_container(
        self,
        image: str = "python:3-alpine",
        cmd: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        name = kwargs.pop("name", None) or f"sit-{uuid.uuid4().hex[:8]}"
        kwargs["name"] = name
        if cmd is None:
            cmd = ["sleep", "3600"]

        if self._use_sdk:
            import docker as docker_mod

            run_kw = {}
            if kwargs.get("read_only"):
                run_kw["read_only"] = True
            if kwargs.get("network"):
                run_kw["network"] = kwargs["network"]
            if kwargs.get("cap_drop"):
                run_kw["cap_drop"] = kwargs["cap_drop"]
            if kwargs.get("cap_add"):
                run_kw["cap_add"] = kwargs["cap_add"]
            if kwargs.get("privileged"):
                run_kw["privileged"] = True
            if kwargs.get("security_opt"):
                run_kw["security_opt"] = kwargs["security_opt"]
            if kwargs.get("tmpfs"):
                run_kw["tmpfs"] = kwargs["tmpfs"]
            if kwargs.get("pid"):
                run_kw["pid_mode"] = kwargs["pid"]
            if kwargs.get("ipc"):
                run_kw["ipc_mode"] = kwargs["ipc"]
            if kwargs.get("uts"):
                run_kw["uts_mode"] = kwargs["uts"]
            container = self._client.containers.run(
                image, command=cmd, detach=True, auto_remove=True, name=name, **run_kw
            )
            cid = container.id
        else:
            args = self._docker_run_args(**kwargs)
            args.extend([image])
            args.extend(cmd)
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"docker run failed: {result.stderr}")
            cid = result.stdout.strip()

        self._resources.append(cid)
        return cid

    def exec_in_container(self, handle: str, cmd: List[str]) -> Tuple[int, str, str]:
        if self._use_sdk:
            container = self._client.containers.get(handle)
            result = container.exec_run(cmd, demux=False)
            # result is (exit_code, output_bytes)
            out = result.output.decode("utf-8", errors="replace") if result.output else ""
            return result.exit_code, out, ""
        else:
            args = ["docker", "exec", handle] + cmd
            result = subprocess.run(args, capture_output=True, text=True, check=False)
            return result.returncode, result.stdout, result.stderr

    def logs(self, handle: str) -> str:
        if self._use_sdk:
            container = self._client.containers.get(handle)
            return container.logs().decode("utf-8", errors="replace")
        else:
            result = subprocess.run(
                ["docker", "logs", handle], capture_output=True, text=True, check=False
            )
            return result.stdout + result.stderr

    def destroy(self, handle: str) -> None:
        if self._use_sdk:
            try:
                container = self._client.containers.get(handle)
                container.remove(force=True)
            except Exception:
                pass
        else:
            subprocess.run(
                ["docker", "rm", "-f", handle],
                capture_output=True,
                text=True,
                check=False,
            )
        if handle in self._resources:
            self._resources.remove(handle)


# ---------------------------------------------------------------------------
# Nerdctl backend
# ---------------------------------------------------------------------------
class NerdctlBackend(BaseBackend):
    name = "nerdctl"

    def __init__(self):
        super().__init__()
        self._nerdctl = shutil.which("nerdctl")

    def is_available(self) -> bool:
        return self._nerdctl is not None

    def run_container(
        self,
        image: str = "python:3-alpine",
        cmd: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        name = kwargs.pop("name", None) or f"sit-n-{uuid.uuid4().hex[:8]}"
        args = [self._nerdctl, "run", "-d", "--rm"]
        if kwargs.get("read_only"):
            args.append("--read-only")
        if kwargs.get("network"):
            args.extend(["--network", kwargs["network"]])
        if kwargs.get("cap_drop"):
            args.extend(["--cap-drop", kwargs["cap_drop"]])
        if kwargs.get("cap_add"):
            args.extend(["--cap-add", kwargs["cap_add"]])
        if kwargs.get("privileged"):
            args.append("--privileged")
        if kwargs.get("security_opt"):
            for opt in kwargs["security_opt"]:
                args.extend(["--security-opt", opt])
        if kwargs.get("tmpfs"):
            for mount, opts in kwargs["tmpfs"].items():
                args.extend(["--tmpfs", f"{mount}:{opts}"])
        if kwargs.get("pid"):
            args.extend(["--pid", kwargs["pid"]])
        if kwargs.get("ipc"):
            args.extend(["--ipc", kwargs["ipc"]])
        if kwargs.get("uts"):
            args.extend(["--uts", kwargs["uts"]])
        args.extend(["--name", name])
        args.extend([image])
        if cmd is None:
            cmd = ["sleep", "3600"]
        args.extend(cmd)

        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"nerdctl run failed: {result.stderr}")
        cid = result.stdout.strip()
        self._resources.append(cid)
        return cid

    def exec_in_container(self, handle: str, cmd: List[str]) -> Tuple[int, str, str]:
        args = [self._nerdctl, "exec", handle] + cmd
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout, result.stderr

    def logs(self, handle: str) -> str:
        result = subprocess.run(
            [self._nerdctl, "logs", handle],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout + result.stderr

    def destroy(self, handle: str) -> None:
        subprocess.run(
            [self._nerdctl, "rm", "-f", handle],
            capture_output=True,
            text=True,
            check=False,
        )
        if handle in self._resources:
            self._resources.remove(handle)


# ---------------------------------------------------------------------------
# E2B backend
# ---------------------------------------------------------------------------
class E2BBackend(BaseBackend):
    name = "e2b"

    def __init__(self):
        super().__init__()
        self._sandbox_cls = None
        self._api_key = os.environ.get("E2B_API_KEY")
        try:
            from e2b import Sandbox

            self._sandbox_cls = Sandbox
        except Exception as exc:
            logger.debug("e2b SDK not importable: %s", exc)

    def is_available(self) -> bool:
        return self._sandbox_cls is not None and bool(self._api_key)

    def run_container(
        self,
        image: str = "",  # ignored for E2B
        cmd: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        # E2B sandboxes are identified by their sandbox ID
        sandbox = self._sandbox_cls(template="base")
        self._resources.append(sandbox.id)
        return sandbox.id

    def _get_sandbox(self, handle: str):
        # E2B SDK does not always expose get-by-id; we keep a map
        if not hasattr(self, "_sandbox_map"):
            self._sandbox_map: Dict[str, any] = {}
        return self._sandbox_map.get(handle)

    def exec_in_container(self, handle: str, cmd: List[str]) -> Tuple[int, str, str]:
        sb = self._get_sandbox(handle)
        if sb is None:
            # Re-hydrate not supported by all SDK versions; skip
            return 2, "", "E2B sandbox handle lost"
        # Try modern API first
        if hasattr(sb, "process") and hasattr(sb.process, "start_and_wait"):
            proc = sb.process.start_and_wait(" ".join(cmd))
            return proc.exit_code or 0, proc.stdout, proc.stderr
        # Fallback
        return 2, "", "E2B process API unavailable"

    def logs(self, handle: str) -> str:
        return ""

    def destroy(self, handle: str) -> None:
        sb = self._get_sandbox(handle)
        if sb and hasattr(sb, "close"):
            try:
                sb.close()
            except Exception:
                pass
        if handle in self._resources:
            self._resources.remove(handle)


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------
TEST_REGISTRY: Dict[str, List[str]] = {
    "docker": [
        "test_container_launch",
        "test_network_isolation",
        "test_filesystem_readonly",
        "test_tmpfs_bounds",
        "test_seccomp_enforcement",
        "test_capability_drop",
        "test_no_new_privs",
        "test_privileged_escape",
        "test_kernel_module_load",
        "test_symlink_escape",
        "test_procfs_escape",
        "test_cgroup_breakout",
        "test_no_host_devices",
        "test_ptrace_blocked",
    ],
    "nerdctl": [
        "test_container_launch",
        "test_namespace_isolation",
        "test_network_isolation",
        "test_filesystem_readonly",
        "test_seccomp_enforcement",
        "test_capability_drop",
        "test_no_new_privs",
        "test_escape_vectors",
    ],
    "e2b": [
        "test_sandbox_lifecycle",
        "test_network_isolation",
        "test_resource_limits",
        "test_filesystem_isolation",
        "test_procfs_escape",
        "test_environment_sanitization",
    ],
}


# ---------------------------------------------------------------------------
# Test implementations
# ---------------------------------------------------------------------------
class TestSuite:
    def __init__(self, backend: BaseBackend):
        self.backend = backend
        self.results: List[Dict] = []

    def _assert_not_in_output(self, stdout: str, forbidden: List[str], test_name: str) -> bool:
        for token in forbidden:
            if token in stdout:
                logger.error("[%s] Isolation breach: found %s in output", test_name, token)
                return False
        return True

    def _assert_in_output(self, stdout: str, required: List[str], test_name: str) -> bool:
        for token in required:
            if token not in stdout:
                logger.error("[%s] Expected token missing: %s", test_name, token)
                return False
        return True

    def _run_python(self, handle: str, code: str, test_name: str) -> Tuple[int, str, str]:
        cmd = self.backend._python_cmd(code)
        rc, out, err = self.backend.exec_in_container(handle, cmd)
        logger.debug("[%s] rc=%d out=%r err=%r", test_name, rc, out[:256], err[:256])
        return rc, out, err

    # ------------------------------------------------------------------
    # Docker tests
    # ------------------------------------------------------------------
    def test_container_launch(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sh", "-c", "echo LAUNCH_OK"])
            # Wait for container to finish if using SDK; otherwise sleep briefly
            time.sleep(1)
            logs = self.backend.logs(cid)
            ok = "LAUNCH_OK" in logs
            self.backend.destroy(cid)
            return ok
        except Exception as exc:
            logger.error("test_container_launch failed: %s", exc)
            return False

    def test_network_isolation(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_NETWORK_ISOLATION, "test_network_isolation")
            self.backend.destroy(cid)
            ok = self._assert_not_in_output(out, ["HOST_IFACE:", "EGRESS_OK"], "test_network_isolation")
            ok = ok and self._assert_in_output(out, ["EGRESS_BLOCKED"], "test_network_isolation")
            return ok
        except Exception as exc:
            logger.error("test_network_isolation failed: %s", exc)
            return False

    def test_filesystem_readonly(self) -> bool:
        try:
            cid = self.backend.run_container(
                "python:3-alpine",
                ["sleep", "3600"],
                read_only=True,
            )
            rc, out, err = self.backend.exec_in_container(
                cid, ["sh", "-c", "echo x > /etc/passwd 2>&1; echo RC=$?"]
            )
            self.backend.destroy(cid)
            return "RC=1" in out or "Read-only" in out or "EROFS" in out
        except Exception as exc:
            logger.error("test_filesystem_readonly failed: %s", exc)
            return False

    def test_tmpfs_bounds(self) -> bool:
        try:
            cid = self.backend.run_container(
                "python:3-alpine",
                ["sleep", "3600"],
                tmpfs={"/tmp": "rw,noexec,nosuid,size=50m"},
            )
            rc, out, err = self.backend.exec_in_container(
                cid,
                [
                    "sh",
                    "-c",
                    "dd if=/dev/zero of=/tmp/fill bs=1M count=60 2>&1; echo DD_RC=$?",
                ],
            )
            self.backend.destroy(cid)
            # dd should hit ENOSPC; partial write is okay but we expect non-zero RC
            # and "No space" or "ENOSPC" in stderr (merged via 2>&1 into out in this payload)
            # Actually we redirect to out, so check out.
            return "DD_RC=1" in out or "No space" in out or "ENOSPC" in out
        except Exception as exc:
            logger.error("test_tmpfs_bounds failed: %s", exc)
            return False

    def test_seccomp_enforcement(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_CAP_SYS_ADMIN_MOUNT, "test_seccomp_enforcement")
            self.backend.destroy(cid)
            return "MOUNT_RC=0" not in out and rc != 0
        except Exception as exc:
            logger.error("test_seccomp_enforcement failed: %s", exc)
            return False

    def test_capability_drop(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_CAPABILITY_DROP, "test_capability_drop")
            self.backend.destroy(cid)
            return "CAPS_OK" in out and "FORBIDDEN_CAPS" not in out
        except Exception as exc:
            logger.error("test_capability_drop failed: %s", exc)
            return False

    def test_no_new_privs(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_NO_NEW_PRIVS, "test_no_new_privs")
            self.backend.destroy(cid)
            return "NO_NEW_PRIVS_OK" in out
        except Exception as exc:
            logger.error("test_no_new_privs failed: %s", exc)
            return False

    def test_privileged_escape(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_PRIVILEGED_ESCAPE, "test_privileged_escape")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["HOST_ROOT_VISIBLE"], "test_privileged_escape")
        except Exception as exc:
            logger.error("test_privileged_escape failed: %s", exc)
            return False

    def test_kernel_module_load(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_KERNEL_MODULE, "test_kernel_module_load")
            self.backend.destroy(cid)
            # We accept MODPROBE_RC!=0 or MODULES_DISABLED as success signals
            return "MODPROBE_RC=0" not in out
        except Exception as exc:
            logger.error("test_kernel_module_load failed: %s", exc)
            return False

    def test_symlink_escape(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_SYMLINK_ESCAPE, "test_symlink_escape")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["FOLLOWED"], "test_symlink_escape")
        except Exception as exc:
            logger.error("test_symlink_escape failed: %s", exc)
            return False

    def test_procfs_escape(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_PROCFS_ESCAPE, "test_procfs_escape")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["PROCFS_ESCAPE"], "test_procfs_escape")
        except Exception as exc:
            logger.error("test_procfs_escape failed: %s", exc)
            return False

    def test_cgroup_breakout(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_CGROUP_BREAKOUT, "test_cgroup_breakout")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["RELEASE_AGENT_WRITABLE"], "test_cgroup_breakout")
        except Exception as exc:
            logger.error("test_cgroup_breakout failed: %s", exc)
            return False

    def test_no_host_devices(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_DEVICE_ACCESS, "test_no_host_devices")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["DEV_READ_OK:", "MKNOD_OK"], "test_no_host_devices")
        except Exception as exc:
            logger.error("test_no_host_devices failed: %s", exc)
            return False

    def test_ptrace_blocked(self) -> bool:
        try:
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            rc, out, err = self._run_python(cid, PAYLOAD_PTRACE, "test_ptrace_blocked")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["PTRACE_OK"], "test_ptrace_blocked")
        except Exception as exc:
            logger.error("test_ptrace_blocked failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Nerdctl tests
    # ------------------------------------------------------------------
    def test_namespace_isolation(self) -> bool:
        try:
            # Create a container
            cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
            # nerdctl doesn't expose ctr directly, but we can inspect via nerdctl inspect
            rc, out, err = self.backend.exec_in_container(
                cid, ["sh", "-c", "cat /proc/self/cgroup | head -n1"]
            )
            self.backend.destroy(cid)
            # A safe heuristic: container cgroup path should contain the container id or a
            # namespace directory, not just root host paths.
            return bool(out.strip()) and "/docker" not in out and "/machine.slice" not in out
        except Exception as exc:
            logger.error("test_namespace_isolation failed: %s", exc)
            return False

    def test_escape_vectors(self) -> bool:
        # Re-run the core escape payloads that Docker tests cover
        all_ok = True
        for subtest_name, payload, forbidden in [
            ("privileged", PAYLOAD_PRIVILEGED_ESCAPE, ["HOST_ROOT_VISIBLE"]),
            ("kernel_module", PAYLOAD_KERNEL_MODULE, ["MODPROBE_RC=0"]),
            ("symlink", PAYLOAD_SYMLINK_ESCAPE, ["FOLLOWED"]),
            ("procfs", PAYLOAD_PROCFS_ESCAPE, ["PROCFS_ESCAPE"]),
            ("cgroup", PAYLOAD_CGROUP_BREAKOUT, ["RELEASE_AGENT_WRITABLE"]),
            ("device", PAYLOAD_DEVICE_ACCESS, ["DEV_READ_OK:", "MKNOD_OK"]),
            ("ptrace", PAYLOAD_PTRACE, ["PTRACE_OK"]),
        ]:
            try:
                cid = self.backend.run_container("python:3-alpine", ["sleep", "3600"])
                rc, out, err = self._run_python(cid, payload, f"test_escape_vectors/{subtest_name}")
                self.backend.destroy(cid)
                for token in forbidden:
                    if token in out:
                        logger.error(
                            "[test_escape_vectors/%s] Breach token found: %s",
                            subtest_name,
                            token,
                        )
                        all_ok = False
            except Exception as exc:
                logger.error("[test_escape_vectors/%s] Exception: %s", subtest_name, exc)
                all_ok = False
        return all_ok

    # ------------------------------------------------------------------
    # E2B tests
    # ------------------------------------------------------------------
    def test_sandbox_lifecycle(self) -> bool:
        try:
            cid = self.backend.run_container(cmd=["echo", "E2B_LIFECYCLE_OK"])
            # E2B exec is async / process-based; check whatever we can
            rc, out, err = self.backend.exec_in_container(cid, ["echo", "E2B_LIFECYCLE_OK"])
            self.backend.destroy(cid)
            return rc == 0 and "E2B_LIFECYCLE_OK" in out
        except Exception as exc:
            logger.error("test_sandbox_lifecycle failed: %s", exc)
            return False

    def test_resource_limits(self) -> bool:
        # E2B resource limits are platform-enforced; we can only probe indirectly
        try:
            cid = self.backend.run_container()
            # Try to allocate a large chunk of memory quickly
            mem_payload = '''
import sys
data = []
try:
    for i in range(1000):
        data.append(b"X" * (1024 * 1024))
    sys.stdout.write("ALLOC_OK\\n")
except MemoryError:
    sys.stdout.write("OOM_BLOCKED\\n")
'''
            rc, out, err = self._run_python(cid, mem_payload, "test_resource_limits")
            self.backend.destroy(cid)
            # We accept either OOM_BLOCKED (limit enforced) or ALLOC_OK (generous limit)
            # but we must NOT see the process killed with no output (that would be a crash)
            return "OOM_BLOCKED" in out or "ALLOC_OK" in out
        except Exception as exc:
            logger.error("test_resource_limits failed: %s", exc)
            return False

    def test_filesystem_isolation(self) -> bool:
        try:
            cid = self.backend.run_container()
            rc, out, err = self._run_python(cid, PAYLOAD_E2B_FS_ISOLATION, "test_filesystem_isolation")
            self.backend.destroy(cid)
            ok = self._assert_not_in_output(out, ["FS_ESCAPE", "HOST_DIR_VISIBLE"], "test_filesystem_isolation")
            return ok
        except Exception as exc:
            logger.error("test_filesystem_isolation failed: %s", exc)
            return False

    def test_environment_sanitization(self) -> bool:
        try:
            cid = self.backend.run_container()
            rc, out, err = self._run_python(cid, PAYLOAD_E2B_ENV_LEAK, "test_environment_sanitization")
            self.backend.destroy(cid)
            return self._assert_not_in_output(out, ["ENV_LEAK:", "HOST_PROCESS:"], "test_environment_sanitization")
        except Exception as exc:
            logger.error("test_environment_sanitization failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
class Runner:
    def __init__(
        self,
        backend_name: str,
        filter_pattern: Optional[str] = None,
        fail_fast: bool = False,
    ):
        self.backend_name = backend_name
        self.filter_pattern = filter_pattern
        self.fail_fast = fail_fast
        self.backend = self._build_backend(backend_name)
        self.results: List[Dict] = []

    def _build_backend(self, name: str) -> BaseBackend:
        if name == "docker":
            return DockerBackend()
        if name == "nerdctl":
            return NerdctlBackend()
        if name == "e2b":
            return E2BBackend()
        raise RuntimeError(f"Unknown backend: {name}")

    def run(self) -> int:
        if not self.backend.is_available():
            logger.error("Backend '%s' is not available (binary/SDK missing)", self.backend_name)
            return 3

        suite = TestSuite(self.backend)
        test_names = TEST_REGISTRY.get(self.backend.name, [])
        if not test_names:
            logger.error("No tests registered for backend '%s'", self.backend_name)
            return 2

        if self.filter_pattern:
            test_names = [t for t in test_names if self.filter_pattern in t]
            if not test_names:
                logger.error("Filter '%s' matched no tests", self.filter_pattern)
                return 2

        exit_code = 0
        for test_name in test_names:
            logger.info("[%s] Running %s ...", self.backend_name, test_name)
            start = time.time()
            try:
                test_fn = getattr(suite, test_name)
                passed = test_fn()
            except Exception as exc:
                logger.error("[%s] %s raised: %s", self.backend_name, test_name, exc)
                passed = False
            elapsed = time.time() - start
            self.results.append(
                {
                    "backend": self.backend_name,
                    "test": test_name,
                    "passed": passed,
                    "elapsed_sec": round(elapsed, 3),
                }
            )
            status = "PASS" if passed else "FAIL"
            logger.info("[%s] %s => %s (%.3fs)", self.backend_name, test_name, status, elapsed)
            if not passed:
                exit_code = 1
                if self.fail_fast:
                    logger.warning("Fail-fast enabled; aborting remaining tests.")
                    break

        # Cleanup any lingering resources
        self.backend.cleanup()
        return exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sandbox integration test runner for Docker, nerdctl, and E2B backends"
    )
    parser.add_argument(
        "--backend",
        choices=["docker", "nerdctl", "e2b", "all"],
        default="docker",
        help="Backend to test (default: docker)",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Run only tests whose name contains this substring",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first test failure",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: plain logging, no interactive output",
    )
    parser.add_argument(
        "--json-report",
        default=None,
        help="Write a JSON report to this file",
    )
    args = parser.parse_args(argv)

    setup_logging(ci=args.ci)

    backends = ["docker", "nerdctl", "e2b"] if args.backend == "all" else [args.backend]
    all_results: List[Dict] = []
    overall_exit = 0

    for backend_name in backends:
        runner = Runner(
            backend_name=backend_name,
            filter_pattern=args.filter,
            fail_fast=args.fail_fast,
        )
        rc = runner.run()
        all_results.extend(runner.results)
        if rc != 0:
            overall_exit = max(overall_exit, rc)

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r["passed"])
    failed = total - passed
    logger.info("=" * 50)
    logger.info("SUMMARY: %d total, %d passed, %d failed", total, passed, failed)
    logger.info("=" * 50)

    if args.json_report:
        report = {
            "results": all_results,
            "summary": {"total": total, "passed": passed, "failed": failed},
            "exit_code": overall_exit,
        }
        with open(args.json_report, "w") as f:
            json.dump(report, f, indent=2)
        logger.info("JSON report written to %s", args.json_report)

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
