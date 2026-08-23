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


def test_xui_csrf_login_posts_json_credentials(monkeypatch):
    """3x-ui v3.6+ accepts the CSRF login payload as application/json."""
    import xui_session

    requests_seen = []

    def response(status_code, body=None):
        payload = body or {}
        return SimpleNamespace(
            status_code=status_code,
            text=json.dumps(payload),
            headers={},
            url="",
            json=lambda: payload,
        )

    def fake_xui_request(_session, method, url, **kwargs):
        requests_seen.append((method, url, kwargs))
        if url.endswith("/csrf-token"):
            return response(200, {"success": True, "obj": "csrf-token"})
        if url.endswith("/login") and kwargs.get("json") == {"username": "admin", "password": "pass"}:
            return response(200, {"success": True})
        return response(404)

    xui_session.invalidate_auth_method_cache()
    monkeypatch.setattr(xui_session, "xui_request", fake_xui_request)

    session = requests.Session()
    result = xui_session.login_panel_detailed(
        session,
        "https://panel.example.test/secret-path",
        "admin",
        "pass",
    )

    assert result["ok"] is True
    login_calls = [call for call in requests_seen if call[1].endswith("/login")]
    assert len(login_calls) == 1
    assert login_calls[0][2]["json"] == {"username": "admin", "password": "pass"}
    assert "data" not in login_calls[0][2]
    assert session.headers["X-CSRF-Token"] == "csrf-token"


def test_xui_legacy_auth_cache_reprobes_csrf_after_panel_upgrade(monkeypatch):
    """A node upgrade must not leave a process pinned to removed legacy endpoints."""
    import xui_session

    base_url = "https://panel.example.test/secret-path"
    requests_seen = []

    def response(status_code, body=None):
        payload = body or {}
        return SimpleNamespace(
            status_code=status_code,
            text=json.dumps(payload),
            headers={},
            url="",
            json=lambda: payload,
        )

    def fake_xui_request(_session, method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        requests_seen.append((method, url, "X-CSRF-Token" in headers))
        if url.endswith("/csrf-token"):
            return response(200, {"success": True, "obj": "csrf-token"})
        if headers.get("X-CSRF-Token"):
            return response(200, {"success": True})
        return response(404)

    xui_session.invalidate_auth_method_cache(base_url)
    xui_session._cache_auth_method(base_url, "legacy")
    monkeypatch.setattr(xui_session, "xui_request", fake_xui_request)

    try:
        result = xui_session.login_panel_detailed(requests.Session(), base_url, "admin", "pass")

        assert result["ok"] is True
        assert requests_seen == [
            ("POST", f"{base_url}/panel/login", False),
            ("POST", f"{base_url}/login", False),
            ("GET", f"{base_url}/csrf-token", False),
            ("POST", f"{base_url}/login", True),
        ]
        assert xui_session._AUTH_METHOD_CACHE[base_url] == "csrf"
    finally:
        xui_session.invalidate_auth_method_cache(base_url)


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


def test_xui_capability_registry_is_per_node_ttl_bound_and_redacted(monkeypatch):
    import xui_session

    node_key = "capability-test:443:"
    operation = "online_clients"
    paths = ("/panel/api/clients/onlines", "/panel/api/inbounds/onlines")
    response = response = SimpleNamespace(
        status_code=200,
        json=lambda: {"success": True, "obj": ["not-stored-as-a-value"]},
    )

    xui_session.invalidate_node_capabilities(node_key)
    monkeypatch.setattr(xui_session, "XUI_CAPABILITY_TTL_SEC", 60)
    xui_session.record_capability_route(node_key, operation, paths[1], response)

    assert xui_session.get_capability_route(node_key, operation, paths) == paths[1]
    stored = xui_session._NODE_CAPABILITIES[node_key][operation]
    assert stored["shape"] == "success=bool;obj=list"
    assert "not-stored-as-a-value" not in str(stored)
    xui_session.invalidate_node_capabilities(node_key)
    assert xui_session.get_capability_route(node_key, operation, paths) is None


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
    assert first["session"] is not second["session"]
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
        max_parallel_polls=2,
        degraded_backoff_sec=300,
    )
    assert collector.configured_max_parallel_polls == 2
    assert collector.max_parallel_polls == 2
    assert collector.semaphore._value == 2
    runtime_status = collector.runtime_status()
    assert runtime_status["configured_max_parallel_polls"] == 2
    assert runtime_status["last_cycle"]["queued_nodes"] == 0
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


def test_snapshot_collector_dashboard_projection_excludes_inventory_payload():
    from services.collector import SnapshotCollector

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    collector._latest = {
        "timestamp": 123.0,
        "nodes": {
            "alpha": {
                "name": "alpha",
                "node_id": 1,
                "available": True,
                "online_clients": 2,
                "traffic_total": 42,
                "system": {"cpu": 7},
                "inbounds": [{"clientStats": [{"email": "private@example.test"}]}],
                "inbounds_result": {"inbounds": [{"id": 1}]},
                "server_status": {"session": "must-not-leak"},
            }
        },
    }

    payload = collector.latest_dashboard_snapshot()

    assert payload["projection"] == "dashboard-v1"
    assert payload["nodes"] == [{
        "name": "alpha",
        "node_id": 1,
        "available": True,
        "online_clients": 2,
        "traffic_total": 42,
        "system": {"cpu": 7},
    }]


def test_snapshot_collector_publishes_presence_without_exposing_it_to_dashboard():
    from services.collector import SnapshotCollector

    class PresenceMonitor:
        def get_server_status(self, node):
            return {
                "node": node["name"],
                "available": True,
                "reason": "ok",
                "system": {"cpu": 4},
                "xray": {"running": True},
                "network": {},
            }

        def get_online_clients(self, _node):
            return {"online_clients": ["First@Example.test", " first@example.test ", "second@example.test", 7]}

        def get_inbounds(self, _node):
            return {"available": True, "inbounds": []}

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=PresenceMonitor(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )

    asyncio.run(collector._poll_node({"id": 1, "name": "alpha"}, "alpha"))

    presence = collector.latest_client_presence()
    dashboard = collector.latest_dashboard_snapshot()

    assert presence["projection"] == "client-presence-v1"
    assert presence["online_emails"] == ["first@example.test", "second@example.test"]
    assert set(presence["last_seen"]) == {"first@example.test", "second@example.test"}
    assert dashboard["nodes"][0]["online_clients"] == 2
    assert "online_client_emails" not in dashboard["nodes"][0]


def test_dashboard_projection_payload_is_bounded_for_a_100_node_fleet():
    from services.collector import SnapshotCollector

    inventory = [
        {
            "id": inbound_id,
            "clientStats": [
                {"email": f"client-{inbound_id}-{client_id}@example.test", "up": client_id, "down": client_id * 2}
                for client_id in range(20)
            ],
        }
        for inbound_id in range(12)
    ]
    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )
    collector._latest = {
        "timestamp": 123.0,
        "nodes": {
            f"node-{index}": {
                "name": f"node-{index}",
                "node_id": index,
                "available": True,
                "online_clients": 20,
                "traffic_total": 12345,
                "system": {"cpu": 10},
                "inbounds": inventory,
                "inbounds_result": {"available": True, "inbounds": inventory},
            }
            for index in range(1, 101)
        },
    }

    full_bytes = len(json.dumps(collector.latest_snapshot()).encode())
    dashboard_bytes = len(json.dumps(collector.latest_dashboard_snapshot()).encode())

    assert dashboard_bytes < 100_000
    assert dashboard_bytes * 20 < full_bytes


def test_snapshot_collector_promotes_server_telemetry_to_snapshot():
    from services.collector import SnapshotCollector

    class TelemetryMonitor:
        def get_server_status(self, node):
            return {
                "node": node["name"],
                "available": True,
                "system": {
                    "cpu": 12.5,
                    "mem": {"current": 512, "total": 1024, "percent": 50.0},
                    "disk": {"current": 20, "total": 100, "percent": 20.0},
                    "uptime": 3600,
                    "loads": [0.1, 0.2, 0.3],
                },
                "xray": {"running": True, "version": "1.8.10", "uptime": 120},
                "network": {"upload": 1000, "download": 2000},
                "panel_version": "2.6.0",
            }

        def get_online_clients(self, _node):
            return {"available": True, "online_clients": ["a@test.local", "b@test.local"]}

        def get_inbounds(self, _node):
            return {"available": True, "inbounds": [{"up": 10, "down": 20}]}

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=TelemetryMonitor(),
        ws_manager=SimpleNamespace(active_connections=[]),
    )

    snapshot = collector._collect_node_snapshot({"id": 1, "name": "alpha"})

    assert snapshot["available"] is True
    assert snapshot["cpu"] == 12.5
    assert snapshot["system"]["mem"]["percent"] == 50.0
    assert snapshot["system"]["disk"]["percent"] == 20.0
    assert snapshot["system"]["loads"] == [0.1, 0.2, 0.3]
    assert snapshot["xray_running"] is True
    assert snapshot["xray"]["version"] == "1.8.10"
    assert snapshot["network"]["upload"] == 1000
    assert snapshot["network"]["download"] == 2000
    assert snapshot["online_clients"] == 2
    assert snapshot["traffic_total"] == 30
    assert snapshot["panel_version"] == "2.6.0"


def test_snapshot_collector_broadcasts_server_status_telemetry():
    from services.collector import SnapshotCollector

    class CaptureWs:
        active_connections = [object()]

        def __init__(self):
            self.messages = []

        async def broadcast(self, message, channel=None):
            self.messages.append((channel, message))

        async def broadcast_server_status(self, status_data):
            self.messages.append(("server_status", status_data))

        async def broadcast_client_update(self, client_data):
            self.messages.append(("clients", client_data))

        async def broadcast_inbound_update(self, inbound_data):
            self.messages.append(("inbounds", inbound_data))

        async def broadcast_traffic_update(self, traffic_data):
            self.messages.append(("traffic", traffic_data))

    ws = CaptureWs()
    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        ws_manager=ws,
    )
    snapshot = {
        "name": "alpha",
        "node_id": 1,
        "available": True,
        "status": "online",
        "reason": "ok",
        "cpu": 12.5,
        "system": {
            "cpu": 12.5,
            "mem": {"current": 512, "total": 1024, "percent": 50.0},
            "disk": {"current": 20, "total": 100, "percent": 20.0},
            "uptime": 3600,
            "loads": [0.1, 0.2, 0.3],
        },
        "xray": {"running": True, "version": "1.8.10", "uptime": 120},
        "network": {"upload": 1000, "download": 2000},
        "xray_running": True,
        "online_clients": 2,
        "traffic_total": 30,
        "panel_version": "2.6.0",
        "api_version": "v3",
        "poll_ms": 42.5,
        "timestamp": time.time(),
        "inbounds": [],
    }

    asyncio.run(collector._broadcast_delta("alpha", snapshot))

    status_payload = next(data for channel, data in ws.messages if channel == "server_status")
    assert status_payload["source"] == "snapshot_collector"
    assert status_payload["node"] == "alpha"
    assert status_payload["system"]["mem"]["percent"] == 50.0
    assert status_payload["system"]["disk"]["percent"] == 20.0
    assert status_payload["system"]["loads"] == [0.1, 0.2, 0.3]
    assert status_payload["network"]["upload"] == 1000
    assert status_payload["network"]["download"] == 2000
    assert status_payload["xray"]["version"] == "1.8.10"
    assert status_payload["panel_version"] == "2.6.0"
    assert status_payload["api_version"] == "v3"
    assert status_payload["poll_ms"] == 42.5


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
