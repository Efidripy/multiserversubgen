import asyncio
import sqlite3
import time
from threading import Lock
from types import SimpleNamespace

import pytest

from services.collector import CollectorMode, SnapshotCollector
from services.db_bootstrap import connect, init_db
from services.metrics_runtime import MetricsRuntime


class _Metric:
    def __init__(self):
        self.values = []

    def labels(self, **labels):
        self.labels_value = labels
        return self

    def set(self, value):
        self.values.append((self.labels_value, value))

    def remove(self, *_args):
        return None


def _snapshot(node_id: int, *, available: bool = True) -> dict:
    return {
        "node_id": node_id,
        "name": f"node-{node_id}",
        "available": available,
        "status": "online" if available else "offline",
        "xray_running": available,
        "cpu": float(node_id),
        "online_clients": node_id,
        "traffic_total": node_id * 100,
        "poll_ms": node_id * 10.0,
        "timestamp": time.time(),
    }


def _collector(**kwargs) -> SnapshotCollector:
    return SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        **kwargs,
    )


def _metrics_runtime(db_path: str, state: dict) -> MetricsRuntime:
    metrics = [_Metric() for _ in range(6)]
    return MetricsRuntime(
        db_path=db_path,
        node_history_enabled=True,
        node_history_min_interval_sec=60,
        node_history_retention_days=30,
        node_metric_labels_state={},
        node_metric_labels_lock=Lock(),
        history_write_state=state,
        history_write_lock=Lock(),
        snapshot_collector=SimpleNamespace(
            get_mode=lambda: "idle", is_running=lambda: True, runtime_status=dict
        ),
        redis_get_client=lambda: None,
        redis_url="",
        node_availability_metric=metrics[0],
        node_xray_running_metric=metrics[1],
        node_cpu_percent_metric=metrics[2],
        node_online_clients_metric=metrics[3],
        node_traffic_total_bytes_metric=metrics[4],
        node_poll_duration_ms_metric=metrics[5],
    )


def test_default_cadence_keeps_active_freshness_and_bounded_idle_polling(monkeypatch):
    collector = _collector()

    assert collector.active_interval_sec == 90
    assert collector.idle_interval_sec == 300

    async def fake_run_blocking(_label, _function, node):
        return _snapshot(node["id"])

    monkeypatch.setattr(collector, "_run_blocking", fake_run_blocking)
    node = {"id": 1, "name": "alpha"}
    key = "id:1"

    collector._mode = CollectorMode.ACTIVE
    for _ in range(5):
        asyncio.run(collector._poll_node(node, key))
    assert collector._node_state[key]["interval"] == 90.0

    collector._mode = CollectorMode.IDLE
    asyncio.run(collector._poll_node(node, key))
    assert collector._node_state[key]["interval"] == 300.0


def test_activity_transitions_are_deterministic_and_do_not_infer_mode_from_due_work(
    monkeypatch,
):
    import services.collector as collector_module

    now = [1000.0]
    monkeypatch.setattr(collector_module.time, "time", lambda: now[0])
    ws_manager = SimpleNamespace(active_connections=[])
    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=ws_manager,
        active_interval_sec=90,
        idle_interval_sec=300,
        idle_after_sec=900,
    )

    collector._mode = CollectorMode.ACTIVE
    collector._last_ws_activity = 99.0
    collector._update_mode_based_on_activity()
    assert collector.get_mode() == "idle"
    assert collector._get_current_interval() == 300.0

    ws_manager.active_connections.append(object())
    collector._update_mode_based_on_activity()
    assert collector.get_mode() == "warming"
    assert collector._last_ws_activity == 1000.0

    now[0] = 1901.0
    ws_manager.active_connections.clear()
    collector._update_mode_based_on_activity()
    assert collector.get_mode() == "idle"

    collector._switch_mode(CollectorMode.ACTIVE)
    assert collector._get_current_interval() == 90.0


def test_idle_control_loop_waits_for_earliest_node_deadline_or_inventory_recheck():
    collector = _collector()
    now = 1000.0
    collector._node_state = {
        f"id:{node_id}": {"next_poll": now + 15.0 * node_id} for node_id in range(1, 15)
    }

    # Fourteen staggered nodes do not create an early fleet poll: the loop
    # wakes at the first individual deadline, which remains due at that time.
    assert collector._next_control_loop_timeout(now=now) == 15.0
    assert collector._next_control_loop_timeout(now=now + 14.0) == 1.0

    # A future fleet deadline does not cause 10-second empty inventory reads;
    # add/remove discovery is instead bounded by the explicit 60-second check.
    for state in collector._node_state.values():
        state["next_poll"] = now + 300.0
    assert collector._next_control_loop_timeout(now=now) == 60.0


def test_idle_control_loop_retries_unexpected_overdue_state_without_busy_loop():
    collector = _collector(min_interval_sec=3)
    collector._node_state = {"id:1": {"next_poll": 999.0}}

    assert collector._next_control_loop_timeout(now=1000.0) == 3.0


def test_force_and_activity_wake_scheduler_without_conflating_triggers():
    async def exercise():
        collector = _collector()
        collector._scheduler_loop = asyncio.get_running_loop()

        observed = collector._scheduler_wake_generation
        waiter = asyncio.create_task(
            collector._wait_for_scheduler_wake(30.0, observed_generation=observed)
        )
        await asyncio.sleep(0)
        await collector.force_poll_all()
        await asyncio.wait_for(waiter, timeout=0.2)
        assert collector._force_poll_event.is_set() is True

        collector._force_poll_event.clear()
        observed = collector._scheduler_wake_generation
        waiter = asyncio.create_task(
            collector._wait_for_scheduler_wake(30.0, observed_generation=observed)
        )
        await asyncio.sleep(0)
        collector.on_websocket_activity()
        await asyncio.wait_for(waiter, timeout=0.2)

        assert collector._force_poll_event.is_set() is False
        assert collector.get_mode() == CollectorMode.WARMING.value

    asyncio.run(exercise())


def test_scheduler_wake_queued_before_wait_is_not_lost():
    async def exercise():
        collector = _collector()
        observed = collector._scheduler_wake_generation

        # This is the clear/wait race boundary: the wake was queued after the
        # cycle captured its generation but before it started waiting.
        collector._mark_scheduler_wake()
        await asyncio.wait_for(
            collector._wait_for_scheduler_wake(30.0, observed_generation=observed),
            timeout=0.2,
        )

    asyncio.run(exercise())


def test_due_cycle_spreads_ordinary_polls_deterministically_without_delaying_force_poll(
    monkeypatch,
):
    collector = _collector(poll_jitter_sec=3.0)
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    async def fake_poll(node, _key):
        return _snapshot(node["id"])

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(collector, "_poll_node", fake_poll)
    due_nodes = [
        ({"id": 3, "name": "gamma"}, "id:3"),
        ({"id": 1, "name": "alpha"}, "id:1"),
        ({"id": 2, "name": "beta"}, "id:2"),
    ]

    snapshots = asyncio.run(collector._poll_due_nodes(due_nodes, force_poll=False))

    assert [snapshot["node_id"] for snapshot in snapshots] == [1, 2, 3]
    assert sleeps == [1.5, 3.0]
    assert collector._poll_delay_for_position(2, 3, force_poll=False) == 3.0
    assert collector._poll_delay_for_position(2, 3, force_poll=True) == 0.0


def test_snapshot_batch_uses_one_connection_and_keeps_offline_terminal_state(
    tmp_path, monkeypatch
):
    import services.collector as collector_module

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO nodes (id, name, ip, port, user, password) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "node-1", "127.0.0.1", "443", "root", "encrypted"),
                (2, "node-2", "127.0.0.2", "443", "root", "encrypted"),
            ],
        )
        conn.commit()

    real_connect = collector_module.connect
    connections = []

    def tracked_connect(path):
        connections.append(path)
        return real_connect(path)

    monkeypatch.setattr(collector_module, "connect", tracked_connect)
    asyncio.run(
        _collector(db_path=db_path)._persist_snapshots(
            [_snapshot(1), _snapshot(2, available=False)]
        )
    )

    assert connections == [db_path]
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT node_id, is_online FROM node_snapshots ORDER BY node_id"
        ).fetchall()
    assert rows == [(1, 1), (2, 0)]


def test_history_batch_is_single_transaction_deduplicated_and_retries_after_failed_write(
    tmp_path, monkeypatch
):
    import services.metrics_runtime as metrics_module

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    state = {"last_by_node": {}, "last_cleanup_ts": time.time()}
    runtime = _metrics_runtime(db_path, state)
    real_connect = metrics_module.connect

    def failing_connect(_path):
        raise sqlite3.OperationalError("injected write failure")

    monkeypatch.setattr(metrics_module, "connect", failing_connect)
    with pytest.raises(sqlite3.OperationalError):
        runtime.record_node_snapshots([_snapshot(1), _snapshot(2, available=False)])
    assert state["last_by_node"] == {}

    connections = []

    def tracked_connect(path):
        connections.append(path)
        return real_connect(path)

    monkeypatch.setattr(metrics_module, "connect", tracked_connect)
    runtime.record_node_snapshots([_snapshot(1), _snapshot(2, available=False)])
    runtime.record_node_snapshots([_snapshot(1), _snapshot(2, available=False)])

    assert connections == [db_path]
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT node_id, available, ts FROM node_history ORDER BY node_id"
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [(1, 1), (2, 0)]
    assert len({row[2] for row in rows}) == 1


def test_partial_inventory_does_not_write_zero_traffic_history(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    state = {"last_by_node": {}, "last_cleanup_ts": time.time()}
    runtime = _metrics_runtime(db_path, state)
    partial = {**_snapshot(1), "inbounds_available": False, "online_clients": None, "traffic_total": None}

    runtime.record_node_snapshots([partial])

    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM node_history").fetchone()[0] == 0
