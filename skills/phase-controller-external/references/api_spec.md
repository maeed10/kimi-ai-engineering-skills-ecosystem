# Phase Controller External — API Specification

## Overview

The phase-controller exposes a minimal, stateless-over-HTTP API. All endpoints return JSON. Errors follow RFC 7807 `application/problem+json` where applicable.

**Base URL:** configurable; e.g. `http://phase-controller:8080`

**Content-Type:** `application/json` for all request and response bodies.

---

## Endpoints

### 1. `GET /health`

Service health check and public key retrieval.

#### Request

```http
GET /health HTTP/1.1
```

#### Response 200 OK

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "public_key": "ed25519:7c3d...9a2f",
  "database": "connected",
  "merkle_root": "sha256:a1b2...c3d4"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"healthy"` or `"degraded"` |
| `version` | string | Semver of the running service |
| `public_key` | string | Ed25519 public key (hex), prefix `ed25519:` |
| `database` | string | `"connected"`, `"reconnecting"`, or `"unavailable"` |
| `merkle_root` | string | Current Merkle root of `transition_log` (`sha256:` prefix) |

#### Response 503 Service Unavailable

Returned when DB is unreachable or Merkle tree is in an inconsistent state.

```json
{
  "status": "unhealthy",
  "database": "unavailable",
  "merkle_root": null
}
```

---

### 2. `GET /phase`

Query the current phase for a mission.

#### Request

```http
GET /phase?mission_id=mission-42 HTTP/1.1
```

| Query Param | Type | Required | Description |
|-------------|------|----------|-------------|
| `mission_id` | string | yes | Mission identifier |

#### Response 200 OK

```json
{
  "mission_id": "mission-42",
  "phase": "EXECUTE",
  "since": "2026-01-10T14:22:00Z",
  "transition_count": 2,
  "last_merkle_root": "sha256:e3b0...4429"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `mission_id` | string | Echo of request param |
| `phase` | string | One of `INIT`, `PLAN`, `EXECUTE`, `VERIFY`, `REPORT`, `ARCHIVE`, `CLOSED` |
| `since` | string (ISO 8601) | Timestamp when current phase was entered |
| `transition_count` | integer | Number of completed transitions for this mission |
| `last_merkle_root` | string | `merkle_root` of the most recent transition record |

#### Response 404 Not Found

Mission has never been seen. Phase is implicitly `INIT` with `transition_count: 0`.

```json
{
  "type": "https://phase-controller.example/errors/mission-not-found",
  "title": "Mission Not Found",
  "status": 404,
  "detail": "No transitions recorded for mission_id 'mission-unknown'.",
  "mission_id": "mission-unknown"
}
```

---

### 3. `POST /transition`

Propose a phase transition. This is the only mutating endpoint.

#### Request

```http
POST /transition HTTP/1.1
Content-Type: application/json

{
  "mission_id": "mission-42",
  "to_phase": "EXECUTE",
  "artifact": { ... },
  "artifact_hash": "sha256:abc123..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `mission_id` | string | yes | Mission identifier |
| `to_phase` | string | yes | Target phase; must be the unique next phase in graph |
| `artifact` | JSON object | yes | Completion artifact for the current phase |
| `artifact_hash` | string | yes | SHA-256 hex of canonical `artifact` JSON (whitespace-sorted keys) |

#### Response 200 OK (Success — new transition)

```json
{
  "mission_id": "mission-42",
  "from_phase": "PLAN",
  "to_phase": "EXECUTE",
  "artifact_hash": "sha256:abc123...",
  "proposed_at": "2026-01-15T09:30:00Z",
  "signature": "base64:SGVs...bG8=",
  "signer_key": "ed25519:7c3d...9a2f",
  "merkle_root": "sha256:def456...",
  "prev_root": "sha256:000111...",
  "receipt_id": 7
}
```

| Field | Type | Description |
|-------|------|-------------|
| `mission_id` | string | Echo |
| `from_phase` | string | Phase before transition |
| `to_phase` | string | Phase after transition |
| `artifact_hash` | string | Echo of request hash |
| `proposed_at` | string (ISO 8601) | Server-side timestamp of acceptance |
| `signature` | string | Base64-encoded Ed25519 signature; prefix `base64:` |
| `signer_key` | string | Public key that can verify signature |
| `merkle_root` | string | New Merkle root after appending this record |
| `prev_root` | string | Merkle root before this record |
| `receipt_id` | integer | Primary key of `transition_log` row; use for `/audit` queries |

#### Response 200 OK (Idempotent — duplicate)

If `mission_id` + `artifact_hash` + `to_phase` already exists, returns the existing receipt without mutation. `receipt_id` points to original record.

#### Response 409 Conflict (Transition Not Allowed)

```json
{
  "type": "https://phase-controller.example/errors/transition-not-allowed",
  "title": "Transition Not Allowed",
  "status": 409,
  "detail": "Cannot transition from PLAN to VERIFY. Allowed next phase: EXECUTE.",
  "mission_id": "mission-42",
  "current_phase": "PLAN",
  "requested_phase": "VERIFY",
  "allowed_phases": ["EXECUTE"]
}
```

#### Response 422 Unprocessable Entity (Artifact Validation Failed)

```json
{
  "type": "https://phase-controller.example/errors/artifact-validation-failed",
  "title": "Artifact Validation Failed",
  "status": 422,
  "detail": "Artifact does not match schema 'plan_spec/v1'.",
  "mission_id": "mission-42",
  "schema_id": "plan_spec/v1",
  "errors": [
    {
      "path": ".tasks[3].owner",
      "message": "must be a valid email address"
    }
  ]
}
```

#### Response 400 Bad Request

Malformed JSON, missing required fields, or `artifact_hash` does not match computed hash of `artifact`.

```json
{
  "type": "https://phase-controller.example/errors/hash-mismatch",
  "title": "Artifact Hash Mismatch",
  "status": 400,
  "detail": "Provided artifact_hash does not match computed SHA-256 of artifact body.",
  "provided_hash": "sha256:abc123...",
  "computed_hash": "sha256:xyz789..."
}
```

#### Response 503 Service Unavailable

Database or signing backend unreachable. Orchestrator should retry with backoff.

---

### 4. `GET /audit`

Retrieve paginated, signed transition records for a mission.

#### Request

```http
GET /audit?mission_id=mission-42&cursor=0&limit=50 HTTP/1.1
```

| Query Param | Type | Required | Default | Description |
|-------------|------|----------|---------|-------------|
| `mission_id` | string | yes | — | Mission identifier |
| `cursor` | integer | no | 0 | Offset in transition sequence (0 = first transition) |
| `limit` | integer | no | 50 | Max records to return; max allowed 100 |

#### Response 200 OK

```json
{
  "mission_id": "mission-42",
  "cursor": 0,
  "limit": 50,
  "total": 3,
  "records": [
    {
      "receipt_id": 1,
      "from_phase": "INIT",
      "to_phase": "PLAN",
      "artifact_hash": "sha256:aaa...",
      "proposed_at": "2026-01-08T10:00:00Z",
      "signature": "base64:SGVs...bG8=",
      "signer_key": "ed25519:7c3d...9a2f",
      "merkle_root": "sha256:bbb...",
      "prev_root": "sha256:000...",
      "merkle_proof": ["sha256:ccc...", "sha256:ddd..."]
    },
    {
      "receipt_id": 2,
      "from_phase": "PLAN",
      "to_phase": "EXECUTE",
      "artifact_hash": "sha256:eee...",
      "proposed_at": "2026-01-10T14:22:00Z",
      "signature": "base64:...",
      "signer_key": "ed25519:7c3d...9a2f",
      "merkle_root": "sha256:fff...",
      "prev_root": "sha256:bbb...",
      "merkle_proof": ["sha256:ggg..."]
    }
  ],
  "current_merkle_root": "sha256:zzz..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `mission_id` | string | Echo |
| `cursor` | integer | Requested offset |
| `limit` | integer | Requested limit |
| `total` | integer | Total transition count for mission |
| `records` | array | Ordered by `receipt_id` ascending |
| `records[].merkle_proof` | array | Sibling hashes proving inclusion in current root |
| `current_merkle_root` | string | Root of full transition log for this mission |

#### Response 404 Not Found

Mission has no transitions.

---

## Authentication & Authorization

The API is intentionally minimal. Authentication is left to the infrastructure layer:

- **mTLS:** recommended for zero-trust environments (both client and server present certificates)
- **Network policy:** restrict orchestrator CIDR to `/transition`; allow monitoring to `/health`
- **Optional bearer token:** if required, supply `Authorization: Bearer <token>`; token validated in reverse proxy or API gateway, not by phase-controller itself

The phase-controller does **not** implement RBAC. It trusts that the transport layer has authenticated the caller.

## Error Format

All error responses use `application/problem+json`:

```json
{
  "type": "https://phase-controller.example/errors/{slug}",
  "title": "Human-readable title",
  "status": 400,
  "detail": "Longer explanation",
  "{context_key}": "additional machine-readable context"
}
```

| HTTP Status | `type` slug | When |
|-------------|-------------|------|
| 400 | `hash-mismatch`, `bad-request` | Malformed request, hash mismatch, invalid JSON |
| 409 | `transition-not-allowed` | Invalid phase transition |
| 422 | `artifact-validation-failed` | Schema or validator rejection |
| 500 | `internal-error` | Signing failure, unexpected DB error |
| 503 | `service-unavailable` | DB or signing backend unreachable |

## Rate Limits

| Endpoint | Default Limit |
|----------|---------------|
| `GET /health` | 100 req/s per source IP |
| `GET /phase` | 50 req/s per `mission_id` |
| `POST /transition` | 10 req/s per `mission_id` |
| `GET /audit` | 20 req/s per `mission_id` |

Exceeding limits returns `429 Too Many Requests` with `Retry-After` header.

## Versioning

The API version is embedded in the service version string returned by `/health`. There is no URL path version prefix (`/v1/...`). Breaking changes require a new service deployment with a new base URL or DNS name.

## Canonical JSON

For hashing and signing, JSON is canonicalized as follows:

1. UTF-8 encoding
2. No whitespace
3. Object keys sorted lexicographically
4. No trailing commas
5. Arrays preserve order
6. Numbers as bare literals (no leading `+`)

Example canonical form:

```json
{"artifact_hash":"sha256:abc123","from_phase":"INIT","mission_id":"mission-42","proposed_at":"2026-01-15T09:30:00Z","to_phase":"PLAN"}
```
