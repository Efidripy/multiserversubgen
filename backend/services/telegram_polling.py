"""Outbound-only Telegram update polling for networks unsuitable for webhooks."""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import URLError
from urllib.request import Request as UrlRequest

from services.telegram_delivery import TelegramMessageEditUnavailableError
from services.telegram_registration import TelegramOutboundMessage
from services.telegram_transport import TelegramApiTransport, TelegramTransportError


logger = logging.getLogger("sub_manager")


class TelegramPollingError(RuntimeError):
    """A Bot API polling request was unavailable or malformed."""


class TelegramBotApiPort(Protocol):
    def delete_webhook(self) -> None: ...

    def get_updates(self, *, offset: int | None, timeout_sec: int) -> list[dict[str, Any]]: ...


class TelegramMessagePort(Protocol):
    def send(self, message: TelegramOutboundMessage) -> int | None: ...


class TelegramBotApiClient:
    """Small Bot API client that always uses the request-local Telegram transport."""

    def __init__(self, bot_token: str | Callable[[], str], *, transport: TelegramApiTransport):
        self._token_provider = bot_token if callable(bot_token) else lambda: bot_token
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
            f"https://api.telegram.org/bot{self._token_provider()}/{method}",
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
        fallback_message: Callable[[TelegramOutboundMessage], TelegramOutboundMessage | None] | None = None,
        record_outbound_delivery: Callable[[TelegramOutboundMessage, int | None], None] | None = None,
        mark_update_response_delivered: Callable[[TelegramOutboundMessage], None] | None = None,
        mark_update_processed: Callable[[int], None] | None = None,
        retry_update_response: Callable[[TelegramOutboundMessage], None] | None = None,
    ):
        if not 1 <= timeout_sec <= 50:
            raise ValueError("Telegram polling timeout must be from 1 to 50 seconds")
        self._api = api
        self._handle_update = handle_update
        self._sender = sender
        self._timeout_sec = timeout_sec
        self._fallback_message = fallback_message
        self._record_outbound_delivery = record_outbound_delivery
        self._mark_update_response_delivered = mark_update_response_delivered
        self._mark_update_processed = mark_update_processed
        self._retry_update_response = retry_update_response
        self._started = False
        self._next_offset: int | None = None
        self._answer_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="telegram-callback")

    def close(self) -> None:
        """Stop accepting callback answers without waiting for in-flight calls."""

        self._answer_executor.shutdown(wait=False, cancel_futures=True)

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
            started_at = time.monotonic()
            handle_ms = 0.0
            send_started_at = started_at
            send_ms = 0.0
            callback = update.get("callback_query")
            callback_id = callback.get("id") if isinstance(callback, dict) else None
            answer_callback_query = getattr(self._sender, "answer_callback_query", None)
            if isinstance(callback_id, str) and answer_callback_query is not None:
                self._answer_executor.submit(self._answer_callback_query, answer_callback_query, callback_id)
            try:
                handle_started_at = time.monotonic()
                messages = self._handle_update(update)
                handle_ms = (time.monotonic() - handle_started_at) * 1000
                send_started_at = time.monotonic()
                for message in messages:
                    try:
                        try:
                            message_id = self._sender.send(message)
                        except TelegramMessageEditUnavailableError:
                            fallback = self._fallback_message(message) if self._fallback_message else None
                            if fallback is None:
                                raise
                            message = fallback
                            message_id = self._sender.send(message)
                        if self._record_outbound_delivery:
                            self._record_outbound_delivery(message, message_id)
                        if self._mark_update_response_delivered:
                            self._mark_update_response_delivered(message)
                    except Exception:
                        if self._retry_update_response:
                            self._retry_update_response(message)
                        raise
                send_ms = (time.monotonic() - send_started_at) * 1000
                if self._mark_update_processed:
                    try:
                        self._mark_update_processed(update_id)
                    except Exception:
                        pass
                self._next_offset = update_id + 1
            finally:
                if send_started_at != started_at and send_ms == 0.0:
                    send_ms = (time.monotonic() - send_started_at) * 1000
                update_kind = "callback" if isinstance(callback, dict) else "message" if isinstance(update.get("message"), dict) else "other"
                if update_kind == "callback":
                    callback_data = callback.get("data") if isinstance(callback, dict) else None
                    callback_head = callback_data.split(":", 1)[0] if isinstance(callback_data, str) else ""
                    if re.fullmatch(r"[a-z][a-z_-]{0,31}", callback_head):
                        update_kind = f"callback:{callback_head}"
                    else:
                        update_kind = "callback:other"
                logger.info("telegram update type=%s handle_ms=%.2f send_ms=%.2f", update_kind, handle_ms, send_ms)
        return TelegramPollingRunResult(processed=bool(updates), update_count=len(updates))

    @staticmethod
    def _answer_callback_query(answer_callback_query: Callable[[str], None], callback_id: str) -> None:
        try:
            answer_callback_query(callback_id)
        except Exception:
            pass
