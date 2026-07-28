"""Security regression tests for auth and node listing."""
import base64
import os
import sys
import tempfile
import requests

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", tempfile.gettempdir())
import main
import xui_session
from routers.realtime import build_realtime_router
from shared.security import bounded_log_count, redact_mapping, safe_content_disposition_filename, validate_outbound_url, validate_path_segment


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        if "SELECT * FROM nodes" in query:
            return _FakeCursor(self._rows)
        raise AssertionError(f"Unexpected query: {query}")


def _basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def test_check_basic_auth_header_accepts_valid_credentials(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: u == "admin" and p == "secret")
    user = main.check_basic_auth_header(_basic_header("admin", "secret"))
    assert user == "admin"


def test_check_basic_auth_header_rejects_non_basic_scheme(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    assert main.check_basic_auth_header("Bearer token-value") is None


def test_list_nodes_does_not_return_password(monkeypatch):
    rows = [
        {
            "id": 1,
            "name": "node-1",
            "ip": "1.2.3.4",
            "port": "443",
            "user": "root",
            "password": "encrypted-secret",
            "base_path": "",
        }
    ]
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: u == "admin" and p == "secret")
    monkeypatch.setattr(main.node_service, "list_nodes", lambda: rows)
    client = TestClient(main.app)

    response = client.get("/api/v1/nodes", headers={"Authorization": _basic_header("admin", "secret")})
    payload = response.json()

    assert response.status_code == 200
    assert len(payload) == 1
    assert "password" not in payload[0]


def test_websocket_requires_short_lived_ticket_and_never_accepts_password_json(monkeypatch):
    app = FastAPI()
    ticket = main.auth_service.issue_ws_ticket("admin")
    app.include_router(
        build_realtime_router(
            check_basic_auth_header=main.check_basic_auth_header,
            verify_totp_code=lambda _user, _code: True,
            verify_ws_ticket=main.auth_service.verify_ws_ticket,
            get_user_role=main.get_user_role,
            ws_manager=main.ws_manager,
            handle_websocket_message=main.handle_websocket_message,
            logger=main.logger,
        )
    )
    client = TestClient(app)

    with client.websocket_connect("/ws", subprotocols=[f"mssg-ticket.{ticket}"]) as websocket:
        websocket.send_json({"type": "auth", "username": "admin", "password": "secret"})
        websocket.send_json({"type": "subscribe", "channel": "traffic"})
        response = websocket.receive_json()

    assert response == {"type": "subscribed", "channel": "traffic", "status": "success"}


def test_shared_security_guards_bound_network_paths_and_logs(monkeypatch):
    assert validate_outbound_url("http://127.0.0.1:8080", require_https=False)[0] is False
    monkeypatch.setattr("shared.security.socket.getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))])
    assert validate_outbound_url("https://internal.example")[0] is False
    assert bounded_log_count(99999) == 500
    assert validate_path_segment("v1.2.3", field="version") == "v1.2.3"
    try:
        validate_path_segment("../etc", field="path")
    except ValueError:
        pass
    else:
        raise AssertionError("path traversal segment was accepted")
    assert "\r" not in safe_content_disposition_filename("bad\r\nname.db")
    assert redact_mapping({"Authorization": "Bearer secret"})["Authorization"] == "<redacted>"


def test_mutation_rejects_cross_origin_browser_request(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda _u, _p: True)
    client = TestClient(main.app)
    response = client.post(
        "/api/v1/nodes/check-connection",
        headers={
            "Authorization": _basic_header("admin", "secret"),
            "Origin": "https://attacker.invalid",
        },
        json={"url": "https://example.com", "user": "u", "password": "p"},
    )
    assert response.status_code == 403


def test_mutation_rejects_missing_browser_provenance_for_all_methods(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda _u, _p: True)
    client = TestClient(main.app)
    headers = {"Authorization": _basic_header("admin", "secret")}

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/v1/nodes/check-connection", headers=headers)
        assert response.status_code == 403


def test_mutation_allows_explicit_same_origin_request(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda _u, _p: True)
    client = TestClient(main.app)
    response = client.post(
        "/api/v1/nodes/check-connection",
        headers={
            "Authorization": _basic_header("admin", "secret"),
            "Origin": "http://testserver",
        },
        json={},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "URL is required"


def test_connection_check_does_not_expose_outbound_validation_details(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda _u, _p: True)
    client = TestClient(main.app)
    response = client.post(
        "/api/v1/nodes/check-connection",
        headers={
            "Authorization": _basic_header("admin", "secret"),
            "Origin": "http://testserver",
        },
        json={"url": "http://127.0.0.1:8080", "user": "u", "password": "p"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid outbound URL"


def test_xui_request_pins_approved_dns_address_and_preserves_host(monkeypatch):
    monkeypatch.setattr(
        "shared.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    captured = {}
    response = requests.Response()
    response.status_code = 200

    def fake_send(adapter, prepared, **_kwargs):
        captured["address"] = adapter._pinned_address
        captured["host"] = prepared.headers["Host"]
        return response

    monkeypatch.setattr(xui_session._PinnedHTTPAdapter, "send", fake_send)

    result = xui_session.xui_request(
        requests.Session(),
        "GET",
        "https://node.example/panel/api/status",
        retries=0,
    )

    assert result.status_code == 200
    assert captured == {"address": "93.184.216.34", "host": "node.example"}


def test_pinned_https_connection_connects_to_approved_address(monkeypatch):
    calls = []

    def fake_create_connection(address, timeout, source_address=None, socket_options=None):
        calls.append((address, timeout))
        return object()

    monkeypatch.setattr(
        xui_session.urllib3_connection.connection,
        "create_connection",
        fake_create_connection,
    )
    connection = xui_session._PinnedHTTPSConnection(
        host="node.example",
        port=443,
        pinned_address="93.184.216.34",
        server_hostname="node.example",
    )

    assert connection._new_conn() is not None
    assert calls == [(("93.184.216.34", 443), None)]
    assert connection.server_hostname == "node.example"
