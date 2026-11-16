"""Draft storage operations for the Telegram registry."""

from __future__ import annotations

import json
from typing import Any

from services.db_bootstrap import connect


def set_admin_draft(
    self,
    *,
    admin_telegram_user_id: int,
    action: str,
    telegram_user_id: int | None = None,
    customer_id: int | None = None,
    expected_row_version: int | None = None,
    page: int = 0,
    value: str | None = None,
    positive_int,
    error_type,
    admin_draft_type,
) -> Any:
    """Persist only bounded command context; never store user application text."""

    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    if action not in {
        "new_customer_name", "existing_customer_email", "delete_customer_confirmation",
    }:
        raise error_type("admin draft action is invalid")
    target_user = positive_int(telegram_user_id, "telegram_user_id") if telegram_user_id is not None else None
    target_customer = positive_int(customer_id, "customer_id") if customer_id is not None else None
    expected_version = positive_int(expected_row_version, "expected_row_version") if expected_row_version is not None else None
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise error_type("admin draft page is invalid")
    normalized_value = value.strip() if isinstance(value, str) else None
    if normalized_value == "":
        normalized_value = None
    if normalized_value is not None and len(normalized_value) > 128:
        raise error_type("admin draft value is too long")
    with connect(self._db_path) as conn:
        conn.execute(
            """
            INSERT INTO telegram_admin_drafts
                (admin_telegram_user_id, action, telegram_user_id, customer_id,
                 expected_row_version, page, value)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(admin_telegram_user_id) DO UPDATE SET
                action = excluded.action,
                telegram_user_id = excluded.telegram_user_id,
                customer_id = excluded.customer_id,
                expected_row_version = excluded.expected_row_version,
                page = excluded.page,
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (admin_id, action, target_user, target_customer, expected_version, page, normalized_value),
        )
    return admin_draft_type(
        admin_telegram_user_id=admin_id,
        action=action,
        telegram_user_id=target_user,
        customer_id=target_customer,
        expected_row_version=expected_version,
        page=page,
        value=normalized_value,
    )

def get_admin_draft(self, admin_telegram_user_id: int, *, positive_int, admin_draft_type) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT admin_telegram_user_id, action, telegram_user_id, customer_id,
                   expected_row_version, page, value
            FROM telegram_admin_drafts WHERE admin_telegram_user_id = ?
            """,
            (admin_id,),
        ).fetchone()
    if row is None:
        return None
    return admin_draft_type(
        admin_telegram_user_id=int(row[0]), action=str(row[1]),
        telegram_user_id=int(row[2]) if row[2] is not None else None,
        customer_id=int(row[3]) if row[3] is not None else None,
        expected_row_version=int(row[4]) if row[4] is not None else None,
        page=int(row[5]), value=str(row[6]) if row[6] is not None else None,
    )

def clear_admin_draft(self, admin_telegram_user_id: int, *, positive_int) -> None:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_admin_drafts WHERE admin_telegram_user_id = ?", (admin_id,)
        )

def set_admin_message_draft(
    self,
    *,
    admin_telegram_user_id: int,
    mode: str,
    customer_id: int | None = None,
    page: int = 0,
    body: str | None = None,
    photo_file_ids: tuple[str, ...] | None = None,
    media_group_id: str | None = None,
    positive_int,
    normalize_admin_message_body,
    error_type,
    admin_message_draft_type,
) -> Any:
    """Store only the owner's bounded, confirmation-gated composition."""

    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    if mode not in {"direct", "broadcast"}:
        raise error_type("admin message draft mode is invalid")
    target_customer = positive_int(customer_id, "customer_id") if customer_id is not None else None
    if mode == "direct" and target_customer is None:
        raise error_type("direct message target is required")
    if mode == "broadcast" and target_customer is not None:
        raise error_type("broadcast cannot target one customer")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise error_type("admin message draft page is invalid")
    normalized_body = normalize_admin_message_body(body) if body is not None else None
    if photo_file_ids and (len(photo_file_ids) > 10 or
                           any(not isinstance(item, str) or not item for item in photo_file_ids) or
                           (normalized_body is not None and len(normalized_body) > 1024)):
        raise error_type("invalid broadcast photos")
    photos_json = json.dumps(photo_file_ids, ensure_ascii=False) if photo_file_ids else None
    with connect(self._db_path) as conn:
        conn.execute(
            """
            INSERT INTO telegram_admin_message_drafts
                (admin_telegram_user_id, mode, customer_id, page, body, photo_file_ids, media_group_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(admin_telegram_user_id) DO UPDATE SET
                mode = excluded.mode,
                customer_id = excluded.customer_id,
                page = excluded.page,
                body = excluded.body,
                photo_file_ids = excluded.photo_file_ids,
                media_group_id = excluded.media_group_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (admin_id, mode, target_customer, page, normalized_body, photos_json, media_group_id),
        )
    return admin_message_draft_type(admin_id, mode, target_customer, page, normalized_body, photo_file_ids, media_group_id)

def get_admin_message_draft(self, admin_telegram_user_id: int, *, positive_int, admin_message_draft_type) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT admin_telegram_user_id, mode, customer_id, page, body, photo_file_ids, media_group_id
            FROM telegram_admin_message_drafts
            WHERE admin_telegram_user_id = ?
            """,
            (admin_id,),
        ).fetchone()
    if row is None:
        return None
    return admin_message_draft_type(
        admin_telegram_user_id=int(row[0]), mode=str(row[1]),
        customer_id=int(row[2]) if row[2] is not None else None,
        page=int(row[3]), body=str(row[4]) if row[4] is not None else None,
        photo_file_ids=tuple(json.loads(row[5])) if row[5] else None,
        media_group_id=str(row[6]) if row[6] is not None else None,
    )

def clear_admin_message_draft(self, admin_telegram_user_id: int, *, positive_int) -> None:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_admin_message_drafts WHERE admin_telegram_user_id = ?", (admin_id,)
        )

def set_customer_note_draft(
    self, *, admin_telegram_user_id: int, customer_id: int, page: int,
    positive_int, error_type, customer_note_draft_type
) -> Any:
    """Persist note-entry destination only; the note text is not staged."""

    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    local_customer_id = positive_int(customer_id, "customer_id")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise error_type("admin draft page is invalid")
    with connect(self._db_path) as conn:
        customer_exists = conn.execute(
            "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if customer_exists is None:
            raise error_type("customer was not found")
        conn.execute(
            """
            INSERT INTO telegram_customer_note_drafts (admin_telegram_user_id, customer_id, page)
            VALUES (?, ?, ?)
            ON CONFLICT(admin_telegram_user_id) DO UPDATE SET
                customer_id = excluded.customer_id,
                page = excluded.page,
                updated_at = CURRENT_TIMESTAMP
            """,
            (admin_id, local_customer_id, page),
        )
    return customer_note_draft_type(admin_id, local_customer_id, page)

def get_customer_note_draft(self, admin_telegram_user_id: int, *, positive_int, customer_note_draft_type) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT customer_id, page
            FROM telegram_customer_note_drafts
            WHERE admin_telegram_user_id = ?
            """,
            (admin_id,),
        ).fetchone()
    if row is None:
        return None
    return customer_note_draft_type(admin_id, int(row[0]), int(row[1]))

def clear_customer_note_draft(self, admin_telegram_user_id: int, *, positive_int) -> None:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_customer_note_drafts WHERE admin_telegram_user_id = ?", (admin_id,)
        )

def set_support_reply_draft(
    self,
    *,
    admin_telegram_user_id: int,
    support_request_id: int,
    customer_id: int,
    expected_row_version: int,
    page: int,
    body: str | None = None,
    positive_int,
    error_type,
    version_conflict_type,
    support_reply_draft_type,
) -> Any:
    """Persist a bounded admin reply only after proving the ticket is still unresolved."""

    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    request_id = positive_int(support_request_id, "support_request_id")
    local_customer_id = positive_int(customer_id, "customer_id")
    expected_version = positive_int(expected_row_version, "expected_row_version")
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise error_type("admin draft page is invalid")
    normalized_body = body.strip() if isinstance(body, str) else None
    if normalized_body == "":
        raise error_type("support response must contain 1 to 1000 characters")
    if normalized_body is not None and not 1 <= len(normalized_body) <= 1000:
        raise error_type("support response must contain 1 to 1000 characters")
    with connect(self._db_path) as conn:
        ticket = conn.execute(
            "SELECT customer_id, status, row_version FROM telegram_support_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if (
            ticket is None
            or int(ticket[0]) != local_customer_id
            or str(ticket[1]) not in {"open", "read"}
            or int(ticket[2]) != expected_version
        ):
            raise version_conflict_type("support request was updated by another administrator")
        conn.execute(
            """
            INSERT INTO telegram_support_reply_drafts
                (admin_telegram_user_id, support_request_id, customer_id, expected_row_version, page, body)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(admin_telegram_user_id) DO UPDATE SET
                support_request_id = excluded.support_request_id,
                customer_id = excluded.customer_id,
                expected_row_version = excluded.expected_row_version,
                page = excluded.page,
                body = excluded.body,
                updated_at = CURRENT_TIMESTAMP
            """,
            (admin_id, request_id, local_customer_id, expected_version, page, normalized_body),
        )
    return support_reply_draft_type(
        admin_id, request_id, local_customer_id, expected_version, page, normalized_body
    )

def get_support_reply_draft(self, admin_telegram_user_id: int, *, positive_int, support_reply_draft_type) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT support_request_id, customer_id, expected_row_version, page, body
            FROM telegram_support_reply_drafts WHERE admin_telegram_user_id = ?
            """,
            (admin_id,),
        ).fetchone()
    if row is None:
        return None
    return support_reply_draft_type(
        admin_id, int(row[0]), int(row[1]), int(row[2]), int(row[3]),
        str(row[4]) if row[4] is not None else None,
    )

def clear_support_reply_draft(self, admin_telegram_user_id: int, *, positive_int) -> None:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_support_reply_drafts WHERE admin_telegram_user_id = ?", (admin_id,)
        )

def set_subscription_device_draft(
    self, *, telegram_user_id: int, subscription_device_id: int, positive_int, get_subscription_device
) -> None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    device = get_subscription_device(
        telegram_user_id=user_id, subscription_device_id=subscription_device_id
    )
    with connect(self._db_path) as conn:
        conn.execute(
            """
            INSERT INTO telegram_subscription_device_drafts (telegram_user_id, subscription_device_id)
            VALUES (?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                subscription_device_id = excluded.subscription_device_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, device.device_id),
        )

def get_subscription_device_draft(self, telegram_user_id: int, *, positive_int) -> int | None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            "SELECT subscription_device_id FROM telegram_subscription_device_drafts "
            "WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row[0]) if row is not None else None

def clear_subscription_device_draft(self, telegram_user_id: int, *, positive_int) -> None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_subscription_device_drafts WHERE telegram_user_id = ?", (user_id,)
        )

def set_logical_device_draft(self, *, telegram_user_id: int, device_id: int, positive_int, error_type, active_telegram_customer) -> None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    local_device_id = positive_int(device_id, "device_id")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        if conn.execute(
            "SELECT 1 FROM telegram_logical_devices WHERE id = ? AND customer_id = ?",
            (local_device_id, customer_id),
        ).fetchone() is None:
            raise error_type("logical device was not found")
        conn.execute(
            """
            INSERT INTO telegram_logical_device_drafts (telegram_user_id, device_id)
            VALUES (?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                device_id = excluded.device_id, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, local_device_id),
        )

def get_logical_device_draft(self, telegram_user_id: int, *, positive_int) -> int | None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            "SELECT device_id FROM telegram_logical_device_drafts WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
    return int(row[0]) if row is not None else None

def clear_logical_device_draft(self, telegram_user_id: int, *, positive_int) -> None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute("DELETE FROM telegram_logical_device_drafts WHERE telegram_user_id = ?", (user_id,))

def clear_support_draft(self, telegram_user_id: int, *, positive_int) -> None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute("DELETE FROM telegram_user_drafts WHERE telegram_user_id = ?", (user_id,))

def set_service_notice_draft(
    self, *, admin_telegram_user_id: int, expected_row_version: int,
    positive_int, error_type, version_conflict_type, service_notice_draft_type
) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    if isinstance(expected_row_version, bool) or not isinstance(expected_row_version, int) or expected_row_version < 0:
        raise error_type("service notice version is invalid")
    with connect(self._db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (admin_id,)
        ).fetchone() is None:
            raise error_type("Telegram identity was not found")
        current = conn.execute(
            "SELECT row_version FROM telegram_service_notice WHERE id = 1"
        ).fetchone()
        current_version = int(current[0]) if current is not None else 0
        if current_version != expected_row_version:
            raise version_conflict_type("service notice was updated by another administrator")
        conn.execute(
            """
            INSERT INTO telegram_service_notice_drafts (admin_telegram_user_id, expected_row_version)
            VALUES (?, ?)
            ON CONFLICT(admin_telegram_user_id) DO UPDATE SET
                expected_row_version = excluded.expected_row_version, updated_at = CURRENT_TIMESTAMP
            """,
            (admin_id, expected_row_version),
        )
    return service_notice_draft_type(admin_id, expected_row_version)

def get_service_notice_draft(self, admin_telegram_user_id: int, *, positive_int, service_notice_draft_type) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            "SELECT expected_row_version FROM telegram_service_notice_drafts WHERE admin_telegram_user_id = ?",
            (admin_id,),
        ).fetchone()
    return service_notice_draft_type(admin_id, int(row[0])) if row is not None else None

def clear_service_notice_draft(self, admin_telegram_user_id: int, *, positive_int) -> None:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_service_notice_drafts WHERE admin_telegram_user_id = ?", (admin_id,)
        )
