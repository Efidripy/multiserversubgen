import logging
import sqlite3
from contextlib import closing

import pytest

from services import db_bootstrap


@pytest.fixture(autouse=True)
def reset_attach():
    db_bootstrap.configure_metrics_attach(None)
    yield
    db_bootstrap.configure_metrics_attach(None)


def startup(admin, metrics, enabled=True):
    db_bootstrap.initialize_databases(str(admin), str(metrics), enabled, logging.getLogger("test"))


def seed(admin):
    db_bootstrap.init_db(str(admin))
    with db_bootstrap.connect(str(admin)) as conn:
        conn.execute("INSERT INTO node_history VALUES(1,1,1,'node',1,1,0,0,0,0)")


def test_attached_reads_writes_and_retention(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        conn.execute("INSERT INTO node_history VALUES(2,2,2,'new',1,1,0,0,0,0)")
        assert conn.execute("SELECT count(*) FROM node_history").fetchone() == (2,)
        conn.execute("DELETE FROM node_history WHERE ts=1")
        assert not conn.execute("SELECT 1 FROM main.sqlite_master WHERE name='node_history'").fetchone()
    with sqlite3.connect(str(metrics)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("new",)]


def test_attached_writer_during_admin_write(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    startup(admin, metrics)
    with sqlite3.connect(str(admin)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO client_notes(node_id,email,client_identifier) VALUES(1,'x','x')")
        with db_bootstrap.connect(str(admin)) as conn:
            conn.execute("PRAGMA busy_timeout=100")
            conn.execute("INSERT INTO adguard_history VALUES(1,1,1,'x',1,0,0,0,0,0,0,'')")


def test_failed_migration_keeps_legacy(tmp_path, monkeypatch, caplog):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)

    def fail(*args):
        raise RuntimeError("private data")

    monkeypatch.setattr(db_bootstrap, "migrate_metrics_db", fail)
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("node",)]
        assert [row[1] for row in conn.execute("PRAGMA database_list")] == ["main"]
    assert "private data" not in caplog.text


def test_split_disabled(tmp_path, monkeypatch):
    from core.app_settings import load_app_settings

    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    monkeypatch.setenv("METRICS_DB_SPLIT_ENABLED", "0")
    startup(admin, metrics, load_app_settings(parse_mfa_users=lambda value: set()).metrics_db_split_enabled)
    assert not metrics.exists()
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT 1 FROM main.sqlite_master WHERE name='node_history'").fetchone()
        assert [row[1] for row in conn.execute("PRAGMA database_list")] == ["main"]


def test_restart_does_not_recreate_tables(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)
    startup(admin, metrics)
    startup(admin, metrics)
    with sqlite3.connect(str(admin)) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        for name in ("node_history", "adguard_history", "traffic_samples", "traffic_stats_snapshots"):
            assert name not in names
            assert name + "_migrated" in names
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("node",)]


def test_restart_recovers_incomplete_metrics_database(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)
    startup(admin, metrics)
    with closing(sqlite3.connect(str(metrics))) as conn:
        conn.execute("DROP TABLE node_history")
        conn.commit()
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("node",)]


def test_checkpoint_both_databases(tmp_path, monkeypatch):
    from services import telegram_retention

    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    startup(admin, metrics)
    statements = []
    original = telegram_retention.connect

    def traced(path):
        conn = original(path)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(telegram_retention, "connect", traced)
    assert telegram_retention.checkpoint_database(str(admin)) == 0
    assert "PRAGMA wal_checkpoint(TRUNCATE)" in statements
    assert "PRAGMA metrics.wal_checkpoint(TRUNCATE)" in statements


def test_restore_backup(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)
    startup(admin, metrics)
    with closing(sqlite3.connect(str(metrics))) as src, closing(sqlite3.connect(str(tmp_path / "metrics.db.bak"))) as dst:
        src.backup(dst)
    metrics.unlink()
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT node_name FROM node_history").fetchall() == [("node",)]


def test_restore_migrated_tables(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)
    startup(admin, metrics)
    metrics.unlink()
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT count(*) FROM node_history").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM main.node_history_migrated").fetchone() == (1,)


def test_empty_auto_create_and_operator_note(tmp_path):
    from core import worker_health
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    startup(admin, metrics)
    assert metrics.exists()
    assert any(note["name"] == "metrics_db_created_empty" for note in worker_health.operator_notes())
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT count(*) FROM node_history").fetchone() == (0,)


def test_empty_auto_create_disabled(tmp_path):
    from core import worker_health
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    db_bootstrap.initialize_databases(str(admin), str(metrics), True, logging.getLogger("test"), auto_create=False)
    assert not metrics.exists()
    assert any(note["name"] == "metrics_db_disabled" for note in worker_health.operator_notes())
    with db_bootstrap.connect(str(admin)) as conn:
        assert [row[1] for row in conn.execute("PRAGMA database_list")] == ["main"]
        for name in db_bootstrap._METRICS_TABLES:
            assert conn.execute(f'SELECT count(*) FROM "{name}"').fetchone() == (0,)


def test_corrupt_candidate_is_skipped(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    (tmp_path / "metrics.db.bak").write_bytes(b"corrupt")
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT count(*) FROM node_history").fetchone() == (0,)


def test_select_candidate_with_most_rows(tmp_path):
    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    for count, name in ((1, "metrics-one.db"), (2, "metrics-two.db.backup")):
        path = tmp_path / name
        db_bootstrap.init_metrics_db(str(path))
        with sqlite3.connect(str(path)) as conn:
            for i in range(count):
                conn.execute("INSERT INTO node_history VALUES(?,?,1,'node',1,1,0,0,0,0)", (i + 1, i))
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT count(*) FROM node_history").fetchone() == (2,)


@pytest.mark.parametrize("use_backup", [False, True])
def test_restore_over_corrupt_metrics(tmp_path, use_backup):
    from core import worker_health

    admin, metrics = tmp_path / "admin.db", tmp_path / "metrics.db"
    seed(admin)
    startup(admin, metrics)
    if use_backup:
        with closing(sqlite3.connect(str(metrics))) as src, closing(sqlite3.connect(str(tmp_path / "metrics.db.bak"))) as dst:
            src.backup(dst)
    metrics.write_bytes(b"invalid sqlite header")
    startup(admin, metrics)
    with db_bootstrap.connect(str(admin)) as conn:
        assert conn.execute("SELECT count(*) FROM node_history").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM main.node_history_migrated").fetchone() == (1,)
    copies = list(tmp_path.glob("metrics.db.corrupt-*"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == b"invalid sqlite header"
    assert any(note["name"] == "metrics_db_recovered" for note in worker_health.operator_notes())
