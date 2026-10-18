import asyncio
import json
import os
import sys
from types import SimpleNamespace


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_tcp_rtt_uses_one_validated_pinned_connect_with_explicit_panel_port(
    monkeypatch,
):
    import services.collector as collector_module

    calls = []
    clocks = iter((10.0, 10.0125))

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        collector_module,
        "build_panel_base_url",
        lambda _node: "https://panel.example.test:8443/panel",
    )
    monkeypatch.setattr(
        collector_module,
        "validate_and_resolve_outbound_url",
        lambda _url: (True, "", "198.51.100.42"),
    )

    def connector(target, *, timeout):
        calls.append((target, timeout))
        return Connection()

    assert (
        collector_module.measure_node_tcp_rtt_ms(
            {"id": 1, "name": "fixture"},
            clock=lambda: next(clocks),
            connector=connector,
        )
        == 12.5
    )
    assert calls == [
        (("198.51.100.42", 8443), collector_module.XUI_CONNECT_TIMEOUT_SEC)
    ]


def test_tcp_rtt_failure_is_unknown_and_never_downgrades_successful_snapshot(
    monkeypatch,
):
    import services.collector as collector_module

    class Monitor:
        def get_server_status(self, node):
            return {
                "available": True,
                "reason": "ok",
                "system": {},
                "xray": {},
                "network": {},
            }

        def get_inbounds(self, node):
            return {"available": True, "inbounds": []}

        def get_online_clients(self, node):
            return {"online_clients": []}

    collector = collector_module.SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=Monitor(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    probes = []
    monkeypatch.setattr(
        collector_module,
        "measure_node_tcp_rtt_ms",
        lambda _node: probes.append(1) or None,
    )

    key = collector._node_key({"id": 1, "name": "fixture"})
    snapshot = asyncio.run(collector._poll_node({"id": 1, "name": "fixture"}, key))

    assert snapshot["available"] is True
    assert snapshot["status"] == "online"
    assert snapshot["tcp_rtt_ms"] is None
    assert probes == [1]


def test_tcp_rtt_is_not_measured_for_failed_xui_snapshot(monkeypatch):
    import services.collector as collector_module

    class Monitor:
        def get_server_status(self, node):
            return {
                "available": False,
                "reason": "timeout",
                "error": "timed out",
                "system": {},
                "xray": {},
                "network": {},
            }

    collector = collector_module.SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=Monitor(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    monkeypatch.setattr(
        collector_module,
        "measure_node_tcp_rtt_ms",
        lambda _node: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )

    key = collector._node_key({"id": 1, "name": "fixture"})
    snapshot = asyncio.run(collector._poll_node({"id": 1, "name": "fixture"}, key))

    assert snapshot["available"] is False
    assert "tcp_rtt_ms" not in snapshot


def test_tcp_rtt_is_dashboard_only_and_excluded_from_durable_snapshot(tmp_path):
    from services.collector import SnapshotCollector
    from services.db_bootstrap import connect, init_db

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO nodes (id, name, ip, port, user, password) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "fixture", "198.51.100.42", "443", "root", "encrypted"),
        )
        conn.commit()
    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        db_path=db_path,
    )
    snapshot = {
        "name": "fixture",
        "node_id": 1,
        "available": True,
        "status": "online",
        "timestamp": 1.0,
        "tcp_rtt_ms": 9.25,
    }

    asyncio.run(collector._persist_snapshot(snapshot))
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT status_data FROM node_snapshots WHERE node_id = 1"
        ).fetchone()
    assert row is not None
    assert "tcp_rtt_ms" not in json.loads(row[0])

    restored = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        db_path=db_path,
    )
    assert asyncio.run(restored.load_persisted_snapshots()) == 1
    restored_node = restored.latest_dashboard_snapshot()["nodes"][0]
    assert "tcp_rtt_ms" not in restored_node


def test_dashboard_projection_keeps_current_ephemeral_tcp_rtt():
    from services.collector import SnapshotCollector

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    collector._latest = {
        "timestamp": 1.0,
        "nodes": {
            "id:1": {
                "name": "fixture",
                "node_id": 1,
                "available": True,
                "tcp_rtt_ms": 4.5,
            }
        },
    }

    assert collector.latest_dashboard_snapshot()["nodes"] == [
        {"name": "fixture", "node_id": 1, "available": True, "tcp_rtt_ms": 4.5}
    ]


def test_tcp_rtt_keeps_poll_duration_bound_to_the_xui_snapshot(monkeypatch):
    import services.collector as collector_module

    collector = collector_module.SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    collector._collect_node_snapshot = lambda _node: {
        "name": "fixture",
        "node_id": 1,
        "available": True,
        "status": "online",
        "timestamp": 1.0,
        "online_client_emails": [],
    }
    clock = {"now": 0.0}
    monkeypatch.setattr(collector_module.time, "time", lambda: clock["now"])

    async def fake_run(label, function, *args):
        if label == "collector.poll_node":
            clock["now"] = 1.0
            return function(*args)
        assert label == "collector.tcp_rtt"
        clock["now"] = 99.0
        return 7.5

    collector._run_blocking = fake_run
    key = collector._node_key({"id": 1, "name": "fixture"})
    snapshot = asyncio.run(collector._poll_node({"id": 1, "name": "fixture"}, key))

    assert snapshot["poll_ms"] == 1000.0
    assert snapshot["tcp_rtt_ms"] == 7.5
