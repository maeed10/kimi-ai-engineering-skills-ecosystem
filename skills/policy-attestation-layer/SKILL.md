---
name: policy-attestation-layer
description: Cryptographic chain of custody linking every code change to the policy-engine decision that authorized it. Use when policy-engine makes tool call decisions, when code is generated during EXECUTE, when recording episodic memories, or when regulatory compliance requires tamper-evident audit trails. Creates a self-auditing codebase with Ed25519-signed Merkle tree linkage.
---

# Policy Attestation Layer

Cryptographic chain of custody linking every code change to the `policy-engine` decision that authorized it.

## Overview

This skill creates a **Self-Auditing Codebase**: every line of code can be traced back to a policy allow-signal via Ed25519-signed attestation records linked in a Merkle tree. When the policy-engine emits ALLOW/BLOCK/ESCALATE, an attestation record is created, signed, and embedded as metadata in generated code files. This addresses **Finding Prod-4 (Cryptographic Chain of Custody for Code)** from the Security Remediation Report.

## When to Trigger

- Immediately after `policy-engine` emits an ALLOW/BLOCK/ESCALATE decision for a tool call
- During EXECUTE phase, before writing any code file
- When `memory-guard` records episodic memories tied to policy decisions
- When `drift-monitor` requests audit data for anomaly detection
- When compliance reporting requires tamper-evident change audit trails

## Core Workflow

### Step 1: Capture Policy Decision

When the policy-engine emits a decision:

```python
decision = {
    "decision_id": "<uuid>",          # Unique per decision
    "timestamp": "<ISO8601>",
    "tool_call": "<tool_name>",
    "arguments_hash": "<blake2b>",    # Hash of canonicalized args
    "decision": "ALLOW|BLOCK|ESCALATE",
    "justification_hash": "<blake2b>", # Hash of policy rule matched
    "policy_version": "<semver>",
    "session_id": "<session_uuid>",
}
```

Compute `arguments_hash` as BLAKE2b over canonical JSON of tool arguments (sorted keys, no whitespace).
Compute `justification_hash` as BLAKE2b over the matched policy rule text.

### Step 2: Create and Sign Attestation Record

Use `scripts/create_attestation.py` to create the attestation:

```bash
python scripts/create_attestation.py \
  --decision-json decision.json \
  --previous-hash <prev_merkle_root> \
  --output attestation.json
```

The script:
1. Loads the Ed25519 signing key from `POLICY_ATTESTATION_KEY` env var (base64-encoded 32-byte seed)
2. Computes the Merkle leaf hash: `BLAKE2b(decision_id || arguments_hash || decision || timestamp)`
3. Combines with `previous_hash` to form a new Merkle root
4. Signs the root: `Ed25519.sign(merkle_root)`
5. Outputs the attestation record (see schema in `references/attestation_schema.md`)

If `POLICY_ATTESTATION_KEY` is not set, the script generates an ephemeral key pair, logs a warning, and stores the public key in the attestation.

### Step 3: Embed Attestation in Code Metadata

For every code file generated under an ALLOW decision, prepend an attestation header:

```python
# ATTESTATION: decision_id=550e8400-e29b-41d4-a716-446655440000
# ATTESTATION: merkle_root=a1b2c3d4...e5f6
# ATTESTATION: signature=3f4a5b6c...7d8e
# ATTESTATION: policy_version=1.2.3
# ATTESTATION: timestamp=2025-01-15T10:30:00Z
# ATTESTATION: tool_call=write_file
#
# To verify: python scripts/create_attestation.py --verify --file <this_file>
```

For multi-line headers in other languages:

```javascript
/* ATTESTATION: decision_id=550e8400-e29b-41d4-a716-446655440000
   ATTESTATION: merkle_root=a1b2c3d4...e5f6
   ATTESTATION: signature=3f4a5b6c...7d8e */
```

Rules:
- One attestation header per file. If multiple decisions contributed, use the most recent ALLOW decision.
- BLOCK decisions do not generate code; attestation is stored in the append-only log only.
- ESCALATE decisions create attestation with `"escalation_target": "<human_or_higher_tier>"`.

### Step 4: Update Append-Only Log

Append the attestation record to `.policy/attestation_log.jsonl`:

```json
{"merkle_root":"a1b2c3d4...","signature":"3f4a5b6c...","decision_id":"550e8400...","timestamp":"2025-01-15T10:30:00Z","leaf_hash":"f5e6d7c8...","previous_root":"b2c3d4e5..."}
```

This log must never be modified in-place. Each line is a complete Merkle tree node.

### Step 5: Link Episodic Memory

When `memory-guard` records an episodic memory tied to a policy decision:

```python
memory_entry = {
    "memory_id": "<uuid>",
    "decision_id": "550e8400-e29b-41d4-a716-446655440000",  # <-- link
    "memory_type": "episodic",
    "content_hash": "<blake2b>",
    "timestamp": "<ISO8601>",
}
```

This cross-reference enables queries like: "show all memories associated with decision X."

## Query Interface

### Query: "Show all code authorized by decision X"

```bash
# Search for attestation headers referencing a decision_id
grep -r "ATTESTATION: decision_id=550e8400-e29b-41d4-a716-446655440000" \
  --include="*.py" --include="*.js" --include="*.ts" --include="*.md" .
```

### Query: "What policy allowed this line?"

```bash
python scripts/create_attestation.py --query --file ./src/main.py --line 42
```

This extracts the attestation header from the file, verifies the signature, looks up the decision in `.policy/attestation_log.jsonl`, and returns:

```json
{
  "decision_id": "550e8400-e29b-41d4-a716-446655440000",
  "decision": "ALLOW",
  "justification_hash": "a3b4c5d6...",
  "policy_version": "1.2.3",
  "timestamp": "2025-01-15T10:30:00Z",
  "merkle_root": "a1b2c3d4...",
  "verified": true
}
```

### Query: "Verify full chain integrity"

```bash
python scripts/create_attestation.py --verify-chain --log .policy/attestation_log.jsonl
```

Iterates through the log, verifying every signature and Merkle linkage. Returns exit code 0 if valid, 1 if tampering detected.

## Merkle Tree Structure

```
Leaf(i) = BLAKE2b(decision_id || arguments_hash || decision || timestamp)
Node(0) = Leaf(0)  [genesis]
Node(n) = BLAKE2b(Node(n-1) || Leaf(n))  [chained]
Root    = latest Node(n)
```

Each attestation record contains:
- `leaf_hash`: hash of the current decision
- `previous_root`: the Merkle root from the prior record
- `merkle_root`: `BLAKE2b(previous_root || leaf_hash)`
- `signature`: Ed25519 signature over `merkle_root`

This structure makes tampering detectable: changing any decision changes all subsequent roots and invalidates all signatures.

## Compliance Reporting

Generate a compliance report:

```bash
python scripts/create_attestation.py --compliance-report \
  --log .policy/attestation_log.jsonl \
  --output report.json
```

Produces:

```json
{
  "report_id": "<uuid>",
  "generated_at": "<ISO8601>",
  "policy_version": "1.2.3",
  "total_decisions": 1523,
  "allow_count": 1489,
  "block_count": 21,
  "escalate_count": 13,
  "chain_integrity": true,
  "first_decision": "2025-01-01T00:00:00Z",
  "last_decision": "2025-01-15T23:59:59Z",
  "public_key": "<ed25519_pub>",
  "merkle_root": "a1b2c3d4..."
}
```

## Key Storage and Rotation

- Signing key: `POLICY_ATTESTATION_KEY` environment variable (base64-encoded 32-byte Ed25519 seed)
- Public key: stored in `.policy/attestation_pubkey.pem` and embedded in every attestation record
- Rotation: when rotating keys, append a `KEY_ROTATION` decision type to the log with `new_public_key` field
- Ephemeral fallback: if key not provided, generate ephemeral key and log warning

## Integration Points

| Component | Integration |
|-----------|-------------|
| `policy-engine` | Emits decisions consumed by this layer |
| `memory-guard` | References `decision_id` in episodic memories |
| `drift-monitor` | Reads attestation log for anomaly detection |
| Code generation | Embeds attestation headers in all output files |

## Resources

- `references/attestation_schema.md` — JSON schema for attestation records, Merkle tree node structure, and code header format
- `scripts/create_attestation.py` — Create signed attestation records, verify chain, query by file/line, generate compliance reports
