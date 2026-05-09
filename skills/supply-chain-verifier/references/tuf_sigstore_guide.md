# TUF + Sigstore Integration Guide

## Scope

This document defines how TUF metadata and Sigstore/cosign signatures are combined to protect skill packages, container images, and configuration artifacts. It covers metadata schemas, delegation layout, Rekor integration, and offline/online trust boundaries.

## Metadata Layout

The TUF repository lives at a well-known origin, e.g. `https://tuf-repo.skills.internal/`. All metadata files are served with `Content-Type: application/json` and `Cache-Control: no-store` for root, targets, snapshot, and timestamp roles.

```
tuf-repo.skills.internal/
├── 1.root.json
├── 2.root.json           (current, MAX_ROOT_VERSION hardcoded in verifier)
├── targets.json
├── snapshot.json
├── timestamp.json
└── skills/
    ├── supply-chain-verifier-1.0.0.tar.gz
    ├── supply-chain-verifier-1.0.0.tar.gz.sig
    └── ...
```

## Role Delegation & Key Thresholds

| Role | Keys | Threshold | Key Storage | Rotation |
|------|------|-----------|-------------|----------|
| root | 5 | 3 | Offline HSM / YubiKey + Shamir backup | Manual ceremony |
| targets | 3 | 2 | HSM-backed, air-gapped signing workstation | Semi-annual or on compromise |
| snapshot | 1 | 1 | Online, automated CI | Auto every 7 days |
| timestamp | 1 | 1 | Online, automated CI | Auto every 7 days |

### targets.json Custom Schema

Each skill-package entry in `targets.json` carries:

```json
{
  "signed": {
    "targets": {
      "skills/supply-chain-verifier-1.0.0.tar.gz": {
        "length": 409600,
        "hashes": {
          "sha256": "abcdef123456..."
        },
        "custom": {
          "skill": {
            "name": "supply-chain-verifier",
            "version": "1.0.0",
            "api_version": "v2",
            "manifest_digest": "sha256:deadbeef..."
          },
          "signatures": [
            {
              "keyid": "release-key-a",
              "sig": "base64..."
            },
            {
              "keyid": "release-key-b",
              "sig": "base64..."
            }
          ],
          "sigstore": {
            "rekor_entry_uuid": "uuid...",
            "inclusion_proof": "base64...",
            "signed_timestamp": "2024-01-15T09:00:00Z"
          }
        }
      }
    }
  }
}
```

Rules:
- `custom.signatures` MUST contain at least 2 valid signatures from keys listed in the `targets` role.
- `custom.sigstore` is OPTIONAL for skill packages but REQUIRED for container images and SBOMs.
- `manifest_digest` is the SHA-256 of the inner `manifest.json` inside the tarball, allowing manifest-level integrity without extracting the whole archive.

## Sigstore / Cosign Integration

### Container Image Signing

Every sandbox-executor and dependency-resolver container image is signed at build time in CI:

```bash
cosign sign --key cosign-release.key \
  --rekor-url https://rekor.sigstore.dev \
  --predicate sbom.spdx.json \
  --type spdx \
  ghcr.io/skills/sandbox-executor@sha256:abcd...
```

Verification by the verifier script:

```bash
cosign verify --key cosign-pub.key \
  --rekor-url https://rekor.sigstore.dev \
  --signature-digest-algorithm sha256 \
  ghcr.io/skills/sandbox-executor@sha256:abcd...
```

### TUF ↔ Sigstore Bridge

TUF `targets.json` does not store raw Sigstore signatures for images. Instead it stores a **Rekor index pointer**:

```json
{
  "custom": {
    "sigstore": {
      "rekor_entry_uuid": "362f8ecba72bfe...",
      "inclusion_proof": "...",
      "signed_timestamp": "2024-01-15T09:00:00Z",
      "identity": "https://github.com/skills/builder/.github/workflows/release.yml@refs/heads/main"
    }
  }
}
```

The verifier:
1. Uses TUF to trust the Rekor index pointer.
2. Queries Rekor (or an offline mirror) for the entry.
3. Verifies the Rekor SET (Signed Entry Timestamp) with the Rekor public key.
4. Extracts the in-toto attestation / cosign signature from the entry.
5. Verifies the signature against the image digest.

This gives **two independent** trust paths:
- TUF (offline root) → targets → Rekor pointer.
- Sigstore (OIDC / Fulcio) → Rekor transparency log → signature.

Either path can detect compromise of the other.

## Offline / Online Trust Boundaries

```
┌─────────────────────────────────────────┐
│  OFFLINE ZONE (HSM, air-gapped)         │
│  • root keys (3-of-5)                   │
│  • targets keys (2-of-3)                │
│  • cosign release private key           │
│  • root key Shamir shards               │
└─────────────────────────────────────────┘
              │ signed metadata exported via QR / sneakernet
              ▼
┌─────────────────────────────────────────┐
│  ONLINE ZONE (CI, registry)             │
│  • snapshot / timestamp keys            │
│  • Rekor upload & query                 │
│  • OCI registry push / pull             │
│  • TUF repo serving                     │
└─────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│  RUNTIME ZONE (sandbox, skill-registry) │
│  • hardcoded root fingerprint           │
│  • TUF client fetching                  │
│  • cosign verify CLI / library          │
│  • no private keys ever                 │
└─────────────────────────────────────────┘
```

## Rekor Offline Cache

To reduce network dependency and latency, the verifier maintains a 7-day offline cache of Rekor inclusion proofs:

```
/var/cache/skills/rekor/
├── 362f8ecba72bfe...json      (Rekor entry + SET)
├── index.json                 (uuid → local filename)
└── checkpoint.json            (latest Rekor tree size + signed checkpoint)
```

Cache freshness is verified by comparing the cached entry's integrated time against a local trusted clock or RFC 3161 timestamp. If the cache is stale, the verifier performs a live Rekor lookup.

## Threat Model & Mitigations

| Threat | Mitigation |
|--------|------------|
| TUF repo compromise | Offline root keys (3-of-5) require physical collusion; snapshot/timestamp compromise alone cannot forge targets. |
| Release key theft | 2-of-3 threshold means 2 keys must be stolen; keys are HSM-backed with non-exportable private material. |
| Rekor log poisoning | Sigstore monitors detect anomalous entries; verifier checks identity string matches expected OIDC URI. |
| Freeze attack | timestamp.json enforces freshness; client aborts if local clock is > 1 day ahead/behind server time. |
| Rollback attack | snapshot.json version monotonicity enforced; old snapshots rejected. |
| Man-in-the-middle | TLS 1.3 + certificate pinning for TUF repo; Sigstore signatures are independent of TLS. |
| Build-system compromise | SBOM in-toto attestation binds image to build provenance; unexpected builder identity triggers P0 alert. |

## API / Data Format Summary

- TUF metadata: conforms to [TUF specification v1.0.32](https://theupdateframework.github.io/specification/latest/).
- Sigstore: [Sigstore specification](https://docs.sigstore.dev) with cosign OCI bundles.
- In-toto attestation: [in-toto.io/attestation](https://github.com/in-toto/attestation) v1.0, predicate type `https://in-toto.io/attestation/sbom` for SBOMs.
- Hash algorithms: SHA-256 minimum; SHA-512 accepted. No MD5, no SHA-1.
- Signature algorithms: Ed25519 (preferred), RSA-PSS with SHA-256 (legacy compat), ECDSA P-256 (cosign default).
