from typing import Callable, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response


def build_observability_router(
    *,
    get_latest_snapshot: Callable[[], Dict],
    render_metrics: Callable[[], Response],
    get_deps_health: Callable[[], Dict],
):
    router = APIRouter()

    @router.get("/api/v1/snapshots/latest")
    async def snapshots_latest(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return get_latest_snapshot()

    @router.get("/metrics")
    async def metrics():
        return render_metrics()

    @router.get("/api/v1/health/deps")
    async def health_deps(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return get_deps_health()

    return router
