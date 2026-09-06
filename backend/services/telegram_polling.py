"""Outbound-only Telegram update polling for networks unsuitable for webhooks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import URLError
from urllib.request import Request as UrlRequest

from services.telegram_registration import TelegramOutboundMessage
from services.telegram_transport import TelegramApiTransport, TelegramTransportError


class TelegramPollingError(RuntimeError):
    """A Bot API polling request was unavailable or malformed."""


class TelegramBotApiPort(Protocol):
    def delete_webhook(self) -> None: ...

    def get_updates(self, *, offset: int | None, timeout_sec: int) -> list[dict[str, Any]]: ...


class TelegramMessagePort(Protocol):
    def send(self, message: TelegramOutboundMessage) -> None: ...


class TelegramBotApiClient:
    """Small Bot API client that always uses the request-local Telegram transport."""

    def __init__(self, bot_token: str, *, transport: TelegramApiTransport):
        self._endpoint = f"https://api.telegram.org/bot{bot_token}"
        self._transport = transport

    def delete_webhook(self) -> None:
        self._call("deleteWebhook", {"drop_pending_updates": False}, timeout=15)

    def get_updates(self, *, offset: int | None, timeout_sec: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_sec,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload, timeout=timeout_sec + 10)
        if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
            raise TelegramPollingError("Telegram getUpdates returned an invalid response")
        return result

    def _call(self, method: str, payload: dict[str, Any], *, timeout: int) -> Any:
        request = UrlRequest(
            f"{self._endpoint}/{method}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._transport.open(request, timeout=timeout) as response:
                if response.status < 200 or response.status >= 300:
                    raise TelegramPollingError("Telegram Bot API rejected polling request")
                body = json.loads(response.read().decode("utf-8"))
        except (URLError, OSError, ValueError, TelegramTransportError) as exc:
            raise TelegramPollingError("Telegram Bot API polling request failed") from exc
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramPollingError("Telegram Bot API rejected polling request")
        return body.get("result")


@dataclass(frozen=True)
class TelegramPollingRunResult:
    processed: bool
    update_count: int = 0


class TelegramPollingWorker:
    """Consume private updates without exposing a public webhook endpoint."""

    def __init__(
        self,
        *,
        api: TelegramBotApiPort,
        handle_update: Callable[[dict[str, Any]], list[TelegramOutboundMessage]],
        sender: TelegramMessagePort,
        timeout_sec: int,
    ):
        if not 1 <= timeout_sec <= 50:
            raise ValueError("Telegram polling timeout must be from 1 to 50 seconds")
        self._api = api
        self._handle_update = handle_update
        self._sender = sender
        self._timeout_sec = timeout_sec
        self._started = False
        self._next_offset: int | None = None

    def run_once(self) -> TelegramPollingRunResult:
        if not self._started:
            # Keep existing pending updates. This enables a safe migration from
            # webhook to polling and does not silently discard a user's /start.
            self._api.delete_webhook()
            self._started = True
        updates = self._api.get_updates(offset=self._next_offset, timeout_sec=self._timeout_sec)
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id <= 0:
                continue
            messages = self._handle_update(update)
            for message in messages:
                self._sender.send(message)
            self._next_offset = update_id + 1
        return TelegramPollingRunResult(processed=bool(updates), update_count=len(updates))
