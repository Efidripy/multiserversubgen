"""Statistics module – FastAPI routes."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

if TYPE_CHECKING:
    from .service import StatisticsService


def build_statistics_router(service: "StatisticsService") -> APIRouter:
    router = APIRouter(prefix="/api/v1/statistics", tags=["statistics"])

    def _check_auth(request: Request) -> str:
        user = getattr(request.state, "auth_user", None)
        if not user:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user

    @router.get("/collectors")
    async def list_collectors(request: Request):
        _check_auth(request)
        return {"collectors": service.list_collectors()}

    @router.get("/history/hourly")
    async def hourly_stats(
        request: Request,
        node_id: Optional[int] = None,
        hours_back: int = 1,
    ):
        _check_auth(request)
        data = await run_in_threadpool(
            service.get_hourly_stats, node_id=node_id, hours_back=hours_back
        )
        return {"data": data, "count": len(data)}

    @router.get("/history/daily")
    async def daily_stats(
        request: Request,
        node_id: Optional[int] = None,
        days_back: int = 7,
    ):
        _check_auth(request)
        data = await run_in_threadpool(
            service.get_daily_stats, node_id=node_id, days_back=days_back
        )
        return {"data": data, "count": len(data)}

    @router.get("/history/monthly")
    async def monthly_stats(
        request: Request,
        node_id: Optional[int] = None,
        months_back: int = 3,
    ):
        _check_auth(request)
        data = await run_in_threadpool(
            service.get_monthly_stats, node_id=node_id, months_back=months_back
        )
        return {"data": data, "count": len(data)}

    return router
