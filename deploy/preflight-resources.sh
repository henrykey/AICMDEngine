#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"
EXAMPLE_ENV_FILE="${SCRIPT_DIR}/env.aliyun.example"
CHECK_PORTS="${CHECK_PORTS:-true}"

readonly REQUIRED_PORT_VARS=(
  ROUTER_HOST_PORT
  PLAN2_HOST_PORT
  OFFICE_WORD_PROXY_PORT
  DOCS_CONVERTER_HOST_PORT
  PDF2MD_ENHANCED_HOST_PORT
  PAGEINDEX_HOST_PORT
)

readonly EXPECTED_ROUTER_HOST_PORT=8000
readonly EXPECTED_PLAN2_HOST_PORT=5122
readonly EXPECTED_OFFICE_WORD_PROXY_PORT=9002
readonly EXPECTED_DOCS_CONVERTER_HOST_PORT=9012
readonly EXPECTED_PDF2MD_ENHANCED_HOST_PORT=9010
readonly EXPECTED_PAGEINDEX_HOST_PORT=9011

readonly DEFAULT_ROUTER_HOST_PORT="${EXPECTED_ROUTER_HOST_PORT}"
readonly DEFAULT_PLAN2_HOST_PORT="${EXPECTED_PLAN2_HOST_PORT}"
readonly DEFAULT_OFFICE_WORD_PROXY_PORT="${EXPECTED_OFFICE_WORD_PROXY_PORT}"
readonly DEFAULT_DOCS_CONVERTER_HOST_PORT="${EXPECTED_DOCS_CONVERTER_HOST_PORT}"
readonly DEFAULT_PDF2MD_ENHANCED_HOST_PORT="${EXPECTED_PDF2MD_ENHANCED_HOST_PORT}"
readonly DEFAULT_PAGEINDEX_HOST_PORT="${EXPECTED_PAGEINDEX_HOST_PORT}"

log() {
  printf '[preflight] %s\n' "$*"
}

warn() {
  printf '[preflight][warn] %s\n' "$*" >&2
}

fail() {
  printf '[preflight][error] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  deploy/preflight-resources.sh [--env /path/to/.env] [--skip-ports]

Notes:
  - This script only checks local readiness and basic reachability.
  - It does not create resources and does not modify remote state.
  - Reserved ports are validated as fixed design constants.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env)
        shift
        [[ $# -gt 0 ]] || fail "--env requires a value"
        ENV_FILE="$1"
        ;;
      --skip-ports)
        CHECK_PORTS=false
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
    shift
  done
}

load_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    log "Loading environment from ${ENV_FILE}"
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
    return
  fi

  warn "Environment file not found: ${ENV_FILE}"
  if [[ -f "${EXAMPLE_ENV_FILE}" ]]; then
    log "Falling back to example env ${EXAMPLE_ENV_FILE}"
    set -a
    # shellcheck disable=SC1090
    source "${EXAMPLE_ENV_FILE}"
    set +a
    return
  fi

  fail "Neither ${ENV_FILE} nor ${EXAMPLE_ENV_FILE} exists"
}

apply_default_port_values() {
  ROUTER_HOST_PORT="${ROUTER_HOST_PORT:-${DEFAULT_ROUTER_HOST_PORT}}"
  PLAN2_HOST_PORT="${PLAN2_HOST_PORT:-${DEFAULT_PLAN2_HOST_PORT}}"
  OFFICE_WORD_PROXY_PORT="${OFFICE_WORD_PROXY_PORT:-${DEFAULT_OFFICE_WORD_PROXY_PORT}}"
  DOCS_CONVERTER_HOST_PORT="${DOCS_CONVERTER_HOST_PORT:-${DEFAULT_DOCS_CONVERTER_HOST_PORT}}"
  PDF2MD_ENHANCED_HOST_PORT="${PDF2MD_ENHANCED_HOST_PORT:-${DEFAULT_PDF2MD_ENHANCED_HOST_PORT}}"
  PAGEINDEX_HOST_PORT="${PAGEINDEX_HOST_PORT:-${DEFAULT_PAGEINDEX_HOST_PORT}}"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

check_required_commands() {
  local missing=()
  local cmd
  for cmd in bash python; do
    if ! command_exists "${cmd}"; then
      missing+=("${cmd}")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    fail "Missing required commands: ${missing[*]}"
  fi
}

check_required_vars() {
  local key
  for key in MEMBERSHIP_SERVICE_URL MONGODB_URI; do
    if [[ -z "${!key:-}" ]]; then
      fail "Required env var is empty: ${key}"
    fi
  done
}

check_reserved_port_values() {
  [[ "${ROUTER_HOST_PORT}" == "${EXPECTED_ROUTER_HOST_PORT}" ]] || fail "ROUTER_HOST_PORT must stay ${EXPECTED_ROUTER_HOST_PORT}"
  [[ "${PLAN2_HOST_PORT}" == "${EXPECTED_PLAN2_HOST_PORT}" ]] || fail "PLAN2_HOST_PORT must stay ${EXPECTED_PLAN2_HOST_PORT}"
  [[ "${OFFICE_WORD_PROXY_PORT}" == "${EXPECTED_OFFICE_WORD_PROXY_PORT}" ]] || fail "OFFICE_WORD_PROXY_PORT must stay ${EXPECTED_OFFICE_WORD_PROXY_PORT}"
  [[ "${DOCS_CONVERTER_HOST_PORT}" == "${EXPECTED_DOCS_CONVERTER_HOST_PORT}" ]] || fail "DOCS_CONVERTER_HOST_PORT must stay ${EXPECTED_DOCS_CONVERTER_HOST_PORT}"
  [[ "${PDF2MD_ENHANCED_HOST_PORT}" == "${EXPECTED_PDF2MD_ENHANCED_HOST_PORT}" ]] || fail "PDF2MD_ENHANCED_HOST_PORT must stay ${EXPECTED_PDF2MD_ENHANCED_HOST_PORT}"
  [[ "${PAGEINDEX_HOST_PORT}" == "${EXPECTED_PAGEINDEX_HOST_PORT}" ]] || fail "PAGEINDEX_HOST_PORT must stay ${EXPECTED_PAGEINDEX_HOST_PORT}"
  log "Reserved port values match the deployment design"
}

port_in_use() {
  local port="$1"

  if command_exists lsof; then
    lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi

  if command_exists nc; then
    nc -z 127.0.0.1 "${port}" >/dev/null 2>&1
    return
  fi

  python - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.3)
try:
    sock.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
else:
    sys.exit(0)
finally:
    sock.close()
PY
}

check_ports() {
  local key port
  for key in "${REQUIRED_PORT_VARS[@]}"; do
    port="${!key}"
    if port_in_use "${port}"; then
      fail "Port is already in use on local host: ${port} (${key})"
    fi
    log "Port is free: ${port} (${key})"
  done
}

check_membership_reachability() {
  if ! command_exists curl; then
    warn "curl not found; skipping Membership API reachability check"
    return
  fi

  if curl -fsS --max-time 5 "${MEMBERSHIP_SERVICE_URL}" >/dev/null 2>&1; then
    log "Membership service reachable: ${MEMBERSHIP_SERVICE_URL}"
    return
  fi

  warn "Membership service did not respond successfully: ${MEMBERSHIP_SERVICE_URL}"
}

check_mongodb_uri_shape() {
  if [[ "${MONGODB_URI}" =~ ^mongodb(\+srv)?:// ]]; then
    log "MongoDB URI format looks valid"
    return
  fi

  warn "MongoDB URI does not look like a standard mongodb URI: ${MONGODB_URI}"
}

check_bridge_hint() {
  local domain="${APP_PUBLIC_DOMAIN:-}"
  local plan2_port="${PLAN2_HOST_PORT:-5122}"

  if [[ -z "${domain}" ]]; then
    warn "APP_PUBLIC_DOMAIN not set; skipping bridge hint"
    return
  fi

  log "Bridge path to verify manually later: ${domain} -> aliapp:${plan2_port}"
}

check_artifacts() {
  local path
  for path in \
    "${ROOT_DIR}/Dockerfile.mcp-router" \
    "${ROOT_DIR}/plan2/Dockerfile" \
    "${ROOT_DIR}/mcp/proxy/requirements.txt" \
    "${SCRIPT_DIR}/docker-compose.mcp.yml" \
    "${SCRIPT_DIR}/plan2.config.aliyun.json" \
    "${SCRIPT_DIR}/mcp-proxy.service" \
    "${SCRIPT_DIR}/mcp-proxy-config.aliyun.yml"; do
    [[ -f "${path}" ]] || fail "Required file is missing: ${path}"
    log "Found ${path}"
  done
}

main() {
  parse_args "$@"
  check_required_commands
  load_env_file
  apply_default_port_values
  check_required_vars
  check_reserved_port_values
  check_artifacts
  if [[ "${CHECK_PORTS}" == "true" ]]; then
    check_ports
  else
    warn "Skipping local port conflict checks"
  fi
  check_mongodb_uri_shape
  check_membership_reachability
  check_bridge_hint
  log "Preflight completed"
}

main "$@"
