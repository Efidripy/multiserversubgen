#!/usr/bin/env bash
set -euo pipefail

BUILD_DIR="${1:-${BUILD_DIR:-}}"
WEB_PATH_INPUT="${2:-${WEB_PATH:-}}"
PUBLIC_SCHEME_INPUT="${3:-${PUBLIC_SCHEME:-}}"
PUBLIC_DOMAIN_INPUT="${4:-${PUBLIC_DOMAIN:-}}"

if [[ -z "$BUILD_DIR" ]]; then
  echo "BUILD_DIR is required"
  exit 1
fi

INDEX_HTML="${BUILD_DIR%/}/index.html"
if [[ ! -f "$INDEX_HTML" ]]; then
  echo "Frontend index.html not found: $INDEX_HTML"
  exit 1
fi

WEB_PATH_NORMALIZED="${WEB_PATH_INPUT#/}"
WEB_PATH_NORMALIZED="${WEB_PATH_NORMALIZED%/}"
if [[ -n "$WEB_PATH_NORMALIZED" ]]; then
  ASSET_PREFIX="/${WEB_PATH_NORMALIZED}/assets/"
  PANEL_URL_PATH="/${WEB_PATH_NORMALIZED}/"
else
  ASSET_PREFIX="/assets/"
  PANEL_URL_PATH="/"
fi

extract_asset_path() {
  local pattern="$1"
  local line
  line="$(grep -oE "$pattern" "$INDEX_HTML" | head -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 1
  fi
  printf '%s\n' "$line" | sed -E 's/^(src|href)="([^"]+)"$/\2/'
}

JS_PATH="$(extract_asset_path 'src="[^"]+/assets/[^"]+\.js"')"
CSS_PATH="$(extract_asset_path 'href="[^"]+/assets/[^"]+\.css"')"

if [[ -z "${JS_PATH:-}" || -z "${CSS_PATH:-}" ]]; then
  echo "Failed to extract hashed assets from $INDEX_HTML"
  exit 1
fi

case "$JS_PATH" in
  "${ASSET_PREFIX}"*) ;;
  *)
    echo "Unexpected JS asset path in index.html: $JS_PATH"
    exit 1
    ;;
esac

case "$CSS_PATH" in
  "${ASSET_PREFIX}"*) ;;
  *)
    echo "Unexpected CSS asset path in index.html: $CSS_PATH"
    exit 1
    ;;
esac

JS_FILE="${BUILD_DIR%/}/${JS_PATH#${PANEL_URL_PATH}}"
CSS_FILE="${BUILD_DIR%/}/${CSS_PATH#${PANEL_URL_PATH}}"

if [[ ! -f "$JS_FILE" ]]; then
  echo "Referenced JS asset is missing: $JS_FILE"
  exit 1
fi

if [[ ! -f "$CSS_FILE" ]]; then
  echo "Referenced CSS asset is missing: $CSS_FILE"
  exit 1
fi

if [[ -n "$PUBLIC_DOMAIN_INPUT" ]]; then
  PUBLIC_SCHEME_RESOLVED="${PUBLIC_SCHEME_INPUT:-https}"
  PANEL_URL="${PUBLIC_SCHEME_RESOLVED}://${PUBLIC_DOMAIN_INPUT}${PANEL_URL_PATH}"
  LIVE_HTML="$(mktemp)"
  trap 'rm -f "$LIVE_HTML"' EXIT

  curl -skf "$PANEL_URL" -o "$LIVE_HTML"

  grep -Fq "$JS_PATH" "$LIVE_HTML" || {
    echo "Live index.html does not reference expected JS asset: $JS_PATH"
    exit 1
  }
  grep -Fq "$CSS_PATH" "$LIVE_HTML" || {
    echo "Live index.html does not reference expected CSS asset: $CSS_PATH"
    exit 1
  }

  JS_CODE="$(curl -sk -o /dev/null -w '%{http_code}' "${PUBLIC_SCHEME_RESOLVED}://${PUBLIC_DOMAIN_INPUT}${JS_PATH}")"
  CSS_CODE="$(curl -sk -o /dev/null -w '%{http_code}' "${PUBLIC_SCHEME_RESOLVED}://${PUBLIC_DOMAIN_INPUT}${CSS_PATH}")"
  if [[ "$JS_CODE" != "200" || "$CSS_CODE" != "200" ]]; then
    echo "Live frontend assets are not healthy: js=$JS_CODE css=$CSS_CODE"
    exit 1
  fi
fi

echo "Frontend release verified: js=$(basename "$JS_FILE") css=$(basename "$CSS_FILE")"
