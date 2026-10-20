import asyncio
import os
import sys
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.clients import build_clients_router
from routers.inbounds import build_inbounds_router
from routers.live_data import build_live_data_router
from routers.nodes import build_nodes_router
from services.clients_runtime import ClientsRuntime
from services.collector import SnapshotCollector
from services.db_bootstrap import init_db
from services.inbounds_runtime import InboundsRuntime


def _collector(**kwargs):
    return SnapshotCollector(
        fetch_nodes=lambda: [{"id": 1, "name": "edge-a"}],
        xui_monitor=SimpleNamespace(),
        ws_manager=SimpleNamespace(active_connections=[]),
        **kwargs,
    )


async def _start_collector(collector, poll_started=None, release=None):
    async def poll_due(_due_nodes, *, force_poll):
        if poll_started is not None:
            poll_started.set()
        if release is not None:
            await release.wait()
        return []

    collector._poll_due_nodes = poll_due
    await collector.start()


def test_force_poll_wait_completes_a_new_cycle_and_wakes_all_waiters():
    async def scenario():
        collector = _collector()
        collector._node_state = {"id:1": {"next_poll": time.time() + 1000, "circuit_until": 0.0}}
        await collector.start()
        try:
            assert await collector.force_poll_all_and_wait(timeout=1.0) is True
        finally:
            await collector.stop()

        collector = _collector()
        collector._node_state = {"id:1": {"next_poll": time.time() + 1000, "circuit_until": 0.0}}
        await collector.start()
        try:
            results = await asyncio.gather(
                collector.force_poll_all_and_wait(timeout=1.0),
                collector.force_poll_all_and_wait(timeout=1.0),
            )
            assert results == [True, True]
        finally:
            await collector.stop()

    asyncio.run(scenario())


def test_force_poll_wait_times_out_for_cycle_already_running_before_request():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        collector = _collector()
        collector._node_state = {"id:1": {"next_poll": time.time() + 1000, "circuit_until": 0.0}}
        await _start_collector(collector, started, release)
        try:
            await collector.force_poll_all()
            await asyncio.wait_for(started.wait(), timeout=1.0)
            assert await collector.force_poll_all_and_wait(timeout=0.02) is False
        finally:
            release.set()
            await collector.stop()

    asyncio.run(scenario())


def _nodes_router_client(snapshot_collector):
    nodes = [{"id": 1, "name": "edge-a", "password": "secret"}]

    class NodeService:
        def list_nodes(self):
            return [dict(node) for node in nodes]

    app = FastAPI()
    @app.middleware("http")
    async def _auth_state(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    app.include_router(
        build_nodes_router(
            check_auth=lambda _request: "admin",
            node_service=NodeService(),
            get_node_or_404=lambda node_id: next(n for n in nodes if n["id"] == node_id),
            db_path=":memory:",
            encrypt=lambda value: value,
            requests_verify=True,
            login_panel=lambda *_args, **_kwargs: None,
            xui_request=lambda *_args, **_kwargs: None,
            invalidate_subscription_cache=lambda: None,
            remove_node_metric_labels=lambda *_args: None,
            node_metric_labels_lock=None,
            node_metric_labels_state={},
            snapshot_collector=snapshot_collector,
            ws_manager=SimpleNamespace(),
            logger=SimpleNamespace(),
        )
    )
    return TestClient(app)


def test_refresh_now_wait_response_contract():
    class Collector:
        async def force_poll_all(self):
            return None

        async def force_poll_all_and_wait(self):
            return True

    client = _nodes_router_client(Collector())
    waited = client.post("/api/v1/nodes/refresh-now?wait=true")
    assert waited.status_code == 200
    assert waited.json()["waited"] is True
    assert waited.json()["completed"] is True
    assert isinstance(waited.json()["duration_ms"], float)

    immediate = client.post("/api/v1/nodes/refresh-now")
    assert immediate.status_code == 200
    assert immediate.json()["waited"] is False


def test_clients_force_bypasses_fresh_cache_and_publishes_result():
    calls = []

    class Manager:
        def get_all_clients(self, _nodes, email_filter=None):
            calls.append(email_filter)
            return [{"email": "fresh@example.test"}]

    cache = {"ts": time.time(), "data": [{"email": "cached@example.test"}]}
    runtime = ClientsRuntime(
        client_mgr=Manager(),
        clients_cache=cache,
        clients_cache_ttl=30,
        clients_cache_stale_ttl=300,
        start_cache_refresh=lambda *_args: None,
    )
    nodes = [{"id": 1}]
    assert runtime.get_cached_clients(nodes) == [{"email": "cached@example.test"}]
    assert calls == []
    assert runtime.get_cached_clients(nodes, force=True) == [{"email": "fresh@example.test"}]
    assert calls == [None]
    assert cache["data"] == [{"email": "fresh@example.test"}]


def test_inbounds_force_bypasses_fresh_cache_and_honors_snapshot_age():
    calls = []
    snapshot_timestamp = [time.time() - 31]

    def usable(_node, not_before):
        calls.append(not_before)
        if snapshot_timestamp[0] >= not_before:
            return [{"id": "snapshot"}]
        return None

    class Manager:
        def get_all_inbounds(self, nodes, *, snapshot_inbounds=None):
            value = snapshot_inbounds(nodes[0]) if snapshot_inbounds else None
            return value or [{"id": "live"}]

    runtime = InboundsRuntime(
        inbound_mgr=Manager(),
        inbounds_cache={"ts": time.time(), "data": [{"id": "cached"}]},
        start_cache_refresh=lambda *_args: None,
        usable_inbounds=usable,
    )
    nodes = [{"id": 1}]
    assert runtime.get_cached_inbounds(nodes) == [{"id": "cached"}]
    assert runtime.get_cached_inbounds(nodes, force=True) == [{"id": "live"}]
    assert calls and calls[-1] >= time.time() - 30.5

    snapshot_timestamp[0] = time.time() - 5
    assert runtime.get_cached_inbounds(nodes, force=True) == [{"id": "snapshot"}]


def _refresh_routes_client(tmp_path):
    nodes = [{"id": 1, "name": "edge-a"}]
    init_db(str(tmp_path / "admin.db"))

    class NodeService:
        def list_nodes(self):
            return list(nodes)

    class InboundManager:
        def get_all_slim_inbounds(self, _nodes, **_kwargs):
            return []

        def get_all_inbound_options(self, _nodes, **_kwargs):
            return []

    app = FastAPI()
    @app.middleware("http")
    async def _auth_state(request, call_next):
        request.state.auth_user = "admin"
        return await call_next(request)

    app.include_router(
        build_clients_router(
            check_auth=lambda _request: "admin",
            client_mgr=SimpleNamespace(),
            db_path=str(tmp_path / "admin.db"),
            get_cached_clients=lambda _nodes, email_filter=None, **_kwargs: [],
            node_service=NodeService(),
            get_node_or_404=lambda node_id: nodes[0],
            invalidate_live_stats_cache=lambda: None,
            invalidate_subscription_cache=lambda: None,
            ws_manager=SimpleNamespace(),
        )
    )
    app.include_router(
        build_inbounds_router(
            check_auth=lambda _request: "admin",
            inbound_mgr=InboundManager(),
            get_cached_inbounds=lambda _nodes, **_kwargs: [],
            get_cached_slim_inbounds=lambda _nodes, **_kwargs: [],
            get_cached_inbound_options=lambda _nodes, **_kwargs: [],
            node_service=NodeService(),
            get_node_or_404=lambda node_id: nodes[0],
            invalidate_subscription_cache=lambda: None,
            invalidate_live_stats_cache=lambda: None,
            ws_manager=SimpleNamespace(),
        )
    )
    app.include_router(
        build_live_data_router(
            get_node_or_404=lambda node_id: nodes[0],
            get_cached_traffic_stats=lambda _nodes, _group_by, **_kwargs: {"stats": {}},
            get_cached_traffic_stats_projection=lambda _group_by: {"stats": {}},
            get_cached_traffic_stats_projection_by_period=lambda _group_by, _period: {"stats": {}},
            list_nodes=NodeService().list_nodes,
            xui_monitor=SimpleNamespace(),
            get_latest_snapshot=lambda: {"nodes": []},
            get_latest_client_presence=lambda: {},
        )
    )
    return TestClient(app)


def test_refresh_get_routes_return_no_store_and_nodes_keep_default_cache_header(tmp_path):
    client = _refresh_routes_client(tmp_path)
    paths = [
        "/api/v1/clients?refresh=1",
        "/api/v1/clients/expired?refresh=1",
        "/api/v1/clients/depleted?refresh=1",
        "/api/v1/inbounds?refresh=1",
        "/api/v1/inbounds/stats?refresh=1",
        "/api/v1/inbounds/slim?refresh=1",
        "/api/v1/inbounds/options?refresh=1",
        "/api/v1/traffic/stats-by-period?refresh=1",
        "/api/v1/dashboard/overview?refresh=1",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers["cache-control"] == "no-store"

    nodes_client = _nodes_router_client(SimpleNamespace())
    assert nodes_client.get("/api/v1/nodes?refresh=1").headers["cache-control"] == "no-store"
    assert nodes_client.get("/api/v1/nodes").headers["cache-control"] == "private, max-age=300"
