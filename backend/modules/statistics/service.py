"""Statistics service – orchestrates collectors and aggregators."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .collectors.base import BaseCollector

logger = logging.getLogger(__name__)


class StatisticsService:
    """Runs all registered collectors for each node and aggregates results.

    Collectors can be registered at startup or added at runtime (plugin
    pattern).  The service is intentionally decoupled from both the node
    list and the collector implementations.

    Args:
        db_path: Path to the SQLite database for aggregators.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._collectors: List[BaseCollector] = []

    # ------------------------------------------------------------------
    # Collector registration (plugin pattern)
    # ------------------------------------------------------------------

    def register_collector(self, collector: BaseCollector) -> None:
        """Register a new metrics collector.

        Args:
            collector: Any :class:`BaseCollector` subclass instance.
        """
        self._collectors.append(collector)
        logger.info("StatisticsService: registered collector '%s'", collector.name)

    def get_collector(self, name: str) -> Optional[BaseCollector]:
        """Return the collector registered under *name*, or ``None``."""
        return next((c for c in self._collectors if c.name == name), None)

    def list_collectors(self) -> List[str]:
        """Return the names of all registered collectors."""
        return [c.name for c in self._collectors if c.enabled]

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    async def collect_all(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run all enabled collectors for every node concurrently.

        Args:
            nodes: List of node dicts (id, name, …).

        Returns:
            List of per-node result dicts, keyed by node_id.
        """
        results = await asyncio.gather(
            *[self._collect_node(node) for node in nodes],
            return_exceptions=True,
        )
        out = []
        for node, result in zip(nodes, results):
            if isinstance(result, Exception):
                logger.warning(
                    "StatisticsService: collection failed for node %s: %s",
                    node.get("id"),
                    result,
                )
                out.append({"node_id": node.get("id"), "error": str(result)})
            else:
                out.append(result)
        return out

    async def _collect_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        node_id = node["id"]
        merged: Dict[str, Any] = {"node_id": node_id, "node_name": node.get("name")}
        for collector in self._collectors:
            if not collector.enabled:
                continue
            try:
                data = await collector.collect(node_id, node)
                merged.update(data)
            except Exception as exc:
                logger.warning(
                    "StatisticsService: collector '%s' failed for node %s: %s",
                    collector.name,
                    node_id,
                    exc,
                )
        return merged

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def get_hourly_stats(
        self, *, node_id: Optional[int] = None, hours_back: int = 1
    ) -> List[Dict]:
        from .aggregators.hourly import HourlyAggregator
        return HourlyAggregator(self._db_path).aggregate(
            node_id=node_id, hours_back=hours_back
        )

    def get_daily_stats(
        self, *, node_id: Optional[int] = None, days_back: int = 7
    ) -> List[Dict]:
        from .aggregators.daily import DailyAggregator
        return DailyAggregator(self._db_path).aggregate(
            node_id=node_id, days_back=days_back
        )

    def get_monthly_stats(
        self, *, node_id: Optional[int] = None, months_back: int = 3
    ) -> List[Dict]:
        from .aggregators.monthly import MonthlyAggregator
        return MonthlyAggregator(self._db_path).aggregate(
            node_id=node_id, months_back=months_back
        )
