# Trace Integration Patterns

Protocol-specific query patterns and authentication for OpenTelemetry, Jaeger, and Zipkin.

## OpenTelemetry (OTLP) — Preferred

### OTLP/gRPC Query (via OpenTelemetry Collector or Tempo)

```python
import grpc
from opentelemetry.proto.collector.trace.v1.trace_service_pb2_grpc import TraceServiceStub
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

def query_otlp(endpoint, headers=None, lookback_hours=24):
    """
    Query traces from OTLP-compatible backend.
    Requires the backend to support reverse query (e.g., Grafana Tempo, Jaeger with OTLP).
    """
    channel = grpc.insecure_channel(endpoint)  # use grpc.secure_channel for TLS
    stub = TraceServiceStub(channel)
    # Most OTLP collectors do not support querying; use Tempo/Jaeger query APIs instead
    # See Tempo example below
```

### Grafana Tempo Query API

```bash
# Tempo search v2 — service graph
curl "http://TEMPO_HOST:3200/api/search?q={service.name=\"payment-service\"}" \
  --data-urlencode "start=$(date -d '24 hours ago' +%s)" \
  --data-urlencode "end=$(date +%s)" \
  --data-urlencode "limit=1000"

# Tempo service graph (pre-aggregated edges)
curl "http://TEMPO_HOST:3200/api/metrics/name/graph?start=$(date -d '24h ago' +%s)"
```

### Authentication

```yaml
# Tempo / OTLP collectors
headers:
  Authorization: "Bearer ${TEMPO_API_TOKEN}"   # if API token auth
  X-Scope-OrgID: "<tenant_id>"                  # multi-tenant Tempo

# TLS/mTLS
config:
  tls:
    cert_file: /path/to/cert.pem
    key_file: /path/to/key.pem
    ca_file: /path/to/ca.pem
```

---

## Jaeger Query API v3

### Service Discovery

```bash
# List services
curl "http://JAEGER_QUERY:16686/api/services"

# List operations for a service
curl "http://JAEGER_QUERY:16686/api/services/payment-service/operations"
```

### Trace Search

```bash
# Search traces between two services
curl "http://JAEGER_QUERY:16686/api/traces?service=order-service" \
  --data-urlencode "tags={\"http.url\":\"/api/v2/payments\"}" \
  --data-urlencode "start=$(($(date +%s) - 86400))000000" \
  --data-urlencode "limit=1000"
```

### Dependencies Endpoint (Pre-aggregated Graph)

```bash
# Get service dependency graph — USE THIS FIRST
curl "http://JAEGER_QUERY:16686/api/dependencies?endTs=$(date +%s)000&lookback=86400000"
```

**Response format:**
```json
{
  "data": [
    {"parent": "order-service", "child": "payment-service", "callCount": 15420},
    {"parent": "order-service", "child": "inventory-service", "callCount": 8320}
  ]
}
```

This is the **fastest path** to a runtime graph. If available, skip per-trace processing and use this endpoint directly.

### Authentication

```yaml
# Jaeger supports Bearer tokens via --query.bearer-token-propagation=true
headers:
  Authorization: "Bearer ${JAEGER_TOKEN}"

# Basic auth
headers:
  Authorization: "Basic $(echo -n 'user:pass' | base64)"
```

---

## Zipkin API v2

### Dependencies Endpoint

```bash
# Get dependency graph
curl "http://ZIPKIN:9411/api/v2/dependencies?endTs=$(date +%s)000&lookback=86400000"
```

**Response format:**
```json
[
  {"parent": "order-service", "child": "payment-service", "callCount": 15420}
]
```

### Trace Search (Fallback)

```bash
# Search traces by service name
curl "http://ZIPKIN:9411/api/v2/traces?serviceName=order-service&lookback=86400000&limit=1000"
```

### Authentication

```yaml
headers:
  Authorization: "Bearer ${ZIPKIN_TOKEN}"   # if enabled
# Zipkin typically runs without auth internally; rely on network isolation
```

---

## Span Attribute Extraction Rules

Map span attributes to graph edge properties:

| Attribute Source | Key(s) | Maps To |
|-----------------|--------|---------|
| Peer service | `peer.service`, `net.peer.name` | `dst` service name |
| HTTP | `http.url`, `http.host`, `server.address` | `dst` host / service |
| Database | `db.system`, `db.name`, `db.connection_string` | `dst` database system |
| Messaging | `messaging.system`, `messaging.destination` | `dst` queue/topic |
| RPC | `rpc.service`, `rpc.method` | `dst` RPC service |
| gRPC | `rpc.system=grpc`, `rpc.service` | `dst` gRPC service |

### Destination Resolution Priority

```python
DEST_ATTR_PRIORITY = [
    "peer.service",
    "rpc.service",
    "server.address",
    "http.host",
    "net.peer.name",
    "db.system",
    "messaging.system",
]

def resolve_destination(span):
    for attr in DEST_ATTR_PRIORITY:
        if attr in span.attributes:
            return span.attributes[attr]
    return None  # orphan span, cannot map
```

---

## Local Trace Export (Fallback)

When no live backend is available, read from local files:

```bash
# OpenTelemetry collector file exporter
# Config snippet:
# exporters:
#   file:
#     path: ./traces.json
#     rotation:
#       max_megabytes: 10
#       max_days: 1

def load_local_traces(path):
    """Load newline-delimited JSON trace exports."""
    for line in open(path):
        yield json.loads(line)  # each line is a ResourceSpans protobuf JSON
```
