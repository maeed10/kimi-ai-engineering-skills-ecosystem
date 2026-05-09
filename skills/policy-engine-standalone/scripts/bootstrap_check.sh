#!/usr/bin/env bash
# =============================================================================
# Policy Engine Bootstrap Readiness Check
# =============================================================================
# Usage:
#   ./bootstrap_check.sh [OPTIONS] <endpoint>
#
# Arguments:
#   endpoint    HTTP URL (http://host:port), host:port pair, or absolute
#               Unix socket path (e.g., /run/policy-engine.sock).
#
# Options:
#   -t, --timeout SECONDS     Max total wait time (default: 60)
#   -i, --interval SECONDS    Probe interval (default: 2)
#   -r, --retries N           Max retry attempts (default: 30)
#   -k, --insecure            Allow insecure HTTPS / skip TLS verify
#   -v, --verbose             Verbose output
#   -h, --help                Show this help
#
# Examples:
#   # Check TCP endpoint
#   ./bootstrap_check.sh policy-engine:8080
#
#   # Check Unix socket
#   ./bootstrap_check.sh /run/policy-engine.sock
#
#   # Kubernetes init container with 90s budget
#   ./bootstrap_check.sh -t 90 http://policy-engine:8080
#
# Exit Codes:
#   0  Policy engine is ready and serving.
#   1  Bad arguments or missing dependencies.
#   2  Policy engine not ready within timeout (or unreachable).
#   3  Policy engine ready but unexpected response structure.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
TIMEOUT=60
INTERVAL=2
RETRIES=30
INSECURE=0
VERBOSE=0
ENDPOINT=""

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log_info()  { echo "[INFO]  $*" >&2; }
log_warn()  { echo "[WARN]  $*" >&2; }
log_error() { echo "[ERROR] $*" >&2; }

usage() {
  sed -n '2,28p' "$0"
  exit 1
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    -i|--interval)
      INTERVAL="$2"
      shift 2
      ;;
    -r|--retries)
      RETRIES="$2"
      shift 2
      ;;
    -k|--insecure)
      INSECURE=1
      shift
      ;;
    -v|--verbose)
      VERBOSE=1
      shift
      ;;
    -h|--help)
      usage
      ;;
    -*)
      log_error "Unknown option: $1"
      exit 1
      ;;
    *)
      ENDPOINT="$1"
      shift
      ;;
  esac
done

if [[ -z "${ENDPOINT:-}" ]]; then
  log_error "Missing endpoint argument."
  usage
fi

# ---------------------------------------------------------------------------
# Resolve endpoint to a curl-ready URL
# ---------------------------------------------------------------------------
resolve_endpoint() {
  local ep="$1"

  # Absolute Unix socket path
  if [[ "$ep" == /* ]]; then
    if [[ ! -e "$ep" ]]; then
      log_error "Unix socket does not exist: $ep"
      return 1
    fi
    if [[ ! -S "$ep" ]]; then
      log_error "Path exists but is not a socket: $ep"
      return 1
    fi
    # curl via abstract Unix socket requires --unix-socket
    echo "unix://$ep"
    return 0
  fi

  # Already a URL scheme
  if [[ "$ep" == http://* || "$ep" == https://* ]]; then
    echo "$ep"
    return 0
  fi

  # host:port shorthand -> http://host:port
  if [[ "$ep" =~ ^[^:]+:[0-9]+$ ]]; then
    echo "http://$ep"
    return 0
  fi

  # host shorthand -> assume http://host:8080 (common default)
  echo "http://${ep}:8080"
}

BASE_URL=$(resolve_endpoint "$ENDPOINT") || exit 2

# ---------------------------------------------------------------------------
# Build curl flags
# ---------------------------------------------------------------------------
CURL_FLAGS=(
  --silent
  --show-error
  --fail
  --max-time 5
  --connect-timeout 3
  -H "Accept: application/json"
)

if [[ "$INSECURE" -eq 1 ]]; then
  CURL_FLAGS+=(--insecure)
fi

# Unix socket handling
if [[ "$BASE_URL" == unix://* ]]; then
  SOCK_PATH="${BASE_URL#unix://}"
  CURL_FLAGS+=(--unix-socket "$SOCK_PATH")
  HEALTH_URL="http://localhost/healthz"
  READY_URL="http://localhost/readyz"
else
  HEALTH_URL="${BASE_URL%/}/healthz"
  READY_URL="${BASE_URL%/}/readyz"
fi

[[ "$VERBOSE" -eq 1 ]] && log_info "health=$HEALTH_URL ready=$READY_URL"

# ---------------------------------------------------------------------------
# Probe functions
# ---------------------------------------------------------------------------
check_liveness() {
  local url="$1"
  local body
  local http_code

  body=$(curl "${CURL_FLAGS[@]}" "$url" 2>/dev/null) || return 1
  http_code=$(curl "${CURL_FLAGS[@]}" -o /dev/null -w "%{http_code}" "$url" 2>/dev/null) || return 1

  if [[ "$http_code" != "200" ]]; then
    return 1
  fi

  # Minimal validation: must be valid JSON with status field
  if ! echo "$body" | jq -e '.status' >/dev/null 2>&1; then
    log_warn "Liveness returned 200 but body missing 'status' field"
    return 1
  fi

  echo "$body"
  return 0
}

check_readiness() {
  local url="$1"
  local body
  local http_code

  body=$(curl "${CURL_FLAGS[@]}" "$url" 2>/dev/null) || return 1
  http_code=$(curl "${CURL_FLAGS[@]}" -o /dev/null -w "%{http_code}" "$url" 2>/dev/null) || return 1

  if [[ "$http_code" != "200" ]]; then
    return 1
  fi

  # Validate structure
  if ! echo "$body" | jq -e '.status' >/dev/null 2>&1; then
    log_warn "Readiness returned 200 but body missing 'status' field"
    return 3
  fi

  local status
  status=$(echo "$body" | jq -r '.status')
  if [[ "$status" != "ready" ]]; then
    return 1
  fi

  # Validate critical fields exist for a fully booted engine
  local rules_loaded
  rules_loaded=$(echo "$body" | jq -r '.rules_loaded // empty')
  if [[ -z "$rules_loaded" || "$rules_loaded" == "null" || "$rules_loaded" == "0" ]]; then
    log_warn "Readiness reports 'ready' but rules_loaded is missing or zero"
    return 3
  fi

  echo "$body"
  return 0
}

# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------
main() {
  local attempt=0
  local start_time
  start_time=$(date +%s)
  local liveness_body=""
  local readiness_body=""

  log_info "Probing policy engine at: $ENDPOINT"
  log_info "Timeout=${TIMEOUT}s Interval=${INTERVAL}s MaxRetries=${RETRIES}"

  while true; do
    local now
    now=$(date +%s)
    local elapsed=$((now - start_time))

    if [[ "$elapsed" -ge "$TIMEOUT" ]]; then
      log_error "Timeout reached after ${elapsed}s. Policy engine not ready."
      exit 2
    fi

    if [[ "$attempt" -ge "$RETRIES" ]]; then
      log_error "Max retries ($RETRIES) exhausted. Policy engine not ready."
      exit 2
    fi

    attempt=$((attempt + 1))

    # Check liveness first (lightweight)
    if liveness_body=$(check_liveness "$HEALTH_URL"); then
      [[ "$VERBOSE" -eq 1 ]] && log_info "Liveness OK (attempt $attempt)"
    else
      [[ "$VERBOSE" -eq 1 ]] && log_warn "Liveness failed (attempt $attempt)"
      sleep "$INTERVAL"
      continue
    fi

    # Check readiness (heavyweight / authoritative)
    if readiness_body=$(check_readiness "$READY_URL"); then
      log_info "Readiness OK after ${elapsed}s and $attempt attempt(s)."
      break
    else
      local rc=$?
      if [[ "$rc" -eq 3 ]]; then
        log_error "Readiness returned malformed/invalid ready state."
        exit 3
      fi
      [[ "$VERBOSE" -eq 1 ]] && log_warn "Readiness not yet OK (attempt $attempt)"
      sleep "$INTERVAL"
      continue
    fi
  done

  # -------------------------------------------------------------------------
  # Final validation and report
  # -------------------------------------------------------------------------
  local rules_loaded manifest_version
  rules_loaded=$(echo "$readiness_body" | jq -r '.rules_loaded // "unknown"')
  manifest_version=$(echo "$readiness_body" | jq -r '.manifest_version // "unknown"')

  log_info "Policy engine is READY."
  log_info "  Rules loaded: $rules_loaded"
  log_info "  Manifest version: $manifest_version"

  # Emit JSON for machine consumption (e.g., init container output parsing)
  echo "{\"ready\":true,\"rules_loaded\":$rules_loaded,\"manifest_version\":\"$manifest_version\",\"elapsed_seconds\":$elapsed}"

  exit 0
}

main "$@"
