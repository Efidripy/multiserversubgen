from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def build_inbounds_router(
    *,
    check_auth,
    inbound_mgr,
    node_service,
    get_node_or_404,
    invalidate_subscription_cache,
    invalidate_live_stats_cache,
    ws_manager,
):
    router = APIRouter()

    def _load_nodes(node_ids=None, exclude_node_id=None):
        nodes = node_service.list_nodes()
        if node_ids:
            node_id_set = {int(node_id) for node_id in node_ids}
            return [node for node in nodes if int(node.get("id")) in node_id_set]
        if exclude_node_id is not None:
            return [node for node in nodes if int(node.get("id")) != int(exclude_node_id)]
        return nodes

    @router.get("/api/v1/inbounds")
    async def list_inbounds(request: Request, protocol: Optional[str] = None, security: Optional[str] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = node_service.list_nodes()
        inbounds = inbound_mgr.get_all_inbounds(nodes)

        if protocol:
            inbounds = [ib for ib in inbounds if ib["protocol"] == protocol]
        if security:
            inbounds = [ib for ib in inbounds if ib["security"] == security]

        return JSONResponse(
            content={"inbounds": inbounds, "count": len(inbounds)},
            headers={"Cache-Control": "private, max-age=300"},
        )

    @router.post("/api/v1/inbounds")
    async def add_inbound(request: Request, config: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        config = dict(config)
        node_ids = config.pop("node_ids", None)
        nodes = _load_nodes(node_ids=node_ids)

        results = []
        for node in nodes:
            success = inbound_mgr.add_inbound(node, config)
            results.append({"node": node["name"], "success": success})

        if any(r.get("success") for r in results):
            invalidate_subscription_cache()
            invalidate_live_stats_cache()

        return {"results": results}

    @router.post("/api/v1/inbounds/clone")
    async def clone_inbound(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        source_node_id = data.get("source_node_id")
        source_inbound_id = data.get("source_inbound_id")
        target_node_ids = data.get("target_node_ids")
        modifications = data.get("modifications", {})

        if not source_node_id or not source_inbound_id:
            raise HTTPException(status_code=400, detail="source_node_id and source_inbound_id required")

        source_node = get_node_or_404(source_node_id)

        if target_node_ids:
            target_nodes = _load_nodes(node_ids=target_node_ids)
        else:
            target_nodes = _load_nodes(exclude_node_id=source_node_id)

        result = inbound_mgr.clone_inbound(source_node, source_inbound_id, target_nodes, modifications)
        if any(r.get("success") for r in result.get("results", [])):
            invalidate_subscription_cache()
            invalidate_live_stats_cache()
        return result

    @router.delete("/api/v1/inbounds/{inbound_id}")
    async def delete_inbound(request: Request, inbound_id: int, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = get_node_or_404(node_id)

        success = inbound_mgr.delete_inbound(node, inbound_id)
        if success:
            invalidate_subscription_cache()
            invalidate_live_stats_cache()
        return {"success": success}

    @router.post("/api/v1/inbounds/batch-enable")
    async def batch_enable_inbounds(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_ids = data.get("node_ids")
        inbound_ids = data.get("inbound_ids", [])
        enable = data.get("enable", True)

        if not inbound_ids:
            raise HTTPException(status_code=400, detail="inbound_ids required")

        nodes = _load_nodes(node_ids=node_ids)
        result = inbound_mgr.batch_enable_inbounds(nodes, inbound_ids, enable)

        if result.get("successful", 0) > 0:
            invalidate_subscription_cache()
            invalidate_live_stats_cache()

        await ws_manager.broadcast_inbound_update({"action": "batch_enable", "result": result})
        return result

    @router.post("/api/v1/inbounds/batch-update")
    async def batch_update_inbounds(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_ids = data.get("node_ids")
        inbound_ids = data.get("inbound_ids", [])
        updates = data.get("updates", {})

        if not inbound_ids:
            raise HTTPException(status_code=400, detail="inbound_ids required")

        nodes = _load_nodes(node_ids=node_ids)
        result = inbound_mgr.batch_update_inbounds(nodes, inbound_ids, updates)

        if result.get("successful", 0) > 0:
            invalidate_subscription_cache()
            invalidate_live_stats_cache()

        await ws_manager.broadcast_inbound_update({"action": "batch_update", "result": result})
        return result

    @router.post("/api/v1/inbounds/batch-delete")
    async def batch_delete_inbounds(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_ids = data.get("node_ids")
        inbound_ids = data.get("inbound_ids", [])

        if not inbound_ids:
            raise HTTPException(status_code=400, detail="inbound_ids required")

        nodes = _load_nodes(node_ids=node_ids)
        result = inbound_mgr.batch_delete_inbounds(nodes, inbound_ids)

        if result.get("successful", 0) > 0:
            invalidate_subscription_cache()
            invalidate_live_stats_cache()

        await ws_manager.broadcast_inbound_update({"action": "batch_delete", "result": result})
        return result

    return router
