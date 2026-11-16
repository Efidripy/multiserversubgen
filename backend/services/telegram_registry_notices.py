"""Service notice operations for the Telegram registry."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable

from services.db_bootstrap import connect


def get_service_notice(self, *, notice_type: type) -> Any:
    with connect(self._db_path) as conn:
        row = conn.execute(
            "SELECT body, is_active, row_version, updated_by, updated_at FROM telegram_service_notice WHERE id = 1"
        ).fetchone()
    if row is None:
        return notice_type(None, False, 0, "system", None)
    return notice_type(
        body=str(row[0]) if row[0] is not None else None,
        is_active=bool(row[1]),
        row_version=int(row[2]),
        updated_by=str(row[3]),
        updated_at=str(row[4]),
    )


def set_service_notice(
    self,
    *,
    body: str | None,
    expected_row_version: int,
    idempotency_key: str,
    updated_by: str,
    nonempty: Callable[[str, str], str],
    payload_digest: Callable[[dict[str, Any]], str],
    error_type: type[Exception],
    idempotency_conflict_type: type[Exception],
    version_conflict_type: type[Exception],
    notice_type: type,
) -> Any:
    if (
        isinstance(expected_row_version, bool)
        or not isinstance(expected_row_version, int)
        or expected_row_version < 0
    ):
        raise error_type("expected_row_version must be a non-negative integer")
    expected_version = expected_row_version
    key = nonempty(idempotency_key, "idempotency_key")
    actor = nonempty(updated_by, "updated_by")
    normalized_body = body.strip() if isinstance(body, str) else None
    if normalized_body is not None and not 1 <= len(normalized_body) <= 1000:
        raise error_type("service notice must contain 1 to 1000 characters")
    digest = payload_digest({"body": normalized_body, "expected_row_version": expected_version})
    scope = "set_service_notice"
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts WHERE scope = ? AND idempotency_key = ?",
            (scope, key),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise idempotency_conflict_type("idempotency key was already used for another command")
            return notice_type(**json.loads(str(receipt[1])))
        current = conn.execute(
            "SELECT row_version FROM telegram_service_notice WHERE id = 1"
        ).fetchone()
        current_version = int(current[0]) if current is not None else 0
        if current_version != expected_version:
            raise version_conflict_type("service notice was updated by another administrator")
        if current is None:
            conn.execute(
                "INSERT INTO telegram_service_notice (id, body, is_active, updated_by) VALUES (1, ?, ?, ?)",
                (normalized_body, int(normalized_body is not None), actor),
            )
            result_version = 1
        else:
            update = conn.execute(
                """
                UPDATE telegram_service_notice
                SET body = ?, is_active = ?, row_version = row_version + 1,
                    updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1 AND row_version = ?
                """,
                (normalized_body, int(normalized_body is not None), actor, expected_version),
            )
            if update.rowcount != 1:
                raise version_conflict_type("service notice was updated by another administrator")
            result_version = expected_version + 1
        row = conn.execute(
            "SELECT body, is_active, row_version, updated_by, updated_at FROM telegram_service_notice WHERE id = 1"
        ).fetchone()
        assert row is not None
        result = notice_type(
            body=str(row[0]) if row[0] is not None else None,
            is_active=bool(row[1]),
            row_version=result_version,
            updated_by=str(row[3]),
            updated_at=str(row[4]),
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
            VALUES ('service_notice_updated', 'admin', ?, 'telegram_service_notice', '1', ?)
            """,
            (actor, digest),
        )
    return result
