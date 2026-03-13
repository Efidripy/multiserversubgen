import base64
import os
import sys
import tempfile

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", tempfile.gettempdir())
import main


def _basic_auth(username: str = "admin", password: str = "secret") -> dict:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


def test_auth_required_for_nodes(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: False)
    client = TestClient(main.app)

    response = client.get("/api/v1/nodes")

    assert response.status_code == 401


def test_nodes_endpoint_returns_sanitized_rows(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: u == "admin" and p == "secret")
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [
            {"id": 2, "name": "beta", "password": "hidden"},
            {"id": 1, "name": "alpha", "password": "hidden"},
        ],
    )
    client = TestClient(main.app)

    response = client.get("/api/v1/nodes", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert [node["name"] for node in payload] == ["beta", "alpha"]
    assert all("password" not in node for node in payload)


def test_inbounds_endpoint_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [
            {"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443", "user": "root", "password": "enc"},
            {"id": 2, "name": "beta", "ip": "2.2.2.2", "port": "443", "user": "root", "password": "enc"},
        ],
    )
    monkeypatch.setattr(
        main.inbound_mgr,
        "get_all_inbounds",
        lambda nodes: [
            {"id": 11, "node_name": "alpha", "protocol": "vless", "security": "reality"},
            {"id": 12, "node_name": "beta", "protocol": "trojan", "security": "tls"},
        ],
    )
    client = TestClient(main.app)

    response = client.get("/api/v1/inbounds?protocol=vless", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["inbounds"][0]["node_name"] == "alpha"


def test_clients_endpoint_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    monkeypatch.setattr(
        main.node_service,
        "list_nodes",
        lambda: [
            {"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443", "user": "root", "password": "enc"},
        ],
    )
    monkeypatch.setattr(
        main.clients_runtime,
        "get_cached_clients",
        lambda nodes, email_filter=None: [
            {"email": "one@test.local", "node_name": "alpha"},
            {"email": "two@test.local", "node_name": "alpha"},
        ],
    )
    client = TestClient(main.app)

    response = client.get("/api/v1/clients", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["clients"][0]["email"] == "one@test.local"


def test_snapshots_latest_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    main.snapshot_collector._latest = {
        "timestamp": 1234567890,
        "nodes": {
            "alpha": {"name": "alpha", "available": True},
            "beta": {"name": "beta", "available": False},
        },
    }
    client = TestClient(main.app)

    response = client.get("/api/v1/snapshots/latest", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["nodes"][0]["name"] == "alpha"


def test_monitoring_stack_smoke(monkeypatch):
    monkeypatch.setattr(main.p, "authenticate", lambda u, p: True)
    client = TestClient(main.app)

    response = client.get("/api/v1/monitoring/stack", headers=_basic_auth())

    assert response.status_code == 200
    payload = response.json()
    assert "services" in payload
    assert "prometheus" in payload["services"]
    assert "public_paths" in payload
