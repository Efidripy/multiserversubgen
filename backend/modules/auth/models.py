"""Authentication module – Pydantic models."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None


class LoginResponse(BaseModel):
    status: str
    username: str
    role: str


class MFAStatusResponse(BaseModel):
    enabled: bool
    required_for_user: bool
