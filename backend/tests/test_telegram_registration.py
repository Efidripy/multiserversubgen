from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.telegram_webhook import build_telegram_webhook_router
from services.db_bootstrap import connect, init_db
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
