from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.telegram_admin import build_telegram_admin_router
from services.db_bootstrap import connect, init_db
from services.telegram_registry import TelegramRegistry


def _build_client(tmp_path, *, username: str = "admin", role: str = "admin", options=None, client_mgr=None):
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
            client_mgr=client_mgr,
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


def test_transport_routes_keep_direct_default_and_reject_unconfigured_local_mode(tmp_path):
    client = _build_client(tmp_path)

    current = client.get("/api/v1/telegram/transport")
    assert current.status_code == 200
    assert current.json()["transport"] == {
        "mode": "direct",
        "row_version": 1,
        "configured": False,
        "reachable": False,
        "updated_by": "system",
        "updated_at": current.json()["transport"]["updated_at"],
    }
    rejected = client.put(
        "/api/v1/telegram/transport",
        json={"mode": "local_proxy", "expected_row_version": 1},
    )
    assert rejected.status_code == 409
    assert "not configured" in rejected.json()["detail"]

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.get("/api/v1/telegram/transport").status_code == 403


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


def test_preapproval_and_unlink_routes_are_admin_only_and_never_start_remote_io(tmp_path):
    client = _build_client(tmp_path)
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="preapproved-user", origin="existing", email_source="existing", public_code="preapproved-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, 1, 1, 'preapproved-client', 'preapproved-sub', 'preapproved-user',
                    'existing_bound', 'confirmed', 1, 1)
            """,
            (customer_id,),
        )

    created = client.post(
        "/api/v1/telegram/preapprovals",
        json={
            "telegram_user_id": 42,
            "customer_id": customer_id,
            "expected_preapproval_version": 0,
            "idempotency_key": "http-preapproval-42",
        },
    )

    assert created.status_code == 200
    assert created.json()["remote_io"] == "not_started"
    assert client.get("/api/v1/telegram/preapprovals/42").json()["item"]["customer_id"] == customer_id

    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="preapproved", first_name="Preapproved", last_name=None
    )
    activated = registry.activate_preapproval(42)
    assert activated is not None
    unlink = client.post(
        "/api/v1/telegram/identities/42/unlink",
        json={
            "customer_id": customer_id,
            "expected_identity_version": activated.identity_row_version,
            "idempotency_key": "http-unlink-42",
        },
    )

    assert unlink.status_code == 200
    assert unlink.json()["remote_io"] == "not_started"
    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.post("/api/v1/telegram/preapprovals", json={}).status_code == 403
    assert viewer.post("/api/v1/telegram/identities/42/unlink", json={}).status_code == 403


def test_existing_remote_customer_can_be_discovered_then_adopted_without_node_write(tmp_path):
    class ClientManager:
        @staticmethod
        def get_node_clients_strict(_node):
            return [{
                "id": "legacy-client", "subId": "legacy-sub", "email": "legacy-user",
                "enable": True, "inbound_id": 1, "inbound_ids": [1],
            }]

    client = _build_client(tmp_path, client_mgr=ClientManager())
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=45, chat_id=45, username="legacy-applicant", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(45)
    discover = client.post(
        "/api/v1/telegram/requests/45/discover-existing",
        json={"expected_identity_version": pending.identity.row_version, "email_display": "legacy-user"},
    )
    assert discover.status_code == 200
    assert discover.json()["candidate"] == {
        "email_display": "legacy-user", "binding_count": 1, "node_names": ["edge-1"],
    }
    adopted = client.post(
        "/api/v1/telegram/requests/45/adopt-existing",
        json={
            "expected_identity_version": pending.identity.row_version,
            "email_display": "legacy-user",
            "idempotency_key": "adopt-legacy-45",
        },
    )
    assert adopted.status_code == 200
    assert adopted.json()["remote_io"] == "read_only"
    with connect(db_path) as conn:
        assert conn.execute("SELECT email_display, origin FROM customers").fetchone() == ("legacy-user", "existing")
        assert conn.execute("SELECT remote_client_id FROM customer_node_bindings").fetchone()[0] == "legacy-client"
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs").fetchone()[0] == 0


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


def test_support_routes_are_admin_only_and_resolution_remains_local(tmp_path):
    client = _build_client(tmp_path)
    db_path = str(tmp_path / "admin.db")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="support-api", origin="telegram", email_source="telegram_username", public_code="support-api"
    )
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="support_api", first_name="Support", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42",
            (customer_id,),
        )
    registry.begin_support_request(telegram_user_id=42, category="link")
    request = registry.submit_pending_support_request(telegram_user_id=42, body="Ссылка не открывается.")
    assert request is not None

    listed = client.get("/api/v1/telegram/support")
    assert listed.status_code == 200
    assert listed.json()["items"] == [{
        "support_request_id": request.support_request_id,
        "telegram_user_id": 42,
        "customer_id": customer_id,
        "email_display": "support-api",
        "category": "link",
        "body": "Ссылка не открывается.",
        "status": "open",
        "row_version": 1,
        "created_at": listed.json()["items"][0]["created_at"],
        "updated_at": listed.json()["items"][0]["updated_at"],
        "admin_response": None,
    }]
    resolved = client.post(
        f"/api/v1/telegram/support/{request.support_request_id}/resolve",
        json={
            "expected_row_version": request.row_version,
            "response": "Проверьте, что ссылка скопирована целиком.",
            "idempotency_key": "resolve-support-api",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["remote_io"] == "not_started"
    assert resolved.json()["support_request"]["status"] == "resolved"

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.get("/api/v1/telegram/support").status_code == 403
    assert viewer.post(f"/api/v1/telegram/support/{request.support_request_id}/resolve", json={}).status_code == 403


def test_service_notice_routes_are_admin_only_and_do_not_start_remote_io(tmp_path):
    client = _build_client(tmp_path)

    initial = client.get("/api/v1/telegram/service-notice")
    assert initial.status_code == 200
    assert initial.json()["notice"]["is_active"] is False
    updated = client.put(
        "/api/v1/telegram/service-notice",
        json={
            "body": "Проводим краткие технические работы.",
            "expected_row_version": initial.json()["notice"]["row_version"],
            "idempotency_key": "notice-api-update",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["remote_io"] == "not_started"
    assert updated.json()["notice"]["is_active"] is True

    viewer = _build_client(tmp_path, username="viewer", role="viewer")
    assert viewer.get("/api/v1/telegram/service-notice").status_code == 403
    assert viewer.put("/api/v1/telegram/service-notice", json={}).status_code == 403
