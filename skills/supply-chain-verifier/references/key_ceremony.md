# Key Ceremony & Threshold Signing Procedures

## Scope

This document describes the complete lifecycle of cryptographic keys used by the supply-chain verifier: root-key generation, release-key provisioning, threshold-signing ceremonies, and scheduled/compromise-driven rotation. All ceremonies assume an air-gapped environment with no network connectivity.

## Participants

| Role | Count | Responsibility |
|------|-------|----------------|
| Key Custodian | 5 | Each holds one root key shard (HSM + paper backup). |
| Release Signer | 3 | Each holds one targets/release signing key (HSM). |
| Ceremony Coordinator | 1 | Orchestrates the ceremony, validates quorum, publishes metadata. |
| Witness | 2 | Independent observers who audit ceremony logs and checksums. |

## Pre-Ceremony Checklist

- [ ] Air-gapped room with Faraday cage or RF shielding.
- [ ] HSM initialization laptops booted from known-good live USB (Ubuntu LTS, SHA-256 verified).
- [ ] 5x YubiKey 5 NFC (or equivalent FIPS-140-2 L2 HSM) for root keys.
- [ ] 3x YubiKey 5 NFC for targets/release keys.
- [ ] Printed Shamir mnemonic cards (2-of-5 scheme) for root key backup.
- [ ] Tamper-evident bags and serial-number logging sheets.
- [ ] Ceremony logbook (paper) + digital video recording (local storage only).

---

## 1. Root Key Generation Ceremony

### 1.1 Generate the Master Root Key

On the air-gapped signing workstation:

```bash
# Generate Ed25519 master key inside an encrypted volume
openssl genpkey -algorithm Ed25519 -out root_master.pem -aes256
# The passphrase is a 128-bit diceware passphrase, split via Shamir
```

### 1.2 Split into 5-of-3 Shamir Shares

```bash
# Using ssss (Shamir Secret Sharing Scheme)
ssss-split -t 3 -n 5 < root_master_passphrase.txt > shares.txt
```

This yields 5 shares. Any 3 can reconstruct the passphrase. Shares are printed on paper, placed in tamper-evident envelopes, and distributed to distinct physical vaults.

### 1.3 Generate Individual HSM-Backed Root Keys

Each of the 5 Key Custodians performs:

```bash
# Generate a unique Ed25519 key on the HSM
yubico-piv-tool -s 9c -a generate -A ED25519 -o "custodian_${N}_pub.pem"
# Self-sign an attestation certificate
yubico-piv-tool -s 9c -a verify -a selfsign \
  -S "/CN=RootCustodian${N}/O=SkillsRegistry/OU=SupplyChain" \
  -i "custodian_${N}_pub.pem" -o "custodian_${N}_cert.pem"
```

The public keys and certificates are exported via QR code scan (no USB, no network) and assembled into the first `root.json`.

### 1.4 Assemble root.json (Version 1)

```json
{
  "signed": {
    "_type": "root",
    "spec_version": "1.0.32",
    "version": 1,
    "expires": "2030-01-01T00:00:00Z",
    "keys": {
      "custodian_1_keyid": {"keytype": "ed25519", "scheme": "ed25519", "keyval": {"public": "base64..."}},
      "custodian_2_keyid": {"keytype": "ed25519", "scheme": "ed25519", "keyval": {"public": "base64..."}},
      "...": "..."
    },
    "roles": {
      "root": {
        "keyids": ["custodian_1_keyid", "custodian_2_keyid", "custodian_3_keyid", "custodian_4_keyid", "custodian_5_keyid"],
        "threshold": 3
      },
      "targets": {
        "keyids": ["release_1_keyid", "release_2_keyid", "release_3_keyid"],
        "threshold": 2
      },
      "snapshot": {
        "keyids": ["snapshot_1_keyid"],
        "threshold": 1
      },
      "timestamp": {
        "keyids": ["timestamp_1_keyid"],
        "threshold": 1
      }
    },
    "consistent_snapshot": true
  },
  "signatures": [
    {"keyid": "custodian_1_keyid", "sig": "..."},
    {"keyid": "custodian_2_keyid", "sig": "..."},
    {"keyid": "custodian_3_keyid", "sig": "..."}
  ]
}
```

Rules:
- Exactly 3 signatures required on version 1 root.json (meets threshold).
- `expires` is set to 5 years from generation.
- `consistent_snapshot` is `true` to prevent mix-and-match attacks.

---

## 2. Targets / Release Key Generation (2-of-3)

The 3 Release Signers repeat the HSM procedure on their own air-gapped laptops. Their public keys are recorded in `root.json` under the `targets` role.

Each Release Signer also generates a cosign key pair for container-image signing:

```bash
cosign generate-key-pair --output-key-prefix release_${N}
# Private key is encrypted with a diceware passphrase and stored on the HSM-backed laptop
# Public key is exported to the TUF repo and CI system
```

---

## 3. Threshold Signing Workflow (Normal Release)

When a new skill package or container image is ready for release:

### Step A: Prepare the targets Metadata

The CI system (online) produces an unsigned `targets.json` update with the new artifact hashes.

### Step B: Export to Air-Gap

The unsigned `targets.json` is exported via QR code / optical scan to the signing workstation.

### Step C: Collect Signatures (2-of-3)

Release Signer 1 inserts HSM and signs:

```bash
python -m tuf.repository_tool \
  --repository /airgap/tuf-repo \
  --role targets \
  --key release_1_keyid \
  sign-targets
```

Release Signer 2 repeats on a separate workstation.

### Step D: Import Signed Metadata

The signed `targets.json` (now bearing 2 signatures) is imported back into the online CI system. CI adds snapshot and timestamp signatures, then publishes to the TUF repository.

---

## 4. Root Key Rotation Ceremony

Root keys MUST be rotated:
- **Scheduled:** Every 2 years, or before the `expires` date.
- **Emergency:** Within 48 hours of any suspected key compromise.

### 4.1 Scheduled Rotation

1. Coordinator schedules ceremony 90 days in advance.
2. At least 3 Key Custodians attend physically.
3. New HSM keys are generated; new `root.json` (version N+1) is assembled.
4. The new root.json is signed by the **old** root threshold (3-of-5 old keys). This proves continuity of trust.
5. New root.json also contains updated `keys` and `roles` for all delegated roles.
6. Old root.json is retained online for 2 update cycles to allow staggered client upgrades.
7. The hardcoded `MAX_ROOT_VERSION` in the verifier binary is incremented and released.

### 4.2 Emergency Rotation (Compromise Response)

1. **Immediate freeze:** The Coordinator publishes a new `timestamp.json` with an empty snapshot, halting all updates.
2. **Incident commander** declares P0 and convenes an emergency ceremony within 48 hours.
3. **Assume compromise** of the online snapshot/timestamp keys. These are revoked in the new `root.json`.
4. If a **targets/release key** is suspected compromised, its keyid is removed and threshold is temporarily raised to 3-of-3 for one cycle.
5. If a **root key** is suspected compromised, the remaining 4 custodians meet and rotate all 5 keys (complete key ceremony §1).
6. New `root.json` (version N+1) is signed by the maximum available old keys (even if below threshold, documented as "emergency override" in ceremony log).
7. All clients with the old hardcoded root must receive an out-of-band trusted update path (e.g., signed email + manual verification).

---

## 5. Key Storage & Backup Requirements

| Key Type | Primary Storage | Backup | Recovery Time Objective |
|----------|----------------|--------|------------------------|
| Root HSM | YubiKey 5 in physical safe | Shamir paper shares (2-of-5) in distinct vaults | 72 hours |
| Release HSM | YubiKey 5 in team safe | Encrypted USB in secondary site | 24 hours |
| Snapshot/Timestamp | Online CI HSM (AWS CloudHSM / GCP HSM) | Offline CI replica | 4 hours |
| Cosign release key | HSM-backed laptop | passphrase-encrypted USB in safe | 24 hours |

---

## 6. Ceremony Audit Log

Every ceremony produces a permanent audit log:

```yaml
ceremony_id: root-gen-2024-001
ceremony_type: root_key_generation
date: 2024-01-15T09:00:00Z
location: SecureRoom-A
participants:
  - name: Alice
    role: KeyCustodian-1
    hsm_serial: YK-12345
  - name: Bob
    role: KeyCustodian-2
    hsm_serial: YK-12346
  - name: Charlie
    role: CeremonyCoordinator
  - name: Dave
    role: Witness
  - name: Eve
    role: Witness
actions:
  - time: 09:15Z
    action: hsm_generate
    custodian: 1
    public_key_fingerprint: "sha256:abc..."
  - time: 09:22Z
    action: shamir_split
    threshold: 3
    shares: 5
  - time: 10:00Z
    action: root_json_assembled
    version: 1
    signatures_collected: 3
    keyids_signed: ["custodian_1", "custodian_2", "custodian_3"]
  - time: 10:30Z
    action: metadata_published
    checksum_sha256: "def..."
witness_signatures:
  - Dave: "sha256:wit1..."
  - Eve: "sha256:wit2..."
```

The audit log is itself signed by the Coordinator and both Witnesses, then stored in the TUF repo under `ceremony-logs/`.
