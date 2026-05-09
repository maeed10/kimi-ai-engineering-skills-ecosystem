# Session-to-Deployment Correlation Schema

Defines how production telemetry is tagged and mapped to agent sessions. All fields are required unless marked optional.

---

## 1. Required Tags

Every production metric must carry these three tags. They are the primary join keys to the agent session registry.

| Tag | Key | Format | Example | Source |
|---|---|---|---|---|
| Session ID | `kimi_session_id` | UUID v4, 36 chars | `abc12345-6789-def0-abcd-ef1234567890` | Agent runtime, injected at deploy time |
| Commit Hash | `kimi_commit_hash` | Git short SHA, 7 chars | `def4567` | CI/CD pipeline, from `git rev-parse --short HEAD` |
| Skill Set | `kimi_skill_set` | dot-notation identifier | `api-contract-tester` | Agent configuration, `skill_set` field |

### Tag Invariants
- `kimi_session_id` must match an active entry in the session registry
- `kimi_commit_hash` must be reachable from the deployed branch (not orphaned)
- `kimi_skill_set` must be a known skill in the registry catalog

---

## 2. Tag Injection Points

Tags must be injected at one of these points. The correlation layer resolves them in priority order.

### Priority 1: Direct Metric Labels (preferred)
The telemetry backend itself stores the tags as native labels/dimensions.

**Prometheus example:**
```yaml
# In application code or exporter
http_requests_total{kimi_session_id="abc123", kimi_commit_hash="def4567", kimi_skill_set="api-contract-tester"}
```

**OpenTelemetry example:**
```python
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    "kimi.session.id": "abc123",
    "kimi.commit.hash": "def4567",
    "kimi.skill.set": "api-contract-tester",
})
```

**CloudWatch example:**
```python
dimensions = [
    {"Name": "kimi_session_id", "Value": "abc123"},
    {"Name": "kimi_commit_hash", "Value": "def4567"},
    {"Name": "kimi_skill_set", "Value": "api-contract-tester"},
]
```

### Priority 2: Deployment Metadata Sidecar
When direct labels are not feasible, store tags in deployment metadata and correlate by container/pod ID.

```yaml
# Kubernetes pod annotation (injected by CI/CD)
metadata:
  annotations:
    kimi.io/session-id: "abc123"
    kimi.io/commit-hash: "def4567"
    kimi.io/skill-set: "api-contract-tester"
```

The correlation layer queries the orchestrator API (Kubernetes, ECS, etc.) to resolve pod → annotation → tags.

### Priority 3: Git Commit → Session Lookup
When no runtime tags are available, correlate by commit hash alone.

```
lookup(commit_hash) -> session_registry -> session_id, skill_set
```

This is the least reliable method (confidence 0.6) because a single commit may be deployed by multiple sessions or re-deployed manually.

---

## 3. Correlation Record Schema

The correlation layer produces a `CorrelationRecord` for each metric stream:

```yaml
CorrelationRecord:
  session_id: string        # Resolved from kimi_session_id tag or registry lookup
  commit_hash: string       # Git short SHA of deployed code
  skill_set: string         # Skill set identifier
  deployment_time_ms: int64 # Unix epoch ms when deployment completed
  metric_source: string     # "prometheus" | "opentelemetry" | "cloudwatch" | "gcp" | "azure" | "datadog"
  confidence: float         # 1.0 = direct label, 0.8 = metadata sidecar, 0.6 = git lookup
  correlation_method: string # "direct" | "sidecar" | "git_lookup"
  tags_source: map[string]string  # All original tags/labels from the metric source
```

### Confidence Rules
- `confidence == 1.0`: direct labels present on metric stream — full trust
- `confidence == 0.8`: deployment metadata sidecar resolved — high trust
- `confidence == 0.6`: git commit lookup only — requires manual review flag
- `confidence < 0.6`: correlation failed — metric stream is **orphaned**, skip evaluation

### Orphaned Stream Handling
When `confidence < 0.6`:
1. Emit `orphaned_stream` warning with metric fingerprint (service name + metric name + label hash)
2. Do not evaluate against baselines (no session to baseline against)
3. Accumulate orphaned streams in a 1h bucket
4. If orphaned bucket exceeds 10% of total streams, raise `tagging_coverage` alert to CI/CD pipeline

---

## 4. Multi-Deployment Scenarios

A single session may produce multiple deployments over time. The correlation layer must track the active deployment.

### Deployment Timeline
```
session_id: abc123
commits:
  - hash: def4567  deployed_at: T-3600  status: active
  - hash: abc8901  deployed_at: T-7200  status: replaced
  - hash: 123cdef  deployed_at: T-10800 status: rolled_back
```

### Active Deployment Resolution
Metrics are always correlated to the **most recent** deployment for a session that has `status: active`. If a new deployment supersedes an old one, the old deployment's metrics are archived and no longer evaluated.

### Rollback Detection
When `error-policy` executes a rollback, the session registry updates:
```yaml
deployment:
  commit_hash: "def4567"
  status: "rolled_back"
  rolled_back_at_ms: 1716234000000
  rolled_back_to: "abc8901"   # previous stable commit
```
Future metrics for `def4567` are ignored; correlation switches to `abc8901`.

---

## 5. Schema Validation

Before a correlation record is accepted, validate:
- `session_id` exists in the session registry and is not `blocked`
- `commit_hash` is a valid 7-char hex string
- `skill_set` is in the catalog
- `deployment_time_ms` is in the past (not future-dated)
- `confidence` is one of `1.0`, `0.8`, `0.6`

Validation failures emit `correlation_invalid` and skip evaluation for that stream.
