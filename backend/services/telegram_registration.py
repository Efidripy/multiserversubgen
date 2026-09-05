"""Neutral pre-approval Telegram conversation without transport side effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from services.telegram_registry import TelegramRegistry, TelegramRegistryError


@dataclass(frozen=True)
class TelegramOutboundMessage:
    chat_id: int
    text: str
    reply_markup: dict[str, Any] | None = None


def _private_actor(update: dict[str, Any]) -> tuple[int, int, dict[str, Any], str | None, str | None] | None:
    """Return trusted transport fields only for a private Telegram chat."""

    message = update.get("message")
    callback = update.get("callback_query")
    payload = message if isinstance(message, dict) else callback if isinstance(callback, dict) else None
    if not isinstance(payload, dict):
        return None
    sender = payload.get("from")
    callback_message = payload.get("message") if isinstance(payload.get("message"), dict) else None
    chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else callback_message.get("chat") if callback_message else None
    if not isinstance(sender, dict) or not isinstance(chat, dict) or chat.get("type") != "private":
        return None
    user_id = sender.get("id")
    chat_id = chat.get("id")
    if isinstance(user_id, bool) or isinstance(chat_id, bool) or not isinstance(user_id, int) or not isinstance(chat_id, int):
        return None
    text = message.get("text") if isinstance(message, dict) and isinstance(message.get("text"), str) else None
    callback_data = callback.get("data") if isinstance(callback, dict) and isinstance(callback.get("data"), str) else None
    return user_id, chat_id, sender, text, callback_data


class TelegramRegistrationService:
    """Handles first contact without exposing technical service details."""

    def __init__(self, registry: TelegramRegistry, *, introduction_max_chars: int):
        self._registry = registry
        self._introduction_max_chars = introduction_max_chars

    def handle_update(self, update: dict[str, Any]) -> list[TelegramOutboundMessage]:
        update_id = update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id <= 0:
            return []
        actor = _private_actor(update)
        if actor is None:
            return []
        user_id, chat_id, sender, text, callback_data = actor
        update_type = "callback_query" if callback_data is not None else "message"
        digest_source = {
            "update_id": update_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "text": text,
            "callback": callback_data,
        }
        digest = hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        # The durable update row has an FK to identity. Upsert the immutable
        # numeric identity first; a duplicate update can only refresh display
        # metadata and still cannot create a second application.
        identity = self._registry.get_or_create_identity(
            telegram_user_id=user_id,
            chat_id=chat_id,
            username=sender.get("username") if isinstance(sender.get("username"), str) else None,
            first_name=sender.get("first_name") if isinstance(sender.get("first_name"), str) else None,
            last_name=sender.get("last_name") if isinstance(sender.get("last_name"), str) else None,
            locale="ru",
        )
        if not self._registry.claim_update(
            update_id=update_id,
            telegram_user_id=user_id,
            update_type=update_type,
            payload_digest=digest,
        ):
            return []
        if identity.access_status == "blocked":
            return [TelegramOutboundMessage(chat_id, "Сейчас это действие недоступно.")]

        if text and text.strip().startswith("/start"):
            pending = self._registry.create_pending_application(user_id)
            if pending.created:
                return [
                    TelegramOutboundMessage(
                        chat_id,
                        "Здравствуйте. Ваша заявка принята и ожидает проверки. Пожалуйста, дождитесь ответа.",
                        {"inline_keyboard": [[{"text": "◎ Представиться", "callback_data": "registration:intro"}]]},
                    )
                ]
            if pending.identity.access_status == "approved":
                return [TelegramOutboundMessage(chat_id, "Ваш доступ уже подтверждён. Откройте меню, чтобы продолжить.")]
            return [TelegramOutboundMessage(chat_id, "Заявка уже ожидает проверки. Пожалуйста, дождитесь ответа.")]

        if callback_data == "registration:intro":
            if identity.access_status != "pending":
                return [TelegramOutboundMessage(chat_id, "Сейчас представление не требуется.")]
            return [
                TelegramOutboundMessage(
                    chat_id,
                    "Если хотите, коротко расскажите о себе и причине обращения одним сообщением. Это необязательно.",
                )
            ]

        if text and identity.access_status == "pending":
            try:
                saved = self._registry.submit_introduction(
                    user_id, text, maximum_chars=self._introduction_max_chars
                )
            except TelegramRegistryError:
                return [TelegramOutboundMessage(chat_id, "Сообщение не удалось принять. Попробуйте короче.")]
            if saved:
                return [TelegramOutboundMessage(chat_id, "Спасибо. Заявка по-прежнему ожидает проверки.")]
            return [TelegramOutboundMessage(chat_id, "Заявка уже ожидает проверки. Пожалуйста, дождитесь ответа.")]

        return [TelegramOutboundMessage(chat_id, "Для начала отправьте /start.")]
