from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import ORJSONResponse

from services.client_notes import enrich_clients_with_notes, upsert_client_note


def build_clients_router(
    *,
    check_auth,
    client_mgr,
    db_path,
    get_cached_clients,
    node_service,
    get_node_or_404,
    invalidate_live_stats_cache,
    invalidate_subscription_cache,
    ws_manager,
):
    router = APIRouter()

    async def _broadcast_client_update(payload: Dict):
        try:
            await ws_manager.broadcast_client_update(payload)
        except Exception:
            return

    async def _broadcast_traffic_update(payload: Dict):
        try:
            await ws_manager.broadcast_traffic_update(payload)
        except Exception:
            return

    def _load_nodes(node_ids=None):
        if node_ids:
            return [get_node_or_404(node_id) for node_id in node_ids]
        return node_service.list_nodes()

    def _with_notes(clients, nodes):
        return enrich_clients_with_notes(db_path, clients, nodes=nodes)

    @router.get("/api/v1/clients/count")
    async def count_clients(request: Request, node_id: Optional[int] = None):
        """Return total client count without the full payload."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        if node_id is not None:
            nodes = [get_node_or_404(node_id)]
        else:
            nodes = node_service.list_nodes()
        clients = get_cached_clients(nodes, email_filter=None)
        return {"count": len(clients), "node_id": node_id}

    @router.get("/api/v1/clients/expired")
    async def list_expired_clients(request: Request):
        """Return only expired clients (expiryTime > 0 and past)."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        import time as _time
        now_ms = int(_time.time() * 1000)
        nodes = node_service.list_nodes()
        clients = _with_notes(get_cached_clients(nodes, email_filter=None), nodes)
        expired = [c for c in clients if c.get("expiryTime", 0) > 0 and c.get("expiryTime", 0) < now_ms]
        return ORJSONResponse(content={"clients": expired, "count": len(expired)})

    @router.get("/api/v1/clients/depleted")
    async def list_depleted_clients(request: Request):
        """Return only traffic-depleted clients (used >= total > 0)."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = node_service.list_nodes()
        clients = _with_notes(get_cached_clients(nodes, email_filter=None), nodes)
        depleted = [
            c for c in clients
            if c.get("total", 0) > 0 and (c.get("up", 0) + c.get("down", 0)) >= c.get("total", 0)
        ]
        return ORJSONResponse(content={"clients": depleted, "count": len(depleted)})

    @router.get("/api/v1/clients/search")
    async def search_clients(
        request: Request,
        q: Optional[str] = None,
        node_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ):
        """Search clients by partial email match with optional filters and pagination.

        status: active | expired | depleted | disabled
        """
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        import time
        nodes = node_service.list_nodes()
        if node_id is not None:
            nodes = [n for n in nodes if int(n.get("id", -1)) == node_id]
        clients = _with_notes(get_cached_clients(nodes, email_filter=None), nodes)
        if q:
            q_lower = q.lower()
            clients = [c for c in clients if q_lower in c.get("email", "").lower()]
        now_ms = int(time.time() * 1000)
        if status == "active":
            clients = [c for c in clients if c.get("enable") and
                       (c.get("expiryTime", 0) == 0 or c.get("expiryTime", 0) > now_ms) and
                       (c.get("total", 0) == 0 or (c.get("up", 0) + c.get("down", 0)) < c.get("total", 0))]
        elif status == "expired":
            clients = [c for c in clients if c.get("expiryTime", 0) > 0 and c.get("expiryTime", 0) < now_ms]
        elif status == "depleted":
            clients = [c for c in clients if c.get("total", 0) > 0 and (c.get("up", 0) + c.get("down", 0)) >= c.get("total", 0)]
        elif status == "disabled":
            clients = [c for c in clients if not c.get("enable")]
        total = len(clients)
        page_clients = clients[offset: offset + limit]
        return ORJSONResponse(content={"clients": page_clients, "total": total, "limit": limit, "offset": offset})

    @router.get("/api/v1/clients")
    async def list_clients(request: Request, email: Optional[str] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = node_service.list_nodes()
        clients = _with_notes(get_cached_clients(nodes, email_filter=email), nodes)
        return ORJSONResponse(
            content={"clients": clients, "count": len(clients)},
            headers={"Cache-Control": "private, max-age=180"},
        )

    @router.get("/api/v1/nodes/{node_id}/clients")
    async def list_node_clients(request: Request, node_id: int, email: Optional[str] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = get_node_or_404(node_id)
        node_name = node.get("name", "")
        # Use the shared cache (20s fresh / 180s stale) instead of a live panel call.
        # Fetch all nodes so the cache covers the full fleet and filter to this node.
        all_nodes = node_service.list_nodes()
        all_clients = _with_notes(get_cached_clients(all_nodes, email_filter=email), all_nodes)
        clients = [c for c in all_clients if c.get("node_name") == node_name]
        return ORJSONResponse(
            content={"clients": clients, "count": len(clients)},
            headers={"Cache-Control": "private, max-age=20"},
        )

    @router.post("/api/v1/clients/batch-add")
    async def batch_add_clients(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_ids = data.get("node_ids")
        clients_configs = data.get("clients", [])
        nodes = _load_nodes(node_ids=node_ids)

        results = client_mgr.batch_add_clients(nodes, clients_configs)
        invalidate_live_stats_cache()
        invalidate_subscription_cache()
        await _broadcast_client_update({"action": "batch_add", "result": results, "_delta": True})
        return results

    @router.post("/api/v1/clients/add-to-nodes")
    async def add_client_to_nodes(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        email = data.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="email is required")

        inbound_id = data.get("inbound_id")
        if inbound_id is None:
            raise HTTPException(status_code=400, detail="inbound_id is required")

        nodes = _load_nodes(node_ids=data.get("node_ids"))

        try:
            results = client_mgr.add_client_to_multiple_nodes(
                nodes=nodes,
                email=email,
                inbound_id=inbound_id,
                flow=data.get("flow", ""),
                totalGB=data.get("totalGB", 0),
                expiryTime=data.get("expiryTime", 0),
                enable=data.get("enable", True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        invalidate_live_stats_cache()
        invalidate_subscription_cache()
        await _broadcast_client_update({"action": "add_to_nodes", "email": email, "result": results, "_delta": True})
        return results

    @router.put("/api/v1/clients/{client_uuid}")
    async def update_client(request: Request, client_uuid: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_id = data.get("node_id")
        inbound_id = data.get("inbound_id")
        updates = dict(data.get("updates", {}) or {})
        note_present = "notes" in updates
        note_value = updates.pop("notes", "")

        if not node_id or not inbound_id:
            raise HTTPException(status_code=400, detail="node_id and inbound_id required")

        node = get_node_or_404(node_id)
        success = True if not updates else client_mgr.update_client(node, inbound_id, client_uuid, updates)
        if success:
            saved_note = None
            if note_present:
                try:
                    saved_note = upsert_client_note(
                        db_path,
                        node_id=node_id,
                        inbound_id=inbound_id,
                        client_identifier=updates.get("id") or client_uuid,
                        email=updates.get("email") or data.get("email") or client_uuid,
                        notes=note_value,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
            invalidate_live_stats_cache()
            invalidate_subscription_cache()
            broadcast_updates = dict(updates)
            if saved_note is not None:
                broadcast_updates["notes"] = saved_note["notes"]
            await _broadcast_client_update(
                {
                    "action": "update_client",
                    "node_id": node_id,
                    "inbound_id": inbound_id,
                    "client_uuid": client_uuid,
                    "updates": broadcast_updates,
                    "_delta": True,
                }
            )
        return {"success": success}

    @router.put("/api/v1/clients/{client_identifier}/notes")
    @router.post("/api/v1/clients/{client_identifier}/notes")
    async def update_client_notes(request: Request, client_identifier: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        try:
            saved = upsert_client_note(
                db_path,
                node_id=data.get("node_id"),
                inbound_id=data.get("inbound_id", 0),
                client_identifier=client_identifier,
                email=data.get("email"),
                notes=data.get("notes", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        await _broadcast_client_update(
            {
                "action": "update_client_notes",
                "node_id": saved["node_id"],
                "inbound_id": saved["inbound_id"],
                "client_uuid": saved["client_identifier"],
                "email": saved["email"],
                "notes": saved["notes"],
                "_delta": True,
            }
        )
        return {"status": "success", **saved}

    @router.delete("/api/v1/clients/{client_uuid}")
    async def delete_client(request: Request, client_uuid: str, node_id: int, inbound_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node = get_node_or_404(node_id)
        success = client_mgr.delete_client(node, inbound_id, client_uuid)
        if success:
            invalidate_live_stats_cache()
            invalidate_subscription_cache()
            await _broadcast_client_update(
                {
                    "action": "delete_client",
                    "node_id": node_id,
                    "inbound_id": inbound_id,
                    "client_uuid": client_uuid,
                    "_delta": True,
                }
            )
        return {"success": success}

    @router.post("/api/v1/clients/batch-delete")
    async def batch_delete_clients(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        nodes = _load_nodes(node_ids=data.get("node_ids"))
        results = client_mgr.batch_delete_clients(
            nodes,
            data.get("email_pattern"),
            data.get("expired_only", False),
            data.get("depleted_only", False),
        )
        invalidate_live_stats_cache()
        invalidate_subscription_cache()
        await _broadcast_client_update(
            {
                "action": "batch_delete",
                "result": results,
                "expired_only": data.get("expired_only", False),
                "depleted_only": data.get("depleted_only", False),
                "_delta": True,
            }
        )
        return results

    @router.post("/api/v1/clients/{client_uuid}/reset-traffic")
    async def reset_client_traffic(request: Request, client_uuid: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)

        node_id = data.get("node_id")
        inbound_id = data.get("inbound_id")
        email = data.get("email")
        if not all([node_id, inbound_id, email]):
            raise HTTPException(status_code=400, detail="node_id, inbound_id, and email required")

        node = get_node_or_404(node_id)
        success = client_mgr.reset_client_traffic(node, inbound_id, email)
        if success:
            await _broadcast_traffic_update(
                {
                    "action": "reset_client_traffic",
                    "node_id": node_id,
                    "inbound_id": inbound_id,
                    "client_uuid": client_uuid,
                    "email": email,
                    "_delta": True,
                }
            )
        return {"success": success}

    @router.post("/api/v1/clients/del-depleted")
    async def del_depleted_clients(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node_ids = data.get("node_ids")
        nodes = _load_nodes(node_ids=node_ids)
        result = client_mgr.del_depleted(nodes)
        if result.get("total_deleted", 0) > 0:
            invalidate_live_stats_cache()
            invalidate_subscription_cache()
        return result

    @router.post("/api/v1/clients/bulk-adjust")
    async def bulk_adjust_clients(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node_ids = data.get("node_ids")
        emails = data.get("emails", [])
        add_days = int(data.get("add_days", 0))
        add_bytes = int(data.get("add_bytes", 0))
        if not emails:
            raise HTTPException(status_code=400, detail="emails required")
        if not add_days and not add_bytes:
            raise HTTPException(status_code=400, detail="add_days or add_bytes required")
        nodes = _load_nodes(node_ids=node_ids)
        result = client_mgr.bulk_adjust(nodes, emails, add_days=add_days, add_bytes=add_bytes)
        if result.get("total_adjusted", 0) > 0:
            invalidate_live_stats_cache()
        return result

    @router.get("/api/v1/clients/{email}/links")
    async def get_client_links(request: Request, email: str, node_id: Optional[int] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        if node_id:
            nodes = [get_node_or_404(node_id)]
        else:
            nodes = node_service.list_nodes()
        all_links = []
        for node in nodes:
            links = client_mgr.get_client_links(node, email)
            all_links.extend(links)
        return {"email": email, "links": all_links, "count": len(all_links)}

    @router.post("/api/v1/clients/bulk-enable")
    async def bulk_enable_clients(request: Request, data: Dict):
        """Включить/выключить несколько клиентов по email."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        emails: list = data.get("emails", [])
        enable: bool = bool(data.get("enable", True))
        node_ids = data.get("node_ids")
        if not emails:
            raise HTTPException(status_code=400, detail="emails required")
        nodes = _load_nodes(node_ids=node_ids)
        results = []
        for node in nodes:
            for email in emails:
                ok = client_mgr.update_client(
                    node, 0, email,
                    {"enable": enable, "email": email},
                )
                results.append({"email": email, "node": node["name"], "success": ok})
        ok_count = sum(1 for r in results if r["success"])
        if ok_count > 0:
            invalidate_live_stats_cache()
        return {"results": results, "updated": ok_count}

    @router.get("/api/v1/clients/online")
    async def get_online_clients(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = node_service.list_nodes()
        online = client_mgr.get_online_clients(nodes)
        return ORJSONResponse(content={"online": online, "count": len(online)})

    # --- IP tracking ---

    @router.get("/api/v1/clients/{email}/ips")
    async def get_client_ips(request: Request, email: str, node_id: Optional[int] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = [get_node_or_404(node_id)] if node_id else node_service.list_nodes()
        results = []
        for node in nodes:
            r = client_mgr.get_client_ips(node, email)
            if r.get("ips"):
                results.append({"node": node["name"], "ips": r["ips"]})
        return {"email": email, "results": results}

    @router.post("/api/v1/clients/{email}/clear-ips")
    async def clear_client_ips(request: Request, email: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node_id = data.get("node_id")
        nodes = [get_node_or_404(node_id)] if node_id else node_service.list_nodes()
        ok = any(client_mgr.clear_client_ips(n, email) for n in nodes)
        return {"success": ok}

    @router.get("/api/v1/clients/find-by-ip")
    async def find_clients_by_ip(request: Request, ip: str, node_id: Optional[int] = None):
        """Search which clients have connected from a given IP address."""
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        if not ip or not ip.strip():
            raise HTTPException(status_code=400, detail="ip parameter required")
        nodes = [get_node_or_404(node_id)] if node_id else node_service.list_nodes()
        matches = []
        for node in nodes:
            try:
                all_clients = client_mgr.get_all_clients([node])
                for c in all_clients:
                    email = c.get("email", "")
                    if not email:
                        continue
                    ip_result = client_mgr.get_client_ips(node, email)
                    client_ips = ip_result.get("ips", [])
                    if ip.strip() in client_ips:
                        matches.append({"email": email, "node": node["name"], "ips": client_ips})
            except Exception:
                pass
        return {"ip": ip, "matches": matches, "count": len(matches)}

    @router.post("/api/v1/clients/last-online")
    async def get_last_online(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node_ids = data.get("node_ids")
        emails = data.get("emails")
        nodes = _load_nodes(node_ids=node_ids)
        merged: Dict = {}
        for node in nodes:
            r = client_mgr.get_last_online(node, emails)
            merged.update(r.get("data") or {})
        results = [{"email": k, "last_online": v} for k, v in merged.items()]
        return {"results": results, "data": merged}

    # --- Bulk traffic reset ---

    @router.post("/api/v1/clients/bulk-reset-traffic")
    async def bulk_reset_traffic(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        emails = data.get("emails", [])
        node_ids = data.get("node_ids")
        if not emails:
            raise HTTPException(status_code=400, detail="emails required")
        nodes = _load_nodes(node_ids=node_ids)
        result = client_mgr.bulk_reset_traffic(nodes, emails)
        if result.get("successful", 0) > 0:
            invalidate_live_stats_cache()
        return result

    # --- Attach / Detach ---

    @router.post("/api/v1/clients/{email}/attach")
    async def attach_client(request: Request, email: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node_id = data.get("node_id")
        inbound_ids = data.get("inbound_ids", [])
        if not node_id or not inbound_ids:
            raise HTTPException(status_code=400, detail="node_id and inbound_ids required")
        ok = client_mgr.attach_client(get_node_or_404(node_id), email, inbound_ids)
        if ok:
            invalidate_subscription_cache()
        return {"success": ok}

    @router.post("/api/v1/clients/{email}/detach")
    async def detach_client(request: Request, email: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        node_id = data.get("node_id")
        inbound_ids = data.get("inbound_ids", [])
        if not node_id or not inbound_ids:
            raise HTTPException(status_code=400, detail="node_id and inbound_ids required")
        ok = client_mgr.detach_client(get_node_or_404(node_id), email, inbound_ids)
        if ok:
            invalidate_subscription_cache()
        return {"success": ok}

    # --- Groups ---

    @router.get("/api/v1/nodes/{node_id}/client-groups")
    async def get_client_groups(request: Request, node_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return client_mgr.get_client_groups(get_node_or_404(node_id))

    @router.post("/api/v1/nodes/{node_id}/client-groups")
    async def create_client_group(request: Request, node_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        ok = client_mgr.create_client_group(get_node_or_404(node_id), name)
        return {"success": ok}

    @router.put("/api/v1/nodes/{node_id}/client-groups/{group_name}")
    async def rename_client_group(request: Request, node_id: int, group_name: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        new_name = (data.get("newName") or "").strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="newName required")
        ok = client_mgr.rename_client_group(get_node_or_404(node_id), group_name, new_name)
        return {"success": ok}

    @router.delete("/api/v1/nodes/{node_id}/client-groups/{group_name}")
    async def delete_client_group(request: Request, node_id: int, group_name: str):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        ok = client_mgr.delete_client_group(get_node_or_404(node_id), group_name)
        return {"success": ok}

    @router.post("/api/v1/nodes/{node_id}/client-groups/{group_name}/add")
    async def add_to_group(request: Request, node_id: int, group_name: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        emails = data.get("emails", [])
        if not emails:
            raise HTTPException(status_code=400, detail="emails required")
        ok = client_mgr.add_to_group(get_node_or_404(node_id), group_name, emails)
        return {"success": ok}

    @router.post("/api/v1/nodes/{node_id}/client-groups/{group_name}/remove")
    async def remove_from_group(request: Request, node_id: int, group_name: str, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        emails = data.get("emails", [])
        if not emails:
            raise HTTPException(status_code=400, detail="emails required")
        ok = client_mgr.remove_from_group(get_node_or_404(node_id), group_name, emails)
        return {"success": ok}

    @router.get("/api/v1/nodes/{node_id}/client-groups/{group_name}/emails")
    async def get_group_emails(request: Request, node_id: int, group_name: str):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        return client_mgr.get_group_emails(get_node_or_404(node_id), group_name)

    # --- Sub links by subscription ID ---

    @router.get("/api/v1/clients/sub-links/{sub_id}")
    async def get_sub_links(request: Request, sub_id: str, node_id: Optional[int] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401)
        nodes = [get_node_or_404(node_id)] if node_id else node_service.list_nodes()
        all_links = []
        for node in nodes:
            all_links.extend(client_mgr.get_sub_links(node, sub_id))
        return {"sub_id": sub_id, "links": all_links, "count": len(all_links)}

    return router
