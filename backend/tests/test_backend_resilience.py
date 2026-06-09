import asyncio
import json
import os
import requests
import sqlite3
import sys
import time
from types import SimpleNamespace


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_xui_timeout_is_hard_capped():
    from xui_session import bounded_xui_timeout

    connect_timeout, read_timeout = bounded_xui_timeout(180)

    assert connect_timeout <= 3.0
    assert read_timeout <= 4.0


def test_xui_panel_base_url_preserves_panel_url_path():
    import xui_session

    node = {
        "panel_url": "https://panel.example.test/secret-path",
        "ip": "panel.example.test",
        "port": "443",
        "scheme": "https",
        "base_path": "",
    }

    assert xui_session.build_panel_base_url(node) == "https://panel.example.test/secret-path"
    assert xui_session.make_node_key_for_node(node) == "panel.example.test:443:secret-path"


def test_xui_panel_base_url_recovers_path_from_urlish_ip():
    import xui_session

    node = {
        "ip": "https://panel.example.test/secret-path",
        "port": "443",
        "scheme": "https",
        "base_path": "",
    }

    assert xui_session.build_panel_base_url(node) == "https://panel.example.test:443/secret-path"
    assert xui_session.make_node_key_for_node(node) == "panel.example.test:443:secret-path"


def test_xui_login_requests_keep_base_url_prefix(monkeypatch):
    import xui_session

    urls = []

    def response(status_code, body=None):
        payload = body or {}
        return SimpleNamespace(
            status_code=status_code,
            text=json.dumps(payload),
            headers={},
            url="",
            json=lambda: payload,
        )

    def fake_xui_request(_session, _method, url, **_kwargs):
        urls.append(url)
        if url.endswith("/csrf-token"):
            return response(404)
        if url.endswith("/panel/login"):
            return response(404)
        return response(200, {"success": True})

    monkeypatch.setattr(xui_session, "xui_request", fake_xui_request)

    result = xui_session.login_panel_detailed(
        requests.Session(),
        "https://panel.example.test/secret-path",
        "admin",
        "pass",
    )

    assert result["ok"] is True
    assert urls == [
        "https://panel.example.test/secret-path/csrf-token",
        "https://panel.example.test/secret-path/panel/login",
        "https://panel.example.test/secret-path/login",
    ]


def test_xui_panel_api_404_is_auth_failure():
    import xui_session

    resp = SimpleNamespace(
        status_code=404,
        text="not found",
        headers={},
        url="https://panel.example.test/secret-path/panel/api/server/status",
        request=SimpleNamespace(url="https://panel.example.test/secret-path/panel/api/server/status"),
    )

    assert xui_session.is_auth_failure_response(resp) is True


def test_xui_plain_404_is_not_auth_failure():
    import xui_session

    resp = SimpleNamespace(
        status_code=404,
        text="not found",
        headers={},
        url="https://panel.example.test/secret-path/something-else",
        request=SimpleNamespace(url="https://panel.example.test/secret-path/something-else"),
    )

    assert xui_session.is_auth_failure_response(resp) is False


def test_xui_session_pool_reuses_session_until_forced_reauth(monkeypatch):
    import xui_session

    node_key = "unit-test:443:"
    xui_session.invalidate_session_cache(node_key)
    calls = {"login": 0}

    def fake_login(session, *_args, **_kwargs):
        calls["login"] += 1
        return {"ok": True, "reason": "ok", "error": ""}

    monkeypatch.setattr(xui_session, "login_panel_detailed", fake_login)

    first = xui_session.get_authenticated_session(
        node_key=node_key,
        base_url="https://unit-test:443",
        username="admin",
        password="pass",
        bearer_token=None,
        verify_value=False,
    )
    second = xui_session.get_authenticated_session(
        node_key=node_key,
        base_url="https://unit-test:443",
        username="admin",
        password="pass",
        bearer_token=None,
        verify_value=False,
    )
    third = xui_session.get_authenticated_session(
        node_key=node_key,
        base_url="https://unit-test:443",
        username="admin",
        password="pass",
        bearer_token=None,
        verify_value=False,
        force_reauth=True,
    )

    assert first["ok"] is True
    assert second["cached"] is True
    assert first["session"] is second["session"]
    assert third["session"] is not first["session"]
    assert calls["login"] == 2
    xui_session.invalidate_session_cache(node_key)


def test_snapshot_collector_opens_timeout_circuit():
    from services.collector import SnapshotCollector

    class TimeoutMonitor:
        def get_server_status(self, node):
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                "reason": "request_failed",
                "error": "HTTPSConnectionPool(host='h1n1.kleva.ru'): Read timed out.",
            }

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=TimeoutMonitor(),
        ws_manager=SimpleNamespace(active_connections=[]),
        degraded_backoff_sec=300,
    )
    assert collector.semaphore._value == 5
    collector._node_state["Server-6"] = {
        "next_poll": 0.0,
        "interval": 60.0,
        "failures": 0,
        "stable_cycles": 0,
        "last_hash": "",
        "circuit_until": 0.0,
    }

    asyncio.run(
        collector._poll_node(
            {"id": 6, "name": "Server-6"},
            "Server-6",
            asyncio.Semaphore(1),
        )
    )

    state = collector._node_state["Server-6"]
    snapshot = collector._latest["nodes"]["Server-6"]

    assert state["interval"] == 300.0
    assert state["circuit_until"] > time.time()
    assert snapshot["available"] is False
    assert snapshot["status"] == "offline"
    assert snapshot["reason"] == "timeout"


def test_snapshot_collector_persists_and_loads_sqlite_snapshots(tmp_path):
    from services.collector import SnapshotCollector
    from services.db_bootstrap import connect, init_db

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO nodes (id, name, ip, port, user, password)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "alpha", "127.0.0.1", "443", "root", "encrypted"),
        )
        conn.commit()

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        db_path=db_path,
    )
    snapshot = {
        "name": "alpha",
        "node_id": 1,
        "available": True,
        "status": "online",
        "reason": "ok",
        "online_clients": 2,
        "traffic_total": 1234,
        "timestamp": time.time(),
        "server_status": {"node": "alpha", "available": True},
    }

    asyncio.run(collector._persist_snapshot(snapshot))

    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM node_snapshots WHERE node_id = 1").fetchone()
    assert row is not None
    assert row["is_online"] == 1
    assert json.loads(row["status_data"])["traffic_total"] == 1234

    loaded = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        db_path=db_path,
    )
    loaded_count = asyncio.run(loaded.load_persisted_snapshots())
    latest = loaded.latest_snapshot()

    assert loaded_count == 1
    assert latest["count"] == 1
    assert latest["nodes"][0]["name"] == "alpha"
    assert latest["nodes"][0]["traffic_total"] == 1234
    assert latest["nodes"][0]["cached_from_db"] is True
