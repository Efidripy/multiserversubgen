"""Appeal and support request operations for the Telegram registry."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Any

from services.db_bootstrap import connect


def submit_suspended_appeal(
    self, *, telegram_user_id: int, body: str, positive_int, error_type, suspended_statuses, appeal_result_type
):
    """Store one bounded appeal; it never changes customer access."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    normalized_body = body.strip()
    if not 1 <= len(normalized_body) <= 1000:
        raise error_type("appeal body must contain 1 to 1000 characters")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT i.customer_id, i.access_status, c.status
            FROM telegram_identities AS i
            JOIN customers AS c ON c.id = i.customer_id
            WHERE i.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if (
            row is None
            or str(row[1]) != "approved"
            or str(row[2]) not in suspended_statuses
        ):
            raise error_type("appeal is available only for a suspended customer")
        try:
            cursor = conn.execute(
                """
                INSERT INTO telegram_appeals (telegram_user_id, customer_id, body)
                VALUES (?, ?, ?)
                """,
                (user_id, int(row[0]), normalized_body),
            )
            appeal_id = int(cursor.lastrowid)
            result = appeal_result_type(appeal_id=appeal_id, created=True, status="open")
            conn.execute(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json)
                VALUES ('admin_appeal_created', ?, ?, ?)
                """,
                (str(appeal_id), f"admin:appeal-created:{appeal_id}", json.dumps({"appeal_id": appeal_id})),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id)
                VALUES ('appeal_created', 'telegram_user', ?, 'telegram_appeal', ?)
                """,
                (str(user_id), str(appeal_id)),
            )
        except sqlite3.IntegrityError:
            existing = conn.execute(
                """
                SELECT id, status FROM telegram_appeals
                WHERE telegram_user_id = ? AND status = 'open'
                ORDER BY id DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
            if existing is None:
                raise error_type("appeal could not be stored")
            return appeal_result_type(appeal_id=int(existing[0]), created=False, status=str(existing[1]))
    return result

def list_appeals(self, *, status: str = "open", limit: int = 100, error_type, appeal_item_type):
    if status not in {"open", "handled", "rejected", "all"}:
        raise error_type("appeal status is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise error_type("limit must be an integer from 1 to 200")
    where = "" if status == "all" else "WHERE a.status = ?"
    params: tuple[Any, ...] = (status, limit) if status != "all" else (limit,)
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.telegram_user_id, a.customer_id, c.email_display, a.body, a.status,
                   a.row_version, a.created_at, a.updated_at
            FROM telegram_appeals AS a
            JOIN customers AS c ON c.id = a.customer_id
            """
            + where
            + " ORDER BY a.created_at DESC, a.id DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        appeal_item_type(
            appeal_id=int(row[0]), telegram_user_id=int(row[1]), customer_id=int(row[2]),
            email_display=str(row[3]), body=str(row[4]), status=str(row[5]), row_version=int(row[6]),
            created_at=str(row[7]), updated_at=str(row[8]),
        )
        for row in rows
    ]

def resolve_appeal(
    self,
    *,
    appeal_id: int,
    expected_row_version: int,
    status: str,
    idempotency_key: str,
    resolved_by: str,
    positive_int,
    nonempty,
    payload_digest,
    error_type,
    idempotency_conflict_type,
    version_conflict_type,
    resolution_type,
):
    normalized_id = positive_int(appeal_id, "appeal_id")
    expected_version = positive_int(expected_row_version, "expected_row_version")
    if status not in {"handled", "rejected"}:
        raise error_type("appeal resolution status is invalid")
    key = nonempty(idempotency_key, "idempotency_key")
    actor = nonempty(resolved_by, "resolved_by")
    digest = payload_digest({"appeal_id": normalized_id, "expected_row_version": expected_version, "status": status})
    scope = "resolve_appeal"
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts WHERE scope = ? AND idempotency_key = ?",
            (scope, key),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise idempotency_conflict_type("idempotency key was already used for another command")
            return resolution_type(**json.loads(str(receipt[1])))
        row = conn.execute(
            "SELECT row_version, status FROM telegram_appeals WHERE id = ?", (normalized_id,)
        ).fetchone()
        if row is None:
            raise error_type("appeal was not found")
        if int(row[0]) != expected_version or str(row[1]) != "open":
            raise version_conflict_type("appeal was updated by another administrator")
        update = conn.execute(
            """
            UPDATE telegram_appeals
            SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'open' AND row_version = ?
            """,
            (status, normalized_id, expected_version),
        )
        if update.rowcount != 1:
            raise version_conflict_type("appeal was updated by another administrator")
        result = resolution_type(normalized_id, status, expected_version + 1)
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('appeal_resolved', 'admin', ?, 'telegram_appeal', ?, ?)
            """,
            (actor, str(normalized_id), digest),
        )
    return result

def begin_support_request(
    self, *, telegram_user_id: int, category: str, positive_int, support_categories, error_type
):
    """Remember one bounded support category without creating a ticket yet."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    if category not in support_categories:
        raise error_type("support category is invalid")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            """
            SELECT i.customer_id, i.access_status, c.status
            FROM telegram_identities AS i
            JOIN customers AS c ON c.id = i.customer_id
            WHERE i.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if identity is None or str(identity[1]) != "approved" or str(identity[2]) != "active":
            raise error_type("support is available only for an active customer")
        customer_id = int(identity[0])
        open_request = conn.execute(
            """
            SELECT 1 FROM telegram_support_requests
            WHERE customer_id = ? AND status IN ('open', 'read')
            """,
            (customer_id,),
        ).fetchone()
        if open_request is not None:
            raise error_type("an open support request already exists")
        conn.execute(
            """
            INSERT INTO telegram_user_drafts
                (telegram_user_id, action, customer_id, category)
            VALUES (?, 'support_request', ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                action = 'support_request', customer_id = excluded.customer_id,
                category = excluded.category, updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, customer_id, category),
        )

def submit_pending_support_request(
    self, *, telegram_user_id: int, body: str, positive_int, error_type, support_request_type
):
    """Create a ticket only from an explicit support draft and bounded text."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    normalized_body = body.strip()
    if not 1 <= len(normalized_body) <= 1000:
        raise error_type("support request body must contain 1 to 1000 characters")
    with connect(self._db_path) as conn:
        draft = conn.execute(
            """
            SELECT customer_id, category FROM telegram_user_drafts
            WHERE telegram_user_id = ? AND action = 'support_request'
            """,
            (user_id,),
        ).fetchone()
        if draft is None:
            return None
        customer_id, category = int(draft[0]), str(draft[1])
        identity = conn.execute(
            """
            SELECT i.customer_id, i.access_status, c.status
            FROM telegram_identities AS i
            JOIN customers AS c ON c.id = i.customer_id
            WHERE i.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if (
            identity is None
            or int(identity[0]) != customer_id
            or str(identity[1]) != "approved"
            or str(identity[2]) != "active"
        ):
            raise error_type("support is available only for an active customer")
        try:
            cursor = conn.execute(
                """
                INSERT INTO telegram_support_requests
                    (telegram_user_id, customer_id, category, body)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, customer_id, category, normalized_body),
            )
        except sqlite3.IntegrityError as exc:
            raise error_type("an open support request already exists") from exc
        request_id = int(cursor.lastrowid)
        conn.execute("DELETE FROM telegram_user_drafts WHERE telegram_user_id = ?", (user_id,))
        conn.execute(
            """
            INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
            VALUES ('admin_support_created', ?, ?)
            """,
            (str(request_id), f"admin:support-created:{request_id}"),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id)
            VALUES ('support_created', 'telegram_user', ?, 'telegram_support_request', ?)
            """,
            (str(user_id), str(request_id)),
        )
        row = conn.execute(
            """
            SELECT s.id, s.telegram_user_id, s.customer_id, c.email_display,
                   s.category, s.body, s.status, s.row_version, s.created_at,
                   s.updated_at, s.admin_response
            FROM telegram_support_requests AS s
            JOIN customers AS c ON c.id = s.customer_id
            WHERE s.id = ?
            """,
            (request_id,),
        ).fetchone()
    assert row is not None
    return support_request_type(
        support_request_id=int(row[0]), telegram_user_id=int(row[1]), customer_id=int(row[2]),
        email_display=str(row[3]), category=str(row[4]), body=str(row[5]), status=str(row[6]),
        row_version=int(row[7]), created_at=str(row[8]), updated_at=str(row[9]),
        admin_response=str(row[10]) if row[10] is not None else None,
    )

def list_support_requests(self, *, status: str = "open", limit: int = 100, error_type, support_request_type):
    if status not in {"open", "read", "resolved", "all"}:
        raise error_type("support request status is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise error_type("limit must be an integer from 1 to 200")
    where = "" if status == "all" else "WHERE s.status = ?"
    params: tuple[Any, ...] = (status, limit) if status != "all" else (limit,)
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.telegram_user_id, s.customer_id, c.email_display,
                   s.category, s.body, s.status, s.row_version, s.created_at,
                   s.updated_at, s.admin_response
            FROM telegram_support_requests AS s
            JOIN customers AS c ON c.id = s.customer_id
            """
            + where
            + " ORDER BY s.created_at DESC, s.id DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        support_request_type(
            support_request_id=int(row[0]), telegram_user_id=int(row[1]), customer_id=int(row[2]),
            email_display=str(row[3]), category=str(row[4]), body=str(row[5]), status=str(row[6]),
            row_version=int(row[7]), created_at=str(row[8]), updated_at=str(row[9]),
            admin_response=str(row[10]) if row[10] is not None else None,
        )
        for row in rows
    ]

def list_customer_support_requests(self, customer_id: int, *, limit: int = 20, positive_int, error_type, support_request_type):
    local_customer_id = positive_int(customer_id, "customer_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise error_type("limit must be an integer from 1 to 100")
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.telegram_user_id, s.customer_id, c.email_display,
                   s.category, s.body, s.status, s.row_version, s.created_at,
                   s.updated_at, s.admin_response
            FROM telegram_support_requests AS s
            JOIN customers AS c ON c.id = s.customer_id
            WHERE s.customer_id = ?
            ORDER BY s.created_at DESC, s.id DESC LIMIT ?
            """,
            (local_customer_id, limit),
        ).fetchall()
    return [
        support_request_type(
            support_request_id=int(row[0]), telegram_user_id=int(row[1]), customer_id=int(row[2]),
            email_display=str(row[3]), category=str(row[4]), body=str(row[5]), status=str(row[6]),
            row_version=int(row[7]), created_at=str(row[8]), updated_at=str(row[9]),
            admin_response=str(row[10]) if row[10] is not None else None,
        )
        for row in rows
    ]

def resolve_support_request(
    self,
    *,
    support_request_id: int,
    expected_row_version: int,
    response: str | None,
    idempotency_key: str,
    resolved_by: str,
    positive_int,
    nonempty,
    payload_digest,
    error_type,
    idempotency_conflict_type,
    version_conflict_type,
    resolution_type,
):
    request_id = positive_int(support_request_id, "support_request_id")
    expected_version = positive_int(expected_row_version, "expected_row_version")
    normalized_response = response.strip() if isinstance(response, str) else None
    if normalized_response is not None and not 1 <= len(normalized_response) <= 1000:
        raise error_type("support response must contain 1 to 1000 characters")
    key = nonempty(idempotency_key, "idempotency_key")
    actor = nonempty(resolved_by, "resolved_by")
    digest = payload_digest({
        "support_request_id": request_id, "expected_row_version": expected_version,
        "response": normalized_response,
    })
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'resolve_support_request' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise idempotency_conflict_type("idempotency key was already used for another command")
            return resolution_type(**json.loads(str(receipt[1])))
        row = conn.execute(
            "SELECT telegram_user_id, status, row_version FROM telegram_support_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if row is None or str(row[1]) not in {"open", "read"} or int(row[2]) != expected_version:
            raise version_conflict_type("support request was updated by another administrator")
        update = conn.execute(
            """
            UPDATE telegram_support_requests
            SET status = 'resolved', admin_response = ?, resolved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
            WHERE id = ? AND status IN ('open', 'read') AND row_version = ?
            """,
            (normalized_response, request_id, expected_version),
        )
        if update.rowcount != 1:
            raise version_conflict_type("support request was updated by another administrator")
        result = resolution_type(request_id, "resolved", expected_version + 1)
        conn.execute(
            """
            INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
            VALUES ('user_support_resolved', ?, ?)
            """,
            (str(request_id), f"user:support-resolved:{request_id}"),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('support_resolved', 'admin', ?, 'telegram_support_request', ?, ?)
            """,
            (actor, str(request_id), digest),
        )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES ('resolve_support_request', ?, ?, ?)
            """,
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result

