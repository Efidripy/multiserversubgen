#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(pwd)}"
LOG_FILE="${LOG_FILE:-/opt/.sub_manager_install.log}"
ROLLBACK_ON_FAIL="${ROLLBACK_ON_FAIL:-1}"

if [[ ! -f "$LOG_FILE" ]]; then
  echo "Install log not found: $LOG_FILE"
  exit 1
fi

# shellcheck disable=SC1090
source "$LOG_FILE"

PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
PROJECT_DIR="${PROJECT_DIR:-/opt/${PROJECT_NAME}}"
APP_PORT="${APP_PORT:-666}"
WEB_PATH="${WEB_PATH:-my-panel}"
GRAFANA_WEB_PATH="${GRAFANA_WEB_PATH:-grafana}"

BACKUP_ROOT="/var/backups/${PROJECT_NAME}_deploy"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_TAR="${BACKUP_ROOT}/project_${STAMP}.tgz"
mkdir -p "$BACKUP_ROOT"

rollback() {
  echo "Deploy failed, starting rollback..."
  if [[ -f "$BACKUP_TAR" ]]; then
    rm -rf "$PROJECT_DIR"
    mkdir -p "$PROJECT_DIR"
    tar -xzf "$BACKUP_TAR" -C /
  fi
  systemctl restart "$PROJECT_NAME" || true
  systemctl reload nginx || true
}

trap '[[ "$ROLLBACK_ON_FAIL" == "1" ]] && rollback' ERR

if [[ -d "$PROJECT_DIR" ]]; then
  tar -czf "$BACKUP_TAR" "$PROJECT_DIR"
fi

cd "$REPO_DIR"
git pull --ff-only

if [[ ! -x "$PROJECT_DIR/venv/bin/pip" ]]; then
  python3 -m venv "$PROJECT_DIR/venv"
fi
"$PROJECT_DIR/venv/bin/pip" install -U pip >/dev/null
"$PROJECT_DIR/venv/bin/pip" install -r backend/requirements.txt >/dev/null
"$PROJECT_DIR/venv/bin/pip" install -r backend/requirements-dev.txt >/dev/null
"$PROJECT_DIR/venv/bin/python" -m pytest \
  backend/tests/test_runtime_controls.py \
  backend/tests/test_security_hardening.py \
  backend/tests/test_api_smoke.py \
  -q >/dev/null

mkdir -p "$PROJECT_DIR"
cp backend/*.py "$PROJECT_DIR/"
for pkg in core modules integrations routers services shared; do
  if [[ -d "backend/$pkg" ]]; then
    rm -rf "${PROJECT_DIR:?}/$pkg"
    cp -r "backend/$pkg" "$PROJECT_DIR/$pkg"
  fi
done

bash "$REPO_DIR/scripts/deploy/build-and-publish-frontend.sh"

systemctl daemon-reload
systemctl restart "$PROJECT_NAME"
nginx -t >/dev/null
systemctl reload nginx

code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${APP_PORT}/health")"
if [[ "$code" != "200" ]]; then
  echo "Health check failed: $code"
  exit 1
fi

trap - ERR
echo "Deploy completed successfully."
