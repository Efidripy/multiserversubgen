"""Node management – Pydantic models."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class NodeCreate(BaseModel):
    name: str
    ip: str
    port: str
    user: str
    password: str
    base_path: Optional[str] = ""
    tags: Optional[List[str]] = None


class NodeUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    base_path: Optional[str] = None
    tags: Optional[List[str]] = None


class NodeResponse(BaseModel):
    id: int
    name: str
    ip: str
    port: str
    user: str
    base_path: str = ""
    tags: List[str] = Field(default_factory=list)
