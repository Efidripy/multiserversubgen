from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_registry import TelegramRegistry
from services.telegram_retention import TelegramRetentionService


def test_retention_expires_only_old_pending_application_and_preserves_customer(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="old", first_name="Old", last_name=None
    )
    registry.create_pending_application(42)
    customer_id = registry.create_customer(email_display="active", origin="manual", email_source="admin", public_code="active")
    with connect(db_path) as conn:
        conn.execute("UPDATE telegram_applications SET created_at = '2025-01-01 00:00:00' WHERE telegram_user_id = 42")

    result = TelegramRetentionService(db_path).run_once(now=datetime(2026, 2, 1, tzinfo=timezone.utc))

    assert result.expired_pending == 1
    with connect(db_path) as conn:
        assert conn.execute("SELECT access_status FROM telegram_identities WHERE telegram_user_id = 42").fetchone()[0] == "eligible"
        assert conn.execute("SELECT status, introduction_text FROM telegram_applications WHERE telegram_user_id = 42").fetchone() == ("cancelled", None)
        assert conn.execute("SELECT id FROM customers WHERE id = ?", (customer_id,)).fetchone()[0] == customer_id
