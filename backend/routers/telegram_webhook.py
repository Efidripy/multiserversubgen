"""Webhook adapter for the intentionally small first Telegram conversation."""

from __future__ import annotations

import secrets
from typing import Any, Callable, Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from services.telegram_delivery import TelegramApiSender, TelegramMessageEditUnavailableError
from services.telegram_registration import TelegramOutboundMessage, TelegramRegistrationService
from services.telegram_registry import TelegramRegistry
from services.telegram_transport import TelegramApiTransport


class TelegramMessageSender(Protocol):
    def send(self, message: TelegramOutboundMessage) -> int | None: ...


def build_telegram_webhook_router(
    *,
    telegram_settings,
    db_path: str,
    sender: TelegramMessageSender | None = None,
    list_nodes: Callable[[], list[dict[str, Any]]] | None = None,
    get_links_filtered: Callable[[list[dict[str, Any]], str, str | None], list[str]] | None = None,
    get_cached_inbound_options: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    traffic_projection_loader: Callable[[], dict[str, Any]] | None = None,
    discover_existing: Callable[[str], tuple[Any, ...]] | None = None,
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
        traffic_projection_loader=traffic_projection_loader,
        discover_existing=discover_existing,
    )
    message_sender = sender or TelegramApiSender(
        telegram_settings.bot_token,
        transport=TelegramApiTransport(db_path=db_path, local_proxy_url=telegram_settings.local_proxy_url),
    )

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
            try:
                message_id = await run_in_threadpool(message_sender.send, message)
            except TelegramMessageEditUnavailableError:
                fallback = service.fallback_subscription_message(message)
                if fallback is None:
                    raise
                message = fallback
                message_id = await run_in_threadpool(message_sender.send, message)
            await run_in_threadpool(service.record_outbound_delivery, message, message_id)
        return {"ok": True}

    return router
