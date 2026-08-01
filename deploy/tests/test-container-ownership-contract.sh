#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="${ROOT_DIR}/deploy/deploy.sh"
COMPOSE="${ROOT_DIR}/deploy/docker-compose.mcp.yml"
EXTERNAL_MCPS="${ROOT_DIR}/deploy/config/external_mcps.yml"

fail_test() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -F 'if ! $SUDO docker container inspect "${container}"' "${SCRIPT}" >/dev/null \
  || fail_test "deployment does not restrict existence checks to containers"
grep -F 'owner_service="$($SUDO docker container inspect' "${SCRIPT}" >/dev/null \
  || fail_test "deployment does not inspect Compose service ownership"
grep -F 'owner_project="$($SUDO docker container inspect' "${SCRIPT}" >/dev/null \
  || fail_test "deployment does not inspect Compose project ownership"
grep -F 'actual_image="$($SUDO docker container inspect' "${SCRIPT}" >/dev/null \
  || fail_test "deployment does not inspect intended image identity"
grep -F 'Container name conflict is not owned by the intended service' \
  "${SCRIPT}" >/dev/null \
  || fail_test "unrelated same-name containers are not rejected"
grep -F '$SUDO docker rm -f "${container}"' "${SCRIPT}" >/dev/null \
  || fail_test "owned legacy containers are not removed"
grep -F -- '--project-name "${COMPOSE_PROJECT_NAME}"' "${SCRIPT}" >/dev/null \
  || fail_test "Compose project identity is not stable"
grep -F -- 'up -d --force-recreate ${SERVICES}' "${SCRIPT}" >/dev/null \
  || fail_test "selected services are not force-recreated"
sed -n '/^  mcp-router:/,/^  plan2:/p' "${COMPOSE}" \
  | grep -F -- 'host.docker.internal:host-gateway' >/dev/null \
  || fail_test "mcp-router cannot resolve host-proxied MCP services"
grep -F -- 'url: http://host.docker.internal:9002' "${EXTERNAL_MCPS}" >/dev/null \
  || fail_test "office-word does not target the host MCP proxy"
grep -F -- 'url: http://host.docker.internal:8139' "${EXTERNAL_MCPS}" >/dev/null \
  || fail_test "BasinComparator does not use an allowed host name"

echo "PASS: remote container ownership contract"
