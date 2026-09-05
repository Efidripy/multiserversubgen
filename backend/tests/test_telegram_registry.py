from __future__ import annotations

import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_registry import (
    IdempotencyConflictError,
    NodePolicyUnavailableError,
    TelegramRegistry,
    TelegramRegistryError,
    VersionConflictError,
)


def _insert_node(db_path: str, node_id: int, name: str, *, enabled: int = 1, read_only: int = 0) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO nodes (id, name, enabled, read_only) VALUES (?, ?, ?, ?)",
            (node_id, name, enabled, read_only),
        )


def test_telegram_schema_is_idempotent_and_foreign_keys_are_enforced(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    init_db(db_path)

    with connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert {
            "customers",
            "telegram_identities",
            "telegram_node_policies",
            "customer_node_bindings",
            "telegram_provisioning_jobs",
            "telegram_provisioning_attempts",
            "telegram_customer_operations",
            "telegram_customer_operation_attempts",
            "telegram_updates",
            "telegram_abuse_state",
            "telegram_outbox",
            "telegram_audit_log",
            "telegram_command_receipts",
        } <= tables
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    _insert_node(db_path, 1, "cascade-target")
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id) VALUES (1)")
        conn.execute("DELETE FROM nodes WHERE id = 1")
        assert conn.execute("SELECT COUNT(*) FROM telegram_node_policies").fetchone()[0] == 0


def test_customer_live_email_is_unique_but_deleted_tombstone_allows_new_registration(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)

    first = registry.create_customer(
        email_display="Alice", origin="telegram", email_source="telegram_name", public_code="first"
    )
    with pytest.raises(TelegramRegistryError, match="already exists"):
        registry.create_customer(
            email_display=" ALICE ", origin="telegram", email_source="telegram_name", public_code="second"
        )

    with connect(db_path) as conn:
        conn.execute(
            "UPDATE customers SET status = 'deleted', deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (first,),
        )
    second = registry.create_customer(
        email_display="Alice", origin="telegram", email_source="telegram_name", public_code="second"
    )
    assert second != first


def test_identity_uses_numeric_id_and_updates_only_display_metadata(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)

    first = registry.get_or_create_identity(
        telegram_user_id=42,
        chat_id=42,
        username="old-name",
        first_name="Old",
        last_name=None,
    )
    second = registry.get_or_create_identity(
        telegram_user_id=42,
        chat_id=99,
        username="new-name",
        first_name="New",
        last_name="Person",
        locale="unexpected",
    )

    assert first.telegram_user_id == second.telegram_user_id == 42
    assert first.access_status == second.access_status == "eligible"
    assert second.chat_id == 99
    assert second.row_version == first.row_version + 1
    with connect(db_path) as conn:
        metadata = conn.execute(
            "SELECT username, first_name, last_name, locale FROM telegram_identities WHERE telegram_user_id = 42"
        ).fetchone()
    assert metadata == ("new-name", "New", "Person", "ru")


def test_pending_application_is_deduplicated_and_creates_one_admin_outbox_event(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username=None, first_name="Name", last_name=None
    )

    first = registry.create_pending_application(42)
    second = registry.create_pending_application(42)

    assert first.created is True
    assert first.identity.access_status == "pending"
    assert first.identity.application_attempt == 1
    assert first.request_code
    assert second.created is False
    assert second.identity.application_attempt == 1
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_applications").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM telegram_outbox").fetchone()[0] == 1


def test_introduction_is_one_time_plain_text_for_the_current_pending_attempt(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username=None, first_name="Name", last_name=None
    )
    registry.create_pending_application(42)

    assert registry.submit_introduction(42, "Хочу представиться", maximum_chars=700) is True
    assert registry.submit_introduction(42, "Повтор", maximum_chars=700) is False
    with connect(db_path) as conn:
        text = conn.execute("SELECT introduction_text FROM telegram_applications").fetchone()[0]
    assert text == "Хочу представиться"


def test_policy_command_normalizes_defaults_versions_and_replays_idempotently(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "edge-a")
    registry = TelegramRegistry(db_path)

    first = registry.set_node_provisioning_policy(
        node_id=1,
        provisioning_enabled=True,
        total_bytes="",
        validity_days=None,
        client_enabled="",
        expected_policy_version=0,
        idempotency_key="create-edge-a",
        updated_by="admin",
        node_is_compatible=True,
    )
    assert (first.total_bytes, first.validity_days, first.client_enabled, first.policy_version) == (0, 0, True, 1)

    replay = registry.set_node_provisioning_policy(
        node_id=1,
        provisioning_enabled=True,
        total_bytes="",
        validity_days=None,
        client_enabled="",
        expected_policy_version=0,
        idempotency_key="create-edge-a",
        updated_by="another-admin",
        node_is_compatible=True,
    )
    assert replay == first

    with pytest.raises(IdempotencyConflictError):
        registry.set_node_provisioning_policy(
            node_id=1,
            provisioning_enabled=False,
            total_bytes=0,
            validity_days=0,
            client_enabled=True,
            expected_policy_version=1,
            idempotency_key="create-edge-a",
            updated_by="admin",
            node_is_compatible=True,
        )
    with pytest.raises(VersionConflictError):
        registry.set_node_provisioning_policy(
            node_id=1,
            provisioning_enabled=False,
            total_bytes=0,
            validity_days=0,
            client_enabled=True,
            expected_policy_version=0,
            idempotency_key="stale-edge-a",
            updated_by="admin",
            node_is_compatible=True,
        )


@pytest.mark.parametrize("enabled,read_only,compatible", [(0, 0, True), (1, 1, True), (1, 0, False)])
def test_policy_cannot_enable_unwritable_or_incompatible_node(tmp_path, enabled, read_only, compatible):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "unsafe-edge", enabled=enabled, read_only=read_only)

    with pytest.raises(NodePolicyUnavailableError):
        TelegramRegistry(db_path).set_node_provisioning_policy(
            node_id=1,
            provisioning_enabled=True,
            total_bytes=0,
            validity_days=0,
            client_enabled=True,
            expected_policy_version=0,
            idempotency_key="unsafe-edge",
            updated_by="admin",
            node_is_compatible=compatible,
        )


def test_customer_node_matrix_hides_technical_nodes_but_keeps_problem_bindings(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "bound-now-read-only", read_only=1)
    _insert_node(db_path, 2, "available")
    _insert_node(db_path, 3, "technical-hidden")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="matrix-user", origin="telegram", email_source="admin", public_code="matrix"
    )
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (2, 1)"
        )
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, remote_email, source, desired_enabled, management_state)
            VALUES (?, 1, 'matrix-user', 'bot_provisioned', 1, 'confirmed')
            """,
            (customer_id,),
        )

    rows = registry.customer_node_matrix(customer_id)
    assert [(row.node_id, row.state) for row in rows] == [(1, "problem"), (2, "available_to_add")]
    assert rows[0].binding_id is not None
    assert rows[1].binding_id is None
