import base64
import datetime
import io
import sqlite3
from services.db_bootstrap import connect
import time
import zipfile
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import ORJSONResponse, Response
from shared.security import (
    MAX_BACKUP_BYTES,
    MAX_BACKUP_B64_CHARS,
    is_supported_sqlite_backup,
    safe_content_disposition_filename,
)


def build_operations_router(
    *,
    check_auth,
    db_path,
    node_service,
    client_mgr,
    server_monitor,
    get_node_or_404,
    snapshot_collector,
):
    router = APIRouter()

    async def _run(method, *args, **kwargs):
        return await run_in_threadpool(method, *args, **kwargs)

    async def _load_node(node_id: int) -> Dict:
        return await _run(get_node_or_404, node_id)

    async def _load_nodes(node_ids=None):
        nodes = await _run(node_service.list_nodes)
        if node_ids:
            node_id_set = {int(node_id) for node_id in node_ids}
            return [node for node in nodes if int(node.get("id")) in node_id_set]
        return nodes

    def _is_supported_backup_data(backup_data: str) -> bool:
        try:
            content = base64.b64decode(backup_data, validate=True)
        except (ValueError, TypeError):
            content = backup_data.encode("utf-8")
        return is_supported_sqlite_backup(content)

    def _latest_snapshot_payload() -> Dict:
        payload = snapshot_collector.latest_snapshot() if snapshot_collector else {}
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

    def _missing_cached_status(node: Dict) -> Dict:
        return {
            "node": node.get("name"),
            "node_id": node.get("id"),
            "available": False,
            "status": "offline",
            "reason": "snapshot_not_ready",
            "error": "Status has not been collected yet",
            "cached": True,
        }

    def _status_from_snapshot(node: Dict, cached: Dict | None) -> Dict:
        if not isinstance(cached, dict):
            return _missing_cached_status(node)

        server_status = cached.get("server_status")
        if isinstance(server_status, dict):
            payload = dict(server_status)
        else:
            payload = {
                "node": cached.get("name") or node.get("name"),
                "node_id": cached.get("node_id") or node.get("id"),
                "available": bool(cached.get("available")),
                "status": cached.get("status") or ("online" if cached.get("available") else "offline"),
                "reason": cached.get("reason") or ("ok" if cached.get("available") else "unknown"),
                "error": cached.get("error", ""),
                "xray": {"running": bool(cached.get("xray_running"))},
                "system": {"cpu": cached.get("cpu", 0)},
                "network": {"upload": 0, "download": cached.get("traffic_total", 0)},
                "panel_version": cached.get("panel_version", ""),
            }

        payload.setdefault("node", cached.get("name") or node.get("name"))
        payload.setdefault("available", bool(cached.get("available")))
        payload.setdefault("status", cached.get("status") or ("online" if cached.get("available") else "offline"))
        payload.setdefault("reason", cached.get("reason") or ("ok" if cached.get("available") else "unknown"))
        payload.setdefault("error", cached.get("error", ""))
        payload["node_id"] = cached.get("node_id") or node.get("id")
        payload["cached"] = True
        payload["snapshot_timestamp"] = cached.get("timestamp")
        payload["snapshot_updated_at"] = cached.get("snapshot_updated_at")
        payload["poll_ms"] = cached.get("poll_ms")
        if cached.get("circuit_open_until"):
            payload["circuit_open_until"] = cached.get("circuit_open_until")
        return payload

    def _availability_from_snapshot(node: Dict, cached: Dict | None) -> Dict:
        if not isinstance(cached, dict):
            return {
                "node": node.get("name"),
                "node_id": node.get("id"),
                "available": False,
                "latency_ms": None,
                "status_code": 0,
                "timestamp": None,
                "reason": "snapshot_not_ready",
                "error": "Status has not been collected yet",
                "cached": True,
            }
        available = bool(cached.get("available"))
        return {
            "node": cached.get("name") or node.get("name"),
            "node_id": cached.get("node_id") or node.get("id"),
            "available": available,
            "latency_ms": cached.get("poll_ms"),
            "status_code": 200 if available else 0,
            "timestamp": cached.get("timestamp"),
            "reason": cached.get("reason") or ("ok" if available else "unknown"),
            "error": cached.get("error", ""),
            "cached": True,
        }

    @router.get("/api/v1/status")
    async def app_status(request: Request):
        """Public health + summary endpoint (no auth required)."""
        nodes = await _load_nodes()
        return {
            "status": "ok",
            "version": "3.1",
            "nodes_total": len(nodes),
            "timestamp": int(__import__("time").time()),
        }

    @router.post("/api/v1/automation/reset-all-traffic")
    async def reset_all_traffic(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        results = await _run(
            client_mgr.reset_all_traffic,
            await _load_nodes(node_ids=data.get("node_ids")),
            data.get("inbound_id"),
        )
        return results

    @router.get("/api/v1/servers/status")
    async def get_servers_status(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = await _load_nodes()
        by_id, by_name, _snapshot = _snapshot_by_node(nodes)
        statuses = [
            _status_from_snapshot(node, _snapshot_for_node(node, by_id, by_name))
            for node in nodes
        ]
        return ORJSONResponse(content={"servers": statuses, "count": len(statuses)})

    @router.get("/api/v1/servers/{node_id}/status")
    async def get_server_status(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = await _load_node(node_id)
        by_id, by_name, _snapshot = _snapshot_by_node([node])
        return _status_from_snapshot(node, _snapshot_for_node(node, by_id, by_name))

    @router.get("/api/v1/servers/availability")
    async def check_servers_availability(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = await _load_nodes()
        by_id, by_name, _snapshot = _snapshot_by_node(nodes)
        availability = [
            _availability_from_snapshot(node, _snapshot_for_node(node, by_id, by_name))
            for node in nodes
        ]
        return ORJSONResponse(content={"availability": availability})

    @router.post("/api/v1/servers/{node_id}/restart-xray")
    async def restart_xray_on_server(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        success = await _run(server_monitor.restart_xray, await _load_node(node_id))
        return {"success": success}

    @router.get("/api/v1/servers/{node_id}/logs")
    async def get_server_logs(request: Request, node_id: int, count: int = 100, level: str = "info"):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.get_server_logs, await _load_node(node_id), count, level)

    @router.get("/api/v1/backup/database/{node_id}")
    async def get_database_backup(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return await _run(server_monitor.get_database_backup, await _load_node(node_id))

    @router.get("/api/v1/backup/node/{node_id}")
    async def get_database_backup_legacy(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        backup = await _run(server_monitor.get_database_backup, await _load_node(node_id))
        if backup.get("error"):
            raise HTTPException(status_code=502, detail=backup["error"])

        backup_b64 = backup.get("backup_b64") or ""
        if not backup_b64:
            raise HTTPException(status_code=502, detail="Empty backup payload")
        try:
            payload = base64.b64decode(backup_b64)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Invalid backup payload: {exc}")

        filename = f"backup_{backup.get('node','node')}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
        headers = {
            "Content-Disposition": safe_content_disposition_filename(filename, "backup.db"),
            "Content-Encoding": "identity",
            "Cache-Control": "no-store",
        }
        return Response(content=payload, media_type="application/x-sqlite3", headers=headers)

    @router.post("/api/v1/backup/database/{node_id}")
    async def import_database_backup(request: Request, node_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        backup_data = data.get("backup_data")
        if not isinstance(backup_data, str) or not backup_data or len(backup_data) > MAX_BACKUP_B64_CHARS:
            raise HTTPException(status_code=400, detail="backup_data required")
        if not _is_supported_backup_data(backup_data):
            raise HTTPException(status_code=400, detail="unsupported backup format")
        success = await _run(server_monitor.import_database_backup, await _load_node(node_id), backup_data)
        return {"success": success}

    @router.post("/api/v1/backup/node/{node_id}/import")
    async def import_database_backup_legacy(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = await _load_node(node_id)
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail="file required")

        content = await upload.read(MAX_BACKUP_BYTES + 1)
        if len(content) > MAX_BACKUP_BYTES:
            raise HTTPException(status_code=413, detail="backup file is too large")
        if not content:
            raise HTTPException(status_code=400, detail="empty file")
        if not is_supported_sqlite_backup(content):
            raise HTTPException(status_code=400, detail="unsupported backup format")

        backup_data = base64.b64encode(content).decode("ascii")
        success = await _run(server_monitor.import_database_backup, node, backup_data)
        return {"success": success}

    @router.get("/api/v1/backup/all")
    async def get_all_databases_backup(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = await _load_nodes()
        backups = [await _run(server_monitor.get_database_backup, node) for node in nodes]
        if request.query_params.get("format", "").lower() == "json":
            return {"backups": backups, "count": len(backups)}

        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, backup in enumerate(backups, start=1):
                node_name = (backup.get("node") or f"node_{idx}").replace("/", "_")
                if backup.get("error"):
                    zf.writestr(f"{node_name}.error.txt", backup.get("error", "unknown error"))
                    continue
                try:
                    raw = base64.b64decode(backup.get("backup_b64", ""))
                    if raw:
                        zf.writestr(f"{node_name}.db", raw)
                    else:
                        zf.writestr(f"{node_name}.error.txt", "empty backup payload")
                except Exception as exc:
                    zf.writestr(f"{node_name}.error.txt", f"decode error: {exc}")
        mem.seek(0)
        headers = {
            "Content-Disposition": f'attachment; filename="all_backups_{ts}.zip"',
            "Content-Encoding": "identity",
            "Cache-Control": "no-store",
        }
        return Response(content=mem.getvalue(), media_type="application/zip", headers=headers)

    @router.get("/api/v1/history/nodes")
    async def all_nodes_history(request: Request, since_sec: int = 86400, limit_per_node: int = 1200):
        """Return bounded fleet history in one SQLite read for monitoring."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        since_sec = min(max(int(since_sec), 60), 30 * 86400)
        limit_per_node = min(max(int(limit_per_node), 100), 5000)
        ts_from = int(time.time()) - since_sec

        def _read_history():
            with connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    """
                    SELECT ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
                    FROM (
                        SELECT ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms,
                               ROW_NUMBER() OVER (PARTITION BY node_id ORDER BY ts DESC) AS row_number
                        FROM node_history
                        WHERE ts >= ?
                    )
                    WHERE row_number <= ?
                    ORDER BY ts ASC, node_id ASC
                    """,
                    (ts_from, limit_per_node),
                ).fetchall()

        points = [dict(row) for row in await _run(_read_history)]
        return {
            "since_sec": since_sec,
            "limit_per_node": limit_per_node,
            "count": len(points),
            "points": points,
        }

    @router.get("/api/v1/history/nodes/{node_id}")
    async def node_history(request: Request, node_id: int, since_sec: int = 86400, limit: int = 2000):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        if since_sec < 60:
            since_sec = 60
        if since_sec > 30 * 86400:
            since_sec = 30 * 86400
        if limit < 100:
            limit = 100
        if limit > 5000:
            limit = 5000

        await _load_node(node_id)
        ts_from = int(time.time()) - since_sec
        def _read_history():
            with connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(
                    """
                    SELECT ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
                    FROM node_history
                    WHERE node_id = ? AND ts >= ?
                    ORDER BY ts DESC
                    LIMIT ?
                    """,
                    (node_id, ts_from, limit),
                ).fetchall()

        rows = await _run(_read_history)
        points = [dict(r) for r in reversed(rows)]
        return {"node_id": node_id, "since_sec": since_sec, "count": len(points), "points": points}

    return router
