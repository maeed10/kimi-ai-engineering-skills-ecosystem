#!/usr/bin/env python3
"""
Dynamic Behavior Analyzer
Runs code in an instrumented sandbox with strace, then analyzes syscalls,
network attempts, filesystem access, and timing patterns for anomalies.

Usage:
    # Analyze existing strace log
    python analyze_behavior.py \
        --strace-log strace.log \
        --code-file target.py \
        --write-paths /tmp,/output \
        --report-json behavior_report.json

    # Full pipeline: run code + analyze
    python analyze_behavior.py \
        --run \
        --code target.py \
        --interpreter python3 \
        --write-paths /tmp,/output \
        --report-json behavior_report.json

    # With custom thresholds
    python analyze_behavior.py \
        --run \
        --code target.py \
        --interpreter python3 \
        --thresholds-override custom_thresholds.json \
        --report-json behavior_report.json
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class Severity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskDecision(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    BLOCK_DELIVERY = "BLOCK_DELIVERY"


@dataclass
class SyscallEvent:
    pid: int
    timestamp_ms: float
    syscall: str
    args: str
    result: str
    line: str


@dataclass
class Anomaly:
    severity: Severity
    category: str
    syscall: str
    pid: int
    timestamp_ms: float
    args: str
    details: str


@dataclass
class TimingProfile:
    total_duration_ms: float = 0.0
    syscalls_per_second: float = 0.0
    nanosleep_total_ms: float = 0.0
    nanosleep_count: int = 0
    clock_query_per_second: float = 0.0
    alarm_count: int = 0
    max_consecutive_identical: int = 0
    anomalies: list = field(default_factory=list)


@dataclass
class FilesystemProfile:
    accessed_paths: list = field(default_factory=list)
    writes_outside_allowed: list = field(default_factory=list)
    sensitive_path_accesses: list = field(default_factory=list)
    files_created: list = field(default_factory=list)
    files_deleted: list = field(default_factory=list)
    symlinks_created: list = field(default_factory=list)
    chmod_events: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)


@dataclass
class NetworkProfile:
    connection_attempts: list = field(default_factory=list)
    socket_events: list = field(default_factory=list)
    send_events: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)


@dataclass
class ProcessProfile:
    child_processes: int = 0
    threads: int = 0
    execve_events: list = field(default_factory=list)
    kill_events: list = field(default_factory=list)
    ptrace_events: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)


class Thresholds:
    """Default anomaly thresholds."""

    # Timing
    MAX_EXECUTION_TIME_SECONDS = 30
    MAX_WALL_CLOCK_SECONDS = 60
    MAX_SYSCALLS_PER_SECOND = 10_000
    MAX_NANOSLEEP_TOTAL_SECONDS = 10
    MAX_NANOSLEEP_COUNT = 100
    MAX_CLOCK_QUERY_PER_SECOND = 1_000
    MAX_ALARM_COUNT = 5
    MAX_CONSECUTIVE_IDENTICAL_SYSCALLS = 1_000

    # Network
    MAX_INET_SOCKET_ATTEMPTS = 0
    MAX_INET6_SOCKET_ATTEMPTS = 0
    MAX_NETLINK_SOCKET_ATTEMPTS = 0
    MAX_CONNECT_ATTEMPTS = 0
    MAX_BIND_ATTEMPTS = 0
    MAX_SEND_PAYLOADS = 0
    MAX_TOTAL_NETWORK_SYSCALLS = 5
    MAX_DNS_ATTEMPTS = 0

    # Filesystem
    MAX_WRITE_PATHS_OUTSIDE_DECLARED = 0
    MAX_FILES_CREATED = 50
    MAX_FILES_DELETED = 10
    MAX_TOTAL_WRITE_MB = 100
    MAX_SENSITIVE_PATH_READS = 0
    MAX_SENSITIVE_PATH_WRITES = 0
    MAX_SYMLINKS_CREATED = 0
    MAX_HARDLINKS_CREATED = 0
    MAX_CHMOD_COUNT = 0
    MAX_RMDIR_COUNT = 0
    MAX_TEMP_FILES = 20

    # Process
    MAX_CHILD_PROCESSES = 5
    MAX_THREADS = 10
    MAX_EXECVE_CALLS = 0
    MAX_KILL_CALLS = 0
    MAX_PTRACE_CALLS = 0

    # Sensitive path patterns
    SENSITIVE_PATH_PATTERNS = [
        r"^/etc/shadow$",
        r"^/etc/shadow-$",
        r"^/etc/gshadow$",
        r"^/etc/gshadow-$",
        r"^/etc/master\.passwd$",
        r"^/etc/security/passwd$",
        r"^/etc/sudoers$",
        r"^/etc/sudoers\.d/",
        r"^/etc/ssh/sshd_config$",
        r"^/etc/ssh/ssh_host_.*_key$",
        r"^/root/",
        r"^/home/.*/\.ssh/",
        r"^/home/.*/\.gnupg/",
        r"^/home/.*/\.aws/",
        r"^/home/.*/\.azure/",
        r"^/proc/1/",
        r"^/proc/kcore$",
        r"^/proc/kallsyms$",
        r"^/sys/kernel/debug/",
        r"^/dev/mem$",
        r"^/dev/kmem$",
        r"^/dev/port$",
        r"^/boot/",
    ]

    def __init__(self, override_path: Optional[str] = None):
        if override_path and os.path.exists(override_path):
            with open(override_path) as f:
                override = json.load(f)
            self._apply_override(override)

    def _apply_override(self, override: dict):
        for section, values in override.items():
            for key, value in values.items():
                attr_name = f"{section.upper()}_{key.upper()}" if section != "sensitive_paths" else key
                if hasattr(self, attr_name):
                    setattr(self, attr_name, value)
                else:
                    # Try common naming variations
                    alt_name = key.upper()
                    if hasattr(self, alt_name):
                        setattr(self, alt_name, value)


STRACE_RE = re.compile(
    r"^(?P<pid>\d+)?\s*(?P<timestamp>\d+:\d+:\d+\.\d+)?\s*(?P<syscall>\w+)\((?P<args>.*)\)\s*=\s*(?P<result>-?[\w\s/]+)"
)

def parse_strace_log(log_path: str) -> list[SyscallEvent]:
    """Parse strace -ff log output into structured events."""
    events = []
    pid = 0

    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("strace:"):
                continue

            # Try to extract PID from log filename pattern (strace.log.PID)
            # and timestamp/syscall from line content
            m = STRACE_RE.match(line)
            if m:
                groups = m.groupdict()
                syscall = groups.get("syscall", "")
                args = groups.get("args", "")
                result = groups.get("result", "").strip()

                # Extract PID from filename if multiple logs
                if ".log." in log_path:
                    pid_str = log_path.rsplit(".", 1)[-1]
                    try:
                        pid = int(pid_str)
                    except ValueError:
                        pass

                # Parse timestamp if present
                ts_str = groups.get("timestamp", "")
                ts_ms = 0.0
                if ts_str:
                    try:
                        parts = ts_str.split(":")
                        ts_ms = (
                            float(parts[0]) * 3600
                            + float(parts[1]) * 60
                            + float(parts[2])
                        ) * 1000
                    except (ValueError, IndexError):
                        pass

                events.append(
                    SyscallEvent(
                        pid=pid,
                        timestamp_ms=ts_ms,
                        syscall=syscall,
                        args=args,
                        result=result,
                        line=line,
                    )
                )

    return events


def parse_strace_log_dir(log_dir: str) -> list[SyscallEvent]:
    """Parse all strace -ff log files in a directory."""
    all_events = []
    log_path = Path(log_dir)

    # Check if it's a single file
    if log_path.is_file():
        return parse_strace_log(str(log_path))

    # Check for strace.log (single file) first
    single_log = log_path / "strace.log"
    if single_log.exists():
        return parse_strace_log(str(single_log))

    # Check for strace.log.PID files
    for log_file in sorted(log_path.glob("strace.log.*")):
        all_events.extend(parse_strace_log(str(log_file)))

    # Sort by timestamp
    all_events.sort(key=lambda e: e.timestamp_ms)
    return all_events


def analyze_timing(events: list[SyscallEvent], total_duration_ms: float, thresholds: Thresholds) -> TimingProfile:
    """Analyze timing patterns in syscall trace."""
    profile = TimingProfile(total_duration_ms=total_duration_ms)

    if total_duration_ms > 0:
        profile.syscalls_per_second = len(events) / (total_duration_ms / 1000.0)

    prev_syscall = None
    consecutive_count = 0
    max_consecutive = 0
    clock_queries = 0
    clock_window_start = 0
    max_clock_per_sec = 0

    for event in events:
        # nanosleep tracking
        if event.syscall in ("nanosleep", "clock_nanosleep"):
            profile.nanosleep_count += 1
            # Parse sleep duration from args
            try:
                duration_match = re.search(r"\{(\d+),\s*(\d+)\}", event.args)
                if duration_match:
                    sec = int(duration_match.group(1))
                    nsec = int(duration_match.group(2))
                    profile.nanosleep_total_ms += sec * 1000 + nsec / 1e6
                else:
                    # Try simple float pattern
                    duration_match = re.search(r"([\d.]+)", event.args)
                    if duration_match:
                        profile.nanosleep_total_ms += float(duration_match.group(1)) * 1000
            except (ValueError, AttributeError):
                pass

        # alarm tracking
        if event.syscall in ("alarm", "setitimer", "timer_create"):
            profile.alarm_count += 1

        # clock query tracking (per-second rate)
        if event.syscall in ("clock_gettime", "gettimeofday", "time"):
            clock_queries += 1
            if event.timestamp_ms - clock_window_start >= 1000:
                max_clock_per_sec = max(max_clock_per_sec, clock_queries)
                clock_queries = 0
                clock_window_start = event.timestamp_ms

        # consecutive identical syscall tracking
        if event.syscall == prev_syscall:
            consecutive_count += 1
            max_consecutive = max(max_consecutive, consecutive_count)
        else:
            consecutive_count = 1
            prev_syscall = event.syscall

    profile.max_consecutive_identical = max_consecutive
    profile.clock_query_per_second = max_clock_per_sec

    # Detect anomalies
    if total_duration_ms > thresholds.MAX_EXECUTION_TIME_SECONDS * 1000:
        profile.anomalies.append(
            Anomaly(
                severity=Severity.HIGH,
                category="timing",
                syscall="N/A",
                pid=0,
                timestamp_ms=total_duration_ms,
                args="",
                details=f"Execution time {total_duration_ms/1000:.1f}s exceeds threshold {thresholds.MAX_EXECUTION_TIME_SECONDS}s",
            )
        )

    if profile.syscalls_per_second > thresholds.MAX_SYSCALLS_PER_SECOND:
        profile.anomalies.append(
            Anomaly(
                severity=Severity.HIGH,
                category="timing",
                syscall="N/A",
                pid=0,
                timestamp_ms=0,
                args="",
                details=f"Syscall rate {profile.syscalls_per_second:.0f}/sec exceeds threshold {thresholds.MAX_SYSCALLS_PER_SECOND}/sec",
            )
        )

    if profile.nanosleep_total_ms > thresholds.MAX_NANOSLEEP_TOTAL_SECONDS * 1000:
        profile.anomalies.append(
            Anomaly(
                severity=Severity.MEDIUM,
                category="timing",
                syscall="nanosleep",
                pid=0,
                timestamp_ms=profile.nanosleep_total_ms,
                args="",
                details=f"Total sleep {profile.nanosleep_total_ms/1000:.1f}s exceeds threshold {thresholds.MAX_NANOSLEEP_TOTAL_SECONDS}s",
            )
        )

    if profile.clock_query_per_second > thresholds.MAX_CLOCK_QUERY_PER_SECOND:
        profile.anomalies.append(
            Anomaly(
                severity=Severity.LOW,
                category="timing",
                syscall="clock_gettime",
                pid=0,
                timestamp_ms=0,
                args="",
                details=f"Clock query rate {profile.clock_query_per_second}/sec exceeds threshold",
            )
        )

    if max_consecutive > thresholds.MAX_CONSECUTIVE_IDENTICAL_SYSCALLS:
        profile.anomalies.append(
            Anomaly(
                severity=Severity.MEDIUM,
                category="timing",
                syscall=prev_syscall or "unknown",
                pid=0,
                timestamp_ms=0,
                args="",
                details=f"Consecutive identical syscalls: {max_consecutive}",
            )
        )

    return profile


def analyze_network(events: list[SyscallEvent], thresholds: Thresholds) -> NetworkProfile:
    """Analyze network-related syscalls."""
    profile = NetworkProfile()
    inet_sockets = 0
    inet6_sockets = 0
    netlink_sockets = 0
    connect_count = 0
    bind_count = 0
    send_count = 0
    dns_count = 0

    for event in events:
        if event.syscall == "socket":
            profile.socket_events.append(event)
            if "AF_INET" in event.args and "AF_INET6" not in event.args:
                inet_sockets += 1
                if inet_sockets > thresholds.MAX_INET_SOCKET_ATTEMPTS:
                    profile.anomalies.append(
                        Anomaly(
                            severity=Severity.MEDIUM,
                            category="network",
                            syscall="socket",
                            pid=event.pid,
                            timestamp_ms=event.timestamp_ms,
                            args=event.args,
                            details=f"AF_INET socket creation #{inet_sockets} (threshold: {thresholds.MAX_INET_SOCKET_ATTEMPTS})",
                        )
                    )
            elif "AF_INET6" in event.args:
                inet6_sockets += 1
                if inet6_sockets > thresholds.MAX_INET6_SOCKET_ATTEMPTS:
                    profile.anomalies.append(
                        Anomaly(
                            severity=Severity.MEDIUM,
                            category="network",
                            syscall="socket",
                            pid=event.pid,
                            timestamp_ms=event.timestamp_ms,
                            args=event.args,
                            details=f"AF_INET6 socket creation #{inet6_sockets}",
                        )
                    )
            elif "AF_NETLINK" in event.args:
                netlink_sockets += 1
                if netlink_sockets > thresholds.MAX_NETLINK_SOCKET_ATTEMPTS:
                    profile.anomalies.append(
                        Anomaly(
                            severity=Severity.SUSPICIOUS,
                            category="network",
                            syscall="socket",
                            pid=event.pid,
                            timestamp_ms=event.timestamp_ms,
                            args=event.args,
                            details="AF_NETLINK socket creation detected",
                        )
                    )

        elif event.syscall == "connect":
            connect_count += 1
            profile.connection_attempts.append({
                "syscall": "connect",
                "address": event.args,
                "result": event.result,
                "pid": event.pid,
                "timestamp_ms": event.timestamp_ms,
            })
            profile.anomalies.append(
                Anomaly(
                    severity=Severity.HIGH,
                    category="network",
                    syscall="connect",
                    pid=event.pid,
                    timestamp_ms=event.timestamp_ms,
                    args=event.args,
                    details=f"Connection attempt #{connect_count} to {event.args} (result: {event.result})",
                )
            )

        elif event.syscall in ("sendto", "sendmsg", "sendmmsg"):
            send_count += 1
            profile.send_events.append(event)
            if send_count > thresholds.MAX_SEND_PAYLOADS:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.HIGH,
                        category="network",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args[:200],
                        details=f"Network send #{send_count}",
                    )
                )

        elif event.syscall == "bind":
            bind_count += 1
            if bind_count > thresholds.MAX_BIND_ATTEMPTS:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.SUSPICIOUS,
                        category="network",
                        syscall="bind",
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Bind attempt #{bind_count}",
                    )
                )

        elif event.syscall in ("gethostbyname", "getaddrinfo", "gethostbyaddr"):
            dns_count += 1
            profile.anomalies.append(
                Anomaly(
                    severity=Severity.HIGH,
                    category="network",
                    syscall=event.syscall,
                    pid=event.pid,
                    timestamp_ms=event.timestamp_ms,
                    args=event.args,
                    details=f"DNS resolution attempt #{dns_count}",
                )
            )

    total_network = inet_sockets + inet6_sockets + netlink_sockets + connect_count + bind_count + send_count
    if total_network > thresholds.MAX_TOTAL_NETWORK_SYSCALLS:
        # Add a summary anomaly if the total is high but individual ones didn't trigger
        existing_categories = {a.syscall for a in profile.anomalies}
        if not existing_categories:
            profile.anomalies.append(
                Anomaly(
                    severity=Severity.LOW,
                    category="network",
                    syscall="N/A",
                    pid=0,
                    timestamp_ms=0,
                    args="",
                    details=f"Total network syscalls {total_network} exceeds threshold {thresholds.MAX_TOTAL_NETWORK_SYSCALLS}",
                )
            )

    return profile


def _is_sensitive_path(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any sensitive path pattern."""
    for pattern in patterns:
        if re.search(pattern, path):
            return True
    return False


def _path_in_allowed(path: str, allowed_paths: list[str]) -> bool:
    """Check if a path is within allowed paths."""
    path = os.path.abspath(path)
    for allowed in allowed_paths:
        allowed = os.path.abspath(allowed)
        if path == allowed or path.startswith(allowed + "/"):
            return True
    return False


def analyze_filesystem(events: list[SyscallEvent], write_paths: list[str], thresholds: Thresholds) -> FilesystemProfile:
    """Analyze filesystem-related syscalls."""
    profile = FilesystemProfile()
    files_created = 0
    files_deleted = 0
    symlinks_created = 0
    chmod_count = 0
    rmdir_count = 0

    for event in events:
        if event.syscall in ("open", "openat"):
            # Extract path from args
            path_match = re.search(r'"([^"]+)"', event.args)
            if not path_match:
                continue
            path = path_match.group(1)
            profile.accessed_paths.append(path)

            # Check for sensitive path access
            if _is_sensitive_path(path, thresholds.SENSITIVE_PATH_PATTERNS):
                # Determine if read or write
                is_write = any(
                    flag in event.args
                    for flag in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND")
                )
                if is_write and thresholds.MAX_SENSITIVE_PATH_WRITES == 0:
                    profile.anomalies.append(
                        Anomaly(
                            severity=Severity.CRITICAL,
                            category="filesystem",
                            syscall=event.syscall,
                            pid=event.pid,
                            timestamp_ms=event.timestamp_ms,
                            args=event.args,
                            details=f"Write to sensitive path: {path}",
                        )
                    )
                elif thresholds.MAX_SENSITIVE_PATH_READS == 0:
                    profile.anomalies.append(
                        Anomaly(
                            severity=Severity.MEDIUM,
                            category="filesystem",
                            syscall=event.syscall,
                            pid=event.pid,
                            timestamp_ms=event.timestamp_ms,
                            args=event.args,
                            details=f"Read from sensitive path: {path}",
                        )
                    )
                profile.sensitive_path_accesses.append(path)

            # Check for writes outside declared paths
            if any(flag in event.args for flag in ("O_WRONLY", "O_RDWR", "O_CREAT")):
                if not _path_in_allowed(path, write_paths):
                    profile.writes_outside_allowed.append(path)
                    if len(profile.writes_outside_allowed) > thresholds.MAX_WRITE_PATHS_OUTSIDE_DECLARED:
                        profile.anomalies.append(
                            Anomaly(
                                severity=Severity.MEDIUM,
                                category="filesystem",
                                syscall=event.syscall,
                                pid=event.pid,
                                timestamp_ms=event.timestamp_ms,
                                args=event.args,
                                details=f"Write outside declared paths: {path}",
                            )
                        )

        elif event.syscall == "creat":
            files_created += 1
            path_match = re.search(r'"([^"]+)"', event.args)
            if path_match:
                profile.files_created.append(path_match.group(1))

        elif event.syscall in ("unlink", "unlinkat"):
            files_deleted += 1
            path_match = re.search(r'"([^"]+)"', event.args)
            if path_match:
                profile.files_deleted.append(path_match.group(1))
            if files_deleted > thresholds.MAX_FILES_DELETED:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.MEDIUM,
                        category="filesystem",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"File deletion #{files_deleted} exceeds threshold {thresholds.MAX_FILES_DELETED}",
                    )
                )

        elif event.syscall in ("symlink", "symlinkat"):
            symlinks_created += 1
            if symlinks_created > thresholds.MAX_SYMLINKS_CREATED:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.MEDIUM,
                        category="filesystem",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Symlink creation #{symlinks_created}",
                    )
                )

        elif event.syscall in ("chmod", "fchmod", "fchmodat"):
            chmod_count += 1
            # Check for SUID/SGID
            if "S_ISUID" in event.args or "S_ISGID" in event.args or "04755" in event.args or "02755" in event.args:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.HIGH,
                        category="filesystem",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details="SUID/SGID permission change detected",
                    )
                )
            elif chmod_count > thresholds.MAX_CHMOD_COUNT:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.LOW,
                        category="filesystem",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Chmod count {chmod_count} exceeds threshold",
                    )
                )

        elif event.syscall == "rmdir":
            rmdir_count += 1
            if rmdir_count > thresholds.MAX_RMDIR_COUNT:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.MEDIUM,
                        category="filesystem",
                        syscall="rmdir",
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Directory removal #{rmdir_count}",
                    )
                )

    return profile


def analyze_process(events: list[SyscallEvent], thresholds: Thresholds) -> ProcessProfile:
    """Analyze process-related syscalls."""
    profile = ProcessProfile()
    shell_binaries = ("/bin/sh", "/bin/bash", "/bin/dash", "/bin/zsh", "/usr/bin/sh")

    for event in events:
        if event.syscall in ("fork", "clone", "vfork"):
            profile.child_processes += 1
            if event.syscall == "clone" and "CLONE_THREAD" in event.args:
                profile.threads += 1
            if profile.child_processes > thresholds.MAX_CHILD_PROCESSES:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.HIGH,
                        category="process",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Child process count {profile.child_processes} exceeds threshold {thresholds.MAX_CHILD_PROCESSES}",
                    )
                )

        elif event.syscall in ("execve", "execveat"):
            profile.execve_events.append(event)
            # Check for shell execution
            if any(sh in event.args for sh in shell_binaries):
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.CRITICAL,
                        category="process",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details="Shell execution detected (likely system() or popen() call)",
                    )
                )
            elif len(profile.execve_events) > thresholds.MAX_EXECVE_CALLS:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.HIGH,
                        category="process",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Execve count {len(profile.execve_events)} exceeds threshold {thresholds.MAX_EXECVE_CALLS}",
                    )
                )

        elif event.syscall in ("kill", "tkill", "tgkill"):
            profile.kill_events.append(event)
            if len(profile.kill_events) > thresholds.MAX_KILL_CALLS:
                profile.anomalies.append(
                    Anomaly(
                        severity=Severity.MEDIUM,
                        category="process",
                        syscall=event.syscall,
                        pid=event.pid,
                        timestamp_ms=event.timestamp_ms,
                        args=event.args,
                        details=f"Signal send count {len(profile.kill_events)} exceeds threshold",
                    )
                )

        elif event.syscall == "ptrace":
            profile.ptrace_events.append(event)
            profile.anomalies.append(
                Anomaly(
                    severity=Severity.CRITICAL,
                    category="process",
                    syscall="ptrace",
                    pid=event.pid,
                    timestamp_ms=event.timestamp_ms,
                    args=event.args,
                    details="Process tracing (ptrace) detected - possible injection attempt",
                )
            )

        elif event.syscall in ("setuid", "setgid", "setreuid", "setregid"):
            profile.anomalies.append(
                Anomaly(
                    severity=Severity.CRITICAL,
                    category="process",
                    syscall=event.syscall,
                    pid=event.pid,
                    timestamp_ms=event.timestamp_ms,
                    args=event.args,
                    details="Privilege escalation attempt detected",
                )
            )

    return profile


def check_composite_indicators(
    events: list[SyscallEvent],
    network_profile: NetworkProfile,
    process_profile: ProcessProfile,
) -> list[Anomaly]:
    """Detect dangerous syscall combinations that indicate specific attack patterns."""
    composite_anomalies = []

    syscall_names = {e.syscall for e in events}

    # 1. Reverse shell: socket + dup2 + execve
    if "socket" in syscall_names and "dup2" in syscall_names and "execve" in syscall_names:
        composite_anomalies.append(
            Anomaly(
                severity=Severity.CRITICAL,
                category="composite",
                syscall="socket+dup2+execve",
                pid=0,
                timestamp_ms=0,
                args="",
                details="Reverse shell pattern detected (socket + dup2 + execve)",
            )
        )

    # 2. C2 bot: socket + connect + execve
    if (
        network_profile.connection_attempts
        and process_profile.execve_events
    ):
        composite_anomalies.append(
            Anomaly(
                severity=Severity.CRITICAL,
                category="composite",
                syscall="socket+connect+execve",
                pid=0,
                timestamp_ms=0,
                args="",
                details="C2 bot pattern detected (network connection + subprocess execution)",
            )
        )

    # 3. Fileless execution: memfd_create + execve
    if "memfd_create" in syscall_names and "execve" in syscall_names:
        composite_anomalies.append(
            Anomaly(
                severity=Severity.CRITICAL,
                category="composite",
                syscall="memfd_create+execve",
                pid=0,
                timestamp_ms=0,
                args="",
                details="Fileless execution pattern detected (memfd_create + execve)",
            )
        )

    # 4. Data exfiltration: socket + open(/etc/shadow) + sendto
    has_shadow_access = any(
        "shadow" in e.args or "passwd" in e.args
        for e in events
        if e.syscall in ("open", "openat")
    )
    if network_profile.send_events and has_shadow_access:
        composite_anomalies.append(
            Anomaly(
                severity=Severity.CRITICAL,
                category="composite",
                syscall="socket+open(shadow)+sendto",
                pid=0,
                timestamp_ms=0,
                args="",
                details="Data exfiltration pattern detected (sensitive file access + network send)",
            )
        )

    # 5. Self-modifying network code
    has_proc_maps = any(
        "/proc/self/maps" in e.args for e in events if e.syscall in ("open", "openat")
    )
    has_mprotect_exec = any(
        "PROT_EXEC" in e.args for e in events if e.syscall == "mprotect"
    )
    if has_proc_maps and has_mprotect_exec and network_profile.socket_events:
        composite_anomalies.append(
            Anomaly(
                severity=Severity.HIGH,
                category="composite",
                syscall="open(/proc/self/maps)+mprotect(PROT_EXEC)+socket",
                pid=0,
                timestamp_ms=0,
                args="",
                details="Self-modifying network code pattern detected",
            )
        )

    return composite_anomalies


def calculate_overall_risk(
    timing: TimingProfile,
    network: NetworkProfile,
    filesystem: FilesystemProfile,
    process: ProcessProfile,
    composite: list[Anomaly],
) -> tuple[Severity, RiskDecision, str]:
    """Calculate overall risk and delivery decision."""
    severity_values = {
        "CRITICAL": 4,
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
        "NONE": 0,
    }

    all_anomalies = (
        timing.anomalies
        + network.anomalies
        + filesystem.anomalies
        + process.anomalies
        + composite
    )

    category_scores = {
        "network": max(
            (a.severity for a in network.anomalies + composite if a.category in ("network", "composite")),
            default=Severity.NONE,
        ).value,
        "filesystem": max(
            (a.severity for a in filesystem.anomalies + composite if a.category in ("filesystem", "composite")),
            default=Severity.NONE,
        ).value,
        "process": max(
            (a.severity for a in process.anomalies + composite if a.category in ("process", "composite")),
            default=Severity.NONE,
        ).value,
        "timing": max(
            (a.severity for a in timing.anomalies),
            default=Severity.NONE,
        ).value,
    }

    weights = {"network": 3.0, "filesystem": 2.5, "process": 2.5, "timing": 1.0}

    weighted_score = sum(
        weights[cat] * severity_values.get(score, 0)
        for cat, score in category_scores.items()
    )

    # Determine overall severity
    if weighted_score >= 10:
        overall = Severity.CRITICAL
    elif weighted_score >= 7:
        overall = Severity.HIGH
    elif weighted_score >= 4:
        overall = Severity.MEDIUM
    elif weighted_score >= 1:
        overall = Severity.LOW
    else:
        overall = Severity.NONE

    # Determine decision
    if overall in (Severity.CRITICAL, Severity.HIGH):
        decision = RiskDecision.BLOCK_DELIVERY
    elif overall == Severity.MEDIUM:
        decision = RiskDecision.CONDITIONAL_PASS
    else:
        decision = RiskDecision.PASS

    # Build reason
    critical_reasons = [
        a.details for a in all_anomalies if a.severity == Severity.CRITICAL
    ]
    if critical_reasons:
        reason = "; ".join(critical_reasons[:3])
    else:
        high_reasons = [
            a.details for a in all_anomalies if a.severity == Severity.HIGH
        ]
        reason = "; ".join(high_reasons[:3]) if high_reasons else "No significant anomalies detected"

    return overall, decision, reason


def run_in_sandbox(code_file: str, interpreter: str, output_dir: str) -> tuple[list[SyscallEvent], float, int]:
    """Run code in an instrumented Docker sandbox and return events, duration, and exit code."""
    abs_code = os.path.abspath(code_file)
    abs_output = os.path.abspath(output_dir)
    code_dir = os.path.dirname(abs_code)
    basename = os.path.basename(abs_code)

    # Check for Docker/Podman
    container_runtime = None
    for runtime in ("docker", "podman"):
        if shutil.which(runtime):
            container_runtime = runtime
            break

    if not container_runtime:
        print("ERROR: No container runtime (docker/podman) found. Install one or use --strace-log.", file=sys.stderr)
        sys.exit(1)

    strace_log_dir = os.path.join(abs_output, "strace_logs")
    os.makedirs(strace_log_dir, exist_ok=True)

    # Determine entrypoint based on interpreter
    if interpreter in ("python3", "python"):
        entrypoint_args = [interpreter, f"/code/{basename}"]
    elif interpreter in ("node", "nodejs"):
        entrypoint_args = [interpreter, f"/code/{basename}"]
    else:
        entrypoint_args = [interpreter, f"/code/{basename}"]

    cmd = [
        container_runtime, "run", "--rm",
        "--network", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--read-only",
        "--tmpfs", "/tmp:noexec,nosuid,size=50m",
        "--pids-limit", "100",
        "--memory", "256m",
        "--cpus", "1",
        "-v", f"{code_dir}:/code:ro",
        "-v", f"{strace_log_dir}:/output",
        "--entrypoint", "strace",
        "python:3-slim",
        "-ff",
        "-e", "trace=network,file,process,memory",
        "-o", "/output/strace.log",
    ] + entrypoint_args

    print(f"Running sandbox command: {' '.join(cmd)}", file=sys.stderr)

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("WARNING: Sandbox execution timed out after 120s", file=sys.stderr)
        return [], (time.time() - start_time) * 1000, -1
    end_time = time.time()

    duration_ms = (end_time - start_time) * 1000
    exit_code = result.returncode

    if result.stderr:
        print(f"Sandbox stderr: {result.stderr[:1000]}", file=sys.stderr)

    # Parse strace logs
    events = parse_strace_log_dir(strace_log_dir)
    return events, duration_ms, exit_code


def generate_report(
    code_file: str,
    exit_code: int,
    duration_ms: float,
    timing: TimingProfile,
    network: NetworkProfile,
    filesystem: FilesystemProfile,
    process: ProcessProfile,
    composite: list[Anomaly],
) -> dict:
    """Generate the JSON behavior report."""
    overall_risk, decision, reason = calculate_overall_risk(
        timing, network, filesystem, process, composite
    )

    code_size = os.path.getsize(code_file) if os.path.exists(code_file) else 0

    def anomaly_to_dict(a: Anomaly) -> dict:
        return {
            "severity": a.severity.value,
            "category": a.category,
            "syscall": a.syscall,
            "pid": a.pid,
            "timestamp_ms": a.timestamp_ms,
            "args": a.args,
            "details": a.details,
        }

    return {
        "scan_id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "target": {
            "file": code_file,
            "language": _detect_language(code_file),
            "size_bytes": code_size,
        },
        "sandbox_config": {
            "network": "none",
            "capabilities": "dropped",
            "read_only_root": True,
        },
        "execution": {
            "exit_code": exit_code,
            "duration_ms": round(duration_ms, 2),
            "timed_out": duration_ms > 60000,
        },
        "syscalls": {
            "total_count": len([e for e in []]),  # Will be set by caller
            "by_category": {
                "network": len(network.socket_events) + len(network.connection_attempts) + len(network.send_events),
                "file": len(filesystem.accessed_paths),
                "process": process.child_processes + len(process.execve_events),
                "memory": 0,
                "other": 0,
            },
            "anomalies": [anomaly_to_dict(a) for a in network.anomalies + process.anomalies + composite],
        },
        "filesystem": {
            "accessed_paths": sorted(set(filesystem.accessed_paths)),
            "writes_outside_allowed": filesystem.writes_outside_allowed,
            "sensitive_path_accesses": filesystem.sensitive_path_accesses,
            "files_created": filesystem.files_created,
            "files_deleted": filesystem.files_deleted,
        },
        "network": {
            "connection_attempts": network.connection_attempts,
        },
        "timing": {
            "total_duration_ms": round(timing.total_duration_ms, 2),
            "syscalls_per_second": round(timing.syscalls_per_second, 2),
            "anomalies": [anomaly_to_dict(a) for a in timing.anomalies],
        },
        "risk_assessment": {
            "overall_risk": overall_risk.value,
            "decision": decision.value,
            "reason": reason,
        },
    }


def _detect_language(code_file: str) -> str:
    """Detect programming language from file extension."""
    ext = os.path.splitext(code_file)[1].lower()
    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",
        ".rs": "rust",
        ".c": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".java": "java",
        ".rb": "ruby",
        ".sh": "shell",
        ".php": "php",
    }
    return mapping.get(ext, "unknown")


def main():
    parser = argparse.ArgumentParser(description="Dynamic behavior analyzer for generated code")
    parser.add_argument("--run", action="store_true", help="Run code in sandbox before analysis")
    parser.add_argument("--code", required=True, help="Path to code file to analyze")
    parser.add_argument("--interpreter", default="python3", help="Interpreter to use (python3, node, etc.)")
    parser.add_argument("--strace-log", help="Path to existing strace log (skip sandbox run)")
    parser.add_argument("--write-paths", default="/tmp", help="Comma-separated allowed write paths")
    parser.add_argument("--thresholds-override", help="Path to JSON threshold overrides")
    parser.add_argument("--report-json", required=True, help="Path to write JSON report")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error output")
    args = parser.parse_args()

    thresholds = Thresholds(args.thresholds_override)
    write_paths = [p.strip() for p in args.write_paths.split(",")]

    events = []
    duration_ms = 0.0
    exit_code = 0

    if args.strace_log and not args.run:
        # Analyze existing strace log
        if not args.quiet:
            print(f"Parsing strace log: {args.strace_log}", file=sys.stderr)
        events = parse_strace_log_dir(args.strace_log)
        duration_ms = events[-1].timestamp_ms if events else 0
    elif args.run:
        # Run in sandbox
        if not args.quiet:
            print(f"Running {args.code} in instrumented sandbox...", file=sys.stderr)
        with tempfile.TemporaryDirectory() as tmpdir:
            events, duration_ms, exit_code = run_in_sandbox(
                args.code, args.interpreter, tmpdir
            )
            # Copy strace logs to output if requested
            strace_src = os.path.join(tmpdir, "strace_logs")
            if os.path.exists(strace_src):
                strace_dst = os.path.join(os.path.dirname(args.report_json) or ".", "strace_logs")
                if os.path.exists(strace_dst):
                    shutil.rmtree(strace_dst)
                shutil.copytree(strace_src, strace_dst, ignore_dangling_symlinks=True)
    else:
        print("ERROR: Either --run or --strace-log is required", file=sys.stderr)
        sys.exit(1)

    if not events:
        print("WARNING: No syscalls captured. Code may have failed to start.", file=sys.stderr)

    # Run all analyses
    timing = analyze_timing(events, duration_ms, thresholds)
    network = analyze_network(events, thresholds)
    filesystem = analyze_filesystem(events, write_paths, thresholds)
    process = analyze_process(events, thresholds)
    composite = check_composite_indicators(events, network, process)

    # Generate report
    report = generate_report(
        args.code,
        exit_code,
        duration_ms,
        timing,
        network,
        filesystem,
        process,
        composite,
    )

    # Set actual total count
    report["syscalls"]["total_count"] = len(events)
    report["syscalls"]["by_category"]["memory"] = len(
        [e for e in events if e.syscall in ("mmap", "mmap2", "mprotect", "brk", "munmap")]
    )
    report["syscalls"]["by_category"]["other"] = len(events) - sum(
        report["syscalls"]["by_category"].values()
    )

    # Write report
    report_dir = os.path.dirname(args.report_json)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    with open(args.report_json, "w") as f:
        json.dump(report, f, indent=2, default=str)

    if not args.quiet:
        print(f"Report written to: {args.report_json}", file=sys.stderr)
        print(f"Overall risk: {report['risk_assessment']['overall_risk']}", file=sys.stderr)
        print(f"Decision: {report['risk_assessment']['decision']}", file=sys.stderr)

    # Exit with non-zero if blocked
    if report["risk_assessment"]["decision"] == RiskDecision.BLOCK_DELIVERY.value:
        print(f"BLOCKED: {report['risk_assessment']['reason']}", file=sys.stderr)
        sys.exit(2)
    elif report["risk_assessment"]["decision"] == RiskDecision.CONDITIONAL_PASS.value:
        print(f"WARNING: {report['risk_assessment']['reason']}", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
