import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest
import requests


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _collector(monitor):
    from services.collector import SnapshotCollector

    return SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=monitor,
        ws_manager=SimpleNamespace(active_connections=[]),
    )


def test_transport_backoff_stale_snapshot_and_recovery_are_bounded(monkeypatch, caplog):
    class Monitor:
        available = True

        def get_server_status(self, _node):
            if self.available:
                return {
                    "available": True,
                    "reason": "ok",
                    "system": {"cpu": 17},
                    "xray": {"running": True},
                    "network": {},
                }
            return {
                "available": False,
                "reason": "timeout",
                "error": "https://private.example.test/credential-value timed out",
            }

        def get_inbounds(self, _node):
            return {"available": True, "inbounds": []}

        def get_online_clients(self, _node):
            return {"available": True, "online_clients": []}

    now = [1000.0]
    monkeypatch.setattr("services.collector.time.time", lambda: now[0])
    monitor = Monitor()
    collector = _collector(monitor)
    node = {"id": 8, "name": "private-node"}
    key = collector._node_key(node)

    asyncio.run(collector._poll_node(node, key))
    for expected_backoff in (300.0, 600.0, 900.0, 900.0):
        monitor.available = False
        with caplog.at_level("INFO", logger="sub_manager"):
            asyncio.run(collector._poll_node(node, key))
        snapshot = collector.latest_snapshot()["nodes"][0]
        state = collector._node_state[key]
        assert state["interval"] == expected_backoff
        assert snapshot["available"] is False
        assert snapshot["stale"] is True
        assert snapshot["cpu"] == 17
        assert snapshot["error"] == "Node panel transport is unavailable"
        assert snapshot["last_success_at"] == 1000.0
        assert snapshot["last_attempt_at"] == now[0]
        assert snapshot["circuit_open_until"] == now[0] + expected_backoff
        serialized_projection = json.dumps(
            {
                "latest": collector.latest_snapshot(),
                "dashboard": collector.latest_dashboard_snapshot(),
            }
        )
        assert "private.example.test" not in serialized_projection
        assert "credential-value" not in serialized_projection
        now[0] += expected_backoff

    monitor.available = True
    with caplog.at_level("INFO", logger="sub_manager"):
        asyncio.run(collector._poll_node(node, key))
    recovered = collector.latest_snapshot()["nodes"][0]
    assert recovered["available"] is True
    assert "stale" not in recovered
    assert collector._node_state[key]["failures"] == 0

    transport_messages = [
        record.getMessage()
        for record in caplog.records
        if "Collector transport" in record.getMessage()
    ]
    assert transport_messages == [
        "Collector transport unavailable; retry_in_sec=300",
        "Collector transport failure persists: repeated_attempts=2 retry_in_sec=900",
        "Collector transport failure persists: repeated_attempts=1 retry_in_sec=900",
        "Collector transport recovered after 4 failed attempt(s)",
    ]
    combined = "\n".join(transport_messages)
    assert "private-node" not in combined
    assert "private.example.test" not in combined
    assert "credential-value" not in combined


def test_force_poll_bypasses_node_timeout_circuit(monkeypatch):
    from services.collector import SnapshotCollector

    now = [1000.0]
    monkeypatch.setattr("services.collector.time.time", lambda: now[0])
    node = {"id": 1, "name": "fixture"}
    collector = SnapshotCollector(
        fetch_nodes=lambda: [node],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    collector._node_state["id:1"] = {"next_poll": 1900.0, "circuit_until": 1900.0}
    captured = {}

    async def fake_poll_due(due_nodes, *, force_poll):
        captured["due_nodes"] = due_nodes
        captured["force_poll"] = force_poll
        collector._running = False
        return []

    monkeypatch.setattr(collector, "_poll_due_nodes", fake_poll_due)
    monkeypatch.setattr(collector, "_get_current_interval", lambda: 0.0)
    collector._force_poll_event.set()
    collector._running = True
    asyncio.run(collector._run())

    assert captured == {"due_nodes": [(node, "id:1")], "force_poll": True}


def test_transport_failure_overlay_does_not_enter_durable_snapshot_callbacks(
    monkeypatch,
):
    from services.collector import SnapshotCollector

    failure = {"node_id": 1, "available": False, "_transient_transport_failure": True}
    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    captured = {"persist": [], "notify": []}

    async def fake_poll_due(_due_nodes, *, force_poll):
        collector._running = False
        return [failure]

    async def fake_persist(snapshots):
        captured["persist"].append(snapshots)

    async def fake_notify(snapshots):
        captured["notify"].append(snapshots)

    monkeypatch.setattr(collector, "_poll_due_nodes", fake_poll_due)
    monkeypatch.setattr(collector, "_persist_snapshots", fake_persist)
    monkeypatch.setattr(collector, "_notify_completed_snapshots", fake_notify)
    monkeypatch.setattr(collector, "_get_current_interval", lambda: 0.0)
    collector._running = True
    asyncio.run(collector._run())

    assert captured == {"persist": [], "notify": []}
    assert "_transient_transport_failure" not in failure


def test_collector_context_resets_and_manual_adapter_warnings_remain(
    monkeypatch, caplog
):
    import xui_session

    assert xui_session.collector_transport_diagnostics_suppressed() is False
    with pytest.raises(RuntimeError, match="fixture"):
        with xui_session.suppress_collector_transport_diagnostics():
            assert xui_session.collector_transport_diagnostics_suppressed() is True
            raise RuntimeError("fixture")
    assert xui_session.collector_transport_diagnostics_suppressed() is False

    async def context_flags():
        async def read_flag():
            return xui_session.collector_transport_diagnostics_suppressed()

        manual_task = asyncio.create_task(read_flag())
        with xui_session.suppress_collector_transport_diagnostics():
            collector_task = asyncio.create_task(read_flag())
            return await manual_task, await collector_task

    assert asyncio.run(context_flags()) == (False, True)

    async def thread_flag():
        with xui_session.suppress_collector_transport_diagnostics():
            return await asyncio.to_thread(
                xui_session.collector_transport_diagnostics_suppressed
            )

    assert asyncio.run(thread_flag()) is True
    assert xui_session.collector_transport_diagnostics_suppressed() is False

    monkeypatch.setattr(
        xui_session,
        "validate_and_resolve_outbound_url",
        lambda _url: (True, "", "198.51.100.7"),
    )

    def fail_request(*_args, **_kwargs):
        raise requests.ConnectionError("fixture disconnected")

    monkeypatch.setattr(xui_session, "_pinned_session_request", fail_request)
    url = "https://private.example.test/panel/api/server/status"
    with caplog.at_level("WARNING", logger="sub_manager"):
        with pytest.raises(requests.ConnectionError):
            with xui_session.suppress_collector_transport_diagnostics():
                xui_session.xui_request(requests.Session(), "GET", url)
        with pytest.raises(requests.ConnectionError):
            xui_session.xui_request(requests.Session(), "GET", url)

    request_warnings = [
        record.getMessage()
        for record in caplog.records
        if "request error" in record.getMessage()
    ]
    assert len(request_warnings) == 1


def test_server_monitor_suppresses_only_collector_transport_login_warning(
    monkeypatch, caplog
):
    import server_monitor
    import xui_session

    monkeypatch.setattr(
        server_monitor, "build_panel_base_url", lambda _node: "https://fixture"
    )
    monkeypatch.setattr(
        server_monitor, "extract_node_auth", lambda *_args: ("admin", "pass", None)
    )
    monkeypatch.setattr(
        server_monitor,
        "get_authenticated_session",
        lambda **_kwargs: {"ok": False, "reason": "timeout", "error": "timed out"},
    )
    monitor = server_monitor.ThreeXUIMonitor(lambda value: value)
    node = {"name": "private-node", "ip": "8.8.8.8", "port": 443}
    with caplog.at_level("WARNING", logger="sub_manager"):
        with xui_session.suppress_collector_transport_diagnostics():
            assert monitor._get_session(node)[:2] == (None, None)
        assert monitor._get_session(node)[:2] == (None, None)

    warnings = [
        record.getMessage()
        for record in caplog.records
        if "failed to login" in record.getMessage()
    ]
    assert warnings == ["ThreeXUIMonitor: failed to login to private-node"]
