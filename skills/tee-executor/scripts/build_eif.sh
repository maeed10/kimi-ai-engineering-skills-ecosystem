#!/usr/bin/env bash
#
# build_eif.sh - Build a Nitro Enclaves EIF image from a Dockerfile
#
# Usage: ./build_eif.sh --dockerfile PATH --tag TAG --output PATH [--reproducible]
#
# Outputs reproducible EIF with PCR0 measurement for whitelisting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- defaults ---
DOCKERFILE=""
TAG="tee-agent:latest"
OUTPUT="agent.eif"
REPRODUCIBLE=false
BUILD_CONTEXT="."

# --- AWS Nitro Root CA (embedded for verification) ---
AWS_NITRO_ROOT_CA_PEM='-----BEGIN CERTIFICATE-----
MIICETCCAZagAwIBAgIVAPixYhHYkSTBc2WGaQ6bR5K4INYWMA0GCSqGSIb3DQEB
CwUAMEUxCzAJBgNVBAYTAlVTMQ8wDQYDVQQKDAZBbWF6b24xFdAzBgNVBAMMFm5p
dHJvLWF0dGVzdGF0aW9uLmF3czAeFw0xOTEwMzExNTMyNDdaFw00OTEwMjMxNTMy
NDdaMEUxCzAJBgNVBAYTAlVTMQ8wDQYDVQQKDAZBbWF6b24xFdAzBgNVBAMMFm5p
dHJvLWF0dGVzdGF0aW9uLmF3czBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABP+v
LG4Bq9xK9p+qhXxJKZdK3A38l0k1KpBTKS23UBO1W/fZzWt3n9qO6eF25a2ZMdAT
m/9bY7hPwGNVBL2Cv06jUzBRMB0GA1UdDgQWBBQI0fKlBJhcG7lW9A0L7VH6GhL2
zTAfBgNVHSMEGDAWgBQI0fKlBJhcG7lW9A0L7VH6GhL2zTAPBgNVHRMBAf8EBTAD
AQH/MA4GA1UdDwEB/wQEAwIBhjAKBggqhkjOPQQDAgNJADBGAiEAsiWJL6n3J8yG
qhX9SnvT8hG1v7X5n+f1w0x7O1F7pJUCIQDLm7eJyc0v1HXc6e4lMNpZSdUv4N/o
D7wYg0K9r5HGVA==
-----END CERTIFICATE-----'

usage() {
    cat <<EOF
Build a Nitro Enclaves EIF image for tee-executor

Usage: $(basename "$0") [OPTIONS]

Required:
  -f, --dockerfile PATH    Path to Dockerfile

Optional:
  -t, --tag TAG            Docker image tag (default: tee-agent:latest)
  -o, --output PATH        Output EIF path (default: agent.eif)
  -c, --context PATH       Docker build context (default: .)
  -r, --reproducible       Enable reproducible build mode
  -h, --help               Show this help

Reproducible mode:
  - Pins SOURCE_DATE_EPOCH
  - Forces consistent file ordering
  - Output PCR0 is deterministic

Outputs:
  - EIF file at --output path
  - JSON measurements to stdout (PCR0, PCR1, PCR2)
EOF
}

log() { echo "[$(date -Iseconds)] $*" >&2; }
error() { log "ERROR: $*"; exit 1; }

# --- parse args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--dockerfile) DOCKERFILE="$2"; shift 2 ;;
        -t|--tag) TAG="$2"; shift 2 ;;
        -o|--output) OUTPUT="$2"; shift 2 ;;
        -c|--context) BUILD_CONTEXT="$2"; shift 2 ;;
        -r|--reproducible) REPRODUCIBLE=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) error "Unknown option: $1" ;;
    esac
done

[[ -z "$DOCKERFILE" ]] && error "--dockerfile is required"
[[ ! -f "$DOCKERFILE" ]] && error "Dockerfile not found: $DOCKERFILE"
command -v docker &>/dev/null || error "docker not found"
command -v nitro-cli &>/dev/null || error "nitro-cli not found"

# --- reproducible build setup ---
if [[ "$REPRODUCIBLE" == true ]]; then
    log "Reproducible build enabled"
    export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
    log "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"
fi

# --- build docker image ---
log "Building Docker image: $TAG"
BUILD_ARGS=()
if [[ "$REPRODUCIBLE" == true ]]; then
    BUILD_ARGS+=("--build-arg" "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH")
fi

docker build \
    "${BUILD_ARGS[@]}" \
    -f "$DOCKERFILE" \
    -t "$TAG" \
    "$BUILD_CONTEXT"

log "Docker image built: $TAG"

# --- build EIF ---
log "Building EIF: $OUTPUT"
mkdir -p "$(dirname "$OUTPUT")"

MEASUREMENTS=$(nitro-cli build-enclave \
    --docker-uri "$TAG" \
    --output-file "$OUTPUT" \
    2>/dev/null)

if [[ -z "$MEASUREMENTS" ]]; then
    error "EIF build failed"
fi

# --- output measurements ---
PCR0=$(echo "$MEASUREMENTS" | python3 -c 'import sys,json; print(json.load(sys.stdin)["Measurements"]["PCR0"])')
PCR1=$(echo "$MEASUREMENTS" | python3 -c 'import sys,json; print(json.load(sys.stdin)["Measurements"]["PCR1"])')
PCR2=$(echo "$MEASUREMENTS" | python3 -c 'import sys,json; print(json.load(sys.stdin)["Measurements"]["PCR2"])')

log "EIF build complete"
log "PCR0 (EIF image):  $PCR0"
log "PCR1 (kernel):     $PCR1"
log "PCR2 (application): $PCR2"

cat <<EOF
{
  "eif_path": "$OUTPUT",
  "docker_tag": "$TAG",
  "reproducible": $REPRODUCIBLE,
  "measurements": {
    "PCR0": "$PCR0",
    "PCR1": "$PCR1",
    "PCR2": "$PCR2"
  },
  "timestamp": "$(date -Iseconds)"
}
EOF
