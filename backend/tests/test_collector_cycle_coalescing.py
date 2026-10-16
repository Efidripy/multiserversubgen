import asyncio
import sqlite3
import time
from threading import Lock
from types import SimpleNamespace

import pytest

from services.collector import SnapshotCollector
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
