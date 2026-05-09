# Anomaly Thresholds

Default thresholds for dynamic analysis anomaly detection. Override per-project by passing `--thresholds-override` to the analysis script.

---

## Timing Thresholds

| Metric | Default | Strict | Lenient | Unit |
|--------|---------|--------|---------|------|
| Max total execution time | 30 | 10 | 60 | seconds |
| Max wall-clock before SIGKILL | 60 | 20 | 120 | seconds |
| Max syscalls per second | 10,000 | 5,000 | 20,000 | count/sec |
| Max `nanosleep` total duration | 10 | 5 | 30 | seconds |
| Max `nanosleep` call count | 100 | 50 | 200 | count |
| Max `clock_gettime` / `gettimeofday` per second | 1,000 | 500 | 2,000 | count/sec |
| Max `alarm` / `setitimer` calls | 5 | 2 | 10 | count |
| Max timer creation (`timer_create`) | 2 | 1 | 5 | count |
| Min execution time (stuck detection) | 0.1 | 0.1 | 0.1 | seconds |
| Max consecutive identical syscalls | 1,000 | 500 | 2,000 | count |

### Timing Anomaly Classification

| Severity | Condition |
|----------|-----------|
| CRITICAL | Execution time > max wall-clock (killed) |
| HIGH | Execution time > max total OR syscalls/sec > threshold |
| MEDIUM | Excessive sleep OR excessive clock queries |
| LOW | Slightly elevated syscall rate |

## Network Thresholds

| Metric | Default | Strict | Lenient | Unit |
|--------|---------|--------|---------|------|
| Max `socket(AF_INET)` attempts | 0 | 0 | 1 | count |
| Max `socket(AF_INET6)` attempts | 0 | 0 | 1 | count |
| Max `socket(AF_NETLINK)` attempts | 0 | 0 | 0 | count |
| Max `connect` attempts | 0 | 0 | 0 | count |
| Max `bind` attempts | 0 | 0 | 0 | count |
| Max `sendto`/`sendmsg` payloads | 0 | 0 | 0 | count |
| Max total network-related syscalls | 5 | 0 | 10 | count |
| Max DNS resolution attempts | 0 | 0 | 0 | count |

### Network Anomaly Classification

| Severity | Condition |
|----------|-----------|
| CRITICAL | Successful `connect` to external address |
| HIGH | Any `connect` attempt (even if blocked) |
| HIGH | `socket(AF_INET)` + `sendto` sequence |
| MEDIUM | `socket(AF_INET)` only (attempted but no connect) |
| LOW | `socket(AF_UNIX)` only (normal IPC) |

## Filesystem Thresholds

| Metric | Default | Strict | Lenient | Unit |
|--------|---------|--------|---------|------|
| Max write paths accessed outside declared | 0 | 0 | 2 | count |
| Max files created | 50 | 20 | 100 | count |
| Max files deleted | 10 | 5 | 20 | count |
| Max file size written (total) | 100 | 50 | 200 | MB |
| Max sensitive path reads | 0 | 0 | 1 | count |
| Max sensitive path writes | 0 | 0 | 0 | count |
| Max symlinks created | 0 | 0 | 2 | count |
| Max hardlinks created | 0 | 0 | 0 | count |
| Max permission changes (`chmod`) | 0 | 0 | 2 | count |
| Max directory removals (`rmdir`) | 0 | 0 | 2 | count |
| Max recursive directory operations | 0 | 0 | 1 | count |
| Max temp files in `/tmp` | 20 | 10 | 40 | count |

### Sensitive Paths (Regex Patterns)

```
/etc/shadow
/etc/shadow-
/etc/gshadow
/etc/gshadow-
/etc/master.passwd
/etc/security/passwd
/etc/sudoers
/etc/sudoers.d/.*
/etc/ssh/sshd_config
/etc/ssh/ssh_host_.*_key
/root/
/home/.*/\.ssh/.*
/home/.*/\.gnupg/.*
/home/.*/\.aws/.*
/home/.*/\.azure/.*
/proc/1/ .*
/proc/kcore
/proc/kallsyms
/sys/kernel/debug/.*
/dev/mem
/dev/kmem
/dev/port
/boot/.*
```

### Filesystem Anomaly Classification

| Severity | Condition |
|----------|-----------|
| CRITICAL | Write to `/etc/shadow` or equivalent |
| HIGH | Write to any sensitive path |
| HIGH | `chmod` with SUID/SGID on any file |
| MEDIUM | Read from sensitive path |
| MEDIUM | Write outside declared `write_paths` |
| LOW | Excessive temp file creation |
| LOW | Symlink creation (context-dependent) |

## Process Thresholds

| Metric | Default | Strict | Lenient | Unit |
|--------|---------|--------|---------|------|
| Max child processes (`fork`/`clone`) | 5 | 2 | 10 | count |
| Max threads | 10 | 4 | 20 | count |
| Max `execve` calls | 0 | 0 | 1 | count (unless allowlisted) |
| Max signal sends (`kill`) | 0 | 0 | 2 | count |
| Max `ptrace` calls | 0 | 0 | 0 | count |

### Process Anomaly Classification

| Severity | Condition |
|----------|-----------|
| CRITICAL | `ptrace` of any process |
| CRITICAL | `execve` of `/bin/sh` or shell (indicates `system()` call) |
| HIGH | `execve` of non-allowlisted binary |
| HIGH | Excessive child processes (> threshold) |
| MEDIUM | `kill` signal to external process |
| LOW | Thread count slightly above threshold |

## Composite Score Weights

Overall risk score = weighted sum of category scores:

| Category | Weight |
|----------|--------|
| Network anomalies | 3.0x |
| Filesystem anomalies | 2.5x |
| Process anomalies | 2.5x |
| Timing anomalies | 1.0x |

### Overall Risk Calculation

```python
def calculate_risk(category_scores):
    """
    category_scores: dict of {category: max_severity_value}
    severity_values = {'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'NONE': 0}
    """
    weights = {
        'network': 3.0,
        'filesystem': 2.5,
        'process': 2.5,
        'timing': 1.0,
    }
    severity_values = {
        'CRITICAL': 4,
        'HIGH': 3,
        'MEDIUM': 2,
        'LOW': 1,
        'NONE': 0,
    }
    weighted_score = sum(
        weights[cat] * severity_values.get(score, 0)
        for cat, score in category_scores.items()
    )

    if weighted_score >= 10:
        return 'CRITICAL'
    elif weighted_score >= 7:
        return 'HIGH'
    elif weighted_score >= 4:
        return 'MEDIUM'
    elif weighted_score >= 1:
        return 'LOW'
    else:
        return 'NONE'
```

## Threshold Override Format

Pass a JSON file to `--thresholds-override`:

```json
{
  "timing": {
    "max_execution_time_seconds": 45,
    "max_wall_clock_seconds": 90
  },
  "network": {
    "max_inet_socket_attempts": 1,
    "max_total_network_syscalls": 10
  },
  "filesystem": {
    "max_files_created": 100,
    "max_write_paths_outside_declared": 1
  },
  "process": {
    "max_child_processes": 10,
    "max_threads": 20
  }
}
```
