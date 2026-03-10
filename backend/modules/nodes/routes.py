"""Nodes module – FastAPI routes."""

from __future__ import annotations

from typing import Dict, Optional, TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

if TYPE_CHECKING:
    from core.event_bus import EventBus

    from .service import NodesService


def build_nodes_router(
    nodes_service: "NodesService",
    event_bus: Optional["EventBus"] = None,
) -> APIRouter:
    """Return a router with node CRUD endpoints."""

    router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

    def _check_auth(request: Request) -> str:
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user

    @router.get("")
    async def list_nodes(request: Request):
        _check_auth(request)
        nodes = await run_in_threadpool(nodes_service.list_nodes)
        return {"nodes": nodes, "count": len(nodes)}

    @router.get("/list")
    async def list_nodes_simple(request: Request):
        _check_auth(request)
        nodes = await run_in_threadpool(nodes_service.list_nodes)
        return [{"id": n["id"], "name": n["name"]} for n in nodes]

    @router.post("")
    async def create_node(request: Request, data: Dict):
        _check_auth(request)
        node = await run_in_threadpool(nodes_service.create_node, data)
        if event_bus:
            await event_bus.emit("node.created", {"node_id": node["id"], "name": node["name"]})
        return {"status": "success", "node": node}

    @router.put("/{node_id}")
    async def update_node(node_id: int, request: Request, data: Dict):
        _check_auth(request)
        node = await run_in_threadpool(nodes_service.update_node, node_id, data)
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")
        if event_bus:
            await event_bus.emit("node.updated", {"node_id": node_id})
        return {"status": "success", "node": node}

    @router.delete("/{node_id}")
    async def delete_node(node_id: int, request: Request):
        _check_auth(request)
        deleted = await run_in_threadpool(nodes_service.delete_node, node_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Node not found")
        if event_bus:
            await event_bus.emit("node.deleted", {"node_id": node_id})
        return {"status": "success"}

    return router
