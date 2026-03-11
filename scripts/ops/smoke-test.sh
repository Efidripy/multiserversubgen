#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${LOG_FILE:-/opt/.sub_manager_install.log}"
if [[ -f "$LOG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$LOG_FILE"
fi

PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
APP_PORT="${APP_PORT:-666}"
WEB_PATH="${WEB_PATH:-my-panel}"
PUBLIC_SCHEME="${PUBLIC_SCHEME:-https}"
PUBLIC_DOMAIN="${PUBLIC_DOMAIN:-}"

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

check "systemd $PROJECT_NAME active" systemctl is-active --quiet "$PROJECT_NAME"
check "nginx active" systemctl is-active --quiet nginx
check "nginx config valid" nginx -t >/dev/null 2>&1
check "local /health is 200" bash -lc "code=\$(curl -ksS -o /dev/null -w '%{http_code}' http://127.0.0.1:${APP_PORT}/health); [[ \"\$code\" == \"200\" ]]"

if [[ -n "$PUBLIC_DOMAIN" ]]; then
  panel_url="${PUBLIC_SCHEME}://${PUBLIC_DOMAIN}/${WEB_PATH}/"
  check "public panel URL is reachable ($panel_url)" bash -lc "code=\$(curl -ksS -o /dev/null -w '%{http_code}' '$panel_url'); [[ \"\$code\" == \"200\" || \"\$code\" == \"301\" || \"\$code\" == \"302\" ]]"
fi

printf '\nSmoke summary: ok=%d fail=%d\n' "$ok" "$fail"
[[ "$fail" -eq 0 ]]
