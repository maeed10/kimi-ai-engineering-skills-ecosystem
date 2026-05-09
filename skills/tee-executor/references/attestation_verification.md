# Attestation Verification Procedure

Complete specification for verifying TEE attestation documents before secret provisioning.

## Table of Contents
1. [Overview](#overview)
2. [Nitro Enclaves Attestation](#nitro-enclaves-attestation)
3. [Intel SGX Attestation](#intel-sgx-attestation)
4. [Verification Procedure](#verification-procedure)
5. [Failure Handling](#failure-handling)
6. [Policy Configuration](#policy-configuration)

## Overview

Attestation is a cryptographic proof that:
1. The code is running inside genuine TEE hardware (signed by AWS/Intel)
2. The code has not been tampered with (PCR/MRENCLAVE matches)
3. The attestation is fresh (not replayed)
4. The user data matches expectations (binding to specific execution)

**Rule: No secrets are provisioned until all attestation checks pass.**

## Nitro Enclaves Attestation

### Attestation Document Format

The attestation document is a COSE (CBOR Object Signing and Encryption) signed structure.

```json
{
  "module_id": "i-0abcd1234-enc0123456789abcdef0",
  "timestamp": "2024-01-15T09:30:00Z",
  "digest": "SHA384",
  "certificate": "-----BEGIN CERTIFICATE-----\n...",
  "cabundle": [
    "-----BEGIN CERTIFICATE-----\n...",
    "-----BEGIN CERTIFICATE-----\n..."
  ],
  "pcrs": {
    "0": "BASE64_ENCODED_SHA384_HASH",
    "1": "BASE64_ENCODED_SHA384_HASH",
    "2": "BASE64_ENCODED_SHA384_HASH",
    "8": "BASE64_ENCODED_SHA384_HASH"
  },
  "user_data": "BASE64_ENCODED_USER_DATA"
}
```

### PCR Register Meanings

| PCR | Content | Example Value | Verified? |
|-----|---------|---------------|-----------|
| PCR0 | EIF image measurement (SHA384) | Reproducible per build | **Yes** — must match whitelist |
| PCR1 | Kernel configuration hash | Stable per kernel | **Yes** — must match whitelist |
| PCR2 | Application + cmdline hash | Changes with code | **Yes** — must match whitelist |
| PCR3 | IAM role credential hash | Per-session | Optional — session binding |
| PCR4 | Instance ID hash | Per-instance | Optional — instance binding |
| PCR8 | Enclave image file hash | Per-EIF | Optional — file integrity |

### Requesting Attestation

Inside the enclave:
```python
import nsm_lib  # NSM (Nitro Secure Module) library

def get_attestation_document(user_data: bytes) -> bytes:
    """
    Request attestation document from NSM.
    user_data: binds this attestation to specific context (e.g., session ID)
    """
    nsm = nsm_lib.open_device()
    response = nsm_lib.attestation_request(
        nsm,
        user_data=user_data,
        nonce=os.urandom(32)  # prevent replay
    )
    nsm_lib.close_device(nsm)
    return response.document
```

The `nsm_lib` communicates with the Nitro Secure Module device at `/dev/nsm`.

## Intel SGX Attestation

### Quote Structure (DCAP)

```c
// SGX Quote v3 (ECDSA)
struct sgx_quote3 {
    uint16_t version;        // 0x0300 for ECDSA
    uint16_t att_key_type;   // 2 = ECDSA-256-with-P-256
    uint32_t tee_type;       // 0x00000000 = SGX
    uint16_t qe_svn;
    uint16_t pce_svn;
    uint8_t  uuid[16];       // QE vendor ID
    uint8_t  user_data[20];  // SHA256 of auth data
    // ... report body containing MRENCLAVE, MRSIGNER, ISVPRODID, ISVSVN
};
```

### Key Fields

| Field | Description | Verified? |
|-------|-------------|-----------|
| `MRENCLAVE` | SHA256 measurement of enclave code | **Yes** — must match whitelist |
| `MRSIGNER` | Public key hash of enclave signer | **Yes** — must match whitelist |
| `ISVPRODID` | Product ID | Optional |
| `ISVSVN` | Security version number | **Yes** — must be >= minimum |
| `REPORT_DATA` | 64 bytes of custom data | **Yes** — must match expected |

### Verification Path (DCAP)

```
Quote from enclave
    |
    v
QE Report signature verification
    |
    v
PCK certificate chain validation (Intel SGX PCK Processor CA)
    |
    v
TCB level check (CPUSVN >= required)
    |
    v
QvE (Quote Verification Enclave) or QVL (Quote Verification Library)
    |
    v
MRENCLAVE + MRSIGNER match whitelist
    |
    v
ISVSVN >= minimum version
    |
    v
REPORT_DATA matches expected
```

## Verification Procedure

### Step-by-Step: Nitro Enclaves

```python
def verify_nitro_attestation(
    document: bytes,
    expected_pcr0: str,
    expected_pcr1: str,
    expected_pcr2: str,
    expected_user_data: bytes,
    max_clock_skew_seconds: int = 300
) -> AttestationResult:
    """
    Full verification of a Nitro Enclaves attestation document.
    """
    # 1. Decode COSE Sign1 structure
    cose = decode_cose_sign1(document)

    # 2. Extract payload (CBOR-encoded attestation document)
    payload = cose.payload
    doc = cbor2.loads(payload)

    # 3. Verify AWS signature
    signing_cert = x509.load_pem_x509_certificate(doc['certificate'].encode())
    cabundle = [x509.load_pem_x509_certificate(c.encode()) for c in doc['cabundle']]

    # Build cert chain: signing_cert -> cabundle[0] -> cabundle[1] -> AWS root
    if not verify_cert_chain(signing_cert, cabundle, AWS_NITRO_ROOT_CA):
        return AttestationResult.FAILED_SIGNATURE

    # Verify COSE signature with signing cert's public key
    if not verify_cose_signature(cose, signing_cert.public_key()):
        return AttestationResult.FAILED_SIGNATURE

    # 4. Verify timestamp freshness
    attestation_time = datetime.fromisoformat(doc['timestamp'].replace('Z', '+00:00'))
    now = datetime.now(timezone.utc)
    skew = abs((now - attestation_time).total_seconds())
    if skew > max_clock_skew_seconds:
        return AttestationResult.FAILED_EXPIRED

    # 5. Verify PCR measurements
    pcrs = doc['pcrs']
    if base64.b64decode(pcrs['0']).hex() != expected_pcr0:
        return AttestationResult.FAILED_PCR_MISMATCH
    if base64.b64decode(pcrs['1']).hex() != expected_pcr1:
        return AttestationResult.FAILED_PCR_MISMATCH
    if base64.b64decode(pcrs['2']).hex() != expected_pcr2:
        return AttestationResult.FAILED_PCR_MISMATCH

    # 6. Verify user data binding
    if doc.get('user_data'):
        actual_user_data = base64.b64decode(doc['user_data'])
        if actual_user_data != expected_user_data:
            return AttestationResult.FAILED_USER_DATA

    # 7. Verify digest algorithm
    if doc.get('digest') != 'SHA384':
        return AttestationResult.FAILED_ALGORITHM

    return AttestationResult.SUCCESS
```

### Step-by-Step: Intel SGX (DCAP)

```python
def verify_sgx_attestation(
    quote: bytes,
    expected_mrenclave: str,
    expected_mrsigner: str,
    minimum_isvsvn: int,
    expected_report_data: bytes,
    dcap_collateral: DCAPCollateral
) -> AttestationResult:
    """
    Full verification of an Intel SGX ECDSA quote.
    """
    # 1. Parse quote structure
    parsed = parse_quote_v3(quote)

    # 2. Verify QE signature on the quote
    if not verify_quote_signature(parsed, dcap_collateral):
        return AttestationResult.FAILED_SIGNATURE

    # 3. Verify PCK certificate chain
    if not verify_pck_chain(parsed, dcap_collateral):
        return AttestationResult.FAILED_SIGNATURE

    # 4. Check TCB level
    if not check_tcb_level(parsed, dcap_collateral):
        return AttestationResult.FAILED_TCB_OUTDATED

    # 5. Verify MRENCLAVE
    if parsed.report_body.mrenclave.hex() != expected_mrenclave:
        return AttestationResult.FAILED_PCR_MISMATCH

    # 6. Verify MRSIGNER
    if parsed.report_body.mrsigner.hex() != expected_mrsigner:
        return AttestationResult.FAILED_PCR_MISMATCH

    # 7. Verify ISVSVN
    if parsed.report_body.isvsvn < minimum_isvsvn:
        return AttestationResult.FAILED_VERSION

    # 8. Verify REPORT_DATA
    if parsed.report_body.report_data[:len(expected_report_data)] != expected_report_data:
        return AttestationResult.FAILED_USER_DATA

    return AttestationResult.SUCCESS
```

## Failure Handling

### Failure Action Matrix

| Failure Reason | Action | Alert Level |
|----------------|--------|-------------|
| `FAILED_SIGNATURE` | Reject secrets, terminate enclave | **Critical** |
| `FAILED_EXPIRED` | Reject secrets, request fresh attestation | **Warning** |
| `FAILED_PCR_MISMATCH` | Reject secrets, terminate enclave, alert ops | **Critical** |
| `FAILED_USER_DATA` | Reject secrets, terminate enclave | **High** |
| `FAILED_TCB_OUTDATED` | Reject secrets, request TCB update | **Warning** |
| `FAILED_VERSION` | Reject secrets, require enclave update | **High** |
| `FAILED_ALGORITHM` | Reject secrets, terminate enclave | **Critical** |

### Critical vs Warning

**Critical (immediate security response):**
- Signature failure = possible spoofing attempt
- PCR mismatch = possible code tampering
- These are treated as active attacks

**Warning (operational issue):**
- Expired attestation = clock skew or stale request
- TCB outdated = needs software update
- These are treated as configuration issues

## Policy Configuration

### policy-engine Integration

The `policy-engine` provides per-policy attestation rules:

```yaml
# policy definition example
tee_attestation:
  backend: nitro
  pcr_whitelist:
    - pcr0: "a1b2c3d4..."  # production EIF v1.2.3
      pcr1: "e5f6g7h8..."
      pcr2: "i9j0k1l2..."
    - pcr0: "m3n4o5p6..."  # staging EIF
  max_clock_skew_seconds: 300
  require_user_data: true
  user_data_format: "session_id:sha256"
  minimum_isvsvn: 5  # SGX only
```

### User Data Format

User data binds the attestation to a specific execution context:

```
session_id=<uuid>&code_hash=<sha256>&timestamp=<iso8601>
```

Verification:
1. Parse user data from attestation document
2. Verify `session_id` matches the current session
3. Verify `code_hash` matches the code about to execute
4. Verify `timestamp` is within clock skew window

This prevents:
- Replay attacks (session_id is unique per execution)
- Code substitution (code_hash binds to specific code)
- Delayed attacks (timestamp limits attestation age)
