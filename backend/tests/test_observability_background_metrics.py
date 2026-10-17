import asyncio
import logging
import time
from threading import Lock
from types import SimpleNamespace

from services.collector import SnapshotCollector
from services.db_bootstrap import connect, init_db
from services.metrics_runtime import MetricsRuntime
from services.runtime_support import AuditQueueRuntime


class _Histogram:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.observations = []
        self._labels = None

    def labels(self, **labels):
        if self.fail:
            raise RuntimeError("metric labels failed")
        self._labels = labels
        return self

    def observe(self, value):
        if self.fail:
            raise RuntimeError("metric observe failed")
        self.observations.append((self._labels, value))


class _Gauge:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.values = []

    def set(self, value):
        if self.fail:
            raise RuntimeError("metric set failed")
        self.values.append(value)


class _Counter:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.increments = []
        self._labels = None

    def labels(self, **labels):
        if self.fail:
            raise RuntimeError("metric labels failed")
        self._labels = labels
        return self

    def inc(self, value=1):
        if self.fail:
            raise RuntimeError("metric inc failed")
        self.increments.append((self._labels, value))


class _NodeMetric:
    def labels(self, **_labels):
        return self

    def set(self, _value):
        return None

    def remove(self, *_args):
        return None


def _snapshot(node_id=1):
    return {
        "node_id": node_id,
        "name": f"node-{node_id}",
        "available": True,
        "xray_running": True,
        "cpu": 1.0,
        "online_clients": 1,
        "traffic_total": 10.0,
        "poll_ms": 2.0,
    }


def _collector(*, fetch_nodes, metric, clock, on_snapshots=None):
    return SnapshotCollector(
        fetch_nodes=fetch_nodes,
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        collector_cycle_duration_metric=metric,
        cycle_clock=clock,
        on_snapshots=on_snapshots,
        poll_jitter_sec=0,
    )


def _run_one_collector_cycle(collector):
    collector._get_current_interval = lambda: 0
    asyncio.run(collector._run())


def test_collector_cycle_duration_observes_only_completed_due_node_cycles(monkeypatch):
    metric = _Histogram()
    clock_values = iter((10.0, 12.5))
    collector = _collector(
        fetch_nodes=lambda: [{"id": 1, "name": "alpha"}],
        metric=metric,
        clock=lambda: next(clock_values),
        on_snapshots=lambda _snapshots: setattr(collector, "_running", False),
    )

    async def poll_due(_due_nodes, *, force_poll):
        assert force_poll is False
        return [_snapshot()]

    monkeypatch.setattr(collector, "_poll_due_nodes", poll_due)
    collector._running = True
    _run_one_collector_cycle(collector)

    assert metric.observations == [(None, 2.5)]


def test_collector_cycle_duration_metric_failure_does_not_abort_completed_cycle(
    monkeypatch,
):
    collector = _collector(
        fetch_nodes=lambda: [{"id": 1, "name": "alpha"}],
        metric=_Histogram(fail=True),
        clock=lambda: 1.0,
        on_snapshots=lambda _snapshots: setattr(collector, "_running", False),
    )

    async def poll_due(_due_nodes, *, force_poll):
        return [_snapshot()]

    monkeypatch.setattr(collector, "_poll_due_nodes", poll_due)
    collector._running = True
    _run_one_collector_cycle(collector)

    assert collector.runtime_status()["last_cycle"]["due_nodes"] == 1


def test_collector_cycle_duration_skips_no_due_and_failed_cycles():
    no_due_metric = _Histogram()
    no_due_collector = _collector(
        fetch_nodes=lambda: setattr(no_due_collector, "_running", False) or [],
        metric=no_due_metric,
        clock=lambda: 1.0,
    )
    no_due_collector._running = True
    _run_one_collector_cycle(no_due_collector)
    assert no_due_metric.observations == []

    failed_metric = _Histogram()

    def fail_fetch():
        failed_collector._running = False
        raise RuntimeError("collector fetch failed")

    failed_collector = _collector(
        fetch_nodes=fail_fetch,
        metric=failed_metric,
        clock=lambda: 1.0,
    )
    failed_collector._running = True
    _run_one_collector_cycle(failed_collector)
    assert failed_metric.observations == []


def test_collector_batch_metric_is_semantic_and_metric_failure_isolated(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO nodes (id, name, ip, port, user, password) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (node_id, f"node-{node_id}", "127.0.0.1", "443", "root", "encrypted")
                for node_id in (1, 2, 3)
            ],
        )
        conn.commit()
    metric = _Histogram()
    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        db_path=db_path,
        sqlite_batch_rows_metric=metric,
    )

    collector._upsert_snapshot_rows([_snapshot(1), _snapshot(2)])
    assert metric.observations == [({"operation": "collector_snapshot_upsert"}, 2)]

    failing_metric = _Histogram(fail=True)
    collector._sqlite_batch_rows_metric = failing_metric
    collector._upsert_snapshot_rows([_snapshot(3)])
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM node_snapshots").fetchone()[0] == 3


def _metrics_runtime(db_path, sqlite_batch_rows_metric):
    node_metric = _NodeMetric()
    return MetricsRuntime(
        db_path=db_path,
        node_history_enabled=True,
        node_history_min_interval_sec=1,
        node_history_retention_days=30,
        node_metric_labels_state={},
        node_metric_labels_lock=Lock(),
        history_write_state={"last_by_node": {}, "last_cleanup_ts": time.time()},
        history_write_lock=Lock(),
        snapshot_collector=SimpleNamespace(
            get_mode=lambda: "idle", is_running=lambda: True, runtime_status=dict
        ),
        redis_get_client=lambda: None,
        redis_url="",
        node_availability_metric=node_metric,
        node_xray_running_metric=node_metric,
        node_cpu_percent_metric=node_metric,
        node_online_clients_metric=node_metric,
        node_traffic_total_bytes_metric=node_metric,
        node_poll_duration_ms_metric=node_metric,
        sqlite_batch_rows_metric=sqlite_batch_rows_metric,
    )


def test_history_batch_metric_tracks_committed_rows_only(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    metric = _Histogram()
    runtime = _metrics_runtime(db_path, metric)

    runtime.record_node_snapshots([_snapshot(1), _snapshot(2)])

    assert metric.observations == [({"operation": "node_history_insert"}, 2)]


def test_history_batch_metric_failure_does_not_rollback_commit(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    runtime = _metrics_runtime(db_path, _Histogram(fail=True))

    runtime.record_node_snapshots([_snapshot(1)])

    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM node_history").fetchone()[0] == 1


def test_audit_metrics_track_queue_transitions_drops_and_semantic_batches(
    tmp_path, monkeypatch
):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    depth = _Gauge()
    drops = _Counter()
    rows = _Histogram()
    runtime = AuditQueueRuntime(
        db_path=db_path,
        batch_size=2,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        memory_queue_max_size=1,
        logger=logging.getLogger("test.audit.metrics"),
        memory_queue_depth_metric=depth,
        audit_events_dropped_metric=drops,
        sqlite_batch_rows_metric=rows,
    )

    assert depth.values == [0]
    assert runtime.enqueue_event({"request_id": "one"}) is True
    assert runtime.enqueue_event({"request_id": "full"}) is False
    runtime.close_admission()
    assert runtime.enqueue_event({"request_id": "closed"}) is False
    assert runtime.persist_memory_batch(2) == 1
    assert runtime.drain_batch(2) == 1

    assert depth.values == [0, 1, 0]
    assert drops.increments == [
        ({"reason": "full"}, 1),
        ({"reason": "closed"}, 1),
    ]
    assert rows.observations == [
        ({"operation": "audit_memory_persist"}, 1),
        ({"operation": "audit_event_drain"}, 1),
    ]

    failing_db_runtime = AuditQueueRuntime(
        db_path=db_path,
        batch_size=1,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        logger=logging.getLogger("test.audit.persist-error"),
        audit_events_dropped_metric=drops,
    )
    assert failing_db_runtime.enqueue_event({"request_id": "persist-error"}) is True

    def fail_connect(*_args, **_kwargs):
        raise OSError("sqlite unavailable")

    monkeypatch.setattr("services.runtime_support.connect", fail_connect)
    assert failing_db_runtime.persist_memory_batch(1) == 0
    assert ({"reason": "persist_error"}, 1) in drops.increments


def test_metric_failures_do_not_change_audit_outcomes(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    runtime = AuditQueueRuntime(
        db_path=db_path,
        batch_size=1,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        memory_queue_max_size=1,
        logger=logging.getLogger("test.audit.metric-failure"),
        memory_queue_depth_metric=_Gauge(fail=True),
        audit_events_dropped_metric=_Counter(fail=True),
        sqlite_batch_rows_metric=_Histogram(fail=True),
    )

    assert runtime.enqueue_event({"request_id": "one"}) is True
    assert runtime.enqueue_event({"request_id": "full"}) is False
    assert runtime.persist_memory_batch(1) == 1
    assert runtime.drain_batch(1) == 1
