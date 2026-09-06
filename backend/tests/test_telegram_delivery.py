from __future__ import annotations

import os
import sys
import json


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.telegram_delivery import TelegramApiSender
from services.telegram_registration import TelegramOutboundMessage


class _Response:
    status = 200

    def __init__(self, *, message_id=101):
        self._body = json.dumps({"ok": True, "result": {"message_id": message_id}}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


class _Transport:
    def __init__(self):
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        return _Response()


def test_sender_uses_json_send_message_for_text():
    transport = _Transport()
    message_id = TelegramApiSender("test-token", transport=transport).send(
        TelegramOutboundMessage(chat_id=42, text="Hello", reply_markup={"inline_keyboard": []})
    )

    request, timeout = transport.requests[0]
    assert request.full_url.endswith("/sendMessage")
    assert request.get_header("Content-type") == "application/json"
    assert request.data == b'{"chat_id": 42, "text": "Hello", "reply_markup": {"inline_keyboard": []}}'
    assert timeout == 10
    assert message_id == 101


def test_sender_uses_multipart_send_photo_for_qr():
    transport = _Transport()
    png = b"\x89PNG\r\n\x1a\nexample"
    TelegramApiSender("test-token", transport=transport).send(
        TelegramOutboundMessage(
            chat_id=42,
            text="QR ready",
            reply_markup={"inline_keyboard": []},
            photo_png=png,
            photo_filename="access-qr.png",
        )
    )

    request, timeout = transport.requests[0]
    assert request.full_url.endswith("/sendPhoto")
    assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="photo"; filename="access-qr.png"' in request.data
    assert b"Content-Type: image/png" in request.data
    assert png in request.data
    assert timeout == 10


def test_sender_edits_the_original_subscription_message_instead_of_sending_another():
    transport = _Transport()
    message_id = TelegramApiSender("test-token", transport=transport).send(
        TelegramOutboundMessage(
            chat_id=42,
            text="Ссылка уже получена. Скопируйте её в приложение-клиент:\nhttps://example.test/sub/opaque",
            reply_markup={"inline_keyboard": []},
            edit_message_id=77,
        )
    )

    request, timeout = transport.requests[0]
    assert request.full_url.endswith("/editMessageText")
    assert json.loads(request.data) == {
        "chat_id": 42,
        "message_id": 77,
        "text": "Ссылка уже получена. Скопируйте её в приложение-клиент:\nhttps://example.test/sub/opaque",
        "reply_markup": {"inline_keyboard": []},
    }
    assert timeout == 10
    assert message_id == 101
