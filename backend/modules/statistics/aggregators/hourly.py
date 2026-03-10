"""Hourly statistics aggregator.

Reads node_history records from the last hour and computes aggregate
metrics (averages, totals, min/max).
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional


class HourlyAggregator:
    """Aggregate node_history records into hourly summaries.

    Args:
        db_path: Path to the SQLite database.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def aggregate(
        self,
        node_id: Optional[int] = None,
        hours_back: int = 1,
    ) -> List[Dict[str, Any]]:
        """Return per-node hourly aggregates.

        Args:
            node_id: If provided, limit results to this node.
            hours_back: How many hours of history to include.

        Returns:
            List of aggregate dicts, one per node.
        """
        cutoff = int(time.time()) - hours_back * 3600
        query = """
            SELECT
                node_id,
                node_name,
                COUNT(*) as sample_count,
                AVG(cpu) as avg_cpu,
                AVG(online_clients) as avg_online_clients,
                AVG(traffic_total) as avg_traffic_total,
                AVG(poll_ms) as avg_poll_ms,
                AVG(available) as availability_ratio,
                AVG(xray_running) as xray_running_ratio,
                MIN(ts) as period_start,
                MAX(ts) as period_end
            FROM node_history
            WHERE ts >= ?
        """
        params: list = [cutoff]
        if node_id is not None:
            query += " AND node_id = ?"
            params.append(node_id)
        query += " GROUP BY node_id, node_name"

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]
