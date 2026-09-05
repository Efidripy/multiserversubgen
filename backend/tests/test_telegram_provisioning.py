from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_provisioning import (
    ClientManagerProvisioningPort,
    ProvisioningRemoteError,
    RemoteClient,
    TelegramProvisioningWorker,
)
from services.telegram_registry import TelegramRegistry


class FakeProvisioningPort:
    def __init__(self, *, add_error: Exception | None = None, compatible: bool = True):
        self.clients: list[RemoteClient] = []
        self.add_calls: list[dict] = []
        self.add_error = add_error
        self.compatible = compatible

    def supports_fixed_contract(self, *, node, inbound_id):
        assert inbound_id == 1
        return self.compatible

    def list_clients(self, *, node, inbound_id, email):
        assert inbound_id == 1
        return [client for client in self.clients if client.email == email]

    def add_client(self, *, node, inbound_id, client):
        assert inbound_id == 1
        self.add_calls.append(client)
        if self.add_error:
            raise self.add_error
        self.clients.append(
            RemoteClient(
                client_id=client["id"], email=client["email"], sub_id=client["subId"],
                flow=client["flow"], enabled=client["enable"],
            )
        )


def _queued_job(tmp_path, *, validity_days: int = 0):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (1, 'edge-a', 1, 0)")
        conn.execute(
            """
            INSERT INTO telegram_node_policies
                (node_id, provisioning_enabled, total_bytes, validity_days, client_enabled)
            VALUES (1, 1, 123, ?, 1)
            """,
            (validity_days,),
        )
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=55, chat_id=55, username="worker-user", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(55)
    approval = registry.approve_new_application(
        telegram_user_id=55,
        expected_identity_version=pending.identity.row_version,
        email_display=None,
        idempotency_key="worker-approval",
        approved_by="admin",
    )
    with connect(db_path) as conn:
        attempt = conn.execute(
            """
            SELECT id, desired_client_id, desired_sub_id, desired_expiry_time
            FROM telegram_provisioning_attempts WHERE job_id = ?
            """,
            (approval.job_id,),
        ).fetchone()
    return db_path, approval, attempt


def _worker(db_path, port, *, now=None, node=None):
    return TelegramProvisioningWorker(
        db_path=db_path,
        node_loader=lambda _node_id: node if node is not None else {"id": 1, "enabled": 1, "read_only": 0},
        port=port,
        worker_id="test-worker",
        now=now or (lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )


def test_worker_reads_then_creates_then_confirms_exact_binding_with_fixed_contract(tmp_path):
    db_path, approval, attempt = _queued_job(tmp_path, validity_days=7)
    port = FakeProvisioningPort()

    outcome = _worker(db_path, port).run_once()

    assert outcome.outcome == "succeeded"
    assert len(port.add_calls) == 1
    assert port.add_calls[0] == {
        "id": attempt[1],
        "email": "worker-user",
        "subId": attempt[2],
        "flow": "xtls-rprx-vision",
        "totalGB": 123,
        "expiryTime": attempt[3],
        "enable": True,
    }
    assert attempt[3] > 0
    with connect(db_path) as conn:
        assert conn.execute("SELECT status FROM telegram_provisioning_jobs WHERE id = ?", (approval.job_id,)).fetchone()[0] == "succeeded"
        binding = conn.execute(
            "SELECT remote_client_id, remote_sub_id, remote_email, desired_enabled FROM customer_node_bindings"
        ).fetchone()
    assert binding == (attempt[1], attempt[2], "worker-user", 1)


def test_worker_never_adds_when_exact_email_is_already_owned_by_another_remote_client(tmp_path):
    db_path, approval, _attempt = _queued_job(tmp_path)
    port = FakeProvisioningPort()
    port.clients.append(
        RemoteClient("other-id", "worker-user", "other-sub", "xtls-rprx-vision", True)
    )

    outcome = _worker(db_path, port).run_once()

    assert outcome.outcome == "failed"
    assert port.add_calls == []
    with connect(db_path) as conn:
        assert conn.execute("SELECT status FROM telegram_provisioning_jobs WHERE id = ?", (approval.job_id,)).fetchone()[0] == "failed"
        assert conn.execute("SELECT error_code FROM telegram_provisioning_attempts").fetchone()[0] == "identity_conflict"


def test_uncertain_add_is_marked_ambiguous_and_is_not_replayed_immediately(tmp_path):
    db_path, approval, _attempt = _queued_job(tmp_path)
    port = FakeProvisioningPort(add_error=ProvisioningRemoteError("connection reset"))
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    worker = _worker(db_path, port, now=lambda: now)

    first = worker.run_once()
    second = worker.run_once()

    assert first.outcome == "ambiguous"
    assert second.processed is False
    assert len(port.add_calls) == 1
    with connect(db_path) as conn:
        assert conn.execute("SELECT status FROM telegram_provisioning_jobs WHERE id = ?", (approval.job_id,)).fetchone()[0] == "partial"
        row = conn.execute("SELECT status, error_code, next_attempt_at FROM telegram_provisioning_attempts").fetchone()
    assert row[0] == "ambiguous"
    assert row[1] == "remote_add_uncertain"
    assert row[2] is not None


def test_expired_running_lease_is_recovered_by_a_new_worker_without_blind_add(tmp_path):
    db_path, approval, attempt = _queued_job(tmp_path)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_provisioning_jobs SET status = 'running', lease_owner = 'dead', lease_until = ? WHERE id = ?",
            ((datetime(2026, 1, 1) - timedelta(seconds=1)).isoformat(sep=" "), approval.job_id),
        )
    port = FakeProvisioningPort()
    port.clients.append(RemoteClient(attempt[1], "worker-user", attempt[2], "xtls-rprx-vision", True))

    outcome = _worker(db_path, port).run_once()

    assert outcome.outcome == "succeeded"
    assert port.add_calls == []


def test_client_manager_port_uses_strict_read_and_preserves_exact_inbound_filter():
    class StrictManager:
        def __init__(self):
            self.added = None

        def get_node_clients_strict(self, node):
            return [
                {"id": "wrong-inbound", "email": "same", "subId": "a", "flow": "xtls-rprx-vision", "inbound_id": 2},
                {"id": "target", "email": "same", "subId": "b", "flow": "xtls-rprx-vision", "inbound_ids": [1]},
            ]

        def inbound_supports_telegram_contract_strict(self, node, inbound_id):
            return inbound_id == 1

        def add_client(self, node, inbound_id, client):
            self.added = (node, inbound_id, client)
            return True

    manager = StrictManager()
    port = ClientManagerProvisioningPort(manager)
    clients = port.list_clients(node={"id": 1}, inbound_id=1, email="same")
    port.add_client(node={"id": 1}, inbound_id=1, client={"id": "new"})

    assert clients == [RemoteClient("target", "same", "b", "xtls-rprx-vision", True)]
    assert manager.added == ({"id": 1}, 1, {"id": "new"})


def test_worker_skips_attempt_when_current_inbound_no_longer_supports_fixed_contract(tmp_path):
    db_path, approval, _attempt = _queued_job(tmp_path)
    port = FakeProvisioningPort(compatible=False)

    outcome = _worker(db_path, port).run_once()

    assert outcome.outcome == "skipped"
    assert port.add_calls == []
    with connect(db_path) as conn:
        assert conn.execute("SELECT status FROM telegram_provisioning_jobs WHERE id = ?", (approval.job_id,)).fetchone()[0] == "failed"
        assert conn.execute("SELECT error_code FROM telegram_provisioning_attempts").fetchone()[0] == "inbound_contract_incompatible"


def test_admin_reconcile_reschedules_failed_attempt_without_remote_io_and_requires_fresh_version(tmp_path):
    db_path, approval, _attempt = _queued_job(tmp_path)
    port = FakeProvisioningPort(compatible=False)
    assert _worker(db_path, port).run_once().outcome == "skipped"
    registry = TelegramRegistry(db_path)
    failed = registry.get_provisioning_job(approval.job_id)
    assert failed.status == "failed"

    queued = registry.reschedule_provisioning_job(
        job_id=approval.job_id,
        expected_job_version=failed.row_version,
        idempotency_key="reconcile-failed-job",
        requested_by="admin",
        action="reconcile",
    )
    replay = registry.reschedule_provisioning_job(
        job_id=approval.job_id,
        expected_job_version=failed.row_version,
        idempotency_key="reconcile-failed-job",
        requested_by="another-admin",
        action="reconcile",
    )

    assert queued == replay
    assert queued.status == "queued"
    assert port.add_calls == []
    refreshed = registry.get_provisioning_job(approval.job_id)
    assert refreshed.row_version == queued.row_version
    assert refreshed.attempts[0].status == "pending"
