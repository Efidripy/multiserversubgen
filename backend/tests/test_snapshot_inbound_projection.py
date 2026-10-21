import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inbound_manager import InboundManager
from services.collector import SnapshotCollector
from services.inbounds_runtime import InboundsRuntime


def _collector(snapshot=None):
    collector = SnapshotCollector(fetch_nodes=lambda: [], xui_monitor=None, ws_manager=SimpleNamespace())
    collector._latest = {"timestamp": time.time(), "nodes": {"id:1": snapshot} if snapshot else {}}
    return collector


def _snapshot(**overrides):
    value = {
        "available": True,
        "stale": False,
        "inbounds_available": True,
        "timestamp": time.time(),
        "inbounds": [{"id": 1, "settings": {"clients": []}, "streamSettings": {}}],
    }
    value.update(overrides)
    return value


def test_usable_inbounds_accepts_only_recent_healthy_snapshot():
    collector = _collector(_snapshot())
    node = {"id": 1, "name": "node"}
    assert collector.usable_inbounds(node) == collector._latest["nodes"]["id:1"]["inbounds"]
    for invalid in (
        {"available": False},
        {"stale": True},
        {"inbounds_available": False},
        {"inbounds": {}},
        {"timestamp": time.time() - 601},
    ):
        candidate = _snapshot(**invalid)
        assert _collector(candidate).usable_inbounds(node) is None
    current = time.time()
    assert _collector(_snapshot(timestamp=current)).usable_inbounds(node, not_before=current + 1) is None
    assert _collector().usable_inbounds(node) is None


def test_full_projection_snapshot_matches_live_projection_and_avoids_fetch():
    manager = InboundManager(decrypt_func=lambda value: value)
    node = {"id": 1, "name": "node", "ip": "127.0.0.1"}
    raw = {"id": 4, "protocol": "vless", "settings": {"clients": []}, "streamSettings": {"security": "reality"}}
    manager._fetch_inbounds_from_node = Mock(return_value=[raw])
    live = manager.get_all_inbounds([node])
    manager._fetch_inbounds_from_node = Mock(side_effect=AssertionError("network"))
    snapshot = manager.get_all_inbounds([node], snapshot_inbounds=lambda _node: [raw])
    assert snapshot == live


@pytest.mark.parametrize("method", ["get_all_slim_inbounds", "get_all_inbound_options"])
def test_slim_and_options_use_snapshot_without_network(method):
    manager = InboundManager(decrypt_func=lambda value: value)
    node = {"id": 1, "name": "node", "ip": "127.0.0.1"}
    raw = {"id": 4, "protocol": "vless", "settings": {"clients": []}, "streamSettings": {}}
    manager._fetch_inbounds_from_node = Mock(side_effect=AssertionError("network"))
    manager._read_v3_projection = Mock(side_effect=AssertionError("network"))
    result = getattr(manager, method)([node], snapshot_inbounds=lambda _node: [raw])
    assert result and result[0]["id"] == 4


def test_runtime_callback_reads_invalidation_boundary_at_call_time():
    seen = []

    class Manager:
        def get_all_inbounds(self, nodes, *, snapshot_inbounds=None):
            seen.append(snapshot_inbounds(nodes[0]))
            return []

    timestamp = time.time() - 1

    def usable(_node, not_before):
        return [{"id": 1}] if timestamp >= not_before else None

    runtime = InboundsRuntime(
        inbound_mgr=Manager(),
        inbounds_cache={"ts": 0.0, "data": []},
        start_cache_refresh=lambda *_args: None,
        usable_inbounds=usable,
    )
    node = {"id": 1, "name": "node"}
    runtime.get_cached_inbounds([node])
    runtime.invalidate()
    callback = runtime._full_loader_kwargs()["snapshot_inbounds"]
    assert callback(node) is None
    assert seen == [[{"id": 1}]]
