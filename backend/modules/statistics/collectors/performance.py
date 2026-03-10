"""Performance statistics collector.

Reads CPU usage and poll latency from the latest node snapshot.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseCollector


class PerformanceCollector(BaseCollector):
    """Collects CPU and poll latency metrics from node snapshots."""

    name = "performance"

    def __init__(self, snapshot_provider=None) -> None:
        self._snapshot_provider = snapshot_provider

    async def collect(self, node_id: int, node: Dict[str, Any]) -> Dict[str, Any]:
        if not self._snapshot_provider:
            return {"cpu_percent": 0.0, "poll_latency_ms": 0.0}

        latest = self._snapshot_provider()
        nodes_data = latest.get("nodes", {})
        node_snapshot = nodes_data.get(str(node_id), {})

        return {
            "cpu_percent": float(node_snapshot.get("cpu", 0) or 0),
            "poll_latency_ms": float(node_snapshot.get("poll_ms", 0) or 0),
        }
