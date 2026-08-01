#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

# shellcheck source=../deploy.sh
source "${ROOT_DIR}/deploy/deploy.sh"

fail_test() {
  echo "FAIL: $*" >&2
  exit 1
}

docker() {
  if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
    return 0
  fi
  if [[ "${1:-}" == "run" ]]; then
    if [[ "${TEST_DOCKER_MODE:-}" == "download_fail" ]]; then
      return 1
    fi
    if [[ "${TEST_DOCKER_MODE:-}" == "download" ]]; then
      local mount_spec="" mount_source=""
      while [[ "$#" -gt 0 ]]; do
        if [[ "$1" == "-v" ]]; then
          shift
          case "${1:-}" in
            *:/wheelhouse) mount_spec="$1" ;;
          esac
        fi
        shift || true
      done
      mount_source="${mount_spec%:/wheelhouse}"
      printf '%s\n' "${mount_source}" > "${TEST_DIR}/download-mount-source"
      [[ -f "${TEST_DOWNLOAD_OUTPUT_DIR}/existing.whl" ]] \
        && : > "${TEST_DIR}/existing-cache-survived-download"
      printf 'new wheel\n' > "${mount_source}/httpx-0.28.1-py3-none-any.whl"
      return 0
    fi
    [[ "${TEST_WHEELHOUSE_COMPLETE:-false}" == "true" ]]
    return
  fi
  return 1
}

BUILD_PLATFORM="linux/amd64"

resolved_basin_backend="$(resolve_basin_comparator_backend_dir)"
expected_basin_backend="$(cd -P "${ROOT_DIR}/../membership/basin-comparator/backend" && pwd)"
[[ "${resolved_basin_backend}" == "${expected_basin_backend}" ]] \
  || fail_test "Basin backend did not resolve across the Membership AIPlanner symlink"

mkdir -p "${TEST_DIR}/source" "${TEST_DIR}/wheels"
printf 'PyYAML==6.0.2\n' > "${TEST_DIR}/source/requirements.txt"
printf 'wheel\n' > "${TEST_DIR}/wheels/PyYAML-6.0.2-py3-none-any.whl"
requirements_fingerprint "${TEST_DIR}/source" requirements.txt \
  > "${TEST_DIR}/wheels/.requirements.sha256"

TEST_WHEELHOUSE_COMPLETE=true
wheelhouse_is_complete python:3.11-slim "${TEST_DIR}/source" requirements.txt \
  "${TEST_DIR}/wheels" || fail_test "complete matching wheelhouse was not reused"

TEST_WHEELHOUSE_COMPLETE=false
if wheelhouse_is_complete python:3.11-slim "${TEST_DIR}/source" requirements.txt \
  "${TEST_DIR}/wheels"; then
  fail_test "wheelhouse with a missing declared dependency was accepted"
fi

TEST_WHEELHOUSE_COMPLETE=true
printf 'PyYAML==6.0.3\n' > "${TEST_DIR}/source/requirements.txt"
if wheelhouse_is_complete python:3.11-slim "${TEST_DIR}/source" requirements.txt \
  "${TEST_DIR}/wheels"; then
  fail_test "wheelhouse with a stale requirements fingerprint was accepted"
fi

BUILD_PLATFORM_ARG="linux/amd64"
apply_env_defaults
[[ "${WHEEL_CACHE_DIR}" == "${CACHE_DIR}/wheels/linux-amd64" ]] \
  || fail_test "linux/amd64 wheelhouse cache is not platform-isolated"
BUILD_PLATFORM_ARG="linux/arm64"
apply_env_defaults
[[ "${WHEEL_CACHE_DIR}" == "${CACHE_DIR}/wheels/linux-arm64" ]] \
  || fail_test "linux/arm64 wheelhouse cache is not platform-isolated"

TEST_DOWNLOAD_OUTPUT_DIR="${TEST_DIR}/download-output"
mkdir -p "${TEST_DOWNLOAD_OUTPUT_DIR}"
printf 'existing wheel\n' > "${TEST_DOWNLOAD_OUTPUT_DIR}/existing.whl"
TEST_DOCKER_MODE=download
LOCAL_PIP_INDEX_URL=""
BUILD_PLATFORM="linux/amd64"
download_wheelhouse python:3.11-slim "${TEST_DIR}/source" requirements.txt \
  "${TEST_DOWNLOAD_OUTPUT_DIR}"
unset TEST_DOCKER_MODE
download_mount_source="$(<"${TEST_DIR}/download-mount-source")"
[[ "${download_mount_source}" != "${TEST_DOWNLOAD_OUTPUT_DIR}" ]] \
  || fail_test "wheelhouse download writes directly into the live cache"
[[ -f "${TEST_DIR}/existing-cache-survived-download" ]] \
  || fail_test "live wheelhouse was cleared before replacement was ready"
[[ -f "${TEST_DOWNLOAD_OUTPUT_DIR}/httpx-0.28.1-py3-none-any.whl" ]] \
  || fail_test "completed staged wheelhouse was not promoted"
[[ ! -f "${TEST_DOWNLOAD_OUTPUT_DIR}/existing.whl" ]] \
  || fail_test "old wheelhouse contents survived successful replacement"
[[ -f "${TEST_DOWNLOAD_OUTPUT_DIR}/.requirements.sha256" ]] \
  || fail_test "promoted wheelhouse is missing its requirements fingerprint"

printf 'known good wheel\n' > "${TEST_DOWNLOAD_OUTPUT_DIR}/known-good.whl"
TEST_DOCKER_MODE=download_fail
if download_wheelhouse python:3.11-slim "${TEST_DIR}/source" requirements.txt \
  "${TEST_DOWNLOAD_OUTPUT_DIR}"; then
  fail_test "failed wheelhouse download unexpectedly succeeded"
fi
unset TEST_DOCKER_MODE
[[ -f "${TEST_DOWNLOAD_OUTPUT_DIR}/known-good.whl" ]] \
  || fail_test "failed wheelhouse download destroyed the live cache"

grep -F 'elif [ -n "${PIP_INDEX_URL}" ]; then' \
  "${ROOT_DIR}/Dockerfile.mcp-router" >/dev/null \
  || fail_test "mcp-router Dockerfile lacks configured-index fallback"
grep -F 'pip install -r requirements.txt' \
  "${ROOT_DIR}/Dockerfile.mcp-router.cn" >/dev/null \
  || fail_test "CN mcp-router Dockerfile lacks online fallback"
echo "PASS: wheelhouse cache and fallback contracts"
