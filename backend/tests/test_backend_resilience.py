import asyncio
import os
import sys
import time
from types import SimpleNamespace


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_xui_timeout_is_hard_capped():
    from xui_session import bounded_xui_timeout

    connect_timeout, read_timeout = bounded_xui_timeout(180)

    assert connect_timeout <= 3.0
    assert read_timeout <= 4.0


def test_snapshot_collector_opens_timeout_circuit():
    from services.collector import SnapshotCollector

    class TimeoutMonitor:
        def get_server_status(self, node):
            return {
                "node": node["name"],
                "available": False,
                "status": "offline",
                "reason": "request_failed",
                "error": "HTTPSConnectionPool(host='h1n1.kleva.ru'): Read timed out.",
            }

    collector = SnapshotCollector(
        fetch_nodes=lambda: [],
        xui_monitor=TimeoutMonitor(),
        ws_manager=SimpleNamespace(active_connections=[]),
        degraded_backoff_sec=300,
    )
    collector._node_state["Server-6"] = {
        "next_poll": 0.0,
        "interval": 60.0,
        "failures": 0,
        "stable_cycles": 0,
        "last_hash": "",
        "circuit_until": 0.0,
    }

    asyncio.run(
        collector._poll_node(
            {"id": 6, "name": "Server-6"},
            "Server-6",
            asyncio.Semaphore(1),
        )
    )

    state = collector._node_state["Server-6"]
    snapshot = collector._latest["nodes"]["Server-6"]

    assert state["interval"] == 300.0
    assert state["circuit_until"] > time.time()
    assert snapshot["available"] is False
    assert snapshot["status"] == "offline"
    assert snapshot["reason"] == "timeout"
