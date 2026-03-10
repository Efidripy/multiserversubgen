"""Monthly statistics aggregator."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional


class MonthlyAggregator:
    """Aggregate node_history records into monthly summaries."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def aggregate(
        self,
        node_id: Optional[int] = None,
        months_back: int = 3,
    ) -> List[Dict[str, Any]]:
        cutoff = int(time.time()) - months_back * 30 * 86400
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
