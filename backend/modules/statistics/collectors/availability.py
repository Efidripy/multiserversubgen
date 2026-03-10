"""Availability statistics collector.

Reads availability and Xray-running status from the latest node snapshot.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseCollector


class AvailabilityCollector(BaseCollector):
    """Collects node availability and service status from snapshots."""

    name = "availability"

    def __init__(self, snapshot_provider=None) -> None:
        self._snapshot_provider = snapshot_provider

    async def collect(self, node_id: int, node: Dict[str, Any]) -> Dict[str, Any]:
        if not self._snapshot_provider:
            return {"available": False, "xray_running": False, "online_clients": 0}

        latest = self._snapshot_provider()
        nodes_data = latest.get("nodes", {})
        node_snapshot = nodes_data.get(str(node_id), {})

        return {
            "available": bool(node_snapshot.get("available", False)),
            "xray_running": bool(node_snapshot.get("xray_running", False)),
            "online_clients": int(node_snapshot.get("online_clients", 0) or 0),
        }
