import asyncio
import os
import sys
import time
from threading import Lock
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
from services.live_stats_runtime import LiveStatsRuntime


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


def test_force_poll_wait_ignores_persistently_unreachable_node_but_cycle_still_polls_it():
    async def scenario():
        nodes = [{"id": 1, "name": "edge-a"}, {"id": 2, "name": "edge-b"}]
        collector = SnapshotCollector(
            fetch_nodes=lambda: nodes,
            xui_monitor=SimpleNamespace(),
            ws_manager=SimpleNamespace(active_connections=[]),
        )
        collector._inventory_nodes = [dict(node) for node in nodes]
        collector._latest = {
            "timestamp": time.time(),
            "nodes": {
                "id:2": {
                    "available": False,
                    "last_success_at": time.time() - 1000,
                }
            },
        }
        collector._node_state = {
            "id:1": {"next_poll": time.time() + 1000, "circuit_until": 0.0},
            "id:2": {"next_poll": time.time() + 1000, "circuit_until": 0.0},
        }
        dead_started = asyncio.Event()
        release_dead = asyncio.Event()
        polled = []

        async def fake_poll(node, key, *, delay):
            del delay
            polled.append(key)
            started = time.monotonic_ns()
            collector._poll_start_sequence += 1
            started_sequence = collector._poll_start_sequence
            if key == "id:2":
                dead_started.set()
                await release_dead.wait()
            collector._mark_force_poll_finished(
                key,
                poll_started_at=started,
                poll_finished_at=time.monotonic_ns(),
                poll_started_sequence=started_sequence,
            )
            return {"node_id": node["id"], "name": node["name"], "available": key == "id:1"}

        collector._poll_node_after_delay = fake_poll
        await collector.start()
        try:
            assert await collector.force_poll_all_and_wait(timeout=0.3) is True
            await asyncio.wait_for(dead_started.wait(), timeout=1.0)
            assert polled == ["id:1", "id:2"]
        finally:
            release_dead.set()
            await collector.stop()

    asyncio.run(scenario())


def test_force_poll_wait_with_no_reachable_nodes_waits_for_cycle_end():
    async def scenario():
        node = {"id": 1, "name": "edge-a"}
        collector = SnapshotCollector(
            fetch_nodes=lambda: [node],
            xui_monitor=SimpleNamespace(),
            ws_manager=SimpleNamespace(active_connections=[]),
        )
        collector._inventory_nodes = [dict(node)]
        collector._latest = {
            "timestamp": time.time(),
            "nodes": {"id:1": {"available": False, "last_success_at": time.time() - 1000}},
        }
        collector._node_state = {"id:1": {"next_poll": time.time() + 1000, "circuit_until": 0.0}}
        release = asyncio.Event()
        cycle_done = asyncio.Event()

        async def fake_poll_due(due_nodes, *, force_poll):
            assert force_poll is True
            assert due_nodes
            await release.wait()
            cycle_done.set()
            return []

        collector._poll_due_nodes = fake_poll_due
        await collector.start()
        try:
            waiter = asyncio.create_task(collector.force_poll_all_and_wait(timeout=1.0))
            await asyncio.sleep(0.05)
            assert not waiter.done()
            release.set()
            assert await waiter is True
            assert cycle_done.is_set()
        finally:
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
        request.state.auth_role = "admin"
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


def _refresh_routes_client(tmp_path, *, role="admin", client_calls=None):
    nodes = [{"id": 1, "name": "edge-a"}]
    tmp_path.mkdir(parents=True, exist_ok=True)
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
        request.state.auth_role = role
        return await call_next(request)

    app.include_router(
        build_clients_router(
            check_auth=lambda _request: "admin",
            client_mgr=SimpleNamespace(),
            db_path=str(tmp_path / "admin.db"),
            get_cached_clients=lambda _nodes, email_filter=None, **kwargs: (
                client_calls.append(kwargs) if client_calls is not None else None
            ) or [],
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
            get_cached_traffic_stats_projection=lambda _group_by, **_kwargs: {"stats": {}},
            get_cached_traffic_stats_projection_by_period=lambda _group_by, _period, **_kwargs: {"stats": {}},
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


def test_refresh_is_ignored_for_viewer_but_forced_for_operator(tmp_path):
    viewer_calls = []
    viewer = _refresh_routes_client(tmp_path / "viewer", role="viewer", client_calls=viewer_calls)
    assert viewer.get("/api/v1/clients?refresh=1").status_code == 200
    assert viewer_calls == [{}]

    operator_calls = []
    operator = _refresh_routes_client(tmp_path / "operator", role="operator", client_calls=operator_calls)
    assert operator.get("/api/v1/clients?refresh=1").status_code == 200
    assert operator_calls == [{"force": True}]


def test_traffic_refresh_rebuilds_from_collector_snapshot_without_live_loader(tmp_path):
    snapshot = {
        "timestamp": time.time(),
        "nodes": [{
            "node_id": 1,
            "name": "edge-a",
            "inbounds_available": True,
            "inbounds": [{
                "id": 10,
                "remark": "main",
                "up": 2,
                "down": 3,
                "clientStats": [{"email": "new@example.test", "up": 2, "down": 3}],
            }],
        }],
    }
    calls = []

    class ClientManager:
        def get_traffic_stats(self, *_args, **_kwargs):
            calls.append(True)
            raise AssertionError("refresh projection must not perform a live fleet scan")

    redis_store = {}
    runtime = LiveStatsRuntime(
        client_mgr=ClientManager(),
        db_path=str(tmp_path / "stats.db"),
        traffic_stats_cache={"client": (time.time(), {"stats": {"old@example.test": {"up": 1}}})},
        cache_refresh_state={"traffic": set()},
        state_lock=Lock(),
        redis_get_json=lambda key: redis_store.get(key),
        redis_set_json=lambda key, value, _ttl: redis_store.__setitem__(key, value),
        redis_delete=lambda *_keys: None,
        traffic_stats_cache_ttl=30,
        traffic_stats_stale_ttl=120,
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
        get_latest_snapshot=lambda: snapshot,
    )
    runtime._snapshot_projection_timestamp = snapshot["timestamp"]
    runtime._snapshot_projections = {"client": {"stats": {"old@example.test": {"up": 1}}}}

    app = FastAPI()
    @app.middleware("http")
    async def _auth_state(request, call_next):
        request.state.auth_user = "operator"
        request.state.auth_role = "operator"
        return await call_next(request)

    app.include_router(build_live_data_router(
        get_node_or_404=lambda node_id: {"id": node_id, "name": "edge-a"},
        get_cached_traffic_stats=lambda *_args, **_kwargs: {"stats": {}},
        get_cached_traffic_stats_projection=runtime.get_cached_traffic_stats_projection,
        get_cached_traffic_stats_projection_by_period=runtime.get_cached_traffic_stats_projection_by_period,
        list_nodes=lambda: [],
        xui_monitor=SimpleNamespace(),
        get_latest_snapshot=lambda: snapshot,
        get_latest_client_presence=lambda: {},
    ))
    client = TestClient(app)

    period = client.get("/api/v1/traffic/stats-by-period?refresh=1")
    overview = client.get("/api/v1/dashboard/overview?refresh=1")
    assert period.status_code == overview.status_code == 200
    assert "new@example.test" in period.json()["stats"]
    assert "new@example.test" in overview.json()["summary"]["top_clients"][0]["email"]
    assert calls == []
