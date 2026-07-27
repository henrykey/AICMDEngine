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

grep -F 'elif [ -n "${PIP_INDEX_URL}" ]; then' \
  "${ROOT_DIR}/Dockerfile.mcp-router" >/dev/null \
  || fail_test "mcp-router Dockerfile lacks configured-index fallback"
grep -F 'pip install -r requirements.txt' \
  "${ROOT_DIR}/Dockerfile.mcp-router.cn" >/dev/null \
  || fail_test "CN mcp-router Dockerfile lacks online fallback"
echo "PASS: wheelhouse cache and fallback contracts"
