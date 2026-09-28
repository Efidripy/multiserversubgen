from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.subscription_tokens import ensure_tokens, regenerate_token
from services.telegram_registry import TelegramRegistry


def _approved_customer(registry: TelegramRegistry, db_path: str, *, telegram_user_id: int = 42) -> int:
    registry.get_or_create_identity(
        telegram_user_id=telegram_user_id,
        chat_id=telegram_user_id,
        username="guest_owner",
        first_name="Guest",
        last_name="Owner",
    )
    customer_id = registry.create_customer(
        email_display="guest_owner",
        origin="telegram",
        email_source="telegram_username",
        public_code="guest-owner",
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, telegram_user_id),
        )
    return customer_id


def test_guest_link_is_expiring_revocable_and_keeps_the_primary_token_unchanged(tmp_path):
    db_path = str(tmp_path / "guest-link.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = _approved_customer(registry, db_path)
    primary_token = ensure_tokens(db_path, "email", ["guest_owner"])["guest_owner"]

    first = registry.create_guest_subscription_link(telegram_user_id=42, duration_hours=1)

    assert first.token is not None
    assert registry.resolve_guest_subscription_link(first.token).email_display == "guest_owner"
    assert ensure_tokens(db_path, "email", ["guest_owner"])["guest_owner"] == primary_token

    second = registry.create_guest_subscription_link(telegram_user_id=42, duration_hours=24)

    assert first.token != second.token
    assert registry.resolve_guest_subscription_link(first.token) is None
    assert registry.resolve_guest_subscription_link(second.token).customer_id == customer_id
    devices = registry.list_logical_devices(42)
    assert [(item.kind, item.status) for item in devices] == [
        ("primary", "active"),
        ("guest", "active"),
        ("guest", "revoked"),
    ]

    registry.revoke_guest_subscription_link(telegram_user_id=42, guest_link_id=second.guest_link_id)

    assert registry.resolve_guest_subscription_link(second.token) is None


def test_logical_device_label_quality_signal_thresholds_and_token_history_are_safe(tmp_path):
    db_path = str(tmp_path / "telegram-ux.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = _approved_customer(registry, db_path)

    primary_token = ensure_tokens(db_path, "email", ["guest_owner"])["guest_owner"]
    rotated_token = regenerate_token(
        db_path,
        "email",
        "guest_owner",
        actor_type="telegram_user",
        actor_id="42",
        reason="self_service",
    )
    devices = registry.list_logical_devices(42)
    primary = next(item for item in devices if item.kind == "primary")
    renamed = registry.set_logical_device_label(
        telegram_user_id=42, device_id=primary.device_id, label="Мой телефон"
    )
    preferences = registry.toggle_traffic_reminder_threshold(42, 50)
    report = registry.submit_quality_report(telegram_user_id=42, kind="slow", platform="ios")
    history = registry.list_subscription_token_events(customer_id)

    assert rotated_token is not None and rotated_token != primary_token
    assert renamed.label == "Мой телефон"
    assert preferences.traffic_reminder_thresholds == (50, 80, 95, 100)
    assert report.kind == "slow"
    assert any(event.event_type == "rotated" and event.reason == "self_service" for event in history)
    assert all(primary_token not in repr(event) and rotated_token not in repr(event) for event in history)
    with connect(db_path) as conn:
        assert conn.execute(
            "SELECT event_type FROM telegram_outbox WHERE entity_id = ?", (str(report.report_id),)
        ).fetchone() == ("admin_quality_report_created",)
