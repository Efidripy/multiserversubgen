import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "deploy"


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_online_backup_contains_committed_wal_data_and_restores(tmp_path):
    source, backup = tmp_path / "source.db", tmp_path / "backup.db"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE items (value TEXT)")
        db.execute("INSERT INTO items VALUES ('saved')")
        db.commit()
        result = run_script("sqlite-backup.py", source, backup)
        assert result.returncode == 0, result.stderr
        assert sqlite3.connect(backup).execute("SELECT value FROM items").fetchall() == [("saved",)]
    result = run_script("sqlite-restore-check.py", backup, "--temp-dir", tmp_path)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.glob("sqlite-restore-*"))


def test_backup_refuses_to_overwrite_existing_file(tmp_path):
    source, backup = tmp_path / "source.db", tmp_path / "backup.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE items (value TEXT)")
    backup.write_bytes(b"preserve")
    assert run_script("sqlite-backup.py", source, backup).returncode != 0
    assert backup.read_bytes() == b"preserve"


def test_backup_failure_removes_incomplete_output(tmp_path):
    source, backup = tmp_path / "source.db", tmp_path / "backup.db"
    source.write_bytes(b"invalid")
    assert run_script("sqlite-backup.py", source, backup).returncode != 0
    assert not backup.exists()


def test_restore_rejects_invalid_backup(tmp_path):
    backup = tmp_path / "backup.db"
    backup.write_bytes(b"invalid")
    assert run_script("sqlite-restore-check.py", backup, "--temp-dir", tmp_path).returncode != 0
    assert not list(tmp_path.glob("sqlite-restore-*"))
