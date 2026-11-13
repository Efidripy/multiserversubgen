from __future__ import annotations

import io
import json
import os
import sys
from urllib.error import HTTPError

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.telegram_delivery import (
    TelegramApiSender,
    TelegramDeliveryError,
    TelegramMessageEditUnavailableError,
)
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


def test_sender_preserves_an_explicit_html_parse_mode():
    transport = _Transport()
    TelegramApiSender("test-token", transport=transport).send(
        TelegramOutboundMessage(chat_id=42, text="<b>Status:</b> active", parse_mode="HTML")
    )

    request, _timeout = transport.requests[0]
    assert json.loads(request.data) == {
        "chat_id": 42,
        "text": "<b>Status:</b> active",
        "parse_mode": "HTML",
    }


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


def test_sender_deletes_qr_message_without_sending_its_text():
    transport = _Transport()
    result = TelegramApiSender("test-token", transport=transport).send(
        TelegramOutboundMessage(chat_id=42, text="ignored", delete_message_id=77)
    )

    request, timeout = transport.requests[0]
    assert request.full_url.endswith("/deleteMessage")
    assert json.loads(request.data) == {"chat_id": 42, "message_id": 77}
    assert b"ignored" not in request.data
    assert timeout == 10
    assert result is None


class _ErrorTransport:
    def __init__(self, description: str, status: int = 400):
        self.description = description
        self.status = status

    def open(self, request, *, timeout):
        body = json.dumps({"ok": False, "error_code": self.status, "description": self.description}).encode("utf-8")
        raise HTTPError(request.full_url, self.status, "Bad Request", {}, io.BytesIO(body))


def test_sender_edit_raises_edit_unavailable_on_no_text_in_message_error():
    transport = _ErrorTransport("Bad Request: there is no text in the message to edit")
    sender = TelegramApiSender("test-token", transport=transport)
    msg = TelegramOutboundMessage(chat_id=42, text="New text", edit_message_id=77)
    with pytest.raises(TelegramMessageEditUnavailableError):
        sender.send(msg)


def test_sender_delete_ignores_not_found_and_cant_be_deleted_but_raises_other_errors():
    sender1 = TelegramApiSender("test-token", transport=_ErrorTransport("Bad Request: message to delete not found"))
    assert sender1.send(TelegramOutboundMessage(chat_id=42, text="", delete_message_id=77)) is None

    sender2 = TelegramApiSender("test-token", transport=_ErrorTransport("Bad Request: message can't be deleted"))
    assert sender2.send(TelegramOutboundMessage(chat_id=42, text="", delete_message_id=77)) is None

    sender3 = TelegramApiSender("test-token", transport=_ErrorTransport("Bad Request: chat not found"))
    with pytest.raises(TelegramDeliveryError):
        sender3.send(TelegramOutboundMessage(chat_id=42, text="", delete_message_id=77))


class _SequenceTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_best_effort_delete_swallows_network_and_bad_request_errors():
    network = _SequenceTransport([OSError("offline")])
    assert TelegramApiSender("token", transport=network).send(
        TelegramOutboundMessage(42, "", delete_message_id=77, best_effort=True)
    ) is None
    bad_request = TelegramApiSender("token", transport=_ErrorTransport("Bad Request: chat not found"))
    assert bad_request.send(
        TelegramOutboundMessage(42, "", delete_message_id=77, best_effort=True)
    ) is None


def test_best_effort_cant_delete_clears_markup_and_swallows_markup_failure():
    # The first response must be a Telegram HTTP error; the second is the
    # swallowed editMessageReplyMarkup failure.
    class _FirstCantDeleteThenFail:
        def __init__(self):
            self.requests = []

        def open(self, request, *, timeout):
            self.requests.append(request)
            if len(self.requests) == 1:
                raise HTTPError(request.full_url, 400, "Bad Request", {}, io.BytesIO(
                    b'{"ok":false,"description":"Bad Request: message can\'t be deleted"}'
                ))
            raise OSError("markup failure")

    transport = _FirstCantDeleteThenFail()
    assert TelegramApiSender("token", transport=transport).send(
        TelegramOutboundMessage(42, "", delete_message_id=77, best_effort=True)
    ) is None
    assert len(transport.requests) == 2
    assert transport.requests[1].full_url.endswith("/editMessageReplyMarkup")
    assert json.loads(transport.requests[1].data)["reply_markup"] == {"inline_keyboard": []}


def test_best_effort_not_found_does_not_clear_markup():
    transport = _ErrorTransport("Bad Request: message to delete not found")
    sender = TelegramApiSender("token", transport=transport)
    assert sender.send(TelegramOutboundMessage(42, "", delete_message_id=77, best_effort=True)) is None


def test_sender_answer_callback_query_sends_correct_payload():
    transport = _Transport()
    TelegramApiSender("test-token", transport=transport).answer_callback_query("cb_query_123")

    assert len(transport.requests) == 1
    request, timeout = transport.requests[0]
    assert request.full_url.endswith("/answerCallbackQuery")
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"callback_query_id": "cb_query_123"}
    assert timeout == 10


def test_sender_uses_file_ids_for_photo_and_album():
    class AlbumTransport(_Transport):
        def open(self, request, *, timeout):
            self.requests.append((request, timeout))
            response = _Response()
            response._body = json.dumps({"ok": True, "result": [{"message_id": 123}, {"message_id": 124}]}).encode()
            return response

    transport = AlbumTransport()
    sender = TelegramApiSender("test-token", transport=transport)
    assert sender.send(TelegramOutboundMessage(42, "caption", photo_file_ids=("one", "two"), parse_mode="HTML")) == 123
    request = transport.requests[-1][0]
    assert request.full_url.endswith("/sendMediaGroup")
    assert json.loads(request.data)["media"] == [
        {"type": "photo", "media": "one", "caption": "caption", "parse_mode": "HTML"},
        {"type": "photo", "media": "two"},
    ]
    sender.send(TelegramOutboundMessage(42, "caption", photo_file_ids=("one",)))
    request = transport.requests[-1][0]
    assert request.full_url.endswith("/sendPhoto")
    assert json.loads(request.data)["photo"] == "one"


@pytest.mark.parametrize("status", [403, 429])
def test_interactive_failure_does_not_interrupt_update(status, caplog):
    from services.telegram_polling import TelegramPollingWorker

    class FailingTransport:
        def open(self, request, *, timeout):
            body = json.dumps({"parameters": {"retry_after": 17}}).encode()
            raise HTTPError(request.full_url, status, "error", {}, io.BytesIO(body))

    class Api:
        def delete_webhook(self):
            pass

        def get_updates(self, *, offset, timeout_sec):
            return [{"update_id": 1, "message": {}}]

    actions = []
    sender = TelegramApiSender("secret", transport=FailingTransport())
    worker = TelegramPollingWorker(
        api=Api(), sender=sender, timeout_sec=1,
        handle_update=lambda update: actions.append(update["update_id"]) or [
            TelegramOutboundMessage(987654321, "reply", edit_message_id=1)
        ],
    )
    with caplog.at_level("WARNING", logger="sub_manager"):
        worker.run_once()
    worker.close()
    assert actions == [1]
    assert len(caplog.records) == 1
    assert "987654321" not in caplog.text
    assert str(status) in caplog.text
    if status == 429:
        assert "retry_after=17" in caplog.text


def test_sender_propagates_transient_network_errors_so_the_update_is_retried():
    from urllib.error import URLError

    class _Down:
        def open(self, request, *, timeout):
            raise URLError("down")

    sender = TelegramApiSender("test-token", transport=_Down())
    with pytest.raises(TelegramDeliveryError):
        sender.send(TelegramOutboundMessage(chat_id=42, text="Hello"))
