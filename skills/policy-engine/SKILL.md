---
name: policy-engine
description: >
  External policy engine that parses machine-readable safety rules and enforces them BEFORE any tool call reaches the OS. Transforms prompt-based safety into programmatic, fail-closed guarantees. Acts as the sole enforcement layer for the 144 ALWAYS/NEVER rules previously existing only as natural language in SKILL.md files. Intercepts every proposed tool call, validates against typed rule objects, and returns allow/block/escalate with full audit trail. Provides cryptographic chain of custody and tamper-evident audit trails via Ed25519-signed attestation records and Merkle tree linkage, creating a self-auditing codebase where every code change is traceable to the policy decision that authorized it. Integrates with tool-execution-gateway, phase-controller, skill-registry, and sandbox-executor.
---

# policy-engine — Policy Engine

## Overview

The `policy-engine` skill transforms the ecosystem's natural-language safety rules
into executable, programmatic policies. It acts as the sole enforcement layer between
the orchestrator and the operating system: every proposed tool call, phase
transition, skill activation, and sandbox configuration is validated against
loaded policies before execution proceeds.

The engine operates on a **fail-closed** principle: if validation cannot be
performed (missing policy, corrupt file, runtime exception), the action is
**BLOCKED**. The LLM is never trusted to self-enforce rules; enforcement is
external, deterministic, and auditable.

## Core Capabilities

### 1. Policy Loading & Integrity Validation

At session start, the engine discovers and loads all `.json` policy files from
the `policy/` directory (populated by rules contributed from all skills). Before
parsing, each file's SHA-256 hash is validated against a trusted manifest.

**ALWAYS** validate file integrity before loading.  
**NEVER** load a policy file with a hash mismatch or parse error.  
**NEVER** modify policy files during a session (read-only after load).

**Workflow:**
1. Enumerate `policy/**/*.json`
2. Compute SHA-256; verify against `policy/manifest.json`
3. Validate JSON against `references/rule-schema.md`
4. Parse into typed rule objects
5. Store immutable rule registry in memory
6. Log `POLICY_LOAD` event for each file

### 2. Rule Classification & Registry

Rules are typed by the resource they protect. Each rule carries a severity
(`info`, `warning`, `error`, `critical`), a directive (`ALWAYS` | `NEVER`),
conditions (matchers), and an action (`allow`, `block`, `escalate`).

| Rule Type | Scope | Example |
|-----------|-------|---------|
| `FilesystemRule` | Allowed paths, read/write modes, path traversal | NEVER write outside `/mnt/agents/output` |
| `NetworkRule` | Allowed domains, protocols, ports | ONLY `api.github.com:443` |
| `ExecutionRule` | Allowed commands, blocked patterns | NEVER `rm -rf /` |
| `DataRule` | PII handling, retention, redaction | ALWAYS redact SSNs in logs |
| `PhaseRule` | Allowed phase transitions | NEVER transition `DEPLOY` → `DESIGN` |
| `SkillRule` | Allowed activations by phase | NEVER activate `sandbox-executor` in `ANALYSIS` phase |

Rules support boolean combinators:
- `ALL_OF` — every sub-condition must match
- `ANY_OF` — at least one sub-condition must match
- `NOT` — condition must not match

### 3. Pre-Execution Validation

For every tool call proposal from the `tool-execution-gateway`, the engine runs
`PolicyEngine.validate(tool_request)`.

**Matching logic:**
1. Filter rules whose `applies_to.tool` matches the requested tool (or `*`)
2. Evaluate each rule's conditions against the request payload
3. Collect all triggered rules

**Decision logic (strict priority order):**

| Triggered Rules | Result | Rationale |
|-----------------|--------|-----------|
| ANY `NEVER` rule matches | **BLOCK** | Fail-closed: violation detected |
| ANY `ALWAYS` rule does NOT match | **BLOCK** | Mandatory requirement unsatisfied |
| `NEVER` + `ALWAYS` both present | **BLOCK** | Never wins; violation supersedes |
| No rules triggered | **ALLOW** | Default deny is off; only explicit rules govern |
| `ESCALATE` action configured | **ESCALATE** | Human approval required before allow |

**Return envelope:**
```json
{
  "action": "allow | block | escalate",
  "reason": "string: human-readable rationale",
  "violated_rules": [
    {
      "rule_id": "string",
      "rule_type": "filesystem | network | execution | data | phase | skill",
      "directive": "ALWAYS | NEVER",
      "severity": "info | warning | error | critical",
      "message": "string"
    }
  ],
  "request_id": "uuid",
  "timestamp": "ISO8601",
  "policy_version": "sha256-of-manifest"
}
```

### 4. Post-Execution Verification

After the LLM response is generated, `PolicyEngine.verify_response()` scans
the response for:
- Proposed tool calls that bypassed pre-validation (e.g., hidden in markdown)
- Disclosure of sensitive data prohibited by `DataRule`
- Policy bypass attempts (`override`, `exception`, `ignore policy`)

If post-execution violations are found, the engine:
1. Flags the session for audit
2. Blocks any subsequent dependent tool calls
3. Logs `POST_EXEC_VIOLATION` with full response excerpt

### 5. Audit Logging

Every policy decision produces an immutable audit record. The audit subsystem
operates independently of the policy engine to prevent tampering.

**ALWAYS** log the following fields:
- `event_type`: `POLICY_LOAD | PRE_EXEC_ALLOW | PRE_EXEC_BLOCK | PRE_EXEC_ESCALATE | POST_EXEC_VIOLATION | POLICY_BYPASS_ATTEMPT`
- `timestamp`: ISO8601 with millisecond precision
- `request_id`: UUID correlating to the tool call or phase transition
- `tool`: Tool name (or `phase/skill/sandbox` for non-tool events)
- `rule_triggered`: List of rule IDs that fired
- `severity`: Max severity among triggered rules
- `action`: `allow | block | escalate`
- `rationale`: Full human-readable explanation
- `context_hash`: SHA-256 of the request payload (for integrity verification)
- `policy_version`: Hash of the manifest at decision time

**NEVER** omit a log entry when a policy decision is made.  
**NEVER** allow the LLM to modify, redact, or skip audit records.

### 6. Integration Contracts

#### tool-execution-gateway
- Gateway **MUST** call `PolicyEngine.validate(tool_request)` before executing any tool.
- Gateway **MUST** treat `block` as a hard stop; the tool is not invoked.
- Gateway **MUST** treat `escalate` as a soft stop; hold the request pending human approval.
- Gateway **MUST** attach the returned envelope to the tool response metadata.

#### phase-controller
- Before any phase transition, `PhaseController.validate_transition(current, proposed)` delegates to `PolicyEngine.validate(...)` with a synthetic tool request of type `phase_transition`.
- Cyclical or unauthorized transitions are blocked by `PhaseRule`.

#### skill-registry
- `SkillRegistry.activate(skill_name)` calls `PolicyEngine.validate(...)` with a synthetic tool request of type `skill_activation`.
- `SkillRule` checks the calling phase and dependencies.

#### sandbox-executor
- `SandboxExecutor.configure(config)` calls `PolicyEngine.validate(...)` with a synthetic tool request of type `sandbox_config`.
- `FilesystemRule` and `NetworkRule` constrain allowed mounts, directories, and egress domains.
- **Critical**: The policy-engine endpoint is isolated from sandbox network namespaces. Sandboxes with `network: true` CANNOT reach the policy engine via REST API. Validation occurs in the host namespace before container creation.

## Safety Rules (Engine-Level Guarantees)

These are the foundational guarantees the `policy-engine` itself provides. They
mirror and enforce the 144 ecosystem rules.

### ALWAYS
- **A1.** ALWAYS enforce loaded policies for every tool call without exception.
- **A2.** ALWAYS log every policy decision with full context and rationale.
- **A3.** ALWAYS validate policy file integrity (SHA-256) before loading.
- **A4.** ALWAYS return a clear `reason` string when blocking or escalating.
- **A5.** ALWAYS fail closed if the engine encounters an internal error.
- **A6.** ALWAYS use deterministic rule matching; never use probabilistic or LLM-based matching for safety-critical rules.

### NEVER
- **N1.** NEVER allow a tool call to proceed if ANY `NEVER` rule is triggered.
- **N2.** NEVER modify policy files during runtime (read-only during session).
- **N3.** NEVER trust the LLM to self-enforce rules — this skill IS the enforcement layer.
- **N4.** NEVER allow policy bypass via "override", "exception", or "ignore policy" without explicit human approval.
- **N5.** NEVER expose policy internals (rule IDs, hashes, bypass mechanisms) in user-facing output.
- **N6.** NEVER load policies from untrusted or non-manifest-listed paths.

## Workflow

```
Session Start
      |
      v
[1] Load policy/ directory
      - Enumerate .json files
      - SHA-256 integrity check
      - Schema validation
      - Parse into typed rules
      |
      v
[2] Build immutable rule registry
      |
      v
[3] Receive tool call / phase change / skill activation / sandbox config
      |
      v
[4] Match request against applicable rules
      |
      v
[5] Evaluate rule conditions
      |
      +-- NEVER rule triggered ----> [BLOCK] ----> Log + Escalate if critical
      |
      +-- ALWAYS rule unsatisfied -> [BLOCK] ----> Log
      |
      +-- ESCALATE action ---------> [ESCALATE] -> Log + Await human approval
      |
      +-- No rules triggered -------> [ALLOW] ---> Log
      |
      v
[6] Return decision envelope to caller
      |
      v
[7] Post-execution: scan LLM response for violations
      +-- Violation found ---------> Flag + Log + Block dependents
      +-- Clean -------------------> Continue
```

## Rule Schema & Examples

For the formal JSON schema, see `references/rule-schema.md`.

### Minimal Example: FilesystemRule
```json
{
  "rule_id": "FS-001",
  "version": "4.0.0",
  "rule_type": "filesystem",
  "directive": "NEVER",
  "severity": "critical",
  "description": "Prevent writing to system directories",
  "conditions": {
    "operator": "ANY_OF",
    "predicates": [
      { "field": "path", "operator": "prefix", "value": "/etc" },
      { "field": "path", "operator": "prefix", "value": "/usr/bin" },
      { "field": "path", "operator": "regex", "value": "^/sys/.*" }
    ]
  },
  "action": "block",
  "applies_to": {
    "tools": ["shell", "write_file", "edit_file"],
    "phases": ["*"]
  },
  "metadata": {
    "rationale": "System directory writes compromise host integrity",
    "remediation": "Write to /mnt/agents/output or request sandboxed path"
  }
}
```

### Minimal Example: NetworkRule
```json
{
  "rule_id": "NET-007",
  "version": "4.0.0",
  "rule_type": "network",
  "directive": "ALWAYS",
  "severity": "error",
  "description": "Only allow HTTPS to known domains",
  "conditions": {
    "operator": "ALL_OF",
    "predicates": [
      { "field": "protocol", "operator": "eq", "value": "https" },
      { "field": "domain", "operator": "in", "value": ["api.github.com", "pypi.org"] }
    ]
  },
  "action": "block",
  "applies_to": {
    "tools": ["web_search", "browser_visit", "get_data_source"],
    "phases": ["*"]
  },
  "metadata": {
    "rationale": "Prevent data exfiltration to unknown endpoints"
  }
}
```

### Minimal Example: PhaseRule
```json
{
  "rule_id": "PHASE-003",
  "version": "4.0.0",
  "rule_type": "phase",
  "directive": "NEVER",
  "severity": "critical",
  "description": "Prevent regression from DEPLOY to DESIGN",
  "conditions": {
    "operator": "ALL_OF",
    "predicates": [
      { "field": "from_phase", "operator": "eq", "value": "DEPLOY" },
      { "field": "to_phase", "operator": "eq", "value": "DESIGN" }
    ]
  },
  "action": "block",
  "applies_to": {
    "tools": ["phase_transition"],
    "phases": ["DEPLOY"]
  },
  "metadata": {
    "rationale": "Phase regression breaks traceability and safety gates"
  }
}
```

## Network Isolation Architecture

### The Sandbox-Reachability Problem

If the policy engine exposes its REST API on a network interface reachable from inside sandbox containers, an escaped process could:
1. Call `/validate` with forged arguments to get ALLOW decisions
2. Query `/audit-log` to exfiltrate execution history
3. Flood the API to cause denial-of-service

### Solution: Dual-Interface Design

```
Host Namespace (where policy-engine runs):
  ├─ Unix socket: /var/run/kimi/policy-engine.sock  ← Primary interface
  └─ Loopback TCP: 127.0.0.1:9100 (mTLS required)   ← Fallback for remote callers

Sandbox Network Namespace:
  ├─ network: none  → No access to any interface
  └─ network: whitelist  → Only allowed domains; 127.0.0.1:9100 explicitly blocked
```

**Enforcement:**
1. **Primary**: `policy-engine` listens on Unix domain socket `unix:/var/run/kimi/policy-engine.sock`
   - Not routable from any network namespace
   - File permissions: 0600, owner: kimi-daemon
   - `sandbox-executor` validates via this socket from the host namespace BEFORE creating the container

2. **Fallback**: Loopback TCP `127.0.0.1:9100` with mutual TLS
   - Only for external monitoring/healthcheck tools
   - Sandboxes with `network: true` get an explicit iptables/nftables DROP rule for 127.0.0.1:9100
   - mTLS client certificate required; sandbox containers do not possess the client cert

3. **Validation Order**:
   ```
   SandboxExecutor.run(request)
     → Host namespace: connect to unix:/var/run/kimi/policy-engine.sock
     → PolicyEngine.validate(request) → returns decision
     → Only AFTER validation: create container with requested capabilities
   ```

### Policy Rule: POLICY-NET-001

```json
{
  "rule_id": "POLICY-NET-001",
  "rule_type": "network",
  "directive": "NEVER",
  "severity": "critical",
  "description": "Prevent sandbox containers from reaching policy-engine API",
  "conditions": {
    "operator": "ANY_OF",
    "predicates": [
      { "field": "destination_ip", "operator": "eq", "value": "127.0.0.1" },
      { "field": "destination_port", "operator": "eq", "value": 9100 },
      { "field": "unix_socket_path", "operator": "prefix", "value": "/var/run/kimi/" }
    ]
  },
  "action": "block",
  "applies_to": {
    "tools": ["sandbox_execution"],
    "phases": ["*"]
  }
}
```

## Implementation Reference

The `scripts/policy-engine.py` template provides the `PolicyEngine` class with:
- `load_policies(policy_dir, manifest_path)`
- `validate(request: dict) -> DecisionEnvelope`
- `verify_response(response_text: str) -> List[Violation]`
- `get_audit_log() -> List[AuditRecord]`

## Failure Handling

| Condition | Engine Behavior | Caller Responsibility |
|-----------|---------------|---------------------|
| Policy hash mismatch | Skip file; log `POLICY_LOAD_FAILURE`; continue if other files valid | Gateways default to `block` if zero policies loaded |
| Schema validation error | Skip file; log `POLICY_LOAD_FAILURE` | Notify orchestrator of configuration drift |
| Runtime exception during validate | Return `block` with reason `ENGINE_INTERNAL_ERROR` | Retry once; if persists, escalate to human |
| Missing policy directory | Return `block` with reason `POLICY_DIR_UNAVAILABLE` | Halt session startup until resolved |
| Audit log write failure | Return `block`; safety takes priority over availability | Alert infrastructure operator |

## Versioning & Drift

- Policy files carry a `version` field (SemVer).
- The manifest carries an `ecosystem_version` that must match the orchestrator's declared version.
- On mismatch, the engine logs `VERSION_DRIFT` and blocks session start until alignment.

# Policy Attestation Layer

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

---

**Classification:** security-core | **Criticality:** p0-runtime-guard  
**Failure mode:** fail-closed | **Trust boundary:** engine sits below orchestrator, above OS/tools