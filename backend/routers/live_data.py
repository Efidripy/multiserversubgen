import time
from typing import Callable, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import ORJSONResponse


def build_live_data_router(
    *,
    get_node_or_404: Callable[[int], Dict],
    get_cached_traffic_stats: Callable[[list, str], Dict],
    get_cached_online_clients: Callable[[list], list],
    list_nodes: Callable[[], list],
    xui_monitor,
    get_latest_snapshot: Callable[[], Dict] = None,
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

    def _latest_snapshot_payload() -> Dict:
        if not get_latest_snapshot:
            return {"timestamp": None, "nodes": [], "count": 0}
        payload = get_latest_snapshot()
        return payload if isinstance(payload, dict) else {"timestamp": None, "nodes": [], "count": 0}

    def _snapshot_by_node(nodes: list) -> tuple[Dict[str, Dict], Dict[str, Dict], Dict]:
        snapshot = _latest_snapshot_payload()
        snapshot_nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else []
        by_id: Dict[str, Dict] = {}
        by_name: Dict[str, Dict] = {}
        if isinstance(snapshot_nodes, list):
            for item in snapshot_nodes:
                if not isinstance(item, dict):
                    continue
                node_id = item.get("node_id")
                name = item.get("name") or item.get("node")
                if node_id is not None:
                    by_id[str(node_id)] = item
                if name:
                    by_name[str(name)] = item
        return by_id, by_name, snapshot

    def _snapshot_for_node(node: Dict, by_id: Dict[str, Dict], by_name: Dict[str, Dict]) -> Dict | None:
        node_id = node.get("id")
        if node_id is not None and str(node_id) in by_id:
            return by_id[str(node_id)]
        name = node.get("name")
        if name and str(name) in by_name:
            return by_name[str(name)]
        return None

    @router.get("/api/v1/traffic/stats")
    async def get_traffic_stats(request: Request, group_by: str = "client", limit: int = 0):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if group_by not in ["client", "inbound", "node"]:
            raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
        nodes = await run_in_threadpool(list_nodes)
        payload = await run_in_threadpool(get_cached_traffic_stats, nodes, group_by)
        return ORJSONResponse(content=_apply_limit(payload, limit))

    @router.get("/api/v1/clients/online")
    async def get_online_clients(request: Request, limit: int = 0):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(list_nodes)
        online = await run_in_threadpool(get_cached_online_clients, nodes)
        if limit > 0:
            online = online[:limit]
        return ORJSONResponse(content={"online_clients": online, "count": len(online)})

    @router.get("/api/v1/dashboard/summary")
    async def get_dashboard_summary(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(list_nodes)
        by_id, by_name, snapshot = _snapshot_by_node(nodes)
        online_by_node: Dict[str, int] = {}
        total_traffic = 0
        online_total = 0
        online_nodes = 0
        for node in nodes:
            cached = _snapshot_for_node(node, by_id, by_name)
            node_name = node.get("name") or str(node.get("id"))
            if not isinstance(cached, dict):
                online_by_node[node_name] = 0
                continue
            online_count = int(cached.get("online_clients") or 0)
            online_by_node[node_name] = online_count
            online_total += online_count
            if cached.get("available"):
                online_nodes += 1
            total_traffic += int(cached.get("traffic_total") or 0)
        return ORJSONResponse(content={
            "nodes_total": len(nodes),
            "nodes_online": online_nodes,
            "clients_total": 0,
            "online_clients_total": online_total,
            "online_by_node": online_by_node,
            "traffic": {
                "upload": 0,
                "download": 0,
                "total": total_traffic,
            },
            "top_clients": [],
            "cache": {
                "source": "snapshot_collector",
                "timestamp": snapshot.get("timestamp"),
                "age_sec": round(time.time() - snapshot["timestamp"], 2) if snapshot.get("timestamp") else None,
                "ready": bool(snapshot.get("nodes")),
            },
        })

    @router.get("/api/v1/nodes/{node_id}/server-status")
    async def get_node_server_status(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        by_id, by_name, _snapshot = _snapshot_by_node([node])
        cached = _snapshot_for_node(node, by_id, by_name)
        if not isinstance(cached, dict):
            return ORJSONResponse(content={
                "node": node.get("name"),
                "node_id": node_id,
                "available": False,
                "status": "offline",
                "reason": "snapshot_not_ready",
                "error": "Status has not been collected yet",
                "cached": True,
            })
        server_status = cached.get("server_status")
        if isinstance(server_status, dict):
            payload = dict(server_status)
        else:
            payload = {
                "node": cached.get("name") or node.get("name"),
                "node_id": cached.get("node_id") or node_id,
                "available": bool(cached.get("available")),
                "status": cached.get("status") or ("online" if cached.get("available") else "offline"),
                "reason": cached.get("reason") or ("ok" if cached.get("available") else "unknown"),
                "error": cached.get("error", ""),
                "xray": {"running": bool(cached.get("xray_running"))},
                "system": {"cpu": cached.get("cpu", 0)},
                "network": {"upload": 0, "download": cached.get("traffic_total", 0)},
                "panel_version": cached.get("panel_version", ""),
            }
        payload.setdefault("node_id", cached.get("node_id") or node_id)
        payload["cached"] = True
        payload["snapshot_timestamp"] = cached.get("timestamp")
        payload["poll_ms"] = cached.get("poll_ms")
        if cached.get("circuit_open_until"):
            payload["circuit_open_until"] = cached.get("circuit_open_until")
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/traffic")
    async def get_node_traffic(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_traffic, node)
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/inbounds")
    async def get_node_inbounds(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_inbounds, node)
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/online-clients")
    async def get_node_online_clients(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_online_clients, node)
        return ORJSONResponse(content=payload)

    async def _get_node_client_traffic_impl(request: Request, node_id: int, email: str):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_client_traffic, node, email)
        return ORJSONResponse(content=payload)

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
            return ORJSONResponse(content=_apply_limit(payload, limit))
        
        nodes = await run_in_threadpool(list_nodes)
        payload = await run_in_threadpool(period_stats_handler, nodes, group_by, period)
        return ORJSONResponse(content=_apply_limit(payload, limit))

    return router
