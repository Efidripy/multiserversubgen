"""Authentication module – FastAPI routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    from .service import AuthService


def build_auth_router(auth_service: "AuthService") -> APIRouter:
    """Return a router with auth-related endpoints.

    Args:
        auth_service: Configured :class:`~modules.auth.service.AuthService`.

    Returns:
        A :class:`fastapi.APIRouter` instance.
    """
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

    @router.get("/verify")
    async def verify_auth(request: Request):
        """Verify that the current request carries valid credentials."""
        user = getattr(request.state, "auth_user", None)
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {
            "authenticated": True,
            "username": user,
            "role": auth_service.get_user_role(user),
        }

    @router.get("/mfa-status")
    async def mfa_status():
        """Return MFA configuration status."""
        return {"enabled": auth_service.mfa_totp_enabled}

    return router
