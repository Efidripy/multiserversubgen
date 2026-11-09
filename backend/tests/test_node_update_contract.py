"""Regression contract for editing an existing x-ui node connection."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from threading import Lock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers import nodes as nodes_router
from routers.nodes import build_nodes_router
from services.db_bootstrap import connect, init_db
from services.telegram_drift import TelegramDriftScanner
from services.telegram_registry import TelegramRegistry


class _SnapshotCollectorStub:
    def force_poll_all(self):
        raise AssertionError("node editing must not poll a remote panel")

    def get_mode(self):
        return "test"

    def is_running(self):
        return False


class _WsManagerStub:
    active_connections: list[object] = []


@pytest.fixture
def node_client(tmp_path, monkeypatch):
    """A real nodes router backed by an isolated SQLite database."""
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO nodes (
                id, name, panel_url, username, user, password,
                ip, port, base_path, access_path, scheme
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "edge-1",
                "https://old.example.test:8443/old-panel",
                "root",
                "root",
                "encrypted:old-password",
                "old.example.test",
                "8443",
                "old-panel",
                "old-panel",
                "https",
            ),
        )

    # URL parsing and persistence are under test; DNS egress policy is covered
    # independently and must not make this contract depend on external DNS.
    monkeypatch.setattr(nodes_router, "validate_outbound_url", lambda _url: (True, ""))
    invalidations = {"auth": [], "session": [], "capability": [], "reconcile": []}
    monkeypatch.setattr(
        nodes_router,
        "invalidate_auth_method_cache",
        invalidations["auth"].append,
    )
    monkeypatch.setattr(
        nodes_router,
        "invalidate_session_cache",
        invalidations["session"].append,
    )
    monkeypatch.setattr(
        nodes_router,
        "invalidate_node_capabilities",
        invalidations["capability"].append,
    )

    def reconcile(*, node_ids):
        invalidations["reconcile"].extend(node_ids)

    return _client_for(db_path, reconcile), db_path, invalidations


def _client_for(db_path: str, reconcile_telegram_node) -> TestClient:
    app = FastAPI()
    app.include_router(
        build_nodes_router(
            check_auth=lambda _request: "admin",
            node_service=object(),
            get_node_or_404=lambda _node_id: None,
            db_path=db_path,
            encrypt=lambda value: f"encrypted:{value}",
            requests_verify=True,
            login_panel=lambda *_args: False,
            xui_request=lambda *_args, **_kwargs: None,
            invalidate_subscription_cache=lambda: None,
            remove_node_metric_labels=lambda *_args: None,
            node_metric_labels_lock=Lock(),
            node_metric_labels_state={},
            snapshot_collector=_SnapshotCollectorStub(),
            ws_manager=_WsManagerStub(),
            logger=logging.getLogger(__name__),
            reconcile_telegram_node=reconcile_telegram_node,
        )
    )
    return TestClient(app)


def _node_row(db_path: str) -> dict[str, object]:
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM nodes WHERE id = 1").fetchone()
    return dict(row)


def _insert_duplicate(db_path):
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO nodes (id, name, panel_url, username, user, password, ip, port,
                                  base_path, access_path, scheme, enabled)
               VALUES (2, 'duplicate', 'https://OLD.example.test:8443/old-panel/', 'root', 'root', 'x',
                       'OLD.example.test', '8443', 'old-panel/', 'old-panel/', 'https', 0)"""
        )


def test_node_add_rejects_duplicate_panel(node_client):
    client, db_path, _ = node_client
    with connect(db_path) as conn:
        conn.execute("UPDATE nodes SET enabled = 0 WHERE id = 1")
    response = client.post("/api/v1/nodes", json={
        "name": "new", "url": "https://OLD.EXAMPLE.TEST:8443/old-panel/", "user": "root", "password": "x",
    })
    assert response.status_code == 409
    assert response.json()["detail"] == "Another node already uses this panel: #1 edge-1"
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1


def test_node_edit_rejects_duplicate_panel_without_changes(node_client):
    client, db_path, _ = node_client
    _insert_duplicate(db_path)
    with connect(db_path) as conn:
        conn.execute("UPDATE nodes SET ip = 'other.example.test', panel_url = 'https://other.example.test:8443/old-panel' WHERE id = 1")
    before = _node_row(db_path)
    response = client.put("/api/v1/nodes/1", json={
        "name": "changed", "url": "https://old.example.test:8443/old-panel",
    })
    assert response.status_code == 409
    assert response.json()["detail"] == "Another node already uses this panel: #2 duplicate"
    assert _node_row(db_path) == before


def test_node_edit_unchanged_url_allows_existing_duplicate(node_client):
    client, db_path, _ = node_client
    _insert_duplicate(db_path)
    response = client.put("/api/v1/nodes/1", json={
        "name": "renamed", "url": "https://OLD.EXAMPLE.TEST:8443/old-panel/",
    })
    assert response.status_code == 200
    assert _node_row(db_path)["name"] == "renamed"


@pytest.mark.parametrize("url", ["https://old.example.test:9443/old-panel", "https://old.example.test:8443/other"])
def test_node_add_allows_different_port_or_path(node_client, url):
    client, db_path, _ = node_client
    response = client.post("/api/v1/nodes", json={"name": "new", "url": url, "user": "root", "password": "x"})
    assert response.status_code == 200
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 2


def test_node_edit_updates_panel_url_and_password_without_overwriting_username(node_client):
    client, db_path, invalidations = node_client

    response = client.put(
        "/api/v1/nodes/1",
        json={
            "url": "https://edge.example.test:8443/new-panel/",
            "password": "new-password",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    stored = _node_row(db_path)
    assert stored["panel_url"] == "https://edge.example.test:8443/new-panel"
    assert stored["ip"] == "edge.example.test"
    assert stored["port"] == "8443"
    assert stored["base_path"] == "new-panel"
    assert stored["access_path"] == "new-panel"
    assert stored["scheme"] == "https"
    assert stored["password"] == "encrypted:new-password"
    assert stored["username"] == "root"
    assert stored["user"] == "root"
    assert invalidations == {
        "auth": [
            "https://old.example.test:8443/old-panel",
            "https://edge.example.test:8443/new-panel",
        ],
        "session": [
            "old.example.test:8443:old-panel",
            "edge.example.test:8443:new-panel",
        ],
        "capability": [
            "old.example.test:8443:old-panel",
            "edge.example.test:8443:new-panel",
        ],
        "reconcile": [1],
    }


def test_node_endpoint_edit_runs_real_drift_scan_for_that_node_only(node_client, caplog):
    _client, db_path, _invalidations = node_client
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="scan-user", origin="manual", email_source="admin", public_code="scan-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO nodes (id, name, panel_url, username, user, password, ip, port, base_path, access_path, scheme) "
            "VALUES (2, 'edge-2', 'https://other.example.test:8443/p', 'root', 'root', 'x', 'other.example.test', '8443', 'p', 'p', 'https')"
        )
        conn.execute("INSERT INTO telegram_node_policies(node_id, provisioning_enabled) VALUES (1, 1), (2, 1)")
        conn.execute(
            "INSERT INTO customer_node_bindings "
            "(customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state) "
            "VALUES (?, 1, 'gone-client', 'gone-sub', 'scan-user', 'admin_confirmed', 'confirmed')",
            (customer_id,),
        )

    scanned: list[int] = []

    class _ClientManagerStub:
        def get_node_clients_strict(self, node):
            scanned.append(node["id"])
            return []  # a freshly installed panel has none of the bound clients

    scanner = TelegramDriftScanner(
        registry=registry,
        list_nodes=lambda: [{"id": 1}, {"id": 2}],
        client_manager=_ClientManagerStub(),
    )

    response = _client_for(db_path, scanner.scan).put(
        "/api/v1/nodes/1", json={"url": "https://edge.example.test:8443/new-panel/"}
    )

    assert response.status_code == 200
    assert "binding scan after node endpoint update failed" not in caplog.text
    assert scanned == [1]
    findings = registry.list_drift_findings(status="open", limit=10)
    assert [(item.kind, item.node_id) for item in findings] == [("binding_missing", 1)]


def test_node_edit_allows_password_only_and_preserves_username(node_client):
    client, db_path, invalidations = node_client

    response = client.put("/api/v1/nodes/1", json={"password": "rotated-password"})

    assert response.status_code == 200
    stored = _node_row(db_path)
    assert stored["password"] == "encrypted:rotated-password"
    assert stored["username"] == "root"
    assert stored["user"] == "root"
    assert invalidations == {
        "auth": ["https://old.example.test:8443/old-panel"],
        "session": ["old.example.test:8443:old-panel"],
        "capability": ["old.example.test:8443:old-panel"],
        "reconcile": [],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"password": ""},
        {"bearer_token": ""},
        {"bearer_token": "token-value", "user": "root"},
        {"bearer_token": "token-value", "password": "new-password"},
    ],
)
def test_node_edit_rejects_empty_or_conflicting_auth_fields(node_client, payload):
    client, db_path, _invalidations = node_client
    before = _node_row(db_path)

    response = client.put("/api/v1/nodes/1", json=payload)

    assert response.status_code == 400
    assert _node_row(db_path) == before


def test_node_delete_removes_all_local_telegram_and_node_references(node_client):
    client, db_path, _invalidations = node_client
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="delete-node-user", origin="manual", email_source="admin", public_code="delete-node-user"
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies(node_id, provisioning_enabled) VALUES (1, 1)")
        binding = conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, remote_client_id, remote_sub_id, remote_email, source, management_state)
            VALUES (?, 1, 'old-client', 'old-sub', 'delete-node-user', 'admin_confirmed', 'confirmed')
            """,
            (customer_id,),
        )
        job = conn.execute(
            """
            INSERT INTO telegram_provisioning_jobs
                (customer_id, trigger, idempotency_key, policy_snapshot_digest, created_by)
            VALUES (?, 'node_backfill', 'delete-node-job', 'digest', 'test')
            """,
            (customer_id,),
        )
        conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, desired_client_id, desired_sub_id, policy_version)
            VALUES (?, 1, 'queued-client', 'queued-sub', 1)
            """,
            (int(job.lastrowid),),
        )
        operation = conn.execute(
            """
            INSERT INTO telegram_customer_operations
                (customer_id, operation_type, target_snapshot_digest, expected_customer_version, idempotency_key, created_by)
            VALUES (?, 'suspend_node', 'digest', 1, 'delete-node-operation', 'test')
            """,
            (customer_id,),
        )
        conn.execute(
            """
            INSERT INTO telegram_customer_operation_attempts
                (operation_id, binding_id, node_id, remote_client_id, remote_sub_id, remote_email, action)
            VALUES (?, ?, 1, 'old-client', 'old-sub', 'delete-node-user', 'set_enabled_false')
            """,
            (int(operation.lastrowid), int(binding.lastrowid)),
        )
        conn.execute(
            "INSERT INTO client_notes(node_id, inbound_id, client_identifier, email) VALUES (1, 1, 'old-client', 'delete-node-user')"
        )
        conn.execute(
            """
            INSERT INTO node_history(ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms)
            VALUES (1, 1, 'edge-1', 1, 1, 0, 0, 0, 0)
            """
        )
        conn.execute("INSERT INTO node_snapshots(node_id, status_data, is_online) VALUES (1, '{}', 1)")

    with connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")  # skip identity setup; only the node FK matters here
        discovery = conn.execute(
            "INSERT INTO telegram_existing_discovery_jobs (customer_id, telegram_user_id, application_attempt, "
            "idempotency_key, target_snapshot_digest, created_by) VALUES (?, 1, 1, 'delete-node-discovery', 'digest', 'test')",
            (customer_id,),
        )
        conn.execute(
            "INSERT INTO telegram_existing_discovery_targets(job_id, node_id) VALUES (?, 1)", (int(discovery.lastrowid),)
        )

    response = client.delete("/api/v1/nodes/1")

    assert response.status_code == 200
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_existing_discovery_targets").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM telegram_existing_discovery_jobs").fetchone()[0] == "failed"
        for table in (
            "nodes", "telegram_node_policies", "customer_node_bindings", "telegram_provisioning_attempts",
            "telegram_provisioning_jobs", "telegram_customer_operation_attempts", "telegram_customer_operations",
            "client_notes", "node_history", "node_snapshots",
        ):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM customers WHERE id = ?", (customer_id,)).fetchone()[0] == 1
