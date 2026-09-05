"""Durable, opt-in notification delivery for the Telegram integration.

The outbox has at-least-once delivery semantics: a transport timeout can leave
the Telegram API outcome unknowable, so the record is retried after a bounded
backoff instead of being silently dropped.  Commands that change customer or
node state never call this worker inline.
"""

from __future__ import annotations

import secrets
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from urllib.error import URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from services.db_bootstrap import connect


class TelegramDeliveryPort(Protocol):
    def send(self, *, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None: ...


class OutboxPermanentError(RuntimeError):
    """The local event is no longer actionable and should be dead-lettered."""


class TelegramApiOutboxPort:
    """Small runtime-only Bot API transport; endpoint is never logged."""

    def __init__(self, bot_token: str):
        self._endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send(self, *, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
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


@dataclass(frozen=True)
class ClaimedOutboxEvent:
    event_id: int
    event_type: str
    entity_id: str
    attempt_count: int


@dataclass(frozen=True)
class OutboxRunResult:
    processed: bool
    event_id: int | None = None
    outcome: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


class TelegramOutboxWorker:
    """Lease one local notification, render it server-side and deliver safely."""

    def __init__(
        self,
        *,
        db_path: str,
        primary_admin_id: int,
        port: TelegramDeliveryPort,
        worker_id: str,
        now: Callable[[], datetime] = _utc_now,
        lease_seconds: int = 60,
        max_attempts: int = 8,
    ):
        if primary_admin_id <= 0 or not worker_id.strip() or lease_seconds <= 0 or max_attempts < 1:
            raise ValueError("outbox worker configuration is invalid")
        self._db_path = db_path
        self._primary_admin_id = primary_admin_id
        self._port = port
        self._worker_id = worker_id.strip()
        self._now = now
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    def run_once(self) -> OutboxRunResult:
        claimed = self._claim_next()
        if claimed is None:
            return OutboxRunResult(processed=False)
        try:
            chat_id, text, markup = self._render(claimed)
        except OutboxPermanentError as exc:
            self._dead_letter(claimed, str(exc))
            return OutboxRunResult(True, claimed.event_id, "dead_letter")
        try:
            self._port.send(chat_id=chat_id, text=text, reply_markup=markup)
        except Exception:
            self._retry_or_dead_letter(claimed, "delivery_uncertain")
            return OutboxRunResult(True, claimed.event_id, "retry")
        self._mark_sent(claimed)
        return OutboxRunResult(True, claimed.event_id, "sent")

    def _claim_next(self) -> ClaimedOutboxEvent | None:
        current = self._now()
        current_stamp = _timestamp(current)
        lease_until = _timestamp(current + timedelta(seconds=self._lease_seconds))
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT id, event_type, entity_id, attempt_count
                FROM telegram_outbox
                WHERE status IN ('queued', 'retry', 'sending')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY created_at, id
                LIMIT 1
                """,
                (current_stamp, current_stamp),
            ).fetchone()
            if row is None:
                return None
            update = conn.execute(
                """
                UPDATE telegram_outbox
                SET status = 'sending', lease_owner = ?, lease_until = ?,
                    attempt_count = attempt_count + 1, last_error_code = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('queued', 'retry', 'sending')
                  AND (lease_until IS NULL OR lease_until < ?)
                """,
                (self._worker_id, lease_until, int(row[0]), current_stamp),
            )
            if update.rowcount != 1:
                return None
        return ClaimedOutboxEvent(
            event_id=int(row[0]), event_type=str(row[1]), entity_id=str(row[2]), attempt_count=int(row[3]) + 1
        )

    def _render(self, event: ClaimedOutboxEvent) -> tuple[int, str, dict[str, Any] | None]:
        if event.event_type == "admin_request_created":
            return self._primary_admin_id, f"Новая заявка: #{event.entity_id}.", {"inline_keyboard": [[{"text": "Заявки", "callback_data": "admin:requests:0"}]]}
        if event.event_type == "admin_identity_auto_blocked":
            return self._primary_admin_id, f"Автоблокировка: #{event.entity_id}. Проверьте заявку при необходимости.", None
        if event.event_type == "admin_appeal_created":
            with connect(self._db_path) as conn:
                row = conn.execute(
                    """
                    SELECT a.telegram_user_id, c.email_display, a.body
                    FROM telegram_appeals AS a
                    JOIN customers AS c ON c.id = a.customer_id
                    WHERE a.id = ?
                    """,
                    (event.entity_id,),
                ).fetchone()
            if row is None:
                raise OutboxPermanentError("appeal_not_found")
            return self._primary_admin_id, f"Обращение от {row[1]} (#{row[0]}):\n{row[2]}", None
        if event.event_type in {"user_provisioning_queued", "user_existing_access_approved"}:
            try:
                user_id = int(event.entity_id)
            except ValueError as exc:
                raise OutboxPermanentError("invalid_user_id") from exc
            with connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT chat_id FROM telegram_identities WHERE telegram_user_id = ?",
                    (user_id,),
                ).fetchone()
            if row is None:
                raise OutboxPermanentError("identity_not_found")
            if event.event_type == "user_provisioning_queued":
                return int(row[0]), "Решение принято. Доступ готовится; проверьте статус немного позже.", None
            return int(row[0]), "Решение принято. Откройте меню, чтобы продолжить.", None
        raise OutboxPermanentError("unsupported_event_type")

    def _mark_sent(self, claimed: ClaimedOutboxEvent) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_outbox
                SET status = 'sent', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = NULL, sent_at = CURRENT_TIMESTAMP,
                    last_error_code = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'sending' AND lease_owner = ?
                """,
                (claimed.event_id, self._worker_id),
            )

    def _dead_letter(self, claimed: ClaimedOutboxEvent, error_code: str) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_outbox
                SET status = 'dead_letter', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = NULL, last_error_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'sending' AND lease_owner = ?
                """,
                (error_code[:80], claimed.event_id, self._worker_id),
            )

    def _retry_or_dead_letter(self, claimed: ClaimedOutboxEvent, error_code: str) -> None:
        if claimed.attempt_count >= self._max_attempts:
            self._dead_letter(claimed, error_code)
            return
        delay_seconds = min(900, 2 ** min(claimed.attempt_count, 9)) + secrets.randbelow(1000) / 1000
        next_attempt = _timestamp(self._now() + timedelta(seconds=delay_seconds))
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_outbox
                SET status = 'retry', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = ?, last_error_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'sending' AND lease_owner = ?
                """,
                (next_attempt, error_code, claimed.event_id, self._worker_id),
            )
