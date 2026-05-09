# Telemetry Adapter Reference

Integration patterns for ingesting production metrics into the `MetricEnvelope` schema. Implement one adapter per telemetry backend.

---

## 1. Prometheus

### Remote-Read API
```python
import requests

def prometheus_remote_read(endpoint: str, query: str, start_s: int, end_s: int,
                          step: str = "30s") -> list[MetricEnvelope]:
    """Execute PromQL query_range and normalize to MetricEnvelope."""
    resp = requests.get(f"{endpoint}/api/v1/query_range", params={
        "query": query,
        "start": start_s,
        "end": end_s,
        "step": step
    }, timeout=30)
    resp.raise_for_status()
    return _prom_to_envelopes(resp.json())
```

### Required Queries
| Metric | PromQL |
|---|---|
| p99 latency | `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))` |
| Error rate | `rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])` |
| Throughput | `rate(http_requests_total[5m])` |

### Tag Extraction
Prometheus labels map directly to envelope tags. Required label names:
- `kimi_session_id` → `tags.kimi_session_id`
- `kimi_commit_hash` → `tags.kimi_commit_hash`
- `kimi_skill_set` → `tags.kimi_skill_set`

If labels are missing, fall back to deployment metadata sidecar or git-commit lookup before flagging.

### Recording Rules
For high-cardinality services, define recording rules to pre-aggregate:
```yaml
groups:
  - name: production_drift_bridge
    rules:
      - record: job:kimi_error_rate_5m
        expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])
      - record: job:kimi_latency_p99_5m
        expr: histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
```

---

## 2. OpenTelemetry

### OTLP/gRPC Receiver
```python
from opentelemetry.proto.collector.metrics.v1 import metrics_service_pb2_grpc

def otlp_grpc_subscribe(endpoint: str, resource_filter: dict) -> Iterator[MetricEnvelope]:
    """Subscribe to OTLP metrics stream, filter by resource attributes."""
    channel = grpc.insecure_channel(endpoint)
    stub = metrics_service_pb2_grpc.MetricsServiceStub(channel)
    for response in stub.Export(stream_requests(resource_filter)):
        yield _otlp_to_envelopes(response)
```

### Required Resource Attributes
| Attribute | Key | Example |
|---|---|---|
| Session ID | `kimi.session.id` | `abc123` |
| Commit hash | `kimi.commit.hash` | `def4567` |
| Skill set | `kimi.skill.set` | `api-contract-tester` |
| Service name | `service.name` | `payment-gateway` |

### Span Metrics Bridge
If using span-to-metrics pipelines, ensure the span processor adds Kimi attributes to the resulting metric resource. Example OpenTelemetry Collector config fragment:
```yaml
processors:
  resource/kimi:
    attributes:
      - key: kimi.session.id
        from_attribute: session.id
        action: upsert
      - key: kimi.commit.hash
        from_attribute: commit.hash
        action: upsert
```

---

## 3. Cloud-Native APIs

### AWS CloudWatch
```python
import boto3

def cloudwatch_get_metric(namespace: str, metric_name: str, dimensions: list,
                         start_time: datetime, end_time: datetime, period: int = 60):
    client = boto3.client("cloudwatch")
    return client.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start_time,
        EndTime=end_time,
        Period=period,
        Statistics=["Average", "p99"]
    )
```

Tag mapping: CloudWatch dimensions → envelope tags. Use `kimi_session_id`, `kimi_commit_hash`, `kimi_skill_set` as dimension names, or embed as custom metric metadata via `PutMetricData` `StorageResolution` fields if dimension limits are reached.

### GCP Monitoring (Google Cloud)
```python
from google.cloud import monitoring_v3

def gcp_read_time_series(project_id: str, filter_str: str, interval):
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project_id}"
    return client.list_time_series(
        request={"name": project_name, "filter": filter_str, "interval": interval}
    )
```

Map `metric.labels` to envelope tags. Use MonitoredResource labels for service identity.

### Azure Monitor
```python
from azure.monitor.query import MetricsQueryClient

def azure_read_metrics(resource_uri: str, metric_names: list, timespan: tuple):
    client = MetricsQueryClient(credential)
    return client.query_resource(resource_uri, metric_names, timespan=timespan)
```

Map `metric.namespace` tags to envelope tags. Use Application Insights custom dimensions for Kimi-specific attributes.

### Datadog
```python
from datadog_api_client.v1.api.metrics_api import MetricsApi

def datadog_query(query: str, from_s: int, to_s: int):
    api = MetricsApi(api_client)
    return api.query(from_time=from_s, to_time=to_s, query=query)
```

Use Datadog tags (`kimi_session_id:abc123`) for correlation. Query format: `avg:error_rate{kimi_session_id:abc123}`.

---

## 4. Adapter Implementation Checklist

When adding a new telemetry backend:
- [ ] Implement `query(start, end) -> list[MetricEnvelope]` interface
- [ ] Map backend-native identifiers to `kimi_session_id`, `kimi_commit_hash`, `kimi_skill_set`
- [ ] Handle missing tags with fallback to deployment metadata or git lookup
- [ ] Support at minimum `latency_p99`, `error_rate`, `requests_per_sec` metrics
- [ ] Return normalized `MetricEnvelope` with `timestamp_ms`, `tags`, `value`, `metric_name`, `unit`
- [ ] Add connection timeout (default 30s) and retry (3x exponential backoff)
- [ ] Validate that all required envelope fields are populated before returning
