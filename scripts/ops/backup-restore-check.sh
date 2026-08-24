#!/usr/bin/env bash
set -euo pipefail
umask 077

LOG_FILE="${LOG_FILE:-/opt/.sub_manager_install.log}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/install_log.sh
source "${SCRIPT_DIR}/lib/install_log.sh"
install_log_source "$LOG_FILE"

PROJECT_NAME="${PROJECT_NAME:-sub-manager}"
PROJECT_DIR="${PROJECT_DIR:-/opt/${PROJECT_NAME}}"
DB_FILE="${DB_FILE:-${PROJECT_DIR}/admin.db}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups}"
MODE="verify"
MODE_SET="false"
OLDER_THAN_DAYS=""
APPLY_PRUNE="false"
VERIFY_ARTIFACT_GLOB=""
VERIFY_ARTIFACTS=()

fail() {
  printf 'backup verification: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage:
  backup-restore-check.sh [verify]
  backup-restore-check.sh list
  backup-restore-check.sh prune-verify-artifacts --older-than <days> [--apply]

`verify` is the default and creates a new consistency-check artifact.
`list` reports only this project's timestamped `_verify_` artifacts.
`prune-verify-artifacts` is dry-run by default; `--apply` is required to delete.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    verify|list|prune-verify-artifacts)
      [[ "$MODE_SET" == "false" ]] || fail "only one mode may be selected"
      MODE="$1"
      MODE_SET="true"
      ;;
    --older-than)
      [[ $# -ge 2 ]] || fail "--older-than requires a non-negative day count"
      OLDER_THAN_DAYS="$2"
      shift
      ;;
    --apply)
      APPLY_PRUNE="true"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown argument: $1"
      ;;
  esac
  shift
done

[[ "$PROJECT_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail "unsafe project name"
[[ "$BACKUP_ROOT" == /* ]] || fail "BACKUP_ROOT must be an absolute path"
if [[ "$MODE" != "prune-verify-artifacts" && ( -n "$OLDER_THAN_DAYS" || "$APPLY_PRUNE" == "true" ) ]]; then
  fail "--older-than and --apply are valid only for prune-verify-artifacts"
fi
VERIFY_ARTIFACT_GLOB="${PROJECT_NAME}_verify_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]"

resolve_backup_root() {
  [[ -e "$BACKUP_ROOT" ]] || return 1
  [[ -d "$BACKUP_ROOT" && ! -L "$BACKUP_ROOT" ]] || fail "BACKUP_ROOT must be an existing non-symlinked directory"
  BACKUP_ROOT="$(realpath -e -- "$BACKUP_ROOT")" || fail "cannot resolve BACKUP_ROOT"
}

collect_verify_artifacts() {
  VERIFY_ARTIFACTS=()
  resolve_backup_root || return 0
  mapfile -d '' -t VERIFY_ARTIFACTS < <(
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name "$VERIFY_ARTIFACT_GLOB" -print0 | LC_ALL=C sort -z
  )
}

list_verify_artifacts() {
  collect_verify_artifacts
  local artifact bytes total_bytes=0
  printf 'Verification artifacts for %s under %s:\n' "$PROJECT_NAME" "$BACKUP_ROOT"
  for artifact in "${VERIFY_ARTIFACTS[@]}"; do
    bytes="$(du -sb -- "$artifact" | awk '{print $1}')" || fail "cannot measure artifact: $artifact"
    total_bytes=$((total_bytes + bytes))
    printf '%s\t%s bytes\n' "$artifact" "$bytes"
  done
  printf 'Count: %s\nTotal: %s bytes\n' "${#VERIFY_ARTIFACTS[@]}" "$total_bytes"
}

prune_verify_artifacts() {
  [[ "$OLDER_THAN_DAYS" =~ ^[0-9]+$ ]] || fail "prune requires --older-than <non-negative-days>"
  (( OLDER_THAN_DAYS <= 36500 )) || fail "--older-than must not exceed 36500 days"
  resolve_backup_root || {
    printf 'No verification artifact root exists: %s\n' "$BACKUP_ROOT"
    return 0
  }

  VERIFY_ARTIFACTS=()
  mapfile -d '' -t VERIFY_ARTIFACTS < <(
    find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name "$VERIFY_ARTIFACT_GLOB" -mtime "+$OLDER_THAN_DAYS" -print0 | LC_ALL=C sort -z
  )
  printf 'Verification artifacts older than %s day(s): %s\n' "$OLDER_THAN_DAYS" "${#VERIFY_ARTIFACTS[@]}"
  local artifact
  for artifact in "${VERIFY_ARTIFACTS[@]}"; do
    printf '%s\n' "$artifact"
  done

  if [[ "$APPLY_PRUNE" != "true" ]]; then
    printf 'Dry-run only. Re-run with --apply to remove exactly these verification artifacts.\n'
    return 0
  fi

  for artifact in "${VERIFY_ARTIFACTS[@]}"; do
    [[ -d "$artifact" && ! -L "$artifact" ]] || fail "refusing changed or symlinked artifact: $artifact"
    [[ "$(dirname -- "$artifact")" == "$BACKUP_ROOT" ]] || fail "refusing artifact outside BACKUP_ROOT: $artifact"
    rm -rf --one-file-system -- "$artifact"
  done
  printf 'Removed %s verification artifact(s).\n' "${#VERIFY_ARTIFACTS[@]}"
}

case "$MODE" in
  list)
    list_verify_artifacts
    exit 0
    ;;
  prune-verify-artifacts)
    prune_verify_artifacts
    exit 0
    ;;
  verify)
    ;;
  *)
    fail "unsupported mode: $MODE"
    ;;
esac

[[ ! -L "$BACKUP_ROOT" ]] || fail "BACKUP_ROOT must not be a symlink"
mkdir -p -m 0700 "$BACKUP_ROOT"
resolve_backup_root || fail "cannot create BACKUP_ROOT: $BACKUP_ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${BACKUP_ROOT}/${PROJECT_NAME}_verify_${STAMP}"

if [[ ! -f "$DB_FILE" ]]; then
  fail "DB file not found: $DB_FILE"
fi

mkdir -p -m 0700 "$OUT_DIR"
BACKUP_FILE="$OUT_DIR/admin.db.bak"
RESTORE_FILE="$OUT_DIR/admin.db.restore-test"

if ! command -v sqlite3 >/dev/null 2>&1; then
  fail "sqlite3 is required"
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
