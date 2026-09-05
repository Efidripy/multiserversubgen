from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.telegram_admin import build_telegram_admin_router
from services.db_bootstrap import connect, init_db
from services.telegram_registry import TelegramRegistry


def _build_client(tmp_path, *, username: str = "admin", role: str = "admin", options=None):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO nodes (id, name) VALUES (1, 'edge-1')")
    app = FastAPI()
    app.include_router(
        build_telegram_admin_router(
            check_auth=lambda _request: username,
            get_user_role=lambda _username: role,
            db_path=db_path,
            list_nodes=lambda: [{"id": 1, "name": "edge-1", "enabled": 1, "read_only": 0}],
            get_cached_inbound_options=lambda _nodes: options or [],
        )
    )
    return TestClient(app)


def _policy_payload(**overrides):
    payload = {
        "provisioning_enabled": True,
        "total_bytes": "",
        "validity_days": None,
        "client_enabled": "",
        "expected_policy_version": 0,
        "idempotency_key": "test-create-policy",
    }
    payload.update(overrides)
    return payload


def test_telegram_policy_routes_are_admin_only(tmp_path):
    client = _build_client(tmp_path, username="viewer", role="viewer")

    assert client.get("/api/v1/telegram/node-policies").status_code == 403
    assert client.put("/api/v1/telegram/node-policies/1", json=_policy_payload()).status_code == 403


def test_policy_route_uses_backend_inbound_proof_and_normalizes_defaults(tmp_path):
    client = _build_client(
        tmp_path,
        options=[{"node_id": 1, "id": 1, "enable": True, "protocol": "vless", "tlsFlowCapable": True}],
    )

    response = client.put("/api/v1/telegram/node-policies/1", json=_policy_payload())

    assert response.status_code == 200
    assert response.json() == {
        "policy": {
            "node_id": 1,
            "provisioning_enabled": True,
            "total_bytes": 0,
            "validity_days": 0,
            "client_enabled": True,
            "policy_version": 1,
            "updated_by": "admin",
        },
        "fixed_contract": {"inbound_id": 1, "flow": "xtls-rprx-vision"},
    }
    listed = client.get("/api/v1/telegram/node-policies")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["provisioning_enabled"] is True


def test_policy_route_rejects_inbound_other_than_exact_bot_contract(tmp_path):
    client = _build_client(
        tmp_path,
        options=[{"node_id": 1, "id": 2, "enable": True, "protocol": "vless", "tlsFlowCapable": True}],
    )

    response = client.put("/api/v1/telegram/node-policies/1", json=_policy_payload())

    assert response.status_code == 409
    assert "eligible" in response.json()["detail"]


def test_request_queue_is_admin_only_and_approval_queues_local_work_without_remote_io(tmp_path):
    client = _build_client(tmp_path)
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="Ivan_Petrov", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(42)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (1, 1)")

    queue = client.get("/api/v1/telegram/requests")
    assert queue.status_code == 200
    assert queue.json()["items"][0]["suggested_email"] == "ivan_petrov"
    response = client.post(
        "/api/v1/telegram/requests/42/approve-new",
        json={
            "expected_identity_version": pending.identity.row_version,
            "email_display": "",
            "idempotency_key": "http-approve-42",
        },
    )
    assert response.status_code == 200
    assert response.json()["remote_io"] == "not_started"
    assert response.json()["approval"]["target_node_ids"] == [1]
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM customer_node_bindings").fetchone()[0] == 0

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.get("/api/v1/telegram/requests").status_code == 403
    assert viewer.post(
        "/api/v1/telegram/requests/42/approve-new",
        json={"expected_identity_version": 2, "idempotency_key": "viewer"},
    ).status_code == 403
