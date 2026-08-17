from services.db_bootstrap import connect
import json
import time
from typing import Callable, Dict
from shared.sql import update_by_id_query
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import ORJSONResponse

from xui_session import invalidate_auth_method_cache, invalidate_session_cache, make_node_key
from shared.security import redact_url, validate_outbound_url


def _serialize_tags(value) -> str:
    if value is None or value == "":
        return "[]"
    if isinstance(value, list):
        tags = [str(tag).strip() for tag in value if str(tag).strip()]
        return json.dumps(tags, ensure_ascii=False)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "[]"
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                tags = [str(tag).strip() for tag in parsed if str(tag).strip()]
                return json.dumps(tags, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        tags = [tag.strip() for tag in stripped.split(",") if tag.strip()]
        return json.dumps(tags, ensure_ascii=False)
    return "[]"


def build_nodes_router(
    *,
    check_auth: Callable[[Request], str | None],
    node_service,
    get_node_or_404: Callable[[int], Dict],
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

        nodes = await run_in_threadpool(node_service.list_nodes)
        result = []
        for node_dict in nodes:
            node_dict.pop("password", None)
            result.append(node_dict)
        return ORJSONResponse(content=result, headers={"Cache-Control": "private, max-age=300"})

    @router.get("/api/v1/nodes/list")
    async def list_nodes_simple(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        return ORJSONResponse(
            content=await run_in_threadpool(node_service.list_nodes_simple),
            headers={"Cache-Control": "private, max-age=300"},
        )

    # These CRUD handlers perform SQLite work only. Keeping them sync lets
    # FastAPI run the complete transaction in its worker thread pool.
    @router.post("/api/v1/nodes")
    def add_node(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        name = data.get("name")
        url = data.get("url")
        node_user = data.get("user")
        password = data.get("password")
        bearer_token = str(data.get("bearer_token") or "").strip()
        read_only = bool(data.get("read_only", False))
        tags = _serialize_tags(data.get("tags"))

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
        valid_url, url_error = validate_outbound_url(str(url))
        if not valid_url:
            raise HTTPException(status_code=400, detail=url_error)

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
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO nodes (
                        name, panel_url, username, user,
                        password, ip, port, base_path, access_path,
                        read_only, scheme, verify_tls, tags
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        1,
                        tags,
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"Error adding node: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

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
        valid_url, url_error = validate_outbound_url(url)
        if not valid_url:
            logger.info("Node connection URL rejected: %s", url_error)
            raise HTTPException(status_code=400, detail="Invalid outbound URL")

        scheme = parsed.scheme or "https"
        port = parsed.port or 443
        base_path = parsed.path.strip("/")
        prefix = f"/{base_path}" if base_path else ""
        base_url = f"{scheme}://{parsed.hostname}:{port}{prefix}"

        session = requests.Session()
        session.verify = requests_verify if requests_verify is not False else True

        try:
            if bearer_token:
                # Для bearer-токена: один запрос валидирует токен И считает инбаунды
                session.headers.update({"Authorization": f"Bearer {bearer_token}"})
                probe = await run_in_threadpool(
                    xui_request, session, "GET", f"{base_url}/panel/api/inbounds/list", timeout=15
                )
                if probe.status_code != 200:
                    return {"success": False, "message": f"Bearer token rejected (HTTP {probe.status_code})", "base_url": base_url}
                try:
                    payload = probe.json()
                except Exception:
                    return {"success": False, "message": "Bearer token: invalid JSON response", "base_url": base_url}
                if not payload.get("success"):
                    return {"success": False, "message": "Bearer token rejected by panel", "base_url": base_url}
                inbounds = payload.get("obj") or []
                return {
                    "success": True,
                    "message": "Connection OK",
                    "base_url": base_url,
                    "inbounds_count": len(inbounds) if isinstance(inbounds, list) else 0,
                    "details": "",
                }
            else:
                if not await run_in_threadpool(login_panel, session, base_url, node_user, password):
                    return {"success": False, "message": "Login failed", "base_url": base_url}

            inbounds_count = None
            details = ""
            try:
                probe = await run_in_threadpool(
                    xui_request, session, "GET", f"{base_url}/panel/api/inbounds/list", timeout=15
                )
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
                logger.warning("Node inbounds probe failed for %s: %s", redact_url(base_url), exc)
                details = "Unable to read panel status"

            return {
                "success": True,
                "message": "Connection OK",
                "base_url": base_url,
                "inbounds_count": inbounds_count,
                "details": details,
            }
        except Exception as exc:
            logger.warning("Node connection check failed for %s: %s", redact_url(base_url), exc)
            return {"success": False, "message": "Connection check failed", "base_url": base_url}

    @router.put("/api/v1/nodes/{node_id}")
    def update_node(node_id: int, request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        has_name = "name" in data
        has_read_only = "read_only" in data
        has_bearer = "bearer_token" in data
        has_credentials = "user" in data or "password" in data
        has_tags = "tags" in data
        if not has_name and not has_read_only and not has_bearer and not has_credentials and not has_tags:
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

        node_panel_url: str | None = None
        try:
            with connect(db_path) as conn:
                existing = conn.execute(
                    "SELECT name, panel_url FROM nodes WHERE id = ?", (node_id,)
                ).fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="Node not found")

                old_name = str(existing[0] or "")
                node_panel_url = existing[1]
                update_fields = []
                update_values = []

                if has_name:
                    update_fields.append("name")
                    update_values.append(new_name)

                if has_read_only:
                    update_fields.append("read_only")
                    update_values.append(1 if new_read_only else 0)

                if has_tags:
                    update_fields.append("tags")
                    update_values.append(_serialize_tags(data.get("tags")))

                if has_bearer:
                    new_bearer = str(data.get("bearer_token") or "").strip()
                    if new_bearer:
                        update_fields.append("password")
                        update_values.append(encrypt(f"bearer:{new_bearer}"))
                        update_fields.append("username")
                        update_values.append("bearer_token")
                        update_fields.append("user")
                        update_values.append("bearer_token")
                    else:
                        raise HTTPException(status_code=400, detail="bearer_token cannot be empty")
                elif has_credentials:
                    new_user = str(data.get("user") or "").strip()
                    new_pass = str(data.get("password") or "").strip()
                    if not new_user or not new_pass:
                        raise HTTPException(status_code=400, detail="user and password cannot be empty")
                    update_fields.append("password")
                    update_values.append(encrypt(new_pass))
                    update_fields.append("username")
                    update_values.append(new_user)
                    update_fields.append("user")
                    update_values.append(new_user)

                update_values.append(node_id)
                result = conn.execute(
                    update_by_id_query("nodes", update_fields),
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
            raise HTTPException(status_code=500, detail="Internal server error")

        node_id_str = str(node_id)
        with node_metric_labels_lock:
            if has_name and old_name and old_name != new_name:
                remove_node_metric_labels(old_name, node_id_str)
            if has_name:
                node_metric_labels_state[node_id_str] = new_name

        if has_bearer or has_credentials:
            # Сбрасываем кешированный метод авторизации — credentials изменились
            invalidate_auth_method_cache(node_panel_url)  # None → сбрасывает весь кеш
            invalidate_session_cache(make_node_key(node_panel_url or "", 443))

        try:
            invalidate_subscription_cache()
        except Exception as exc:
            logger.warning(f"Node updated but cache invalidation failed: {exc}")
        return {"status": "success"}

    @router.delete("/api/v1/nodes/{node_id}")
    def delete_node(node_id: int, request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            with connect(db_path) as conn:
                conn.execute("DELETE FROM node_snapshots WHERE node_id = ?", (node_id,))
                conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
                conn.commit()
        except Exception as exc:
            logger.error(f"Error deleting node: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

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

    @router.post("/api/v1/nodes/{node_id}/generate-keypair")
    async def generate_reality_keypair(request: Request, node_id: int):
        """Generate a new x25519 keypair for Reality security.
        Tries the panel API first; falls back to local Python generation."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        # Try via the panel API first
        node = await run_in_threadpool(get_node_or_404, node_id)
        try:
            result = await run_in_threadpool(node_service.call_node_api, node, "POST", "/api/node/keypair", {})
            if result and result.get("privateKey"):
                return {"privateKey": result["privateKey"], "publicKey": result.get("publicKey", "")}
        except Exception:
            pass
        # Fallback: generate locally using cryptography library if available
        try:
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            import base64
            private_key = X25519PrivateKey.generate()
            private_bytes = private_key.private_bytes_raw()
            public_bytes = private_key.public_key().public_bytes_raw()
            private_b64 = base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode()
            public_b64 = base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode()
            return {"privateKey": private_b64, "publicKey": public_b64}
        except ImportError:
            pass
        # Final fallback: random bytes (not a proper keypair, just for UI)
        import os
        rnd = os.urandom(32)
        import base64 as b64m
        return {
            "privateKey": b64m.urlsafe_b64encode(rnd).rstrip(b"=").decode(),
            "publicKey": "",
            "warning": "cryptography library not installed — install it for proper keypair generation",
        }

    @router.get("/api/v1/collector/status")
    def get_collector_status(request: Request):
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
