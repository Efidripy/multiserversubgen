#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/scripts/installer/lib/resource_guard.sh"
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

FRONTEND_DIR="$SCRIPT_DIR/frontend"
TARGET_BUILD_DIR="$PROJECT_DIR/build"
TMP_BUILD_DIR="${PROJECT_DIR}/.build-next"
PREV_BUILD_DIR="${PROJECT_DIR}/.build-prev"

resource_guard_detect_profile
resource_guard_export_build_env
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

PUBLIC_DOMAIN='' PUBLIC_SCHEME='' bash "$SCRIPT_DIR/scripts/deploy/verify-frontend-release.sh" "$TMP_BUILD_DIR" "$WEB_PATH"

if [[ -d "$TARGET_BUILD_DIR" ]]; then
  mv "$TARGET_BUILD_DIR" "$PREV_BUILD_DIR"
fi
mv "$TMP_BUILD_DIR" "$TARGET_BUILD_DIR"
rm -rf "$PREV_BUILD_DIR"
# Post-build: remove npm deps (not needed at runtime, frees ~120MB)
rm -rf "$FRONTEND_DIR/node_modules" "$FRONTEND_DIR/.vite"

if [[ "$SKIP_LIVE_VERIFY" == "1" || -z "$PUBLIC_DOMAIN" ]]; then
  PUBLIC_DOMAIN='' PUBLIC_SCHEME='' bash "$SCRIPT_DIR/scripts/deploy/verify-frontend-release.sh" "$TARGET_BUILD_DIR" "$WEB_PATH"
else
  bash "$SCRIPT_DIR/scripts/deploy/verify-frontend-release.sh" "$TARGET_BUILD_DIR" "$WEB_PATH" "$PUBLIC_SCHEME" "$PUBLIC_DOMAIN"
fi
