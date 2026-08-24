import os
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "backup-restore-check.sh"


def _bash() -> str:
    git_bash = Path("E:/Git/bin/bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    bash = shutil.which("bash")
    assert bash, "bash is required for backup verification retention tests"
    return bash


def test_verify_artifact_prune_is_opt_in_and_scope_limited():
    fixture = r'''
if command -v cygpath >/dev/null 2>&1; then
    script="$(cygpath -u "$BACKUP_VERIFY_SCRIPT")"
else
    script="$BACKUP_VERIFY_SCRIPT"
fi
root="$(mktemp -d)"
trap 'rm -rf -- "$root"' EXIT
mkdir -p "$root/backups/sub-manager_verify_20200101_000000"
mkdir -p "$root/backups/sub-manager_verify_20990101_000000"
mkdir -p "$root/backups/sub-manager_backup_20200101_000000"
mkdir -p "$root/backups/other_verify_20200101_000000"
mkdir -p "$root/backups/sub-manager_verify_invalid"
touch -d '2020-01-01 00:00:00 UTC' "$root/backups/sub-manager_verify_20200101_000000"
touch -d '2099-01-01 00:00:00 UTC' "$root/backups/sub-manager_verify_20990101_000000"

BACKUP_ROOT="$root/backups" "$script" list > "$root/list.txt"
grep -q 'Count: 2' "$root/list.txt"
grep -q 'sub-manager_verify_20200101_000000' "$root/list.txt"
grep -q 'sub-manager_verify_20990101_000000' "$root/list.txt"
if grep -q 'sub-manager_backup_20200101_000000\|other_verify_20200101_000000\|sub-manager_verify_invalid' "$root/list.txt"; then
    exit 1
fi

BACKUP_ROOT="$root/backups" "$script" prune-verify-artifacts --older-than 30 > "$root/dry-run.txt"
grep -q 'Dry-run only' "$root/dry-run.txt"
test -d "$root/backups/sub-manager_verify_20200101_000000"

if BACKUP_ROOT="$root/backups" "$script" prune-verify-artifacts --apply >/dev/null 2>&1; then
    exit 1
fi
test -d "$root/backups/sub-manager_verify_20200101_000000"

if BACKUP_ROOT="$root/backups" "$script" list --apply >/dev/null 2>&1; then
    exit 1
fi
test -d "$root/backups/sub-manager_verify_20200101_000000"

BACKUP_ROOT="$root/backups" "$script" prune-verify-artifacts --older-than 30 --apply > "$root/apply.txt"
grep -q 'Removed 1 verification artifact' "$root/apply.txt"
test ! -e "$root/backups/sub-manager_verify_20200101_000000"
test -d "$root/backups/sub-manager_verify_20990101_000000"
test -d "$root/backups/sub-manager_backup_20200101_000000"
test -d "$root/backups/other_verify_20200101_000000"
test -d "$root/backups/sub-manager_verify_invalid"
'''
    environment = os.environ | {"BACKUP_VERIFY_SCRIPT": str(SCRIPT)}
    result = subprocess.run(
        [_bash(), "-e", "-u", "-o", "pipefail", "-c", fixture],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
