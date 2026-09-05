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

    jobs = client.get("/api/v1/telegram/jobs")
    assert jobs.status_code == 200
    assert jobs.json()["items"][0]["status"] == "queued"
    assert jobs.json()["items"][0]["attempts"][0]["node_id"] == 1
    assert "desired_client_id" not in str(jobs.json())
    job_id = response.json()["approval"]["job_id"]
    assert client.get(f"/api/v1/telegram/jobs/{job_id}").status_code == 200

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.get("/api/v1/telegram/requests").status_code == 403
    assert viewer.post(
        "/api/v1/telegram/requests/42/approve-new",
        json={"expected_identity_version": 2, "idempotency_key": "viewer"},
    ).status_code == 403
    assert viewer.get("/api/v1/telegram/jobs").status_code == 403


def test_job_reconcile_is_admin_only_and_queues_no_remote_work_inline(tmp_path):
    client = _build_client(tmp_path)
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=44, chat_id=44, username="retry-user", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(44)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (1, 1)")
    approval = registry.approve_new_application(
        telegram_user_id=44,
        expected_identity_version=pending.identity.row_version,
        email_display=None,
        idempotency_key="queue-retry-job",
        approved_by="admin",
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_provisioning_attempts SET status = 'failed', error_code = 'test' WHERE job_id = ?",
            (approval.job_id,),
        )
        conn.execute("UPDATE telegram_provisioning_jobs SET status = 'failed' WHERE id = ?", (approval.job_id,))
    job = registry.get_provisioning_job(approval.job_id)

    response = client.post(
        f"/api/v1/telegram/jobs/{approval.job_id}/reconcile",
        json={"expected_job_version": job.row_version, "idempotency_key": "http-reconcile"},
    )
    assert response.status_code == 200
    assert response.json()["remote_io"] == "not_started"
    assert response.json()["job"]["status"] == "queued"

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.post(
        f"/api/v1/telegram/jobs/{approval.job_id}/reconcile",
        json={"expected_job_version": 1, "idempotency_key": "viewer-reconcile"},
    ).status_code == 403


def test_customer_read_endpoints_are_admin_only_and_hide_unrelated_nodes(tmp_path):
    client = _build_client(tmp_path)
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="customer-api", origin="manual", email_source="admin", public_code="customer-api"
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (1, 1)")

    listing = client.get("/api/v1/telegram/customers", params={"query": "customer-api"})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["customer_id"] == customer_id
    assert client.get(f"/api/v1/telegram/customers/{customer_id}").status_code == 200
    nodes = client.get(f"/api/v1/telegram/customers/{customer_id}/nodes")
    assert nodes.status_code == 200
    assert nodes.json()["items"] == [{
        "node_id": 1,
        "node_name": "edge-1",
        "state": "available_to_add",
        "binding_id": None,
        "desired_enabled": None,
        "management_state": None,
    }]

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.get("/api/v1/telegram/customers").status_code == 403


def test_customer_lifecycle_preview_and_queue_are_admin_only_and_do_not_run_remote_io(tmp_path):
    client = _build_client(tmp_path)
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="lifecycle-api", origin="manual", email_source="admin", public_code="lifecycle-api"
    )

    preview = client.post(
        f"/api/v1/telegram/customers/{customer_id}/lifecycle/preview",
        json={"operation_type": "suspend"},
    )
    assert preview.status_code == 200
    preview_payload = preview.json()["preview"]
    assert preview.json()["remote_io"] == "not_started"
    queued = client.post(
        f"/api/v1/telegram/customers/{customer_id}/lifecycle",
        json={
            "operation_type": "suspend",
            "expected_customer_version": preview_payload["expected_customer_version"],
            "target_snapshot_digest": preview_payload["target_snapshot_digest"],
            "idempotency_key": "lifecycle-api-suspend",
        },
    )
    assert queued.status_code == 200
    assert queued.json()["operation"]["status"] == "succeeded"
    assert queued.json()["remote_io"] == "not_started"
    assert client.get(f"/api/v1/telegram/customers/{customer_id}/operations").status_code == 200

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.post(
        f"/api/v1/telegram/customers/{customer_id}/lifecycle/preview",
        json={"operation_type": "suspend"},
    ).status_code == 403
