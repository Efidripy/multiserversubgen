from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def build_clients_router(
    *,
    check_auth,
    client_mgr,
    get_cached_clients,
    node_service,
    get_node_or_404,
    invalidate_live_stats_cache,
    invalidate_subscription_cache,
):
    router = APIRouter()

    def _load_nodes(node_ids=None):
        if node_ids:
            return [get_node_or_404(node_id) for node_id in node_ids]
        return node_service.list_nodes()

    @router.get("/api/v1/clients")
    async def list_clients(request: Request, email: Optional[str] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = node_service.list_nodes()
        clients = get_cached_clients(nodes, email_filter=email)
        return JSONResponse(
            content={"clients": clients, "count": len(clients)},
            headers={"Cache-Control": "private, max-age=180"},
        )

    @router.get("/api/v1/nodes/{node_id}/clients")
    async def list_node_clients(request: Request, node_id: int, email: Optional[str] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = get_node_or_404(node_id)
        clients = client_mgr.get_all_clients([node], email_filter=email)
        return JSONResponse(
            content={"clients": clients, "count": len(clients)},
            headers={"Cache-Control": "private, max-age=120"},
        )

    @router.post("/api/v1/clients/batch-add")
    async def batch_add_clients(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_ids = data.get("node_ids")
        clients_configs = data.get("clients", [])
        nodes = _load_nodes(node_ids=node_ids)

        results = client_mgr.batch_add_clients(nodes, clients_configs)
        invalidate_live_stats_cache()
        invalidate_subscription_cache()
        return results

    @router.post("/api/v1/clients/add-to-nodes")
    async def add_client_to_nodes(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        email = data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="email is required")

        inbound_id = data.get("inbound_id")
        if inbound_id is None:
            raise HTTPException(status_code=400, detail="inbound_id is required")

        nodes = _load_nodes(node_ids=data.get("node_ids"))

        try:
            results = client_mgr.add_client_to_multiple_nodes(
                nodes=nodes,
                email=email,
                inbound_id=inbound_id,
                flow=data.get("flow", ""),
                totalGB=data.get("totalGB", 0),
                expiryTime=data.get("expiryTime", 0),
                enable=data.get("enable", True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        invalidate_live_stats_cache()
        invalidate_subscription_cache()
        return results

    @router.put("/api/v1/clients/{client_uuid}")
    async def update_client(request: Request, client_uuid: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_id = data.get("node_id")
        inbound_id = data.get("inbound_id")
        updates = data.get("updates", {})

        if not node_id or not inbound_id:
            raise HTTPException(status_code=400, detail="node_id and inbound_id required")

        node = get_node_or_404(node_id)
        success = client_mgr.update_client(node, inbound_id, client_uuid, updates)
        if success:
            invalidate_live_stats_cache()
            invalidate_subscription_cache()
        return {"success": success}

    @router.delete("/api/v1/clients/{client_uuid}")
    async def delete_client(request: Request, client_uuid: str, node_id: int, inbound_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = get_node_or_404(node_id)
        success = client_mgr.delete_client(node, inbound_id, client_uuid)
        if success:
            invalidate_live_stats_cache()
            invalidate_subscription_cache()
        return {"success": success}

    @router.post("/api/v1/clients/batch-delete")
    async def batch_delete_clients(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = _load_nodes(node_ids=data.get("node_ids"))
        results = client_mgr.batch_delete_clients(
            nodes,
            data.get("email_pattern"),
            data.get("expired_only", False),
            data.get("depleted_only", False),
        )
        invalidate_live_stats_cache()
        invalidate_subscription_cache()
        return results

    @router.post("/api/v1/clients/{client_uuid}/reset-traffic")
    async def reset_client_traffic(request: Request, client_uuid: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_id = data.get("node_id")
        inbound_id = data.get("inbound_id")
        email = data.get("email")
        if not all([node_id, inbound_id, email]):
            raise HTTPException(status_code=400, detail="node_id, inbound_id, and email required")

        node = get_node_or_404(node_id)
        success = client_mgr.reset_client_traffic(node, inbound_id, email)
        return {"success": success}

    return router
