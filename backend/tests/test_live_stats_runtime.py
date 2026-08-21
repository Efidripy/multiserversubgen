import os
import sys
from copy import deepcopy
from threading import Event, Lock, Thread
from types import SimpleNamespace


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.live_stats_runtime import LiveStatsRuntime


class DummyClientManager:
    def __init__(self, stats):
        self._stats = stats

    def get_traffic_stats(self, _nodes, group_by):
        return {"stats": deepcopy(self._stats), "group_by": group_by}

    def get_online_clients(self, _nodes):
        return []


def _build_runtime(tmp_path, stats):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    redis_store = {}

    return LiveStatsRuntime(
        client_mgr=DummyClientManager(stats),
        db_path=db_path,
        traffic_stats_cache={},
        online_clients_cache={"ts": 0.0, "data": []},
        cache_refresh_state={"traffic": set(), "online_clients": False},
        state_lock=Lock(),
        redis_get_json=lambda key: deepcopy(redis_store.get(key)),
        redis_set_json=lambda key, value, _ttl: redis_store.__setitem__(key, deepcopy(value)),
        redis_delete=lambda *keys: [redis_store.pop(key, None) for key in keys],
        traffic_stats_cache_ttl=30,
        traffic_stats_stale_ttl=120,
        online_clients_cache_ttl=30,
        online_clients_stale_ttl=120,
        logger=SimpleNamespace(
            warning=lambda *args, **kwargs: None,
            info=lambda *args, **kwargs: None,
        ),
    )


def test_day_period_uses_snapshot_before_requested_window(monkeypatch, tmp_path):
    now_ts = 200 * 3600
    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 160, "down": 40, "total": 200, "count": 1}},
    )

    old_snapshot_ts = now_ts - (25 * 3600)
    recent_snapshot_ts = now_ts - (2 * 3600)

    runtime._save_period_snapshots(
        "client",
        {"alpha@example.com": {"up": 80, "down": 20, "total": 100, "count": 1}},
        old_snapshot_ts,
    )
    runtime._save_period_snapshots(
        "client",
        {"alpha@example.com": {"up": 144, "down": 36, "total": 180, "count": 1}},
        recent_snapshot_ts,
    )

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_traffic_stats_by_period([{"id": 1, "name": "alpha"}], "client", "day")

    assert payload["stats"]["alpha@example.com"]["total"] == 100
    assert int(payload["snapshot_ts"]) == old_snapshot_ts


def test_period_stats_do_not_fallback_to_all_time_without_history(monkeypatch, tmp_path):
    now_ts = 300 * 3600
    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 320, "down": 80, "total": 400, "count": 1}},
    )

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_traffic_stats_by_period([{"id": 1, "name": "alpha"}], "client", "day")

    assert payload["stats"] == {}
    assert "No historical snapshot" in payload["note"]


def test_db_snapshot_survives_runtime_restart(monkeypatch, tmp_path):
    now_ts = 400 * 3600
    old_snapshot_ts = now_ts - (26 * 3600)

    first_runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 240, "down": 60, "total": 300, "count": 1}},
    )
    first_runtime._save_period_snapshots(
        "client",
        {"alpha@example.com": {"up": 80, "down": 20, "total": 100, "count": 1}},
        old_snapshot_ts,
    )

    restarted_runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 240, "down": 60, "total": 300, "count": 1}},
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = restarted_runtime.get_traffic_stats_by_period([{"id": 1, "name": "alpha"}], "client", "day")

    assert payload["stats"]["alpha@example.com"]["total"] == 200
    assert int(payload["snapshot_ts"]) == old_snapshot_ts


def test_backfill_node_history_snapshots_restores_node_period_history(monkeypatch, tmp_path):
    now_ts = 500 * 3600
    runtime = _build_runtime(
        tmp_path,
        {
            "alpha-node": {"up": 0, "down": 320, "total": 320, "count": 1},
            "beta-node": {"up": 0, "down": 480, "total": 480, "count": 1},
        },
    )

    snapshot_a_ts = now_ts - (26 * 3600)
    snapshot_b_ts = snapshot_a_ts + 120

    with connect(runtime.db_path) as conn:
        conn.execute(
            """
            INSERT INTO node_history (
                ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
            ) VALUES (?, ?, ?, 1, 1, 0, 0, ?, 0)
            """,
            (int(snapshot_a_ts), 1, "alpha-node", 120),
        )
        conn.execute(
            """
            INSERT INTO node_history (
                ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
            ) VALUES (?, ?, ?, 1, 1, 0, 0, ?, 0)
            """,
            (int(snapshot_b_ts), 2, "beta-node", 300),
        )
        conn.commit()

    summary = runtime.backfill_node_history_snapshots(now_ts=now_ts)

    assert summary["hour"] >= 1
    assert summary["day"] >= 1

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)
    payload = runtime.get_traffic_stats_by_period(
        [{"id": 1, "name": "alpha-node"}, {"id": 2, "name": "beta-node"}],
        "node",
        "day",
    )

    assert payload["stats"]["alpha-node"]["total"] == 200
    assert payload["stats"]["beta-node"]["total"] == 180
    assert payload["stats"]["alpha-node"]["down"] == 200
    assert payload["stats"]["beta-node"]["down"] == 180
    assert int(payload["snapshot_ts"]) == int(snapshot_b_ts)


def test_year_period_uses_earliest_available_snapshot_when_window_is_partial(monkeypatch, tmp_path):
    now_ts = 500 * 86400
    snapshot_ts = now_ts - (31 * 86400)
    runtime = _build_runtime(
        tmp_path,
        {"alpha-node": {"up": 0, "down": 320, "total": 320, "count": 1}},
    )

    runtime._save_period_snapshots(
        "node",
        {"alpha-node": {"up": 0, "down": 120, "total": 120, "count": 1}},
        snapshot_ts,
    )

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)
    payload = runtime.get_traffic_stats_by_period(
        [{"id": 1, "name": "alpha-node"}],
        "node",
        "year",
    )

    assert payload["stats"]["alpha-node"]["total"] == 200
    assert int(payload["snapshot_ts"]) == int(snapshot_ts)
    assert "part of the requested window" in payload["note"]


def test_ensure_current_period_snapshots_seeds_buckets_without_ui_request(monkeypatch, tmp_path):
    now_ts = 700 * 3600
    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 10, "down": 20, "total": 30, "count": 1}},
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    seeded = runtime.ensure_current_period_snapshots([{"id": 1, "name": "alpha"}], ["client"], now_ts=now_ts)

    assert seeded == {"client": True}

    with connect(runtime.db_path) as conn:
        rows = conn.execute(
            """
            SELECT bucket_kind, bucket_start
            FROM traffic_stats_snapshots
            WHERE group_by = 'client'
            ORDER BY bucket_kind ASC
            """
        ).fetchall()

    assert ("day", int(now_ts / 86400)) in rows
    assert ("hour", int(now_ts / 3600)) in rows

    seeded_again = runtime.ensure_current_period_snapshots([{"id": 1, "name": "alpha"}], ["client"], now_ts=now_ts + 6)
    assert seeded_again == {}


def test_concurrent_cold_traffic_requests_share_one_fleet_fetch(tmp_path):
    class BlockingClientManager(DummyClientManager):
        def __init__(self, stats):
            super().__init__(stats)
            self.calls = 0
            self.started = Event()
            self.release = Event()

        def get_traffic_stats(self, nodes, group_by):
            self.calls += 1
            self.started.set()
            assert self.release.wait(timeout=2)
            return super().get_traffic_stats(nodes, group_by)

    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 10, "down": 20, "total": 30, "count": 1}},
    )
    manager = BlockingClientManager(runtime.client_mgr._stats)
    runtime.client_mgr = manager
    results = []

    def fetch():
        results.append(runtime.get_cached_traffic_stats([{"id": 1, "name": "alpha"}], "client"))

    first = Thread(target=fetch)
    second = Thread(target=fetch)
    first.start()
    assert manager.started.wait(timeout=1)
    second.start()
    manager.release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert manager.calls == 1
    assert len(results) == 2
    assert results[0]["stats"] == results[1]["stats"]


def test_cached_traffic_projection_never_starts_fleet_fetch(tmp_path):
    class CountingClientManager(DummyClientManager):
        def __init__(self, stats):
            super().__init__(stats)
            self.calls = 0

        def get_traffic_stats(self, nodes, group_by):
            self.calls += 1
            return super().get_traffic_stats(nodes, group_by)

    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 10, "down": 20, "total": 30, "count": 1}},
    )
    manager = CountingClientManager(runtime.client_mgr._stats)
    runtime.client_mgr = manager

    empty = runtime.get_cached_traffic_stats_projection("client")
    runtime.traffic_stats_cache["client"] = (
        123.0,
        {"stats": {"alpha@example.com": {"up": 10, "down": 20, "total": 30}}},
    )
    cached = runtime.get_cached_traffic_stats_projection("client")

    runtime._save_period_snapshots(
        "client",
        {"persisted@example.com": {"up": 40, "down": 60, "total": 100}},
        456.0,
    )
    restarted = _build_runtime(tmp_path, manager._stats)
    restarted_manager = CountingClientManager(manager._stats)
    restarted.client_mgr = restarted_manager
    persisted = restarted.get_cached_traffic_stats_projection("client")

    assert empty == {"stats": {}, "group_by": "client", "cache_source": "empty"}
    assert cached["stats"]["alpha@example.com"]["total"] == 30
    assert cached["cache_source"] == "memory"
    assert manager.calls == 0
    assert persisted["stats"]["persisted@example.com"]["total"] == 100
    assert persisted["cache_source"] == "sqlite_snapshot"
    assert restarted_manager.calls == 0
