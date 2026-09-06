#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OPS_DIR="${SCRIPT_DIR}/scripts/ops"

LOG_FILE="${LOG_FILE:-/opt/.sub_manager_install.log}"
# shellcheck source=lib/install_log.sh
source "${OPS_DIR}/lib/install_log.sh"
install_log_source "$LOG_FILE"

load_env_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "${line:0:1}" == "#" || "$line" != *=* ]] && continue
    local key="${line%%=*}"
    local value="${line#*=}"
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [[ -n "${!key-}" ]] && continue
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
    export "$key=$value"
  done < "$file"
}

derive_public_from_url() {
  local url="$1"
  python3 - "$url" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
path = parsed.path.strip("/")
print(parsed.scheme or "")
print(parsed.netloc or "")
print(path)
PY
}

load_env_file "${SCRIPT_DIR}/.env"
load_env_file "${SCRIPT_DIR}/frontend/.env"
load_env_file "${SCRIPT_DIR}/backend/.env"

if [[ -n "${PLAYWRIGHT_BASE_URL:-}" ]]; then
  mapfile -t parsed_url < <(derive_public_from_url "$PLAYWRIGHT_BASE_URL")
  PUBLIC_SCHEME="${parsed_url[0]:-${PUBLIC_SCHEME:-https}}"
  PUBLIC_DOMAIN="${parsed_url[1]:-${PUBLIC_DOMAIN:-}}"
  if [[ -n "${parsed_url[2]:-}" ]]; then
    WEB_PATH="${parsed_url[2]}"
  fi
fi

if [[ -n "${VITE_BASE:-}" ]]; then
  derived_web_path="${VITE_BASE#/}"
  derived_web_path="${derived_web_path%/}"
  if [[ -n "$derived_web_path" ]]; then
    WEB_PATH="$derived_web_path"
  fi
fi

PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
APP_PORT="${APP_PORT:-666}"
WEB_PATH="${WEB_PATH:-}"
WEB_PATH="${WEB_PATH#/}"
WEB_PATH="${WEB_PATH%/}"
PUBLIC_SCHEME="${PUBLIC_SCHEME:-https}"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"
CURL_MAX_TIME="${CURL_MAX_TIME:-5}"
MONITORING_ENABLED="${MONITORING_ENABLED:-false}"
GRAFANA_WEB_PATH="${GRAFANA_WEB_PATH:-grafana}"
GRAFANA_WEB_PATH="${GRAFANA_WEB_PATH#/}"
GRAFANA_WEB_PATH="${GRAFANA_WEB_PATH%/}"
GRAFANA_HTTP_PORT="${GRAFANA_HTTP_PORT:-43000}"

ok=0
fail=0

check() {
  local name="$1"
  shift
  if "$@"; then
    printf '[OK] %s\n' "$name"
    ok=$((ok + 1))
  else
    printf '[FAIL] %s\n' "$name"
    fail=$((fail + 1))
  fi
}

check_shell() {
  local name="$1"
  local cmd="$2"
  if bash -lc "$cmd"; then
    printf '[OK] %s\n' "$name"
    ok=$((ok + 1))
  else
    printf '[FAIL] %s\n' "$name"
    fail=$((fail + 1))
  fi
}

check "systemd $PROJECT_NAME active" systemctl is-active --quiet "$PROJECT_NAME"
check "nginx active" systemctl is-active --quiet nginx
check_shell "nginx config valid" "sudo -n nginx -t >/dev/null 2>&1"
check_shell "local /health is 200" "code=\$(curl -fsSL --max-time '${CURL_MAX_TIME}' -o /dev/null -w '%{http_code}' http://127.0.0.1:${APP_PORT}/health); [[ \"\$code\" == \"200\" ]]"

if [[ -d "${PROJECT_DIR:-/opt/${PROJECT_NAME}}/build" ]]; then
  check_shell "frontend build references existing assets" "PROJECT_DIR='${PROJECT_DIR:-/opt/${PROJECT_NAME}}'; WEB_PATH='${WEB_PATH}'; PUBLIC_SCHEME='${PUBLIC_SCHEME:-https}'; PUBLIC_DOMAIN='${PUBLIC_DOMAIN:-}'; bash '${SCRIPT_DIR}/scripts/deploy/verify-frontend-release.sh' \"\$PROJECT_DIR/build\" \"\$WEB_PATH\" \"\$PUBLIC_SCHEME\" \"\$PUBLIC_DOMAIN\" >/dev/null"
else
  printf '[FAIL] %s\n' "frontend build directory exists"
  fail=$((fail + 1))
fi

if [[ -n "$PUBLIC_DOMAIN" ]]; then
  panel_path="/"
  [[ -n "$WEB_PATH" ]] && panel_path="/${WEB_PATH}/"
  panel_url="${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}${panel_path}"
  check_shell "public panel URL is reachable ($panel_url)" "code=\$(curl -fsSL --max-time '${CURL_MAX_TIME}' -o /dev/null -w '%{http_code}' '$panel_url'); [[ \"\$code\" == \"200\" || \"\$code\" == \"301\" || \"\$code\" == \"302\" || \"\$code\" == \"401\" ]]"
fi

if [[ "$MONITORING_ENABLED" == "true" ]]; then
  if [[ ! "$GRAFANA_HTTP_PORT" =~ ^[0-9]+$ ]] || (( GRAFANA_HTTP_PORT < 1 || GRAFANA_HTTP_PORT > 65535 )); then
    printf '[FAIL] %s\n' "Grafana port is invalid: $GRAFANA_HTTP_PORT"
    fail=$((fail + 1))
  else
    check "systemd grafana-server active" systemctl is-active --quiet grafana-server
    check_shell "local Grafana /login is reachable" "code=\$(curl -fsSL --max-time '${CURL_MAX_TIME}' -o /dev/null -w '%{http_code}' 'http://127.0.0.1:${GRAFANA_HTTP_PORT}/login'); [[ \"\$code\" == \"200\" || \"\$code\" == \"301\" || \"\$code\" == \"302\" ]]"
    if [[ -n "$PUBLIC_DOMAIN" ]]; then
      grafana_url="${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${GRAFANA_WEB_PATH}/login"
      check_shell "public Grafana URL is reachable ($grafana_url)" "code=\$(curl -fsSL --max-time '${CURL_MAX_TIME}' -o /dev/null -w '%{http_code}' '$grafana_url'); [[ \"\$code\" == \"200\" || \"\$code\" == \"301\" || \"\$code\" == \"302\" ]]"
    fi
  fi
fi

printf '\nSmoke summary: ok=%d fail=%d\n' "$ok" "$fail"
[[ "$fail" -eq 0 ]]
