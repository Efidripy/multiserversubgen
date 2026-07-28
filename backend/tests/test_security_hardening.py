"""Security regression tests for auth and node listing."""
import base64
import os
import sys
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", tempfile.gettempdir())
import main
from routers.realtime import build_realtime_router


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
