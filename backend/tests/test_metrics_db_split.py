import sqlite3

import pytest

from services.db_bootstrap import connect, init_db, init_metrics_db, migrate_metrics_db


def _seed(path):
    init_db(str(path))
    with connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO node_history(ts,node_id,node_name,available,xray_running,cpu,online_clients,traffic_total,poll_ms) "
            "VALUES(1,1,'node',1,1,0,0,0,0)"
        )


def test_metrics_migration_and_repeat(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    _seed(admin)
    migrate_metrics_db(str(admin), str(metrics), batch_size=1)
    migrate_metrics_db(str(admin), str(metrics), batch_size=1)
    with connect(str(admin)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "node_history_migrated" in names
        assert "node_history" not in names
    with connect(str(metrics)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("node",)]


def test_retry_replaces_stale_metrics(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    _seed(admin)
    init_metrics_db(str(metrics))
    with connect(str(metrics)) as conn:
        conn.execute("CREATE TABLE metrics_migration_staging (x INTEGER)")
        conn.execute("INSERT INTO node_history VALUES(1,2,1,'different',1,1,0,0,0,0)")
    migrate_metrics_db(str(admin), str(metrics), batch_size=1)
    with connect(str(metrics)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("node",)]


def test_metrics_writer_does_not_block_on_admin_writer(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    _seed(admin)
    init_metrics_db(str(metrics))
    with connect(str(admin)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        with sqlite3.connect(str(metrics), timeout=0.1) as target:
            target.execute("INSERT INTO node_history VALUES(1,1,1,'node',1,1,0,0,0,0)")


def test_backup_and_restore_check_cover_both_files(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    _seed(admin)
    init_metrics_db(str(metrics))
    with connect(str(metrics)) as conn:
        conn.execute("INSERT INTO node_history VALUES(1,1,1,'metrics',1,1,0,0,0,0)")
    scripts = Path(__file__).resolve().parents[2] / "scripts" / "deploy"
    admin_backup, metrics_backup = tmp_path / "admin.bak", tmp_path / "metrics.bak"
    subprocess.run(
        [sys.executable, str(scripts / "sqlite-backup.py"), str(admin), str(admin_backup),
         "--metrics-database", str(metrics), "--metrics-backup", str(metrics_backup)], check=True,
    )
    subprocess.run(
        [sys.executable, str(scripts / "sqlite-restore-check.py"), str(admin_backup),
         "--metrics-backup", str(metrics_backup), "--temp-dir", str(tmp_path)], check=True,
    )
    with sqlite3.connect(str(metrics_backup)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchone() == ("metrics",)


def test_interrupted_batch_copy_preserves_admin(tmp_path, monkeypatch):
    from services import db_bootstrap

    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    _seed(admin)
    with connect(str(admin)) as conn:
        conn.execute(
            "INSERT INTO node_history(ts,node_id,node_name,available,xray_running,cpu,online_clients,traffic_total,poll_ms) "
            "VALUES(2,2,'second',1,1,0,0,0,0)"
        )
    original = db_bootstrap.connect_metrics
    calls = 0

    def interrupted(path):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise sqlite3.OperationalError("simulated interruption")
        return original(path)

    monkeypatch.setattr(db_bootstrap, "connect_metrics", interrupted)
    with pytest.raises(sqlite3.OperationalError, match="simulated interruption"):
        migrate_metrics_db(str(admin), str(metrics), batch_size=1)
    with connect(str(admin)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM node_history").fetchone()[0] == 2
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='node_history_migrated'").fetchone()
    with connect(str(admin)) as conn:
        conn.execute("UPDATE node_history SET node_name='changed' WHERE id=1")
        conn.execute("DELETE FROM node_history WHERE id=2")
        expected = conn.execute("SELECT * FROM node_history").fetchall()
    monkeypatch.setattr(db_bootstrap, "connect_metrics", original)
    migrate_metrics_db(str(admin), str(metrics), batch_size=1)
    migrate_metrics_db(str(admin), str(metrics), batch_size=1)
    with connect(str(metrics)) as conn:
        assert conn.execute("SELECT * FROM node_history").fetchall() == expected
    with connect(str(admin)) as conn:
        assert conn.execute("SELECT * FROM node_history_migrated").fetchall() == expected
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='node_history'").fetchone()


def test_migration_refuses_to_wipe_an_active_metrics_store(tmp_path):
    import pytest
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    _seed(admin)
    init_metrics_db(str(metrics))
    with connect(str(metrics)) as conn:
        conn.execute("INSERT INTO node_history VALUES(1,2,1,'active',1,1,0,0,0,0)")
    with pytest.raises(RuntimeError):
        migrate_metrics_db(str(admin), str(metrics))
    with connect(str(metrics)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("active",)]
