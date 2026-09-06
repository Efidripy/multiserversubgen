from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.telegram_webhook import build_telegram_webhook_router
from services.db_bootstrap import connect, init_db
from services.subscription_tokens import resolve_token
from services.telegram_registration import TelegramOutboundMessage, TelegramRegistrationService
from services.telegram_registry import TelegramRegistry


def _message(update_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "username": "new_user", "first_name": "New"},
            "text": text,
        },
    }


def _admin_message(update_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": 108100140, "type": "private"},
            "from": {"id": 108100140, "username": "owner", "first_name": "Owner"},
            "text": text,
        },
    }


def _admin_callback(update_id: int, data: str) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"admin-{update_id}",
            "from": {"id": 108100140, "username": "owner", "first_name": "Owner"},
            "message": {"chat": {"id": 108100140, "type": "private"}},
            "data": data,
        },
    }


def test_first_start_creates_one_pending_request_with_neutral_copy_and_dedupes(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    service = TelegramRegistrationService(TelegramRegistry(db_path), introduction_max_chars=700)

    first = service.handle_update(_message(1, "/start"))
    duplicate = service.handle_update(_message(1, "/start"))
    repeated_start = service.handle_update(_message(2, "/start"))

    assert len(first) == 1
    assert first[0].reply_markup == {
        "inline_keyboard": [[{"text": "◎ Представиться", "callback_data": "registration:intro"}]]
    }
    lowered = first[0].text.lower()
    assert not any(term in lowered for term in ("vpn", "proxy", "подписк", "сервер", "инбаунд"))
    assert duplicate == []
    assert len(repeated_start) == 1
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM telegram_outbox").fetchone()[0] == 1
        assert conn.execute("SELECT access_status, application_attempt FROM telegram_identities").fetchone() == (
            "pending",
            1,
        )


def test_pending_user_can_submit_one_voluntary_introduction(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    service = TelegramRegistrationService(TelegramRegistry(db_path), introduction_max_chars=20)
    service.handle_update(_message(1, "/start"))
    prompt = service.handle_update(
        {
            "update_id": 2,
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 42, "first_name": "New"},
                "message": {"chat": {"id": 42, "type": "private"}},
                "data": "registration:intro",
            },
        }
    )
    accepted = service.handle_update(_message(3, "Привет"))
    repeated = service.handle_update(_message(4, "Ещё раз"))

    assert "необязательно" in prompt[0].text.lower()
    assert "спасибо" in accepted[0].text.lower()
    assert "ожидает" in repeated[0].text.lower()


def test_approved_user_gets_opaque_subscription_link_and_rotation_invalidates_previous_token(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="new_user", first_name="New", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="new_user", origin="telegram", email_source="telegram_username", public_code="new-user"
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
        get_links_filtered=lambda nodes, email, protocol: ["vless://opaque-link"],
    )

    status = service.handle_update(_message(10, "/start"))
    link = service.handle_update(_message(11, "/subscription"))
    old_token = link[0].text.rsplit("/", 1)[-1]
    confirm_prompt = service.handle_update(
        {
            "update_id": 12,
            "callback_query": {
                "id": "rotate-1",
                "from": {"id": 42, "first_name": "New"},
                "message": {"chat": {"id": 42, "type": "private"}},
                "data": "subscription:rotate",
            },
        }
    )
    rotated = service.handle_update(
        {
            "update_id": 13,
            "callback_query": {
                "id": "rotate-2",
                "from": {"id": 42, "first_name": "New"},
                "message": {"chat": {"id": 42, "type": "private"}},
                "data": "subscription:rotate:confirm",
            },
        }
    )
    new_token = rotated[0].text.rsplit("/", 1)[-1]

    assert "active" in status[0].text
    assert "https://bot.example.test/api/v1/sub/" in link[0].text
    assert old_token != new_token
    assert resolve_token(db_path, "email", old_token) is None
    assert resolve_token(db_path, "email", new_token) == "new_user"
    assert "подтвердить" in confirm_prompt[0].text.lower()


def test_approved_status_shows_customer_lifetime_traffic_independent_of_subscription_token(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="traffic_user", first_name="Traffic", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="traffic_user", origin="telegram", email_source="telegram_username", public_code="traffic-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    service = TelegramRegistrationService(
        registry,
        introduction_max_chars=700,
        traffic_projection_loader=lambda: {"stats": {"traffic_user": {"total": 4096}}},
    )

    status = service.handle_update(_message(15, "/status"))

    assert "4.0 КБ" in status[0].text
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 4096


def test_approved_user_can_toggle_only_background_notification_preference(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="prefs_user", first_name="Prefs", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="prefs_user", origin="telegram", email_source="telegram_username", public_code="prefs-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    service = TelegramRegistrationService(registry, introduction_max_chars=700)

    menu = service.handle_update({
        "update_id": 16,
        "callback_query": {
            "id": "prefs-menu", "from": {"id": 42, "first_name": "Prefs"},
            "message": {"chat": {"id": 42, "type": "private"}}, "data": "preferences:menu",
        },
    })
    toggled = service.handle_update({
        "update_id": 17,
        "callback_query": {
            "id": "prefs-toggle", "from": {"id": 42, "first_name": "Prefs"},
            "message": {"chat": {"id": 42, "type": "private"}}, "data": "preferences:toggle-background",
        },
    })

    assert "включены" in menu[0].text
    assert "выключены" in toggled[0].text
    assert registry.get_notification_preferences(42).background_notifications_enabled is False


def test_help_is_a_separate_screen_and_can_return_to_the_approved_menu(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="help_user", first_name="Help", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="help_user", origin="telegram", email_source="telegram_username", public_code="help-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
    service = TelegramRegistrationService(registry, introduction_max_chars=700)

    help_screen = service.handle_update({
        "update_id": 18,
        "callback_query": {
            "id": "help-screen", "from": {"id": 42, "first_name": "Help"},
            "message": {"chat": {"id": 42, "type": "private"}}, "data": "help",
        },
    })
    home = service.handle_update({
        "update_id": 19,
        "callback_query": {
            "id": "help-home", "from": {"id": 42, "first_name": "Help"},
            "message": {"chat": {"id": 42, "type": "private"}}, "data": "menu:home",
        },
    })

    assert help_screen[0].text.startswith("Помощь")
    assert help_screen[0].reply_markup == {
        "inline_keyboard": [[{"text": "← Меню", "callback_data": "menu:home"}]]
    }
    assert "Статус доступа" in home[0].text


def test_primary_admin_has_user_and_blocked_sections_with_safe_customer_card(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="admin-card-user", origin="telegram", email_source="telegram_username", public_code="admin-card-user"
    )
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="card_user", first_name="Card", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute("UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42", (customer_id,))
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (1, 'edge-a', 1, 0)")
        conn.execute("INSERT INTO telegram_node_policies (node_id, provisioning_enabled) VALUES (1, 1)")
    service = TelegramRegistrationService(registry, introduction_max_chars=700, primary_admin_id=108100140)

    home = service.handle_update(_admin_message(40, "/admin"))
    customers = service.handle_update(_admin_callback(41, "admin:customers:0"))
    card = service.handle_update(_admin_callback(42, f"admin:customer:{customer_id}:0"))

    labels = [button["text"] for row in home[0].reply_markup["inline_keyboard"] for button in row]
    assert {"Заявки", "Пользователи", "TG-ноды", "Заблокированные"} <= set(labels)
    assert "admin-card-user" in customers[0].text
    assert "Трафик за всё время" in card[0].text
    assert any(
        button["callback_data"] == f"admin:cn:{customer_id}:1:add:0"
        for row in card[0].reply_markup["inline_keyboard"] for button in row
    )


def test_primary_admin_queues_customer_suspend_and_can_unblock_an_applicant(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="lifecycle-card-user", origin="telegram", email_source="telegram_username", public_code="lifecycle-card-user"
    )
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="lifecycle_user", first_name="Lifecycle", last_name=None
    )
    registry.get_or_create_identity(
        telegram_user_id=77, chat_id=77, username="blocked_user", first_name="Blocked", last_name=None
    )
    pending = registry.create_pending_application(77)
    blocked = registry.block_identity(
        telegram_user_id=77,
        expected_identity_version=pending.identity.row_version,
        idempotency_key="block-77",
        blocked_by="admin",
    )
    with connect(db_path) as conn:
        conn.execute("UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42", (customer_id,))
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (1, 'edge-a', 1, 0)")
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled)
            VALUES (?, 1, 1, 'remote-id', 'remote-sub', 'lifecycle-card-user',
                    'admin_confirmed', 'confirmed', 1, 1)
            """,
            (customer_id,),
        )
    service = TelegramRegistrationService(registry, introduction_max_chars=700, primary_admin_id=108100140)

    suspended = service.handle_update(_admin_callback(50, f"admin:customer-op:{customer_id}:1:suspend:0"))
    blocked_list = service.handle_update(_admin_callback(51, "admin:blocked:0"))
    unblocked = service.handle_update(_admin_callback(52, f"admin:unblock:77:{blocked.row_version}:0"))

    assert "Приостановка поставлена в очередь" in suspended[0].text
    assert registry.get_customer(customer_id).status == "suspending"
    assert "@blocked_user" in blocked_list[0].text
    assert "разблокирована" in unblocked[0].text.lower()
    assert registry.create_pending_application(77).created is True


def test_suspended_user_can_send_one_bounded_appeal_without_automatic_resume(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="appeal_user", first_name="Appeal", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="appeal_user", origin="telegram", email_source="telegram_username", public_code="appeal-user"
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
        conn.execute("UPDATE customers SET status = 'suspended' WHERE id = ?", (customer_id,))
    service = TelegramRegistrationService(TelegramRegistry(db_path), introduction_max_chars=700)
    prompt = service.handle_update(
        {
            "update_id": 20,
            "callback_query": {
                "id": "appeal-1",
                "from": {"id": 42, "first_name": "Appeal"},
                "message": {"chat": {"id": 42, "type": "private"}},
                "data": "support:appeal",
            },
        }
    )
    sent = service.handle_update(_message(21, "Я всё понял и больше не буду нарушать."))

    assert "администратору" in prompt[0].text.lower()
    assert "принято" in sent[0].text.lower()
    with connect(db_path) as conn:
        assert conn.execute("SELECT status FROM customers WHERE id = ?", (customer_id,)).fetchone()[0] == "suspended"
        assert conn.execute("SELECT COUNT(*) FROM telegram_appeals WHERE customer_id = ?", (customer_id,)).fetchone()[0] == 1


def test_primary_admin_can_toggle_only_a_compatible_node_from_the_bot(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled, read_only) VALUES (1, 'edge-a', 1, 0)")
    service = TelegramRegistrationService(
        TelegramRegistry(db_path),
        introduction_max_chars=700,
        primary_admin_id=108100140,
        list_nodes=lambda: [{"id": 1, "name": "edge-a", "enabled": 1, "read_only": 0}],
        get_cached_inbound_options=lambda _nodes: [
            {"node_id": 1, "id": 1, "enable": True, "protocol": "vless", "tlsFlowCapable": True}
        ],
    )

    home = service.handle_update(_admin_message(30, "/admin"))
    nodes = service.handle_update(_admin_callback(31, "admin:nodes:0"))
    toggled = service.handle_update(_admin_callback(32, "admin:node:1:0"))

    assert "управление" in home[0].text.lower()
    assert "tg-ноды" in nodes[0].text.lower()
    assert "включена" in toggled[0].text.lower()
    with connect(db_path) as conn:
        assert conn.execute("SELECT provisioning_enabled FROM telegram_node_policies WHERE node_id = 1").fetchone()[0] == 1


class _Sender:
    def __init__(self):
        self.messages: list[TelegramOutboundMessage] = []

    def send(self, message: TelegramOutboundMessage) -> None:
        self.messages.append(message)


def test_webhook_requires_exact_suffix_and_secret_then_dispatches_private_update(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    sender = _Sender()
    settings = SimpleNamespace(
        enabled=True,
        bot_token="not-used-by-test-sender",
        webhook_path_suffix="private-path",
        webhook_secret="private-header-secret",
        introduction_max_chars=700,
    )
    app = FastAPI()
    app.include_router(build_telegram_webhook_router(telegram_settings=settings, db_path=db_path, sender=sender))
    client = TestClient(app)

    assert client.post("/telegram/webhook/wrong", json=_message(1, "/start")).status_code == 404
    assert client.post("/telegram/webhook/private-path", json=_message(1, "/start")).status_code == 403
    accepted = client.post(
        "/telegram/webhook/private-path",
        headers={"X-Telegram-Bot-Api-Secret-Token": "private-header-secret"},
        json=_message(1, "/start"),
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"ok": True}
    assert len(sender.messages) == 1
