"""Subscriptions module – Pydantic models."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


class SubscriptionGroup(BaseModel):
    id: Optional[int] = None
    name: str
    identifier: str
    description: str = ""
    email_patterns: List[str] = []
    node_filters: List[str] = []
    protocol_filter: Optional[str] = None
