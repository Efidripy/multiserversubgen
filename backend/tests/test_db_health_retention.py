import logging
import sqlite3

from services.db_bootstrap import connect, init_db
from services.runtime_support import AuditQueueRuntime
from services.telegram_retention import checkpoint_database, maintain_database_batch


def test_retention_preserves_unfinished_records(tmp_path):
    path = str(tmp_path / "admin.db")
    init_db(path)
    with connect(path) as conn:
        conn.executemany(
            "INSERT INTO telegram_updates (update_id, update_type, payload_digest, status, processed_at) VALUES (?, 'x', 'x', ?, '2000-01-01')",
            [(1, 'processed'), (2, 'received'), (3, 'processed')],
        )
        conn.execute("INSERT INTO telegram_update_responses (update_id, response_index, chat_id, text, status) VALUES (3, 0, 1, 'x', 'prepared')")
        conn.executemany("INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, status, updated_at) VALUES ('x', 'x', ?, ?, '2000-01-01')", [('a', 'sent'), ('b', 'retry')])
    maintain_database_batch(path)
    with connect(path) as conn:
        assert conn.execute("SELECT update_id FROM telegram_updates ORDER BY update_id").fetchall() == [(2,), (3,)]
        assert conn.execute("SELECT dedupe_key FROM telegram_outbox").fetchall() == [('b',)]


def test_checkpoint_reports_sizes(tmp_path, caplog):
    path = str(tmp_path / "admin.db")
    init_db(path)
    with caplog.at_level(logging.INFO, logger="sub_manager"):
        checkpoint_database(path)
    assert "SQLite size: db=" in caplog.text


def test_audit_locked_batch_retried_and_retained(monkeypatch, caplog):
    import services.runtime_support as module

    calls = []
    def locked(_path):
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(module, "connect", locked)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    runtime = AuditQueueRuntime(db_path="unused", batch_size=1, idle_sleep_sec=1, active_sleep_sec=1, logger=logging.getLogger("audit-test"))
    runtime.enqueue_event({"event": "test"})
    assert runtime.persist_memory_batch(1) == 0
    assert len(calls) == 3
    assert runtime.pending_count() == 1
    assert "failed batches=1" in caplog.text


def test_long_write_transaction_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DB_WRITE_WARNING_SECONDS", "0")
    with caplog.at_level(logging.WARNING, logger="sub_manager"):
        with connect(str(tmp_path / "db")) as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
    assert "SQLite write transaction held" in caplog.text


def test_audit_recovers_after_lock(tmp_path, monkeypatch):
    import services.runtime_support as module

    path = str(tmp_path / "admin.db")
    init_db(path)
    original = module.connect
    calls = []
    def flaky(db_path):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(db_path)
    monkeypatch.setattr(module, "connect", flaky)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    runtime = AuditQueueRuntime(db_path=path, batch_size=1, idle_sleep_sec=1, active_sleep_sec=1, logger=logging.getLogger("audit-test"))
    runtime.enqueue_event({"event": "test"})
    assert runtime.persist_memory_batch(1) == 1
    assert runtime.pending_count() == 0
    with connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)


def test_retention_keeps_provisioning_snapshots_used_by_reminders(tmp_path):
    path = str(tmp_path / "admin.db")
    with connect(path) as conn:
        conn.execute("CREATE TABLE telegram_updates (update_id INTEGER, status TEXT, processed_at TEXT)")
        conn.execute("CREATE TABLE telegram_update_responses (update_id INTEGER, status TEXT)")
        conn.execute("CREATE TABLE telegram_outbox (id INTEGER, status TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE telegram_provisioning_jobs (id INTEGER, status TEXT, finished_at TEXT)")
        conn.execute("CREATE TABLE telegram_provisioning_attempts (id INTEGER, job_id INTEGER, status TEXT)")
        conn.executemany("INSERT INTO telegram_provisioning_jobs VALUES (?, ?, '2000-01-01')", [(1, 'succeeded'), (2, 'running')])
        conn.executemany("INSERT INTO telegram_provisioning_attempts VALUES (?, ?, ?)", [(1, 1, 'succeeded'), (2, 1, 'pending'), (3, 2, 'succeeded')])
    maintain_database_batch(path, batch_size=1)
    with connect(path) as conn:
        assert conn.execute("SELECT id FROM telegram_provisioning_attempts ORDER BY id").fetchall() == [(1,), (2,), (3,)]
        assert conn.execute("SELECT id FROM telegram_provisioning_jobs ORDER BY id").fetchall() == [(1,), (2,)]
