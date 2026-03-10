"""Monitoring module – FastAPI routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    from .health_checks import HealthCheckService


def build_monitoring_router(health_service: "HealthCheckService") -> APIRouter:
    router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])

    @router.get("/health")
    async def full_health(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Unauthorized")
        return await health_service.check_all()

    return router
