import base64
import datetime
import io
import sqlite3
from services.db_bootstrap import connect
import time
import zipfile
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response


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

    def _load_node(node_id: int) -> Dict:
        return get_node_or_404(node_id)

    def _load_nodes(node_ids=None):
        nodes = node_service.list_nodes()
        if node_ids:
            node_id_set = {int(node_id) for node_id in node_ids}
            return [node for node in nodes if int(node.get("id")) in node_id_set]
        return nodes

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
        nodes = _load_nodes()
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

        results = client_mgr.reset_all_traffic(_load_nodes(node_ids=data.get("node_ids")), data.get("inbound_id"))
        return results

    @router.get("/api/v1/servers/status")
    async def get_servers_status(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = _load_nodes()
        by_id, by_name, _snapshot = _snapshot_by_node(nodes)
        statuses = [
            _status_from_snapshot(node, _snapshot_for_node(node, by_id, by_name))
            for node in nodes
        ]
        return {"servers": statuses, "count": len(statuses)}

    @router.get("/api/v1/servers/{node_id}/status")
    async def get_server_status(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node = _load_node(node_id)
        by_id, by_name, _snapshot = _snapshot_by_node([node])
        return _status_from_snapshot(node, _snapshot_for_node(node, by_id, by_name))

    @router.get("/api/v1/servers/availability")
    async def check_servers_availability(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = _load_nodes()
        by_id, by_name, _snapshot = _snapshot_by_node(nodes)
        availability = [
            _availability_from_snapshot(node, _snapshot_for_node(node, by_id, by_name))
            for node in nodes
        ]
        return {"availability": availability}

    @router.post("/api/v1/servers/{node_id}/restart-xray")
    async def restart_xray_on_server(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        success = server_monitor.restart_xray(_load_node(node_id))
        return {"success": success}

    @router.get("/api/v1/servers/{node_id}/logs")
    async def get_server_logs(request: Request, node_id: int, count: int = 100, level: str = "info"):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return server_monitor.get_server_logs(_load_node(node_id), count, level)

    @router.get("/api/v1/backup/database/{node_id}")
    async def get_database_backup(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return server_monitor.get_database_backup(_load_node(node_id))

    @router.get("/api/v1/backup/node/{node_id}")
    async def get_database_backup_legacy(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        backup = server_monitor.get_database_backup(_load_node(node_id))
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
            "Content-Disposition": f'attachment; filename="{filename}"',
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
        if not backup_data:
            raise HTTPException(status_code=400, detail="backup_data required")
        success = server_monitor.import_database_backup(_load_node(node_id), backup_data)
        return {"success": success}

    @router.post("/api/v1/backup/node/{node_id}/import")
    async def import_database_backup_legacy(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = _load_node(node_id)
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail="file required")

        content = await upload.read()
        if not content:
            raise HTTPException(status_code=400, detail="empty file")

        backup_data = base64.b64encode(content).decode("ascii")
        success = server_monitor.import_database_backup(node, backup_data)
        return {"success": success}

    @router.get("/api/v1/backup/all")
    async def get_all_databases_backup(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        backups = [server_monitor.get_database_backup(node) for node in _load_nodes()]
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

        get_node_or_404(node_id)
        ts_from = int(time.time()) - since_sec
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
                FROM node_history
                WHERE node_id = ? AND ts >= ?
                ORDER BY ts DESC
                LIMIT ?
                """,
                (node_id, ts_from, limit),
            ).fetchall()
        points = [dict(r) for r in reversed(rows)]
        return {"node_id": node_id, "since_sec": since_sec, "count": len(points), "points": points}

    return router
