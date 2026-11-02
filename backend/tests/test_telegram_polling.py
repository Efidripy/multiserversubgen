import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.telegram_delivery import TelegramMessageEditUnavailableError
from services.telegram_polling import TelegramPollingWorker
from services.telegram_registration import TelegramOutboundMessage


class _Api:
    def __init__(self, updates):
        self.updates = list(updates)
        self.deleted_webhooks = 0
        self.offsets = []

    def delete_webhook(self):
        self.deleted_webhooks += 1

    def get_updates(self, *, offset, timeout_sec):
        self.offsets.append((offset, timeout_sec))
        updates, self.updates = self.updates, []
        return updates


class _Sender:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_polling_keeps_pending_updates_when_switching_from_webhook():
    api = _Api([{"update_id": 17, "message": {}}])
    sender = _Sender()
    handled = []

    worker = TelegramPollingWorker(
        api=api,
        handle_update=lambda update: (
            handled.append(update["update_id"])
            or [TelegramOutboundMessage(chat_id=101, text="received")]
        ),
        sender=sender,
        timeout_sec=25,
    )

    first = worker.run_once()
    second = worker.run_once()

    assert first.processed is True
    assert first.update_count == 1
    assert second.processed is False
    assert api.deleted_webhooks == 1
    assert api.offsets == [(None, 25), (18, 25)]
    assert handled == [17]
    assert sender.messages == [TelegramOutboundMessage(chat_id=101, text="received")]


def test_polling_marks_each_durable_update_response_after_send():
    api = _Api([{"update_id": 18, "message": {}}])
    sender = _Sender()
    delivered = []
    message = TelegramOutboundMessage(
        chat_id=101,
        text="received",
        update_response_update_id=18,
        update_response_index=0,
    )
    worker = TelegramPollingWorker(
        api=api,
        handle_update=lambda _update: [message],
        sender=sender,
        timeout_sec=25,
        mark_update_response_delivered=lambda item: delivered.append(
            (item.update_response_update_id, item.update_response_index)
        ),
    )

    worker.run_once()

    assert delivered == [(18, 0)]


class _AnswerTrackingSender(_Sender):
    def __init__(self, events=None, raise_in_answer=False):
        super().__init__()
        self.events = events if events is not None else []
        self.answer_calls = []
        self.raise_in_answer = raise_in_answer

    def answer_callback_query(self, callback_query_id):
        self.answer_calls.append(callback_query_id)
        self.events.append(("answer", callback_query_id))
        if self.raise_in_answer:
            raise OSError("Telegram connection error during answerCallbackQuery")


class _EditFallbackPollingSender(_Sender):
    def send(self, message):
        if message.edit_message_id is not None:
            raise TelegramMessageEditUnavailableError("message to edit not found")
        super().send(message)
        return 201


def test_polling_answers_callback_query_once_before_handle_update():
    events = []
    sender = _AnswerTrackingSender(events)
    api = _Api([{"update_id": 21, "callback_query": {"id": "cb_21", "data": "help"}}])
    worker = TelegramPollingWorker(
        api=api,
        handle_update=lambda update: (
            events.append(("handle", update["update_id"]))
            or [TelegramOutboundMessage(chat_id=42, text="answered")]
        ),
        sender=sender,
        timeout_sec=25,
    )

    result = worker.run_once()

    assert result.processed is True
    assert sender.answer_calls == ["cb_21"]
    assert events == [("answer", "cb_21"), ("handle", 21)]
    assert len(sender.messages) == 1


def test_polling_callback_query_answer_exception_does_not_break_update_handling():
    sender = _AnswerTrackingSender(raise_in_answer=True)
    api = _Api([{"update_id": 22, "callback_query": {"id": "cb_22", "data": "help"}}])
    worker = TelegramPollingWorker(
        api=api,
        handle_update=lambda _update: [TelegramOutboundMessage(chat_id=42, text="handled despite answer error")],
        sender=sender,
        timeout_sec=25,
    )

    result = worker.run_once()

    assert result.processed is True
    assert sender.answer_calls == ["cb_22"]
    assert len(sender.messages) == 1
    assert sender.messages[0].text == "handled despite answer error"


def test_polling_regular_message_does_not_call_answer_callback_query():
    sender = _AnswerTrackingSender()
    api = _Api([{"update_id": 23, "message": {"text": "hello", "chat": {"id": 42}}}])
    worker = TelegramPollingWorker(
        api=api,
        handle_update=lambda _update: [TelegramOutboundMessage(chat_id=42, text="reply")],
        sender=sender,
        timeout_sec=25,
    )

    result = worker.run_once()

    assert result.processed is True
    assert sender.answer_calls == []
    assert len(sender.messages) == 1
    assert sender.messages[0].text == "reply"


def test_polling_falls_back_to_fallback_message_on_edit_unavailable():
    sender = _EditFallbackPollingSender()
    fallback_recorded = []

    def fake_fallback(msg):
        fallback_recorded.append(msg)
        return TelegramOutboundMessage(
            chat_id=msg.chat_id,
            text=msg.text,
            reply_markup=msg.reply_markup,
            edit_message_id=None,
        )

    api = _Api([{"update_id": 24, "message": {}}])
    initial_message = TelegramOutboundMessage(
        chat_id=42,
        text="Card content",
        reply_markup={"inline_keyboard": []},
        edit_message_id=99,
    )
    worker = TelegramPollingWorker(
        api=api,
        handle_update=lambda _update: [initial_message],
        sender=sender,
        timeout_sec=25,
        fallback_message=fake_fallback,
    )

    result = worker.run_once()

    assert result.processed is True
    assert len(fallback_recorded) == 1
    assert fallback_recorded[0].edit_message_id == 99
    assert len(sender.messages) == 1
    assert sender.messages[0].edit_message_id is None
    assert sender.messages[0].text == "Card content"
