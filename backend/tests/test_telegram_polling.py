import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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

    def send(self, *, chat_id, text, reply_markup=None):
        self.messages.append((chat_id, text, reply_markup))


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
    assert sender.messages == [(101, "received", None)]
