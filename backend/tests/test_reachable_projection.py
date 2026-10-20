"""Reachability boundaries for fleet read projections."""

import time
from types import SimpleNamespace

import pytest

from services.clients_runtime import ClientsRuntime
from services.collector import SnapshotCollector
from services.inbounds_runtime import InboundsRuntime


def _collector_with_snapshots(*snapshots):
    collector = SnapshotCollector(
        fetch_nodes=lambda: [], xui_monitor=None, ws_manager=SimpleNamespace()
    )
    collector._latest = {
        "timestamp": time.time(),
        "nodes": {
            collector._node_key({"id": snapshot["node_id"], "name": snapshot.get("name")}): snapshot
            for snapshot in snapshots
        },
    }
    return collector


def _projection_nodes():
    return [
        {"id": 1, "name": "dead"},
        {"id": 2, "name": "live"},
        {"id": 3, "name": "unknown"},
    ]


def _reachability_filter():
    return _collector_with_snapshots(
        {"node_id": 1, "name": "dead", "available": False},
        {"node_id": 2, "name": "live", "available": True},
    ).filter_reachable_nodes


def test_reachable_projection_loaders_skip_only_explicitly_unavailable_nodes():
    class ClientManager:
        def __init__(self):
            self.calls = []

        def get_all_clients(self, nodes, email_filter=None):
            self.calls.append(nodes)
            return []

    class InboundManager:
        def __init__(self):
            self.calls = []

        def get_all_inbounds(self, nodes):
            self.calls.append(("full", nodes))
            return []

        def get_all_slim_inbounds(self, nodes, *, cached_full):
            self.calls.append(("slim", nodes))
            return []

        def get_all_inbound_options(self, nodes, *, cached_full):
            self.calls.append(("options", nodes))
            return []

    filter_reachable_nodes = _reachability_filter()
    client_manager = ClientManager()
    clients_runtime = ClientsRuntime(
        client_mgr=client_manager,
        clients_cache={"ts": 0.0, "data": []},
        clients_cache_ttl=30,
        clients_cache_stale_ttl=300,
        start_cache_refresh=lambda *_args: None,
        filter_reachable_nodes=filter_reachable_nodes,
    )
    inbound_manager = InboundManager()
    inbounds_runtime = InboundsRuntime(
        inbound_mgr=inbound_manager,
        inbounds_cache={"ts": 0.0, "data": []},
        start_cache_refresh=lambda *_args: None,
        filter_reachable_nodes=filter_reachable_nodes,
    )

    nodes = _projection_nodes()
    clients_runtime.get_cached_clients(nodes)
    inbounds_runtime.get_cached_inbounds(nodes)
    inbounds_runtime.get_cached_slim_inbounds(nodes)
    inbounds_runtime.get_cached_inbound_options(nodes)

    assert [[node["id"] for node in call] for call in client_manager.calls] == [[2, 3]]
    assert [
        (kind, [node["id"] for node in call_nodes])
        for kind, call_nodes in inbound_manager.calls
    ] == [("full", [2, 3]), ("slim", [2, 3]), ("options", [2, 3])]


def test_reachable_projection_background_refreshes_filter_nodes():
    class ClientManager:
        def __init__(self):
            self.calls = []

        def get_all_clients(self, nodes, email_filter=None):
            self.calls.append(nodes)
            return []

    class InboundManager:
        def __init__(self):
            self.calls = []

        def get_all_inbounds(self, nodes):
            self.calls.append(("full", nodes))
            return []

        def get_all_slim_inbounds(self, nodes, *, cached_full):
            self.calls.append(("slim", nodes))
            return []

        def get_all_inbound_options(self, nodes, *, cached_full):
            self.calls.append(("options", nodes))
            return []

    refreshes = []

    def start_cache_refresh(_key, refresh):
        refreshes.append(refresh)

    stale_at = time.time() - 31
    filter_reachable_nodes = _reachability_filter()
    client_manager = ClientManager()
    clients_runtime = ClientsRuntime(
        client_mgr=client_manager,
        clients_cache={"ts": stale_at, "data": [{"email": "cached"}]},
        clients_cache_ttl=30,
        clients_cache_stale_ttl=300,
        start_cache_refresh=start_cache_refresh,
        filter_reachable_nodes=filter_reachable_nodes,
    )
    inbound_manager = InboundManager()
    inbounds_runtime = InboundsRuntime(
        inbound_mgr=inbound_manager,
        inbounds_cache={"ts": stale_at, "data": [{"id": "cached"}]},
        start_cache_refresh=start_cache_refresh,
        filter_reachable_nodes=filter_reachable_nodes,
    )
    inbounds_runtime._slim_cache = {"ts": stale_at, "data": [{"id": "cached"}]}
    inbounds_runtime._options_cache = {"ts": stale_at, "data": [{"id": "cached"}]}

    nodes = _projection_nodes()
    clients_runtime.get_cached_clients(nodes)
    inbounds_runtime.get_cached_inbounds(nodes)
    inbounds_runtime.get_cached_slim_inbounds(nodes)
    inbounds_runtime.get_cached_inbound_options(nodes)
    for refresh in refreshes:
        refresh()

    assert [[node["id"] for node in call] for call in client_manager.calls] == [[2, 3]]
    assert [
        (kind, [node["id"] for node in call_nodes])
        for kind, call_nodes in inbound_manager.calls
    ] == [("full", [2, 3]), ("slim", [2, 3]), ("options", [2, 3])]


def test_filter_reachable_nodes_preserves_order_and_keeps_unknown_nodes_without_ids():
    collector = _collector_with_snapshots(
        {"node_id": 1, "name": "dead", "available": False}
    )
    nodes = [
        {"id": 2, "name": "live"},
        {"name": "unknown-without-id"},
        {"id": 1, "name": "dead"},
        {"id": 3, "name": "unknown"},
    ]

    assert collector.filter_reachable_nodes(nodes) == [nodes[0], nodes[1], nodes[3]]


def test_filter_reachable_nodes_uses_last_success_age_before_excluding_offline_nodes():
    collector = _collector_with_snapshots(
        {
            "node_id": 1,
            "name": "recent",
            "available": False,
            "last_success_at": time.time() - 60,
        },
        {
            "node_id": 2,
            "name": "old",
            "available": False,
            "last_success_at": time.time() - 2 * 60 * 60,
        },
        {"node_id": 3, "name": "never", "available": False},
    )
    nodes = [
        {"id": 1, "name": "recent"},
        {"id": 2, "name": "old"},
        {"id": 4, "name": "unknown"},
        {"id": 3, "name": "never"},
    ]

    assert collector.filter_reachable_nodes(nodes) == [nodes[0], nodes[2]]


def _seed_runtime():
    return InboundsRuntime(
        inbound_mgr=object(),
        inbounds_cache={"ts": 0.0, "data": []},
        start_cache_refresh=lambda *_args: None,
    )


def _available_snapshot(node_id):
    return {
        "node_id": node_id,
        "name": f"node-{node_id}",
        "available": True,
        "timestamp": time.time(),
        "inbounds": [],
    }


def test_collector_cycle_seed_accepts_nodes_filtered_by_collector():
    runtime = _seed_runtime()
    live_snapshot = {
        **_available_snapshot(1),
        "inbounds": [{"id": 10, "protocol": "vless", "settings": {}}],
    }
    collector = _collector_with_snapshots(
        live_snapshot,
        {"node_id": 2, "name": "dead", "available": False},
    )
    nodes = collector.filter_reachable_nodes(
        [{"id": 1, "enabled": True}, {"id": 2, "enabled": True}]
    )

    assert runtime.seed_full_cache_from_completed_collector_cycle([live_snapshot], nodes) is True
    assert runtime.inbounds_cache["data"][0]["node_id"] == 1


@pytest.mark.parametrize(
    "incomplete_snapshot",
    [
        {"inbounds_available": False},
        {"stale": True},
        {"cached_from_db": True},
        {"_transient_transport_failure": True, "available": False},
    ],
)
def test_collector_cycle_seed_rejects_partial_expected_node(incomplete_snapshot):
    runtime = _seed_runtime()
    nodes = [{"id": 1, "enabled": True}, {"id": 2, "enabled": True}]
    snapshots = [_available_snapshot(1), {**_available_snapshot(2), **incomplete_snapshot}]

    assert runtime.seed_full_cache_from_completed_collector_cycle(snapshots, nodes) is False


def test_collector_cycle_seed_rejects_missing_expected_node_snapshot():
    runtime = _seed_runtime()
    nodes = [{"id": 1, "enabled": True}, {"id": 2, "enabled": True}]

    assert runtime.seed_full_cache_from_completed_collector_cycle(
        [_available_snapshot(1)], nodes
    ) is False
