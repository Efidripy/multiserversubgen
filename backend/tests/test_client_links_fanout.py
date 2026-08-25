import asyncio
import os
import sys
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.clients import _collect_node_links, build_clients_router


def test_client_link_fanout_is_bounded_and_preserves_node_order():
    nodes = [{"id": index} for index in range(8)]
    lock = threading.Lock()
    active = 0
    max_active = 0
    started = threading.Event()
    release = threading.Event()

    def fetch(node):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                started.set()
        release.wait(timeout=2)
        with lock:
            active -= 1
        return [f"link-{node['id']}"]

    async def exercise():
        task = asyncio.create_task(_collect_node_links(nodes, fetch, max_workers=2))
        await asyncio.to_thread(started.wait, 1)
        release.set()
        return await task

    links = asyncio.run(exercise())

    assert max_active == 2
    assert links == [f"link-{index}" for index in range(8)]


def test_client_link_fanout_propagates_node_failure():
    nodes = [{"id": 1}, {"id": 2}, {"id": 3}]

    def fetch(node):
        if node["id"] == 2:
            raise RuntimeError("node unavailable")
        return [f"link-{node['id']}"]

    with pytest.raises(RuntimeError, match="node unavailable"):
        asyncio.run(_collect_node_links(nodes, fetch, max_workers=2))


def test_link_routes_keep_response_shape_for_fleet_fan_out(tmp_path):
    nodes = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]

    class NodeService:
        def list_nodes(self):
            return list(nodes)

    class ClientManager:
        def get_client_links(self, node, email):
            return [f"{email}@{node['name']}"]

        def get_sub_links(self, node, sub_id):
            return [f"{sub_id}@{node['name']}"]

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
    client = TestClient(app)

    links = client.get("/api/v1/clients/user@example.test/links").json()
    sub_links = client.get("/api/v1/clients/sub-links/sub-123").json()

    assert links == {
        "email": "user@example.test",
        "links": ["user@example.test@alpha", "user@example.test@beta"],
        "count": 2,
    }
    assert sub_links == {
        "sub_id": "sub-123",
        "links": ["sub-123@alpha", "sub-123@beta"],
        "count": 2,
    }
