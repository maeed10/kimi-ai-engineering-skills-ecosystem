---
name: dynamic-analyzer
description: Dynamic behavioral analysis skill that runs generated code in instrumented sandboxes with strace, network capture, filesystem monitoring, and timing anomaly detection. Use after EXECUTE phase, when security-auditor flags suspicious patterns, or when code from untrusted sources needs runtime validation. Feeds findings to drift-monitor. Blocks delivery on unexpected behavior.
---

# Dynamic Analyzer

## Overview

Run generated or untrusted code in a tightly-instrumented sandbox to detect hidden backdoors, unexpected network connections, anomalous filesystem access, and timing anomalies. This skill is the runtime validation gate between EXECUTE and DELIVER.

## Workflow Decision Tree

```
Code ready for delivery?
├── Source is trusted AND has no network/fs/subprocess ops?
│   └── Skip dynamic analysis (still log decision)
├── security-auditor flagged suspicious patterns?
│   └── Run full analysis → classify anomalies → feed to drift-monitor
├── Code contains network, filesystem, or subprocess operations?
│   └── Run full analysis → classify anomalies
└── Code from untrusted/external source?
    └── Run full analysis with elevated scrutiny → classify anomalies
```

## Pre-execution Checklist

Before running dynamic analysis, confirm:

1. **Sandbox environment** is available: Docker/Podman with `--network none` capability
2. **strace** is installed in the sandbox or host
3. **Target code** has been written to a temporary file accessible by the sandbox
4. **Declared write_paths** are documented (paths the code is expected to access)
5. **Expected syscalls** are known (load from `references/syscall_watchlist.md`)

## Phase 1: Instrumented Execution

### 1.1 Launch Sandbox with strace

Run the target code inside a sandbox with full syscall tracing:

```bash
docker run --rm \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --read-only \
  --tmpfs /tmp:noexec,nosuid,size=50m \
  -v "$(pwd)/code:/code:ro" \
  -v "$(pwd)/output:/output" \
  --entrypoint strace \
  sandbox-image \
  -ff -e trace=network,file,process \
  -o /output/strace.log \
  python /code/target.py
```

Key flags:
- `--network none`: blocks all network access at container level
- `--cap-drop ALL`: removes all Linux capabilities
- `--security-opt no-new-privileges:true`: prevents privilege escalation
- `--read-only`: makes root filesystem read-only
- `strace -ff`: follows forks/clones, separate log per PID
- `strace -e trace=network,file,process`: traces relevant syscall classes

### 1.2 Filesystem Monitoring

Mount a FUSE overlay or use `fanotify`/`inotify` to track filesystem events:

```bash
# Using inotifywatch for simple monitoring
inotifywatch -e create,delete,modify,attrib,move -t 60 -r /output/workspace/
```

### 1.3 Network Capture (even with --network none)

Capture any socket creation attempts at the syscall level:

```bash
# strace already captures socket/connect syscalls
# Additionally log any network namespace events
docker run ... \
  --network none \
  --pids-limit 100 \
  ...
```

## Phase 2: Syscall Analysis

### 2.1 Parse strace Output

Run the analysis script:

```bash
python scripts/analyze_behavior.py \
  --strace-log /output/strace.log \
  --code-file /code/target.py \
  --expected-syscalls references/syscall_watchlist.md \
  --thresholds references/anomaly_thresholds.md \
  --write-paths /tmp,/output \
  --report-json /output/behavior_report.json
```

### 2.2 Classification Rules

For each detected syscall, classify as:

| Class | Action | Example |
|-------|--------|---------|
| `EXPECTED` | Log only | `open` on declared `write_paths` |
| `SUSPICIOUS` | Flag in report | `socket` with `AF_INET` even if blocked |
| `MALICIOUS` | Block delivery, alert | `execve` of unexpected binary |
| `ANOMALOUS` | Feed to drift-monitor | Unusual syscall sequence patterns |

### 2.3 Critical Syscall Watchlist

Load `references/syscall_watchlist.md` for the full list. Key syscalls to flag:

- **`socket` / `socketpair`**: Network capability attempts
- **`connect` / `sendto` / `sendmsg`**: Outbound connection attempts
- **`execve` / `execveat`**: Subprocess spawning (validate against allowlist)
- **`open` / `openat` / `creat`**: File access outside declared paths
- **`unlink` / `unlinkat` / `rmdir`**: Destructive filesystem operations
- **`chmod` / `fchmod` / `chmodat`**: Permission changes
- **`ptrace`**: Process tracing (strong indicator of injection)
- **`setuid` / `setgid` / `setreuid`**: Privilege escalation attempts
- **`mount` / `umount`**: Filesystem mounting (usually blocked by seccomp)
- **`kill` / `tkill` / `tgkill`**: Signal sending to other processes

## Phase 3: Anomaly Classification

### 3.1 Timing Anomalies

| Check | Threshold | Action |
|-------|-----------|--------|
| Total execution time | >30s default (see thresholds) | Flag as potential infinite loop or stalling |
| Syscalls per second | >10,000/sec | Flag as potential busy-loop or scanning |
| Sleep/timer syscalls | Excessive `nanosleep`/`alarm` | Flag as potential stalling behavior |
| Clock access patterns | Repeated `clock_gettime` in tight loop | Flag as timing side-channel |

### 3.2 Network Anomalies

| Check | Threshold | Action |
|-------|-----------|--------|
| Any `socket(AF_INET/AF_INET6, ...)` | 1+ occurrences | Log as `SUSPICIOUS` even if blocked |
| `connect` to any address | 1+ occurrences | Log as `MALICIOUS` attempt |
| DNS resolution syscalls | Any `gethostbyname` etc. | Log and inspect payload |
| Socket option manipulation | `setsockopt` with unusual flags | Flag for review |

### 3.3 Filesystem Anomalies

| Check | Threshold | Action |
|-------|-----------|--------|
| Access outside `write_paths` | Any `open` on undeclared path | Flag as `SUSPICIOUS` |
| Write to sensitive paths | Any write to `/etc`, `/bin`, `/sbin` | Flag as `MALICIOUS` |
| Symlink/hardlink creation | `symlink`/`link` syscalls | Flag as `SUSPICIOUS` |
| Temporary file creation | Excessive files in `/tmp` | Flag if >threshold |
| File deletion patterns | `unlink` on files not created by process | Flag as `SUSPICIOUS` |

## Phase 4: Reporting

### 4.1 Behavior Report Schema

```json
{
  "scan_id": "uuid-v4",
  "timestamp": "ISO-8601",
  "target": {
    "file": "/code/target.py",
    "language": "python",
    "size_bytes": 1234
  },
  "sandbox_config": {
    "network": "none",
    "capabilities": "dropped",
    "read_only_root": true
  },
  "execution": {
    "exit_code": 0,
    "duration_ms": 1250,
    "timed_out": false
  },
  "syscalls": {
    "total_count": 4521,
    "by_category": {
      "network": 2,
      "file": 45,
      "process": 0,
      "memory": 120,
      "other": 4354
    },
    "anomalies": [
      {
        "severity": "SUSPICIOUS",
        "syscall": "socket",
        "pid": 42,
        "timestamp_ms": 340,
        "args": "AF_INET, SOCK_STREAM, 0",
        "details": "Network socket creation attempted despite --network none"
      }
    ]
  },
  "filesystem": {
    "accessed_paths": ["/tmp/work.dat"],
    "writes_outside_allowed": [],
    "sensitive_path_accesses": [],
    "files_created": ["/tmp/work.dat"],
    "files_deleted": []
  },
  "network": {
    "connection_attempts": [
      {
        "syscall": "connect",
        "address": "192.168.1.100:4444",
        "result": "EPERM (Operation not permitted)"
      }
    ]
  },
  "timing": {
    "total_duration_ms": 1250,
    "syscalls_per_second": 3616,
    "anomalies": []
  },
  "risk_assessment": {
    "overall_risk": "HIGH",
    "decision": "BLOCK_DELIVERY",
    "reason": "Network connection attempt to external IP detected"
  }
}
```

### 4.2 Decision Matrix

| Overall Risk | Decision | Next Action |
|--------------|----------|-------------|
| `CRITICAL` | `BLOCK_DELIVERY` | Immediate alert, feed to drift-monitor, escalate |
| `HIGH` | `BLOCK_DELIVERY` | Detailed report to drift-monitor, require manual review |
| `MEDIUM` | `CONDITIONAL_PASS` | Flag for drift-monitor, allow delivery with warnings |
| `LOW` | `PASS` | Log summary, proceed to DELIVER |
| `NONE` | `PASS` | Minimal log entry |

## Phase 5: Integration with drift-monitor

Feed the behavior report to drift-monitor for anomaly scoring:

```bash
# After generating report, submit to drift-monitor
curl -X POST http://drift-monitor:8080/api/v1/anomaly-score \
  -H "Content-Type: application/json" \
  -d @/output/behavior_report.json
```

The anomaly score from drift-monitor contributes to the overall code risk profile. If drift-monitor returns a score above the configured threshold, delivery is blocked regardless of local risk assessment.

## Quick Reference: One-Liner Analysis

```bash
# Full pipeline: sandbox + strace + analysis
python scripts/analyze_behavior.py \
  --run \
  --code target.py \
  --interpreter python3 \
  --output behavior_report.json
```

## Resources

### references/syscall_watchlist.md
Full syscall watchlist with expected vs. unexpected patterns for common languages. Load before analysis to configure detection rules.

### references/anomaly_thresholds.md
Timing, network, and filesystem anomaly thresholds. Customize per-project or per-security policy.

### scripts/analyze_behavior.py
Executable Python script that orchestrates sandbox execution, strace parsing, anomaly detection, and JSON report generation.
