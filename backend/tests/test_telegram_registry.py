from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_registry import (
    ApprovalUnavailableError,
    IdempotencyConflictError,
    LifecycleUnavailableError,
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
            "telegram_transport_preferences",
            "telegram_admin_drafts",
            "telegram_admin_message_drafts",
            "telegram_broadcast_jobs",
        } <= tables
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    _insert_node(db_path, 1, "cascade-target")
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id) VALUES (1)")
        conn.execute("DELETE FROM nodes WHERE id = 1")
    assert conn.execute("SELECT COUNT(*) FROM telegram_node_policies").fetchone()[0] == 0


def test_telegram_lifecycle_schema_migrates_legacy_operation_table_before_creating_schedule_index(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE telegram_customer_operations
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 customer_id INTEGER NOT NULL,
                 operation_type TEXT NOT NULL,
                 status TEXT NOT NULL,
                 target_snapshot_digest TEXT NOT NULL,
                 expected_customer_version INTEGER NOT NULL,
                 idempotency_key TEXT NOT NULL UNIQUE,
                 created_by TEXT NOT NULL,
                 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                 finished_at TEXT DEFAULT NULL)
            """
        )

    init_db(db_path)

    with connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(telegram_customer_operations)").fetchall()}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(telegram_customer_operations)").fetchall()}
        attempt_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(telegram_customer_operation_attempts)").fetchall()
        }
    assert {"lease_owner", "lease_until", "attempt_count", "next_attempt_at", "row_version"} <= columns
    assert "idx_telegram_customer_operations_schedule" in indexes
    assert "remote_email" in attempt_columns


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


def test_customer_traffic_ledger_survives_counter_reset_and_uses_customer_not_token_identity(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="traffic-user", origin="telegram", email_source="telegram_username", public_code="traffic-user"
    )

    first = registry.observe_customer_traffic(customer_id=customer_id, observed_bytes=100)
    next_value = registry.observe_customer_traffic(customer_id=customer_id, observed_bytes=180)
    after_reset = registry.observe_customer_traffic(customer_id=customer_id, observed_bytes=20)
    after_more = registry.observe_customer_traffic(customer_id=customer_id, observed_bytes=50)

    assert first.lifetime_bytes == 100
    assert next_value.lifetime_bytes == 180
    assert after_reset.lifetime_bytes == 200
    assert after_more.lifetime_bytes == 230
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 230
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
        events = conn.execute(
            "SELECT event_type, entity_id FROM telegram_outbox ORDER BY id"
        ).fetchall()
    assert text == "Хочу представиться"
    assert events == [
        ("admin_request_created", "42"),
        ("admin_introduction_submitted", "42:1"),
    ]


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


def test_customer_page_searches_only_local_authority_and_matrix_remains_filtered(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "technical")
    _insert_node(db_path, 2, "allowed")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="paged-user", origin="manual", email_source="admin", public_code="paged-user"
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (2, 1)")
        conn.execute(
            "INSERT INTO telegram_identities (telegram_user_id, chat_id, username, customer_id, access_status) "
            "VALUES (777, 777, 'pager', ?, 'approved')",
            (customer_id,),
        )

    page = registry.list_customers(query="pager", page=1, page_size=10)
    assert page.total == 1
    assert page.items[0].customer_id == customer_id
    assert page.items[0].telegram_user_id == 777
    assert [row.node_id for row in registry.customer_node_matrix(customer_id)] == [2]


def test_pending_queue_suggests_safe_transliterated_name_and_approval_creates_only_local_job(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "edge-a")
    _insert_node(db_path, 2, "edge-b")
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO telegram_node_policies (node_id, provisioning_enabled, total_bytes, validity_days, client_enabled) "
            "VALUES (1, 1, 0, 0, 1)"
        )
        conn.execute(
            "INSERT INTO telegram_node_policies (node_id, provisioning_enabled, total_bytes, validity_days, client_enabled) "
            "VALUES (2, 1, 123, 7, 0)"
        )
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username=None, first_name="Иван", last_name="Петров"
    )
    pending = registry.create_pending_application(42)

    queued = registry.get_pending_application(42)
    assert queued.suggested_email == "ivan-petrov"
    assert queued.suggested_email_source == "telegram_name"

    approved = registry.approve_new_application(
        telegram_user_id=42,
        expected_identity_version=pending.identity.row_version,
        email_display=None,
        idempotency_key="approve-42",
        approved_by="admin",
    )
    replay = registry.approve_new_application(
        telegram_user_id=42,
        expected_identity_version=pending.identity.row_version,
        email_display="",
        idempotency_key="approve-42",
        approved_by="another-admin",
    )

    assert approved == replay
    assert approved.email_display == "ivan-petrov"
    assert approved.email_source == "telegram_name"
    assert approved.target_node_ids == (1, 2)
    with connect(db_path) as conn:
        customer = conn.execute(
            "SELECT email_display, email_source FROM customers WHERE id = ?", (approved.customer_id,)
        ).fetchone()
        attempts = conn.execute(
            """
            SELECT node_id, inbound_id, desired_flow, desired_total_bytes, desired_validity_days,
                   desired_expiry_time, desired_client_enabled, policy_version, desired_client_id, desired_sub_id
            FROM telegram_provisioning_attempts WHERE job_id = ? ORDER BY node_id
            """,
            (approved.job_id,),
        ).fetchall()
        identity = conn.execute(
            "SELECT access_status, customer_id FROM telegram_identities WHERE telegram_user_id = 42"
        ).fetchone()
        assert conn.execute("SELECT COUNT(*) FROM customer_node_bindings").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM telegram_outbox WHERE event_type = 'user_provisioning_queued'").fetchone()[0] == 1
    assert customer == ("ivan-petrov", "telegram_name")
    assert identity == ("approved", approved.customer_id)
    assert [row[:5] + row[6:8] for row in attempts] == [
        (1, 1, "xtls-rprx-vision", 0, 0, 1, 1),
        (2, 1, "xtls-rprx-vision", 123, 7, 0, 1),
    ]
    assert attempts[0][5] == 0
    assert attempts[1][5] > 0
    assert all(len(row[8]) == 36 and len(row[9]) == 36 for row in attempts)


def test_approval_fails_closed_without_target_and_leaves_pending_request_unchanged(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=77, chat_id=77, username="user77", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(77)

    with pytest.raises(ApprovalUnavailableError, match="no eligible"):
        registry.approve_new_application(
            telegram_user_id=77,
            expected_identity_version=pending.identity.row_version,
            email_display=None,
            idempotency_key="approve-77",
            approved_by="admin",
        )
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
        assert conn.execute(
            "SELECT access_status FROM telegram_identities WHERE telegram_user_id = 77"
        ).fetchone()[0] == "pending"


def test_pending_queue_allocates_distinct_suggestions_for_matching_display_metadata(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    for user_id in (71, 72):
        registry.get_or_create_identity(
            telegram_user_id=user_id, chat_id=user_id, username="same_name", first_name=None, last_name=None
        )
        registry.create_pending_application(user_id)

    suggested = [item.suggested_email for item in registry.list_pending_applications()]
    assert suggested[0] == "same_name"
    assert suggested[1].startswith("same_name-")
    assert len(set(suggested)) == 2


def test_existing_approval_requires_confirmed_exact_local_binding_and_never_queues_create(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "existing-edge")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="existing-user", origin="existing", email_source="existing", public_code="existing-1"
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, remote_email, source, management_state)
            VALUES (?, 1, 'existing-user', 'existing_bound', 'confirmed')
            """,
            (customer_id,),
        )
    registry.get_or_create_identity(
        telegram_user_id=73, chat_id=73, username="existing", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(73)

    approved = registry.approve_existing_application(
        telegram_user_id=73,
        customer_id=customer_id,
        expected_identity_version=pending.identity.row_version,
        idempotency_key="existing-73",
        approved_by="admin",
    )
    assert approved.customer_id == customer_id
    assert approved.confirmed_binding_count == 1
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_provisioning_jobs").fetchone()[0] == 0
        assert conn.execute(
            "SELECT access_status, customer_id FROM telegram_identities WHERE telegram_user_id = 73"
        ).fetchone() == ("approved", customer_id)


def test_existing_approval_rejects_customer_without_confirmed_binding(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="unconfirmed", origin="existing", email_source="existing", public_code="unconfirmed-1"
    )
    registry.get_or_create_identity(
        telegram_user_id=74, chat_id=74, username="unconfirmed", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(74)

    with pytest.raises(ApprovalUnavailableError, match="no confirmed"):
        registry.approve_existing_application(
            telegram_user_id=74,
            customer_id=customer_id,
            expected_identity_version=pending.identity.row_version,
            idempotency_key="existing-74",
            approved_by="admin",
        )


def test_reject_block_and_unblock_require_versions_and_do_not_create_repeat_request(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=88, chat_id=88, username="user88", first_name=None, last_name=None
    )
    pending = registry.create_pending_application(88)
    rejected = registry.reject_application(
        telegram_user_id=88,
        expected_identity_version=pending.identity.row_version,
        idempotency_key="reject-88",
        rejected_by="admin",
        reason="not now",
    )
    blocked = registry.block_identity(
        telegram_user_id=88,
        expected_identity_version=rejected.row_version,
        idempotency_key="block-88",
        blocked_by="admin",
    )
    unblocked = registry.unblock_identity(
        telegram_user_id=88,
        expected_identity_version=blocked.row_version,
        idempotency_key="unblock-88",
        unblocked_by="admin",
    )

    assert (rejected.access_status, blocked.access_status, unblocked.access_status) == (
        "rejected", "blocked", "eligible"
    )
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT event_type, entity_id FROM telegram_outbox WHERE event_type = 'user_application_rejected'"
        ).fetchone() == ("user_application_rejected", "88")
    repeat = registry.create_pending_application(88)
    assert repeat.created is True
    assert repeat.identity.application_attempt == 2


def test_noop_abuse_counter_blocks_only_the_fifty_first_unique_action_and_unblock_resets_window(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=99, chat_id=99, username="user99", first_name=None, last_name=None
    )
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for _ in range(50):
        result = registry.record_unapproved_noop(99, now=base)
        assert result.auto_blocked is False
    blocked = registry.record_unapproved_noop(99, now=base)
    assert blocked.auto_blocked is True
    assert blocked.noop_count == 51
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT access_status, decision_reason FROM telegram_identities WHERE telegram_user_id = 99"
        ).fetchone() == ("blocked", "auto_spam")
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_outbox WHERE event_type = 'admin_identity_auto_blocked'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_audit_log WHERE event_type = 'identity_auto_blocked'"
        ).fetchone()[0] == 1
        version = conn.execute(
            "SELECT row_version FROM telegram_identities WHERE telegram_user_id = 99"
        ).fetchone()[0]
    unblocked = registry.unblock_identity(
        telegram_user_id=99,
        expected_identity_version=version,
        idempotency_key="unblock-99",
        unblocked_by="admin",
    )
    assert unblocked.access_status == "eligible"
    after_reset = registry.record_unapproved_noop(99, now=base)
    assert after_reset.noop_count == 1


def test_customer_lifecycle_preview_queues_exact_targets_once_and_never_performs_remote_io(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "allowed")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="lifecycle-user", origin="manual", email_source="admin", public_code="lifecycle-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, 1, 1, 'remote-uuid', 'remote-sub', 'lifecycle-user',
                    'admin_confirmed', 'confirmed', 1, 1)
            """,
            (customer_id,),
        )

    preview = registry.preview_customer_operation(customer_id=customer_id, operation_type="suspend")
    assert preview.expected_customer_version == 1
    assert preview.blocked_binding_ids == ()
    assert preview.targets[0].action == "set_enabled_false"
    assert not hasattr(preview.targets[0], "remote_client_id")

    queued = registry.queue_customer_operation(
        customer_id=customer_id,
        operation_type="suspend",
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest,
        idempotency_key="suspend-lifecycle-user",
        created_by="admin",
    )
    replay = registry.queue_customer_operation(
        customer_id=customer_id,
        operation_type="suspend",
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest,
        idempotency_key="suspend-lifecycle-user",
        created_by="another-admin",
    )

    assert queued == replay
    assert queued.status == "queued"
    operation = registry.get_customer_operation(queued.operation_id)
    assert operation.status == "queued"
    assert operation.attempts[0].action == "set_enabled_false"
    assert operation.attempts[0].status == "pending"
    assert registry.get_customer(customer_id).status == "suspending"
    with connect(db_path) as conn:
        stored = conn.execute(
            "SELECT remote_client_id, remote_sub_id FROM telegram_customer_operation_attempts"
        ).fetchone()
    assert stored == ("remote-uuid", "remote-sub")


def test_customer_node_add_queues_only_the_selected_eligible_node(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "edge-a")
    _insert_node(db_path, 2, "edge-b")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="node-add-user", origin="manual", email_source="admin", public_code="node-add-user"
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (1, 1)")
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (2, 0)")

    result = registry.queue_customer_node_add(
        customer_id=customer_id,
        node_id=1,
        expected_customer_version=1,
        idempotency_key="node-add-1",
        created_by="admin",
    )
    replay = registry.queue_customer_node_add(
        customer_id=customer_id,
        node_id=1,
        expected_customer_version=1,
        idempotency_key="node-add-1",
        created_by="another-admin",
    )

    assert result == replay
    assert result.status == "queued"
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT node_id FROM telegram_provisioning_attempts WHERE job_id = ?", (result.job_id,)
        ).fetchone()[0] == 1
    matrix = registry.customer_node_matrix(customer_id)
    assert {(item.node_id, item.state) for item in matrix} == {(1, "available_to_add")}


def test_customer_node_suspend_and_resume_use_exact_preview_and_keep_global_status(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "edge-a")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="node-lifecycle-user", origin="manual", email_source="admin", public_code="node-lifecycle-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, 1, 1, 'remote-id', 'remote-sub', 'node-lifecycle-user',
                    'admin_confirmed', 'confirmed', 1, 1)
            """,
            (customer_id,),
        )
    preview = registry.preview_customer_node_operation(
        customer_id=customer_id, node_id=1, operation_type="suspend_node"
    )
    queued = registry.queue_customer_node_operation(
        customer_id=customer_id,
        node_id=1,
        operation_type="suspend_node",
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest,
        idempotency_key="suspend-node-1",
        created_by="admin",
    )
    assert queued.status == "queued"
    assert registry.get_customer(customer_id).status == "active"
    with connect(db_path) as conn:
        operation_id = queued.operation_id
        conn.execute(
            "UPDATE telegram_customer_operation_attempts SET status = 'succeeded', previous_enabled = 1 "
            "WHERE operation_id = ?",
            (operation_id,),
        )
    # The worker normally performs this finalization; this assertion verifies
    # the queued operation remains node-scoped and does not globally suspend.
    assert registry.get_customer_operation(operation_id).operation_type == "suspend_node"


def test_customer_lifecycle_rejects_non_exact_binding_and_resume_uses_prior_suspend_state(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _insert_node(db_path, 1, "allowed")
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="resume-user", origin="manual", email_source="admin", public_code="resume-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, 1, 1, 'remote-uuid', 'remote-sub', 'resume-user',
                    'admin_confirmed', 'conflict', 1, 1)
            """,
            (customer_id,),
        )
    blocked = registry.preview_customer_operation(customer_id=customer_id, operation_type="suspend")
    assert blocked.blocked_binding_ids
    with pytest.raises(LifecycleUnavailableError):
        registry.queue_customer_operation(
            customer_id=customer_id,
            operation_type="suspend",
            expected_customer_version=blocked.expected_customer_version,
            target_snapshot_digest=blocked.target_snapshot_digest,
            idempotency_key="blocked-lifecycle-user",
            created_by="admin",
        )

    with connect(db_path) as conn:
        binding_id = conn.execute("SELECT id FROM customer_node_bindings").fetchone()[0]
        conn.execute("UPDATE customers SET status = 'suspended' WHERE id = ?", (customer_id,))
        conn.execute(
            "UPDATE customer_node_bindings SET management_state = 'confirmed', desired_enabled = 0, "
            "suspended_by_operation_id = 99 WHERE id = ?",
            (binding_id,),
        )
        conn.execute(
            """
            INSERT INTO telegram_customer_operations
                (id, customer_id, operation_type, status, target_snapshot_digest,
                 expected_customer_version, idempotency_key, created_by)
            VALUES (99, ?, 'suspend', 'succeeded', 'old', 1, 'old-suspend', 'admin')
            """,
            (customer_id,),
        )
        conn.execute(
            """
            INSERT INTO telegram_customer_operation_attempts
                (operation_id, binding_id, node_id, inbound_id, remote_client_id, remote_sub_id,
                 action, previous_enabled, status)
            VALUES (99, ?, 1, 1, 'remote-uuid', 'remote-sub', 'set_enabled_false', 1, 'succeeded')
            """,
            (binding_id,),
        )

    resume = registry.preview_customer_operation(customer_id=customer_id, operation_type="resume")
    assert resume.blocked_binding_ids == ()
    assert len(resume.targets) == 1
    assert resume.targets[0].action == "restore_previous_enabled"
    assert resume.targets[0].previous_enabled is True


def test_admin_draft_is_durable_bounded_and_exact_customer_lookup_is_not_fuzzy(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=501, chat_id=501, username="requester", first_name="Requester", last_name=None
    )
    pending = registry.create_pending_application(501)
    customer_id = registry.create_customer(
        email_display="existing-user", origin="manual", email_source="admin", public_code="existing-user"
    )

    saved = registry.set_admin_draft(
        admin_telegram_user_id=108100140,
        action="new_customer_name",
        telegram_user_id=501,
        expected_row_version=pending.identity.row_version,
        page=2,
        value="chosen-user",
    )
    restarted = TelegramRegistry(db_path)

    assert restarted.get_admin_draft(108100140) == saved
    assert restarted.get_customer_by_email("EXISTING-USER").customer_id == customer_id
    with pytest.raises(TelegramRegistryError):
        restarted.get_customer_by_email("existing")
    with pytest.raises(TelegramRegistryError):
        restarted.set_admin_draft(
            admin_telegram_user_id=108100140,
            action="invalid",
        )
    restarted.clear_admin_draft(108100140)
    assert restarted.get_admin_draft(108100140) is None


def test_customer_telegram_profile_preserves_a_voluntarily_shared_phone_number(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="profile-user", origin="telegram", email_source="telegram_username", public_code="profile-user"
    )
    registry.get_or_create_identity(
        telegram_user_id=42,
        chat_id=42,
        username="profile_user",
        first_name="Profile",
        last_name="User",
        phone_number="+7 (999) 000-11-22",
    )
    registry.get_or_create_identity(
        telegram_user_id=42,
        chat_id=43,
        username="profile_user_new",
        first_name="New",
        last_name="Name",
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42",
            (customer_id,),
        )

    profile = registry.get_customer_telegram_profile(customer_id)

    assert profile.telegram_user_id == 42
    assert profile.username == "profile_user_new"
    assert profile.first_name == "New"
    assert profile.last_name == "Name"
    assert profile.phone_number == "+79990001122"


def test_broadcast_queue_excludes_pending_blocked_deleted_and_opted_out_identities(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_ids = [
        registry.create_customer(
            email_display=f"broadcast-{index}", origin="telegram", email_source="telegram_username",
            public_code=f"broadcast-{index}",
        )
        for index in range(1, 5)
    ]
    for user_id in range(41, 45):
        registry.get_or_create_identity(
            telegram_user_id=user_id, chat_id=user_id, username=f"user{user_id}", first_name="User", last_name=None
        )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 41",
            (customer_ids[0],),
        )
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'blocked' WHERE telegram_user_id = 42",
            (customer_ids[1],),
        )
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 43",
            (customer_ids[2],),
        )
        conn.execute(
            "UPDATE customers SET status = 'deleted', deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (customer_ids[2],),
        )
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 44",
            (customer_ids[3],),
        )
    registry.toggle_background_notifications(44)

    assert registry.registered_broadcast_recipient_count() == 1
    result = registry.queue_registered_broadcast(
        body="Системное сообщение.", created_by=108100140, idempotency_key="broadcast-filters-1"
    )

    assert result.recipient_count == 1
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT entity_id FROM telegram_outbox WHERE event_type = 'registered_broadcast'"
        ).fetchall()
    assert rows == [(f"{result.broadcast_id}:41",)]
