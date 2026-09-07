from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_registry import TelegramRegistry
from services.telegram_reminders import TelegramReminderService


def _active_customer_with_expiry(db_path: str, *, expires_at: int) -> int:
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="expiry-user", origin="telegram", email_source="telegram_username", public_code="expiry-user"
    )
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=777, username="expiry_user", first_name="Expiry", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name) VALUES (1, 'expiry-node')")
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 42",
            (customer_id,),
        )
        job = conn.execute(
            """
            INSERT INTO telegram_provisioning_jobs
                (customer_id, trigger, idempotency_key, status, policy_snapshot_digest, created_by)
            VALUES (?, 'approve_new', 'expiry-job', 'succeeded', 'expiry-snapshot', 'test')
            """,
            (customer_id,),
        )
        conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, status, desired_client_id, desired_sub_id, desired_expiry_time, policy_version)
            VALUES (?, 1, 'succeeded', 'expiry-client', 'expiry-sub', ?, 1)
            """,
            (int(job.lastrowid), expires_at),
        )
    return customer_id


def test_expiry_reminders_use_immutable_snapshot_bands_and_dedupe(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expires_at = int((now + timedelta(days=2, hours=12)).timestamp() * 1000)
    customer_id = _active_customer_with_expiry(db_path, expires_at=expires_at)

    first = TelegramReminderService(db_path, now=lambda: now).run_once()
    replay = TelegramReminderService(db_path, now=lambda: now).run_once()
    one_day = TelegramReminderService(db_path, now=lambda: now + timedelta(days=2)).run_once()

    assert (first.scanned, first.queued) == (1, 1)
    assert replay.queued == 0
    assert one_day.queued == 1
    with connect(db_path) as conn:
        events = conn.execute(
            "SELECT entity_id, payload_json FROM telegram_outbox WHERE event_type = 'user_expiry_reminder' ORDER BY id"
        ).fetchall()
        receipts = conn.execute(
            "SELECT threshold_days FROM telegram_reminder_receipts WHERE customer_id = ? ORDER BY threshold_days",
            (customer_id,),
        ).fetchall()
    assert [(entity_id, json.loads(payload)["days"]) for entity_id, payload in events] == [("42", 3), ("42", 1)]
    assert receipts == [(1,), (3,)]


def test_expiry_reminder_skips_expired_and_opted_out_customers(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _active_customer_with_expiry(db_path, expires_at=int((now + timedelta(hours=12)).timestamp() * 1000))
    TelegramRegistry(db_path).toggle_expiry_reminders(42)

    result = TelegramReminderService(db_path, now=lambda: now).run_once()

    assert result.scanned == 0
    assert result.queued == 0


def test_expiry_reminder_ignores_a_superseded_successful_snapshot_on_the_same_node(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    customer_id = _active_customer_with_expiry(db_path, expires_at=int((now + timedelta(hours=12)).timestamp() * 1000))
    with connect(db_path) as conn:
        replacement = conn.execute(
            """
            INSERT INTO telegram_provisioning_jobs
                (customer_id, trigger, idempotency_key, status, policy_snapshot_digest, created_by)
            VALUES (?, 'manual_sync', 'expiry-replacement-job', 'succeeded', 'replacement-snapshot', 'test')
            """,
            (customer_id,),
        )
        conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, status, desired_client_id, desired_sub_id, desired_expiry_time, policy_version)
            VALUES (?, 1, 'succeeded', 'replacement-client', 'replacement-sub', ?, 2)
            """,
            (int(replacement.lastrowid), int((now + timedelta(days=30)).timestamp() * 1000)),
        )

    result = TelegramReminderService(db_path, now=lambda: now).run_once()

    assert result.scanned == 1
    assert result.queued == 0
