#!/usr/bin/env bash
# policy-engine-wrapper.sh — External integrity verifier for policy-engine-server.py
# Kimi AI Engineering Skills Ecosystem v4.2.1
#
# This wrapper runs OUTSIDE the Python process to verify the policy engine script's
# SHA-256 hash before execution. It addresses the self-integrity paradox: the code
# that checks the hash must not be inside the file being checked.
#
# Usage:
#   ./policy-engine-wrapper.sh [arguments forwarded to policy-engine-server.py]
#
# Exit codes:
#   0 — Hash verified, daemon started normally
#   1 — Hash mismatch or manifest missing (daemon blocked)
#   2 — Python not found

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_PATH="${SCRIPT_DIR}/../policy/manifest.json"
SCRIPT_PATH="${SCRIPT_DIR}/policy-engine-server.py"

# --- Validate prerequisites ---
if [[ ! -f "$SCRIPT_PATH" ]]; then
    echo "FATAL: policy-engine-server.py not found at $SCRIPT_PATH" >&2
    exit 1
fi

if [[ ! -f "$MANIFEST_PATH" ]]; then
    echo "FATAL: manifest.json not found at $MANIFEST_PATH" >&2
    exit 1
fi

# --- Compute SHA-256 of the script ---
ACTUAL_HASH=$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')

# --- Read expected hash from manifest ---
EXPECTED_HASH=$(python3 -c "
import json, sys
try:
    with open('$MANIFEST_PATH') as f:
        m = json.load(f)
    print(m.get('self_integrity', {}).get('sha256', ''))
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    sys.exit(1)
")

if [[ -z "$EXPECTED_HASH" ]]; then
    echo "WARNING: No self_integrity hash in manifest. Custodian check disabled." >&2
elif [[ "$EXPECTED_HASH" != "$ACTUAL_HASH" ]]; then
    echo "======================================================================" >&2
    echo "SELF-INTEGRITY CHECK FAILED" >&2
    echo "======================================================================" >&2
    echo "Expected: $EXPECTED_HASH" >&2
    echo "Actual:   $ACTUAL_HASH" >&2
    echo "" >&2
    echo "The policy engine script may have been tampered with." >&2
    echo "Reinstall from a trusted source." >&2
    echo "======================================================================" >&2
    exit 1
else
    echo "Self-integrity check passed (${ACTUAL_HASH:0:16}...)."
fi

# --- Start the daemon ---
if ! command -v python3 &> /dev/null; then
    echo "FATAL: python3 not found in PATH" >&2
    exit 2
fi

exec python3 "$SCRIPT_PATH" "$@"
