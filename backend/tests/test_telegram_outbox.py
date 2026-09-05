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
