"""Webhook adapter for the intentionally small first Telegram conversation."""

from __future__ import annotations

import json
import secrets
from typing import Any, Callable, Protocol
from urllib.error import URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from services.telegram_registration import TelegramOutboundMessage, TelegramRegistrationService
from services.telegram_registry import TelegramRegistry


class TelegramMessageSender(Protocol):
    def send(self, message: TelegramOutboundMessage) -> None: ...


class TelegramApiSender:
    """Minimal Bot API sender; never logs a token-bearing endpoint."""

    def __init__(self, bot_token: str):
        self._endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send(self, message: TelegramOutboundMessage) -> None:
        payload: dict[str, Any] = {"chat_id": message.chat_id, "text": message.text}
        if message.reply_markup is not None:
            payload["reply_markup"] = message.reply_markup
        request = UrlRequest(
            self._endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError("Telegram delivery was rejected")
        except (URLError, OSError, RuntimeError) as exc:
            raise RuntimeError("Telegram delivery failed") from exc


def build_telegram_webhook_router(
    *,
    telegram_settings,
    db_path: str,
    sender: TelegramMessageSender | None = None,
    list_nodes: Callable[[], list[dict[str, Any]]] | None = None,
    get_links_filtered: Callable[[list[dict[str, Any]], str, str | None], list[str]] | None = None,
    get_cached_inbound_options: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
):
    router = APIRouter()
    registry = TelegramRegistry(db_path)
    service = TelegramRegistrationService(
        registry,
        introduction_max_chars=telegram_settings.introduction_max_chars,
        public_base_url=getattr(telegram_settings, "public_base_url", ""),
        list_nodes=list_nodes,
        get_links_filtered=get_links_filtered,
        primary_admin_id=getattr(telegram_settings, "primary_admin_id", None),
        get_cached_inbound_options=get_cached_inbound_options,
    )
    message_sender = sender or TelegramApiSender(telegram_settings.bot_token)

    @router.post("/telegram/webhook/{path_suffix}", include_in_schema=False)
    async def receive_update(path_suffix: str, request: Request, data: dict[str, Any]):
        if not telegram_settings.enabled or not secrets.compare_digest(
            path_suffix, telegram_settings.webhook_path_suffix
        ):
            raise HTTPException(status_code=404, detail="Not found")
        supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secrets.compare_digest(supplied_secret, telegram_settings.webhook_secret):
            raise HTTPException(status_code=403, detail="Forbidden")
        for message in service.handle_update(data):
            await run_in_threadpool(message_sender.send, message)
        return {"ok": True}

    return router
