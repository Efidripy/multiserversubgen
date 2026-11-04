from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_locale import _BUTTONS, _MESSAGES
from services.telegram_registration import TelegramRegistrationService
from services.telegram_registry import TelegramRegistry


def _approved_service(tmp_path):
    db_path = str(tmp_path / "client.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="client_user", first_name="Client", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="client_user", origin="telegram", email_source="telegram_username", public_code="client-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    service = TelegramRegistrationService(
        registry,
        introduction_max_chars=700,
        public_base_url="https://bot.example.test",
        list_nodes=lambda: [{"id": 1, "name": "edge-a"}],
        get_links_filtered=lambda _nodes, _email, _protocol: ["vless://opaque-link"],
    )
    return service, registry, db_path


def test_ru_catalog_is_simple_and_locales_match():
    forbidden = ("нода", "импорт", "подписка", "самодиагностика", "диагностика", "клиент", "провижининг", "ротация", "токен", "внимание")
    for catalogue in (_MESSAGES, _BUTTONS):
        assert {item["ru"] for item in catalogue.values()}
        for item in catalogue.values():
            assert not any(word in item["ru"].lower() for word in forbidden)
            assert set(item) == {"ru", "en"}
    for key, item in _MESSAGES.items():
        assert set(re.findall(r"{(\w+)}", item["ru"])) == set(re.findall(r"{(\w+)}", item["en"]))


def test_approved_menu_layout_and_suspended_layout():
    rows = TelegramRegistrationService._approved_menu("ru", show_readiness=True)["inline_keyboard"]
    assert [row[0]["callback_data"] for row in rows[:5]] == [
        "subscription:get", "setup:diagnostics", "setup:menu", "devices:menu", "help"
    ]
    assert [button["callback_data"] for button in rows[5]] == ["preferences:menu", "language:menu"]
    suspended = TelegramRegistrationService._approved_menu("ru", suspended=True)["inline_keyboard"]
    assert [row[0]["callback_data"] for row in suspended] == ["subscription:get", "support:appeal"]


def test_copy_button_is_first_and_matches_primary_device_and_guest_url(tmp_path):
    service, registry, _db_path = _approved_service(tmp_path)
    primary = service._subscription_message(user_id=42, chat_id=42)
    device = registry.create_subscription_device(telegram_user_id=42, label="Phone")
    device_message = service._subscription_message(user_id=42, chat_id=42, subscription_device_id=device.device_id)
    guest = registry.create_guest_subscription_link(telegram_user_id=42, duration_hours=1)
    guest_message = service._guest_link_ready_message(chat_id=42, guest=guest, locale="ru")
    for message in (primary, device_message, guest_message):
        url = message.text.splitlines()[-1]
        first = message.reply_markup["inline_keyboard"][0][0]
        assert first["copy_text"]["text"] == url
        assert "callback_data" not in first


def test_subscription_tokens_are_absent_from_durable_update_responses(tmp_path):
    service, _registry, db_path = _approved_service(tmp_path)
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Client"},
            "text": "/subscription",
        },
    }
    service.handle_update(update)
    response = service.handle_update({
        "update_id": 2,
        "callback_query": {
            "id": "copy-test",
            "from": {"id": 42, "first_name": "Client"},
            "message": {"chat": {"id": 42, "type": "private"}},
            "data": "subscription:link:primary",
        },
    })
    assert response
    with connect(db_path) as conn:
        values = conn.execute("SELECT * FROM telegram_update_responses").fetchall()
    assert all("/api/v1/sub/" not in str(value) and "copy_text" not in str(value) for row in values for value in row)


def test_first_time_hint_only_for_active_access(tmp_path):
    service, registry, _db_path = _approved_service(tmp_path)
    active = service._approved_status(42, 42, "ru")
    assert "Подключаетесь в первый раз?" in active.text
    identity = registry.get_customer_access(42)
    with connect(registry.database_path) as conn:
        conn.execute("UPDATE customers SET status = 'suspended' WHERE id = ?", (identity.customer_id,))
    suspended = service._approved_status(42, 42, "ru")
    assert "Подключаетесь в первый раз?" not in suspended.text
