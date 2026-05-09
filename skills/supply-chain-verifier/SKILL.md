---
name: supply-chain-verifier
description: Cryptographic supply chain integrity verifier using TUF and Sigstore/cosign to sign and verify all skill packages, container images, and metadata before loading. Use during skill-registry loading, image verification, dependency resolution, and any supply chain trust validation. Ensures SHA-256 alone cannot be bypassed by manifest tampering.
---

# Supply Chain Verifier

## Overview

Replace SHA-256-only checksums with a defense-in-depth signing stack: TUF (The Update Framework) for skill-package and metadata updates, Sigstore/cosign for container-image signing, and a hardcoded root-of-trust that is bootstrapped offline. This skill must be loaded before any skill-registry REGISTERED → LOADED transition or before any sandbox image is executed.

## Core Capabilities

1. **TUF Skill-Package Verification** — Validate `root.json`, `targets.json`, `snapshot.json`, `timestamp.json` chain for every skill package.
2. **Sigstore/Cosign Image Verification** — Verify container-image signatures against a fixed OIDC identity or public-key fingerprint before sandbox execution.
3. **Threshold-Signed Releases** — Require 2-of-3 release-key signatures on the `targets` role; root key is 3-of-5.
4. **Hardcoded Root-of-Trust** — One root public key is embedded in the verifier binary/config; all other trust is derived from it.
5. **Dependency-Feed Integrity** — External vulnerability feeds (OSV, GitHub Advisory) are verified via Sigstore-signed checksum files.
6. **Policy & Config Binding** — `sandbox-config.yaml` and policy files carry detached cosign signatures that are checked against the same root.

## Trust Hierarchy

```
Root Key (3-of-5, offline)          [hardcoded fingerprint]
    │
    ▼
Targets Key (2-of-3, HSM-backed)
    │
    ├── Skill Package A (signed payload: manifest.json + archive digest)
    ├── Skill Package B
    ├── sandbox-config.yaml
    └── policy-bundle.json
    │
    ▼
Snapshot Key (1-of-1, online)  →  snapshot.json (protects rollback)
    │
    ▼
Timestamp Key (1-of-1, online) → timestamp.json (freshness)

Container Image Trust (Sigstore)
    │
    ▼
Cosign public-key / OIDC identity
    ├── sandbox-executor:latest  (signature + SBOM attestation)
    ├── runtime-base:sha-256...  (signature)
    └── dependency-resolver:1.x  (signature)
```

## Verification Workflow

### 1. Skill-Package Verification (TUF)

**Trigger:** `skill-registry` receives a REGISTER or UPDATE event.

```
Given: skill-name, version, tarball_path, tuf_repo_url
1. Fetch root.json (max 16 KiB). Verify its version ≤ embedded MAX_ROOT_VERSION.
2. Verify root.json self-signature meets threshold (3-of-5).
3. Derive targets key from root → verify targets.json signature (2-of-3).
4. Verify snapshot.json against targets key, then timestamp.json against snapshot key.
5. Lookup skill-name in targets.json; extract custom metadata:
   { "sha256": "...", "length": N, "signatures": [...] }
6. Stream-download tarball; compute SHA-256; verify length.
7. Verify detached package signature (Ed25519 or RSA-PSS) in custom metadata
   against release keys listed in targets.json.
8. Only if (5)–(7) pass: transition REGISTERED → LOADED.
```

**Failure modes:** see § Failure & Alert Matrix.

### 2. Container-Image Verification (Sigstore/Cosign)

**Trigger:** `sandbox-executor` pulls an image before starting a container.

```
Given: image_ref, expected_digest, sigstore_rekor_url, cosign_pub_key
1. Enforce: image_ref must be digest-pin (sha256:...), tag alone is rejected.
2. cosign verify --key cosign_pub_key --rekor-url <url> <image_ref>
3. Inspect OCI attestation layer for in-toto SBOM predicate.
4. Verify SBOM subject matches image digest.
5. Only if (2)–(4) pass: allow docker run / nerdctl run.
```

### 3. Dependency-Feed Verification

**Trigger:** `dependency-resolver` fetches OSV or GitHub Advisory data.

```
Given: feed_url, feed_signature_url, feed_checkpoint
1. Download feed + detached signature.
2. Verify signature against targets.json entry for external-feeds role.
3. Verify feed checkpoint (Rekor inclusion proof) if feed is Sigstore-signed.
4. Only on pass: parse feed and apply to dependency graph.
```

### 4. Policy / Config Binding

**Trigger:** `sandbox-config.yaml` or policy bundle is staged for enforcement.

```
Given: config_path, config_sig_path
1. Read config and detached signature.
2. Verify signature against targets.json entry for policy/<config-name>.
3. Compute SHA-256 of config; match against targets.json hash.
4. Bind config to the running agent's attestation hash.
```

## Key Ceremony & Rotation

See `references/key_ceremony.md` for the complete offline root-key generation, threshold (2-of-3) release signing, and root-key rotation ceremony.

Summary:
- Root keys: 5 offline HSM/YubiKeys, Shamir-split backup. Threshold 3.
- Targets/Release keys: 3 HSM-backed keys. Threshold 2.
- Snapshot/Timestamp: 1 online key each, short-lived (30 days), auto-rotated.
- Rotation: New root.json is signed by the old threshold; old root is retained for 2 update cycles.

## TUF + Sigstore Integration

See `references/tuf_sigstore_guide.md` for metadata schemas, delegation layout, Rekor integration, and trust boundary definitions.

Summary:
- TUF metadata lives in tuf-repo.skills.internal/ with standard layout.
- Sigstore signatures are stored as in-toto attestations linked from TUF targets metadata via custom.sigstore.
- Rekor inclusion proofs are cached offline for 7 days before requiring re-verification.

## Failure & Alert Matrix

| Failure | Immediate Action | Registry Transition | Alert Level |
|---------|------------------|---------------------|-------------|
| root.json self-sig threshold NOT met | REJECT; do not download further metadata | BLOCKED | P0 — security incident |
| targets.json sig threshold NOT met | REJECT; freeze all package loads | BLOCKED | P0 — security incident |
| snapshot/timestamp replay / rollback | REJECT; log version numbers | BLOCKED | P1 — possible freeze attack |
| package digest mismatch targets.json | REJECT; delete partial download | BLOCKED | P1 — tampered package |
| package detached signature invalid | REJECT | BLOCKED | P0 — unauthorized release key |
| container image cosign verify fails | REJECT; do not run container | BLOCKED | P0 — untrusted image |
| image SBOM attestation missing | WARN; allow only if policy flag set | CONDITIONAL | P2 — compliance gap |
| dependency feed signature invalid | REJECT feed; fallback to stale cache | DEGRADED | P1 — feed compromise |
| sandbox-config signature invalid | REJECT config; enforce last known good | BLOCKED | P0 — policy tampering |
| root version > MAX_ROOT_VERSION | REJECT; manual operator review required | BLOCKED | P1 — unexpected rotation |

## Scripts

- `scripts/verify_signature.py` — CLI entrypoint to verify a full skill-package signature chain, a container image, or a policy file. Returns structured JSON with {"valid": bool, "role": str, "errors": [...]}.

## Implementation Quality Bar

- Every verification path must be unit-tested with both valid and malicious (tampered) inputs.
- The hardcoded root key fingerprint must be a compile-time constant; runtime override is allowed ONLY via a second, already-trusted config signed by the root.
- All cryptographic operations use standard libraries: `tuf`, `securesystemslib`, `sigstore-python` or `cosign` CLI.
- Network fetches must enforce TLS 1.3 + certificate pinning for the TUF repo and Rekor endpoints.
- On any P0 failure, emit a structured security event to the incident-response channel and halt the calling workflow.
