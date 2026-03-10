"""AdGuard module – Pydantic models."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class AdGuardSource(BaseModel):
    id: Optional[int] = None
    name: str
    url: str
    username: str = ""
    password: str = ""
    enabled: bool = True


class AdGuardStats(BaseModel):
    source_id: int
    source_name: str
    available: bool = False
    dns_queries: int = 0
    dns_blocked: int = 0
    block_rate: float = 0.0
    latency_ms: float = 0.0
    cache_hit_pct: float = 0.0
    upstream_errors: int = 0
