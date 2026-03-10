"""Polling module – Pydantic models."""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class PollingStrategy(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    ADAPTIVE = "adaptive"


class PollingConfig(BaseModel):
    interval_sec: int = 300
    timeout_sec: int = 30
    strategy: PollingStrategy = PollingStrategy.ADAPTIVE
    retry_attempts: int = 3
    max_parallel: int = 4


class PollResult(BaseModel):
    node_id: int
    node_name: str
    success: bool
    duration_ms: float
    error: Optional[str] = None
