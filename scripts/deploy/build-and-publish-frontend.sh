#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
INSTALLER_DIR="$(cd "${DEPLOY_DIR}/../installer" && pwd -P)"
# shellcheck disable=SC1091
source "$INSTALLER_DIR/lib/source_layout.sh"
if ! mssg_resolve_source_layout "$INSTALLER_DIR"; then
  exit 1
fi
# shellcheck disable=SC1091
source "$MSSG_INSTALLER_DIR/lib/resource_guard.sh"
REPO_DIR="${REPO_DIR:-$MSSG_SOURCE_ROOT}"
PROJECT_DIR="${PROJECT_DIR:-/opt/sub-manager}"
WEB_PATH="${WEB_PATH:-}"
GRAFANA_WEB_PATH="${GRAFANA_WEB_PATH:-grafana}"
PUBLIC_SCHEME="${PUBLIC_SCHEME:-https}"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"
SKIP_LIVE_VERIFY="${SKIP_LIVE_VERIFY:-0}"

if [[ -z "$PROJECT_DIR" ]]; then
  echo "PROJECT_DIR is required"
  exit 1
fi

if [[ -n "$WEB_PATH" ]]; then
  VITE_BASE="/${WEB_PATH#/}/"
else
  VITE_BASE="/"
fi
VITE_GRAFANA_PATH="/${GRAFANA_WEB_PATH#/}/"

FRONTEND_DIR="$MSSG_FRONTEND_DIR"
TARGET_BUILD_DIR="$PROJECT_DIR/build"
TMP_BUILD_DIR="${PROJECT_DIR}/.build-next"
PREV_BUILD_DIR="${PROJECT_DIR}/.build-prev"

resource_guard_detect_profile
resource_guard_export_build_env
if [[ -n "${FRONTEND_NODE_OPTIONS:-}" ]]; then
  export NODE_OPTIONS="$FRONTEND_NODE_OPTIONS"
fi
rm -rf "$FRONTEND_DIR/node_modules" "$FRONTEND_DIR/.vite" "$TMP_BUILD_DIR" "$PREV_BUILD_DIR"
resource_guard_require_free_mb "${FRONTEND_BUILD_MIN_FREE_MB:-900}" "before frontend dependency install/build" "/"

mkdir -p "$TMP_BUILD_DIR"

pushd "$FRONTEND_DIR" >/dev/null
if [[ -f package-lock.json ]]; then
  resource_guard_run_heavy npm ci --prefer-offline --no-audit --no-fund
else
  resource_guard_run_heavy npm install --prefer-offline --no-audit --no-fund
fi

resource_guard_run_heavy npx --no-install tsc
resource_guard_run_heavy env VITE_BASE="$VITE_BASE" VITE_GRAFANA_PATH="$VITE_GRAFANA_PATH" npx --no-install vite build --outDir "$TMP_BUILD_DIR" --emptyOutDir

# Stamp sw.js with a unique cache version so each deploy evicts stale SW caches.
# Prevents the white-screen bug where a cached sw.js serves old asset hashes
# that no longer exist on the server after a deploy.
CACHE_VER="$(date +%Y%m%d%H%M%S)-$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo 'local')"
if [[ -f "$TMP_BUILD_DIR/sw.js" ]]; then
  sed -i "s/__CACHE_VER__/${CACHE_VER}/g" "$TMP_BUILD_DIR/sw.js"
fi
popd >/dev/null

PUBLIC_DOMAIN='' PUBLIC_SCHEME='' bash "$MSSG_VERIFY_FRONTEND_RELEASE_SCRIPT" "$TMP_BUILD_DIR" "$WEB_PATH"

if [[ -d "$TARGET_BUILD_DIR" ]]; then
  mv "$TARGET_BUILD_DIR" "$PREV_BUILD_DIR"
fi
mv "$TMP_BUILD_DIR" "$TARGET_BUILD_DIR"
find "$TARGET_BUILD_DIR" -type d -exec chmod 0755 {} +
find "$TARGET_BUILD_DIR" -type f -exec chmod 0644 {} +
rm -rf "$PREV_BUILD_DIR"
# Post-build: remove npm deps (not needed at runtime, frees ~120MB)
rm -rf "$FRONTEND_DIR/node_modules" "$FRONTEND_DIR/.vite"

if [[ "$SKIP_LIVE_VERIFY" == "1" || -z "$PUBLIC_DOMAIN" ]]; then
  PUBLIC_DOMAIN='' PUBLIC_SCHEME='' bash "$MSSG_VERIFY_FRONTEND_RELEASE_SCRIPT" "$TARGET_BUILD_DIR" "$WEB_PATH"
else
  bash "$MSSG_VERIFY_FRONTEND_RELEASE_SCRIPT" "$TARGET_BUILD_DIR" "$WEB_PATH" "$PUBLIC_SCHEME" "$PUBLIC_DOMAIN"
fi
