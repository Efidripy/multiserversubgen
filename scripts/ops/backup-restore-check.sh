#!/usr/bin/env bash
set -euo pipefail
umask 077

LOG_FILE="${LOG_FILE:-/opt/.sub_manager_install.log}"
if [[ -f "$LOG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$LOG_FILE"
fi

PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
PROJECT_DIR="${PROJECT_DIR:-/opt/${PROJECT_NAME}}"
DB_FILE="${DB_FILE:-${PROJECT_DIR}/admin.db}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${BACKUP_ROOT}/${PROJECT_NAME}_verify_${STAMP}"

if [[ ! -f "$DB_FILE" ]]; then
  echo "DB file not found: $DB_FILE"
  exit 1
fi

mkdir -p -m 0700 "$OUT_DIR"
BACKUP_FILE="$OUT_DIR/admin.db.bak"
RESTORE_FILE="$OUT_DIR/admin.db.restore-test"

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 is required"
  exit 1
fi

# Do not copy the main database while a running process may still have WAL
# pages outside the main file. SQLite's online backup API gives us a
# transactionally consistent snapshot without stopping or mutating the
# service's live database state.
sqlite3 "$DB_FILE" ".backup '$BACKUP_FILE'"
chmod 0600 "$BACKUP_FILE"

src_check="$(sqlite3 "$DB_FILE" 'PRAGMA integrity_check;' | tr -d '\r')"
bak_check="$(sqlite3 "$BACKUP_FILE" 'PRAGMA integrity_check;' | tr -d '\r')"

if [[ "$src_check" != "ok" || "$bak_check" != "ok" ]]; then
  echo "Integrity check failed"
  echo "source: $src_check"
  echo "backup: $bak_check"
  exit 1
fi

sqlite3 "$RESTORE_FILE" ".restore '$BACKUP_FILE'"
chmod 0600 "$RESTORE_FILE"
restored_check="$(sqlite3 "$RESTORE_FILE" 'PRAGMA integrity_check;' | tr -d '\r')"
[[ "$restored_check" == "ok" ]] || { echo "Restored DB integrity failed: $restored_check"; exit 1; }

echo "Backup/restore verification passed."
echo "Artifacts: $OUT_DIR"
