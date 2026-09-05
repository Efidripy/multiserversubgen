from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import init_db
from services.telegram_registry import TelegramRegistry
from services.telegram_traffic import TelegramTrafficService


def test_refresh_reads_existing_projection_without_network_and_is_case_insensitive(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = registry.create_customer(
        email_display="Traffic.User", origin="manual", email_source="admin", public_code="traffic-user"
    )
    calls = 0

    def projection():
        nonlocal calls
        calls += 1
        return {"stats": {"traffic.user": {"up": 25, "down": 75}}}

    ledger = TelegramTrafficService(registry, projection).refresh_for_access(
        customer_id=customer_id, email="Traffic.User"
    )

    assert calls == 1
    assert ledger.lifetime_bytes == 100
