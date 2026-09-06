from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_outbox import TelegramOutboxWorker
from services.telegram_registry import TelegramRegistry


class FakeOutboxPort:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.messages: list[tuple[int, str, dict | None]] = []

    def send(self, *, chat_id: int, text: str, reply_markup=None):
        if self.error:
            raise self.error
        self.messages.append((chat_id, text, reply_markup))


def _worker(db_path, port, *, now=None, max_attempts=8):
    return TelegramOutboxWorker(
        db_path=db_path,
        primary_admin_id=108100140,
        port=port,
        worker_id="outbox-test-worker",
        now=now or (lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)),
        max_attempts=max_attempts,
    )


def test_admin_request_event_is_delivered_once_after_a_durable_lease(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="requester", first_name="Requester", last_name=None
    )
    registry.create_pending_application(42)
    port = FakeOutboxPort()

    result = _worker(db_path, port).run_once()

    assert result.outcome == "sent"
    assert port.messages[0][0] == 108100140
    assert "новая заявка" in port.messages[0][1].lower()
    with connect(db_path) as conn:
        assert conn.execute("SELECT status, attempt_count FROM telegram_outbox").fetchone() == ("sent", 1)
    assert _worker(db_path, port).run_once().processed is False


def test_admin_receives_the_voluntary_introduction_for_the_exact_application_attempt(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="requester", first_name="Requester", last_name=None
    )
    registry.create_pending_application(42)
    registry.submit_introduction(42, "Хочу коротко представиться.", maximum_chars=700)
    port = FakeOutboxPort()

    assert _worker(db_path, port).run_once().outcome == "sent"  # application notification
    result = _worker(db_path, port).run_once()

    assert result.outcome == "sent"
    assert port.messages[1][0] == 108100140
    assert "@requester" in port.messages[1][1]
    assert "Хочу коротко представиться." in port.messages[1][1]
    assert port.messages[1][2] == {
        "inline_keyboard": [[{"text": "Заявки", "callback_data": "admin:requests:0"}]]
    }


def test_uncertain_delivery_retries_with_backoff_and_dead_letters_after_bound(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key) VALUES ('admin_identity_auto_blocked', '42', 'one')"
        )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = _worker(db_path, FakeOutboxPort(RuntimeError("timeout")), now=lambda: now, max_attempts=1).run_once()

    assert first.outcome == "retry"
    with connect(db_path) as conn:
        assert conn.execute("SELECT status, last_error_code FROM telegram_outbox").fetchone() == ("dead_letter", "delivery_uncertain")


def test_user_approval_event_resolves_chat_id_only_from_numeric_identity(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="user", first_name="User", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key) VALUES ('user_provisioning_queued', '42', 'two')"
        )
    port = FakeOutboxPort()

    result = _worker(db_path, port).run_once()

    assert result.outcome == "sent"
    assert port.messages[0][0] == 777
    assert "готовится" in port.messages[0][1].lower()


def test_user_can_suppress_background_outbox_messages_without_losing_the_event_audit(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="user", first_name="User", last_name=None
    )
    registry.toggle_background_notifications(42)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key) VALUES ('user_provisioning_queued', '42', 'three')"
        )
    port = FakeOutboxPort()

    result = _worker(db_path, port).run_once()

    assert result.outcome == "cancelled"
    assert port.messages == []
    with connect(db_path) as conn:
        assert conn.execute("SELECT status, last_error_code FROM telegram_outbox").fetchone() == (
            "cancelled", "notifications_disabled"
        )


def test_admin_direct_message_is_delivered_to_the_approved_live_customer(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="direct-target", origin="telegram", email_source="telegram_username", public_code="direct-target"
    )
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="target", first_name="Target", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42",
            (customer_id,),
        )
    registry.queue_admin_direct_message(
        customer_id=customer_id,
        body="Сообщение от администратора.",
        created_by=108100140,
        idempotency_key="direct-delivery-1",
    )
    port = FakeOutboxPort()

    result = _worker(db_path, port).run_once()

    assert result.outcome == "sent"
    assert port.messages == [(777, "Сообщение от администратора.", None)]


def test_registered_broadcast_is_cancelled_when_recipient_opts_out_after_queueing(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="broadcast-target", origin="telegram", email_source="telegram_username", public_code="broadcast-target"
    )
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="target", first_name="Target", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42",
            (customer_id,),
        )
    registry.queue_registered_broadcast(
        body="Новость для зарегистрированных пользователей.",
        created_by=108100140,
        idempotency_key="broadcast-delivery-1",
    )
    registry.toggle_background_notifications(42)
    port = FakeOutboxPort()

    result = _worker(db_path, port).run_once()

    assert result.outcome == "cancelled"
    assert port.messages == []
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT status, last_error_code FROM telegram_outbox WHERE event_type = 'registered_broadcast'"
        ).fetchone() == ("cancelled", "notifications_disabled")


def test_user_result_notifications_cover_provisioning_rejection_and_lifecycle(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="target", first_name="Target", last_name=None
    )
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json) VALUES (?, '42', ?, ?)",
            [
                ("user_provisioning_completed", "result-provisioning", "{}"),
                ("user_application_rejected", "result-rejected", "{}"),
                ("user_lifecycle_completed", "result-lifecycle", '{"operation":"resume"}'),
            ],
        )
    port = FakeOutboxPort()
    worker = _worker(db_path, port)

    outcomes = [worker.run_once().outcome for _ in range(3)]

    assert outcomes == ["sent", "sent", "sent"]
    assert port.messages == [
        (777, "Доступ готов. Откройте меню и получите персональную ссылку.", None),
        (777, "Заявка отклонена. Если хотите подать новую, отправьте /start.", None),
        (777, "Доступ восстановлен. Откройте меню, чтобы продолжить.", None),
    ]
