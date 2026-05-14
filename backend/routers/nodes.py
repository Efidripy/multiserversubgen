import sqlite3
import time
from typing import Callable, Dict
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def build_nodes_router(
    *,
    check_auth: Callable[[Request], str | None],
    node_service,
    db_path: str,
    encrypt: Callable[[str], str],
    requests_verify,
    login_panel,
    xui_request,
    invalidate_subscription_cache: Callable[[], None],
    remove_node_metric_labels: Callable[[str, str], None],
    node_metric_labels_lock,
    node_metric_labels_state: Dict[str, str],
    snapshot_collector,
    ws_manager,
    logger,
):
    router = APIRouter()

    @router.get("/api/v1/nodes")
    async def list_nodes(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        nodes = node_service.list_nodes()
        result = []
        for node_dict in nodes:
            node_dict.pop("password", None)
            result.append(node_dict)
        return JSONResponse(content=result, headers={"Cache-Control": "private, max-age=300"})

    @router.get("/api/v1/nodes/list")
    async def list_nodes_simple(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        return JSONResponse(
            content=node_service.list_nodes_simple(),
            headers={"Cache-Control": "private, max-age=300"},
        )

    @router.post("/api/v1/nodes")
    async def add_node(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        name = data.get("name")
        url = data.get("url")
        node_user = data.get("user")
        password = data.get("password")
        bearer_token = data.get("bearer_token")
        read_only = bool(data.get("read_only", False))

        if not all([name, url]):
            raise HTTPException(status_code=400, detail="name and url are required")
        
        # Either bearer token OR (user + password) required
        has_token = bool(bearer_token)
        has_credentials = bool(node_user and password)
        if not has_token and not has_credentials:
            raise HTTPException(status_code=400, detail="Either bearer_token OR (user+password) required")

        if not str(url).startswith(("http://", "https://")):
            url = "https://" + str(url)

        parsed = urlparse(str(url))
        if not parsed.hostname:
            raise HTTPException(status_code=400, detail="Invalid URL")

        scheme = parsed.scheme or "https"
        port = str(parsed.port) if parsed.port else "443"
        base_path = parsed.path.strip("/")
        prefix = f"/{base_path}" if base_path else ""
        canonical_panel_url = f"{scheme}://{parsed.hostname}:{port}{prefix}"

        try:
            # Store bearer token with prefix, or encrypt password
            if bearer_token:
                encrypted_password = encrypt(f"bearer:{bearer_token}")
                stored_user = "bearer_token"
            else:
                encrypted_password = encrypt(str(password))
                stored_user = node_user
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO nodes (
                        name, panel_url, username, user,
                        password, ip, port, base_path, access_path,
                        read_only, scheme, verify_tls
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        name,
                        canonical_panel_url,
                        stored_user,
                        stored_user,
                        encrypted_password,
                        parsed.hostname,
                        port,
                        base_path,
                        base_path,
                        1 if read_only else 0,
                        scheme,
                        0,
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"Error adding node: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

        try:
            invalidate_subscription_cache()
        except Exception as exc:
            logger.warning(f"Node added but cache invalidation failed: {exc}")
        return {"status": "success"}

    @router.post("/api/v1/nodes/check-connection")
    async def check_node_connection(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        url = str(data.get("url") or "").strip()
        node_user = str(data.get("user") or "").strip()
        password = str(data.get("password") or "").strip()
        bearer_token = str(data.get("bearer_token") or "").strip()

        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        
        # Either bearer token OR (user + password) required
        has_token = bool(bearer_token)
        has_credentials = bool(node_user and password)
        if not has_token and not has_credentials:
            raise HTTPException(status_code=400, detail="Either bearer_token OR (user+password) required")

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)
        if not parsed.hostname:
            raise HTTPException(status_code=400, detail="Invalid URL")

        scheme = parsed.scheme or "https"
        port = parsed.port or 443
        base_path = parsed.path.strip("/")
        prefix = f"/{base_path}" if base_path else ""
        base_url = f"{scheme}://{parsed.hostname}:{port}{prefix}"

        session = requests.Session()
        # Always allow self-signed certificates for connectivity probing.
        session.verify = False

        try:
            if bearer_token:
                if not login_panel(session, base_url, bearer_token=bearer_token):
                    return {"success": False, "message": "Login failed", "base_url": base_url}
            else:
                if not login_panel(session, base_url, node_user, password):
                    return {"success": False, "message": "Login failed", "base_url": base_url}

            inbounds_count = None
            details = ""
            try:
                probe = xui_request(session, "GET", f"{base_url}/panel/api/inbounds/list", timeout=15)
                if probe.status_code == 200:
                    payload = probe.json()
                    if isinstance(payload, dict) and payload.get("success"):
                        inbounds = payload.get("obj") or []
                        inbounds_count = len(inbounds) if isinstance(inbounds, list) else 0
                    elif isinstance(payload, dict):
                        details = str(payload.get("msg") or "panel success=false")
                else:
                    details = f"inbounds/list status={probe.status_code}"
            except Exception as exc:
                details = f"inbounds probe failed: {exc}"

            return {
                "success": True,
                "message": "Connection OK",
                "base_url": base_url,
                "inbounds_count": inbounds_count,
                "details": details,
            }
        except Exception as exc:
            logger.warning(f"Node connection check failed for {base_url}: {exc}")
            return {"success": False, "message": str(exc), "base_url": base_url}

    @router.put("/api/v1/nodes/{node_id}")
    async def update_node(node_id: int, request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        has_name = "name" in data
        has_read_only = "read_only" in data
        if not has_name and not has_read_only:
            raise HTTPException(status_code=400, detail="No updatable fields provided")

        new_name = None
        if has_name:
            new_name = str(data.get("name", "")).strip()
            if not new_name:
                raise HTTPException(status_code=400, detail="Name cannot be empty")

        def _coerce_bool(value) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"1", "true", "yes", "on"}:
                    return True
                if normalized in {"0", "false", "no", "off", ""}:
                    return False
            return bool(value)

        new_read_only = _coerce_bool(data.get("read_only")) if has_read_only else None

        try:
            with sqlite3.connect(db_path) as conn:
                existing = conn.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="Node not found")

                old_name = str(existing[0] or "")
                update_fields = []
                update_values = []

                if has_name:
                    update_fields.append("name = ?")
                    update_values.append(new_name)

                if has_read_only:
                    update_fields.append("read_only = ?")
                    update_values.append(1 if new_read_only else 0)

                update_values.append(node_id)
                result = conn.execute(
                    f"UPDATE nodes SET {', '.join(update_fields)} WHERE id = ?",
                    tuple(update_values),
                )

                if has_name:
                    conn.execute("UPDATE node_history SET node_name = ? WHERE node_id = ?", (new_name, node_id))
                conn.commit()
                if result.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Node not found")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Error updating node: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

        node_id_str = str(node_id)
        with node_metric_labels_lock:
            if has_name and old_name and old_name != new_name:
                remove_node_metric_labels(old_name, node_id_str)
            if has_name:
                node_metric_labels_state[node_id_str] = new_name

        try:
            invalidate_subscription_cache()
        except Exception as exc:
            logger.warning(f"Node updated but cache invalidation failed: {exc}")
        return {"status": "success"}

    @router.delete("/api/v1/nodes/{node_id}")
    async def delete_node(node_id: int, request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
                conn.commit()
        except Exception as exc:
            logger.error(f"Error deleting node: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

        try:
            invalidate_subscription_cache()
        except Exception as exc:
            logger.warning(f"Node deleted but cache invalidation failed: {exc}")
        return {"status": "success"}

    @router.post("/api/v1/nodes/refresh-now")
    async def force_refresh_nodes(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        await snapshot_collector.force_poll_all()
        return {"status": "success", "message": "Force poll initiated"}

    @router.get("/api/v1/collector/status")
    async def get_collector_status(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return {
            "mode": snapshot_collector.get_mode(),
            "running": snapshot_collector.is_running(),
            "ws_connections": len(ws_manager.active_connections),
            "timestamp": time.time(),
        }

    return router
