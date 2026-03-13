#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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

rm -rf "$TMP_BUILD_DIR" "$PREV_BUILD_DIR"
mkdir -p "$TMP_BUILD_DIR"

pushd "$FRONTEND_DIR" >/dev/null
if [[ -f package-lock.json ]]; then
  rm -rf node_modules
  npm ci
else
  npm install
fi

npx --no-install tsc
VITE_BASE="$VITE_BASE" VITE_GRAFANA_PATH="$VITE_GRAFANA_PATH" npx --no-install vite build --outDir "$TMP_BUILD_DIR" --emptyOutDir
popd >/dev/null

PUBLIC_DOMAIN= PUBLIC_SCHEME= bash "$SCRIPT_DIR/scripts/deploy/verify-frontend-release.sh" "$TMP_BUILD_DIR" "$WEB_PATH"

if [[ -d "$TARGET_BUILD_DIR" ]]; then
  mv "$TARGET_BUILD_DIR" "$PREV_BUILD_DIR"
fi
mv "$TMP_BUILD_DIR" "$TARGET_BUILD_DIR"
rm -rf "$PREV_BUILD_DIR"

if [[ "$SKIP_LIVE_VERIFY" == "1" || -z "$PUBLIC_DOMAIN" ]]; then
  PUBLIC_DOMAIN= PUBLIC_SCHEME= bash "$SCRIPT_DIR/scripts/deploy/verify-frontend-release.sh" "$TARGET_BUILD_DIR" "$WEB_PATH"
else
  bash "$SCRIPT_DIR/scripts/deploy/verify-frontend-release.sh" "$TARGET_BUILD_DIR" "$WEB_PATH" "$PUBLIC_SCHEME" "$PUBLIC_DOMAIN"
fi
