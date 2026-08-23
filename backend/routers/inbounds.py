from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import ORJSONResponse


def build_inbounds_router(
    *,
    check_auth,
    inbound_mgr,
    get_cached_inbounds,
    get_cached_slim_inbounds,
    get_cached_inbound_options,
    node_service,
    get_node_or_404,
    invalidate_subscription_cache,
    invalidate_live_stats_cache,
    ws_manager,
):
    router = APIRouter()

    async def _load_nodes(node_ids=None, exclude_node_id=None):
        nodes = await run_in_threadpool(node_service.list_nodes)
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

        nodes = await run_in_threadpool(node_service.list_nodes)
        inbounds = await run_in_threadpool(get_cached_inbounds, nodes)

        if protocol:
            inbounds = [ib for ib in inbounds if ib.get("protocol") == protocol]
        if security:
            inbounds = [ib for ib in inbounds if ib.get("security") == security]

        return ORJSONResponse(
            content={"inbounds": inbounds, "count": len(inbounds)},
            headers={"Cache-Control": "private, max-age=30"},
        )

    @router.get("/api/v1/inbounds/stats")
    async def get_inbound_stats(request: Request):
        """Return aggregate stats: total count, by protocol, by security, enabled vs disabled."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(node_service.list_nodes)
        inbounds = await run_in_threadpool(get_cached_inbounds, nodes)
        by_protocol: dict = {}
        by_security: dict = {}
        enabled = sum(1 for ib in inbounds if ib.get("enable"))
        for ib in inbounds:
            p = ib.get("protocol", "unknown")
            by_protocol[p] = by_protocol.get(p, 0) + 1
            s = "reality" if ib.get("is_reality") else (ib.get("security") or "none")
            by_security[s] = by_security.get(s, 0) + 1
        return {
            "total": len(inbounds),
            "enabled": enabled,
            "disabled": len(inbounds) - enabled,
            "by_protocol": by_protocol,
            "by_security": by_security,
        }

    @router.get("/api/v1/inbounds/slim")
    async def list_slim_inbounds(request: Request):
        """List-only projection; never suitable as an inbound edit payload."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(node_service.list_nodes)
        inbounds = await run_in_threadpool(get_cached_slim_inbounds, nodes)
        return ORJSONResponse(
            content={"detail_level": "slim", "inbounds": inbounds, "count": len(inbounds)},
            headers={"Cache-Control": "private, max-age=30"},
        )

    @router.get("/api/v1/inbounds/options")
    async def list_inbound_options(request: Request):
        """Small picker projection, intentionally excluding settings/client stats."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await run_in_threadpool(node_service.list_nodes)
        options = await run_in_threadpool(get_cached_inbound_options, nodes)
        return ORJSONResponse(
            content={"detail_level": "option", "inbounds": options, "count": len(options)},
            headers={"Cache-Control": "private, max-age=30"},
        )

    @router.post("/api/v1/inbounds")
    async def add_inbound(request: Request, config: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        config = dict(config)
        node_ids = config.pop("node_ids", None)
        nodes = await _load_nodes(node_ids=node_ids)

        results = []
        for node in nodes:
            success = await run_in_threadpool(inbound_mgr.add_inbound, node, config)
            results.append({"node": node["name"], "success": success})

        if any(r.get("success") for r in results):
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)

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

        source_node = await run_in_threadpool(get_node_or_404, source_node_id)

        if target_node_ids:
            target_nodes = await _load_nodes(node_ids=target_node_ids)
        else:
            target_nodes = await _load_nodes(exclude_node_id=source_node_id)

        result = await run_in_threadpool(
            inbound_mgr.clone_inbound, source_node, source_inbound_id, target_nodes, modifications
        )
        if any(r.get("success") for r in result.get("results", [])):
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)
        return result

    @router.delete("/api/v1/inbounds/{inbound_id}")
    async def delete_inbound(request: Request, inbound_id: int, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = await run_in_threadpool(get_node_or_404, node_id)

        success = await run_in_threadpool(inbound_mgr.delete_inbound, node, inbound_id)
        if success:
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)
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

        nodes = await _load_nodes(node_ids=node_ids)
        result = await run_in_threadpool(inbound_mgr.batch_enable_inbounds, nodes, inbound_ids, enable)

        if result.get("successful", 0) > 0:
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)

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

        nodes = await _load_nodes(node_ids=node_ids)
        result = await run_in_threadpool(inbound_mgr.batch_update_inbounds, nodes, inbound_ids, updates)

        if result.get("successful", 0) > 0:
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)

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

        nodes = await _load_nodes(node_ids=node_ids)
        result = await run_in_threadpool(inbound_mgr.batch_delete_inbounds, nodes, inbound_ids)

        if result.get("successful", 0) > 0:
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)

        await ws_manager.broadcast_inbound_update({"action": "batch_delete", "result": result})
        return result

    @router.post("/api/v1/inbounds/{node_id}/{inbound_id}/set-enable")
    async def set_inbound_enable(request: Request, node_id: int, inbound_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await run_in_threadpool(get_node_or_404, node_id)
        enable = bool(data.get("enable", True))
        success = await run_in_threadpool(inbound_mgr.set_inbound_enable, node, inbound_id, enable)
        if success:
            await run_in_threadpool(invalidate_live_stats_cache)
        return {"success": success}

    @router.post("/api/v1/inbounds/{node_id}/{inbound_id}/reset-traffic")
    async def reset_inbound_traffic(request: Request, node_id: int, inbound_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await run_in_threadpool(get_node_or_404, node_id)
        success = await run_in_threadpool(inbound_mgr.reset_inbound_traffic, node, inbound_id)
        if success:
            await run_in_threadpool(invalidate_live_stats_cache)
        return {"success": success}

    @router.post("/api/v1/inbounds/{node_id}/{inbound_id}/del-all-clients")
    async def del_all_inbound_clients(request: Request, node_id: int, inbound_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await run_in_threadpool(get_node_or_404, node_id)
        result = await run_in_threadpool(inbound_mgr.del_all_inbound_clients, node, inbound_id)
        if "error" not in result:
            await run_in_threadpool(invalidate_subscription_cache)
            await run_in_threadpool(invalidate_live_stats_cache)
        return result

    @router.post("/api/v1/inbounds/{node_id}/reset-all-traffics")
    async def reset_all_inbound_traffics(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await run_in_threadpool(get_node_or_404, node_id)
        success = await run_in_threadpool(inbound_mgr.reset_all_inbound_traffics, node)
        if success:
            await run_in_threadpool(invalidate_live_stats_cache)
        return {"success": success}

    @router.put("/api/v1/inbounds/{node_id}/{inbound_id}")
    async def update_inbound(request: Request, node_id: int, inbound_id: int, data: Dict):
        """Update a single inbound's configuration directly (port, remark, settings, etc.)."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await run_in_threadpool(get_node_or_404, node_id)
        updates = {k: v for k, v in data.items() if k != "node_id"}
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        success = await run_in_threadpool(inbound_mgr.update_inbound, node, inbound_id, updates)
        if success:
            await run_in_threadpool(invalidate_live_stats_cache)
        return {"success": success}

    return router
