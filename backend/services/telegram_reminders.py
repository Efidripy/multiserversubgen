"""Local, deduplicated Telegram reminders derived from immutable expiry snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from services.db_bootstrap import connect
from services.telegram_registry import CustomerTrafficQuotaBinding, TelegramRegistry


@dataclass(frozen=True)
class TelegramReminderRunResult:
    scanned: int
    queued: int
    traffic_scanned: int = 0
    traffic_queued: int = 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramReminderService:
    """Queue expiry notices only; it never fetches or mutates a remote node."""

    def __init__(
        self,
        db_path: str,
        *,
        now: Callable[[], datetime] = _utc_now,
        traffic_snapshot_loader: Callable[[str, tuple[CustomerTrafficQuotaBinding, ...]], int | None] | None = None,
    ):
        self._db_path = db_path
        self._now = now
        self._traffic_snapshot_loader = traffic_snapshot_loader

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
        traffic_scanned, traffic_queued = self._queue_traffic_reminders()
        return TelegramReminderRunResult(
            scanned=len(rows), queued=queued, traffic_scanned=traffic_scanned, traffic_queued=traffic_queued
        )

    def _queue_traffic_reminders(self) -> tuple[int, int]:
        """Queue at most one highest newly crossed traffic band per plan.

        The source callable is a local collector projection. A missing or
        ambiguous value is deliberately a no-op; this worker never refreshes a
        cache and therefore never contacts a node itself.
        """

        if self._traffic_snapshot_loader is None:
            return 0, 0
        candidates = TelegramRegistry(self._db_path).list_traffic_reminder_candidates()
        queued = 0
        for candidate in candidates:
            try:
                observed_bytes = self._traffic_snapshot_loader(candidate.email_display, candidate.bindings)
            except Exception:
                continue
            if observed_bytes is None or isinstance(observed_bytes, bool) or observed_bytes < 0:
                continue
            due = [
                threshold for threshold in (80, 95, 100)
                if int(observed_bytes) * 100 >= candidate.quota_total_bytes * threshold
            ]
            if not due:
                continue
            threshold = max(due)
            with connect(self._db_path) as conn:
                receipt = conn.execute(
                    """
                    INSERT OR IGNORE INTO telegram_traffic_reminder_receipts
                        (customer_id, quota_plan_digest, threshold_percent)
                    VALUES (?, ?, ?)
                    """,
                    (candidate.customer_id, candidate.quota_plan_digest, threshold),
                )
                if receipt.rowcount != 1:
                    continue
                # A delayed first observation can cross several bands. Record
                # the lower bands too, then send only the strongest signal.
                for lower_threshold in due:
                    if lower_threshold != threshold:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO telegram_traffic_reminder_receipts
                                (customer_id, quota_plan_digest, threshold_percent)
                            VALUES (?, ?, ?)
                            """,
                            (candidate.customer_id, candidate.quota_plan_digest, lower_threshold),
                        )
                conn.execute(
                    """
                    INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json)
                    VALUES ('user_traffic_reminder', ?, ?, ?)
                    """,
                    (
                        str(candidate.telegram_user_id),
                        f"user:traffic-reminder:{candidate.customer_id}:{candidate.quota_plan_digest}:{threshold}",
                        json.dumps(
                            {
                                "percent": threshold,
                                "used_bytes": int(observed_bytes),
                                "limit_bytes": candidate.quota_total_bytes,
                            },
                            separators=(",", ":"),
                        ),
                    ),
                )
                queued += 1
        return len(candidates), queued
