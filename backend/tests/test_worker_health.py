import logging

from core import worker_health


def test_worker_health_failure_and_recovery(caplog):
    name = "test.health.failure"
    worker_health.register(name, 60)
    worker_health.mark_start(name)
    with caplog.at_level(logging.INFO, logger="core.worker_health"):
        for _ in range(6):
            worker_health.mark_failure(name, "RuntimeError")
        record = next(row for row in worker_health.snapshot() if row["name"] == name)
        assert not record["healthy"]
        assert record["consecutive_failures"] == 6
        assert record["last_error_code"] == "RuntimeError"
        worker_health.mark_success(name)
        record = next(row for row in worker_health.snapshot() if row["name"] == name)
        assert record["healthy"] and record["last_success_at"]
        assert record["consecutive_failures"] == 0
    assert sum(record.levelno == logging.ERROR for record in caplog.records) == 1
    assert sum(record.levelno == logging.INFO for record in caplog.records) == 1


def test_worker_health_stale_and_metric(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(worker_health.time, "time", lambda: now[0])
    name = "test.health.stale"
    worker_health.register(name, 10)
    worker_health.mark_success(name)
    now[0] += 31
    assert worker_health._metric_value(name) == 0
    worker_health.mark_success(name)
    assert worker_health._metric_value(name) == 1


def test_audit_runtime_reports_retained_batch_after_failed_persist(tmp_path):
    import logging

    from services.runtime_support import AuditQueueRuntime

    # No audit_events table exists, so the insert fails and the batch is retained.
    runtime = AuditQueueRuntime(
        db_path=str(tmp_path / "admin.db"),
        batch_size=1,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        logger=logging.getLogger("test.audit.retained"),
    )
    assert runtime.has_retained_batch() is False
    runtime.enqueue_event({"request_id": "x"})
    assert runtime.persist_memory_batch(1) == 0
    assert runtime.has_retained_batch() is True
