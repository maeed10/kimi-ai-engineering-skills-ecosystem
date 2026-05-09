#!/usr/bin/env python3
"""
validate_allowlist.py

Validates a sandbox-config.yaml against the executable_allowlist schema defined in
references/allowlist_schema.md.

Exit codes:
  0  Valid config.
  1  Schema violation or blocked syscall detected.
  2  CLI usage error.
  3  File I/O or YAML parse error.

Usage:
  python validate_allowlist.py --config sandbox-config.yaml [--strict-syscalls] [--max-entries 10] [--emit-seccomp profile.json] [--emit-minibin ./mini_bin/]
"""

import argparse
import json
import os
import re
import sys
import typing as t
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"

MANDATORY_SYSCALLS = frozenset(
    {
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
        "gettimeofday",
    }
)

BLOCKED_SYSCALLS = frozenset(
    {
        "ptrace",
        "personality",
        "mount",
        "umount2",
        "reboot",
        "kexec_load",
        "open_by_handle_at",
        "init_module",
        "finit_module",
    }
)

SHELL_METACHARS = re.compile(r"[;|&$`<>\(\)\*\?\[\]\{\}]")

ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

PATH_RE = re.compile(r"^/[^.]*$")

BASELINE_ALLOW_SYSCALLS = [
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
]

NETWORK_SYSCALLS = [
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
    "getsockopt",
]


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(errs: t.List[str]) -> str:
    return "\n  - " + "\n  - ".join(errs)


def _validate_path(path: str, idx: int) -> t.List[str]:
    errs: t.List[str] = []
    if not isinstance(path, str):
        errs.append(f"entry[{idx}].path must be a string")
        return errs
    if not path.startswith("/"):
        errs.append(f"entry[{idx}].path must be absolute: {path!r}")
    if ".." in path:
        errs.append(f"entry[{idx}].path contains relative segment: {path!r}")
    if not PATH_RE.match(path):
        errs.append(f"entry[{idx}].path contains suspicious characters: {path!r}")
    return errs


def _validate_args(args: t.Any, idx: int) -> t.List[str]:
    errs: t.List[str] = []
    if not isinstance(args, list) or len(args) == 0:
        errs.append(f"entry[{idx}].args must be a non-empty list")
        return errs
    for a_idx, arg_pat in enumerate(args):
        prefix = f"entry[{idx}].args[{a_idx}]"
        if not isinstance(arg_pat, dict):
            errs.append(f"{prefix} must be a dict")
            continue
        pattern = arg_pat.get("pattern")
        if not isinstance(pattern, list) or len(pattern) == 0:
            errs.append(f"{prefix}.pattern must be a non-empty list")
            continue
        for token in pattern:
            if not isinstance(token, str):
                errs.append(f"{prefix}.pattern contains non-string: {token!r}")
                continue
            if SHELL_METACHARS.search(token):
                errs.append(
                    f"{prefix}.pattern contains shell metacharacter: {token!r}"
                )
        allow_extra = arg_pat.get("allow_extra_args", False)
        if not isinstance(allow_extra, bool):
            errs.append(f"{prefix}.allow_extra_args must be boolean")
    return errs


def _validate_env(env: t.Any, idx: int) -> t.List[str]:
    errs: t.List[str] = []
    if env is None:
        return errs
    if not isinstance(env, list):
        errs.append(f"entry[{idx}].env must be a list")
        return errs
    for e_idx, rule in enumerate(env):
        prefix = f"entry[{idx}].env[{e_idx}]"
        if not isinstance(rule, dict):
            errs.append(f"{prefix} must be a dict")
            continue
        name = rule.get("name")
        if not isinstance(name, str) or not ENV_NAME_RE.match(name):
            errs.append(f"{prefix}.name invalid: {name!r}")
        value = rule.get("value")
        value_regex = rule.get("value_regex")
        if value is not None and value_regex is not None:
            errs.append(f"{prefix} has both 'value' and 'value_regex'")
        if value is not None and not isinstance(value, str):
            errs.append(f"{prefix}.value must be a string")
        if value_regex is not None:
            try:
                re.compile(value_regex)
            except re.error as exc:
                errs.append(f"{prefix}.value_regex invalid regex: {exc}")
    return errs


def _validate_syscalls(syscalls: t.Any, idx: int, strict: bool) -> t.List[str]:
    errs: t.List[str] = []
    if syscalls is None:
        return errs
    if not isinstance(syscalls, list):
        errs.append(f"entry[{idx}].allowed_syscalls must be a list")
        return errs
    for s_idx, name in enumerate(syscalls):
        if not isinstance(name, str):
            errs.append(f"entry[{idx}].allowed_syscalls[{s_idx}] non-string: {name!r}")
            continue
        if name in BLOCKED_SYSCALLS:
            errs.append(
                f"entry[{idx}].allowed_syscalls lists blocked syscall: {name}"
            )
    if strict:
        declared = set(syscalls)
        missing = MANDATORY_SYSCALLS - declared
        if missing:
            errs.append(
                f"entry[{idx}].allowed_syscalls missing mandatory syscalls: {sorted(missing)}"
            )
    return errs


def _validate_entry(entry: t.Any, idx: int, strict: bool) -> t.List[str]:
    errs: t.List[str] = []
    if not isinstance(entry, dict):
        errs.append(f"entry[{idx}] must be a dict")
        return errs

    # path
    path = entry.get("path")
    errs.extend(_validate_path(path, idx))

    # args
    args = entry.get("args")
    errs.extend(_validate_args(args, idx))

    # env
    env = entry.get("env")
    errs.extend(_validate_env(env, idx))

    # max_processes
    max_p = entry.get("max_processes", 1)
    if not isinstance(max_p, int) or not (1 <= max_p <= 64):
        errs.append(f"entry[{idx}].max_processes must be an integer in [1, 64]")

    # allowed_syscalls
    syscalls = entry.get("allowed_syscalls")
    errs.extend(_validate_syscalls(syscalls, idx, strict))

    return errs


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------


def _emit_seccomp(config: t.Dict[str, t.Any], out_path: Path) -> None:
    entries = config.get("executable_allowlist", [])
    allowed_paths = [e["path"] for e in entries]
    syscalls_set: t.Set[str] = set()
    for e in entries:
        syscalls_set.update(e.get("allowed_syscalls", []))
    # If no syscalls declared, use baseline + network defaults
    if not syscalls_set:
        syscalls_set = set(BASELINE_ALLOW_SYSCALLS + NETWORK_SYSCALLS)
    else:
        syscalls_set |= MANDATORY_SYSCALLS

    syscall_groups: t.List[t.Dict[str, t.Any]] = [
        {
            "names": sorted(syscalls_set),
            "action": "SCMP_ACT_ALLOW",
        }
    ]

    # execve rules per path
    for p in allowed_paths:
        syscall_groups.append(
            {
                "names": ["execve", "execveat"],
                "action": "SCMP_ACT_ALLOW",
                "args": [
                    {
                        "index": 0,
                        "type": "SCMP_APATH",
                        "op": "SCMP_CMP_EQ",
                        "value": p,
                    }
                ],
            }
        )

    # catch-all execve deny
    syscall_groups.append(
        {
            "names": ["execve", "execveat"],
            "action": "SCMP_ACT_ERRNO",
        }
    )

    profile = {
        "defaultAction": "SCMP_ACT_ERRNO",
        "archMap": [
            {
                "architecture": "SCMP_ARCH_X86_64",
                "subArchitectures": ["SCMP_ARCH_X86"],
            }
        ],
        "syscalls": syscall_groups,
    }

    out_path.write_text(json.dumps(profile, indent=2))
    print(f"[+] seccomp profile written to {out_path}")


def _emit_minibin(config: t.Dict[str, t.Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = config.get("executable_allowlist", [])
    for e in entries:
        src = e["path"]
        name = os.path.basename(src)
        link = out_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(src)
        print(f"[+] symlinked {link} -> {src}")
    print(f"[+] minimal /bin overlay ready in {out_dir}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def validate(config_path: Path, strict_syscalls: bool, max_entries: int) -> t.List[str]:
    raw = config_path.read_text()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValidationError("YAML root must be a dict")

    allowlist = data.get("executable_allowlist")
    if allowlist is None:
        raise ValidationError("missing top-level key 'executable_allowlist'")
    if not isinstance(allowlist, list):
        raise ValidationError("'executable_allowlist' must be a list")
    if len(allowlist) == 0:
        raise ValidationError("'executable_allowlist' must not be empty")
    if len(allowlist) > max_entries:
        raise ValidationError(
            f"'executable_allowlist' exceeds max entries ({len(allowlist)} > {max_entries})"
        )

    errs: t.List[str] = []
    for idx, entry in enumerate(allowlist):
        errs.extend(_validate_entry(entry, idx, strict_syscalls))

    # forbidden binaries check
    forbidden = {"/bin/sh", "/bin/bash", "/usr/bin/bash", "/usr/bin/sh", "/bin/dash"}
    for idx, entry in enumerate(allowlist):
        path = entry.get("path", "")
        if path in forbidden:
            errs.append(
                f"entry[{idx}].path is a forbidden shell interpreter: {path}"
            )
        if path == "/usr/bin/python3" or path == "/usr/bin/python":
            args = entry.get("args", [])
            for a_idx, ap in enumerate(args):
                pat = ap.get("pattern", [])
                if pat == ["*"] or ap.get("allow_extra_args") is True and not pat:
                    errs.append(
                        f"entry[{idx}].args[{a_idx}] allows unrestricted python execution"
                    )

    return errs


def main(argv: t.Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Validate sandbox-config.yaml executable_allowlist"
    )
    parser.add_argument("--config", required=True, type=Path, help="Path to YAML config")
    parser.add_argument(
        "--strict-syscalls",
        action="store_true",
        help="Require all mandatory syscalls to be explicitly listed",
    )
    parser.add_argument(
        "--max-entries", type=int, default=10, help="Maximum allowlist entries"
    )
    parser.add_argument(
        "--emit-seccomp", type=Path, help="Write generated seccomp JSON to this path"
    )
    parser.add_argument(
        "--emit-minibin", type=Path, help="Write minimal /bin overlay to this directory"
    )
    args = parser.parse_args(argv)

    try:
        errs = validate(args.config, args.strict_syscalls, args.max_entries)
    except yaml.YAMLError as exc:
        print(f"[!] YAML parse error: {exc}", file=sys.stderr)
        return 3
    except ValidationError as exc:
        print(f"[!] Validation failed: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"[!] I/O error: {exc}", file=sys.stderr)
        return 3

    if errs:
        print(f"[!] Found {len(errs)} violation(s):{_fmt(errs)}", file=sys.stderr)
        return 1

    print(f"[+] Config valid (schema {SCHEMA_VERSION}, {args.config})")

    try:
        raw = args.config.read_text()
        data = yaml.safe_load(raw)
    except Exception as exc:
        print(f"[!] Re-read failed: {exc}", file=sys.stderr)
        return 3

    if args.emit_seccomp:
        _emit_seccomp(data, args.emit_seccomp)

    if args.emit_minibin:
        _emit_minibin(data, args.emit_minibin)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
