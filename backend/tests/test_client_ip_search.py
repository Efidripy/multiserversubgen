import asyncio
import sys
import threading
import time

sys.path.insert(0, "backend")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.clients import _find_clients_by_ip, build_clients_router


def test_ip_search_bounds_concurrency_and_preserves_order():
    nodes = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fetch_clients(node):
        return [{"email": f"first@{node['name']}"}, {"email": f"second@{node['name']}"}]

    def fetch_client_ips(node, email):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"ips": ["203.0.113.7"] if email.startswith("first") else []}

    matches = asyncio.run(
        _find_clients_by_ip(nodes, "203.0.113.7", fetch_clients, fetch_client_ips, max_workers=2)
    )

    assert 1 < max_active <= 2
    assert matches == [
        {"email": "first@alpha", "node": "alpha", "ips": ["203.0.113.7"]},
        {"email": "first@beta", "node": "beta", "ips": ["203.0.113.7"]},
    ]


def test_ip_search_isolates_a_failed_node():
    nodes = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]

    def fetch_clients(node):
        return [{"email": f"user@{node['name']}"}]

    def fetch_client_ips(node, email):
        if node["name"] == "beta":
            raise RuntimeError("node unavailable")
        return {"ips": ["203.0.113.8"]}

    matches = asyncio.run(
        _find_clients_by_ip(nodes, "203.0.113.8", fetch_clients, fetch_client_ips, max_workers=2)
    )

    assert matches == [{"email": "user@alpha", "node": "alpha", "ips": ["203.0.113.8"]}]


def test_find_by_ip_route_keeps_response_shape(tmp_path):
    nodes = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]

    class NodeService:
        def list_nodes(self):
            return list(nodes)

    class ClientManager:
        def get_all_clients(self, node_list):
            node = node_list[0]
            return [{"email": f"user@{node['name']}"}]

        def get_client_ips(self, node, _email):
            return {"ips": ["203.0.113.9"]}

    class WsManager:
        async def broadcast_client_update(self, _payload):
            return None

        async def broadcast_traffic_update(self, _payload):
            return None

    app = FastAPI()
    app.include_router(
        build_clients_router(
            check_auth=lambda _request: "admin",
            client_mgr=ClientManager(),
            db_path=str(tmp_path / "admin.db"),
            get_cached_clients=lambda *_args, **_kwargs: [],
            node_service=NodeService(),
            get_node_or_404=lambda node_id: next(node for node in nodes if node["id"] == node_id),
            invalidate_live_stats_cache=lambda: None,
            invalidate_subscription_cache=lambda: None,
            ws_manager=WsManager(),
        )
    )

    response = TestClient(app).get("/api/v1/clients/find-by-ip?ip=203.0.113.9")

    assert response.status_code == 200
    assert response.json() == {
        "ip": "203.0.113.9",
        "matches": [
            {"email": "user@alpha", "node": "alpha", "ips": ["203.0.113.9"]},
            {"email": "user@beta", "node": "beta", "ips": ["203.0.113.9"]},
        ],
        "count": 2,
    }
