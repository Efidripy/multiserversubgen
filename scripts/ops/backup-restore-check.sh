#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${LOG_FILE:-/opt/.sub_manager_install.log}"
if [[ -f "$LOG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$LOG_FILE"
fi

PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
PROJECT_DIR="${PROJECT_DIR:-/opt/${PROJECT_NAME}}"
DB_FILE="${DB_FILE:-${PROJECT_DIR}/nodes.db}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${BACKUP_ROOT}/${PROJECT_NAME}_verify_${STAMP}"

if [[ ! -f "$DB_FILE" ]]; then
  echo "DB file not found: $DB_FILE"
  exit 1
fi

mkdir -p "$OUT_DIR"
cp -a "$DB_FILE" "$OUT_DIR/nodes.db.bak"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required"
  exit 1
fi

src_check="$(sqlite3 "$DB_FILE" 'PRAGMA integrity_check;' | tr -d '\r')"
bak_check="$(sqlite3 "$OUT_DIR/nodes.db.bak" 'PRAGMA integrity_check;' | tr -d '\r')"

if [[ "$src_check" != "ok" || "$bak_check" != "ok" ]]; then
  echo "Integrity check failed"
  echo "source: $src_check"
  echo "backup: $bak_check"
  exit 1
fi

sqlite3 "$OUT_DIR/nodes.db.restore-test" "ATTACH DATABASE '$OUT_DIR/nodes.db.bak' AS src; VACUUM INTO '$OUT_DIR/nodes.db.restored'; DETACH DATABASE src;" >/dev/null 2>&1 || true
if [[ -f "$OUT_DIR/nodes.db.restored" ]]; then
  restored_check="$(sqlite3 "$OUT_DIR/nodes.db.restored" 'PRAGMA integrity_check;' | tr -d '\r')"
  [[ "$restored_check" == "ok" ]] || { echo "Restored DB integrity failed: $restored_check"; exit 1; }
fi

echo "Backup/restore verification passed."
echo "Artifacts: $OUT_DIR"
