import base64
import datetime
import io
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

        statuses = server_monitor.get_all_servers_status(_load_nodes())
        return {"servers": statuses, "count": len(statuses)}

    @router.get("/api/v1/servers/{node_id}/status")
    async def get_server_status(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return server_monitor.get_server_status(_load_node(node_id))

    @router.get("/api/v1/servers/availability")
    async def check_servers_availability(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        availability = [server_monitor.check_server_availability(node) for node in _load_nodes()]
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
        with sqlite3.connect(db_path) as conn:
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
