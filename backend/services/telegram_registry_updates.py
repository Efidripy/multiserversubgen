"""Durable Telegram update and subscription message receipt operations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from services.db_bootstrap import connect


def claim_update(
    self,
    *,
    update_id: int,
    telegram_user_id: int | None,
    update_type: str,
    payload_digest: str,
    positive_int: Callable[[int, str], int],
    nonempty: Callable[[str, str], str],
) -> bool:
    """Persist Telegram's update id before any state-changing handling."""

    normalized_update_id = positive_int(update_id, "update_id")
    normalized_user_id = (
        positive_int(telegram_user_id, "telegram_user_id")
        if telegram_user_id is not None
        else None
    )
    with connect(self._db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO telegram_updates (update_id, telegram_user_id, update_type, payload_digest)
                VALUES (?, ?, ?, ?)
                """,
                (normalized_update_id, normalized_user_id, nonempty(update_type, "update_type"), nonempty(payload_digest, "payload_digest")),
            )
        except sqlite3.IntegrityError:
            return False
    return True


def store_update_responses(
    self,
    *,
    update_id: int,
    responses: list[tuple],
    positive_int: Callable[[int, str], int],
    nonempty: Callable[[str, str], str],
    error_type: type[Exception],
) -> None:
    """Store retry-safe replies keyed by Telegram's immutable update id."""

    normalized_update_id = positive_int(update_id, "update_id")
    rows: list[tuple[int, int, str, str | None]] = []
    for index, response in enumerate(responses):
        chat_id, text, markup = response[:3]
        photos = response[3] if len(response) > 3 else None
        normalized_chat_id = positive_int(chat_id, "chat_id")
        normalized_text = nonempty(text, "response_text")
        if len(normalized_text) > 4096:
            raise error_type("response_text is too long")
        if markup is not None and not isinstance(markup, dict):
            raise error_type("response_markup must be an object")
        markup_json = (
            json.dumps(markup, ensure_ascii=False, separators=(",", ":"))
            if markup is not None
            else None
        )
        if markup_json is not None and len(markup_json) > 16384:
            raise error_type("response_markup is too long")
        rows.append((normalized_update_id, index, normalized_chat_id, normalized_text, markup_json,
                     json.dumps(photos) if photos else None))
    if not rows:
        return
    with connect(self._db_path) as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO telegram_update_responses
                (update_id, response_index, chat_id, text, reply_markup_json, photo_file_ids)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def pending_update_responses(
    self,
    update_id: int,
    *,
    positive_int: Callable[[int, str], int],
    error_type: type[Exception],
) -> list[tuple[int, int, str, dict[str, Any] | None]]:
    normalized_update_id = positive_int(update_id, "update_id")
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT response_index, chat_id, text, reply_markup_json, photo_file_ids
            FROM telegram_update_responses
            WHERE update_id = ?
              AND (
                status = 'queued'
                OR (status = 'prepared' AND created_at <= datetime('now', '-1 minute'))
              )
            ORDER BY response_index
            """,
            (normalized_update_id,),
        ).fetchall()
    result: list[tuple[int, int, str, dict[str, Any] | None]] = []
    for row in rows:
        markup = None
        if row[3] is not None:
            try:
                decoded = json.loads(str(row[3]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise error_type("stored response markup is invalid") from exc
            if not isinstance(decoded, dict):
                raise error_type("stored response markup is invalid")
            markup = decoded
        result.append((int(row[0]), int(row[1]), str(row[2]), markup,
                       tuple(json.loads(row[4])) if row[4] else None))
    return result


def mark_update_response_delivered(
    self,
    *,
    update_id: int,
    response_index: int,
    positive_int: Callable[[int, str], int],
    error_type: type[Exception],
) -> None:
    normalized_update_id = positive_int(update_id, "update_id")
    if isinstance(response_index, bool) or not isinstance(response_index, int) or response_index < 0:
        raise error_type("response_index is invalid")
    with connect(self._db_path) as conn:
        conn.execute(
            """
            UPDATE telegram_update_responses
            SET status = 'sent', sent_at = CURRENT_TIMESTAMP
            WHERE update_id = ? AND response_index = ? AND status IN ('prepared', 'queued')
            """,
            (normalized_update_id, response_index),
        )


def mark_update_processed(
    self,
    update_id: int,
    *,
    positive_int: Callable[[int, str], int],
) -> None:
    """Record completion time without changing the durable update status."""

    normalized_update_id = positive_int(update_id, "update_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "UPDATE telegram_updates SET processed_at = CURRENT_TIMESTAMP WHERE update_id = ?",
            (normalized_update_id,),
        )


def retry_update_response(
    self,
    *,
    update_id: int,
    response_index: int,
    positive_int: Callable[[int, str], int],
    error_type: type[Exception],
) -> None:
    normalized_update_id = positive_int(update_id, "update_id")
    if isinstance(response_index, bool) or not isinstance(response_index, int) or response_index < 0:
        raise error_type("response_index is invalid")
    with connect(self._db_path) as conn:
        conn.execute(
            """
            UPDATE telegram_update_responses
            SET status = 'queued'
            WHERE update_id = ? AND response_index = ? AND status = 'prepared'
            """,
            (normalized_update_id, response_index),
        )


def get_subscription_message_receipt(
    self,
    telegram_user_id: int,
    *,
    positive_int: Callable[[int, str], int],
    receipt_type: type,
) -> Any:
    """Read a delivery pointer without ever exposing or storing the raw token."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT telegram_user_id, token_digest, chat_id, message_id
            FROM telegram_subscription_message_receipts
            WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return receipt_type(
        telegram_user_id=int(row[0]),
        token_digest=str(row[1]),
        chat_id=int(row[2]),
        message_id=int(row[3]),
    )


def record_subscription_message_delivery(
    self,
    *,
    telegram_user_id: int,
    token_digest: str,
    chat_id: int,
    message_id: int,
    positive_int: Callable[[int, str], int],
    nonempty: Callable[[str, str], str],
) -> None:
    """Persist only the opaque token digest and Telegram message coordinates."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    normalized_chat_id = positive_int(chat_id, "chat_id")
    normalized_message_id = positive_int(message_id, "message_id")
    normalized_digest = nonempty(token_digest, "token_digest")
    with connect(self._db_path) as conn:
        conn.execute(
            """
            INSERT INTO telegram_subscription_message_receipts
                (telegram_user_id, token_digest, chat_id, message_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                token_digest = excluded.token_digest,
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, normalized_digest, normalized_chat_id, normalized_message_id),
        )
