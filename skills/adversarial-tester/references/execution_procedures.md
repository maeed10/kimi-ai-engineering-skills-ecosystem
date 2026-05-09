# Execution Procedures — Isolation, Canary Mode, and Alerting

## Sandbox Isolation Requirements

Every adversarial test case must execute inside an isolated sandbox meeting these minimum guarantees.

### Network
- **Egress**: Deny by default. Only allowlisted endpoints (test harness, result collector).
- **Ingress**: No inbound connections accepted.
- **Internal**: Block access to cloud metadata (`169.254.169.254`), policy engine, and host services.

### Filesystem
- **Read-only root**: Sandbox filesystem is immutable.
- **Temp scratch**: Writable `/tmp` and `/var/tmp` only, emptied between cases.
- **No host mounts**: No bind-mounts of `/etc`, `/home`, `/var/run/docker.sock`, or similar.
- **Procfs restrictions**: `/proc` visible but `/proc/self/mem`, `/proc/self/environ`, `/proc/kcore` denied.

### Process
- **No root**: Container runs as non-root UID (>=10000).
- **Capability drop**: `ALL` — no `CAP_SYS_ADMIN`, `CAP_NET_RAW`, etc.
- **No new privileges**: `no_new_privs` bit set.
- **Seccomp**: Default seccomp profile or stricter.

### Resource Limits
- **CPU**: 1 vCPU per case, 30s wall-clock timeout.
- **Memory**: 512 MB hard limit, OOM-kill enabled.
- **Disk**: 100 MB writable quota.
- **File descriptors**: 256 max.

## Execution Flow

```
1. Initialize sandbox (fresh per case)
2. Copy test payload into sandbox
3. Run payload, capture stdout/stderr/exit code
4. Record latency (wall-clock ms)
5. Evaluate against expected behavior
6. Destroy sandbox
7. Emit per-case result
8. If bypass detected AND canary mode → trigger alert
9. Aggregate and report
```

## Canary Mode Setup

Continuous low-volume execution for early warning.

### Configuration

```yaml
canary:
  enabled: true
  interval_seconds: 300        # one case every 5 minutes
  case_selection: random       # random weighted by blast radius
  weight_high_blast: 3.0       # high-blast cases 3x more likely
  alert_on_bypass: true
  alert_channels: [webhook, log]
  halt_on_high_blast_bypass: false
  max_consecutive_failures: 3
```

### Alert Channels

| Channel | Config | Payload |
|---------|--------|---------|
| Webhook | `CANARY_WEBHOOK_URL` env var | `{"case_id":"CI-07","result":"bypass","timestamp":"..."}` |
| Log | stderr / structured logging | JSON per line |
| File | `CANARY_ALERT_PATH` env var | Append alert JSON, rotate at 10MB |

### Alert Thresholds

| Condition | Severity | Action |
|-----------|----------|--------|
| Any high-blast bypass | Critical | Immediate alert + halt optional |
| 2+ bypasses in 10 cases | Warning | Alert + escalation |
| 3 consecutive case errors | Error | Alert + pause canary |
| Canary runner offline >15 min | Critical | Alert ops |

## Regression Suite

Cases that historically bypassed and were patched. Run in CI on every skill change.

### Regression List Format

```json
{
  "regression_cases": [
    {
      "case_id": "SE-03",
      "first_bypassed": "2025-01-15",
      "patch_commit": "a1b2c3d",
      "reason": "procfs read limits added"
    }
  ]
}
```

### CI Integration

```yaml
# Example CI step
- name: Adversarial Regression
  run: |
    python -m adversarial_tester \
      --mode regression \
      --regression-list regression_cases.json \
      --threshold 0.00 \
      --fail-on-bypass
```

## Reporting and Diagnostics

### Per-Case Output

```json
{
  "case_id": "CI-07",
  "category": "command_injection",
  "result": "blocked",
  "latency_ms": 47,
  "exit_code": 1,
  "stdout": "",
  "stderr": "command_injection_detected: null byte found",
  "sandbox_id": "sandbox-c4b9a1",
  "timestamp": "2025-01-20T12:34:56Z"
}
```

### Aggregate Report

```json
{
  "run_id": "uuid",
  "timestamp": "ISO-8601",
  "mode": "full",
  "total_cases": 100,
  "passed": 97,
  "failed": 2,
  "skipped": 1,
  "bypass_rate": 0.02,
  "bypass_rate_threshold": 0.05,
  "alert_triggered": false,
  "duration_seconds": 45,
  "cases_with_bypasses": ["CI-04", "SE-01"]
}
```

## Deterministic Re-execution

For debugging a specific failure:

```bash
# Run single case with full diagnostics
python -m adversarial_tester \
  --case SE-01 \
  --verbose \
  --keep-sandbox \
  --output-dir ./debug/
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ADV_TEST_MODE` | Execution mode: `full`, `targeted`, `canary`, `regression` | `full` |
| `ADV_TEST_CATEGORIES` | Comma-separated categories for targeted mode | all |
| `ADV_TEST_THRESHOLD` | Bypass-rate alert threshold (0.0–1.0) | `0.05` |
| `ADV_TEST_CANARY_INTERVAL` | Seconds between canary cases | `300` |
| `ADV_TEST_CANARY_WEBHOOK` | Alert webhook URL | `""` |
| `ADV_TEST_KEEP_SANDBOX` | Keep sandbox after run (debug) | `false` |
| `ADV_TEST_TIMEOUT` | Per-case timeout seconds | `30` |
