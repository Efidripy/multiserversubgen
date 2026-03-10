"""Traffic statistics collector.

Reads upload/download totals from the latest node snapshot and
normalises them into the statistics schema.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseCollector


class TrafficCollector(BaseCollector):
    """Collects traffic (upload + download bytes) from node snapshots."""

    name = "traffic"

    def __init__(self, snapshot_provider=None) -> None:
        """Args:
            snapshot_provider: Callable that returns the latest snapshot dict.
                When ``None`` the collector returns zeroed metrics.
        """
        self._snapshot_provider = snapshot_provider

    async def collect(self, node_id: int, node: Dict[str, Any]) -> Dict[str, Any]:
        if not self._snapshot_provider:
            return {"traffic_up_bytes": 0, "traffic_down_bytes": 0, "traffic_total_bytes": 0}

        latest = self._snapshot_provider()
        nodes_data = latest.get("nodes", {})
        node_snapshot = nodes_data.get(str(node_id), {})

        return {
            "traffic_up_bytes": node_snapshot.get("traffic_up", 0),
            "traffic_down_bytes": node_snapshot.get("traffic_down", 0),
            "traffic_total_bytes": node_snapshot.get("traffic_total", 0),
        }
