# Changelog

## [4.2.1] — 2025-05-09

### Added
- Expanded to **100 skills** from the original 59
- **Tiered sandbox profiles** — Light (1 CPU / 512 Mi / 60s), Standard (2 CPU / 4 Gi / 600s), Heavy (4 CPU / 8 Gi / 600s)
- **Complete observability suite** — 11 alerting rules (OBS-001 through OBS-011) with PowerShell and Python monitor implementations
- `adversarial-tester-expanded` — 100+ attack cases across 10 categories

### Changed
- EXEC-013 resource limits now enforce declared tiered profiles instead of flat caps
- All heavy-profile skills updated to declare `profile: heavy` in sandbox configs
- `sandbox-executor.py` normalizes capabilities against tiered envelopes before validation

### Fixed
- Resolved conflict where heavy-profile skills declared timeouts exceeding flat EXEC-013 cap
- ECOSYSTEM-OPERATIONS.md fully synchronized with current policy text

## [4.2.0] — 2025-05-08

### Added
- `multi-model-router` — Provider-agnostic cost-tier dispatcher
- `cost-tier-security-gate` — Blocks security-sensitive tasks from external routing
- `post-gemini-validator` — Deterministic output validation for external model responses
- Policy engine attestation upgraded to Ed25519-signed Merkle trees

## [4.1.0] — 2025-05-01

### Added
- `federated-memory-mesh` — Cross-instance memory sharing protocol
- `runtime-taint-tracker` — Data provenance tracking
- `tee-executor` — Trusted Execution Environment backend

## [4.0.0] — 2025-04-20

### Added
- Seven-phase pipeline with hash-verified transitions
- Policy engine v4.0 — 144 machine-readable rules
- Phase controller v4.0 — Deterministic FSM
- Tool execution gateway v4.0 — 8 security gates
- Sandbox executor — Docker isolation with seccomp
- IPI defender — Multi-layer prompt injection defense

## [3.x] — 2025-04

### Overview
- Early prototype phase
- Skill count: 10 → 50
- Prompt-based policy enforcement
- Direct host subprocess execution (no sandbox)
