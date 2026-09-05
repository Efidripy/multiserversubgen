"""Local-only retention for non-active Telegram application content."""

from __future__ import annotations

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
