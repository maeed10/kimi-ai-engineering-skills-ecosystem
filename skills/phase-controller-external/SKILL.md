---
name: phase-controller-external
description: Extracts phase-controller into an external state machine with independent persistence, minimal API, and cryptographic audit trails. Use when decoupling phase control from the orchestrator, designing artifact validation, or implementing transition audit logging. Persistence layer is separate from Obsidian vault.
---

# phase-controller-external

An externalized finite-state machine (FSM) for mission lifecycle phase control. Runs as an isolated process (container/pod) with its own persistence layer, exposes a minimal API, and maintains an append-only, cryptographically verifiable audit log of all phase transitions.

## Overview

When the phase-controller cannot live inside the same process as the orchestrator it controls, it must be extracted into a standalone service. This skill defines the architecture, API, persistence model, artifact schema registry, and cryptographic audit system for that external phase controller.

**Core principles:**

1. **Process isolation** — phase-controller runs in a separate container/pod from the orchestrator
2. **Independent persistence** — SQLite or PostgreSQL, NOT the Obsidian vault
3. **Append-only audit** — every transition is an immutable, signed record
4. **Schema-verified artifacts** — phase completion outputs must match versioned JSON schemas
5. **Deterministic validation** — reference validator functions are pure, testable, and version-locked
6. **Minimal API surface** — only three operations: query phase, propose transition, get audit log

## Architecture

### System Context

```
┌─────────────────────┐         ┌─────────────────────────────┐
│   Orchestrator      │         │   Phase Controller          │
│   (external process)│◄────────┤   (external service)        │
│                     │  HTTP   │   ┌───────────────────────┐ │
│   • No direct DB    │         │   │   FSM Engine          │ │
│   • Calls API only  │         │   │   • Phase graph       │ │
│   • Consumes audit  │         │   │   • Transition rules  │ │
│     log for verify  │         │   │   • Artifact validators│ │
└─────────────────────┘         │   └───────────────────────┘ │
                                │   ┌───────────────────────┐ │
                                │   │   Persistence         │ │
                                │   │   • Current phase     │ │
                                │   │   • Transition log    │ │
                                │   │   • Artifact store    │ │
                                │   │   • Merkle tree       │ │
                                │   └───────────────────────┘ │
                                └─────────────────────────────┘
```

### Isolation Requirements

- **Network boundary:** orchestrator communicates via HTTP/gRPC, never via shared memory or direct DB connection
- **Compute boundary:** phase-controller runs in a separate container image or pod
- **Storage boundary:** phase-controller owns its DB files; orchestrator has zero filesystem access to them
- **Failure boundary:** if the orchestrator panics, the phase-controller remains alive and its state is intact
- **Scaling boundary:** phase-controller may be replicated behind a load balancer; orchestrator may not assume co-location

### Phase State Graph

Missions pass through exactly 7 phases in order:

```
INIT ──► PLAN ──► EXECUTE ──► VERIFY ──► REPORT ──► ARCHIVE ──► CLOSED
  │        │         │          │          │           │           │
  └────────┴─────────┴──────────┴──────────┴───────────┴───────────┘
                              (no skips, no loops)
```

Allowed transitions:

| From     | To       | Requires artifact | Validator |
|----------|----------|-------------------|-----------|
| `INIT`   | `PLAN`   | `init_manifest`   | `v1`      |
| `PLAN`   | `EXECUTE`| `plan_spec`       | `v1`      |
| `EXECUTE`| `VERIFY` | `execute_log`     | `v1`      |
| `VERIFY` | `REPORT` | `verify_results`  | `v1`      |
| `REPORT` | `ARCHIVE`| `report_digest`   | `v1`      |
| `ARCHIVE`| `CLOSED` | `archive_bundle`  | `v1`      |

Any other transition is rejected with `TransitionNotAllowed`.

## Persistence Design

### Database Choice

- **Default:** SQLite (single file, zero-config, sufficient for single-tenant deployments)
- **Production:** PostgreSQL (when horizontal scaling, multi-tenancy, or HA are required)
- **Migration path:** identical schema, switch connection string; no logic change

### Schema

```sql
-- Current phase singleton. Exactly one row, updated in place.
CREATE TABLE current_phase (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    phase      TEXT    NOT NULL CHECK (phase IN (
                 'INIT','PLAN','EXECUTE','VERIFY','REPORT','ARCHIVE','CLOSED')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    mission_id TEXT    NOT NULL
);

-- Append-only transition log. Never UPDATE, never DELETE.
CREATE TABLE transition_log (
    id           BIGSERIAL PRIMARY KEY,
    mission_id   TEXT    NOT NULL,
    from_phase   TEXT    NOT NULL,
    to_phase     TEXT    NOT NULL,
    artifact_hash TEXT   NOT NULL,  -- SHA-256 of artifact JSON
    artifact_cid TEXT,              -- optional content-addressable ID
    proposed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    signature    BYTEA   NOT NULL,    -- Ed25519 signature of canonical record
    signer_key   TEXT   NOT NULL,    -- Ed25519 public key hex
    merkle_root  TEXT   NOT NULL,    -- root after appending this record
    prev_root    TEXT   NOT NULL     -- root before appending this record
);

CREATE INDEX idx_transition_mission ON transition_log(mission_id);
CREATE INDEX idx_transition_proposed ON transition_log(proposed_at);

-- Artifact content store (optional, can be external blob store)
CREATE TABLE artifacts (
    hash        TEXT PRIMARY KEY,   -- SHA-256, self-verifying
    schema_id   TEXT    NOT NULL,   -- e.g. "plan_spec/v1"
    content     JSONB   NOT NULL,
    stored_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Append-Only Contract

1. Rows in `transition_log` are INSERT-only.
2. `signature` covers the canonical JSON `{mission_id, from_phase, to_phase, artifact_hash, prev_root, proposed_at}`.
3. `merkle_root` is recomputed after each insert using `prev_root` and the new record hash.
4. A background verifier task can walk the table in `id` order and rebuild the Merkle tree; any mismatch indicates tampering.

## Artifact Schema Registry

Every phase transition requires a completion artifact. Each artifact type has a versioned JSON Schema and a deterministic validator.

### Registry Location

- **Runtime:** `schemas/` directory mounted into the phase-controller container
- **Format:** `{artifact_type}/{version}.schema.json` + `{artifact_type}/{version}.validator.py`
- **Load:** at startup, the FSM engine validates that every required transition has a schema and validator available

### Schema Versioning Rules

1. Schemas are immutable after release. A change requires a new version.
2. The FSM engine accepts `vN` artifacts only when configured for that version.
3. Backwards compatibility is achieved by the orchestrator choosing which schema version to target, not by the schema itself being lenient.
4. Validator functions are pure (no I/O, no global state) and pinned 1:1 with schema versions.

See `references/artifact_schemas.md` for the full schema definitions of all 7 phase artifacts.

## Cryptographic Audit System

### Ed25519 Signatures

Every transition record is signed with Ed25519 before insertion.

- **Signer:** the phase-controller service itself (not the orchestrator)
- **Key management:** private key loaded from `PHASE_CONTROLLER_PRIVATE_KEY` env var or mounted secret; public key exposed via `/health` for verification
- **Signature payload** (canonical JSON, no whitespace, keys sorted):
  ```json
  {"artifact_hash":"sha256:abc...","from_phase":"INIT","merkle_root":"sha256:def...","mission_id":"mission-42","prev_root":"sha256:000...","proposed_at":"2026-01-15T09:30:00Z","to_phase":"PLAN"}
  ```

### Merkle Tree

The `transition_log` forms a Merkle chain.

- **Leaf hash:** `SHA-256(canonical_json(record))`
- **Node hash:** `SHA-256(left + right)` (standard binary Merkle tree)
- `prev_root` on record N = `merkle_root` of record N-1 (or `sha256:000...` for genesis)
- `merkle_root` on record N = `MerkleRoot(leaves[0..N])`

### Verification Modes

1. **Online:** caller receives `{record, signature, merkle_proof}` and verifies signature + proof path against latest root from `/audit/head`.
2. **Offline:** auditor exports full `transition_log` ordered by `id`, recomputes Merkle tree locally, compares final root against published root.
3. **Incremental:** verifier maintains running root; each new record is validated and root updated in O(log N) via Merkle proof.

## API Overview

The phase-controller exposes exactly three endpoints (plus health). Full specification is in `references/api_spec.md`.

| Endpoint | Purpose |
|----------|---------|
| `GET /phase?mission_id={id}` | Query current phase for a mission |
| `POST /transition` | Propose a phase transition |
| `GET /audit?mission_id={id}&cursor={n}` | Get paginated, signed transition records |
| `GET /health` | Service health + public key |

### Typical Orchestrator Flow

1. Orchestrator finishes work for current phase.
2. Orchestrator builds artifact JSON and computes `artifact_hash`.
3. Orchestrator calls `POST /transition` with `{mission_id, to_phase, artifact, artifact_hash}`.
4. Phase-controller validates:
   - `to_phase` is the correct next phase
   - `artifact_hash` matches provided artifact
   - artifact validates against registered schema + validator
5. Phase-controller signs record, appends to `transition_log`, updates `current_phase`, returns signed receipt.
6. Orchestrator may call `GET /audit` to fetch receipt and verify signature locally.

## Failure Handling

| Scenario | Behavior |
|----------|----------|
| Orchestrator proposes invalid transition | HTTP 409 `TransitionNotAllowed` |
| Artifact fails schema validation | HTTP 422 `ArtifactValidationFailed` (details in body) |
| Signature verification fails (internal) | HTTP 500, logged as critical; service continues but alarm raised |
| Merkle root mismatch (internal) | HTTP 500, service enters read-only mode until operator intervention |
| DB unavailable | HTTP 503, retry with exponential backoff |
| Duplicate proposal (same hash) | HTTP 200 with existing receipt (idempotent) |

## Deployment

### Minimal Docker Compose

```yaml
services:
  phase-controller:
    image: phase-controller:latest
    environment:
      DATABASE_URL: "sqlite:///data/phase.db"
      PHASE_CONTROLLER_PRIVATE_KEY: /run/secrets/signing_key
    volumes:
      - phase_data:/data
    secrets:
      - signing_key
    ports:
      - "8080:8080"
  orchestrator:
    image: orchestrator:latest
    environment:
      PHASE_CONTROLLER_URL: "http://phase-controller:8080"
    # NO access to phase_data volume

volumes:
  phase_data:

secrets:
  signing_key:
    file: ./signing_key.pem
```

### Kubernetes

- Run as separate `Deployment` in same or different namespace
- `NetworkPolicy` to allow orchestrator → phase-controller on port 8080 only
- `PersistentVolumeClaim` for SQLite; or external PostgreSQL with `Secret` for credentials
- `Secret` / `ExternalSecrets` for Ed25519 private key
- Liveness/readiness probes on `/health`

## Security Considerations

1. **Private key protection:** never log, never expose in env var to sidecars, mount as read-only volume or use HSM/KMS.
2. **Artifact size limit:** enforce max JSON size (default 10 MB) to prevent DoS.
3. **Rate limiting:** `POST /transition` should be rate-limited per `mission_id`.
4. **SQL injection:** only parameterized queries; no dynamic schema.
5. **Replay protection:** `proposed_at` + monotonic `id` prevents replay within tolerance window.

## References

- `references/api_spec.md` — Complete API specification
- `references/artifact_schemas.md` — Versioned JSON schemas and validators for all 7 phase artifacts
- `scripts/validate_transition.py` — Standalone script for validating a proposed transition offline
