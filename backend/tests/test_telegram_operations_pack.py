from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_drift import TelegramDriftScanner
from services.telegram_bot_config import TelegramBotConfigurationError, TelegramBotTokenProvider
from services.telegram_registry import TelegramRegistry
from services.telegram_schedules import TelegramScheduleWorker
from routers.telegram_admin import build_telegram_admin_router
from services.telegram_registration import TelegramRegistrationService


def _contains_cyrillic(value: object) -> bool:
    return any("\u0400" <= character <= "\u052f" for character in str(value))


def _customer_with_binding(tmp_path, *, email: str = "ops-user", node_id: int = 1):
    db_path = str(tmp_path / "ops.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes(id, name, enabled, read_only) VALUES (?, ?, 1, 0)", (node_id, f"edge-{node_id}"))
        conn.execute("INSERT INTO telegram_node_policies(node_id, provisioning_enabled) VALUES (?, 1)", (node_id,))
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display=email, origin="manual", email_source="admin", public_code=f"code-{email}-{node_id}"
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, ?, 1, ?, ?, ?, 'admin_confirmed', 'confirmed', 1, 1)
            """,
            (customer_id, node_id, f"remote-{node_id}", f"sub-{node_id}", email),
        )
    return db_path, registry, customer_id


def test_schedule_uses_immutable_preview_and_stales_instead_of_broadening(tmp_path):
    _db_path, registry, customer_id = _customer_with_binding(tmp_path)
    preview = registry.preview_customer_operation(customer_id=customer_id, operation_type="suspend")
    due = datetime.now(timezone.utc) + timedelta(minutes=6)
    schedule = registry.create_lifecycle_schedule(
        customer_id=customer_id, operation_type="suspend", execute_not_before=due.isoformat(),
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest, idempotency_key="schedule-1", created_by="admin",
    )
    cancelled = registry.cancel_lifecycle_schedule(
        schedule_id=schedule.schedule_id, expected_row_version=schedule.row_version, cancelled_by="admin"
    )
    assert cancelled.status == "cancelled"

    schedule = registry.create_lifecycle_schedule(
        customer_id=customer_id, operation_type="suspend", execute_not_before=due.isoformat(),
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest, idempotency_key="schedule-2", created_by="admin",
    )
    with connect(registry.database_path) as conn:
        conn.execute("UPDATE customers SET row_version = row_version + 1 WHERE id = ?", (customer_id,))
    worker = TelegramScheduleWorker(
        registry=registry, worker_id="test-schedules", now=lambda: due + timedelta(seconds=1)
    )
    result = worker.run_once()
    assert result.processed is True and result.outcome == "stale"
    assert registry.list_lifecycle_schedules(customer_id=customer_id, status="stale")[0].schedule_id == schedule.schedule_id


def test_bulk_preview_revalidates_every_customer_and_queues_individual_operations(tmp_path):
    db_path, registry, first = _customer_with_binding(tmp_path, email="bulk-one")
    second = registry.create_customer(
        email_display="bulk-two", origin="manual", email_source="admin", public_code="code-bulk-two"
    )
    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
                VALUES (?, 1, 1, 'remote-two', 'sub-two', 'bulk-two', 'admin_confirmed', 'confirmed', 1, 1)""",
            (second,),
        )
    preview = registry.preview_bulk_customer_operations(customer_ids=[first, second], operation_type="suspend")
    status = registry.queue_bulk_customer_operations(
        operation_type="suspend", target_snapshot_digest=preview.target_snapshot_digest,
        items=[{
            "customer_id": item.customer_id, "expected_customer_version": item.expected_customer_version,
            "target_snapshot_digest": item.target_snapshot_digest,
        } for item in preview.items], idempotency_key="bulk-suspend", created_by="admin",
    )
    assert len(status.items) == 2
    assert {item.status for item in status.items} == {"queued"}
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_customer_operations").fetchone()[0] == 2


def test_tags_filters_dashboard_and_read_only_view_do_not_expose_a_token(tmp_path):
    _db_path, registry, customer_id = _customer_with_binding(tmp_path)
    assert [tag.tag for tag in registry.set_customer_tags(customer_id=customer_id, tags=["VIP", "test"], updated_by="admin")] == ["test", "vip"]
    saved = registry.save_filter(admin_username="admin", name="VIP", query="ops", status="active", tags=["vip"])
    assert registry.list_saved_filters(admin_username="admin")[0].filter_id == saved.filter_id
    view = registry.get_customer_read_only_view(customer_id)
    assert view["connection_available"] is True
    assert view["token_revealed"] is False
    dashboard = registry.get_admin_dashboard()
    assert dashboard.active_customers == 1


def test_drift_scanner_does_not_report_intentional_subset_and_persists_only_real_findings(tmp_path):
    db_path, registry, customer_id = _customer_with_binding(tmp_path)

    class StrictManager:
        @staticmethod
        def get_node_clients_strict(_node):
            return [{"id": "orphan", "subId": "orphan-sub", "email": "ops-user", "flow": "xtls-rprx-vision", "enable": True, "inbound_id": 1}]

    scanner = TelegramDriftScanner(
        registry=registry,
        list_nodes=lambda: [{"id": 1, "name": "edge-1", "enabled": 1, "read_only": 0}],
        client_manager=StrictManager(),
    )
    result = scanner.scan()
    assert result.scanned_node_ids == (1,)
    findings = registry.list_drift_findings()
    assert len(findings) == 1
    assert findings[0].kind == "binding_conflict"
    assert findings[0].customer_id == customer_id

    with connect(db_path) as conn:
        conn.execute("UPDATE customer_node_bindings SET management_state = 'missing' WHERE customer_id = ?", (customer_id,))
    # A remote record on a node where the customer is intentionally not bound
    # remains a candidate only after a specific adoption action; it is not a
    # missing-binding failure and cannot cause an automatic node write.
    result = scanner.scan()
    assert result.finding_count == 1


def test_panel_bot_token_is_write_only_encrypted_and_versioned(tmp_path):
    db_path = str(tmp_path / "bot-token.db")
    init_db(db_path)
    provider = TelegramBotTokenProvider(
        db_path=db_path,
        encrypt=lambda plain: f"encrypted::{plain[::-1]}",
        decrypt=lambda encrypted: encrypted.removeprefix("encrypted::")[::-1],
        fallback_token="",
    )
    token = "1234567890:abcdefghijklmnopqrstuvwxyzABCDE"
    saved = provider.set_token(token=token, expected_row_version=1, updated_by="admin")

    assert saved.configured is True
    assert saved.source == "panel"
    assert saved.token_suffix == token[-4:]
    assert token not in saved.__dict__.values()
    assert provider.get_token() == token
    with connect(db_path) as conn:
        encrypted = conn.execute(
            "SELECT encrypted_bot_token FROM telegram_bot_configuration WHERE singleton_id = 1"
        ).fetchone()[0]
    assert encrypted != token
    assert token not in encrypted

    with pytest.raises(TelegramBotConfigurationError, match="changed concurrently"):
        provider.set_token(token=token, expected_row_version=1, updated_by="admin")

    cleared = provider.clear_token(expected_row_version=saved.row_version, updated_by="admin")
    assert cleared.configured is False
    assert cleared.source == "none"


def test_panel_bot_token_http_contract_is_admin_only_and_never_returns_plaintext(tmp_path):
    db_path = str(tmp_path / "bot-token-http.db")
    init_db(db_path)
    provider = TelegramBotTokenProvider(
        db_path=db_path,
        encrypt=lambda plain: f"encrypted::{plain[::-1]}",
        decrypt=lambda encrypted: encrypted.removeprefix("encrypted::")[::-1],
    )
    app = FastAPI()
    app.include_router(build_telegram_admin_router(
        check_auth=lambda request: request.headers.get("X-User"),
        get_user_role=lambda username: "admin" if username == "admin" else "viewer",
        db_path=db_path,
        list_nodes=lambda: [],
        get_cached_inbound_options=lambda _nodes: [],
        token_provider=provider,
    ))
    client = TestClient(app)
    token = "1234567890:abcdefghijklmnopqrstuvwxyzABCDE"

    assert client.get("/api/v1/telegram/bot-configuration", headers={"X-User": "viewer"}).status_code == 403
    initial = client.get("/api/v1/telegram/bot-configuration", headers={"X-User": "admin"})
    assert initial.status_code == 200
    assert token not in initial.text

    saved = client.put(
        "/api/v1/telegram/bot-configuration",
        headers={"X-User": "admin"},
        json={"bot_token": token, "expected_row_version": initial.json()["configuration"]["row_version"]},
    )
    assert saved.status_code == 200
    assert token not in saved.text
    assert saved.json()["configuration"]["token_suffix"] == token[-4:]
    stale = client.put(
        "/api/v1/telegram/bot-configuration",
        headers={"X-User": "admin"},
        json={"bot_token": token, "expected_row_version": 1},
    )
    assert stale.status_code == 409


def test_sqlite_backup_restore_preserves_telegram_operations_without_replaying_them(tmp_path):
    db_path, registry, customer_id = _customer_with_binding(tmp_path, email="recovery-user")
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="recovery", first_name="Recovery", last_name=None, locale="en"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    registry.set_customer_tags(customer_id=customer_id, tags=["recovery"], updated_by="admin")
    preview = registry.preview_customer_operation(customer_id=customer_id, operation_type="suspend")
    schedule = registry.create_lifecycle_schedule(
        customer_id=customer_id,
        operation_type="suspend",
        execute_not_before=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        expected_customer_version=preview.expected_customer_version,
        target_snapshot_digest=preview.target_snapshot_digest,
        idempotency_key="recovery-schedule",
        created_by="admin",
    )
    registry.begin_support_request(telegram_user_id=42, category="link")
    support = registry.submit_pending_support_request(telegram_user_id=42, body="Recovery test request.")
    assert support is not None
    provider = TelegramBotTokenProvider(
        db_path=db_path,
        encrypt=lambda plain: f"encrypted::{plain[::-1]}",
        decrypt=lambda encrypted: encrypted.removeprefix("encrypted::")[::-1],
    )
    recovery_token = "1234567890:abcdefghijklmnopqrstuvwxyzABCDE"
    provider.set_token(token=recovery_token, expected_row_version=1, updated_by="admin")

    restored_path = str(tmp_path / "restored.db")
    with sqlite3.connect(db_path) as source, sqlite3.connect(restored_path) as target:
        source.backup(target)

    restored = TelegramRegistry(restored_path)
    restored_provider = TelegramBotTokenProvider(
        db_path=restored_path,
        encrypt=lambda plain: f"encrypted::{plain[::-1]}",
        decrypt=lambda encrypted: encrypted.removeprefix("encrypted::")[::-1],
    )
    assert restored_provider.get_token() == recovery_token
    assert [tag.tag for tag in restored.list_customer_tags(customer_id)] == ["recovery"]
    assert [item.schedule_id for item in restored.list_lifecycle_schedules(customer_id=customer_id)] == [schedule.schedule_id]
    assert [item.support_request_id for item in restored.list_support_requests(status="open")] == [support.support_request_id]
    with connect(restored_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM telegram_outbox WHERE event_type = 'admin_support_created' AND status = 'queued'"
        ).fetchone()[0] == 1


def test_english_telegram_onboarding_uses_english_without_russian_fallback(tmp_path):
    db_path = str(tmp_path / "english-onboarding.db")
    init_db(db_path)
    service = TelegramRegistrationService(TelegramRegistry(db_path), introduction_max_chars=700)
    reply = service.handle_update({
        "update_id": 1,
        "message": {
            "message_id": 1,
            "text": "/start",
            "from": {"id": 42, "first_name": "Alice", "language_code": "en-US"},
            "chat": {"id": 42, "type": "private"},
        },
    })
    assert len(reply) == 1
    assert "To send a request" in reply[0].text
    assert "Чтобы отправить заявку" not in reply[0].text


def test_manual_english_locale_survives_callback_without_language_code_and_localizes_customer_ui(tmp_path):
    db_path = str(tmp_path / "english-customer-ui.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="alice", first_name="Alice", last_name=None, locale="ru"
    )
    customer_id = registry.create_customer(
        email_display="alice", origin="telegram", email_source="telegram_username", public_code="alice-code"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    service = TelegramRegistrationService(TelegramRegistry(db_path), introduction_max_chars=700)

    language = service.handle_update({
        "update_id": 1,
        "callback_query": {
            "id": "language-en", "from": {"id": 42, "first_name": "Alice", "language_code": "ru"},
            "message": {"message_id": 10, "chat": {"id": 42, "type": "private"}}, "data": "language:set:en",
        },
    })
    preferences = service.handle_update({
        "update_id": 2,
        "callback_query": {
            "id": "preferences-en", "from": {"id": 42, "first_name": "Alice"},
            "message": {"message_id": 11, "chat": {"id": 42, "type": "private"}}, "data": "preferences:menu",
        },
    })
    qr_deleted = service.handle_update({
        "update_id": 3,
        "callback_query": {
            "id": "delete-qr-en", "from": {"id": 42, "first_name": "Alice"},
            "message": {"message_id": 12, "chat": {"id": 42, "type": "private"}}, "data": "qr:delete",
        },
    })

    assert registry.get_locale(42) == "en"
    assert "Interface language: English" in language[0].text
    assert "Background notifications" in preferences[0].text
    assert not _contains_cyrillic(preferences[0].text)
    assert not _contains_cyrillic(preferences[0].reply_markup)
    assert "removed from the chat" in qr_deleted[1].text
    assert not _contains_cyrillic(qr_deleted[1].reply_markup)


def test_manual_locale_is_not_overwritten_by_the_telegram_client_language_on_callbacks(tmp_path):
    db_path = str(tmp_path / "manual-locale-priority.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="alice", first_name="Alice", last_name=None, locale="en"
    )
    customer_id = registry.create_customer(
        email_display="alice", origin="telegram", email_source="telegram_username", public_code="alice-manual-locale"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    service = TelegramRegistrationService(TelegramRegistry(db_path), introduction_max_chars=700)

    changed = service.handle_update({
        "update_id": 1,
        "callback_query": {
            "id": "language-ru", "from": {"id": 42, "first_name": "Alice", "language_code": "en-US"},
            "message": {"message_id": 10, "chat": {"id": 42, "type": "private"}}, "data": "language:set:ru",
        },
    })
    menu = service.handle_update({
        "update_id": 2,
        "callback_query": {
            "id": "menu-ru", "from": {"id": 42, "first_name": "Alice", "language_code": "en-US"},
            "message": {"message_id": 11, "chat": {"id": 42, "type": "private"}}, "data": "menu:home",
        },
    })

    assert registry.get_locale(42) == "ru"
    assert "Язык интерфейса: русский." in changed[0].text
    assert "Статус доступа" in menu[0].text
    assert "Access" not in menu[0].text
