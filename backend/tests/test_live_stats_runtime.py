import json
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
        self.traffic_calls = 0

    def get_traffic_stats(self, _nodes, group_by):
        self.traffic_calls += 1
        return {"stats": deepcopy(self._stats), "group_by": group_by}

    def get_online_clients(self, _nodes):
        return []


def _build_runtime(tmp_path, stats, get_latest_snapshot=None):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    redis_store = {}

    return LiveStatsRuntime(
        client_mgr=DummyClientManager(stats),
        db_path=db_path,
        traffic_stats_cache={},
        cache_refresh_state={"traffic": set()},
        state_lock=Lock(),
        redis_get_json=lambda key: deepcopy(redis_store.get(key)),
        redis_set_json=lambda key, value, _ttl: redis_store.__setitem__(key, deepcopy(value)),
        redis_delete=lambda *keys: [redis_store.pop(key, None) for key in keys],
        traffic_stats_cache_ttl=30,
        traffic_stats_stale_ttl=120,
        logger=SimpleNamespace(
            warning=lambda *args, **kwargs: None,
            info=lambda *args, **kwargs: None,
        ),
        get_latest_snapshot=get_latest_snapshot,
    )


def _seed_traffic_projection(runtime, group_by, stats, timestamp=0.0):
    runtime.traffic_stats_cache[group_by] = (
        timestamp,
        {"stats": deepcopy(stats), "group_by": group_by},
    )


def _node_identity_stats(*rows):
    return {
        f"node:{node_id}": {
            "up": up,
            "down": down,
            "total": up + down,
            "count": 1,
            "_display_key": display_key,
            "_legacy_key": legacy_key,
        }
        for node_id, display_key, legacy_key, up, down in rows
    }


def test_invalidation_rejects_in_flight_live_stats_cache_publish(tmp_path):
    runtime = _build_runtime(tmp_path, {"before@example.test": {"up": 1, "down": 2}})
    generation = runtime._cache_generation_snapshot()

    runtime.invalidate()

    traffic = {"stats": {"before@example.test": {"up": 1, "down": 2}}, "group_by": "client"}
    assert runtime._store_traffic_cache("client", traffic, generation) is False
    assert runtime.traffic_stats_cache == {}
    assert not hasattr(runtime, "_store_online_clients")


def test_memory_snapshot_fallback_expires_and_remains_bounded(monkeypatch, tmp_path):
    runtime = _build_runtime(tmp_path, {})
    runtime._memory_snapshot_max_entries = 2
    runtime.redis_get_json = lambda _key: None
    monotonic_now = [100.0]
    monkeypatch.setattr("services.live_stats_runtime.time.monotonic", lambda: monotonic_now[0])

    assert runtime._write_snapshot("one", {"ts": 1, "stats": {"one": {}}}, 5) is True
    assert runtime._read_snapshot("one") == {"ts": 1, "stats": {"one": {}}}

    monotonic_now[0] = 106.0
    assert runtime._read_snapshot("one") is None
    assert "one" not in runtime._memory_snapshots

    for key in ("two", "three", "four"):
        assert runtime._write_snapshot(key, {"ts": 1, "stats": {key: {}}}, 60) is True
        monotonic_now[0] += 1

    assert set(runtime._memory_snapshots) == {"three", "four"}


def test_collector_projection_serves_all_groupings_without_client_manager_fanout(monkeypatch, tmp_path):
    now_ts = 500 * 3600
    snapshot = {
        "timestamp": now_ts,
        "nodes": [
            {
                "name": "alpha",
                "system_client_emails": ["two@example.test"],
                "inbounds": [
                    {
                        "id": 7,
                        "remark": "main",
                        "up": 100,
                        "down": 200,
                        "clientStats": [
                            {"email": "one@example.test", "up": 70, "down": 120},
                            {"email": "two@example.test", "up": 30, "down": 80},
                        ],
                    }
                ],
            }
        ],
    }
    runtime = _build_runtime(
        tmp_path,
        {"should-not": {"up": 1, "down": 1}},
        get_latest_snapshot=lambda: snapshot,
    )
    runtime._save_period_snapshots(
        "client",
        {"one@example.test": {"up": 20, "down": 20, "total": 40, "count": 1}},
        now_ts - 25 * 3600,
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    client = runtime.get_cached_traffic_stats_projection_by_period("client", "day")
    inbound = runtime.get_cached_traffic_stats_projection_by_period("inbound", "all_time")
    node = runtime.get_cached_traffic_stats_projection_by_period("node", "all_time")

    assert runtime.client_mgr.traffic_calls == 0
    assert client["cache_source"] == "snapshot_collector"
    assert client["system_client_emails"] == ["two@example.test"]
    assert client["stats"]["one@example.test"]["total"] == 150
    assert client["stats"]["two@example.test"]["total"] == 110
    assert inbound["stats"]["alpha:main"]["total"] == 300
    assert node["stats"]["alpha"]["total"] == 300


def test_collector_traffic_projection_keeps_duplicate_node_names_separate(tmp_path):
    snapshot = {
        "timestamp": 123.0,
        "nodes": [
            {"node_id": 1, "name": "edge", "inbounds": [{"id": 7, "remark": "main", "up": 10, "down": 20}]},
            {"node_id": 2, "name": "edge", "inbounds": [{"id": 7, "remark": "main", "up": 30, "down": 40}]},
        ],
    }
    runtime = _build_runtime(tmp_path, {}, get_latest_snapshot=lambda: snapshot)

    node = runtime.get_cached_traffic_stats_projection("node")
    inbound = runtime.get_cached_traffic_stats_projection("inbound")

    assert node["stats"] == {
        "edge #1": {"up": 10, "down": 20, "total": 30, "count": 1},
        "edge #2": {"up": 30, "down": 40, "total": 70, "count": 1},
    }
    assert node["identity_stats"]["node:1"]["total"] == 30
    assert node["identity_stats"]["node:2"]["total"] == 70
    assert inbound["stats"]["edge #1:main"]["total"] == 30
    assert inbound["stats"]["edge #2:main"]["total"] == 70
    assert inbound["identity_stats"]["node:1:inbound:7"]["total"] == 30
    assert inbound["identity_stats"]["node:2:inbound:7"]["total"] == 70


def test_node_period_uses_stable_identity_after_rename(monkeypatch, tmp_path):
    now_ts = 500 * 3600
    runtime = _build_runtime(tmp_path, {})
    baseline = _node_identity_stats((1, "old-name", "old-name", 20, 100))
    current = _node_identity_stats((1, "new-name", "new-name", 40, 280))
    runtime._save_period_snapshots("node", {}, now_ts - 25 * 3600, baseline)
    runtime.traffic_stats_cache["node"] = (
        now_ts,
        {"stats": {"new-name": {"up": 40, "down": 280, "total": 320, "count": 1}}, "identity_stats": current},
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("node", "day")

    assert payload["stats"] == {"new-name": {"up": 20, "down": 180, "total": 200, "count": 1}}


def test_sqlite_identity_snapshot_rebuilds_readable_node_labels(tmp_path):
    runtime = _build_runtime(tmp_path, {})
    identity_stats = _node_identity_stats(
        (1, "edge #1", "edge", 10, 20),
        (2, "edge #2", "edge", 30, 40),
    )
    runtime._save_period_snapshots("node", {}, 500 * 3600, identity_stats)
    restarted = _build_runtime(tmp_path, {})

    payload = restarted.get_cached_traffic_stats_projection("node")

    assert payload["cache_source"] == "sqlite_snapshot"
    assert set(payload["stats"]) == {"edge #1", "edge #2"}
    assert "node:1" not in payload["stats"]
    assert set(payload["identity_stats"]) == {"node:1", "node:2"}


def test_node_period_reads_legacy_name_snapshot_only_when_unambiguous(monkeypatch, tmp_path):
    now_ts = 500 * 3600
    runtime = _build_runtime(tmp_path, {})
    runtime._save_period_snapshots(
        "node",
        {"alpha": {"up": 20, "down": 100, "total": 120, "count": 1}},
        now_ts - 25 * 3600,
    )
    current = _node_identity_stats((1, "alpha", "alpha", 40, 280))
    runtime.traffic_stats_cache["node"] = (
        now_ts,
        {"stats": {"alpha": {"up": 40, "down": 280, "total": 320, "count": 1}}, "identity_stats": current},
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("node", "day")

    assert payload["stats"]["alpha"]["total"] == 200
    assert "missing_baseline_count" not in payload


def test_node_period_omits_ambiguous_legacy_name_snapshot(monkeypatch, tmp_path):
    now_ts = 500 * 3600
    runtime = _build_runtime(tmp_path, {})
    runtime._save_period_snapshots(
        "node",
        {"edge": {"up": 20, "down": 100, "total": 120, "count": 1}},
        now_ts - 25 * 3600,
    )
    current = _node_identity_stats(
        (1, "edge #1", "edge", 40, 280),
        (2, "edge #2", "edge", 50, 350),
    )
    runtime.traffic_stats_cache["node"] = (
        now_ts,
        {
            "stats": {
                "edge #1": {"up": 40, "down": 280, "total": 320, "count": 1},
                "edge #2": {"up": 50, "down": 350, "total": 400, "count": 1},
            },
            "identity_stats": current,
        },
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("node", "day")

    assert payload["stats"] == {}
    assert payload["missing_baseline_count"] == 2
    assert "no unambiguous historical baseline" in payload["note"]


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
    _seed_traffic_projection(
        runtime,
        "client",
        {"alpha@example.com": {"up": 160, "down": 40, "total": 200, "count": 1}},
        now_ts,
    )

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("client", "day")

    assert payload["stats"]["alpha@example.com"]["total"] == 100
    assert int(payload["snapshot_ts"]) == old_snapshot_ts


def test_period_stats_do_not_fallback_to_all_time_without_history(monkeypatch, tmp_path):
    now_ts = 300 * 3600
    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 320, "down": 80, "total": 400, "count": 1}},
    )
    _seed_traffic_projection(
        runtime,
        "client",
        {"alpha@example.com": {"up": 320, "down": 80, "total": 400, "count": 1}},
    )

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("client", "day")

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
    _seed_traffic_projection(
        restarted_runtime,
        "client",
        {"alpha@example.com": {"up": 240, "down": 60, "total": 300, "count": 1}},
        now_ts,
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = restarted_runtime.get_cached_traffic_stats_projection_by_period("client", "day")

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
    with connect(runtime.db_path) as conn:
        row = conn.execute(
            "SELECT stats_json FROM traffic_stats_snapshots WHERE group_by = 'node' AND bucket_kind = 'day' LIMIT 1"
        ).fetchone()
    persisted = json.loads(row[0])
    assert set(persisted) == {"node:1", "node:2"}
    assert persisted["node:1"]["_display_key"] == "alpha-node"
    assert persisted["node:2"]["_display_key"] == "beta-node"

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)
    _seed_traffic_projection(
        runtime,
        "node",
        {
            "alpha-node": {"up": 0, "down": 320, "total": 320, "count": 1},
            "beta-node": {"up": 0, "down": 480, "total": 480, "count": 1},
        },
        now_ts,
    )
    runtime.traffic_stats_cache["node"][1]["identity_stats"] = _node_identity_stats(
        (1, "alpha-node", "alpha-node", 0, 320),
        (2, "beta-node", "beta-node", 0, 480),
    )
    payload = runtime.get_cached_traffic_stats_projection_by_period("node", "day")

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
    _seed_traffic_projection(
        runtime,
        "node",
        {"alpha-node": {"up": 0, "down": 320, "total": 320, "count": 1}},
        now_ts,
    )

    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)
    payload = runtime.get_cached_traffic_stats_projection_by_period("node", "year")

    assert payload["stats"]["alpha-node"]["total"] == 200
    assert int(payload["snapshot_ts"]) == int(snapshot_ts)
    assert "part of the requested window" in payload["note"]


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


def test_cached_traffic_projection_period_uses_baseline_without_fleet_fetch(monkeypatch, tmp_path):
    now_ts = 900 * 3600
    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 160, "down": 240, "total": 400, "count": 1}},
    )
    runtime.traffic_stats_cache["client"] = (
        now_ts,
        {"stats": {"alpha@example.com": {"up": 160, "down": 240, "total": 400, "count": 1}}},
    )
    runtime._save_period_snapshots(
        "client",
        {"alpha@example.com": {"up": 100, "down": 150, "total": 250, "count": 1}},
        now_ts - (25 * 3600),
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("client", "day")

    assert payload["stats"] == {
        "alpha@example.com": {"up": 60, "down": 90, "total": 150, "count": 1},
    }
    assert payload["current_count"] == 1
    assert payload["cache_source"] == "memory"


def test_cached_traffic_projection_period_reports_missing_history_without_fleet_fetch(monkeypatch, tmp_path):
    now_ts = 1000 * 3600
    runtime = _build_runtime(
        tmp_path,
        {"alpha@example.com": {"up": 160, "down": 240, "total": 400, "count": 1}},
    )
    runtime.traffic_stats_cache["client"] = (
        now_ts,
        {"stats": {"alpha@example.com": {"up": 160, "down": 240, "total": 400, "count": 1}}},
    )
    monkeypatch.setattr("services.live_stats_runtime.time.time", lambda: now_ts)

    payload = runtime.get_cached_traffic_stats_projection_by_period("client", "week")

    assert payload["stats"] == {}
    assert payload["current_count"] == 1
    assert "No historical snapshot" in payload["note"]
