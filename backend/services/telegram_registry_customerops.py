"""Customer and administrator operations for the Telegram registry."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Iterable

from services.db_bootstrap import connect

CustomerListItem = Any
CustomerPage = Any
CustomerTelegramProfile = Any
CustomerAdminNote = Any
BroadcastQueueResult = Any
CustomerOperationPreview = Any
CustomerOperationTarget = Any
CustomerOperationQueueResult = Any
CustomerOperationAttemptStatus = Any
CustomerOperationStatus = Any
CustomerOperationRescheduleResult = Any
TelegramAdminDashboard = Any
CustomerTag = Any
TelegramSavedFilter = Any
CustomerTimelineEvent = Any
LifecycleSchedule = Any
BulkLifecyclePreviewItem = Any
BulkLifecyclePreview = Any
BulkLifecycleStatus = Any
BulkLifecycleItemStatus = Any

def list_customers(self, *, query: str='', status: str | None=None, page: int=1, page_size: int=50, include_deleted: bool=False, CustomerListItem=None, CustomerPage=None, TelegramRegistryError=None) -> CustomerPage:
    """Page local customers only; fleet discovery remains a separate safe workflow."""

    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise TelegramRegistryError("page must be a positive integer")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 200:
        raise TelegramRegistryError("page_size must be an integer from 1 to 200")
    allowed_statuses = {
        "active", "suspending", "suspended", "suspend_partial", "resuming", "resume_partial",
        "deleting", "delete_partial", "deleted", "conflict",
    }
    if status is not None and status not in allowed_statuses:
        raise TelegramRegistryError("customer status is invalid")
    if not isinstance(query, str) or len(query.strip()) > 128:
        raise TelegramRegistryError("query is invalid")
    filters: list[str] = []
    params: list[Any] = []
    if not include_deleted:
        filters.append("c.deleted_at IS NULL")
    if status is not None:
        filters.append("c.status = ?")
        params.append(status)
    if query.strip():
        like = f"%{query.strip().casefold()}%"
        filters.append(
            "(c.email_canonical LIKE ? OR EXISTS ("
            "SELECT 1 FROM telegram_identities AS ti WHERE ti.customer_id = c.id "
            "AND (CAST(ti.telegram_user_id AS TEXT) LIKE ? OR lower(COALESCE(ti.username, '')) LIKE ?)"
            "))"
        )
        params.extend([like, like, like])
    where = " WHERE " + " AND ".join(filters) if filters else ""
    base = (
        " FROM customers AS c "
        + where
    )
    with connect(self._db_path) as conn:
        total = int(conn.execute("SELECT COUNT(*)" + base, params).fetchone()[0])
        rows = conn.execute(
            """
            SELECT c.id, c.email_display, c.origin, c.status, c.row_version,
                   (SELECT telegram_user_id FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT username FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT first_name FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT last_name FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT COUNT(*) FROM customer_node_bindings AS b WHERE b.customer_id = c.id),
                   (SELECT lifetime_bytes FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                   (SELECT last_observed_at FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                   (SELECT a.introduction_text
                    FROM telegram_identities AS i
                    JOIN telegram_applications AS a
                      ON a.telegram_user_id = i.telegram_user_id
                     AND a.application_attempt = i.application_attempt
                    WHERE i.customer_id = c.id AND a.status = 'approved'
                      AND a.introduction_text IS NOT NULL
                    ORDER BY a.introduction_submitted_at DESC, a.id DESC LIMIT 1),
                   c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM telegram_support_requests AS tsr
                    WHERE tsr.customer_id = c.id AND tsr.status IN ('open', 'read'))
            """
            + base
            + " ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
        node_state_counts = self._customer_node_state_counts(conn, [int(row[0]) for row in rows])
    return CustomerPage(
        items=tuple(
            CustomerListItem(
                customer_id=int(row[0]), email_display=str(row[1]), origin=str(row[2]),
                status=str(row[3]), row_version=int(row[4]),
                telegram_user_id=int(row[5]) if row[5] is not None else None,
                telegram_username=str(row[6]) if row[6] is not None else None,
                telegram_first_name=str(row[7]) if row[7] is not None else None,
                telegram_last_name=str(row[8]) if row[8] is not None else None,
                node_count=int(row[9]),
                nodes_active=node_state_counts[int(row[0])]["active"],
                nodes_suspended=node_state_counts[int(row[0])]["suspended"],
                nodes_available=node_state_counts[int(row[0])]["available_to_add"],
                nodes_problem=node_state_counts[int(row[0])]["problem"],
                lifetime_bytes=int(row[10]) if row[10] is not None else None,
                traffic_observed_at=str(row[11]) if row[11] is not None else None,
                application_introduction=str(row[12]) if row[12] is not None else None,
                created_at=str(row[13]), updated_at=str(row[14]), open_support_count=int(row[15]),
            )
            for row in rows
        ),
        total=total,
        page=page,
        page_size=page_size,
    )

def get_customer(self, customer_id: int, *, CustomerListItem=None, TelegramRegistryError=None, _positive_int=None) -> CustomerListItem:
    normalized_customer_id = _positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT c.id, c.email_display, c.origin, c.status, c.row_version,
                   (SELECT telegram_user_id FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT username FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT first_name FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT last_name FROM telegram_identities AS ti
                    WHERE ti.customer_id = c.id
                    ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                   (SELECT COUNT(*) FROM customer_node_bindings AS b WHERE b.customer_id = c.id),
                   (SELECT lifetime_bytes FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                   (SELECT last_observed_at FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                   (SELECT a.introduction_text
                    FROM telegram_identities AS i
                    JOIN telegram_applications AS a
                      ON a.telegram_user_id = i.telegram_user_id
                     AND a.application_attempt = i.application_attempt
                    WHERE i.customer_id = c.id AND a.status = 'approved'
                      AND a.introduction_text IS NOT NULL
                    ORDER BY a.introduction_submitted_at DESC, a.id DESC LIMIT 1),
                   c.created_at, c.updated_at,
                   (SELECT COUNT(*) FROM telegram_support_requests AS tsr
                    WHERE tsr.customer_id = c.id AND tsr.status IN ('open', 'read'))
            FROM customers AS c
            WHERE c.id = ?
            """,
            (normalized_customer_id,),
        ).fetchone()
    if row is None:
        raise TelegramRegistryError("customer was not found")
    with connect(self._db_path) as conn:
        node_state_counts = self._customer_node_state_counts(conn, [normalized_customer_id])
    customer_counts = node_state_counts[normalized_customer_id]
    return CustomerListItem(
        customer_id=int(row[0]), email_display=str(row[1]), origin=str(row[2]), status=str(row[3]),
        row_version=int(row[4]), telegram_user_id=int(row[5]) if row[5] is not None else None,
        telegram_username=str(row[6]) if row[6] is not None else None,
        telegram_first_name=str(row[7]) if row[7] is not None else None,
        telegram_last_name=str(row[8]) if row[8] is not None else None,
        node_count=int(row[9]),
        nodes_active=customer_counts["active"],
        nodes_suspended=customer_counts["suspended"],
        nodes_available=customer_counts["available_to_add"],
        nodes_problem=customer_counts["problem"],
        lifetime_bytes=int(row[10]) if row[10] is not None else None,
        traffic_observed_at=str(row[11]) if row[11] is not None else None,
        application_introduction=str(row[12]) if row[12] is not None else None,
        created_at=str(row[13]), updated_at=str(row[14]), open_support_count=int(row[15]),
    )

def get_customer_telegram_profile(self, customer_id: int, *, CustomerTelegramProfile=None, TelegramRegistryError=None, _positive_int=None) -> CustomerTelegramProfile:
    """Return the one display-safe Telegram identity bound to a customer."""

    local_customer_id = _positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        customer_exists = conn.execute(
            "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if customer_exists is None:
            raise TelegramRegistryError("customer was not found")
        row = conn.execute(
            """
            SELECT telegram_user_id, username, first_name, last_name, phone_number
            FROM telegram_identities
            WHERE customer_id = ?
            ORDER BY access_status = 'approved' DESC, created_at ASC, telegram_user_id ASC
            LIMIT 1
            """,
            (local_customer_id,),
        ).fetchone()
    if row is None:
        return CustomerTelegramProfile(local_customer_id, None, None, None, None, None)
    return CustomerTelegramProfile(
        customer_id=local_customer_id,
        telegram_user_id=int(row[0]),
        username=str(row[1]) if row[1] is not None else None,
        first_name=str(row[2]) if row[2] is not None else None,
        last_name=str(row[3]) if row[3] is not None else None,
        phone_number=str(row[4]) if row[4] is not None else None,
    )

def get_customer_admin_note(self, customer_id: int, *, CustomerAdminNote=None, TelegramRegistryError=None, _positive_int=None) -> CustomerAdminNote | None:
    """Return the private override note without exposing it through public APIs."""

    local_customer_id = _positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        customer_exists = conn.execute(
            "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if customer_exists is None:
            raise TelegramRegistryError("customer was not found")
        row = conn.execute(
            """
            SELECT body, updated_by_telegram_user_id, updated_at
            FROM telegram_customer_notes
            WHERE customer_id = ?
            """,
            (local_customer_id,),
        ).fetchone()
    if row is None:
        return None
    return CustomerAdminNote(
        customer_id=local_customer_id,
        body=str(row[0]),
        updated_by_telegram_user_id=int(row[1]),
        updated_at=str(row[2]),
    )

def get_customer_registration_introduction(self, customer_id: int, *, TelegramRegistryError=None, _positive_int=None) -> str | None:
    """Return the approved registration text retained as the historical source."""

    local_customer_id = _positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        customer_exists = conn.execute(
            "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if customer_exists is None:
            raise TelegramRegistryError("customer was not found")
        row = conn.execute(
            """
            SELECT a.introduction_text
            FROM telegram_identities AS i
            JOIN telegram_applications AS a
              ON a.telegram_user_id = i.telegram_user_id
             AND a.application_attempt = i.application_attempt
            WHERE i.customer_id = ?
              AND a.status = 'approved'
              AND a.introduction_text IS NOT NULL
            ORDER BY a.introduction_submitted_at DESC, a.id DESC
            LIMIT 1
            """,
            (local_customer_id,),
        ).fetchone()
    return str(row[0]) if row is not None else None

def set_customer_admin_note(self, *, customer_id: int, body: str, updated_by_telegram_user_id: int, CustomerAdminNote=None, TelegramRegistryError=None, _payload_digest=None, _positive_int=None) -> CustomerAdminNote:
    """Create or replace an administrator-only customer note atomically."""

    local_customer_id = _positive_int(customer_id, "customer_id")
    admin_id = _positive_int(updated_by_telegram_user_id, "updated_by_telegram_user_id")
    normalized_body = body.strip() if isinstance(body, str) else ""
    if not 1 <= len(normalized_body) <= 1000:
        raise TelegramRegistryError("customer note must contain 1 to 1000 characters")
    with connect(self._db_path) as conn:
        customer_exists = conn.execute(
            "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if customer_exists is None:
            raise TelegramRegistryError("customer was not found")
        identity_exists = conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (admin_id,)
        ).fetchone()
        if identity_exists is None:
            raise TelegramRegistryError("note author was not found")
        conn.execute(
            """
            INSERT INTO telegram_customer_notes (customer_id, body, updated_by_telegram_user_id)
            VALUES (?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                body = excluded.body,
                updated_by_telegram_user_id = excluded.updated_by_telegram_user_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (local_customer_id, normalized_body, admin_id),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('customer_note_updated', 'admin', ?, 'customer', ?, ?)
            """,
            (str(admin_id), str(local_customer_id), _payload_digest({"body": normalized_body})),
        )
        row = conn.execute(
            """
            SELECT body, updated_by_telegram_user_id, updated_at
            FROM telegram_customer_notes WHERE customer_id = ?
            """,
            (local_customer_id,),
        ).fetchone()
    assert row is not None
    return CustomerAdminNote(
        customer_id=local_customer_id,
        body=str(row[0]),
        updated_by_telegram_user_id=int(row[1]),
        updated_at=str(row[2]),
    )

def _registered_broadcast_recipient_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT i.telegram_user_id
        FROM telegram_identities AS i
        JOIN customers AS c ON c.id = i.customer_id
        LEFT JOIN telegram_notification_preferences AS p ON p.telegram_user_id = i.telegram_user_id
        WHERE i.access_status = 'approved'
          AND c.deleted_at IS NULL
          AND c.status NOT IN ('deleting', 'delete_partial', 'deleted')
          AND COALESCE(p.background_notifications_enabled, 1) = 1
        ORDER BY i.telegram_user_id
        """
    ).fetchall()
    return [int(row[0]) for row in rows]

def registered_broadcast_recipient_count(self) -> int:
    with connect(self._db_path) as conn:
        return len(self._registered_broadcast_recipient_ids(conn))

def queue_admin_direct_message(self, *, customer_id: int, body: str, created_by: int | str, idempotency_key: str, photo_file_ids: tuple[str, ...] | None=None, TelegramRegistryError=None, _nonempty=None, _normalize_admin_message_body=None, _positive_int=None) -> int:
    """Queue one admin message to an already approved, live Telegram user."""

    local_customer_id = _positive_int(customer_id, "customer_id")
    if isinstance(created_by, bool):
        raise TelegramRegistryError("created_by is invalid")
    if isinstance(created_by, int):
        admin_id = str(_positive_int(created_by, "created_by"))
    elif isinstance(created_by, str):
        admin_id = _nonempty(created_by, "created_by")
    else:
        raise TelegramRegistryError("created_by is invalid")
    normalized_body = _normalize_admin_message_body(body)
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 180:
        raise TelegramRegistryError("idempotency key is invalid")
    if photo_file_ids and (len(photo_file_ids) > 10 or len(normalized_body) > 1024 or
                           any(not isinstance(item, str) or not item for item in photo_file_ids)):
        raise TelegramRegistryError("invalid direct message photos")
    photos_json = json.dumps(photo_file_ids, ensure_ascii=False) if photo_file_ids else None
    digest = hashlib.sha256((normalized_body + (photos_json or "")).encode("utf-8")).hexdigest()
    with connect(self._db_path) as conn:
        recipient = conn.execute(
            """
            SELECT i.telegram_user_id
            FROM telegram_identities AS i
            JOIN customers AS c ON c.id = i.customer_id
            WHERE c.id = ? AND c.deleted_at IS NULL AND c.status NOT IN ('deleting', 'delete_partial', 'deleted')
              AND i.access_status = 'approved'
            ORDER BY i.created_at ASC, i.telegram_user_id ASC
            LIMIT 1
            """,
            (local_customer_id,),
        ).fetchone()
        if recipient is None:
            raise TelegramRegistryError("customer has no active Telegram contact")
        recipient_id = int(recipient[0])
        cursor = conn.execute(
            """
            INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json)
            VALUES ('admin_direct_message', ?, ?, ?)
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            (str(recipient_id), f"admin-direct:{key}", json.dumps({"body": normalized_body, **({"photo_file_ids": photo_file_ids} if photo_file_ids else {})}, ensure_ascii=False)),
        )
        if cursor.rowcount == 0:
            row = conn.execute(
                "SELECT id FROM telegram_outbox WHERE dedupe_key = ?", (f"admin-direct:{key}",)
            ).fetchone()
            assert row is not None
            return int(row[0])
        outbox_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('admin_direct_message_queued', 'admin', ?, 'customer', ?, ?)
            """,
            (admin_id, str(local_customer_id), digest),
        )
    return outbox_id

def queue_registered_broadcast(self, *, body: str, created_by: int, idempotency_key: str, photo_file_ids: tuple[str, ...] | None=None, BroadcastQueueResult=None, TelegramRegistryError=None, _normalize_admin_message_body=None, _positive_int=None) -> BroadcastQueueResult:
    """Snapshot opted-in registered users into durable per-recipient outbox rows."""

    admin_id = _positive_int(created_by, "created_by")
    normalized_body = _normalize_admin_message_body(body)
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 180:
        raise TelegramRegistryError("idempotency key is invalid")
    if photo_file_ids and (len(photo_file_ids) > 10 or len(normalized_body) > 1024 or
                           any(not isinstance(item, str) or not item for item in photo_file_ids)):
        raise TelegramRegistryError("invalid broadcast photos")
    photos_json = json.dumps(photo_file_ids, ensure_ascii=False) if photo_file_ids else None
    digest = hashlib.sha256((normalized_body + (photos_json or "")).encode("utf-8")).hexdigest()
    with connect(self._db_path) as conn:
        recipient_ids = self._registered_broadcast_recipient_ids(conn)
        if not recipient_ids:
            raise TelegramRegistryError("no registered recipients are available")
        existing = conn.execute(
            "SELECT id, recipient_count FROM telegram_broadcast_jobs WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if existing is not None:
            return BroadcastQueueResult(int(existing[0]), int(existing[1]))
        cursor = conn.execute(
            """
            INSERT INTO telegram_broadcast_jobs (created_by, idempotency_key, body, recipient_count, photo_file_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (admin_id, key, normalized_body, len(recipient_ids), photos_json),
        )
        broadcast_id = int(cursor.lastrowid)
        conn.executemany(
            """
            INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
            VALUES ('registered_broadcast', ?, ?)
            """,
            [
                (f"{broadcast_id}:{recipient_id}", f"registered-broadcast:{broadcast_id}:{recipient_id}")
                for recipient_id in recipient_ids
            ],
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('registered_broadcast_queued', 'admin', ?, 'broadcast', ?, ?)
            """,
            (str(admin_id), str(broadcast_id), digest),
        )
    return BroadcastQueueResult(broadcast_id=broadcast_id, recipient_count=len(recipient_ids))

def _lifecycle_operation_type(value: str, *, TelegramRegistryError=None) -> str:
    if value not in {"suspend", "resume", "delete"}:
        raise TelegramRegistryError("unsupported customer lifecycle operation")
    return value

def _forget_missing_binding(conn, binding_id: int, *, actor_type: str, actor_id: str) -> bool:
    row = conn.execute(
        "SELECT customer_id, node_id, remote_email FROM customer_node_bindings "
        "WHERE id = ? AND management_state = 'missing'", (binding_id,),
    ).fetchone()
    if row is None or conn.execute(
        "SELECT 1 FROM telegram_customer_operation_attempts a "
        "JOIN telegram_customer_operations o ON o.id = a.operation_id "
        "WHERE a.binding_id = ? AND o.status IN ('queued', 'running', 'partial') "
        "AND o.dismissed_at IS NULL LIMIT 1", (binding_id,),
    ).fetchone():
        return False
    conn.execute("DELETE FROM telegram_customer_operation_attempts WHERE binding_id = ?", (binding_id,))
    conn.execute(
        "UPDATE telegram_drift_findings SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP, "
        "row_version = row_version + 1 WHERE customer_id = ? AND node_id = ? "
        "AND kind = 'binding_missing' AND status IN ('open', 'ignored') "
        "AND lower(remote_email) = lower(?)", (row[0], row[1], row[2] or ""),
    )
    conn.execute("DELETE FROM customer_node_bindings WHERE id = ?", (binding_id,))
    event = "drift_binding_auto_forgotten" if actor_type == "system" else "binding_forgotten"
    conn.execute(
        "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id) "
        "VALUES (?, ?, ?, 'customer_node_binding', ?)", (event, actor_type, actor_id, str(binding_id)),
    )
    return True

def forget_missing_bindings(self, customer_id: int, actor: str, *, TelegramRegistryError=None, _positive_int=None) -> dict[str, Any]:
    """Drop bindings marked 'missing' (client is gone from the panel and the admin does not want it back).

    Traffic totals live in separate ledgers keyed by customer/node, so nothing is lost; a client that
    reappears on the panel is found by the drift scan as an unknown remote client again.
    """
    customer_id = _positive_int(customer_id, "customer_id")
    forgotten: list[str] = []
    busy: list[str] = []
    with connect(self._db_path) as conn:
        if conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is None:
            raise TelegramRegistryError("customer was not found")
        rows = conn.execute(
            "SELECT b.id, b.node_id, b.remote_email, n.name FROM customer_node_bindings b "
            "JOIN nodes n ON n.id = b.node_id WHERE b.customer_id = ? AND b.management_state = 'missing'",
            (customer_id,),
        ).fetchall()
        for binding_id, node_id, remote_email, name in rows:
            if not self._forget_missing_binding(conn, binding_id, actor_type="admin", actor_id=str(actor)):
                busy.append(str(name))
                continue
            forgotten.append(str(name))
    return {"forgotten": forgotten, "busy": busy}

def repair_customer(self, customer_id: int, actor: str, *, INITIAL_JOB_COMPLETE_SQL=None, TelegramRegistryError=None, _fresh_snapshot_has_client=None, _positive_int=None) -> dict[str, Any]:
    customer_id = _positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        customer = conn.execute(
            "SELECT status, deleted_at FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if customer is None:
            raise TelegramRegistryError("customer was not found")
        problems: list[dict[str, Any]] = []
        identity = conn.execute(
            "SELECT remote_snapshot_ready FROM telegram_identities "
            "WHERE customer_id = ? AND access_status = 'approved' LIMIT 1", (customer_id,)
        ).fetchone()
        if customer[0] != 'active' or customer[1] is not None:
            problems.append({"code": "customer_inactive"})
        if identity is None:
            problems.append({"code": "identity_not_approved"})
        jobs = conn.execute(
            f"SELECT j.id, j.status FROM telegram_provisioning_jobs j WHERE j.customer_id = ? "
            f"AND j.trigger = 'approve_new' AND NOT {INITIAL_JOB_COMPLETE_SQL}", (customer_id,)
        ).fetchall()
        for job_id, status in jobs:
            problems.append({"code": "unfinished_job", "job_id": int(job_id), "status": str(status)})
        unresolved = conn.execute(
            """SELECT t.id FROM telegram_existing_discovery_jobs j
            JOIN telegram_existing_discovery_targets t ON t.job_id = j.id
            WHERE j.customer_id = ? AND (
                t.status IN ('pending', 'reconciling', 'deferred', 'blocked_after_retry_limit', 'conflict')
                OR (t.status = 'confirmed_absent' AND EXISTS (
                    SELECT 1 FROM telegram_provisioning_jobs p
                    WHERE p.id = t.provisioning_job_id AND p.status != 'succeeded'
                ))
            )""", (customer_id,)
        ).fetchall()
        for (target_id,) in unresolved:
            problems.append({"code": "unfinished_discovery", "target_id": int(target_id)})
        bindings = conn.execute(
            "SELECT b.management_state, n.name, b.id, b.node_id, b.remote_client_id, COALESCE(n.enabled, 1) "
            "FROM customer_node_bindings b "
            "JOIN nodes n ON n.id = b.node_id WHERE b.customer_id = ?", (customer_id,)
        ).fetchall()
        # Re-check missing bindings against a fresh node snapshot so the admin gets a real answer:
        # a client that is really gone is a note, not a repairable problem; one that is visible
        # again is left for the drift scan to confirm (it checks the full identity).
        notes: list[dict[str, Any]] = []
        resolved: list[tuple] = []
        for state, name, binding_id, node_id, remote_client_id, node_enabled in bindings:
            if state == 'missing':
                present = _fresh_snapshot_has_client(conn, int(node_id), str(remote_client_id or ""))
                if present is True:
                    # Not confirmed here: the drift scan verifies inbound, id, sub id and email together.
                    notes.append({"code": "binding_present", "node_name": str(name)})
                    state = 'present'
                elif present is False or (present is None and not node_enabled):
                    # A node taken out of service has no fresh snapshot: that is an expected note too.
                    notes.append({"code": "binding_absent", "node_name": str(name)})
                    state = 'absent'
            resolved.append((state, name))
        confirmed = any(row[0] == 'confirmed' for row in resolved)
        if not confirmed:
            problems.append({"code": "no_confirmed_binding"})
        for state, name in resolved:
            if state in ('missing', 'conflict'):
                problems.append({"code": 'binding_' + str(state), "node_name": str(name)})
        for operation_id, node_name in conn.execute(
            "SELECT DISTINCT o.id, n.name FROM telegram_customer_operations o "
            "LEFT JOIN telegram_customer_operation_attempts a ON a.operation_id = o.id "
            "LEFT JOIN nodes n ON n.id = a.node_id WHERE o.customer_id = ? "
            "AND o.status IN ('queued', 'running', 'partial') AND o.dismissed_at IS NULL",
            (customer_id,),
        ):
            problems.append({"code": "unfinished_operation", "operation_id": int(operation_id),
                             "node_name": str(node_name) if node_name is not None else None})
        changed = False
        if (customer[0] == 'active' and customer[1] is None and identity is not None
                and not jobs and not unresolved and confirmed):
            changed = bool(conn.execute(
                "UPDATE telegram_identities SET remote_snapshot_ready = 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE customer_id = ? AND access_status = 'approved' AND remote_snapshot_ready = 0",
                (customer_id,),
            ).rowcount)
            if changed:
                conn.execute(
                    "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id) "
                    "VALUES ('customer_repaired', 'admin', ?, 'customer', ?)", (str(actor), str(customer_id))
                )
        if identity is not None and not bool(identity[0]) and not changed:
            problems.append({"code": "snapshot_incomplete"})
    result: dict[str, Any] = {"fixed": ["remote_snapshot_ready"] if changed else [], "problems": problems}
    if notes:
        result["notes"] = notes
    return result

def _customer_operation_snapshot(self, conn: sqlite3.Connection, *, customer_id: int, operation_type: str, CustomerOperationPreview=None, CustomerOperationTarget=None, LifecycleUnavailableError=None, TelegramRegistryError=None, _payload_digest=None) -> tuple[CustomerOperationPreview, tuple[dict[str, Any], ...]]:
    """Build an exact, private target snapshot without doing remote I/O."""

    customer = conn.execute(
        "SELECT status, deleted_at, row_version FROM customers WHERE id = ?",
        (customer_id,),
    ).fetchone()
    if customer is None:
        raise TelegramRegistryError("customer was not found")
    current_status, deleted_at, row_version = str(customer[0]), customer[1], int(customer[2])
    remote_snapshot = conn.execute(
        "SELECT remote_snapshot_ready FROM telegram_identities "
        "WHERE customer_id = ? AND access_status = 'approved' ORDER BY telegram_user_id LIMIT 1",
        (customer_id,),
    ).fetchone()
    if remote_snapshot is not None and not bool(remote_snapshot[0]):
        raise LifecycleUnavailableError("customer remote snapshot is incomplete")
    unresolved = conn.execute(
        """SELECT 1 FROM telegram_existing_discovery_jobs AS j
            JOIN telegram_existing_discovery_targets AS t ON t.job_id = j.id
            WHERE j.customer_id = ? AND (
                t.status IN ('pending', 'reconciling', 'deferred', 'blocked_after_retry_limit', 'conflict')
                OR (t.status = 'confirmed_absent' AND EXISTS (
                    SELECT 1 FROM telegram_provisioning_jobs AS p
                    WHERE p.id = t.provisioning_job_id AND p.status != 'succeeded'
                ))
            ) LIMIT 1""",
        (customer_id,),
    ).fetchone()
    if unresolved is not None:
        raise LifecycleUnavailableError("customer remote snapshot remains degraded")
    if deleted_at is not None or current_status == "deleted":
        raise LifecycleUnavailableError("deleted customer cannot be changed")
    allowed_states = {
        "suspend": {"active", "resume_partial"},
        "resume": {"suspended", "suspend_partial", "resume_partial"},
        "delete": {"active", "suspended", "suspend_partial", "resume_partial"},
    }
    if current_status not in allowed_states[operation_type]:
        raise LifecycleUnavailableError("customer is busy or not in a compatible lifecycle state")

    rows = conn.execute(
        """
        SELECT b.id, b.node_id, n.name, b.inbound_id, b.remote_client_id, b.remote_sub_id,
               b.remote_email, b.management_state, b.desired_enabled, b.suspended_by_operation_id,
               b.last_enabled
        FROM customer_node_bindings AS b
        JOIN nodes AS n ON n.id = b.node_id
        WHERE b.customer_id = ?
        ORDER BY b.node_id, b.id
        """,
        (customer_id,),
    ).fetchall()

    targets: list[CustomerOperationTarget] = []
    private_targets: list[dict[str, Any]] = []
    blocked_binding_ids: list[int] = []
    for row in rows:
        binding_id, node_id, node_name, inbound_id = int(row[0]), int(row[1]), str(row[2]), int(row[3])
        remote_client_id = str(row[4]) if row[4] is not None else ""
        remote_sub_id = str(row[5]) if row[5] is not None else ""
        remote_email = str(row[6])
        management_state = str(row[7])
        suspended_by_operation_id = int(row[9]) if row[9] is not None else None

        # Disabled by hand on the panel (drift sync keeps last_enabled = 1): global resume re-enables it too.
        panel_disabled = (
            operation_type == "resume" and suspended_by_operation_id is None
            and not bool(row[8]) and row[10] == 1
        )
        if operation_type == "resume" and suspended_by_operation_id is None and not panel_disabled:
            continue
        if management_state != "confirmed" or not remote_client_id:
            blocked_binding_ids.append(binding_id)
            continue

        previous_enabled: bool | None = None
        if operation_type == "resume":
            previous = conn.execute(
                """
                SELECT a.previous_enabled
                FROM telegram_customer_operation_attempts AS a
                JOIN telegram_customer_operations AS o ON o.id = a.operation_id
                WHERE a.binding_id = ? AND o.operation_type = 'suspend'
                  AND a.action = 'set_enabled_false' AND a.status = 'succeeded'
                ORDER BY a.id DESC LIMIT 1
                """,
                (binding_id,),
            ).fetchone()
            if panel_disabled:
                previous = (1,)
            if previous is None or previous[0] is None:
                blocked_binding_ids.append(binding_id)
                continue
            previous_enabled = bool(previous[0])

        action = {
            "suspend": "set_enabled_false",
            "resume": "restore_previous_enabled",
            "delete": "delete_client",
        }[operation_type]
        targets.append(
            CustomerOperationTarget(
                binding_id=binding_id,
                node_id=node_id,
                node_name=node_name,
                inbound_id=inbound_id,
                action=action,
                previous_enabled=previous_enabled,
            )
        )
        private_targets.append(
            {
                "binding_id": binding_id,
                "node_id": node_id,
                "inbound_id": inbound_id,
                "remote_client_id": remote_client_id,
                "remote_sub_id": remote_sub_id,
                "remote_email": remote_email,
                "action": action,
                "previous_enabled": previous_enabled,
            }
        )

    snapshot = {
        "customer_id": customer_id,
        "operation_type": operation_type,
        "expected_customer_version": row_version,
        "targets": private_targets,
        "blocked_binding_ids": blocked_binding_ids,
    }
    return (
        CustomerOperationPreview(
            customer_id=customer_id,
            operation_type=operation_type,
            expected_customer_version=row_version,
            target_snapshot_digest=_payload_digest(snapshot),
            targets=tuple(targets),
            blocked_binding_ids=tuple(blocked_binding_ids),
        ),
        tuple(private_targets),
    )

def preview_customer_operation(self, *, customer_id: int, operation_type: str, CustomerOperationPreview=None, _positive_int=None) -> CustomerOperationPreview:
    normalized_customer_id = _positive_int(customer_id, "customer_id")
    normalized_operation = self._lifecycle_operation_type(operation_type)
    with connect(self._db_path) as conn:
        preview, _ = self._customer_operation_snapshot(
            conn, customer_id=normalized_customer_id, operation_type=normalized_operation
        )
    return preview

def _node_operation_type(value: str, *, TelegramRegistryError=None) -> str:
    if value not in {"suspend_node", "resume_node"}:
        raise TelegramRegistryError("unsupported customer node operation")
    return value

def _customer_node_operation_snapshot(self, conn: sqlite3.Connection, *, customer_id: int, node_id: int, operation_type: str, CustomerOperationPreview=None, CustomerOperationTarget=None, LifecycleUnavailableError=None, TelegramRegistryError=None, _payload_digest=None) -> tuple[CustomerOperationPreview, dict[str, Any]]:
    customer = conn.execute(
        "SELECT status, row_version FROM customers WHERE id = ? AND deleted_at IS NULL",
        (customer_id,),
    ).fetchone()
    if customer is None:
        raise TelegramRegistryError("customer was not found")
    if str(customer[0]) != "active":
        raise LifecycleUnavailableError("node operation requires an active customer")
    remote_snapshot = conn.execute(
        "SELECT remote_snapshot_ready FROM telegram_identities "
        "WHERE customer_id = ? AND access_status = 'approved' ORDER BY telegram_user_id LIMIT 1",
        (customer_id,),
    ).fetchone()
    if remote_snapshot is not None and not bool(remote_snapshot[0]):
        raise LifecycleUnavailableError("customer remote snapshot is incomplete")
    unresolved = conn.execute(
        """SELECT 1 FROM telegram_existing_discovery_jobs AS j
            JOIN telegram_existing_discovery_targets AS t ON t.job_id = j.id
            WHERE j.customer_id = ? AND (
                t.status IN ('pending', 'reconciling', 'deferred', 'blocked_after_retry_limit', 'conflict')
                OR (t.status = 'confirmed_absent' AND EXISTS (
                    SELECT 1 FROM telegram_provisioning_jobs AS p
                    WHERE p.id = t.provisioning_job_id AND p.status != 'succeeded'
                ))
            ) LIMIT 1""",
        (customer_id,),
    ).fetchone()
    if unresolved is not None:
        raise LifecycleUnavailableError("customer remote snapshot remains degraded")
    binding = conn.execute(
        """
        SELECT b.id, b.node_id, n.name, b.inbound_id, b.remote_client_id,
               b.remote_sub_id, b.remote_email, b.management_state,
               b.desired_enabled, b.suspended_by_operation_id, b.last_enabled
        FROM customer_node_bindings AS b
        JOIN nodes AS n ON n.id = b.node_id
        WHERE b.customer_id = ? AND b.node_id = ? AND b.inbound_id = 1
        """,
        (customer_id, node_id),
    ).fetchone()
    if binding is None:
        raise LifecycleUnavailableError("customer is not assigned to this node")
    if str(binding[7]) != "confirmed" or not binding[4]:
        raise LifecycleUnavailableError("node binding has no exact confirmed remote target")
    if operation_type == "suspend_node":
        if not bool(binding[8]):
            raise LifecycleUnavailableError("customer is already suspended on this node")
        action = "set_enabled_false"
        previous_enabled = None
    else:
        panel_disabled = not bool(binding[8]) and binding[9] is None and binding[10] == 1
        if bool(binding[8]) or (binding[9] is None and not panel_disabled):
            raise LifecycleUnavailableError("customer is not suspended by a node operation")
        previous = None if panel_disabled else conn.execute(
            """
            SELECT a.previous_enabled
            FROM telegram_customer_operation_attempts AS a
            JOIN telegram_customer_operations AS o ON o.id = a.operation_id
            WHERE a.binding_id = ? AND o.operation_type = 'suspend_node'
              AND a.action = 'set_enabled_false' AND a.status = 'succeeded'
            ORDER BY a.id DESC LIMIT 1
            """,
            (int(binding[0]),),
        ).fetchone()
        if panel_disabled:
            # Disabled by hand on the panel (drift sync recorded it as previously enabled): Resume re-enables.
            previous = (1,)
        if previous is None or previous[0] is None:
            raise LifecycleUnavailableError("suspend snapshot is unavailable")
        action = "restore_previous_enabled"
        previous_enabled = bool(previous[0])

    active_operation = conn.execute(
        """
        SELECT 1
        FROM telegram_customer_operations AS o
        JOIN telegram_customer_operation_attempts AS a ON a.operation_id = o.id
        WHERE o.customer_id = ? AND a.node_id = ?
          AND o.status IN ('queued', 'running', 'partial') AND o.dismissed_at IS NULL
        LIMIT 1
        """,
        (customer_id, node_id),
    ).fetchone()
    if active_operation is not None:
        raise LifecycleUnavailableError("this node already has an active operation")

    target = {
        "binding_id": int(binding[0]),
        "node_id": int(binding[1]),
        "inbound_id": int(binding[3]),
        "remote_client_id": str(binding[4]),
        "remote_sub_id": str(binding[5] or ""),
        "remote_email": str(binding[6]),
        "action": action,
        "previous_enabled": previous_enabled,
    }
    snapshot = {
        "customer_id": customer_id,
        "node_id": node_id,
        "operation_type": operation_type,
        "expected_customer_version": int(customer[1]),
        "target": target,
    }
    preview = CustomerOperationPreview(
        customer_id=customer_id,
        operation_type=operation_type,
        expected_customer_version=int(customer[1]),
        target_snapshot_digest=_payload_digest(snapshot),
        targets=(CustomerOperationTarget(
            binding_id=int(binding[0]), node_id=int(binding[1]), node_name=str(binding[2]),
            inbound_id=int(binding[3]), action=action, previous_enabled=previous_enabled,
        ),),
        blocked_binding_ids=(),
    )
    return preview, target

def preview_customer_node_operation(self, *, customer_id: int, node_id: int, operation_type: str, CustomerOperationPreview=None, _positive_int=None) -> CustomerOperationPreview:
    normalized_customer_id = _positive_int(customer_id, "customer_id")
    normalized_node_id = _positive_int(node_id, "node_id")
    normalized_operation = self._node_operation_type(operation_type)
    with connect(self._db_path) as conn:
        preview, _ = self._customer_node_operation_snapshot(
            conn, customer_id=normalized_customer_id, node_id=normalized_node_id,
            operation_type=normalized_operation,
        )
    return preview

def queue_customer_node_operation(self, *, customer_id: int, node_id: int, operation_type: str, expected_customer_version: int, target_snapshot_digest: str, idempotency_key: str, created_by: str, CustomerOperationQueueResult=None, IdempotencyConflictError=None, VersionConflictError=None, _nonempty=None, _payload_digest=None, _positive_int=None) -> CustomerOperationQueueResult:
    normalized_customer_id = _positive_int(customer_id, "customer_id")
    normalized_node_id = _positive_int(node_id, "node_id")
    normalized_operation = self._node_operation_type(operation_type)
    expected_version = _positive_int(expected_customer_version, "expected_customer_version")
    expected_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(created_by, "created_by")
    payload = {
        "customer_id": normalized_customer_id,
        "node_id": normalized_node_id,
        "operation_type": normalized_operation,
        "expected_customer_version": expected_version,
        "target_snapshot_digest": expected_digest,
    }
    digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'customer_node_operation' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return CustomerOperationQueueResult(**json.loads(str(receipt[1])))
        preview, target = self._customer_node_operation_snapshot(
            conn, customer_id=normalized_customer_id, node_id=normalized_node_id,
            operation_type=normalized_operation,
        )
        if preview.expected_customer_version != expected_version or preview.target_snapshot_digest != expected_digest:
            raise VersionConflictError("node operation preview is stale")
        update = conn.execute(
            "UPDATE customers SET row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND row_version = ? AND status = 'active' AND deleted_at IS NULL",
            (normalized_customer_id, expected_version),
        )
        if update.rowcount != 1:
            raise VersionConflictError("customer was updated by another operation")
        operation = conn.execute(
            """
            INSERT INTO telegram_customer_operations
                (customer_id, operation_type, status, target_snapshot_digest,
                 expected_customer_version, idempotency_key, created_by)
            VALUES (?, ?, 'queued', ?, ?, ?, ?)
            """,
            (normalized_customer_id, normalized_operation, expected_digest, expected_version, key, actor),
        )
        operation_id = int(operation.lastrowid)
        conn.execute(
            """
            INSERT INTO telegram_customer_operation_attempts
                (operation_id, binding_id, node_id, inbound_id, remote_client_id,
                 remote_sub_id, remote_email, action, previous_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id, target["binding_id"], target["node_id"], target["inbound_id"],
                target["remote_client_id"], target["remote_sub_id"], target["remote_email"],
                target["action"], int(target["previous_enabled"]) if target["previous_enabled"] is not None else None,
            ),
        )
        result = CustomerOperationQueueResult(
            operation_id=operation_id, customer_id=normalized_customer_id,
            operation_type=normalized_operation, status="queued", row_version=1,
        )
        conn.execute(
            "INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('customer_node_operation', ?, ?, ?)",
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
            """,
            (f"customer_{normalized_operation}_queued", actor, str(operation_id), digest),
        )
    return result

def _get_customer_operation_from_conn(self, conn: sqlite3.Connection, operation_id: int, *, CustomerOperationAttemptStatus=None, CustomerOperationStatus=None, TelegramRegistryError=None) -> CustomerOperationStatus:
    operation = conn.execute(
        """
        SELECT o.id, o.customer_id, c.email_display, o.operation_type, o.status, o.row_version,
               o.attempt_count, o.target_snapshot_digest, o.created_at, o.finished_at
        FROM telegram_customer_operations AS o
        JOIN customers AS c ON c.id = o.customer_id
        WHERE o.id = ?
        """,
        (operation_id,),
    ).fetchone()
    if operation is None:
        raise TelegramRegistryError("customer operation was not found")
    attempts = conn.execute(
        """
        SELECT a.binding_id, a.node_id, n.name, a.action, a.status, a.error_code,
               a.error_summary, a.attempt_count
        FROM telegram_customer_operation_attempts AS a
        JOIN nodes AS n ON n.id = a.node_id
        WHERE a.operation_id = ?
        ORDER BY a.node_id, a.id
        """,
        (operation_id,),
    ).fetchall()
    return CustomerOperationStatus(
        operation_id=int(operation[0]),
        customer_id=int(operation[1]),
        customer_email=str(operation[2]),
        operation_type=str(operation[3]),
        status=str(operation[4]),
        row_version=int(operation[5]),
        attempt_count=int(operation[6]),
        target_snapshot_digest=str(operation[7]),
        created_at=str(operation[8]),
        finished_at=str(operation[9]) if operation[9] is not None else None,
        attempts=tuple(
            CustomerOperationAttemptStatus(
                binding_id=int(row[0]), node_id=int(row[1]), node_name=str(row[2]),
                action=str(row[3]), status=str(row[4]),
                error_code=str(row[5]) if row[5] is not None else None,
                error_summary=str(row[6]) if row[6] is not None else None,
                attempt_count=int(row[7]),
            )
            for row in attempts
        ),
    )

def queue_customer_operation(self, *, customer_id: int, operation_type: str, expected_customer_version: int, target_snapshot_digest: str, idempotency_key: str, created_by: str, CustomerOperationQueueResult=None, IdempotencyConflictError=None, LifecycleUnavailableError=None, VersionConflictError=None, _nonempty=None, _payload_digest=None, _positive_int=None) -> CustomerOperationQueueResult:
    """Queue a lifecycle operation after proving its preview is still current.

    This transaction intentionally does not touch a node. A worker must later
    claim these immutable attempts, read the remote client, and reconcile
    before it writes anything.
    """

    normalized_customer_id = _positive_int(customer_id, "customer_id")
    normalized_operation = self._lifecycle_operation_type(operation_type)
    expected_version = _positive_int(expected_customer_version, "expected_customer_version")
    expected_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(created_by, "created_by")
    command_payload = {
        "customer_id": normalized_customer_id,
        "operation_type": normalized_operation,
        "expected_customer_version": expected_version,
        "target_snapshot_digest": expected_digest,
    }
    command_digest = _payload_digest(command_payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'customer_lifecycle' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != command_digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return CustomerOperationQueueResult(**json.loads(str(receipt[1])))

        preview, private_targets = self._customer_operation_snapshot(
            conn, customer_id=normalized_customer_id, operation_type=normalized_operation
        )
        if preview.expected_customer_version != expected_version:
            raise VersionConflictError("customer was updated by another operation")
        if preview.target_snapshot_digest != expected_digest:
            raise VersionConflictError("lifecycle target preview is stale")
        if preview.blocked_binding_ids:
            raise LifecycleUnavailableError("customer has bindings without an exact confirmed remote target")

        queued_status = "queued" if private_targets else "succeeded"
        next_customer_status = {
            "suspend": "suspending" if private_targets else "suspended",
            "resume": "resuming" if private_targets else "active",
            "delete": "deleting" if private_targets else "deleted",
        }[normalized_operation]
        if normalized_operation == "delete" and not private_targets:
            update = conn.execute(
                """
                UPDATE customers
                SET status = ?, deleted_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND deleted_at IS NULL
                """,
                (next_customer_status, normalized_customer_id, expected_version),
            )
        else:
            update = conn.execute(
                """
                UPDATE customers
                SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND deleted_at IS NULL
                """,
                (next_customer_status, normalized_customer_id, expected_version),
            )
        if update.rowcount != 1:
            raise VersionConflictError("customer was updated by another operation")

        cursor = conn.execute(
            """
            INSERT INTO telegram_customer_operations
                (customer_id, operation_type, status, target_snapshot_digest,
                 expected_customer_version, idempotency_key, created_by, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'succeeded' THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (
                normalized_customer_id, normalized_operation, queued_status,
                preview.target_snapshot_digest, expected_version, key, actor, queued_status,
            ),
        )
        operation_id = int(cursor.lastrowid)
        for target in private_targets:
            conn.execute(
                """
                INSERT INTO telegram_customer_operation_attempts
                    (operation_id, binding_id, node_id, inbound_id, remote_client_id, remote_sub_id,
                     remote_email, action, previous_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, target["binding_id"], target["node_id"], target["inbound_id"],
                    target["remote_client_id"], target["remote_sub_id"], target["remote_email"], target["action"],
                    int(target["previous_enabled"]) if target["previous_enabled"] is not None else None,
                ),
            )
        result = CustomerOperationQueueResult(
            operation_id=operation_id,
            customer_id=normalized_customer_id,
            operation_type=normalized_operation,
            status=queued_status,
            row_version=1,
        )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES ('customer_lifecycle', ?, ?, ?)
            """,
            (key, command_digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
            """,
            (f"customer_{normalized_operation}_queued", actor, str(operation_id), command_digest),
        )
    return result

def get_customer_operation(self, operation_id: int, *, CustomerOperationStatus=None, _positive_int=None) -> CustomerOperationStatus:
    normalized_operation_id = _positive_int(operation_id, "operation_id")
    with connect(self._db_path) as conn:
        return self._get_customer_operation_from_conn(conn, normalized_operation_id)

def list_customer_operations(self, *, customer_id: int, limit: int=100, CustomerOperationStatus=None, TelegramRegistryError=None, _positive_int=None) -> list[CustomerOperationStatus]:
    normalized_customer_id = _positive_int(customer_id, "customer_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    with connect(self._db_path) as conn:
        operation_ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM telegram_customer_operations WHERE customer_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (normalized_customer_id, limit),
            ).fetchall()
        ]
        return [self._get_customer_operation_from_conn(conn, operation_id) for operation_id in operation_ids]

def reschedule_customer_operation(self, *, operation_id: int, expected_operation_version: int, idempotency_key: str, requested_by: str, action: str, CustomerOperationRescheduleResult=None, IdempotencyConflictError=None, LifecycleUnavailableError=None, TelegramRegistryError=None, VersionConflictError=None, _nonempty=None, _payload_digest=None, _positive_int=None) -> CustomerOperationRescheduleResult:
    """Queue a read-first lifecycle retry; conflict targets require manual repair."""

    normalized_operation_id = _positive_int(operation_id, "operation_id")
    expected_version = _positive_int(expected_operation_version, "expected_operation_version")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(requested_by, "requested_by")
    if action not in {"retry", "reconcile", "dismiss"}:
        raise TelegramRegistryError("unsupported customer operation action")
    dismiss = action == "dismiss"
    payload = {
        "operation_id": normalized_operation_id,
        "expected_operation_version": expected_version,
    }
    digest = _payload_digest(payload)
    scope = f"customer_operation_{action}"
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = ? AND idempotency_key = ?",
            (scope, key),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return CustomerOperationRescheduleResult(**json.loads(str(receipt[1])))
        operation = conn.execute(
            "SELECT status, row_version, lease_until, dismissed_at FROM telegram_customer_operations WHERE id = ?",
            (normalized_operation_id,),
        ).fetchone()
        if operation is None:
            raise TelegramRegistryError("customer operation was not found")
        if int(operation[1]) != expected_version:
            raise VersionConflictError("customer operation was updated by another worker or administrator")
        if str(operation[0]) not in {"partial", "failed"} or operation[2] is not None or operation[3] is not None:
            raise VersionConflictError("customer operation cannot be rescheduled in its current state")
        if dismiss:
            # No status means "abandoned"; hide it from the attention list but keep the history.
            update = conn.execute(
                """
                UPDATE telegram_customer_operations
                SET dismissed_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND lease_until IS NULL
                """,
                (normalized_operation_id, expected_version),
            )
        else:
            changed = conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = 'pending', error_code = NULL, error_summary = NULL, next_attempt_at = NULL,
                    finished_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE operation_id = ? AND status IN ('failed', 'blocked', 'ambiguous', 'missing')
                """,
                (normalized_operation_id,),
            )
            if changed.rowcount == 0:
                raise LifecycleUnavailableError("customer operation has no safe retryable attempts")
            update = conn.execute(
                """
                UPDATE telegram_customer_operations
                SET status = 'queued', next_attempt_at = NULL, finished_at = NULL,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND lease_until IS NULL
                """,
                (normalized_operation_id, expected_version),
            )
        if update.rowcount != 1:
            raise VersionConflictError("customer operation was updated by another worker or administrator")
        result = CustomerOperationRescheduleResult(
            operation_id=normalized_operation_id,
            status=str(operation[0]) if dismiss else "queued",
            row_version=expected_version + 1,
        )
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
            VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
            """,
            ("customer_operation_dismissed" if dismiss else f"customer_operation_{action}_queued",
             actor, str(normalized_operation_id), digest),
        )
    return result

def get_admin_dashboard(self, *, TelegramAdminDashboard=None) -> TelegramAdminDashboard:
    """Return only local operational counts; never probes a node."""

    with connect(self._db_path) as conn:
        def count(sql: str, parameters: tuple[Any, ...] = ()) -> int:
            row = conn.execute(sql, parameters).fetchone()
            return int(row[0]) if row is not None else 0

        return TelegramAdminDashboard(
            pending_requests=count("SELECT COUNT(*) FROM telegram_identities WHERE access_status = 'pending'"),
            active_customers=count("SELECT COUNT(*) FROM customers WHERE status = 'active' AND deleted_at IS NULL"),
            suspended_customers=count("SELECT COUNT(*) FROM customers WHERE status = 'suspended' AND deleted_at IS NULL"),
            lifecycle_attention=count(
                "SELECT COUNT(*) FROM telegram_customer_operations "
                "WHERE status IN ('partial', 'failed', 'running') AND dismissed_at IS NULL"
            ),
            provisioning_attention=count(
                "SELECT COUNT(*) FROM telegram_provisioning_jobs "
                "WHERE status IN ('partial', 'failed', 'running')"
            ),
            open_appeals=count("SELECT COUNT(*) FROM telegram_appeals WHERE status = 'open'"),
            open_support_requests=count(
                "SELECT COUNT(*) FROM telegram_support_requests WHERE status IN ('open', 'read')"
            ),
            open_drift_findings=count("SELECT COUNT(*) FROM telegram_drift_findings WHERE status = 'open'"),
            scheduled_lifecycle_actions=count(
                "SELECT COUNT(*) FROM telegram_lifecycle_schedules WHERE status = 'scheduled'"
            ),
        )

def list_attention_items(self, *, limit: int=100, TelegramRegistryError=None) -> dict[str, list[Any]]:
    """Jobs and lifecycle operations counted by get_admin_dashboard, so the UI can act on them."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    with connect(self._db_path) as conn:
        def ids(table: str, extra: str = "") -> list[int]:
            return [int(row[0]) for row in conn.execute(
                f"SELECT id FROM {table} WHERE status IN ('partial', 'failed', 'running'){extra} "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]
        operation_ids = ids("telegram_customer_operations", " AND dismissed_at IS NULL")
        lifecycle = [self._get_customer_operation_from_conn(conn, i) for i in operation_ids]
        job_ids = ids("telegram_provisioning_jobs")
    return {
        "provisioning": [self.get_provisioning_job(i) for i in job_ids],
        "lifecycle": lifecycle,
    }

def list_customer_tags(self, customer_id: int, *, CustomerTag=None, _positive_int=None) -> tuple[CustomerTag, ...]:
    local_customer_id = _positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        rows = conn.execute(
            "SELECT customer_id, tag FROM telegram_customer_tags WHERE customer_id = ? ORDER BY tag",
            (local_customer_id,),
        ).fetchall()
    return tuple(CustomerTag(customer_id=int(row[0]), tag=str(row[1])) for row in rows)

def set_customer_tags(self, *, customer_id: int, tags: object, updated_by: str, CustomerTag=None, TelegramRegistryError=None, _nonempty=None, _normalize_tags=None, _payload_digest=None, _positive_int=None) -> tuple[CustomerTag, ...]:
    local_customer_id = _positive_int(customer_id, "customer_id")
    normalized_tags = _normalize_tags(tags)
    actor = _nonempty(updated_by, "updated_by")
    with connect(self._db_path) as conn:
        customer = conn.execute(
            "SELECT 1 FROM customers WHERE id = ? AND deleted_at IS NULL", (local_customer_id,)
        ).fetchone()
        if customer is None:
            raise TelegramRegistryError("customer was not found")
        conn.execute("DELETE FROM telegram_customer_tags WHERE customer_id = ?", (local_customer_id,))
        conn.executemany(
            "INSERT INTO telegram_customer_tags(customer_id, tag, created_by) VALUES (?, ?, ?)",
            [(local_customer_id, tag, actor) for tag in normalized_tags],
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('customer_tags_updated', 'admin', ?, 'customer', ?, ?)
            """,
            (actor, str(local_customer_id), _payload_digest({"tags": normalized_tags})),
        )
    return tuple(CustomerTag(customer_id=local_customer_id, tag=tag) for tag in normalized_tags)

def list_saved_filters(self, *, admin_username: str, TelegramRegistryError=None, TelegramSavedFilter=None, _nonempty=None, _normalize_tags=None) -> tuple[TelegramSavedFilter, ...]:
    actor = _nonempty(admin_username, "admin_username")
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, name, query, status, tags_json, updated_at
            FROM telegram_admin_saved_filters
            WHERE admin_username = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (actor,),
        ).fetchall()
    result: list[TelegramSavedFilter] = []
    for row in rows:
        try:
            tags = _normalize_tags(json.loads(str(row[4])))
        except (ValueError, TypeError, json.JSONDecodeError, TelegramRegistryError):
            tags = ()
        result.append(TelegramSavedFilter(
            filter_id=int(row[0]), name=str(row[1]), query=str(row[2]),
            status=str(row[3]) if row[3] is not None else None,
            tags=tags, updated_at=str(row[5]),
        ))
    return tuple(result)

def save_filter(self, *, admin_username: str, name: object, query: object, status: object, tags: object, TelegramRegistryError=None, TelegramSavedFilter=None, _nonempty=None, _normalize_tags=None) -> TelegramSavedFilter:
    actor = _nonempty(admin_username, "admin_username")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise TelegramRegistryError("filter name must contain 1 to 80 characters")
    if not isinstance(query, str) or len(query.strip()) > 160:
        raise TelegramRegistryError("filter query must contain at most 160 characters")
    normalized_status = status.strip() if isinstance(status, str) else None
    allowed_statuses = {
        "active", "suspending", "suspended", "suspend_partial", "resuming", "resume_partial",
        "deleting", "delete_partial", "deleted", "conflict",
    }
    if normalized_status == "":
        normalized_status = None
    if normalized_status not in allowed_statuses and normalized_status is not None:
        raise TelegramRegistryError("filter status is invalid")
    normalized_tags = _normalize_tags(tags)
    normalized_name = unicodedata.normalize("NFKC", name).strip()
    normalized_query = unicodedata.normalize("NFKC", query).strip()
    tags_json = json.dumps(normalized_tags, ensure_ascii=False, separators=(",", ":"))
    with connect(self._db_path) as conn:
        conn.execute(
            """
            INSERT INTO telegram_admin_saved_filters(admin_username, name, query, status, tags_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(admin_username, name) DO UPDATE SET
                query = excluded.query, status = excluded.status, tags_json = excluded.tags_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (actor, normalized_name, normalized_query, normalized_status, tags_json),
        )
        row = conn.execute(
            """
            SELECT id, name, query, status, tags_json, updated_at
            FROM telegram_admin_saved_filters WHERE admin_username = ? AND name = ?
            """,
            (actor, normalized_name),
        ).fetchone()
    assert row is not None
    return TelegramSavedFilter(
        filter_id=int(row[0]), name=str(row[1]), query=str(row[2]),
        status=str(row[3]) if row[3] is not None else None,
        tags=normalized_tags, updated_at=str(row[5]),
    )

def delete_saved_filter(self, *, admin_username: str, filter_id: int, TelegramRegistryError=None, _nonempty=None, _positive_int=None) -> None:
    actor = _nonempty(admin_username, "admin_username")
    normalized_filter_id = _positive_int(filter_id, "filter_id")
    with connect(self._db_path) as conn:
        deleted = conn.execute(
            "DELETE FROM telegram_admin_saved_filters WHERE id = ? AND admin_username = ?",
            (normalized_filter_id, actor),
        )
        if deleted.rowcount != 1:
            raise TelegramRegistryError("saved filter was not found")

def customer_timeline(self, *, customer_id: int, limit: int=100, CustomerTimelineEvent=None, TelegramRegistryError=None, _positive_int=None) -> tuple[CustomerTimelineEvent, ...]:
    local_customer_id = _positive_int(customer_id, "customer_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    with connect(self._db_path) as conn:
        exists = conn.execute("SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)).fetchone()
        if exists is None:
            raise TelegramRegistryError("customer was not found")
        rows = conn.execute(
            """
            SELECT event_type, entity_type, entity_id, created_at, actor_type, actor_id, status
            FROM (
                SELECT event_type, entity_type, entity_id, created_at, actor_type, actor_id, NULL AS status
                FROM telegram_audit_log
                WHERE (entity_type = 'customer' AND entity_id = ?)
                   OR (entity_type = 'customer_operation' AND entity_id IN (
                       SELECT CAST(id AS TEXT) FROM telegram_customer_operations WHERE customer_id = ?
                   ))
                UNION ALL
                SELECT 'lifecycle:' || operation_type, 'customer_operation', CAST(id AS TEXT),
                       updated_at, 'system', NULL, status
                FROM telegram_customer_operations WHERE customer_id = ?
                UNION ALL
                SELECT 'provisioning:' || trigger, 'provisioning_job', CAST(id AS TEXT),
                       created_at, 'system', NULL, status
                FROM telegram_provisioning_jobs WHERE customer_id = ?
            ) ORDER BY created_at DESC LIMIT ?
            """,
            (str(local_customer_id), local_customer_id, local_customer_id, local_customer_id, limit),
        ).fetchall()
    return tuple(CustomerTimelineEvent(
        event_type=str(row[0]), entity_type=str(row[1]), entity_id=str(row[2]), created_at=str(row[3]),
        actor_type=str(row[4]) if row[4] is not None else None,
        actor_id=str(row[5]) if row[5] is not None else None,
        status=str(row[6]) if row[6] is not None else None,
    ) for row in rows)

def get_customer_read_only_view(self, customer_id: int, *, initial_job_incomplete=None) -> dict[str, Any]:
    """A no-token projection of what the linked person can currently see."""

    customer = self.get_customer(customer_id)
    profile = self.get_customer_telegram_profile(customer.customer_id)
    with connect(self._db_path) as conn:
        initial_ready = not initial_job_incomplete(conn, customer.customer_id)
    return {
        "customer_id": customer.customer_id,
        "identity_linked": profile.telegram_user_id is not None,
        "identity_access_status": "approved" if profile.telegram_user_id is not None else None,
        "customer_status": customer.status,
        "connection_available": customer.status == "active" and initial_ready,
        "connection_reason": None if customer.status == "active" and initial_ready else (
            "initial_provisioning" if not initial_ready else "lifecycle"
        ),
        "token_revealed": False,
    }

def create_lifecycle_schedule(self, *, customer_id: int, operation_type: object, execute_not_before: object, expected_customer_version: int, target_snapshot_digest: str, idempotency_key: str, created_by: str, IdempotencyConflictError=None, LifecycleSchedule=None, LifecycleUnavailableError=None, TelegramRegistryError=None, VersionConflictError=None, _nonempty=None, _parse_future_timestamp=None, _payload_digest=None, _positive_int=None) -> LifecycleSchedule:
    """Store a cancellable grace-period command, without touching a node."""

    local_customer_id = _positive_int(customer_id, "customer_id")
    if operation_type not in {"suspend", "delete"}:
        raise TelegramRegistryError("only suspend and delete may be scheduled")
    expected_version = _positive_int(expected_customer_version, "expected_customer_version")
    expected_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
    execute_at = _parse_future_timestamp(execute_not_before, "execute_not_before")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(created_by, "created_by")
    payload = {
        "customer_id": local_customer_id, "operation_type": operation_type,
        "expected_customer_version": expected_version, "target_snapshot_digest": expected_digest,
        "execute_not_before": execute_at,
    }
    payload_digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'lifecycle_schedule' AND idempotency_key = ?", (key,)
        ).fetchone()
        if receipt is not None:
            if str(receipt[0]) != payload_digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return LifecycleSchedule(**json.loads(str(receipt[1])))
        preview, _targets = self._customer_operation_snapshot(
            conn, customer_id=local_customer_id, operation_type=str(operation_type)
        )
        if preview.expected_customer_version != expected_version or preview.target_snapshot_digest != expected_digest:
            raise VersionConflictError("lifecycle target preview is stale")
        if preview.blocked_binding_ids:
            raise LifecycleUnavailableError("customer has bindings without an exact confirmed remote target")
        cursor = conn.execute(
            """
            INSERT INTO telegram_lifecycle_schedules
                (customer_id, operation_type, expected_customer_version, target_snapshot_digest,
                 execute_not_before, idempotency_key, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (local_customer_id, operation_type, expected_version, expected_digest, execute_at, key, actor),
        )
        schedule = LifecycleSchedule(
            schedule_id=int(cursor.lastrowid), customer_id=local_customer_id,
            customer_email=self.get_customer(local_customer_id).email_display,
            operation_type=str(operation_type), expected_customer_version=expected_version,
            target_snapshot_digest=expected_digest, execute_not_before=execute_at,
            status="scheduled", row_version=1, operation_id=None, created_at="",
        )
        created_at = conn.execute(
            "SELECT created_at FROM telegram_lifecycle_schedules WHERE id = ?", (schedule.schedule_id,)
        ).fetchone()
        assert created_at is not None
        schedule = LifecycleSchedule(**{**asdict(schedule), "created_at": str(created_at[0])})
        conn.execute(
            "INSERT INTO telegram_command_receipts(scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('lifecycle_schedule', ?, ?, ?)",
            (key, payload_digest, json.dumps(asdict(schedule), separators=(",", ":"))),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('customer_lifecycle_scheduled', 'admin', ?, 'customer', ?, ?)
            """,
            (actor, str(local_customer_id), payload_digest),
        )
    return schedule

def _schedule_from_row(self, row: tuple[Any, ...], *, LifecycleSchedule=None) -> LifecycleSchedule:
    return LifecycleSchedule(
        schedule_id=int(row[0]), customer_id=int(row[1]), customer_email=str(row[2]),
        operation_type=str(row[3]), expected_customer_version=int(row[4]),
        target_snapshot_digest=str(row[5]), execute_not_before=str(row[6]), status=str(row[7]),
        row_version=int(row[8]), operation_id=int(row[9]) if row[9] is not None else None,
        created_at=str(row[10]),
    )

def list_lifecycle_schedules(self, *, customer_id: int | None=None, status: str='all', limit: int=100, LifecycleSchedule=None, TelegramRegistryError=None, _positive_int=None) -> tuple[LifecycleSchedule, ...]:
    if status not in {"all", "scheduled", "activating", "queued", "cancelled", "stale", "failed"}:
        raise TelegramRegistryError("schedule status is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    where: list[str] = []
    values: list[Any] = []
    if customer_id is not None:
        where.append("s.customer_id = ?")
        values.append(_positive_int(customer_id, "customer_id"))
    if status != "all":
        where.append("s.status = ?")
        values.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    values.append(limit)
    with connect(self._db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT s.id, s.customer_id, c.email_display, s.operation_type, s.expected_customer_version,
                   s.target_snapshot_digest, s.execute_not_before, s.status, s.row_version,
                   s.operation_id, s.created_at
            FROM telegram_lifecycle_schedules AS s
            JOIN customers AS c ON c.id = s.customer_id
            {clause}
            ORDER BY s.execute_not_before DESC, s.id DESC LIMIT ?
            """,
            tuple(values),
        ).fetchall()
    return tuple(self._schedule_from_row(row) for row in rows)

def cancel_lifecycle_schedule(self, *, schedule_id: int, expected_row_version: int, cancelled_by: str, reason: object=None, LifecycleSchedule=None, VersionConflictError=None, _nonempty=None, _payload_digest=None, _positive_int=None) -> LifecycleSchedule:
    local_schedule_id = _positive_int(schedule_id, "schedule_id")
    expected_version = _positive_int(expected_row_version, "expected_row_version")
    actor = _nonempty(cancelled_by, "cancelled_by")
    normalized_reason = str(reason).strip()[:240] if reason is not None else None
    with connect(self._db_path) as conn:
        updated = conn.execute(
            """
            UPDATE telegram_lifecycle_schedules
            SET status = 'cancelled', cancel_reason = ?, row_version = row_version + 1,
                lease_owner = NULL, lease_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'scheduled' AND row_version = ?
            """,
            (normalized_reason or None, local_schedule_id, expected_version),
        )
        if updated.rowcount != 1:
            raise VersionConflictError("schedule is no longer cancellable")
        row = conn.execute(
            """
            SELECT s.id, s.customer_id, c.email_display, s.operation_type, s.expected_customer_version,
                   s.target_snapshot_digest, s.execute_not_before, s.status, s.row_version,
                   s.operation_id, s.created_at
            FROM telegram_lifecycle_schedules AS s JOIN customers AS c ON c.id = s.customer_id
            WHERE s.id = ?
            """,
            (local_schedule_id,),
        ).fetchone()
        assert row is not None
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('customer_lifecycle_schedule_cancelled', 'admin', ?, 'customer_schedule', ?, ?)
            """,
            (actor, str(local_schedule_id), _payload_digest({"reason": normalized_reason or ""})),
        )
    return self._schedule_from_row(row)

def claim_due_lifecycle_schedule(self, *, worker_id: str, now: datetime | None=None, lease_seconds: int=60, LifecycleSchedule=None, TelegramRegistryError=None, _nonempty=None, _timestamp=None, _utc_now=None) -> LifecycleSchedule | None:
    actor = _nonempty(worker_id, "worker_id")
    if lease_seconds <= 0:
        raise TelegramRegistryError("lease_seconds must be positive")
    current = _timestamp(now or _utc_now())
    lease_until = _timestamp((now or _utc_now()) + timedelta(seconds=lease_seconds))
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT s.id, s.customer_id, c.email_display, s.operation_type, s.expected_customer_version,
                   s.target_snapshot_digest, s.execute_not_before, s.status, s.row_version,
                   s.operation_id, s.created_at
            FROM telegram_lifecycle_schedules AS s JOIN customers AS c ON c.id = s.customer_id
            WHERE s.status IN ('scheduled', 'activating') AND s.execute_not_before <= ?
              AND (s.lease_until IS NULL OR s.lease_until < ?)
            ORDER BY s.execute_not_before, s.id LIMIT 1
            """,
            (current, current),
        ).fetchone()
        if row is None:
            return None
        claimed = conn.execute(
            """
            UPDATE telegram_lifecycle_schedules
            SET status = 'activating', lease_owner = ?, lease_until = ?,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('scheduled', 'activating')
              AND (lease_until IS NULL OR lease_until < ?)
            """,
            (actor, lease_until, int(row[0]), current),
        )
        if claimed.rowcount != 1:
            return None
        row = list(row)
        row[7] = "activating"
        row[8] = int(row[8]) + 1
    return self._schedule_from_row(tuple(row))

def complete_lifecycle_schedule(self, *, schedule_id: int, operation_id: int | None, outcome: str, TelegramRegistryError=None, VersionConflictError=None, _positive_int=None) -> None:
    if outcome not in {"queued", "stale", "failed"}:
        raise TelegramRegistryError("schedule outcome is invalid")
    with connect(self._db_path) as conn:
        updated = conn.execute(
            """
            UPDATE telegram_lifecycle_schedules
            SET status = ?, operation_id = ?, lease_owner = NULL, lease_until = NULL,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'activating'
            """,
            (outcome, operation_id, _positive_int(schedule_id, "schedule_id")),
        )
        if updated.rowcount != 1:
            raise VersionConflictError("schedule completion lost its lease")

def _bulk_preview_digest(operation_type: str, items: Iterable[BulkLifecyclePreviewItem], *, BulkLifecyclePreviewItem=None, _payload_digest=None) -> str:
    return _payload_digest({
        "operation_type": operation_type,
        "items": [
            {
                "customer_id": item.customer_id,
                "expected_customer_version": item.expected_customer_version,
                "target_snapshot_digest": item.target_snapshot_digest,
            }
            for item in sorted(items, key=lambda item: item.customer_id)
        ],
    })

def preview_bulk_customer_operations(self, *, customer_ids: object, operation_type: object, BulkLifecyclePreview=None, BulkLifecyclePreviewItem=None, LifecycleUnavailableError=None, TelegramRegistryError=None, _positive_int=None) -> BulkLifecyclePreview:
    if operation_type not in {"suspend", "resume", "delete"}:
        raise TelegramRegistryError("bulk operation is invalid")
    if not isinstance(customer_ids, (list, tuple)):
        raise TelegramRegistryError("customer_ids must be a list")
    normalized_ids = tuple(sorted({_positive_int(value, "customer_id") for value in customer_ids}))
    if not 1 <= len(normalized_ids) <= 100:
        raise TelegramRegistryError("bulk preview requires 1 to 100 customers")
    with connect(self._db_path) as conn:
        items: list[BulkLifecyclePreviewItem] = []
        for customer_id in normalized_ids:
            preview, _targets = self._customer_operation_snapshot(
                conn, customer_id=customer_id, operation_type=str(operation_type)
            )
            if preview.blocked_binding_ids:
                raise LifecycleUnavailableError(
                    f"customer {customer_id} has bindings without an exact confirmed remote target"
                )
            email = conn.execute("SELECT email_display FROM customers WHERE id = ?", (customer_id,)).fetchone()
            assert email is not None
            items.append(BulkLifecyclePreviewItem(
                customer_id=customer_id, customer_email=str(email[0]),
                expected_customer_version=preview.expected_customer_version,
                target_snapshot_digest=preview.target_snapshot_digest,
                target_count=len(preview.targets),
            ))
    return BulkLifecyclePreview(
        operation_type=str(operation_type),
        target_snapshot_digest=self._bulk_preview_digest(str(operation_type), items),
        items=tuple(items),
    )

def _parse_bulk_preview_items(values: object, *, BulkLifecyclePreviewItem=None, TelegramRegistryError=None, _nonempty=None, _positive_int=None) -> tuple[BulkLifecyclePreviewItem, ...]:
    if not isinstance(values, list) or not values:
        raise TelegramRegistryError("bulk preview items are required")
    items: list[BulkLifecyclePreviewItem] = []
    seen: set[int] = set()
    for value in values:
        if not isinstance(value, dict):
            raise TelegramRegistryError("bulk preview item is invalid")
        customer_id = _positive_int(value.get("customer_id"), "customer_id")
        if customer_id in seen:
            raise TelegramRegistryError("bulk preview contains a duplicate customer")
        seen.add(customer_id)
        version = _positive_int(value.get("expected_customer_version"), "expected_customer_version")
        digest = _nonempty(value.get("target_snapshot_digest"), "target_snapshot_digest")
        items.append(BulkLifecyclePreviewItem(
            customer_id=customer_id, customer_email="", expected_customer_version=version,
            target_snapshot_digest=digest, target_count=0,
        ))
    if len(items) > 100:
        raise TelegramRegistryError("bulk preview may contain at most 100 customers")
    return tuple(sorted(items, key=lambda item: item.customer_id))

def _insert_bulk_lifecycle_operation(self, conn: sqlite3.Connection, *, preview: CustomerOperationPreview, private_targets: list[dict[str, Any]], operation_type: str, idempotency_key: str, created_by: str, CustomerOperationPreview=None, CustomerOperationQueueResult=None, VersionConflictError=None) -> CustomerOperationQueueResult:
    """Insert the same immutable records as a normal lifecycle command.

    The caller has already revalidated every member in one transaction;
    this helper intentionally does no remote I/O and does not expose the
    target identifiers in its return value.
    """

    queued_status = "queued" if private_targets else "succeeded"
    next_customer_status = {
        "suspend": "suspending" if private_targets else "suspended",
        "resume": "resuming" if private_targets else "active",
        "delete": "deleting" if private_targets else "deleted",
    }[operation_type]
    if operation_type == "delete" and not private_targets:
        update = conn.execute(
            """
            UPDATE customers
            SET status = ?, deleted_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND row_version = ? AND deleted_at IS NULL
            """,
            (next_customer_status, preview.customer_id, preview.expected_customer_version),
        )
    else:
        update = conn.execute(
            """
            UPDATE customers SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND row_version = ? AND deleted_at IS NULL
            """,
            (next_customer_status, preview.customer_id, preview.expected_customer_version),
        )
    if update.rowcount != 1:
        raise VersionConflictError("customer was updated by another operation")
    cursor = conn.execute(
        """
        INSERT INTO telegram_customer_operations
            (customer_id, operation_type, status, target_snapshot_digest,
             expected_customer_version, idempotency_key, created_by, finished_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'succeeded' THEN CURRENT_TIMESTAMP ELSE NULL END)
        """,
        (
            preview.customer_id, operation_type, queued_status, preview.target_snapshot_digest,
            preview.expected_customer_version, idempotency_key, created_by, queued_status,
        ),
    )
    operation_id = int(cursor.lastrowid)
    for target in private_targets:
        conn.execute(
            """
            INSERT INTO telegram_customer_operation_attempts
                (operation_id, binding_id, node_id, inbound_id, remote_client_id, remote_sub_id,
                 remote_email, action, previous_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id, target["binding_id"], target["node_id"], target["inbound_id"],
                target["remote_client_id"], target["remote_sub_id"], target["remote_email"],
                target["action"], int(target["previous_enabled"])
                if target["previous_enabled"] is not None else None,
            ),
        )
    return CustomerOperationQueueResult(
        operation_id=operation_id, customer_id=preview.customer_id,
        operation_type=operation_type, status=queued_status, row_version=1,
    )

def queue_bulk_customer_operations(self, *, operation_type: object, target_snapshot_digest: object, items: object, idempotency_key: str, created_by: str, BulkLifecycleStatus=None, CustomerOperationPreview=None, IdempotencyConflictError=None, TelegramRegistryError=None, VersionConflictError=None, _nonempty=None, _payload_digest=None) -> BulkLifecycleStatus:
    """Atomically queue a reviewed batch of normal lifecycle operations."""

    if operation_type not in {"suspend", "resume", "delete"}:
        raise TelegramRegistryError("bulk operation is invalid")
    parsed_items = self._parse_bulk_preview_items(items)
    expected_bulk_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
    if self._bulk_preview_digest(str(operation_type), parsed_items) != expected_bulk_digest:
        raise VersionConflictError("bulk lifecycle preview is stale")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(created_by, "created_by")
    payload = {"operation_type": operation_type, "target_snapshot_digest": expected_bulk_digest}
    payload_digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'bulk_customer_lifecycle' AND idempotency_key = ?", (key,)
        ).fetchone()
        if receipt is not None:
            if str(receipt[0]) != payload_digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return self.get_bulk_lifecycle_status(int(json.loads(str(receipt[1]))["bulk_job_id"]))

        snapshots: list[tuple[CustomerOperationPreview, list[dict[str, Any]], str]] = []
        for item in parsed_items:
            preview, private_targets = self._customer_operation_snapshot(
                conn, customer_id=item.customer_id, operation_type=str(operation_type)
            )
            if (
                preview.expected_customer_version != item.expected_customer_version
                or preview.target_snapshot_digest != item.target_snapshot_digest
                or preview.blocked_binding_ids
            ):
                raise VersionConflictError("at least one bulk lifecycle target is stale")
            email = conn.execute("SELECT email_display FROM customers WHERE id = ?", (item.customer_id,)).fetchone()
            assert email is not None
            snapshots.append((preview, private_targets, str(email[0])))
        cursor = conn.execute(
            """
            INSERT INTO telegram_bulk_lifecycle_jobs
                (operation_type, target_snapshot_digest, created_by, idempotency_key)
            VALUES (?, ?, ?, ?)
            """,
            (operation_type, expected_bulk_digest, actor, key),
        )
        bulk_job_id = int(cursor.lastrowid)
        for preview, private_targets, _email in snapshots:
            result = self._insert_bulk_lifecycle_operation(
                conn, preview=preview, private_targets=private_targets, operation_type=str(operation_type),
                idempotency_key=f"bulk:{bulk_job_id}:{preview.customer_id}", created_by=actor,
            )
            conn.execute(
                "INSERT INTO telegram_bulk_lifecycle_items(bulk_job_id, customer_id, operation_id) VALUES (?, ?, ?)",
                (bulk_job_id, preview.customer_id, result.operation_id),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
                """,
                (f"customer_{operation_type}_queued_bulk", actor, str(result.operation_id), expected_bulk_digest),
            )
        conn.execute(
            "INSERT INTO telegram_command_receipts(scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('bulk_customer_lifecycle', ?, ?, ?)",
            (key, payload_digest, json.dumps({"bulk_job_id": bulk_job_id}, separators=(",", ":"))),
        )
    return self.get_bulk_lifecycle_status(bulk_job_id)

def get_bulk_lifecycle_status(self, bulk_job_id: int, *, BulkLifecycleItemStatus=None, BulkLifecycleStatus=None, TelegramRegistryError=None, _positive_int=None) -> BulkLifecycleStatus:
    local_bulk_job_id = _positive_int(bulk_job_id, "bulk_job_id")
    with connect(self._db_path) as conn:
        job = conn.execute(
            "SELECT operation_type, created_at FROM telegram_bulk_lifecycle_jobs WHERE id = ?",
            (local_bulk_job_id,),
        ).fetchone()
        if job is None:
            raise TelegramRegistryError("bulk lifecycle job was not found")
        rows = conn.execute(
            """
            SELECT item.customer_id, customer.email_display, item.operation_id, operation.status
            FROM telegram_bulk_lifecycle_items AS item
            JOIN customers AS customer ON customer.id = item.customer_id
            JOIN telegram_customer_operations AS operation ON operation.id = item.operation_id
            WHERE item.bulk_job_id = ? ORDER BY customer.email_display COLLATE NOCASE, item.customer_id
            """,
            (local_bulk_job_id,),
        ).fetchall()
    return BulkLifecycleStatus(
        bulk_job_id=local_bulk_job_id, operation_type=str(job[0]), created_at=str(job[1]),
        items=tuple(BulkLifecycleItemStatus(
            customer_id=int(row[0]), customer_email=str(row[1]), operation_id=int(row[2]), status=str(row[3])
        ) for row in rows),
    )
