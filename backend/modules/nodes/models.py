"""Node management – Pydantic models."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class NodeCreate(BaseModel):
    name: str
    ip: str
    port: str
    user: str
    password: str
    base_path: Optional[str] = ""


class NodeUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    base_path: Optional[str] = None


class NodeResponse(BaseModel):
    id: int
    name: str
    ip: str
    port: str
    user: str
    base_path: str = ""
