"""Server operations router — history metrics, logs, API tokens, observatory."""
from typing import Dict
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool


def build_server_ops_router(
    *,
    check_auth,
    xui_monitor,
    server_monitor,
    get_node_or_404,
):
    router = APIRouter()

    async def _run(method, *args, **kwargs):
        return await run_in_threadpool(method, *args, **kwargs)

    async def _node(node_id):
        return await run_in_threadpool(get_node_or_404, node_id)

    @router.get("/api/v1/nodes/{node_id}/server-history/{metric}")
    async def get_server_history(
        request: Request, node_id: int, metric: str, bucket: str = "5m"
    ):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _node(node_id)
        return await _run(server_monitor.get_server_history, node, metric, bucket)

    @router.get("/api/v1/nodes/{node_id}/panel-update-info")
    async def get_panel_update_info(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _node(node_id)
        return await _run(server_monitor.get_panel_update_info, node)

    @router.get("/api/v1/nodes/{node_id}/xray-observatory")
    async def get_xray_observatory(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _node(node_id)
        return await _run(server_monitor.get_xray_observatory, node)

    @router.get("/api/v1/nodes/{node_id}/api-tokens")
    async def list_api_tokens(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _node(node_id)
        return await _run(server_monitor.get_api_tokens, node)

    @router.post("/api/v1/nodes/{node_id}/api-tokens")
    async def create_api_token(request: Request, node_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        node = await _node(node_id)
        result = await _run(server_monitor.create_api_token, node, name)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result

    @router.get("/api/v1/nodes/{node_id}/server-logs")
    async def get_server_logs(
        request: Request, node_id: int,
        count: int = 100, level: str = "info"
    ):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _node(node_id)
        return await _run(server_monitor.get_server_logs, node, count=min(max(count, 1), 500), level=level)

    @router.get("/api/v1/nodes/{node_id}/xray-logs")
    async def get_xray_logs(request: Request, node_id: int, count: int = 100, level: str = "info"):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _node(node_id)
        return await _run(server_monitor.get_xray_logs, node, count=min(max(count, 1), 500), level=level)

    @router.get("/api/v1/nodes/{node_id}/xray-versions")
    async def get_xray_versions(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.get_xray_versions, await _node(node_id))

    @router.post("/api/v1/nodes/{node_id}/install-xray/{version}")
    async def install_xray(request: Request, node_id: int, version: str):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.install_xray, await _node(node_id), version)

    @router.post("/api/v1/nodes/{node_id}/update-geofile")
    async def update_geofile(request: Request, node_id: int, data: Dict = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        file_name = (data or {}).get("fileName", "")
        return await _run(server_monitor.update_geofile, await _node(node_id), file_name)

    @router.post("/api/v1/nodes/{node_id}/stop-xray")
    async def stop_xray(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        ok = await _run(server_monitor.stop_xray, await _node(node_id))
        return {"success": ok}

    @router.post("/api/v1/nodes/{node_id}/update-panel")
    async def update_panel(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.update_panel, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/xray-metrics")
    async def get_xray_metrics(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.get_xray_metrics, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/outbounds-traffic")
    async def get_outbounds_traffic(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.get_outbounds_traffic, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/generate-uuid")
    async def generate_uuid(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.generate_uuid, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/generate-x25519")
    async def generate_x25519(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.generate_x25519_cert, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/generate-vless-enc")
    async def generate_vless_enc(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.generate_vless_enc, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/generate-mldsa65")
    async def generate_mldsa65(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.generate_mldsa65, await _node(node_id))

    @router.get("/api/v1/nodes/{node_id}/xray-config")
    async def get_xray_config(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.get_xray_config, await _node(node_id))

    @router.post("/api/v1/nodes/{node_id}/backup-telegram")
    async def backup_telegram(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.backup_to_telegram, await _node(node_id))

    @router.delete("/api/v1/nodes/{node_id}/api-tokens/{token_id}")
    async def delete_api_token(request: Request, node_id: int, token_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        ok = await _run(server_monitor.delete_api_token, await _node(node_id), token_id)
        return {"success": ok}

    @router.post("/api/v1/nodes/{node_id}/api-tokens/{token_id}/set-enabled")
    async def set_api_token_enabled(request: Request, node_id: int, token_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        ok = await _run(server_monitor.set_api_token_enabled,
            await _node(node_id),
            token_id,
            bool(data.get("enabled", True)),
        )
        return {"success": ok}

    return router
