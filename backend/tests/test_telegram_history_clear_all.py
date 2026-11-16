from __future__ import annotations

import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.telegram_admin import build_telegram_admin_router
from services.db_bootstrap import connect, init_db
from services.telegram_registry import IdempotencyConflictError, TelegramRegistry, TelegramRegistryError


def _registry(tmp_path):
    path = str(tmp_path / "history-all.db")
    init_db(path)
    with connect(path) as conn:
        conn.execute("INSERT INTO nodes(id, name, enabled, read_only) VALUES (1, 'edge-test', 1, 0)")
    return TelegramRegistry(path), path


def _customer(registry: TelegramRegistry) -> int:
    return registry.create_customer(
        email_display="history-all-user",
        origin="manual",
        email_source="admin",
        public_code="history-all-code",
    )


def _insert_job(conn, customer_id: int, key: str, status: str) -> int:
    return conn.execute(
        """
        INSERT INTO telegram_provisioning_jobs
            (customer_id, trigger, idempotency_key, status, policy_snapshot_digest, created_by,
             finished_at)
        VALUES (?, 'manual_sync', ?, ?, 'digest', 'test',
                CASE WHEN ? IN ('succeeded', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP END)
        """,
        (customer_id, key, status, status),
    ).lastrowid


def test_clear_jobs_all_hides_protected_and_keeps_active(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = _customer(registry)
    with connect(path) as conn:
        deleted_job = _insert_job(conn, customer_id, "job-deleted", "succeeded")
        protected_job = _insert_job(conn, customer_id, "job-protected", "succeeded")
        for status in ("queued", "running", "partial"):
            _insert_job(conn, customer_id, f"job-{status}", status)
        conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, status, desired_client_id, desired_sub_id, policy_version,
                 remote_client_id, finished_at)
            VALUES (?, 1, 'succeeded', 'client', 'sub', 1, 'remote-client', CURRENT_TIMESTAMP)
            """,
            (protected_job,),
        )

    result = registry.clear_terminal_provisioning_history(
        idempotency_key="jobs-all", cleared_by="admin", mode="all"
    )
    assert result == {"deleted_count": 1, "hidden_count": 1}
    assert registry.clear_terminal_provisioning_history(
        idempotency_key="jobs-all", cleared_by="admin", mode="all"
    ) == result
    with pytest.raises(IdempotencyConflictError):
        registry.clear_terminal_provisioning_history(
            idempotency_key="jobs-all", cleared_by="admin", mode="safe"
        )
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE id = ?", (deleted_job,)).fetchone()[0] == 0
        assert conn.execute("SELECT hidden_at IS NOT NULL FROM telegram_provisioning_jobs WHERE id = ?", (protected_job,)).fetchone()[0] == 1
        assert {row[0] for row in conn.execute("SELECT status FROM telegram_provisioning_jobs WHERE hidden_at IS NULL")} == {
            "queued", "running", "partial"
        }
    assert registry.list_provisioning_jobs_page()[1] == 3
    assert registry.history_overview()["jobs"]["total"] == 3
    assert registry.history_clear_count("jobs") == 0


def test_clear_operations_all_hides_protected_and_keeps_active(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = _customer(registry)
    with connect(path) as conn:
        deleted_id = conn.execute(
            """
            INSERT INTO telegram_customer_operations
                (customer_id, operation_type, status, target_snapshot_digest,
                 expected_customer_version, idempotency_key, created_by, finished_at)
            VALUES (?, 'suspend_node', 'succeeded', 'digest', 1, 'op-deleted', 'test', CURRENT_TIMESTAMP)
            """,
            (customer_id,),
        ).lastrowid
        protected_id = conn.execute(
            """
            INSERT INTO telegram_customer_operations
                (customer_id, operation_type, status, target_snapshot_digest,
                 expected_customer_version, idempotency_key, created_by, finished_at)
            VALUES (?, 'suspend_node', 'succeeded', 'digest', 1, 'op-protected', 'test', CURRENT_TIMESTAMP)
            """,
            (customer_id,),
        ).lastrowid
        for status in ("queued", "running", "partial"):
            conn.execute(
                """
                INSERT INTO telegram_customer_operations
                    (customer_id, operation_type, status, target_snapshot_digest,
                     expected_customer_version, idempotency_key, created_by)
                VALUES (?, 'suspend_node', ?, 'digest', 1, ?, 'test')
                """,
                (customer_id, status, f"op-{status}"),
            )
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, suspended_by_operation_id)
            VALUES (?, 1, 'remote', '', 'history-all-user', 'admin_confirmed',
                    'confirmed', 0, ?)
            """,
            (customer_id, protected_id),
        )

    result = registry.clear_customer_operation_history(
        idempotency_key="operations-all", cleared_by="admin", mode="all"
    )
    assert result == {"deleted_count": 1, "hidden_count": 1}
    assert registry.clear_customer_operation_history(
        idempotency_key="operations-all", cleared_by="admin", mode="all"
    ) == result
    with pytest.raises(IdempotencyConflictError):
        registry.clear_customer_operation_history(
            idempotency_key="operations-all", cleared_by="admin", mode="safe"
        )
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operations WHERE id = ?", (deleted_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT hidden_at IS NOT NULL FROM telegram_customer_operations WHERE id = ?", (protected_id,)).fetchone()[0] == 1
        assert {row[0] for row in conn.execute("SELECT status FROM telegram_customer_operations WHERE hidden_at IS NULL")} == {
            "queued", "running", "partial"
        }
    assert registry.list_customer_operations_page()[1] == 3
    assert registry.history_overview()["operations"]["total"] == 3
    assert registry.history_clear_count("operations") == 0


def test_clear_drift_all_hides_non_open_and_keeps_open(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = _customer(registry)
    with connect(path) as conn:
        for key, status in (("resolved", "resolved"), ("adopted", "adopted"), ("ignored", "ignored"), ("open", "open")):
            conn.execute(
                """
                INSERT INTO telegram_drift_findings
                    (finding_key, kind, customer_id, node_id, remote_email,
                     remote_client_id, remote_sub_id, status)
                VALUES (?, 'binding_conflict', ?, 1, 'history-all-user', ?, '', ?)
                """,
                (key, customer_id, key, status),
            )

    result = registry.clear_drift_history(idempotency_key="drift-all", cleared_by="admin", mode="all")
    assert result == {"deleted_count": 3, "hidden_count": 0}
    assert registry.clear_drift_history(idempotency_key="drift-all", cleared_by="admin", mode="all") == result
    with pytest.raises(IdempotencyConflictError):
        registry.clear_drift_history(idempotency_key="drift-all", cleared_by="admin", mode="safe")
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NOT NULL").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM telegram_drift_findings WHERE status <> 'open'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM telegram_drift_findings WHERE status = 'open'").fetchone()[0] == 1
    assert registry.list_drift_page()[1] == 1
    assert registry.history_overview()["drift"]["open"] == 1


def test_safe_clear_returns_int_and_does_not_hide(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = _customer(registry)
    with connect(path) as conn:
        _insert_job(conn, customer_id, "safe-job", "succeeded")
    assert registry.clear_terminal_provisioning_history(idempotency_key="safe", cleared_by="admin") == 1
    assert registry.clear_terminal_provisioning_history(idempotency_key="safe", cleared_by="admin") == 1
    with connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs").fetchone()[0] == 0


def test_safe_operation_and_drift_clear_return_int(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = _customer(registry)
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO telegram_customer_operations(customer_id, operation_type, status, target_snapshot_digest, expected_customer_version, idempotency_key, created_by, finished_at) VALUES (?, 'suspend_node', 'succeeded', 'digest', 1, 'safe-op', 'test', CURRENT_TIMESTAMP)",
            (customer_id,),
        )
        conn.execute(
            "INSERT INTO telegram_drift_findings(finding_key, kind, customer_id, node_id, remote_email, remote_client_id, remote_sub_id, status) VALUES ('safe-drift', 'binding_conflict', ?, 1, 'history-all-user', 'remote', '', 'resolved')",
            (customer_id,),
        )
    assert registry.clear_customer_operation_history(idempotency_key="safe-op-clear", cleared_by="admin") == 1
    assert registry.clear_drift_history(idempotency_key="safe-drift-clear", cleared_by="admin") == 1


def test_clear_audit_history_is_atomic_and_idempotent(tmp_path):
    registry, path = _registry(tmp_path)
    with connect(path) as conn:
        for event in ("ok", "error", "success"):
            conn.execute(
                "INSERT INTO telegram_audit_log(event_type, actor_type, entity_type, entity_id) VALUES (?, 'system', 'test', '1')",
                (event,),
            )
    result = registry.clear_audit_history(idempotency_key="audit-clear", cleared_by="admin")
    assert result == {"deleted_count": 3, "hidden_count": 0}
    assert registry.clear_audit_history(idempotency_key="audit-clear", cleared_by="admin") == result
    with connect(path) as conn:
        rows = conn.execute("SELECT event_type FROM telegram_audit_log").fetchall()
    assert rows == [("audit_cleared",)]


def test_audit_clear_endpoint_requires_capability(tmp_path):
    _registry_obj, path = _registry(tmp_path)
    app = FastAPI()
    app.include_router(
        build_telegram_admin_router(
            check_auth=lambda request: "admin",
            get_user_role=lambda username: "admin",
            db_path=path,
            list_nodes=lambda: [],
            get_cached_inbound_options=lambda nodes: [],
            client_mgr=None,
            is_owner=lambda username: False,
        )
    )
    client = TestClient(app)
    response = client.post("/api/v1/telegram/history/audit/clear", json={"idempotency_key": "denied"})
    assert response.status_code == 403


def test_audit_clear_endpoint_owner_returns_result(tmp_path):
    registry, path = _registry(tmp_path)
    with connect(path) as conn:
        conn.execute("INSERT INTO telegram_audit_log(event_type, actor_type, entity_type, entity_id) VALUES ('old', 'system', 'test', '1')")
    app = FastAPI()
    app.include_router(
        build_telegram_admin_router(
            check_auth=lambda request: "owner",
            get_user_role=lambda username: "owner",
            db_path=path,
            list_nodes=lambda: [],
            get_cached_inbound_options=lambda nodes: [],
            client_mgr=None,
            is_owner=lambda username: True,
        )
    )
    response = TestClient(app).post("/api/v1/telegram/history/audit/clear", json={"idempotency_key": "owner-clear"})
    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1, "hidden_count": 0}


def test_history_filters_paginate_more_than_two_hundred_rows(tmp_path):
    registry, path = _registry(tmp_path)
    customer_id = _customer(registry)
    with connect(path) as conn:
        for index in range(250):
            _insert_job(conn, customer_id, f"filter-job-{index}", "succeeded" if index % 2 else "failed")
            conn.execute(
                """
                INSERT INTO telegram_customer_operations
                    (customer_id, operation_type, status, target_snapshot_digest,
                     expected_customer_version, idempotency_key, created_by)
                VALUES (?, 'suspend_node', ?, 'digest', 1, ?, 'test')
                """,
                (customer_id, "succeeded" if index % 2 else "failed", f"filter-op-{index}"),
            )
            conn.execute(
                """
                INSERT INTO telegram_drift_findings
                    (finding_key, kind, customer_id, node_id, remote_email,
                     remote_client_id, remote_sub_id, status)
                VALUES (?, 'binding_conflict', ?, 1, 'history-all-user', ?, '', ?)
                """,
                (f"filter-drift-{index}", customer_id, str(index), "open" if index % 2 else "resolved"),
            )
            conn.execute(
                "INSERT INTO telegram_audit_log(event_type, actor_type, entity_type, entity_id) VALUES (?, 'system', 'test', '1')",
                ("request_error" if index % 2 else "request_ok",),
            )
    jobs, jobs_total = registry.list_provisioning_jobs_page(limit=200, status="succeeded")
    operations, operations_total = registry.list_customer_operations_page(limit=200, status="succeeded")
    drift, drift_total = registry.list_drift_page(status="open", limit=200)
    audit, audit_total = registry.list_audit_page(limit=200, outcome="error")
    assert len(jobs) == 125 and jobs_total == 125
    assert len(operations) == 125 and operations_total == 125
    assert len(drift) == 125 and drift_total == 125
    assert len(audit) == 125 and audit_total == 125
    _, audit_success_total = registry.list_audit_page(limit=200, outcome="success")
    assert audit_success_total == 125
    assert registry.list_provisioning_jobs_page(limit=25, offset=120, status="succeeded")[1] == 125
    assert registry.list_customer_operations_page(limit=25, offset=120, status="succeeded")[1] == 125
    assert registry.list_drift_page(status="open", limit=25, offset=120)[1] == 125
    assert registry.list_audit_page(limit=25, offset=120, outcome="error")[1] == 125
    for call in (
        lambda: registry.list_provisioning_jobs_page(status="bogus"),
        lambda: registry.list_customer_operations_page(status="bogus"),
        lambda: registry.list_drift_page(status="bogus"),
        lambda: registry.list_audit_page(outcome="bogus"),
    ):
        with pytest.raises(TelegramRegistryError):
            call()


def test_rescan_reopens_and_unhides_a_resolved_hidden_finding(tmp_path):
    registry, path = _registry(tmp_path)
    payload = {
        "kind": "orphan_remote", "customer_id": None, "node_id": 1,
        "remote_email": "orphan-user", "remote_client_id": "remote-client", "remote_sub_id": "remote-sub",
    }
    first = registry.record_drift_findings(scanned_node_ids=[1], findings=[payload])
    registry.resolve_drift_finding(
        finding_id=first[0].finding_id, expected_row_version=first[0].row_version, status="resolved", resolved_by="admin",
    )
    with connect(path) as conn:
        conn.execute("UPDATE telegram_drift_findings SET hidden_at = CURRENT_TIMESTAMP")

    registry.record_drift_findings(scanned_node_ids=[1], findings=[payload])

    items, total = registry.list_drift_page(status="open")
    assert total == 1 and items[0].status == "open"
