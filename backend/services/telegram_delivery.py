"""Telegram delivery for transient interactive text and locally generated media."""

from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest

from services.telegram_registration import TelegramOutboundMessage
from services.telegram_transport import TelegramApiTransport, TelegramTransportError


class TelegramDeliveryError(RuntimeError):
    """Bot API delivery failed without exposing endpoint or payload details."""


class TelegramMessageEditUnavailableError(TelegramDeliveryError):
    """Telegram no longer has an editable copy of the requested message."""


def _multipart_photo_body(message: TelegramOutboundMessage) -> tuple[bytes, str]:
    if not message.photo_png:
        raise ValueError("photo payload is required")
    boundary = f"----submanager{secrets.token_hex(16)}"
    chunks: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        chunks.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ))

    add_field("chat_id", str(message.chat_id))
    if message.text:
        add_field("caption", message.text)
    if message.reply_markup is not None:
        add_field("reply_markup", json.dumps(message.reply_markup, ensure_ascii=False, separators=(",", ":")))
    filename = message.photo_filename or "access-qr.png"
    chunks.extend((
        f"--{boundary}\r\n".encode(),
        (
            'Content-Disposition: form-data; name="photo"; filename="'
            f'{filename}"\r\nContent-Type: image/png\r\n\r\n'
        ).encode(),
        message.photo_png,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ))
    return b"".join(chunks), boundary


class TelegramApiSender:
    """Request-local Bot API sender; never logs endpoints, links or QR bytes."""

    def __init__(self, bot_token: str, *, transport: TelegramApiTransport):
        self._endpoint = f"https://api.telegram.org/bot{bot_token}"
        self._transport = transport

    def send(self, message: TelegramOutboundMessage) -> int | None:
        if message.edit_message_id is not None:
            return self._edit_message(message)
        if message.photo_png is not None:
            body, boundary = _multipart_photo_body(message)
            request = UrlRequest(
                f"{self._endpoint}/sendPhoto",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
        else:
            payload: dict[str, Any] = {"chat_id": message.chat_id, "text": message.text}
            if message.reply_markup is not None:
                payload["reply_markup"] = message.reply_markup
            request = UrlRequest(
                f"{self._endpoint}/sendMessage",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        return self._send_request(request)

    def _edit_message(self, message: TelegramOutboundMessage) -> int:
        payload: dict[str, Any] = {
            "chat_id": message.chat_id,
            "message_id": message.edit_message_id,
            "text": message.text,
        }
        if message.reply_markup is not None:
            payload["reply_markup"] = message.reply_markup
        request = UrlRequest(
            f"{self._endpoint}/editMessageText",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send_request(request, edited_message_id=message.edit_message_id)

    def _send_request(self, request: UrlRequest, *, edited_message_id: int | None = None) -> int | None:
        try:
            with self._transport.open(request, timeout=10) as response:
                if response.status < 200 or response.status >= 300:
                    raise TelegramDeliveryError("Telegram delivery was rejected")
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            description = self._error_description(exc)
            if edited_message_id is not None and "message is not modified" in description:
                return edited_message_id
            if edited_message_id is not None and self._is_uneditable_message(description):
                raise TelegramMessageEditUnavailableError("Telegram message can no longer be edited") from exc
            raise TelegramDeliveryError("Telegram delivery failed") from exc
        except (URLError, OSError, ValueError, RuntimeError, TelegramTransportError) as exc:
            raise TelegramDeliveryError("Telegram delivery failed") from exc
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramDeliveryError("Telegram delivery was rejected")
        result = body.get("result")
        if isinstance(result, dict):
            message_id = result.get("message_id")
            if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
                return message_id
        return edited_message_id

    @staticmethod
    def _error_description(error: HTTPError) -> str:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (OSError, ValueError):
            return ""
        description = body.get("description") if isinstance(body, dict) else None
        return description.lower() if isinstance(description, str) else ""

    @staticmethod
    def _is_uneditable_message(description: str) -> bool:
        return any(marker in description for marker in (
            "message to edit not found",
            "message can't be edited",
            "message cannot be edited",
            "message is too old",
        ))
