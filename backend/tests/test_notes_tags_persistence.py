import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.clients import build_clients_router
from services.db_bootstrap import connect, init_db
from services.node_service import NodeService


class _NodeServiceStub:
    def __init__(self, nodes):
        self._nodes = nodes

    def list_nodes(self):
        return list(self._nodes)


class _ClientManagerStub:
    def update_client(self, *_args, **_kwargs):
        raise AssertionError("notes-only persistence must not update x-ui clients")


class _BulkClientManagerStub:
    def __init__(self):
        self.updates = []

    def update_client(self, node, inbound_id, email, updates):
        self.updates.append((node["name"], inbound_id, email, updates))
        return True


class _WsManagerStub:
    def __init__(self):
        self.client_updates = []

    async def broadcast_client_update(self, payload):
        self.client_updates.append(payload)


def test_bootstrap_adds_notes_and_tags_schema_idempotently(tmp_path):
    db_path = str(tmp_path / "admin.db")

    init_db(db_path)
    init_db(db_path)

    with connect(db_path) as conn:
        node_columns = {row[1] for row in conn.execute("PRAGMA table_info(nodes)").fetchall()}
        note_columns = {row[1] for row in conn.execute("PRAGMA table_info(client_notes)").fetchall()}

    assert "tags" in node_columns
    assert "notes" in note_columns


def test_client_notes_endpoint_persists_and_enriches_client_list(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    nodes = [{"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443"}]
    cached_clients = [
        {
            "id": "client-1",
            "email": "one@test.local",
            "node_id": 1,
            "inbound_id": 11,
            "node_name": "alpha",
        }
    ]
    ws_manager = _WsManagerStub()

    app = FastAPI()
    app.include_router(
        build_clients_router(
            check_auth=lambda request: "admin",
            client_mgr=_ClientManagerStub(),
            db_path=db_path,
            get_cached_clients=lambda _nodes, email_filter=None: list(cached_clients),
            node_service=_NodeServiceStub(nodes),
            get_node_or_404=lambda node_id: nodes[0],
            invalidate_live_stats_cache=lambda: None,
            invalidate_subscription_cache=lambda: None,
            ws_manager=ws_manager,
        )
    )
    client = TestClient(app)

    saved = client.put(
        "/api/v1/clients/client-1/notes",
        json={"node_id": 1, "inbound_id": 11, "email": "one@test.local", "notes": "server note"},
    )
    listed = client.get("/api/v1/clients")

    assert saved.status_code == 200
    assert saved.json()["notes"] == "server note"
    assert listed.status_code == 200
    assert listed.json()["clients"][0]["notes"] == "server note"
    assert ws_manager.client_updates[-1]["action"] == "update_client_notes"

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT notes FROM client_notes WHERE node_id = ? AND inbound_id = ? AND client_identifier = ?",
            (1, 11, "client-1"),
        ).fetchone()
    assert row[0] == "server note"


def test_bulk_enable_loads_nodes_before_iterating(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    nodes = [
        {"id": 1, "name": "alpha", "ip": "1.1.1.1", "port": "443"},
        {"id": 2, "name": "beta", "ip": "2.2.2.2", "port": "443"},
    ]
    manager = _BulkClientManagerStub()
    app = FastAPI()
    app.include_router(
        build_clients_router(
            check_auth=lambda request: "admin",
            client_mgr=manager,
            db_path=db_path,
            get_cached_clients=lambda _nodes, email_filter=None: [],
            node_service=_NodeServiceStub(nodes),
            get_node_or_404=lambda node_id: next(node for node in nodes if node["id"] == node_id),
            invalidate_live_stats_cache=lambda: None,
            invalidate_subscription_cache=lambda: None,
            ws_manager=_WsManagerStub(),
        )
    )

    response = TestClient(app).post(
        "/api/v1/clients/bulk-enable",
        json={"emails": ["one@test.local"], "enable": False},
    )

    assert response.status_code == 200
    assert response.json()["updated"] == 2
    assert [update[0] for update in manager.updates] == ["alpha", "beta"]


def test_node_service_persists_tags_as_json(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO nodes (id, name, ip, port, user, password) VALUES (?, ?, ?, ?, ?, ?)",
            (1, "alpha", "1.1.1.1", "443", "root", "secret"),
        )

    runtime_updated = NodeService(db_path).update_node(1, {"tags": ["edge", " beta ", ""]})
    comma_updated = NodeService(db_path).update_node(1, {"tags": "core, vpn"})

    assert runtime_updated["tags"] == '["edge", "beta"]'
    assert comma_updated["tags"] == '["core", "vpn"]'
