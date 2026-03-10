"""Statistics module – Pydantic models."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class NodeStats(BaseModel):
    node_id: int
    node_name: Optional[str] = None
    traffic_up_bytes: int = 0
    traffic_down_bytes: int = 0
    traffic_total_bytes: int = 0
    cpu_percent: float = 0.0
    poll_latency_ms: float = 0.0
    available: bool = False
    xray_running: bool = False
    online_clients: int = 0
    extra: Dict[str, Any] = {}


class AggregateStats(BaseModel):
    node_id: int
    node_name: Optional[str] = None
    sample_count: int = 0
    avg_cpu: float = 0.0
    avg_online_clients: float = 0.0
    avg_traffic_total: float = 0.0
    avg_poll_ms: float = 0.0
    availability_ratio: float = 0.0
    xray_running_ratio: float = 0.0
    period_start: Optional[int] = None
    period_end: Optional[int] = None
