#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${SCRIPT_DIR}/out"
CACHE_DIR="${SCRIPT_DIR}/cache"
WHEEL_CACHE_DIR="${CACHE_DIR}/wheels"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"
EXAMPLE_ENV_FILE="${SCRIPT_DIR}/env.aliyun.example"
REMOTE_DIR_DEFAULT="/opt/AICMDEngine"
ROUTER_HOST_PORT_DEFAULT="8000"
PLAN2_HOST_PORT_DEFAULT="5122"
OFFICE_WORD_PROXY_PORT_DEFAULT="9002"
PDF2MD_ENHANCED_HOST_PORT_DEFAULT="9010"
PAGEINDEX_HOST_PORT_DEFAULT="9011"
MCP_TRANSPORT_DEFAULT="stdio"
FASTMCP_LOG_LEVEL_DEFAULT="INFO"
REMOTE_PIP_INDEX_URL_DEFAULT="https://mirrors.aliyun.com/pypi/simple/"
LOCAL_PIP_INDEX_URL_DEFAULT=""
CACHE_PYTHON_311_IMAGE_DEFAULT="python:3.11-slim"
CACHE_PYTHON_312_IMAGE_DEFAULT="python:3.12-slim"
PLAN2_NODE_BASE_IMAGE_DEFAULT="node:20-alpine"
PLAN2_NGINX_BASE_IMAGE_DEFAULT="nginx:alpine"

ACTION="${1:-}"
if [[ -z "${ACTION}" || "${ACTION}" == --* ]]; then
  ACTION="all"
fi
BUILD_IMAGES=false
REFRESH_CACHE=false
WITH_PROXY=false
SKIP_PREFLIGHT=false
APP_HOST=""
REMOTE_DIR="${REMOTE_DIR_DEFAULT}"

readonly IMAGE_ARCHIVE_NAME="aiplanner-images.tar.gz"
readonly IMAGE_NAMES=(
  aiplanner-mcp-router:latest
  aiplanner-plan2:latest
  aiplanner-pdf2md-enhanced:latest
  aiplanner-pageindex:latest
)

log() {
  printf '[deploy] %s\n' "$*"
}

warn() {
  printf '[deploy][warn] %s\n' "$*" >&2
}

fail() {
  printf '[deploy][error] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  deploy/deploy.sh prepare-cache [--env-file PATH]
  deploy/deploy.sh prepare --env-file PATH --app-host HOST [--with-proxy] [--build-images] [--refresh-cache] [--skip-preflight]
  deploy/deploy.sh upload --env-file PATH --app-host HOST [--remote-dir DIR]
  deploy/deploy.sh deploy --env-file PATH --app-host HOST [--remote-dir DIR] [--with-proxy]
  deploy/deploy.sh all --env-file PATH --app-host HOST [--remote-dir DIR] [--with-proxy] [--build-images] [--refresh-cache] [--skip-preflight]

Environment:
  ENV_FILE=/path/to/.env   Backward-compatible override for deploy env file.

Notes:
  - Reserved ports are fixed by design and must not be changed.
  - `prepare-cache` downloads linux/amd64 Python wheels into deploy/cache/wheels.
  - `prepare` generates a remote-ready bundle under deploy/out.
  - `upload` syncs deploy/out to ${APP_HOST}:${REMOTE_DIR}.
  - `deploy` executes the remote install/start sequence on ${APP_HOST}.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      prepare-cache|prepare|upload|deploy|all)
        ACTION="$1"
        ;;
      --env-file)
        shift
        [[ $# -gt 0 ]] || fail "--env-file requires a value"
        ENV_FILE="$1"
        ;;
      --app-host)
        shift
        [[ $# -gt 0 ]] || fail "--app-host requires a value"
        APP_HOST="$1"
        ;;
      --remote-dir)
        shift
        [[ $# -gt 0 ]] || fail "--remote-dir requires a value"
        REMOTE_DIR="$1"
        ;;
      --build-images)
        BUILD_IMAGES=true
        ;;
      --with-proxy)
        WITH_PROXY=true
        ;;
      --refresh-cache)
        REFRESH_CACHE=true
        ;;
      --skip-preflight)
        SKIP_PREFLIGHT=true
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

source_env_file() {
  local source_file
  source_file="${ENV_FILE}"
  if [[ ! -f "${source_file}" ]]; then
    source_file="${EXAMPLE_ENV_FILE}"
    warn "Using example env because ${ENV_FILE} was not found"
  fi

  [[ -f "${source_file}" ]] || fail "No env file available"

  log "Loading environment from ${source_file}"
  set -a
  # shellcheck disable=SC1090
  source "${source_file}"
  set +a
}

apply_env_defaults() {
  ROUTER_HOST_PORT="${ROUTER_HOST_PORT:-${ROUTER_HOST_PORT_DEFAULT}}"
  PLAN2_HOST_PORT="${PLAN2_HOST_PORT:-${PLAN2_HOST_PORT_DEFAULT}}"
  OFFICE_WORD_PROXY_PORT="${OFFICE_WORD_PROXY_PORT:-${OFFICE_WORD_PROXY_PORT_DEFAULT}}"
  PDF2MD_ENHANCED_HOST_PORT="${PDF2MD_ENHANCED_HOST_PORT:-${PDF2MD_ENHANCED_HOST_PORT_DEFAULT}}"
  PAGEINDEX_HOST_PORT="${PAGEINDEX_HOST_PORT:-${PAGEINDEX_HOST_PORT_DEFAULT}}"
  MCP_TRANSPORT="${MCP_TRANSPORT:-${MCP_TRANSPORT_DEFAULT}}"
  FASTMCP_LOG_LEVEL="${FASTMCP_LOG_LEVEL:-${FASTMCP_LOG_LEVEL_DEFAULT}}"
  REMOTE_PIP_INDEX_URL="${REMOTE_PIP_INDEX_URL:-${REMOTE_PIP_INDEX_URL_DEFAULT}}"
  LOCAL_PIP_INDEX_URL="${LOCAL_PIP_INDEX_URL:-${LOCAL_PIP_INDEX_URL_DEFAULT}}"
  CACHE_PYTHON_311_IMAGE="${CACHE_PYTHON_311_IMAGE:-${CACHE_PYTHON_311_IMAGE_DEFAULT}}"
  CACHE_PYTHON_312_IMAGE="${CACHE_PYTHON_312_IMAGE:-${CACHE_PYTHON_312_IMAGE_DEFAULT}}"
  PLAN2_NODE_BASE_IMAGE="${PLAN2_NODE_BASE_IMAGE:-${PLAN2_NODE_BASE_IMAGE_DEFAULT}}"
  PLAN2_NGINX_BASE_IMAGE="${PLAN2_NGINX_BASE_IMAGE:-${PLAN2_NGINX_BASE_IMAGE_DEFAULT}}"
}

load_env_file() {
  source_env_file
  apply_env_defaults
  [[ -n "${APP_HOST}" ]] || fail "--app-host is required"
  PLAN2_PUBLIC_BASE_URL="http://${APP_HOST}:${PLAN2_HOST_PORT}"
  export REMOTE_DIR
  export ROUTER_HOST_PORT PLAN2_HOST_PORT OFFICE_WORD_PROXY_PORT
  export PDF2MD_ENHANCED_HOST_PORT PAGEINDEX_HOST_PORT PLAN2_PUBLIC_BASE_URL
  export MCP_TRANSPORT FASTMCP_LOG_LEVEL
  export REMOTE_PIP_INDEX_URL LOCAL_PIP_INDEX_URL
  export CACHE_PYTHON_311_IMAGE CACHE_PYTHON_312_IMAGE
  export PLAN2_NODE_BASE_IMAGE PLAN2_NGINX_BASE_IMAGE
  export WITH_PROXY
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

docker_image_exists() {
  docker image inspect "$1" >/dev/null 2>&1
}

normalize_proxy_url_for_container() {
  local value="$1"
  if [[ "${value}" =~ ^([a-zA-Z]+)://(127\.0\.0\.1|localhost)(:([0-9]+))?(.*)$ ]]; then
    printf '%s://host.docker.internal%s%s\n' \
      "${BASH_REMATCH[1]}" \
      "${BASH_REMATCH[3]:-}" \
      "${BASH_REMATCH[5]:-}"
    return
  fi
  printf '%s\n' "${value}"
}

proxy_env_args() {
  local args=()
  local value
  for key in HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
    if [[ -n "${!key:-}" ]]; then
      value="${!key}"
      if [[ "${key}" != "NO_PROXY" && "${key}" != "no_proxy" ]]; then
        value="$(normalize_proxy_url_for_container "${value}")"
      fi
      args+=(-e "${key}=${value}")
    fi
  done
  printf '%s\n' "${args[@]}"
}

ensure_out_layout() {
  mkdir -p \
    "${OUT_DIR}" \
    "${OUT_DIR}/data/pdf2md-enhanced/input" \
    "${OUT_DIR}/data/pdf2md-enhanced/output" \
    "${OUT_DIR}/plan2" \
    "${OUT_DIR}/images"

  if [[ "${WITH_PROXY}" == "true" ]]; then
    mkdir -p \
      "${OUT_DIR}/proxy/config" \
      "${OUT_DIR}/proxy/systemd" \
      "${OUT_DIR}/proxy/servers" \
      "${OUT_DIR}/proxy/wheels/core" \
      "${OUT_DIR}/proxy/wheels/office-word"
  fi
}

ensure_cache_layout() {
  mkdir -p \
    "${WHEEL_CACHE_DIR}/mcp-router" \
    "${WHEEL_CACHE_DIR}/pageindex" \
    "${WHEEL_CACHE_DIR}/pdf2md-enhanced" \
    "${WHEEL_CACHE_DIR}/proxy-core" \
    "${WHEEL_CACHE_DIR}/office-word" \
    "${ROOT_DIR}/.wheelhouse/mcp-router" \
    "${ROOT_DIR}/mcp/servers/PageIndex/.wheelhouse" \
    "${ROOT_DIR}/mcp/servers/PDF2MDEnhanced/.wheelhouse"
}

render_template() {
  local src="$1"
  local dest="$2"

  python - "$src" "$dest" <<'PY'
import os
import pathlib
import re
import sys

src = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
text = src.read_text()
pattern = re.compile(r"\$\{([A-Z0-9_]+)\}")
missing = sorted({name for name in pattern.findall(text) if name not in os.environ})
if missing:
    raise SystemExit(f"Missing environment variables for template rendering: {', '.join(missing)}")

rendered = pattern.sub(lambda m: os.environ[m.group(1)], text)
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_text(rendered)
PY
}

copy_tree_filtered() {
  local src="$1"
  local dest="$2"
  mkdir -p "${dest}"
  tar \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='.DS_Store' \
    --exclude='venv' \
    --exclude='.venv' \
    --exclude='node_modules' \
    -C "${src}" \
    -cf - . | tar -C "${dest}" -xf -
}

wheelhouse_has_files() {
  local dir="$1"
  [[ -d "${dir}" ]] || return 1
  find "${dir}" -type f ! -name '.gitkeep' | grep -q .
}

clear_dir_contents() {
  local dir="$1"
  mkdir -p "${dir}"
  find "${dir}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
}

download_wheelhouse() {
  local image="$1"
  local source_dir="$2"
  local requirements_rel="$3"
  local output_dir="$4"
  local extra_requirements="${5:-}"
  local pip_index_arg_string=""
  local -a docker_proxy_env=()
  local -a docker_host_args=()

  clear_dir_contents "${output_dir}"
  if [[ -n "${LOCAL_PIP_INDEX_URL}" ]]; then
    pip_index_arg_string="-i ${LOCAL_PIP_INDEX_URL}"
  fi
  while IFS= read -r line; do
    [[ -n "${line}" ]] && docker_proxy_env+=("${line}")
  done < <(proxy_env_args)
  if [[ "$(uname -s)" == "Linux" ]]; then
    docker_host_args=(--add-host host.docker.internal:host-gateway)
  fi

  docker run --rm --platform linux/amd64 \
    "${docker_host_args[@]}" \
    "${docker_proxy_env[@]}" \
    -v "${source_dir}:/workspace:ro" \
    -v "${output_dir}:/wheelhouse" \
    "${image}" \
    sh -lc "
      set -euo pipefail
      python -m pip install --upgrade pip >/dev/null
      python -m pip download --only-binary=:all: --dest /wheelhouse ${pip_index_arg_string} -r /workspace/${requirements_rel}
      if [ -n \"${extra_requirements}\" ]; then
        python -m pip download --only-binary=:all: --dest /wheelhouse ${pip_index_arg_string} ${extra_requirements}
      fi
    "
}

cache_base_images() {
  printf '%s\n' "${CACHE_PYTHON_311_IMAGE}" "${CACHE_PYTHON_312_IMAGE}"
}

sync_wheelhouse() {
  local src="$1"
  local dest="$2"
  clear_dir_contents "${dest}"
  mkdir -p "${dest}"
  if wheelhouse_has_files "${src}"; then
    cp -R "${src}/." "${dest}/"
  else
    : > "${dest}/.gitkeep"
  fi
}

ensure_cache_base_images() {
  command_exists docker || fail "docker is required for amd64 wheel cache preparation"

  local image attempt
  while IFS= read -r image; do
    if docker_image_exists "${image}"; then
      continue
    fi

    log "Pulling cache base image ${image}"
    for attempt in 1 2 3; do
      if docker pull --platform linux/amd64 "${image}"; then
        break
      fi
      if [[ "${attempt}" -eq 3 ]]; then
        fail "Failed to pull ${image} from Docker Hub after 3 attempts"
      fi
      warn "Pull failed for ${image}, retrying (${attempt}/3)"
      sleep 2
    done
  done < <(cache_base_images)
}

prepare_cache() {
  command_exists docker || fail "docker is required for prepare-cache"

  source_env_file
  apply_env_defaults
  ensure_cache_layout
  ensure_cache_base_images

  log "Preparing linux/amd64 wheelhouse cache"
  download_wheelhouse "${CACHE_PYTHON_311_IMAGE}" "${ROOT_DIR}" "requirements.txt" "${WHEEL_CACHE_DIR}/mcp-router"
  download_wheelhouse "${CACHE_PYTHON_312_IMAGE}" "${ROOT_DIR}/mcp/servers/PageIndex" "requirements.txt" "${WHEEL_CACHE_DIR}/pageindex"
  download_wheelhouse "${CACHE_PYTHON_312_IMAGE}" "${ROOT_DIR}/mcp/servers/PDF2MDEnhanced" "requirements.txt" "${WHEEL_CACHE_DIR}/pdf2md-enhanced"
  if [[ "${WITH_PROXY}" == "true" ]]; then
    download_wheelhouse "${CACHE_PYTHON_312_IMAGE}" "${ROOT_DIR}/mcp/proxy" "requirements.txt" "${WHEEL_CACHE_DIR}/proxy-core" "fastmcp"
    download_wheelhouse "${CACHE_PYTHON_312_IMAGE}" "${ROOT_DIR}/mcp/servers/office-word" "requirements.txt" "${WHEEL_CACHE_DIR}/office-word"
  fi

  sync_wheelhouse "${WHEEL_CACHE_DIR}/mcp-router" "${ROOT_DIR}/.wheelhouse/mcp-router"
  sync_wheelhouse "${WHEEL_CACHE_DIR}/pageindex" "${ROOT_DIR}/mcp/servers/PageIndex/.wheelhouse"
  sync_wheelhouse "${WHEEL_CACHE_DIR}/pdf2md-enhanced" "${ROOT_DIR}/mcp/servers/PDF2MDEnhanced/.wheelhouse"

  log "Prepared wheelhouse cache under ${WHEEL_CACHE_DIR}"
}

cache_is_ready() {
  wheelhouse_has_files "${WHEEL_CACHE_DIR}/mcp-router" &&
  wheelhouse_has_files "${WHEEL_CACHE_DIR}/pageindex" &&
  wheelhouse_has_files "${WHEEL_CACHE_DIR}/pdf2md-enhanced" || return 1

  if [[ "${WITH_PROXY}" == "true" ]]; then
    wheelhouse_has_files "${WHEEL_CACHE_DIR}/proxy-core" &&
    wheelhouse_has_files "${WHEEL_CACHE_DIR}/office-word"
  else
    return 0
  fi
}

ensure_cache_ready() {
  ensure_cache_layout
  if [[ "${REFRESH_CACHE}" == "true" ]]; then
    log "Refreshing linux/amd64 wheelhouse cache by request"
    prepare_cache
    return
  fi

  if cache_is_ready; then
    log "Using existing linux/amd64 wheelhouse cache"
    return
  fi

  log "linux/amd64 wheelhouse cache is missing; preparing automatically"
  prepare_cache
}

write_remote_compose() {
  python - "${SCRIPT_DIR}/docker-compose.mcp.yml" "${OUT_DIR}/docker-compose.mcp.yml" <<'PY'
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])
lines = src.read_text().splitlines()
out = []

in_build = False
build_indent = 0
in_pdf2md_volumes = False
pdf2md_volume_indent = 0
current_service = None

for line in lines:
    stripped = line.lstrip()
    indent = len(line) - len(stripped)

    if in_build:
        if stripped and indent > build_indent:
            continue
        in_build = False

    if in_pdf2md_volumes:
        if stripped and indent > pdf2md_volume_indent:
            continue
        in_pdf2md_volumes = False

    if indent == 2 and stripped.endswith(":") and not stripped.startswith("- "):
        current_service = stripped[:-1]

    if current_service and stripped == "build:":
        in_build = True
        build_indent = indent
        continue

    if current_service == "pdf2md-enhanced" and stripped == "volumes:":
        in_pdf2md_volumes = True
        pdf2md_volume_indent = indent
        out.append(line)
        out.append("      - ./data/pdf2md-enhanced/input:/app/data/input")
        out.append("      - ./data/pdf2md-enhanced/output:/app/data/output")
        continue

    out.append(line)

dest.write_text("\n".join(out) + "\n")
PY
}

copy_static_artifacts() {
  if [[ -f "${ENV_FILE}" ]]; then
    cp "${ENV_FILE}" "${OUT_DIR}/.env"
  else
    cp "${EXAMPLE_ENV_FILE}" "${OUT_DIR}/.env"
  fi

  write_remote_compose
  render_template "${SCRIPT_DIR}/plan2.config.aliyun.json" "${OUT_DIR}/plan2/config.json"

  if [[ "${WITH_PROXY}" == "true" ]]; then
    render_template "${SCRIPT_DIR}/mcp-proxy-config.aliyun.yml" "${OUT_DIR}/proxy/config/mcp-proxy-config.yml"
    render_template "${SCRIPT_DIR}/mcp-proxy.service" "${OUT_DIR}/proxy/systemd/aiplanner-mcp-proxy.service"

    cp "${ROOT_DIR}/mcp/proxy/requirements.txt" "${OUT_DIR}/proxy/requirements.txt"
    copy_tree_filtered "${ROOT_DIR}/mcp/proxy/src" "${OUT_DIR}/proxy/src"
    copy_tree_filtered "${ROOT_DIR}/mcp/servers/office-word" "${OUT_DIR}/proxy/servers/office-word"
    sync_wheelhouse "${WHEEL_CACHE_DIR}/proxy-core" "${OUT_DIR}/proxy/wheels/core"
    sync_wheelhouse "${WHEEL_CACHE_DIR}/office-word" "${OUT_DIR}/proxy/wheels/office-word"
  fi
}

write_manifest() {
  cat > "${OUT_DIR}/MANIFEST.txt" <<EOF
AIPlanner deploy bundle

Generated at: $(date '+%Y-%m-%d %H:%M:%S %z')
Workspace: ${ROOT_DIR}
Remote host: ${APP_HOST:-aliapp}
Remote dir: ${REMOTE_DIR:-/opt/AICMDEngine}

Fixed design ports:
- mcp-router: 8000
- plan2: 5122
- office-word: 9002
- pdf2md-enhanced: 9010
- pageindex: 9011

Membership role:
- login/auth host
- primary MCP client/consumer

Bundle contents:
- .env
- docker-compose.mcp.yml
- plan2/config.json
EOF

  if [[ "${WITH_PROXY}" == "true" ]]; then
    cat >> "${OUT_DIR}/MANIFEST.txt" <<EOF
- proxy/config/mcp-proxy-config.yml
- proxy/systemd/aiplanner-mcp-proxy.service
- proxy/src
- proxy/requirements.txt
- proxy/servers/office-word
- proxy/wheels/core
- proxy/wheels/office-word
EOF
  fi
}

write_images_readme() {
  cat > "${OUT_DIR}/images/README.txt" <<EOF
Image bundle directory

Expected archive name:
- ${IMAGE_ARCHIVE_NAME}

Images:
- aiplanner-mcp-router:latest
- aiplanner-plan2:latest
- aiplanner-pdf2md-enhanced:latest
- aiplanner-pageindex:latest
EOF
}

build_images() {
  command_exists docker || fail "docker is required for --build-images"

  ensure_cache_layout
  sync_wheelhouse "${WHEEL_CACHE_DIR}/mcp-router" "${ROOT_DIR}/.wheelhouse/mcp-router"
  sync_wheelhouse "${WHEEL_CACHE_DIR}/pageindex" "${ROOT_DIR}/mcp/servers/PageIndex/.wheelhouse"
  sync_wheelhouse "${WHEEL_CACHE_DIR}/pdf2md-enhanced" "${ROOT_DIR}/mcp/servers/PDF2MDEnhanced/.wheelhouse"

  log "Building Docker images for linux/amd64"
  docker build --platform linux/amd64 \
    --build-arg USE_WHEELHOUSE=true \
    -f "${ROOT_DIR}/Dockerfile.mcp-router" \
    -t aiplanner-mcp-router:latest \
    "${ROOT_DIR}"
  docker build --platform linux/amd64 \
    --build-arg NODE_BASE_IMAGE="${PLAN2_NODE_BASE_IMAGE}" \
    --build-arg NGINX_BASE_IMAGE="${PLAN2_NGINX_BASE_IMAGE}" \
    -f "${ROOT_DIR}/plan2/Dockerfile" \
    -t aiplanner-plan2:latest \
    "${ROOT_DIR}/plan2"
  docker build --platform linux/amd64 -f "${ROOT_DIR}/mcp/servers/PDF2MDEnhanced/Dockerfile" -t aiplanner-pdf2md-enhanced:latest "${ROOT_DIR}/mcp/servers/PDF2MDEnhanced"
  docker build --platform linux/amd64 -f "${ROOT_DIR}/mcp/servers/PageIndex/Dockerfile" -t aiplanner-pageindex:latest "${ROOT_DIR}/mcp/servers/PageIndex"

  log "Exporting image archive ${IMAGE_ARCHIVE_NAME}"
  docker save "${IMAGE_NAMES[@]}" | gzip > "${OUT_DIR}/images/${IMAGE_ARCHIVE_NAME}"
}

run_prepare() {
  load_env_file

  if [[ "${SKIP_PREFLIGHT}" != "true" ]]; then
    log "Running local preflight"
    bash "${SCRIPT_DIR}/preflight-resources.sh" --env "${ENV_FILE}" --skip-ports || fail "Preflight failed"
  else
    warn "Skipping preflight by request"
  fi

  ensure_cache_ready

  log "Generating deploy output bundle in ${OUT_DIR}"
  rm -rf "${OUT_DIR}"
  ensure_out_layout
  copy_static_artifacts
  write_manifest
  write_images_readme

  if [[ "${BUILD_IMAGES}" == "true" ]]; then
    build_images
  fi

  log "Prepare completed"
}

run_upload() {
  load_env_file
  [[ -d "${OUT_DIR}" ]] || fail "Missing ${OUT_DIR}; run prepare first"
  command_exists ssh || fail "ssh is required for upload"
  command_exists tar || fail "tar is required for upload"

  log "Uploading deploy bundle to ${APP_HOST}:${REMOTE_DIR}"
  ssh "${APP_HOST}" "set -euo pipefail; if [[ \$(id -u) -eq 0 ]]; then SUDO=''; elif command -v sudo >/dev/null 2>&1; then SUDO='sudo'; else echo 'Need root or sudo on remote host' >&2; exit 1; fi; \$SUDO mkdir -p '${REMOTE_DIR}'"
  tar -C "${OUT_DIR}" -cf - . | ssh "${APP_HOST}" "set -euo pipefail; if [[ \$(id -u) -eq 0 ]]; then SUDO=''; elif command -v sudo >/dev/null 2>&1; then SUDO='sudo'; else echo 'Need root or sudo on remote host' >&2; exit 1; fi; \$SUDO tar -xf - -C '${REMOTE_DIR}'"
  log "Upload completed"
}

run_remote_deploy() {
  load_env_file
  command_exists ssh || fail "ssh is required for deploy"

  log "Executing remote deploy on ${APP_HOST}"
  ssh "${APP_HOST}" "REMOTE_DIR='${REMOTE_DIR}' APP_HOST='${APP_HOST}' REMOTE_PIP_INDEX_URL='${REMOTE_PIP_INDEX_URL}' WITH_PROXY='${WITH_PROXY}' bash -s" <<'EOF'
set -euo pipefail

log() {
  printf '[remote-deploy] %s\n' "$*"
}

fail() {
  printf '[remote-deploy][error] %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

REMOTE_DIR="${REMOTE_DIR:?REMOTE_DIR is required}"
REMOTE_PIP_INDEX_URL="${REMOTE_PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
WITH_PROXY="${WITH_PROXY:-false}"
cd "${REMOTE_DIR}"

[[ -f ".env" ]] || fail ".env not found in ${REMOTE_DIR}"
[[ -f "docker-compose.mcp.yml" ]] || fail "docker-compose.mcp.yml not found in ${REMOTE_DIR}"

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
elif command_exists sudo; then
  SUDO="sudo"
else
  fail "Need root or sudo on remote host"
fi

if command_exists python3; then
  PYTHON_BIN="python3"
elif command_exists python; then
  PYTHON_BIN="python"
else
  fail "python3 or python is required on remote host"
fi

if [[ "${WITH_PROXY}" == "true" ]]; then
  [[ -f "proxy/systemd/aiplanner-mcp-proxy.service" ]] || fail "systemd service file missing"
  [[ -f "proxy/config/mcp-proxy-config.yml" ]] || fail "proxy config file missing"

  log "Preparing proxy virtual environment"
  cd "${REMOTE_DIR}/proxy"
  "${PYTHON_BIN}" -m venv --clear venv
  ./venv/bin/python -m ensurepip --upgrade
  ./venv/bin/python -m pip install --upgrade pip -i "${REMOTE_PIP_INDEX_URL}"
  if find wheels/core -type f ! -name '.gitkeep' | grep -q .; then
    if ! ./venv/bin/python -m pip install --no-index --find-links wheels/core -r requirements.txt; then
      log "Offline install for proxy core failed, falling back to remote index"
      ./venv/bin/python -m pip install -i "${REMOTE_PIP_INDEX_URL}" -r requirements.txt
    fi
    if ! ./venv/bin/python -m pip install --no-index --find-links wheels/core fastmcp; then
      log "Offline install for fastmcp failed, falling back to remote index"
      ./venv/bin/python -m pip install -i "${REMOTE_PIP_INDEX_URL}" fastmcp
    fi
  else
    ./venv/bin/python -m pip install -i "${REMOTE_PIP_INDEX_URL}" -r requirements.txt
    ./venv/bin/python -m pip install -i "${REMOTE_PIP_INDEX_URL}" fastmcp
  fi
  if find wheels/office-word -type f ! -name '.gitkeep' | grep -q .; then
    if ! ./venv/bin/python -m pip install --no-index --find-links wheels/office-word -r servers/office-word/requirements.txt; then
      log "Offline install for office-word failed, falling back to remote index"
      ./venv/bin/python -m pip install -i "${REMOTE_PIP_INDEX_URL}" -r servers/office-word/requirements.txt
    fi
  else
    ./venv/bin/python -m pip install -i "${REMOTE_PIP_INDEX_URL}" -r servers/office-word/requirements.txt
  fi

  log "Installing systemd service"
  $SUDO install -d /etc/systemd/system
  $SUDO install -m 644 "${REMOTE_DIR}/proxy/systemd/aiplanner-mcp-proxy.service" /etc/systemd/system/aiplanner-mcp-proxy.service
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable aiplanner-mcp-proxy.service
  $SUDO systemctl restart aiplanner-mcp-proxy.service
  $SUDO systemctl --no-pager --full status aiplanner-mcp-proxy.service || true
else
  log "Proxy deployment disabled; skipping proxy install"
  if $SUDO systemctl list-unit-files aiplanner-mcp-proxy.service >/dev/null 2>&1; then
    $SUDO systemctl stop aiplanner-mcp-proxy.service || true
    $SUDO systemctl disable aiplanner-mcp-proxy.service || true
  fi
fi

cd "${REMOTE_DIR}"

if command_exists docker; then
  if [[ -f "images/aiplanner-images.tar.gz" ]]; then
    log "Loading Docker images from images/aiplanner-images.tar.gz"
    gzip -dc "images/aiplanner-images.tar.gz" | $SUDO docker load
  else
    log "No image archive found; assuming required images already exist on remote host"
  fi
else
  fail "docker is required on remote host"
fi

if $SUDO docker compose version >/dev/null 2>&1; then
  log "Starting application containers"
  $SUDO docker compose --env-file .env -f docker-compose.mcp.yml up -d
else
  fail "docker compose is not available on remote host"
fi

log "Remote deploy completed"
EOF
}

run_deploy() {
  [[ -d "${OUT_DIR}" ]] || fail "Missing ${OUT_DIR}; run prepare first"
  run_remote_deploy
}

main() {
  parse_args "$@"
  case "${ACTION}" in
    prepare)
      run_prepare
      ;;
    prepare-cache)
      prepare_cache
      ;;
    upload)
      run_upload
      ;;
    deploy)
      run_deploy
      ;;
    all)
      run_prepare
      run_upload
      run_deploy
      ;;
    -h|--help|"")
      usage
      [[ -n "${ACTION}" ]] || exit 1
      ;;
    *)
      fail "Unknown action: ${ACTION}"
      ;;
  esac
}

main "$@"
