from typing import Callable, Dict

from fastapi import APIRouter, HTTPException, Request


def build_live_data_router(
    *,
    get_node_or_404: Callable[[int], Dict],
    get_cached_traffic_stats: Callable[[list, str], Dict],
    get_cached_online_clients: Callable[[list], list],
    list_nodes: Callable[[], list],
    xui_monitor,
):
    router = APIRouter()

    @router.get("/api/v1/traffic/stats")
    async def get_traffic_stats(request: Request, group_by: str = "client"):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if group_by not in ["client", "inbound", "node"]:
            raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
        nodes = list_nodes()
        return get_cached_traffic_stats(nodes, group_by)

    @router.get("/api/v1/clients/online")
    async def get_online_clients(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        nodes = list_nodes()
        online = get_cached_online_clients(nodes)
        return {"online_clients": online, "count": len(online)}

    @router.get("/api/v1/dashboard/summary")
    async def get_dashboard_summary(request: Request):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        nodes = list_nodes()
        traffic = get_cached_traffic_stats(nodes, "client").get("stats", {})
        online = get_cached_online_clients(nodes)
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
        node = get_node_or_404(node_id)
        return xui_monitor.get_server_status(node)

    @router.get("/api/v1/nodes/{node_id}/traffic")
    async def get_node_traffic(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = get_node_or_404(node_id)
        return xui_monitor.get_traffic(node)

    @router.get("/api/v1/nodes/{node_id}/inbounds")
    async def get_node_inbounds(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = get_node_or_404(node_id)
        return xui_monitor.get_inbounds(node)

    @router.get("/api/v1/nodes/{node_id}/online-clients")
    async def get_node_online_clients(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = get_node_or_404(node_id)
        return xui_monitor.get_online_clients(node)

    @router.get("/api/v1/nodes/{node_id}/client/{email}/traffic")
    async def get_node_client_traffic(request: Request, node_id: int, email: str):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = get_node_or_404(node_id)
        return xui_monitor.get_client_traffic(node, email)

    return router
