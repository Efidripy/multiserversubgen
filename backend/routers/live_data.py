from typing import Callable, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool


def build_live_data_router(
    *,
    get_node_or_404: Callable[[int], Dict],
    get_cached_traffic_stats: Callable[[list, str], Dict],
    get_cached_online_clients: Callable[[list], list],
    list_nodes: Callable[[], list],
    xui_monitor,
    get_traffic_stats_by_period: Callable[[list, str, str], Dict] = None,
):
    router = APIRouter()
    period_stats_handler = get_traffic_stats_by_period

    def _apply_limit(payload: Dict, limit: int) -> Dict:
        if limit <= 0:
            return payload
        stats = payload.get("stats") if isinstance(payload, dict) else None
        if not isinstance(stats, dict):
            return payload

        top_items = sorted(
            stats.items(),
            key=lambda item: float(
                (item[1] or {}).get("total")
                or ((item[1] or {}).get("up", 0) + (item[1] or {}).get("down", 0))
            ),
            reverse=True,
        )[:limit]

        trimmed = dict(payload)
        trimmed["stats"] = dict(top_items)
        trimmed["count"] = len(top_items)
        return trimmed

    @router.get("/api/v1/traffic/stats")
    async def get_traffic_stats(request: Request, group_by: str = "client", limit: int = 0):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if group_by not in ["client", "inbound", "node"]:
            raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
        nodes = await run_in_threadpool(list_nodes)
        payload = await run_in_threadpool(get_cached_traffic_stats, nodes, group_by)
        return _apply_limit(payload, limit)

    @router.get("/api/v1/clients/online")
    async def get_online_clients(request: Request, limit: int = 0):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(list_nodes)
        online = await run_in_threadpool(get_cached_online_clients, nodes)
        if limit > 0:
            online = online[:limit]
        return {"online_clients": online, "count": len(online)}

    @router.get("/api/v1/dashboard/summary")
    async def get_dashboard_summary(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(list_nodes)
        traffic_data = await run_in_threadpool(get_cached_traffic_stats, nodes, "client")
        traffic = traffic_data.get("stats", {})
        online = await run_in_threadpool(get_cached_online_clients, nodes)
        total_upload = sum(v.get("up", 0) for v in traffic.values())
        total_download = sum(v.get("down", 0) for v in traffic.values())
        top_clients = sorted(
            (
                {"email": k, "upload": v.get("up", 0), "download": v.get("down", 0), "total": v.get("total", 0)}
                for k, v in traffic.items()
            ),
            key=lambda x: x["total"],
            reverse=True,
        )[:5]
        return {
            "nodes_total": len(nodes),
            "clients_total": len(traffic),
            "online_clients_total": len(online),
            "traffic": {
                "upload": total_upload,
                "download": total_download,
                "total": total_upload + total_download,
            },
            "top_clients": top_clients,
        }

    @router.get("/api/v1/nodes/{node_id}/server-status")
    async def get_node_server_status(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        return await run_in_threadpool(xui_monitor.get_server_status, node)

    @router.get("/api/v1/nodes/{node_id}/traffic")
    async def get_node_traffic(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        return await run_in_threadpool(xui_monitor.get_traffic, node)

    @router.get("/api/v1/nodes/{node_id}/inbounds")
    async def get_node_inbounds(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        return await run_in_threadpool(xui_monitor.get_inbounds, node)

    @router.get("/api/v1/nodes/{node_id}/online-clients")
    async def get_node_online_clients(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        return await run_in_threadpool(xui_monitor.get_online_clients, node)

    async def _get_node_client_traffic_impl(request: Request, node_id: int, email: str):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        return await run_in_threadpool(xui_monitor.get_client_traffic, node, email)

    @router.get("/api/v1/nodes/{node_id}/client-traffic")
    async def get_node_client_traffic_query(request: Request, node_id: int, email: str):
        # Query-param variant is robust for arbitrary client identifiers.
        return await _get_node_client_traffic_impl(request, node_id, email)

    @router.get("/api/v1/nodes/{node_id}/client/{email:path}/traffic")
    async def get_node_client_traffic_legacy(request: Request, node_id: int, email: str):
        # Backward-compatible path-based endpoint.
        return await _get_node_client_traffic_impl(request, node_id, email)

    @router.get("/api/v1/traffic/stats-by-period")
    async def get_traffic_stats_period(request: Request, group_by: str = "client", period: str = "all_time", limit: int = 0):
        """Get traffic stats for a specific period (day, week, month, year, all_time)"""
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if group_by not in ["client", "inbound", "node"]:
            raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
        if period not in ["day", "week", "month", "year", "all_time"]:
            raise HTTPException(status_code=400, detail="period must be day, week, month, year, or all_time")
        
        if not period_stats_handler:
            # Fallback to regular stats if handler not provided
            nodes = await run_in_threadpool(list_nodes)
            payload = await run_in_threadpool(get_cached_traffic_stats, nodes, group_by)
            return _apply_limit(payload, limit)
        
        nodes = await run_in_threadpool(list_nodes)
        payload = await run_in_threadpool(period_stats_handler, nodes, group_by, period)
        return _apply_limit(payload, limit)

    return router
