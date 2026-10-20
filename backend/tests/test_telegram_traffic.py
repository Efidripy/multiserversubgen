from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
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


def _bound_customer(registry, db_path, *, email, node_id, origin, source):
    customer_id = registry.create_customer(
        email_display=email, origin=origin,
        email_source="telegram_username" if origin == "telegram" else "existing",
        public_code=f"traffic-{node_id}-{email.split('@')[0].casefold()}",
    )
    identity = registry.get_or_create_identity(
        telegram_user_id=10_000 + customer_id, chat_id=10_000 + customer_id,
        username=f"traffic_{customer_id}", first_name="Traffic", last_name=None,
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled) VALUES (?, ?, 1)", (node_id, f"edge-{node_id}"))
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
        conn.execute(
            "INSERT INTO customer_node_bindings (customer_id, node_id, remote_email, source, management_state) "
            "VALUES (?, ?, ?, ?, 'confirmed')", (customer_id, node_id, email, source),
        )
    return customer_id


def test_reconcile_collector_snapshot_adopts_exact_accumulated_traffic_without_fetching(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    new_customer = _bound_customer(registry, db_path, email="New.User@example.test", node_id=1, origin="telegram", source="bot_provisioned")
    existing_customer = _bound_customer(registry, db_path, email="Existing.User@example.test", node_id=2, origin="existing", source="existing_bound")
    never_observed = registry.create_customer(email_display="never@example.test", origin="manual", email_source="admin", public_code="traffic-never")
    loader_calls = 0

    def loader():
        nonlocal loader_calls
        loader_calls += 1
        raise AssertionError("reconciliation must not load a projection")

    snapshot = {"nodes": [
        {"node_id": 1, "available": True, "inbounds": [{"id": 1, "clientStats": [{"email": "new.user@EXAMPLE.test", "up": 300, "down": 700}]}]},
        {"node_id": 2, "available": True, "inbounds": [{"id": 1, "clientStats": [{"email": "existing.user@example.test", "total": 4096}]}]},
    ]}
    service = TelegramTrafficService(registry, loader)

    assert service.reconcile_collector_snapshot(snapshot) == 2
    assert service.reconcile_collector_snapshot(snapshot) == 0
    assert loader_calls == 0
    assert registry.get_customer_traffic(new_customer).lifetime_bytes == 1000
    assert registry.get_customer_traffic(existing_customer).lifetime_bytes == 4096
    page = {item.customer_id: item for item in registry.list_customers(page_size=10).items}
    assert page[never_observed].lifetime_bytes is None and page[never_observed].traffic_observed_at is None


def test_reconcile_collector_snapshot_rejects_ambiguous_or_incomplete_data(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = _bound_customer(registry, db_path, email="exact@example.test", node_id=1, origin="existing", source="existing_bound")
    service = TelegramTrafficService(registry, None)

    duplicate = {"nodes": [{"node_id": 1, "available": True, "inbounds": [{"id": 1, "clientStats": [
        {"email": "exact@example.test", "total": 10}, {"email": "EXACT@example.test", "total": 10},
    ]}]}]}
    unavailable = {"nodes": [{"node_id": 1, "available": False, "inbounds": []}]}
    partial_inventory = {"nodes": [{"node_id": 1, "available": True, "inbounds_available": False, "inbounds": [
        {"id": 1, "clientStats": [{"email": "exact@example.test", "total": 10}]},
    ]}]}

    assert service.reconcile_collector_snapshot(duplicate) == 0
    assert service.reconcile_collector_snapshot(unavailable) == 0
    assert service.reconcile_collector_snapshot(partial_inventory) == 0
    assert registry.get_customer_traffic(customer_id).last_observed_at == ""
