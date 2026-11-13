"""Local-only retention for non-active Telegram application content."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from services.db_bootstrap import connect


@dataclass(frozen=True)
class RetentionResult:
    expired_pending: int
    deleted_decided_applications: int
    redacted_appeals: int


class TelegramRetentionService:
    """Purge only disposable application text; never touch approved customers."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def run_once(self, *, now: datetime | None = None) -> RetentionResult:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
        pending_cutoff = (current - timedelta(days=30)).isoformat(sep=" ")
        decided_cutoff = (current - timedelta(days=90)).isoformat(sep=" ")
        with connect(self._db_path) as conn:
            pending = conn.execute(
                """
                SELECT i.telegram_user_id, i.application_attempt
                FROM telegram_identities AS i
                JOIN telegram_applications AS a
                  ON a.telegram_user_id = i.telegram_user_id AND a.application_attempt = i.application_attempt
                WHERE i.access_status = 'pending' AND a.status = 'pending' AND a.created_at < ?
                """,
                (pending_cutoff,),
            ).fetchall()
            for user_id, attempt in pending:
                conn.execute(
                    "UPDATE telegram_applications SET status = 'cancelled', introduction_text = NULL, updated_at = CURRENT_TIMESTAMP WHERE telegram_user_id = ? AND application_attempt = ?",
                    (user_id, attempt),
                )
                conn.execute(
                    "UPDATE telegram_identities SET access_status = 'eligible', request_code = NULL, decision_reason = 'request_expired', row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP WHERE telegram_user_id = ? AND access_status = 'pending'",
                    (user_id,),
                )
                conn.execute(
                    "INSERT INTO telegram_audit_log (event_type, actor_type, entity_type, entity_id) VALUES ('pending_application_expired', 'system', 'telegram_identity', ?)",
                    (str(user_id),),
                )
            deleted = conn.execute(
                "DELETE FROM telegram_applications WHERE status IN ('rejected', 'blocked', 'cancelled') AND updated_at < ?",
                (decided_cutoff,),
            ).rowcount
            redacted = conn.execute(
                "UPDATE telegram_appeals SET body = '[redacted]', updated_at = CURRENT_TIMESTAMP WHERE status IN ('handled', 'rejected') AND created_at < ? AND body != '[redacted]'",
                (decided_cutoff,),
            ).rowcount
        return RetentionResult(len(pending), int(deleted), int(redacted))


def maintain_database_batch(db_path: str, retention_days: int = 30, batch_size: int = 500) -> int:
    """Remove a bounded batch of terminal Telegram records per transaction.

    Provisioning jobs and attempts are kept: reminders derive expiry and quotas from them.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).strftime("%Y-%m-%d %H:%M:%S")
    statements = (
        "DELETE FROM telegram_updates WHERE update_id IN (SELECT update_id FROM telegram_updates u "
        "WHERE status IN ('processed', 'rejected') AND processed_at < ? "
        "AND NOT EXISTS (SELECT 1 FROM telegram_update_responses r WHERE r.update_id = u.update_id AND r.status != 'sent') LIMIT ?)",
        "DELETE FROM telegram_outbox WHERE id IN (SELECT id FROM telegram_outbox "
        "WHERE status IN ('sent', 'cancelled') AND updated_at < ? LIMIT ?)",
    )
    total = 0
    for sql in statements:
        with connect(db_path) as conn:
            total += conn.execute(sql, (cutoff, max(1, batch_size))).rowcount
    return total


def checkpoint_database(db_path: str) -> None:
    with connect(db_path) as conn:
        result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    def size(path: str) -> int:
        try:
            return os.path.getsize(path)
        except FileNotFoundError:
            return 0
    logging.getLogger("sub_manager").info(
        "SQLite size: db=%s bytes wal=%s bytes checkpoint_busy=%s", size(db_path), size(db_path + "-wal"), result[0]
    )
