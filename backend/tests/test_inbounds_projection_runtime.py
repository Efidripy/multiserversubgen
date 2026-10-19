"""Cache boundaries for read-only inbound projections."""

import time

from services.inbounds_runtime import InboundsRuntime


class _InboundManager:
    def __init__(self):
        self.options_calls = []
        self.slim_calls = []

    def get_all_inbounds(self, _nodes):
        raise AssertionError(
            "projection cache must not cold-fetch the full inbound DTO"
        )

    def get_all_inbound_options(self, nodes, *, cached_full):
        self.options_calls.append((nodes, cached_full))
        return [{"detail_level": "option", "id": 1}]

    def get_all_slim_inbounds(self, nodes, *, cached_full):
        self.slim_calls.append((nodes, cached_full))
        return [{"detail_level": "slim", "id": 1}]


def test_projection_caches_reuse_existing_full_rows_without_full_fetch():
    manager = _InboundManager()
    runtime = InboundsRuntime(
        inbound_mgr=manager,
        inbounds_cache={
            "ts": time.time(),
            "data": [
                {
                    "id": 1,
                    "node_id": 7,
                    "node_name": "edge-a",
                    "settings": {"clients": []},
                }
            ],
        },
        start_cache_refresh=lambda *_args: None,
    )
    nodes = [{"id": 7, "name": "edge-a"}]

    assert runtime.get_cached_inbound_options(nodes) == [
        {"detail_level": "option", "id": 1}
    ]
    assert runtime.get_cached_inbound_options(nodes) == [
        {"detail_level": "option", "id": 1}
    ]
    assert runtime.get_cached_slim_inbounds(nodes) == [
        {"detail_level": "slim", "id": 1}
    ]

    assert len(manager.options_calls) == 1
    assert len(manager.slim_calls) == 1
    cached_full = manager.options_calls[0][1]
    assert cached_full["7"][0]["id"] == 1
    assert cached_full["edge-a"][0]["id"] == 1


def test_complete_collector_cycle_seeds_empty_full_cache_without_a_fleet_read():
    class _NoFleetReadManager:
        def get_all_inbounds(self, _nodes):
            raise AssertionError(
                "completed collector snapshot must satisfy the cold route"
            )

    runtime = InboundsRuntime(
        inbound_mgr=_NoFleetReadManager(),
        inbounds_cache={"ts": 0.0, "data": []},
        start_cache_refresh=lambda *_args: None,
    )
    nodes = [{"id": 7, "name": "edge-a", "enabled": True}]
    snapshots = [
        {
            "node_id": 7,
            "name": "edge-a",
            "available": True,
            "timestamp": time.time(),
            "inbounds": [
                {
                    "id": 1,
                    "protocol": "vless",
                    "settings": {"clients": []},
                    "streamSettings": {"security": "reality"},
                }
            ],
        }
    ]

    assert (
        runtime.seed_full_cache_from_completed_collector_cycle(snapshots, nodes) is True
    )
    assert runtime.get_cached_inbounds(nodes)[0] == {
        "id": 1,
        "node_id": 7,
        "node_name": "edge-a",
        "node_ip": "edge-a",
        "protocol": "vless",
        "port": None,
        "remark": "",
        "enable": True,
        "client_count": 0,
        "streamSettings": {"security": "reality"},
        "settings": {"clients": []},
        "security": "reality",
        "is_reality": True,
    }


def test_partial_or_stale_collector_cycle_does_not_seed_full_cache():
    class _FleetReadManager:
        def get_all_inbounds(self, _nodes):
            return [{"id": "live"}]

    runtime = InboundsRuntime(
        inbound_mgr=_FleetReadManager(),
        inbounds_cache={"ts": 0.0, "data": []},
        start_cache_refresh=lambda *_args: None,
    )
    nodes = [
        {"id": 7, "name": "edge-a", "enabled": True},
        {"id": 8, "name": "edge-b", "enabled": True},
    ]
    partial = [
        {
            "node_id": 7,
            "name": "edge-a",
            "available": True,
            "timestamp": time.time(),
            "inbounds": [],
        }
    ]
    stale = [
        {**partial[0], "stale": True},
        {
            "node_id": 8,
            "name": "edge-b",
            "available": True,
            "timestamp": time.time(),
            "inbounds": [],
        },
    ]

    assert (
        runtime.seed_full_cache_from_completed_collector_cycle(partial, nodes) is False
    )
    assert runtime.seed_full_cache_from_completed_collector_cycle(stale, nodes) is False
    assert runtime.get_cached_inbounds(nodes) == [{"id": "live"}]
