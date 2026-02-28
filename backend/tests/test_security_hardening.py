"""Security regression tests for auth and node listing."""
import base64
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import main


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


@pytest.mark.asyncio
async def test_list_nodes_does_not_return_password(monkeypatch):
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
    monkeypatch.setattr(main, "check_auth", lambda request: "admin")
    monkeypatch.setattr(main.sqlite3, "connect", lambda _: _FakeConn(rows))

    response = await main.list_nodes(SimpleNamespace(headers={}))
    payload = json.loads(response.body.decode("utf-8"))

    assert len(payload) == 1
    assert "password" not in payload[0]
