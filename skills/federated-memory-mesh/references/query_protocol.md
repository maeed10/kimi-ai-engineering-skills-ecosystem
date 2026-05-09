# Mesh Query Protocol

REST/gRPC API specification for cross-instance memory queries in the Federated Memory Mesh.

## Transport

- **REST**: HTTPS with TLS 1.3, port 7443
- **gRPC**: `federated_memory_mesh.v1.MeshService`, same port with `h2`
- **Encoding**: JSON (REST), Protocol Buffers (gRPC)
- **Base Path**: `/mesh/v1`

## Common Headers

| Header | Required | Description |
|---|---|---|
| `X-Mesh-Node-ID` | Yes | SPIFFE ID of the caller |
| `X-Mesh-Auth-Token` | Yes | Short-lived JWT from mesh CA |
| `Content-Type` | Yes | `application/json` or `application/grpc` |
| `X-Mesh-Request-ID` | No | UUID for request tracing |

## REST Endpoints

### GET /mesh/v1/query

Query procedural patterns from remote nodes by domain tag.

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `domain` | string | Yes | Domain tag prefix (e.g. `user-service:auth`) |
| `min_trust` | float | No | Minimum effective trust score (default: 0.5) |
| `max_hops` | int | No | Maximum hop count to accept (default: 3) |
| `limit` | int | No | Maximum patterns to return (default: 10, max: 50) |

**Request Example:**
```bash
curl -H "X-Mesh-Node-ID: spiffe://mesh/user-svc/instance-a" \
     -H "X-Mesh-Auth-Token: eyJhbG..." \
     "https://instance-b.prod:7443/mesh/v1/query?domain=user-service:auth&min_trust=0.6&limit=5"
```

**Response 200:**
```json
{
  "patterns": [
    {
      "pattern_id": "pmt-jwt-validate-003",
      "domain_tag": "user-service:auth:jwt-validation",
      "trust_score": 0.82,
      "provenance": "instance-c.prod.local",
      "hop_count": 1,
      "max_age": 300,
      "content": {
        "algorithm": "RS256",
        "clock_skew_seconds": 30,
        "key_rotation_hours": 24
      }
    }
  ],
  "from_node": "instance-b.prod.local",
  "query_time_ms": 12,
  "ephemeral_session_id": "uuid-v4-here"
}
```

**Response Codes:**

| Code | Meaning |
|---|---|
| 200 | OK |
| 400 | Invalid domain tag or parameter |
| 401 | Missing/invalid auth token or node ID |
| 403 | Domain tag not in allowed context for caller |
| 503 | Node overloaded; `Retry-After` header present |

### POST /mesh/v1/share

Publish a local procedural pattern to the mesh. The receiving node runs IPI defense and trust checks before re-publishing.

**Request Body:**
```json
{
  "pattern": {
    "pattern_id": "pmt-grpc-timeout-001",
    "domain_tag": "order-service:payment:retry-policy",
    "trust_score": 0.95,
    "provenance": "instance-a.prod.local",
    "hop_count": 0,
    "content": {
      "timeout_ms": 5000,
      "retry_count": 2,
      "backoff_strategy": "exponential"
    }
  }
}
```

**Response 201:**
```json
{
  "status": "accepted",
  "effective_trust": 0.95,
  "pattern_id": "pmt-grpc-timeout-001",
  "shared_with_count": 3
}
```

**Response 202 (if conflict detected):**
```json
{
  "status": "conflict",
  "pattern_id": "pmt-grpc-timeout-001",
  "conflict_resolution": {
    "winner": "local",
    "reason": "higher_trust",
    "incoming_stored_as": "conflicted"
  }
}
```

**Response Codes:**

| Code | Meaning |
|---|---|
| 201 | Accepted and re-shared |
| 202 | Conflict detected; see body for resolution result |
| 400 | Invalid schema |
| 401 | Authentication failure |
| 409 | Pattern already exists with identical content (idempotent noop) |

### GET /mesh/v1/health

Node readiness and mesh connectivity status.

**Response 200:**
```json
{
  "node_id": "instance-b.prod.local",
  "status": "healthy",
  "mesh_peers_known": 4,
  "mesh_peers_healthy": 4,
  "patterns_served": 127,
  "version": "federated-memory-mesh/1.0"
}
```

### POST /mesh/v1/resolve

Invoke `memory-guard` conflict resolution for a specific pattern_id.

**Request Body:**
```json
{
  "pattern_id": "pmt-grpc-timeout-001",
  "candidates": [
    {
      "source": "local",
      "trust_score": 0.85,
      "hop_count": 0,
      "content_hash": "sha256:abc..."
    },
    {
      "source": "instance-c.prod.local",
      "trust_score": 0.72,
      "hop_count": 1,
      "content_hash": "sha256:def..."
    }
  ]
}
```

**Response 200:**
```json
{
  "pattern_id": "pmt-grpc-timeout-001",
  "winner": "local",
  "reason": "higher_trust",
  "action": "keep_local"
}
```

### POST /mesh/v1/join

Enroll a new node in the mesh.

**Request Body:**
```json
{
  "node_id": "instance-d.prod.local",
  "spiffe_id": "spiffe://mesh/order-svc/instance-d",
  "bounded_contexts": ["order-service", "inventory-service"],
  "seed_nodes": ["instance-b.prod.local:7443"],
  "listen_addr": "instance-d.prod.local:7443"
}
```

**Response 200:**
```json
{
  "status": "joined",
  "peers_discovered": 3,
  "gossip_delay_seconds": 30
}
```

### POST /mesh/v1/leave

Graceful node departure announcement.

**Request Body:**
```json
{
  "node_id": "instance-d.prod.local",
  "reason": "rolling_restart"
}
```

**Response 204** (No Content)

## gRPC Service

```protobuf
syntax = "proto3";
package federated_memory_mesh.v1;

service MeshService {
  rpc QueryPatterns(QueryRequest) returns (QueryResponse);
  rpc SharePattern(ShareRequest) returns (ShareResponse);
  rpc HealthCheck(HealthRequest) returns (HealthResponse);
  rpc ResolveConflict(ResolveRequest) returns (ResolveResponse);
  rpc JoinMesh(JoinRequest) returns (JoinResponse);
  rpc LeaveMesh(LeaveRequest) returns (LeaveResponse);
}

message QueryRequest {
  string domain = 1;
  float min_trust = 2;   // default: 0.5
  int32 max_hops = 3;     // default: 3
  int32 limit = 4;        // default: 10
}

message Pattern {
  string pattern_id = 1;
  string domain_tag = 2;
  float trust_score = 3;
  string provenance = 4;
  int32 hop_count = 5;
  int32 max_age = 6;      // seconds
  bytes content = 7;      // JSON blob
}

message QueryResponse {
  repeated Pattern patterns = 1;
  string from_node = 2;
  int64 query_time_ms = 3;
  string ephemeral_session_id = 4;
}

message ShareRequest {
  Pattern pattern = 1;
}

message ShareResponse {
  string status = 1;           // "accepted" | "conflict" | "rejected"
  float effective_trust = 2;
  string pattern_id = 3;
  int32 shared_with_count = 4;
}

message HealthRequest {}

message HealthResponse {
  string node_id = 1;
  string status = 2;           // "healthy" | "degraded" | "unhealthy"
  int32 peers_known = 3;
  int32 peers_healthy = 4;
  int64 patterns_served = 5;
}

message ResolveRequest {
  string pattern_id = 1;
  message Candidate {
    string source = 1;
    float trust_score = 2;
    int32 hop_count = 3;
    string content_hash = 4;
  }
  repeated Candidate candidates = 2;
}

message ResolveResponse {
  string pattern_id = 1;
  string winner = 2;           // source string of winner
  string reason = 3;           // "higher_trust" | "local_preference" | "fewer_hops"
  string action = 4;           // "keep_local" | "adopt_remote" | "flag_conflict"
}

message JoinRequest {
  string node_id = 1;
  string spiffe_id = 2;
  repeated string bounded_contexts = 3;
  repeated string seed_nodes = 4;
  string listen_addr = 5;
}

message JoinResponse {
  string status = 1;
  int32 peers_discovered = 2;
  int32 gossip_delay_seconds = 3;
}

message LeaveRequest {
  string node_id = 1;
  string reason = 2;
}

message LeaveResponse {}
```

## Error Schema

All errors use this JSON structure (gRPC maps to appropriate status codes):

```json
{
  "error_code": "TRUST_TOO_LOW",
  "message": "Effective trust 0.42 is below minimum 0.5",
  "request_id": "uuid-v4-here",
  "retryable": false
}
```

| error_code | HTTP | gRPC | retryable |
|---|---|---|---|
| `INVALID_SCHEMA` | 400 | 3 | false |
| `AUTH_FAILED` | 401 | 16 | false |
| `DOMAIN_NOT_ALLOWED` | 403 | 7 | false |
| `PATTERN_NOT_FOUND` | 404 | 5 | false |
| `CONFLICT` | 202 | — | false |
| `RATE_LIMITED` | 429 | 8 | true |
| `OVERLOADED` | 503 | 14 | true |
| `TRUST_TOO_LOW` | 400 | 3 | false |
| `MAX_HOPS_EXCEEDED` | 400 | 3 | false |

## Ephemeral Session Contract

Every successful query returns an `ephemeral_session_id` (UUID v4). This ID:
- Is **not** stored server-side
- Is included in access logs only (not payload logs)
- Serves as a correlation handle for distributed tracing
- Expires implicitly — there is no "end session" endpoint

## Security Requirements

- mTLS with SPIFFE/SPIRE identities is mandatory for all endpoints
- `X-Mesh-Auth-Token` JWT must be signed by the mesh CA and have `sub` matching `X-Mesh-Node-ID`
- Token expiry is enforced; no grace period
- Request bodies are limited to 64KB
- Response bodies are limited to 256KB
