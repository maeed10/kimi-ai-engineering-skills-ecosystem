# Attestation Schema Reference

JSON schemas and data formats for the policy attestation layer.

## 1. Policy Decision Record

Emitted by the policy-engine before attestation.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PolicyDecision",
  "type": "object",
  "required": ["decision_id", "timestamp", "tool_call", "arguments_hash", "decision", "justification_hash", "policy_version", "session_id"],
  "properties": {
    "decision_id":       {"type": "string", "format": "uuid", "description": "Unique decision identifier"},
    "timestamp":         {"type": "string", "format": "date-time", "description": "ISO 8601 timestamp"},
    "tool_call":         {"type": "string", "description": "Name of the tool being called"},
    "arguments_hash":    {"type": "string", "pattern": "^[a-f0-9]{64}$", "description": "BLAKE2b-256 of canonicalized JSON arguments"},
    "decision":          {"type": "string", "enum": ["ALLOW", "BLOCK", "ESCALATE", "KEY_ROTATION"]},
    "justification_hash":{"type": "string", "pattern": "^[a-f0-9]{64}$", "description": "BLAKE2b-256 of matched policy rule text"},
    "policy_version":    {"type": "string", "description": "Semantic version of the policy ruleset"},
    "session_id":        {"type": "string", "format": "uuid", "description": "Session that made the tool call"},
    "escalation_target": {"type": "string", "description": "Required when decision is ESCALATE"},
    "new_public_key":    {"type": "string", "description": "Required when decision is KEY_ROTATION, base64-encoded Ed25519 public key"}
  }
}
```

## 2. Attestation Record

Produced by `scripts/create_attestation.py` after signing.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AttestationRecord",
  "type": "object",
  "required": ["merkle_root", "signature", "decision_id", "timestamp", "leaf_hash", "previous_root", "public_key", "version"],
  "properties": {
    "merkle_root":  {"type": "string", "pattern": "^[a-f0-9]{64}$", "description": "BLAKE2b-256 of previous_root || leaf_hash"},
    "signature":    {"type": "string", "description": "Base64-encoded Ed25519 signature over merkle_root"},
    "decision_id":  {"type": "string", "format": "uuid"},
    "timestamp":    {"type": "string", "format": "date-time"},
    "leaf_hash":    {"type": "string", "pattern": "^[a-f0-9]{64}$", "description": "BLAKE2b-256 of decision_id || arguments_hash || decision || timestamp"},
    "previous_root":{"type": "string", "pattern": "^[a-f0-9]{64}$", "description": "Merkle root of previous attestation; 64 zeros for genesis"},
    "public_key":   {"type": "string", "description": "Base64-encoded Ed25519 public key that signed this record"},
    "version":      {"type": "string", "enum": ["1.0"], "description": "Attestation format version"},
    "metadata": {
      "type": "object",
      "properties": {
        "tool_call":      {"type": "string"},
        "arguments_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "decision":       {"type": "string", "enum": ["ALLOW", "BLOCK", "ESCALATE", "KEY_ROTATION"]},
        "justification_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "policy_version": {"type": "string"},
        "session_id":     {"type": "string", "format": "uuid"},
        "escalation_target": {"type": "string"},
        "new_public_key": {"type": "string"}
      }
    }
  }
}
```

## 3. Merkle Tree Node

Single line in `.policy/attestation_log.jsonl`.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MerkleNode",
  "type": "object",
  "required": ["merkle_root", "signature", "decision_id", "timestamp", "leaf_hash", "previous_root"],
  "properties": {
    "merkle_root":   {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "signature":     {"type": "string"},
    "decision_id":   {"type": "string", "format": "uuid"},
    "timestamp":     {"type": "string", "format": "date-time"},
    "leaf_hash":     {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "previous_root": {"type": "string", "pattern": "^[a-f0-9]{64}$"}
  }
}
```

## 4. Code File Attestation Header

Embedded in generated source files. Format varies by comment syntax.

### Python / Shell / YAML
```
# ATTESTATION: decision_id=<uuid>
# ATTESTATION: merkle_root=<64-hex>
# ATTESTATION: signature=<base64>
# ATTESTATION: policy_version=<semver>
# ATTESTATION: timestamp=<ISO8601>
# ATTESTATION: tool_call=<tool_name>
#
# To verify: python scripts/create_attestation.py --verify --file <this_file>
```

### JavaScript / TypeScript / C / Java / Go / Rust
```
/* ATTESTATION: decision_id=<uuid>
   ATTESTATION: merkle_root=<64-hex>
   ATTESTATION: signature=<base64>
   ATTESTATION: policy_version=<semver>
   ATTESTATION: timestamp=<ISO8601>
   ATTESTATION: tool_call=<tool_name>

   To verify: python scripts/create_attestation.py --verify --file <this_file> */
```

### HTML / XML
```
<!-- ATTESTATION: decision_id=<uuid>
     ATTESTATION: merkle_root=<64-hex>
     ATTESTATION: signature=<base64>
     ATTESTATION: policy_version=<semver>
     ATTESTATION: timestamp=<ISO8601>
     ATTESTATION: tool_call=<tool_name> -->
```

### Markdown
```markdown
<!-- ATTESTATION-BEGIN
     decision_id: <uuid>
     merkle_root: <64-hex>
     signature: <base64>
     policy_version: <semver>
     timestamp: <ISO8601>
     tool_call: <tool_name>
     ATTESTATION-END -->
```

## 5. Episodic Memory Cross-Reference

When memory-guard links a memory to a policy decision.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MemoryAttestationLink",
  "type": "object",
  "required": ["memory_id", "decision_id", "memory_type", "content_hash", "timestamp"],
  "properties": {
    "memory_id":   {"type": "string", "format": "uuid"},
    "decision_id": {"type": "string", "format": "uuid", "description": "FK to attestation record"},
    "memory_type": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
    "content_hash":{"type": "string", "pattern": "^[a-f0-9]{64}$", "description": "BLAKE2b-256 of memory content"},
    "timestamp":   {"type": "string", "format": "date-time"}
  }
}
```

## 6. Compliance Report

Output of `--compliance-report` command.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ComplianceReport",
  "type": "object",
  "required": ["report_id", "generated_at", "policy_version", "total_decisions", "allow_count", "block_count", "escalate_count", "chain_integrity", "first_decision", "last_decision", "public_key", "merkle_root"],
  "properties": {
    "report_id":      {"type": "string", "format": "uuid"},
    "generated_at":   {"type": "string", "format": "date-time"},
    "policy_version": {"type": "string"},
    "total_decisions":{"type": "integer", "minimum": 0},
    "allow_count":    {"type": "integer", "minimum": 0},
    "block_count":    {"type": "integer", "minimum": 0},
    "escalate_count": {"type": "integer", "minimum": 0},
    "chain_integrity":{"type": "boolean"},
    "first_decision": {"type": "string", "format": "date-time"},
    "last_decision":  {"type": "string", "format": "date-time"},
    "public_key":     {"type": "string"},
    "merkle_root":    {"type": "string", "pattern": "^[a-f0-9]{64}$"}
  }
}
```

## 7. Hash Computation Reference

### Canonical JSON for arguments_hash
```python
import json, hashlib

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def arguments_hash(arguments: dict) -> str:
    return hashlib.blake2b(canonical_json(arguments).encode(), digest_size=32).hexdigest()
```

### Leaf hash
```python
import hashlib

def leaf_hash(decision_id: str, arguments_hash: str, decision: str, timestamp: str) -> str:
    payload = f"{decision_id}||{arguments_hash}||{decision}||{timestamp}"
    return hashlib.blake2b(payload.encode(), digest_size=32).hexdigest()
```

### Merkle root (chained)
```python
def merkle_root(previous_root: str, leaf_hash: str) -> str:
    payload = f"{previous_root}||{leaf_hash}"
    return hashlib.blake2b(payload.encode(), digest_size=32).hexdigest()
```

### Genesis root (first entry)
```python
GENESIS_ROOT = "0" * 64  # 64 hex zeros
```
