"""Local, deduplicated Telegram reminders derived from immutable expiry snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from services.db_bootstrap import connect


@dataclass(frozen=True)
class TelegramReminderRunResult:
    scanned: int
    queued: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramReminderService:
    """Queue expiry notices only; it never fetches or mutates a remote node."""

    def __init__(self, db_path: str, *, now: Callable[[], datetime] = _utc_now):
        self._db_path = db_path
        self._now = now

    @staticmethod
    def _threshold_days(remaining_seconds: int) -> int | None:
        if remaining_seconds <= 0:
            return None
        if remaining_seconds <= 24 * 60 * 60:
            return 1
        if remaining_seconds <= 3 * 24 * 60 * 60:
            return 3
        if remaining_seconds <= 7 * 24 * 60 * 60:
            return 7
        return None

    def run_once(self) -> TelegramReminderRunResult:
        current_ms = int(self._now().astimezone(timezone.utc).timestamp() * 1000)
        with connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT i.telegram_user_id, c.id, MIN(a.desired_expiry_time)
                FROM telegram_identities AS i
                JOIN customers AS c ON c.id = i.customer_id
                JOIN (
                    SELECT j.customer_id, a.node_id, MAX(a.id) AS attempt_id
                    FROM telegram_provisioning_jobs AS j
                    JOIN telegram_provisioning_attempts AS a ON a.job_id = j.id
                    WHERE j.status = 'succeeded' AND a.status = 'succeeded'
                    GROUP BY j.customer_id, a.node_id
                ) AS latest ON latest.customer_id = c.id
                JOIN telegram_provisioning_attempts AS a ON a.id = latest.attempt_id
                LEFT JOIN telegram_notification_preferences AS p ON p.telegram_user_id = i.telegram_user_id
                WHERE i.access_status = 'approved' AND c.status = 'active' AND c.deleted_at IS NULL
                  AND a.desired_expiry_time > 0
                  AND COALESCE(p.background_notifications_enabled, 1) = 1
                  AND COALESCE(p.expiry_reminders_enabled, 1) = 1
                GROUP BY i.telegram_user_id, c.id
                """
            ).fetchall()
            queued = 0
            for telegram_user_id, customer_id, expires_at in rows:
                expiry = int(expires_at)
                threshold_days = self._threshold_days((expiry - current_ms) // 1000)
                if threshold_days is None:
                    continue
                receipt = conn.execute(
                    """
                    INSERT OR IGNORE INTO telegram_reminder_receipts
                        (customer_id, reminder_kind, threshold_days, expires_at)
                    VALUES (?, 'expiry', ?, ?)
                    """,
                    (int(customer_id), threshold_days, expiry),
                )
                if receipt.rowcount != 1:
                    continue
                conn.execute(
                    """
                    INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json)
                    VALUES ('user_expiry_reminder', ?, ?, ?)
                    """,
                    (
                        str(int(telegram_user_id)),
                        f"user:expiry-reminder:{int(customer_id)}:{threshold_days}:{expiry}",
                        json.dumps({"days": threshold_days, "expires_at": expiry}, separators=(",", ":")),
                    ),
                )
                queued += 1
        return TelegramReminderRunResult(scanned=len(rows), queued=queued)
