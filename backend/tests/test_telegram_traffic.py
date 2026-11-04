from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import connect, init_db
from services.telegram_registry import TelegramRegistry
from services.telegram_traffic import TelegramTrafficService


def _bound_customer(registry, db_path, *, email, node_id, origin, source):
    customer_id = registry.create_customer(
        email_display=email,
        origin=origin,
        email_source="telegram_username" if origin == "telegram" else "existing",
        public_code=f"traffic-{node_id}-{email.split('@')[0].casefold()}",
    )
    identity = registry.get_or_create_identity(
        telegram_user_id=10_000 + customer_id,
        chat_id=10_000 + customer_id,
        username=f"traffic_{customer_id}",
        first_name="Traffic",
        last_name=None,
    )
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled) VALUES (?, ?, 1)", (node_id, f"edge-{node_id}"))
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )
        conn.execute(
            "INSERT INTO customer_node_bindings (customer_id, node_id, remote_email, source, management_state) "
            "VALUES (?, ?, ?, ?, 'confirmed')",
            (customer_id, node_id, email, source),
        )
    return customer_id


def _add_binding(registry, db_path, *, customer_id, email, node_id, source):
    with connect(db_path) as conn:
        conn.execute("INSERT INTO nodes (id, name, enabled) VALUES (?, ?, 1)", (node_id, f"edge-{node_id}"))
        conn.execute(
            "INSERT INTO customer_node_bindings (customer_id, node_id, remote_email, source, management_state) "
            "VALUES (?, ?, ?, ?, 'confirmed')",
            (customer_id, node_id, email, source),
        )


def _snapshot(*nodes):
    return {"nodes": list(nodes)}


def _node(node_id, email, *, up=0, down=0, total=None, available=True, inbounds_available=None):
    client = {"email": email, "up": up, "down": down}
    if total is not None:
        client["total"] = total
    inbound = {"id": 1, "clientStats": [client]}
    node = {"node_id": node_id, "available": available, "inbounds": [inbound]}
    if inbounds_available is not None:
        node["inbounds_available"] = inbounds_available
    return node


def test_reconcile_collector_snapshot_uses_up_and_down_when_total_is_limit(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = _bound_customer(
        registry,
        db_path,
        email="Traffic.User@example.test",
        node_id=1,
        origin="manual",
        source="admin_confirmed",
    )
    service = TelegramTrafficService(registry, lambda: {"unexpected": "projection"})

    snapshot = _snapshot(
        _node(1, "traffic.user@EXAMPLE.test", up=25, down=75, total=10_000),
    )
    assert service.reconcile_collector_snapshot(snapshot) == 1
    assert service.reconcile_collector_snapshot(snapshot) == 0
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 100


def test_reconcile_collector_snapshot_adopts_exact_accumulated_traffic_without_fetching(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    new_customer = _bound_customer(
        registry,
        db_path,
        email="New.User@example.test",
        node_id=1,
        origin="telegram",
        source="bot_provisioned",
    )
    existing_customer = _bound_customer(
        registry,
        db_path,
        email="Existing.User@example.test",
        node_id=2,
        origin="existing",
        source="existing_bound",
    )
    never_observed = registry.create_customer(
        email_display="never@example.test",
        origin="manual",
        email_source="admin",
        public_code="traffic-never",
    )
    loader_calls = 0

    def loader():
        nonlocal loader_calls
        loader_calls += 1
        raise AssertionError("reconciliation must not load a projection")

    snapshot = _snapshot(
        _node(1, "new.user@EXAMPLE.test", up=300, down=700),
        _node(2, "existing.user@example.test", up=4000, down=96, total=4096),
    )
    service = TelegramTrafficService(registry, loader)

    assert service.reconcile_collector_snapshot(snapshot) == 2
    assert service.reconcile_collector_snapshot(snapshot) == 0
    assert loader_calls == 0
    assert registry.get_customer_traffic(new_customer).lifetime_bytes == 1000
    assert registry.get_customer_traffic(existing_customer).lifetime_bytes == 4096
    page = {item.customer_id: item for item in registry.list_customers(page_size=10).items}
    assert page[never_observed].lifetime_bytes is None and page[never_observed].traffic_observed_at is None


def test_reconcile_collector_snapshot_skips_incomplete_customer_without_changing_ledgers(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = _bound_customer(
        registry,
        db_path,
        email="exact@example.test",
        node_id=1,
        origin="existing",
        source="existing_bound",
    )
    service = TelegramTrafficService(registry, None)
    complete = _snapshot(_node(1, "exact@example.test", up=10, down=20))
    assert service.reconcile_collector_snapshot(complete) == 1

    with connect(db_path) as conn:
        before_customer = conn.execute(
            "SELECT lifetime_bytes, last_observed_bytes, first_observed_at, last_observed_at, row_version "
            "FROM customer_traffic_ledger WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        before_binding = conn.execute(
            "SELECT customer_id, node_id, inbound_id, last_observed_bytes, updated_at "
            "FROM customer_traffic_binding_ledger WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()

    incomplete = _snapshot(
        _node(1, "exact@example.test", up=30, down=40, inbounds_available=False),
    )
    assert service.reconcile_collector_snapshot(incomplete) == 0

    with connect(db_path) as conn:
        after_customer = conn.execute(
            "SELECT lifetime_bytes, last_observed_bytes, first_observed_at, last_observed_at, row_version "
            "FROM customer_traffic_ledger WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        after_binding = conn.execute(
            "SELECT customer_id, node_id, inbound_id, last_observed_bytes, updated_at "
            "FROM customer_traffic_binding_ledger WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    assert tuple(after_customer) == tuple(before_customer)
    assert tuple(after_binding) == tuple(before_binding)


def test_reconcile_collector_snapshot_handles_node_disappearance_and_return(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    email = "two-nodes@example.test"
    customer_id = _bound_customer(
        registry,
        db_path,
        email=email,
        node_id=1,
        origin="manual",
        source="admin_confirmed",
    )
    _add_binding(registry, db_path, customer_id=customer_id, email=email, node_id=2, source="admin_confirmed")
    service = TelegramTrafficService(registry, None)

    first = _snapshot(_node(1, email, up=100), _node(2, email, up=200))
    assert service.reconcile_collector_snapshot(first) == 1
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 300

    missing = _snapshot(_node(1, email, up=100))
    assert service.reconcile_collector_snapshot(missing) == 0
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 300

    assert service.reconcile_collector_snapshot(first) == 0
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 300


def test_reconcile_collector_snapshot_digest_includes_each_binding_value(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    email = "digest@example.test"
    customer_id = _bound_customer(
        registry,
        db_path,
        email=email,
        node_id=1,
        origin="manual",
        source="admin_confirmed",
    )
    _add_binding(registry, db_path, customer_id=customer_id, email=email, node_id=2, source="admin_confirmed")
    service = TelegramTrafficService(registry, None)

    assert service.reconcile_collector_snapshot(_snapshot(_node(1, email, up=100), _node(2, email, up=200))) == 1
    assert service.reconcile_collector_snapshot(_snapshot(_node(1, email, up=150), _node(2, email, up=150))) == 1
    assert registry.get_customer_traffic(customer_id).lifetime_bytes == 500


def test_reconcile_collector_snapshot_rejects_ambiguous_data(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    customer_id = _bound_customer(
        registry,
        db_path,
        email="exact@example.test",
        node_id=1,
        origin="existing",
        source="existing_bound",
    )
    service = TelegramTrafficService(registry, None)

    duplicate = {
        "nodes": [
            {
                "node_id": 1,
                "available": True,
                "inbounds": [
                    {
                        "id": 1,
                        "clientStats": [
                            {"email": "exact@example.test", "up": 5, "down": 5},
                            {"email": "EXACT@example.test", "up": 5, "down": 5},
                        ],
                    }
                ],
            }
        ]
    }
    assert service.reconcile_collector_snapshot(duplicate) == 0
    assert registry.get_customer_traffic(customer_id).last_observed_at == ""
