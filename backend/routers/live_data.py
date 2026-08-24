import time
from typing import Callable, Dict
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import ORJSONResponse


def build_live_data_router(
    *,
    get_node_or_404: Callable[[int], Dict],
    get_cached_traffic_stats: Callable[[list, str], Dict],
    get_cached_traffic_stats_projection: Callable[[str], Dict] = None,
    get_cached_traffic_stats_projection_by_period: Callable[[str, str], Dict] = None,
    list_nodes: Callable[[], list],
    xui_monitor,
    get_latest_snapshot: Callable[[], Dict] = None,
    get_latest_client_presence: Callable[[], Dict] = None,
):
    router = APIRouter()
    projection_period_handler = get_cached_traffic_stats_projection_by_period

    def _top_clients_from_projection(projection: Dict, limit: int = 5) -> list[Dict]:
        stats = projection.get("stats") if isinstance(projection, dict) else None
        if not isinstance(stats, dict):
            return []
        system_client_emails = {
            email.strip().casefold()
            for email in projection.get("system_client_emails", [])
            if isinstance(email, str) and email.strip()
        }

        def _metric(value) -> int:
            try:
                return max(0, int(float(value or 0)))
            except (TypeError, ValueError, OverflowError):
                return 0

        clients = []
        for email, item in stats.items():
            if not isinstance(item, dict):
                continue
            if str(email).strip().casefold() in system_client_emails:
                continue
            upload = _metric(item.get("up", item.get("upload", 0)))
            download = _metric(item.get("down", item.get("download", 0)))
            total = _metric(item.get("total")) or upload + download
            clients.append({
                "email": str(email),
                "upload": upload,
                "download": download,
                "total": total,
            })
        return sorted(clients, key=lambda client: (-client["total"], client["email"]))[:limit]

    def _traffic_totals_from_projection(projection: Dict) -> Dict[str, int]:
        stats = projection.get("stats") if isinstance(projection, dict) else None
        if not isinstance(stats, dict):
            return {"upload": 0, "download": 0, "total": 0}

        upload = 0
        download = 0
        total = 0
        for item in stats.values():
            if not isinstance(item, dict):
                continue
            try:
                item_upload = max(0, int(float(item.get("up", item.get("upload", 0)) or 0)))
                item_download = max(0, int(float(item.get("down", item.get("download", 0)) or 0)))
                item_total = max(0, int(float(item.get("total") or 0))) or item_upload + item_download
            except (TypeError, ValueError, OverflowError):
                continue
            upload += item_upload
            download += item_download
            total += item_total
        return {"upload": upload, "download": download, "total": total}

    def _apply_limit(payload: Dict, limit: int) -> Dict:
        if limit <= 0:
            return payload
        stats = payload.get("stats") if isinstance(payload, dict) else None
        if not isinstance(stats, dict):
            return payload

        top_items = sorted(
            stats.items(),
            key=lambda item: float(
                (item[1] or {}).get("total")
                or ((item[1] or {}).get("up", 0) + (item[1] or {}).get("down", 0))
            ),
            reverse=True,
        )[:limit]

        trimmed = dict(payload)
        trimmed["stats"] = dict(top_items)
        trimmed["count"] = len(top_items)
        return trimmed

    def _public_traffic_payload(payload: Dict, limit: int) -> Dict:
        """Hide runtime sidecars while preserving an aggregate before top-N trimming."""
        summary = _traffic_totals_from_projection(payload)
        stats = payload.get("stats") if isinstance(payload, dict) else None
        summary["count"] = len(stats) if isinstance(stats, dict) else 0
        limited = _apply_limit(payload, limit)
        public = {key: value for key, value in limited.items() if key != "identity_stats"}
        public["summary"] = summary
        return public

    def _latest_snapshot_payload() -> Dict:
        if not get_latest_snapshot:
            return {"timestamp": None, "nodes": [], "count": 0}
        payload = get_latest_snapshot()
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

    def _safe_panel_url(value) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = urlsplit(raw)
            host = parsed.hostname or parsed.netloc
            try:
                port = parsed.port
            except ValueError:
                port = None
            netloc = f"{host}:{port}" if port is not None else host
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            return raw.split("?", 1)[0].split("#", 1)[0]

    def _dashboard_fleet_row(node: Dict, cached: Dict | None) -> Dict:
        """Serialize only Dashboard fields; credentials never cross this route."""
        cached = cached if isinstance(cached, dict) else {}
        return {
            "id": node.get("id"),
            "name": str(node.get("name") or node.get("id") or "unknown"),
            # `url` can be a UI-derived fallback based on the node name.  It
            # is not an authoritative panel address (and names may contain
            # emoji), so only forward an explicit saved panel URL here.
            "panel_url": _safe_panel_url(node.get("panel_url")),
            "ip": node.get("ip") or "",
            "port": node.get("port") or "",
            "scheme": node.get("scheme") or "https",
            "base_path": node.get("base_path") or "",
            "source_type": node.get("source_type") or "xui",
            "read_only": bool(node.get("read_only")),
            "enabled": bool(node.get("enabled", True)),
            "available": bool(cached.get("available")) if cached else None,
            "status": cached.get("status"),
            "reason": cached.get("reason"),
            "error": cached.get("error"),
            "system": cached.get("system"),
            "xray": cached.get("xray"),
            "network": cached.get("network"),
            "xray_running": cached.get("xray_running"),
            "online_clients": cached.get("online_clients"),
            "traffic_total": cached.get("traffic_total"),
            "timestamp": cached.get("timestamp"),
            "poll_ms": cached.get("poll_ms"),
            "panel_version": cached.get("panel_version") or node.get("panel_version") or "",
            "api_version": cached.get("api_version") or node.get("api_version") or "",
            "xray_compatibility": cached.get("xray_compatibility"),
        }

    async def _dashboard_payload(period: str) -> tuple[Dict, list, Dict[str, Dict], Dict[str, Dict]]:
        nodes = await run_in_threadpool(list_nodes)
        by_id, by_name, snapshot = _snapshot_by_node(nodes)
        traffic_projection = (
            await run_in_threadpool(get_cached_traffic_stats_projection_by_period, "client", period)
            if get_cached_traffic_stats_projection_by_period
            else await run_in_threadpool(get_cached_traffic_stats_projection, "client")
            if get_cached_traffic_stats_projection
            else {"stats": {}, "cache_source": "unavailable"}
        )
        online_by_node: Dict[str, int] = {}
        online_by_node_id: Dict[str, int] = {}
        online_total = 0
        online_nodes = 0
        for node in nodes:
            cached = _snapshot_for_node(node, by_id, by_name)
            node_name = node.get("name") or str(node.get("id"))
            node_id = str(node.get("id") or node_name)
            if not isinstance(cached, dict):
                online_by_node_id[node_id] = 0
                online_by_node.setdefault(node_name, 0)
                continue
            online_count = int(cached.get("online_clients") or 0)
            online_by_node_id[node_id] = online_count
            online_by_node[node_name] = online_by_node.get(node_name, 0) + online_count
            online_total += online_count
            if cached.get("available"):
                online_nodes += 1
        return ({
            "nodes_total": len(nodes),
            "nodes_online": online_nodes,
            "clients_total": int(traffic_projection.get("current_count") or len(traffic_projection.get("stats", {}))),
            "online_clients_total": online_total,
            "online_by_node": online_by_node,
            "online_by_node_id": online_by_node_id,
            "traffic": _traffic_totals_from_projection(traffic_projection),
            "traffic_period": period,
            "traffic_note": traffic_projection.get("note"),
            "top_clients": _top_clients_from_projection(traffic_projection),
            "cache": {
                "source": "snapshot_collector",
                "timestamp": snapshot.get("timestamp"),
                "age_sec": round(time.time() - snapshot["timestamp"], 2) if snapshot.get("timestamp") else None,
                "ready": bool(snapshot.get("nodes")),
                "client_traffic_source": traffic_projection.get("cache_source"),
                "client_traffic_timestamp": traffic_projection.get("cache_timestamp"),
            },
        }, nodes, by_id, by_name)

    @router.get("/api/v1/traffic/stats")
    async def get_traffic_stats(request: Request, group_by: str = "client", limit: int = 0):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if group_by not in ["client", "inbound", "node"]:
            raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
        nodes = await run_in_threadpool(list_nodes)
        payload = await run_in_threadpool(get_cached_traffic_stats, nodes, group_by)
        return ORJSONResponse(content=_public_traffic_payload(payload, limit))

    @router.get("/api/v1/clients/online")
    async def get_online_clients(request: Request, limit: int = 0):
        """Compatibility list derived from the Collector snapshot; never polls nodes."""
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        presence = (
            await run_in_threadpool(get_latest_client_presence)
            if get_latest_client_presence
            else {}
        )
        online_by_node = presence.get("online_by_node", {}) if isinstance(presence, dict) else {}
        node_names = presence.get("node_names", {}) if isinstance(presence, dict) else {}
        online = [
            {
                "email": email,
                "node_id": node_id,
                "node_name": str(node_names.get(node_id) or node_id),
            }
            for node_id, emails in online_by_node.items()
            if isinstance(emails, list)
            for email in emails
            if isinstance(email, str) and email
        ]
        online.sort(key=lambda item: (item["email"], item["node_name"], item["node_id"]))
        if limit > 0:
            online = online[:limit]
        return ORJSONResponse(content={"online_clients": online, "count": len(online), "source": "snapshot_collector"})

    @router.get("/api/v1/clients/presence")
    async def get_client_presence(request: Request):
        """Cached client presence only; never initiates a fleet scan."""
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        payload = await run_in_threadpool(get_latest_client_presence) if get_latest_client_presence else {}
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/dashboard/summary")
    async def get_dashboard_summary(request: Request, period: str = "all_time"):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if period not in ["day", "week", "month", "all_time"]:
            raise HTTPException(status_code=400, detail="period must be day, week, month, or all_time")
        payload, _, _, _ = await _dashboard_payload(period)
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/dashboard/overview")
    async def get_dashboard_overview(request: Request, period: str = "all_time"):
        """One bounded Dashboard read: summary plus sanitized fleet status."""
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if period not in ["day", "week", "month", "all_time"]:
            raise HTTPException(status_code=400, detail="period must be day, week, month, or all_time")
        summary, nodes, by_id, by_name = await _dashboard_payload(period)
        fleet = [_dashboard_fleet_row(node, _snapshot_for_node(node, by_id, by_name)) for node in nodes]
        return ORJSONResponse(content={"summary": summary, "fleet": fleet, "projection": "dashboard-v1"})

    @router.get("/api/v1/nodes/{node_id}/server-status")
    async def get_node_server_status(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        by_id, by_name, _snapshot = _snapshot_by_node([node])
        cached = _snapshot_for_node(node, by_id, by_name)
        if not isinstance(cached, dict):
            return ORJSONResponse(content={
                "node": node.get("name"),
                "node_id": node_id,
                "available": False,
                "status": "offline",
                "reason": "snapshot_not_ready",
                "error": "Status has not been collected yet",
                "cached": True,
            })
        server_status = cached.get("server_status")
        if isinstance(server_status, dict):
            payload = dict(server_status)
        else:
            payload = {
                "node": cached.get("name") or node.get("name"),
                "node_id": cached.get("node_id") or node_id,
                "available": bool(cached.get("available")),
                "status": cached.get("status") or ("online" if cached.get("available") else "offline"),
                "reason": cached.get("reason") or ("ok" if cached.get("available") else "unknown"),
                "error": cached.get("error", ""),
                "xray": {"running": bool(cached.get("xray_running"))},
                "system": {"cpu": cached.get("cpu", 0)},
                "network": {"upload": 0, "download": cached.get("traffic_total", 0)},
                "panel_version": cached.get("panel_version", ""),
            }
        payload.setdefault("node_id", cached.get("node_id") or node_id)
        payload["cached"] = True
        payload["snapshot_timestamp"] = cached.get("timestamp")
        payload["poll_ms"] = cached.get("poll_ms")
        if cached.get("circuit_open_until"):
            payload["circuit_open_until"] = cached.get("circuit_open_until")
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/traffic")
    async def get_node_traffic(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_traffic, node)
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/inbounds")
    async def get_node_inbounds(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_inbounds, node)
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/online-clients")
    async def get_node_online_clients(request: Request, node_id: int):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_online_clients, node)
        return ORJSONResponse(content=payload)

    async def _get_node_client_traffic_impl(request: Request, node_id: int, email: str):
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        node = await run_in_threadpool(get_node_or_404, node_id)
        payload = await run_in_threadpool(xui_monitor.get_client_traffic, node, email)
        return ORJSONResponse(content=payload)

    @router.get("/api/v1/nodes/{node_id}/client-traffic")
    async def get_node_client_traffic_query(request: Request, node_id: int, email: str):
        # Query-param variant is robust for arbitrary client identifiers.
        return await _get_node_client_traffic_impl(request, node_id, email)

    @router.get("/api/v1/nodes/{node_id}/client/{email:path}/traffic")
    async def get_node_client_traffic_legacy(request: Request, node_id: int, email: str):
        # Backward-compatible path-based endpoint.
        return await _get_node_client_traffic_impl(request, node_id, email)

    @router.get("/api/v1/traffic/stats-by-period")
    async def get_traffic_stats_period(request: Request, group_by: str = "client", period: str = "all_time", limit: int = 0):
        """Get traffic stats for a specific period (day, week, month, year, all_time)"""
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        if group_by not in ["client", "inbound", "node"]:
            raise HTTPException(status_code=400, detail="group_by must be client, inbound, or node")
        if period not in ["day", "week", "month", "year", "all_time"]:
            raise HTTPException(status_code=400, detail="period must be day, week, month, year, or all_time")
        
        if not projection_period_handler:
            raise HTTPException(status_code=503, detail="Traffic statistics projection is warming up")

        # Statistics is a read-model: it must never enumerate nodes or invoke
        # the legacy cache helper, because either can trigger a remote 3x-ui
        # fan-out on each Day/Week/Month click.
        payload = await run_in_threadpool(projection_period_handler, group_by, period)
        return ORJSONResponse(content=_public_traffic_payload(payload, limit))

    @router.post("/api/v1/traffic/client-totals")
    async def get_client_traffic_totals(request: Request, data: Dict):
        """Return totals for requested emails from the existing period projection only."""
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401)
        # This is a read projection expressed as POST to carry a bounded email
        # list. It must not make the next Dashboard/Clients read cold.
        request.state.skip_read_projection_invalidation = True
        if not projection_period_handler:
            raise HTTPException(status_code=503, detail="Traffic statistics projection is warming up")
        period = data.get("period", "all_time")
        if period not in ["day", "week", "month", "year", "all_time"]:
            raise HTTPException(status_code=400, detail="period must be day, week, month, year, or all_time")
        emails = data.get("emails")
        if not isinstance(emails, list) or len(emails) > 5000:
            raise HTTPException(status_code=422, detail="emails must be a list with at most 5000 entries")
        wanted = {str(email).strip().casefold() for email in emails if isinstance(email, str) and str(email).strip()}
        payload = await run_in_threadpool(projection_period_handler, "client", period)
        stats = payload.get("stats") if isinstance(payload, dict) else {}
        totals = {}
        if isinstance(stats, dict):
            for email, value in stats.items():
                key = str(email).strip().casefold()
                if key not in wanted or not isinstance(value, dict):
                    continue
                totals[key] = _traffic_totals_from_projection({"stats": {key: value}})["total"]
        return ORJSONResponse(content={"totals": totals, "missing": sorted(wanted - set(totals)), "period": period})

    return router
