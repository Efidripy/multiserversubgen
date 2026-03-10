"""Monitoring module – Pydantic models."""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel


class HealthCheckResult(BaseModel):
    module: str
    state: str
    message: str = ""
    details: Dict[str, Any] = {}


class SystemHealthResponse(BaseModel):
    overall: str
    modules: Dict[str, HealthCheckResult] = {}
