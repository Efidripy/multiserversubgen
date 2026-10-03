#!/usr/bin/env bash
# Internal, authorised deployment helper. It never pulls or selects a remote ref.
set -euo pipefail
umask 077

REPO_DIR="${REPO_DIR:-$(pwd)}"
ROLLBACK_ON_FAIL="${ROLLBACK_ON_FAIL:-1}"
PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
PROJECT_DIR="${PROJECT_DIR:-/opt/${PROJECT_NAME}}"
APP_PORT="${APP_PORT:-666}"
WEB_PATH="${WEB_PATH:-my-panel}"
GRAFANA_WEB_PATH="${GRAFANA_WEB_PATH:-grafana}"
DEPLOY_REF="${DEPLOY_REF:-HEAD}"
RUNTIME_SECRETS_FILE="/etc/${PROJECT_NAME}/runtime-secrets.env"
SERVICE_UNIT="/etc/systemd/system/${PROJECT_NAME}.service"
SERVICE_TEMPLATE=""
STAGED_SERVICE_UNIT=""
SERVICE_UNIT_ROLLBACK=""
SERVICE_UNIT_WAS_PRESENT=0
PROMTAIL_CONFIG="/etc/promtail/config.yml"
PROMTAIL_CONFIG_ROLLBACK=""
PROMTAIL_CONFIG_WAS_PRESENT=0

fail() {
  printf 'Deploy refused: %s\n' "$*" >&2
  exit 1
}

require_safe_target() {
  [[ "$PROJECT_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail "invalid PROJECT_NAME"
  [[ "$PROJECT_DIR" == /* ]] || fail "PROJECT_DIR must be absolute"
  PROJECT_DIR="$(realpath -m -- "$PROJECT_DIR")"
  [[ "$PROJECT_DIR" == /opt/* && "$PROJECT_DIR" != /opt ]] || fail "PROJECT_DIR must stay below /opt"
  PROJECT_PARENT="$(dirname -- "$PROJECT_DIR")"
  PROJECT_BASENAME="$(basename -- "$PROJECT_DIR")"
  [[ "$PROJECT_BASENAME" == "$PROJECT_NAME" ]] || fail "PROJECT_DIR basename must match PROJECT_NAME"
  [[ "$APP_PORT" =~ ^[0-9]+$ ]] && (( APP_PORT >= 1 && APP_PORT <= 65535 )) || fail "invalid APP_PORT"
}

require_safe_target

validate_persistent_runtime_secrets() {
  local unit_definition

  [[ -f "$RUNTIME_SECRETS_FILE" ]] || fail "persistent runtime secrets are missing: $RUNTIME_SECRETS_FILE"
  [[ -r "$RUNTIME_SECRETS_FILE" ]] || fail "persistent runtime secrets are unreadable: $RUNTIME_SECRETS_FILE"
  [[ "$(stat -c '%a' "$RUNTIME_SECRETS_FILE")" == "600" ]] || fail "persistent runtime secrets must use mode 0600"
  grep -q '^WS_AUTH_SECRET=' "$RUNTIME_SECRETS_FILE" || fail "WS_AUTH_SECRET is missing from runtime secrets"
  grep -q '^SUBSCRIPTION_SIGNING_SECRET=' "$RUNTIME_SECRETS_FILE" || fail "SUBSCRIPTION_SIGNING_SECRET is missing from runtime secrets"
  [[ -f "$SERVICE_UNIT" ]] || fail "systemd unit is missing: $SERVICE_UNIT"
  unit_definition="$(systemctl cat "$PROJECT_NAME" 2>/dev/null)" \
    || fail "systemd unit could not be read: $PROJECT_NAME"
  grep -Fq "EnvironmentFile=${RUNTIME_SECRETS_FILE}" <<< "$unit_definition" \
    || fail "systemd unit does not load persistent runtime secrets"
  grep -Fq 'REQUIRE_PERSISTENT_SECRETS=true' <<< "$unit_definition" \
    || fail "systemd unit does not enforce persistent runtime secrets"
}

validate_persistent_runtime_secrets
REPO_DIR="$(realpath -e -- "$REPO_DIR")"
git -C "$REPO_DIR" rev-parse --is-inside-work-tree >/dev/null || fail "REPO_DIR is not a Git worktree"
DEPLOY_COMMIT="$(git -C "$REPO_DIR" rev-parse --verify "${DEPLOY_REF}^{commit}")" || fail "DEPLOY_REF is not a commit"
CURRENT_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD)"
[[ "$DEPLOY_COMMIT" == "$CURRENT_COMMIT" ]] || fail "checkout must already be at immutable DEPLOY_REF"
[[ -z "$(git -C "$REPO_DIR" status --porcelain)" ]] || fail "refuse dirty source worktree"
SERVICE_TEMPLATE="$REPO_DIR/systemd/${PROJECT_NAME}.service"
[[ -f "$SERVICE_TEMPLATE" ]] || fail "immutable systemd service template is missing: $SERVICE_TEMPLATE"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)-${DEPLOY_COMMIT:0:12}"
BACKUP_ROOT="/var/backups/${PROJECT_NAME}_deploy"
BACKUP_TAR="${BACKUP_ROOT}/project_${STAMP}.tgz"
BACKUP_SHA="${BACKUP_TAR}.sha256"
BACKUP_CONTENTS="${BACKUP_TAR}.contents"
STAGE_DIR="${PROJECT_PARENT}/.${PROJECT_BASENAME}.next-${STAMP}"
QUARANTINE_DIR="${PROJECT_PARENT}/.${PROJECT_BASENAME}.previous-${STAMP}"
HAD_PREVIOUS=0
SERVICE_STOPPED=0
STATE_DB="${PROJECT_DIR}/admin.db"

cleanup_stage() {
  [[ -d "$STAGE_DIR" ]] && rm -rf -- "$STAGE_DIR"
  [[ -n "$STAGED_SERVICE_UNIT" && -f "$STAGED_SERVICE_UNIT" ]] && rm -f -- "$STAGED_SERVICE_UNIT"
}

restore_service_unit() {
  if [[ "$SERVICE_UNIT_WAS_PRESENT" == "1" && -n "$SERVICE_UNIT_ROLLBACK" && -f "$SERVICE_UNIT_ROLLBACK" ]]; then
    install -o root -g root -m 0644 "$SERVICE_UNIT_ROLLBACK" "$SERVICE_UNIT" || true
  elif [[ "$SERVICE_UNIT_WAS_PRESENT" == "0" ]]; then
    rm -f -- "$SERVICE_UNIT" || true
  fi
  systemctl daemon-reload || true
}

render_runtime_service_unit() {
  local template="$1"
  local current="$2"
  local destination="$3"

  python3 - "$template" "$current" "$destination" "$PROJECT_NAME" "$PROJECT_DIR" <<'PYTHON'
from pathlib import Path
import re
import sys

template_path, current_path, destination_path, project_name, project_dir = sys.argv[1:]
template = Path(template_path).read_text(encoding="utf-8")
current = Path(current_path).read_text(encoding="utf-8")
environment_pattern = re.compile(r'^Environment="([^=]+)=(.*)"$', re.MULTILINE)
current_values = dict(environment_pattern.findall(current))

template = template.replace("__PROJECT_NAME__", project_name)
template = template.replace("/opt/sub-manager", project_dir)
for key, value in current_values.items():
    pattern = re.compile(rf'^Environment="{re.escape(key)}=.*"$', re.MULTILINE)
    template, count = pattern.subn(f'Environment="{key}={value}"', template)
    if count > 1:
        raise SystemExit(f"ambiguous Environment line for {key}")

app_port = current_values.get("APP_PORT", "666")
if not app_port.isdecimal() or not 1 <= int(app_port) <= 65535:
    raise SystemExit("current systemd APP_PORT is invalid")
template = template.replace('sport = :666', f'sport = :{app_port}')
template = template.replace('--port 666', f'--port {app_port}')
Path(destination_path).write_text(template, encoding="utf-8")
PYTHON
}

restore_previous() {
  systemctl stop "$PROJECT_NAME" || true
  restore_service_unit
  if [[ "$HAD_PREVIOUS" == "1" && -d "$QUARANTINE_DIR" ]]; then
    printf 'Deploy failed; restoring previous release.\n' >&2
    [[ -d "$PROJECT_DIR" ]] && rm -rf -- "$PROJECT_DIR"
    mv -- "$QUARANTINE_DIR" "$PROJECT_DIR"
  fi
  systemctl start "$PROJECT_NAME" || true
  systemctl reload nginx || true

  if [[ "$PROMTAIL_CONFIG_WAS_PRESENT" == "1" && -n "$PROMTAIL_CONFIG_ROLLBACK" && -f "$PROMTAIL_CONFIG_ROLLBACK" ]]; then
    install -o root -g root -m 0644 "$PROMTAIL_CONFIG_ROLLBACK" "$PROMTAIL_CONFIG" || true
    systemctl reset-failed promtail.service || true
    systemctl restart promtail.service || true
  fi
}

rollback_and_exit() {
  cleanup_stage
  [[ "$ROLLBACK_ON_FAIL" == "1" ]] && restore_previous
  trap - ERR
  exit 1
}

on_error() {
  local status=$?
  cleanup_stage
  [[ "$ROLLBACK_ON_FAIL" == "1" ]] && restore_previous
  exit "$status"
}
trap on_error ERR

wait_for_health() {
  local attempt code
  for attempt in {1..30}; do
    if code="$(curl --fail --silent --show-error --max-time 2 --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:${APP_PORT}/health")"; then
      [[ "$code" == "200" ]] && return 0
    fi
    sleep 1
  done
  return 1
}

reconcile_promtail_after_health() {
  local helper="$REPO_DIR/scripts/ops/reconcile-promtail-config.sh"
  local base_template="$REPO_DIR/monitoring/promtail/promtail-config.yml"
  local journal_template="$REPO_DIR/monitoring/promtail/promtail-journal-scrape.yml"

  systemctl cat promtail.service >/dev/null 2>&1 || return 0
  [[ -x "$helper" && -f "$base_template" && -f "$journal_template" ]] \
    || fail "Promtail is managed but the immutable reconciliation sources are incomplete"

  if [[ -f "$PROMTAIL_CONFIG" ]]; then
    PROMTAIL_CONFIG_ROLLBACK="$(mktemp /tmp/${PROJECT_NAME}-promtail-config.XXXXXX)"
    install -o root -g root -m 0600 "$PROMTAIL_CONFIG" "$PROMTAIL_CONFIG_ROLLBACK"
    PROMTAIL_CONFIG_WAS_PRESENT=1
  fi

  if ! PROMTAIL_CONFIG_TEMPLATE="$base_template" \
      PROMTAIL_JOURNAL_TEMPLATE="$journal_template" \
      PROMTAIL_CONFIG_PATH="$PROMTAIL_CONFIG" \
      "$helper" --restart-active; then
    fail "Promtail reconciliation failed after application health became ready"
  fi
}

mkdir -p -m 0700 -- "$BACKUP_ROOT" "$PROJECT_PARENT"
if [[ -f "$SERVICE_UNIT" ]]; then
  SERVICE_UNIT_ROLLBACK="$(mktemp "${BACKUP_ROOT}/${PROJECT_NAME}-service-unit.XXXXXX")"
  install -o root -g root -m 0600 "$SERVICE_UNIT" "$SERVICE_UNIT_ROLLBACK"
  SERVICE_UNIT_WAS_PRESENT=1
fi
STAGED_SERVICE_UNIT="$(mktemp "/tmp/${PROJECT_NAME}-service-unit.XXXXXX")"
render_runtime_service_unit "$SERVICE_TEMPLATE" "$SERVICE_UNIT" "$STAGED_SERVICE_UNIT"
systemd-analyze verify "$STAGED_SERVICE_UNIT"
if [[ -d "$PROJECT_DIR" ]]; then
  HAD_PREVIOUS=1
  [[ -f "$STATE_DB" ]] || fail "required runtime database is missing: $STATE_DB"
  command -v sqlite3 >/dev/null || fail "sqlite3 is required for a consistent runtime database backup"
fi

mkdir -m 0700 -- "$STAGE_DIR"
cp "$REPO_DIR"/backend/*.py "$STAGE_DIR/"
for pkg in core modules integrations routers services shared; do
  [[ -d "$REPO_DIR/backend/$pkg" ]] && cp -a "$REPO_DIR/backend/$pkg" "$STAGE_DIR/$pkg"
done

python3 -m venv "$STAGE_DIR/venv"
"$STAGE_DIR/venv/bin/pip" install --require-hashes -r "$REPO_DIR/backend/requirements.txt" >/dev/null
PYTHONPATH="$STAGE_DIR" "$STAGE_DIR/venv/bin/python" -m compileall -q "$STAGE_DIR"
[[ -x "$STAGE_DIR/venv/bin/uvicorn" ]] || fail "staged uvicorn executable is missing"
"$STAGE_DIR/venv/bin/uvicorn" --version >/dev/null

FRONTEND_NODE_OPTIONS="${FRONTEND_NODE_OPTIONS:---max-old-space-size=512}" \
  PROJECT_DIR="$STAGE_DIR" WEB_PATH="$WEB_PATH" GRAFANA_WEB_PATH="$GRAFANA_WEB_PATH" \
  SKIP_LIVE_VERIFY=1 bash "$REPO_DIR/scripts/deploy/build-and-publish-frontend.sh"

if [[ "$HAD_PREVIOUS" == "1" ]]; then
  systemctl stop "$PROJECT_NAME"
  SERVICE_STOPPED=1
  sqlite3 "$STATE_DB" 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null
  [[ "$(sqlite3 "$STATE_DB" 'PRAGMA integrity_check;' | tr -d '\r')" == "ok" ]] || fail "runtime database integrity check failed"
  tar -C "$PROJECT_PARENT" -czf "$BACKUP_TAR" -- "$PROJECT_BASENAME"
  tar -tzf "$BACKUP_TAR" > "$BACKUP_CONTENTS"
  grep -qx "${PROJECT_BASENAME}/" "$BACKUP_CONTENTS" || fail "backup layout is invalid"
  sha256sum "$BACKUP_TAR" > "$BACKUP_SHA"
  chmod 0600 "$BACKUP_TAR" "$BACKUP_SHA" "$BACKUP_CONTENTS"
  sqlite3 "$STATE_DB" ".backup '$STAGE_DIR/admin.db'"
  [[ "$(sqlite3 "$STAGE_DIR/admin.db" 'PRAGMA integrity_check;' | tr -d '\r')" == "ok" ]] || fail "staged runtime database backup integrity check failed"
  if [[ -f "$PROJECT_DIR/.encryption_key" ]]; then
    install -m 0600 "$PROJECT_DIR/.encryption_key" "$STAGE_DIR/.encryption_key"
  fi
  mv -- "$PROJECT_DIR" "$QUARANTINE_DIR"
fi
mv -- "$STAGE_DIR" "$PROJECT_DIR"
chmod 0755 "$PROJECT_DIR"
sed -i "1s|^#!.*$|#!${PROJECT_DIR}/venv/bin/python|" "$PROJECT_DIR/venv/bin/uvicorn"
[[ -x "$PROJECT_DIR/venv/bin/uvicorn" ]] || fail "deployed uvicorn executable is missing"
"$PROJECT_DIR/venv/bin/uvicorn" --version >/dev/null

install -o root -g root -m 0644 "$STAGED_SERVICE_UNIT" "$SERVICE_UNIT"
rm -f -- "$STAGED_SERVICE_UNIT"
STAGED_SERVICE_UNIT=""
systemctl daemon-reload
systemctl restart "$PROJECT_NAME"
SERVICE_STOPPED=0
nginx -t >/dev/null
systemctl reload nginx

if ! wait_for_health; then
  printf 'Deploy failed: health check did not become ready within 30 seconds\n' >&2
  rollback_and_exit
fi

reconcile_promtail_after_health

trap - ERR
[[ -n "$PROMTAIL_CONFIG_ROLLBACK" ]] && rm -f -- "$PROMTAIL_CONFIG_ROLLBACK"
[[ -d "$QUARANTINE_DIR" ]] && rm -rf -- "$QUARANTINE_DIR"
printf 'Deploy completed: commit=%s backup=%s\n' "$DEPLOY_COMMIT" "${BACKUP_TAR:-none}"
