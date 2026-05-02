#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AIPLANNER_ROOT="$PROJECT_ROOT/AIPlanner"

ACTION="${1:-}"
if [[ -z "$ACTION" || "$ACTION" == --* ]]; then
  ACTION="all"
fi

ENV_FILE=""
APP_HOST=""
APP_USER="root"
APP_PORT="22"
REMOTE_DIR="/opt/AICMDEngine"
REMOTE_SRC_BASE="/opt/AICMDEngine-src"
SOURCE_PACKAGE="/tmp/aiplanner-source.tar.gz"
BUILD_PLATFORM="${BUILD_PLATFORM:-}"
BUILD_PLATFORM_ARG=""
DEPLOY_SCOPE="all"
DOCKER_MIRROR=""
UPLOAD_METHOD="auto"
RSYNC_BWLIMIT=""
UPLOAD_RETRIES="3"
UPLOAD_RETRY_SLEEP="3"
CLEANUP_SOURCE="true"
FORCE_REPACKAGE="false"

SSH_CIPHER="chacha20-poly1305@openssh.com"
REMOTE_RSYNC_CHECKED="false"
REMOTE_RSYNC_AVAILABLE="false"

ROUTER_IMAGE="aiplanner-mcp-router:latest"
PLAN2_IMAGE="aiplanner-plan2:latest"
OFFICE_WORD_IMAGE="aiplanner-office-word:latest"
PDF2MD_ENH_IMAGE="aiplanner-pdf2md-enhanced:latest"
PAGEINDEX_IMAGE="aiplanner-pageindex:latest"

PLAN2_HOST_PORT_DEFAULT="5122"
ROUTER_HOST_PORT_DEFAULT="8000"
OFFICE_WORD_HOST_PORT_DEFAULT="9002"
PDF2MD_ENHANCED_HOST_PORT_DEFAULT="9010"
PAGEINDEX_HOST_PORT_DEFAULT="9011"

log() {
  printf '[aiplanner-remote] %s\n' "$*"
}

fail() {
  printf '[aiplanner-remote][error] %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  bash AIPlanner/deploy/deploy-remote-build.sh [options] <action>

Actions:
  build-src      Prepare local source package only
  upload-src     Upload source package + env + compose + plan2 config to App
  remote-build   Build images and deploy on App
  remote-clean   Remove remote source package only
  all            build-src + upload-src + remote-build
  status         Show remote compose status
  logs           Show remote compose logs

Options:
  --env-file PATH
  --app-host HOST
  --app-user USER
  --app-port PORT
  --remote-dir DIR
  --remote-src-base DIR
  --source-package PATH
  --scope router|plan2|mcp|all
  --platform linux/amd64|linux/arm64
  --mirror cn|PREFIX
  --upload-method auto|scp|rsync  (default: auto)
  --rsync-bwlimit KBPS            Optional rsync bandwidth limit
  --upload-retries N              Upload retries per file (default: 3)
  --upload-retry-sleep SEC        Base sleep seconds between retries (default: 3)
  --cleanup-source true|false     (default: true)
  -f, --force

Examples:
  bash AIPlanner/deploy/deploy-remote-build.sh --env-file AIPlanner/.env.ali --app-host aliapp all
  bash AIPlanner/deploy/deploy-remote-build.sh --env-file AIPlanner/.env.ali --app-host aliapp --mirror cn --upload-method rsync all
  bash AIPlanner/deploy/deploy-remote-build.sh --env-file AIPlanner/.env.ali --app-host aliapp --scope plan2 remote-build
EOF
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing command: $1"
}

require_app_host() {
  [[ -n "$APP_HOST" ]] || fail "--app-host is required"
}

resolve_env_file() {
  if [[ -n "$ENV_FILE" ]]; then
    [[ -f "$ENV_FILE" ]] || fail "env file not found: $ENV_FILE"
    return
  fi

  if [[ -f "$AIPLANNER_ROOT/.env.ali" ]]; then
    ENV_FILE="$AIPLANNER_ROOT/.env.ali"
  elif [[ -f "$SCRIPT_DIR/.env" ]]; then
    ENV_FILE="$SCRIPT_DIR/.env"
  elif [[ -f "$SCRIPT_DIR/env.aliyun.example" ]]; then
    ENV_FILE="$SCRIPT_DIR/env.aliyun.example"
    log "Using example env file: $ENV_FILE"
  else
    fail "No env file available (pass --env-file)"
  fi
}

validate_scope() {
  case "$1" in
    router|plan2|mcp|all)
      ;;
    *)
      fail "Invalid scope: $1 (expected: router|plan2|mcp|all)"
      ;;
  esac
}

scope_to_services() {
  case "$DEPLOY_SCOPE" in
    router)
      printf '%s\n' "mcp-router"
      ;;
    plan2)
      printf '%s\n' "plan2"
      ;;
    mcp)
      printf '%s\n' "office-word" "pdf2md-enhanced" "pageindex"
      ;;
    all)
      printf '%s\n' "mcp-router" "plan2"
      ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    build-src|upload-src|remote-build|remote-clean|all|status|logs)
      ACTION="$1"
      shift
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --app-host)
      APP_HOST="$2"
      shift 2
      ;;
    --app-user)
      APP_USER="$2"
      shift 2
      ;;
    --app-port)
      APP_PORT="$2"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="$2"
      shift 2
      ;;
    --remote-src-base)
      REMOTE_SRC_BASE="$2"
      shift 2
      ;;
    --source-package)
      SOURCE_PACKAGE="$2"
      shift 2
      ;;
    --scope)
      DEPLOY_SCOPE="$2"
      shift 2
      ;;
    --platform)
      BUILD_PLATFORM_ARG="$2"
      shift 2
      ;;
    --mirror)
      DOCKER_MIRROR="$2"
      shift 2
      ;;
    --upload-method)
      UPLOAD_METHOD="$2"
      shift 2
      ;;
    --rsync-bwlimit)
      RSYNC_BWLIMIT="$2"
      shift 2
      ;;
    --upload-retries)
      UPLOAD_RETRIES="$2"
      shift 2
      ;;
    --upload-retry-sleep)
      UPLOAD_RETRY_SLEEP="$2"
      shift 2
      ;;
    --cleanup-source)
      CLEANUP_SOURCE="$2"
      shift 2
      ;;
    -f|--force)
      FORCE_REPACKAGE="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

validate_scope "$DEPLOY_SCOPE"
resolve_env_file

case "$UPLOAD_METHOD" in
  auto|scp|rsync) ;;
  *) fail "Invalid --upload-method: $UPLOAD_METHOD" ;;
esac

[[ "$UPLOAD_RETRIES" =~ ^[0-9]+$ ]] || fail "--upload-retries must be integer"
[[ "$UPLOAD_RETRY_SLEEP" =~ ^[0-9]+$ ]] || fail "--upload-retry-sleep must be integer"

PLAN2_HOST_PORT="$PLAN2_HOST_PORT_DEFAULT"
ROUTER_HOST_PORT="$ROUTER_HOST_PORT_DEFAULT"
PDF2MD_ENHANCED_HOST_PORT="$PDF2MD_ENHANCED_HOST_PORT_DEFAULT"
PAGEINDEX_HOST_PORT="$PAGEINDEX_HOST_PORT_DEFAULT"

# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -n "$BUILD_PLATFORM_ARG" ]]; then
  BUILD_PLATFORM="$BUILD_PLATFORM_ARG"
fi
case "$BUILD_PLATFORM" in
  linux/amd64|linux/arm64)
    ;;
  "")
    fail "BUILD_PLATFORM is required for remote deploy scripts (set BUILD_PLATFORM in env file or pass --platform linux/amd64|linux/arm64)"
    ;;
  *)
    fail "Unsupported BUILD_PLATFORM: $BUILD_PLATFORM (expected linux/amd64 or linux/arm64)"
    ;;
esac

PLAN2_HOST_PORT="${PLAN2_HOST_PORT:-$PLAN2_HOST_PORT_DEFAULT}"
ROUTER_HOST_PORT="${ROUTER_HOST_PORT:-$ROUTER_HOST_PORT_DEFAULT}"
OFFICE_WORD_HOST_PORT="${OFFICE_WORD_HOST_PORT:-$OFFICE_WORD_HOST_PORT_DEFAULT}"
PDF2MD_ENHANCED_HOST_PORT="${PDF2MD_ENHANCED_HOST_PORT:-$PDF2MD_ENHANCED_HOST_PORT_DEFAULT}"
PAGEINDEX_HOST_PORT="${PAGEINDEX_HOST_PORT:-$PAGEINDEX_HOST_PORT_DEFAULT}"

PLAN2_PUBLIC_BASE_URL="http://${APP_HOST}:${PLAN2_HOST_PORT}"

ssh_app() {
  ssh -p "$APP_PORT" "$APP_USER@$APP_HOST" "$@"
}

scp_app() {
  scp -P "$APP_PORT" -o Compression=no -c "$SSH_CIPHER" "$@"
}

detect_remote_rsync() {
  if [[ "$REMOTE_RSYNC_CHECKED" == "true" ]]; then
    return
  fi
  REMOTE_RSYNC_CHECKED="true"
  if ssh_app "command -v rsync >/dev/null 2>&1"; then
    REMOTE_RSYNC_AVAILABLE="true"
  else
    REMOTE_RSYNC_AVAILABLE="false"
  fi
}

rsync_app() {
  local src="$1"
  local dst="$2"
  local -a args

  args=(
    -aP
    --partial
    --partial-dir=.rsync-partial
    -e "ssh -p $APP_PORT -o Compression=no -c $SSH_CIPHER"
  )

  if [[ -n "$RSYNC_BWLIMIT" ]]; then
    args+=(--bwlimit "$RSYNC_BWLIMIT")
  fi

  rsync "${args[@]}" "$src" "$dst"
}

calc_local_sha256() {
  local file="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    fail "Missing shasum/sha256sum"
  fi
}

calc_remote_sha256() {
  local file="$1"
  ssh_app "
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum '$file' | awk '{print \$1}'
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 '$file' | awk '{print \$1}'
else
  echo 'Missing sha256sum/shasum on remote host' >&2
  exit 1
fi
"
}

upload_file_to_app() {
  local src="$1"
  local dst="$2"
  local attempt=0
  local sleep_sec

  while :; do
    attempt=$((attempt + 1))

    case "$UPLOAD_METHOD" in
      scp)
        log "Uploading with scp (attempt $attempt): $src -> $dst"
        if scp_app "$src" "$dst"; then
          return
        fi
        ;;
      rsync)
        require_cmd rsync
        detect_remote_rsync
        [[ "$REMOTE_RSYNC_AVAILABLE" == "true" ]] || fail "Remote host missing rsync"
        log "Uploading with rsync (attempt $attempt): $src -> $dst"
        if rsync_app "$src" "$dst"; then
          return
        fi
        ;;
      auto)
        if command -v rsync >/dev/null 2>&1; then
          detect_remote_rsync
          if [[ "$REMOTE_RSYNC_AVAILABLE" == "true" ]]; then
            log "Uploading with rsync(auto, attempt $attempt): $src -> $dst"
            if rsync_app "$src" "$dst"; then
              return
            fi
          else
            log "Remote rsync unavailable, fallback scp(auto, attempt $attempt): $src -> $dst"
            if scp_app "$src" "$dst"; then
              return
            fi
          fi
        else
          log "Local rsync unavailable, fallback scp(auto, attempt $attempt): $src -> $dst"
          if scp_app "$src" "$dst"; then
            return
          fi
        fi
        ;;
    esac

    if (( attempt > UPLOAD_RETRIES )); then
      fail "Upload failed after $attempt attempts: $src -> $dst"
    fi

    sleep_sec=$((UPLOAD_RETRY_SLEEP * attempt))
    log "Upload attempt $attempt failed, retrying in ${sleep_sec}s..."
    sleep "$sleep_sec"
  done
}

render_plan2_config() {
  local out_file="$1"
  python - "$SCRIPT_DIR/plan2.config.aliyun.json" "$out_file" "$PLAN2_PUBLIC_BASE_URL" <<'PY'
import pathlib
import re
import sys

template = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
out_file = pathlib.Path(sys.argv[2])
plan2_url = sys.argv[3]

rendered = re.sub(r"\$\{PLAN2_PUBLIC_BASE_URL\}", plan2_url, template)
out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(rendered, encoding='utf-8')
PY
}

render_env_with_build_platform() {
  local dest="$1"
  awk -v platform="$BUILD_PLATFORM" '
    BEGIN { written = 0 }
    /^BUILD_PLATFORM=/ {
      print "BUILD_PLATFORM=" platform
      written = 1
      next
    }
    { print }
    END {
      if (!written) {
        print "BUILD_PLATFORM=" platform
      }
    }
  ' "$ENV_FILE" > "$dest"
}

prepare_source_package() {
  require_cmd tar

  if [[ "$FORCE_REPACKAGE" != "true" && -f "$SOURCE_PACKAGE" ]]; then
    log "Using existing source package: $SOURCE_PACKAGE"
    return
  fi

  log "Packaging AIPlanner source tree to $SOURCE_PACKAGE"
  mkdir -p "$(dirname "$SOURCE_PACKAGE")"
  # Prevent user-level TAR_OPTIONS from unexpectedly altering archive contents.
  unset TAR_OPTIONS || true

  case "$DEPLOY_SCOPE" in
    plan2)
      log "Using slim source package profile for scope=plan2"
      COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar -czf "$SOURCE_PACKAGE" \
        --exclude='AIPlanner/plan2/node_modules' \
        --exclude='AIPlanner/plan2/dist' \
        -C "$PROJECT_ROOT" \
        AIPlanner/plan2 \
        AIPlanner/deploy/docker-compose.mcp.yml \
        AIPlanner/deploy/plan2.config.aliyun.json
      ;;
    router)
      log "Using slim source package profile for scope=router"
      COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar -czf "$SOURCE_PACKAGE" \
        -C "$PROJECT_ROOT" \
        AIPlanner/Dockerfile.mcp-router \
        AIPlanner/requirements.txt \
        AIPlanner/src \
        AIPlanner/.wheelhouse \
        AIPlanner/deploy/docker-compose.mcp.yml
      ;;
    mcp)
      log "Using slim source package profile for scope=mcp"
      COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar -czf "$SOURCE_PACKAGE" \
        -C "$PROJECT_ROOT" \
        AIPlanner/mcp/servers/office-word \
        AIPlanner/mcp/servers/PDF2MDEnhanced \
        AIPlanner/mcp/servers/PageIndex \
        AIPlanner/deploy/docker-compose.mcp.yml
      ;;
    all)
      log "Using slim source package profile for scope=all"
      COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar -czf "$SOURCE_PACKAGE" \
        --exclude='AIPlanner/plan2/node_modules' \
        --exclude='AIPlanner/plan2/dist' \
        --exclude='AIPlanner/plan2/.cache' \
        --exclude='AIPlanner/plan2/.vite' \
        --exclude='AIPlanner/src/__pycache__' \
        --exclude='AIPlanner/src/**/*.pyc' \
        --exclude='AIPlanner/mcp/servers/PDF2MDEnhanced/data/output' \
        --exclude='AIPlanner/mcp/servers/PDF2MDEnhanced/data/input' \
        --exclude='AIPlanner/mcp/servers/PDF2MDEnhanced/data/tasks' \
        --exclude='AIPlanner/mcp/servers/PDF2MDEnhanced/__pycache__' \
        --exclude='AIPlanner/mcp/servers/PDF2MDEnhanced/**/*.log' \
        --exclude='AIPlanner/mcp/servers/PageIndex/.git' \
        --exclude='AIPlanner/mcp/servers/PageIndex/tests' \
        --exclude='AIPlanner/mcp/servers/PageIndex/__pycache__' \
        --exclude='AIPlanner/mcp/servers/PageIndex/pageindex/__pycache__' \
        --exclude='AIPlanner/mcp/servers/**/__pycache__' \
        --exclude='AIPlanner/mcp/servers/**/*.pyc' \
        -C "$PROJECT_ROOT" \
        AIPlanner/Dockerfile.mcp-router \
        AIPlanner/requirements.txt \
        AIPlanner/src \
        AIPlanner/.wheelhouse \
        AIPlanner/plan2 \
        AIPlanner/deploy/docker-compose.mcp.yml \
        AIPlanner/deploy/plan2.config.aliyun.json
      ;;
  esac

  validate_source_package
}

archive_has_entry() {
  local archive="$1"
  local entry="$2"
  tar -tzf "$archive" | grep -Fxq "$entry"
}

validate_source_package() {
  local archive="$SOURCE_PACKAGE"
  [[ -f "$archive" ]] || fail "source package not found after packaging: $archive"

  local size
  size="$(wc -c < "$archive" | tr -d ' ')"
  [[ "$size" =~ ^[0-9]+$ ]] || fail "failed to determine source package size: $archive"
  (( size > 1024 )) || fail "source package is unexpectedly small (${size} bytes): $archive"

  case "$DEPLOY_SCOPE" in
    router)
      archive_has_entry "$archive" "AIPlanner/Dockerfile.mcp-router" || fail "source package missing AIPlanner/Dockerfile.mcp-router"
      archive_has_entry "$archive" "AIPlanner/src/main.py" || fail "source package missing AIPlanner/src/main.py"
      ;;
    plan2)
      archive_has_entry "$archive" "AIPlanner/plan2/Dockerfile" || fail "source package missing AIPlanner/plan2/Dockerfile"
      archive_has_entry "$archive" "AIPlanner/deploy/docker-compose.mcp.yml" || fail "source package missing AIPlanner/deploy/docker-compose.mcp.yml"
      ;;
    mcp)
      archive_has_entry "$archive" "AIPlanner/mcp/servers/office-word/Dockerfile" || fail "source package missing AIPlanner/mcp/servers/office-word/Dockerfile"
      archive_has_entry "$archive" "AIPlanner/mcp/servers/PDF2MDEnhanced/Dockerfile" || fail "source package missing AIPlanner/mcp/servers/PDF2MDEnhanced/Dockerfile"
      archive_has_entry "$archive" "AIPlanner/mcp/servers/PageIndex/Dockerfile" || fail "source package missing AIPlanner/mcp/servers/PageIndex/Dockerfile"
      ;;
    all)
      archive_has_entry "$archive" "AIPlanner/Dockerfile.mcp-router" || fail "source package missing AIPlanner/Dockerfile.mcp-router"
      archive_has_entry "$archive" "AIPlanner/plan2/Dockerfile" || fail "source package missing AIPlanner/plan2/Dockerfile"
      ;;
  esac

  log "Source package validation passed (size=${size} bytes, scope=${DEPLOY_SCOPE})"
}

upload_source_and_files() {
  require_app_host
  local rendered_env
  local rendered_plan2_config
  local local_sha
  local remote_sha

  [[ -f "$SOURCE_PACKAGE" ]] || fail "source package not found: $SOURCE_PACKAGE"

  log "Creating remote directory on App"
  ssh_app "mkdir -p '$REMOTE_DIR/plan2' '$REMOTE_DIR/data/pdf2md-enhanced/input' '$REMOTE_DIR/data/pdf2md-enhanced/output'"

  log "Uploading source package"
  ssh_app "rm -f '$REMOTE_DIR/aiplanner-source.tar.gz'"
  upload_file_to_app "$SOURCE_PACKAGE" "$APP_USER@$APP_HOST:$REMOTE_DIR/aiplanner-source.tar.gz"

  log "Verifying uploaded source package integrity"
  local_sha="$(calc_local_sha256 "$SOURCE_PACKAGE")"
  remote_sha="$(calc_remote_sha256 "$REMOTE_DIR/aiplanner-source.tar.gz")"
  [[ "$local_sha" == "$remote_sha" ]] || fail "Source package checksum mismatch"
  log "Source package checksum verified"

  log "Uploading env and compose"
  rendered_env="$(mktemp)"
  render_env_with_build_platform "$rendered_env"
  upload_file_to_app "$rendered_env" "$APP_USER@$APP_HOST:$REMOTE_DIR/.env"
  rm -f "$rendered_env"

  upload_file_to_app "$SCRIPT_DIR/docker-compose.mcp.yml" "$APP_USER@$APP_HOST:$REMOTE_DIR/docker-compose.mcp.yml"

  log "Rendering and uploading plan2 config"
  rendered_plan2_config="$(mktemp)"
  render_plan2_config "$rendered_plan2_config"
  upload_file_to_app "$rendered_plan2_config" "$APP_USER@$APP_HOST:$REMOTE_DIR/plan2/config.json"
  rm -f "$rendered_plan2_config"
}

remote_build_and_deploy() {
  require_app_host

  local services
  local service_args=""
  mapfile -t services < <(scope_to_services)
  if [[ "$DEPLOY_SCOPE" != "all" ]]; then
    service_args="${services[*]}"
  fi

  local mirror_prefix=""
  local npm_registry=""
  local pip_index_url=""
  local alpine_mirror=""
  local apt_mirror=""
  local node_base_image="node:20-alpine"
  local nginx_base_image="nginx:alpine"
  local python311_base_image="python:3.11-slim"
  local python312_base_image="python:3.12-slim"

  if [[ "$DOCKER_MIRROR" == "cn" ]]; then
    mirror_prefix="docker.1ms.run"
    npm_registry="https://registry.npmmirror.com"
    pip_index_url="https://mirrors.aliyun.com/pypi/simple/"
    alpine_mirror="mirrors.aliyun.com/alpine"
    apt_mirror="http://mirrors.aliyun.com/debian"
  elif [[ -n "$DOCKER_MIRROR" ]]; then
    mirror_prefix="${DOCKER_MIRROR%/}"
  fi

  if [[ -n "$mirror_prefix" ]]; then
    node_base_image="${mirror_prefix}/node:20-alpine"
    nginx_base_image="${mirror_prefix}/nginx:alpine"
    python311_base_image="${mirror_prefix}/python:3.11-slim"
    python312_base_image="${mirror_prefix}/python:3.12-slim"
  fi

  log "Building AIPlanner images on App and deploying (scope: $DEPLOY_SCOPE)"
  ssh_app "
set -euo pipefail

command -v docker >/dev/null 2>&1 || { echo 'Missing docker on remote host' >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo 'Missing tar on remote host' >&2; exit 1; }

if [[ '$DEPLOY_SCOPE' == 'plan2' || '$DEPLOY_SCOPE' == 'all' ]]; then
  command -v npm >/dev/null 2>&1 || { echo 'Missing npm on remote host for plan2 build' >&2; exit 1; }
fi

REMOTE_BUILD_DIR='${REMOTE_SRC_BASE%/}-'\
\"\$(date +%Y%m%d%H%M%S)\"
mkdir -p \"\$REMOTE_BUILD_DIR\"

# Set trap to clean up build dir on error (unless CLEANUP_SOURCE=false)
if [[ '$CLEANUP_SOURCE' == 'true' ]]; then
  trap 'rm -rf \"\$REMOTE_BUILD_DIR\" 2>/dev/null; echo \"Build cleanup: removed \$REMOTE_BUILD_DIR\" >&2' EXIT
fi

if tar --help 2>/dev/null | grep -q -- '--warning'; then
  tar --warning=no-unknown-keyword -xzf '$REMOTE_DIR/aiplanner-source.tar.gz' -C \"\$REMOTE_BUILD_DIR\"
else
  tar -xzf '$REMOTE_DIR/aiplanner-source.tar.gz' -C \"\$REMOTE_BUILD_DIR\"
fi
cd \"\$REMOTE_BUILD_DIR/AIPlanner\"

if [[ '$DOCKER_MIRROR' == 'cn' ]]; then
  echo '🇨🇳 已启用国内依赖源: npm=$npm_registry, pip=$pip_index_url, apt=$apt_mirror'
fi

case '$DEPLOY_SCOPE' in
  router)
    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg PYTHON_BASE_IMAGE='$python311_base_image' \
      ${pip_index_url:+--build-arg PIP_INDEX_URL='$pip_index_url'} \
      ${apt_mirror:+--build-arg APT_MIRROR='$apt_mirror'} \
      -f Dockerfile.mcp-router \
      -t '$ROUTER_IMAGE' \
      .
    ;;
  plan2)
    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg NODE_BASE_IMAGE='$node_base_image' \
      --build-arg NGINX_BASE_IMAGE='$nginx_base_image' \
      ${npm_registry:+--build-arg NPM_REGISTRY='$npm_registry'} \
      ${alpine_mirror:+--build-arg ALPINE_MIRROR='$alpine_mirror'} \
      -f plan2/Dockerfile \
      -t '$PLAN2_IMAGE' \
      plan2
    ;;
  mcp)
    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg PYTHON_BASE_IMAGE='$python312_base_image' \
      ${pip_index_url:+--build-arg PIP_INDEX_URL='$pip_index_url'} \
      ${apt_mirror:+--build-arg APT_MIRROR='$apt_mirror'} \
      -f mcp/servers/office-word/Dockerfile \
      -t '$OFFICE_WORD_IMAGE' \
      mcp/servers/office-word

    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg PYTHON_BASE_IMAGE='$python312_base_image' \
      ${pip_index_url:+--build-arg PIP_INDEX_URL='$pip_index_url'} \
      ${apt_mirror:+--build-arg APT_MIRROR='$apt_mirror'} \
      -f mcp/servers/PDF2MDEnhanced/Dockerfile \
      -t '$PDF2MD_ENH_IMAGE' \
      mcp/servers/PDF2MDEnhanced

    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg PYTHON_BASE_IMAGE='$python312_base_image' \
      ${pip_index_url:+--build-arg PIP_INDEX_URL='$pip_index_url'} \
      ${apt_mirror:+--build-arg APT_MIRROR='$apt_mirror'} \
      -f mcp/servers/PageIndex/Dockerfile \
      -t '$PAGEINDEX_IMAGE' \
      mcp/servers/PageIndex
    ;;
  all)
    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg PYTHON_BASE_IMAGE='$python311_base_image' \
      ${pip_index_url:+--build-arg PIP_INDEX_URL='$pip_index_url'} \
      ${apt_mirror:+--build-arg APT_MIRROR='$apt_mirror'} \
      -f Dockerfile.mcp-router \
      -t '$ROUTER_IMAGE' \
      .

    docker build \
      --platform '$BUILD_PLATFORM' \
      --pull=false \
      --build-arg NODE_BASE_IMAGE='$node_base_image' \
      --build-arg NGINX_BASE_IMAGE='$nginx_base_image' \
      ${npm_registry:+--build-arg NPM_REGISTRY='$npm_registry'} \
      ${alpine_mirror:+--build-arg ALPINE_MIRROR='$alpine_mirror'} \
      -f plan2/Dockerfile \
      -t '$PLAN2_IMAGE' \
      plan2
    ;;
esac

cd '$REMOTE_DIR'
if [[ '$DEPLOY_SCOPE' == 'all' ]]; then
  docker compose -f docker-compose.mcp.yml up -d mcp-router plan2
else
  docker compose -f docker-compose.mcp.yml up -d $service_args
fi

# trap EXIT will clean up \$REMOTE_BUILD_DIR after deployment completes
"
}

remote_clean_source_package() {
  require_app_host
  log "Removing remote source package from $REMOTE_DIR"
  ssh_app "rm -f '$REMOTE_DIR/aiplanner-source.tar.gz'"
}

remote_status() {
  require_app_host
  ssh_app "cd '$REMOTE_DIR' && docker compose -f docker-compose.mcp.yml ps"
}

remote_logs() {
  require_app_host
  ssh_app "cd '$REMOTE_DIR' && docker compose -f docker-compose.mcp.yml logs --tail=200"
}

case "$ACTION" in
  build-src)
    prepare_source_package
    ;;
  upload-src)
    require_app_host
    prepare_source_package
    upload_source_and_files
    ;;
  remote-build)
    require_app_host
    remote_build_and_deploy
    ;;
  remote-clean)
    require_app_host
    remote_clean_source_package
    ;;
  all)
    require_app_host
    prepare_source_package
    upload_source_and_files
    remote_build_and_deploy
    ;;
  status)
    remote_status
    ;;
  logs)
    remote_logs
    ;;
  *)
    usage
    exit 1
    ;;
esac
