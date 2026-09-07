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


def _active_customer_with_finite_traffic_quota(db_path: str, *, quota_bytes: int = 1000) -> int:
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="quota-user", origin="telegram", email_source="telegram_username", public_code="quota-user"
    )
    registry.get_or_create_identity(
        telegram_user_id=43, chat_id=778, username="quota_user", first_name="Quota", last_name=None
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name) VALUES (2, 'quota-node')")
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = 43",
            (customer_id,),
        )
        job = conn.execute(
            """
            INSERT INTO telegram_provisioning_jobs
                (customer_id, trigger, idempotency_key, status, policy_snapshot_digest, created_by)
            VALUES (?, 'approve_new', 'quota-job', 'succeeded', 'quota-snapshot', 'test')
            """,
            (customer_id,),
        )
        attempt = conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, status, desired_client_id, desired_sub_id,
                 desired_total_bytes, policy_version, remote_client_id)
            VALUES (?, 2, 'succeeded', 'quota-client', 'quota-sub', ?, 1, 'quota-client')
            """,
            (int(job.lastrowid), quota_bytes),
        )
        assert attempt.rowcount == 1
        conn.execute(
            """
            INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id,
                 remote_email, source, management_state, desired_enabled)
            VALUES (?, 2, 1, 'quota-client', 'quota-sub', 'quota-user',
                    'bot_provisioned', 'confirmed', 1)
            """,
            (customer_id,),
        )
    registry.toggle_traffic_reminders(43)
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


def test_traffic_reminders_use_exact_finite_plan_bands_and_dedupe(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    customer_id = _active_customer_with_finite_traffic_quota(db_path)
    observed = [800]
    worker = TelegramReminderService(
        db_path,
        traffic_snapshot_loader=lambda _email, _bindings: observed[0],
    )

    first = worker.run_once()
    replay = worker.run_once()
    observed[0] = 950
    ninety_five = worker.run_once()
    observed[0] = 1000
    full = worker.run_once()

    assert (first.traffic_scanned, first.traffic_queued) == (1, 1)
    assert replay.traffic_queued == 0
    assert ninety_five.traffic_queued == 1
    assert full.traffic_queued == 1
    with connect(db_path) as conn:
        events = conn.execute(
            "SELECT entity_id, payload_json FROM telegram_outbox WHERE event_type = 'user_traffic_reminder' ORDER BY id"
        ).fetchall()
        receipts = conn.execute(
            """
            SELECT threshold_percent FROM telegram_traffic_reminder_receipts
            WHERE customer_id = ? ORDER BY threshold_percent
            """,
            (customer_id,),
        ).fetchall()
    assert [(entity_id, json.loads(payload)["percent"]) for entity_id, payload in events] == [
        ("43", 80), ("43", 95), ("43", 100)
    ]
    assert receipts == [(80,), (95,), (100,)]


def test_traffic_reminders_skip_unlimited_or_incomplete_plans_and_unknown_snapshot(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    _active_customer_with_finite_traffic_quota(db_path, quota_bytes=0)
    worker = TelegramReminderService(db_path, traffic_snapshot_loader=lambda _email, _bindings: None)

    result = worker.run_once()

    assert result.traffic_scanned == 0
    assert result.traffic_queued == 0


def test_traffic_reminder_requires_completed_initial_registration_and_sends_one_late_band(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    customer_id = _active_customer_with_finite_traffic_quota(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_provisioning_jobs SET status = 'partial' WHERE customer_id = ?",
            (customer_id,),
        )
    worker = TelegramReminderService(db_path, traffic_snapshot_loader=lambda _email, _bindings: 1000)

    incomplete = worker.run_once()
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_provisioning_jobs SET status = 'succeeded' WHERE customer_id = ?",
            (customer_id,),
        )
    late = worker.run_once()

    assert incomplete.traffic_scanned == 0
    assert late.traffic_queued == 1
    with connect(db_path) as conn:
        event = conn.execute(
            "SELECT payload_json FROM telegram_outbox WHERE event_type = 'user_traffic_reminder'"
        ).fetchone()
        receipts = conn.execute(
            """
            SELECT threshold_percent FROM telegram_traffic_reminder_receipts
            WHERE customer_id = ? ORDER BY threshold_percent
            """,
            (customer_id,),
        ).fetchall()
    assert json.loads(event[0])["percent"] == 100
    assert receipts == [(80,), (95,), (100,)]
