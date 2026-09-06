from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_lifecycle import TelegramLifecycleWorker
from services.telegram_provisioning import ProvisioningRemoteError, RemoteClient
from services.telegram_registry import TelegramRegistry


class FakeLifecyclePort:
    def __init__(self, *, update_error: Exception | None = None, delete_error: Exception | None = None):
        self.clients: list[RemoteClient] = []
        self.update_calls: list[tuple[str, bool]] = []
        self.delete_calls: list[str] = []
        self.update_error = update_error
        self.delete_error = delete_error

    def list_clients(self, *, node, inbound_id, email):
        assert inbound_id == 1
        return [client for client in self.clients if client.email == email]

    def set_client_enabled(self, *, node, inbound_id, client_id, enabled):
        assert inbound_id == 1
        self.update_calls.append((client_id, enabled))
        if self.update_error:
            raise self.update_error
        self.clients = [
            RemoteClient(client.client_id, client.email, client.sub_id, client.flow, enabled)
            if client.client_id == client_id else client
            for client in self.clients
        ]

    def delete_client(self, *, node, inbound_id, client_id):
        assert inbound_id == 1
        self.delete_calls.append(client_id)
        if self.delete_error:
            raise self.delete_error
        self.clients = [client for client in self.clients if client.client_id != client_id]


def _queue(tmp_path, operation_type: str):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (1, 'edge-a', 1, 0)")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="lifecycle-worker", origin="manual", email_source="admin", public_code="lifecycle-worker"
    )
    registry.get_or_create_identity(
        telegram_user_id=55, chat_id=55, username="lifecycle_user", first_name=None, last_name=None
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 55",
            (customer_id,),
        )
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, 1, 1, 'remote-id', 'remote-sub', 'lifecycle-worker',
                    'admin_confirmed', 'confirmed', 1, 1)
            """,
            (customer_id,),
        )
    preview = registry.preview_customer_operation(customer_id=customer_id, operation_type=operation_type)
    result = registry.queue_customer_operation(
        customer_id=customer_id,
        operation_type=operation_type,
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest,
        idempotency_key=f"{operation_type}-worker",
        created_by="admin",
    )
    return db_path, registry, customer_id, result.operation_id


def _worker(db_path, port, *, now=None, node=None):
    return TelegramLifecycleWorker(
        db_path=db_path,
        node_loader=lambda _node_id: node if node is not None else {"id": 1, "enabled": 1, "read_only": 0},
        port=port,
        worker_id="lifecycle-test-worker",
        now=now or (lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )


def test_suspend_then_resume_reconciles_exact_client_and_restores_only_prior_enabled_state(tmp_path):
    db_path, registry, customer_id, suspend_operation_id = _queue(tmp_path, "suspend")
    port = FakeLifecyclePort()
    port.clients = [RemoteClient("remote-id", "lifecycle-worker", "remote-sub", "xtls-rprx-vision", True)]

    suspended = _worker(db_path, port).run_once()

    assert suspended.outcome == "succeeded"
    assert port.update_calls == [("remote-id", False)]
    assert port.clients[0].enabled is False
    assert registry.get_customer_operation(suspend_operation_id).status == "succeeded"
    assert registry.get_customer(customer_id).status == "suspended"
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT desired_enabled, last_enabled, suspended_by_operation_id FROM customer_node_bindings"
        ).fetchone() == (0, 0, suspend_operation_id)
        assert conn.execute(
            "SELECT event_type, entity_id, payload_json FROM telegram_outbox WHERE event_type = 'user_lifecycle_completed'"
        ).fetchone() == ("user_lifecycle_completed", "55", '{"operation":"suspend"}')

    resume_preview = registry.preview_customer_operation(customer_id=customer_id, operation_type="resume")
    resume = registry.queue_customer_operation(
        customer_id=customer_id,
        operation_type="resume",
        expected_customer_version=resume_preview.expected_customer_version,
        target_snapshot_digest=resume_preview.target_snapshot_digest,
        idempotency_key="resume-worker",
        created_by="admin",
    )
    resumed = _worker(db_path, port).run_once()

    assert resumed.outcome == "succeeded"
    assert port.update_calls == [("remote-id", False), ("remote-id", True)]
    assert port.clients[0].enabled is True
    assert registry.get_customer_operation(resume.operation_id).status == "succeeded"
    assert registry.get_customer(customer_id).status == "active"
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT desired_enabled, last_enabled, suspended_by_operation_id FROM customer_node_bindings"
        ).fetchone() == (1, 1, None)


def test_delete_requires_read_after_write_and_only_tombstones_after_exact_remote_absence(tmp_path):
    db_path, registry, customer_id, operation_id = _queue(tmp_path, "delete")
    port = FakeLifecyclePort()
    port.clients = [RemoteClient("remote-id", "lifecycle-worker", "remote-sub", "xtls-rprx-vision", True)]

    outcome = _worker(db_path, port).run_once()

    assert outcome.outcome == "succeeded"
    assert port.delete_calls == ["remote-id"]
    assert port.clients == []
    assert registry.get_customer_operation(operation_id).status == "succeeded"
    assert registry.get_customer(customer_id).status == "deleted"
    with connect(db_path) as conn:
        assert conn.execute("SELECT management_state, desired_enabled FROM customer_node_bindings").fetchone() == (
            "missing", 0
        )
        assert conn.execute(
            "SELECT event_type, entity_id, payload_json FROM telegram_outbox WHERE event_type = 'user_lifecycle_completed'"
        ).fetchone() == ("user_lifecycle_completed", "55", '{"operation":"delete"}')
        assert conn.execute(
            "SELECT access_status, customer_id FROM telegram_identities WHERE telegram_user_id = 55"
        ).fetchone() == ("eligible", None)


def test_uncertain_lifecycle_write_is_ambiguous_and_not_replayed_immediately(tmp_path):
    db_path, registry, _customer_id, operation_id = _queue(tmp_path, "suspend")
    port = FakeLifecyclePort(update_error=ProvisioningRemoteError("connection reset"))
    port.clients = [RemoteClient("remote-id", "lifecycle-worker", "remote-sub", "xtls-rprx-vision", True)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = _worker(db_path, port, now=lambda: now)

    first = worker.run_once()
    second = worker.run_once()

    assert first.outcome == "ambiguous"
    assert second.processed is False
    assert port.update_calls == [("remote-id", False)]
    operation = registry.get_customer_operation(operation_id)
    assert operation.status == "partial"
    assert operation.attempts[0].status == "ambiguous"
    assert operation.attempts[0].error_code == "remote_update_uncertain"

    queued = registry.reschedule_customer_operation(
        operation_id=operation_id,
        expected_operation_version=operation.row_version,
        idempotency_key="retry-uncertain-lifecycle",
        requested_by="admin",
        action="reconcile",
    )
    replay = registry.reschedule_customer_operation(
        operation_id=operation_id,
        expected_operation_version=operation.row_version,
        idempotency_key="retry-uncertain-lifecycle",
        requested_by="another-admin",
        action="reconcile",
    )
    assert queued == replay
    assert queued.status == "queued"
    assert port.update_calls == [("remote-id", False)]


def test_conflicting_remote_email_never_triggers_lifecycle_write(tmp_path):
    db_path, registry, _customer_id, operation_id = _queue(tmp_path, "suspend")
    port = FakeLifecyclePort()
    port.clients = [RemoteClient("other-id", "lifecycle-worker", "other-sub", "xtls-rprx-vision", True)]

    outcome = _worker(db_path, port).run_once()

    assert outcome.outcome == "conflict"
    assert port.update_calls == []
    operation = registry.get_customer_operation(operation_id)
    assert operation.status == "partial"
    assert operation.attempts[0].status == "conflict"


def test_node_suspend_worker_changes_only_selected_binding_and_keeps_customer_active(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (1, 'edge-a', 1, 0)")
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (2, 'edge-b', 1, 0)")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="node-worker", origin="manual", email_source="admin", public_code="node-worker"
    )
    with connect(db_path) as conn:
        for node_id, remote_id in ((1, "remote-a"), (2, "remote-b")):
            conn.execute(
                """
                INSERT INTO customer_node_bindings
                    (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                     source, management_state, desired_enabled, last_enabled)
                VALUES (?, ?, 1, ?, ?, 'node-worker', 'admin_confirmed', 'confirmed', 1, 1)
                """,
                (customer_id, node_id, remote_id, f"sub-{node_id}"),
            )
    preview = registry.preview_customer_node_operation(
        customer_id=customer_id, node_id=1, operation_type="suspend_node"
    )
    operation = registry.queue_customer_node_operation(
        customer_id=customer_id,
        node_id=1,
        operation_type="suspend_node",
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest,
        idempotency_key="node-worker-suspend",
        created_by="admin",
    )
    port = FakeLifecyclePort()
    port.clients = [RemoteClient("remote-a", "node-worker", "sub-1", "xtls-rprx-vision", True)]

    result = _worker(db_path, port).run_once()

    assert result.outcome == "succeeded"
    assert port.update_calls == [("remote-a", False)]
    assert registry.get_customer(customer_id).status == "active"
    assert registry.get_customer_operation(operation.operation_id).status == "succeeded"
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT node_id, desired_enabled, suspended_by_operation_id FROM customer_node_bindings ORDER BY node_id"
        ).fetchall()
    assert rows == [(1, 0, operation.operation_id), (2, 1, None)]
