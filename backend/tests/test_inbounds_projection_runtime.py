"""Cache boundaries for read-only inbound projections."""

import time

from services.inbounds_runtime import InboundsRuntime


class _InboundManager:
    def __init__(self):
        self.options_calls = []
        self.slim_calls = []

    def get_all_inbounds(self, _nodes):
        raise AssertionError("projection cache must not cold-fetch the full inbound DTO")

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
            "data": [{"id": 1, "node_id": 7, "node_name": "edge-a", "settings": {"clients": []}}],
        },
        start_cache_refresh=lambda *_args: None,
    )
    nodes = [{"id": 7, "name": "edge-a"}]

    assert runtime.get_cached_inbound_options(nodes) == [{"detail_level": "option", "id": 1}]
    assert runtime.get_cached_inbound_options(nodes) == [{"detail_level": "option", "id": 1}]
    assert runtime.get_cached_slim_inbounds(nodes) == [{"detail_level": "slim", "id": 1}]

    assert len(manager.options_calls) == 1
    assert len(manager.slim_calls) == 1
    cached_full = manager.options_calls[0][1]
    assert cached_full["7"][0]["id"] == 1
    assert cached_full["edge-a"][0]["id"] == 1
