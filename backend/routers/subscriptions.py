import base64
import datetime
import json
import sqlite3
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse


def build_subscriptions_router(
    *,
    check_auth,
    db_path,
    node_service,
    check_subscription_rate_limit,
    get_emails,
    get_links_filtered,
    invalidate_subscription_cache,
    logger,
):
    router = APIRouter()

    def _no_cache_headers():
        return {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }

    def _ensure_stats_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                email TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_download TEXT DEFAULT ''
            )
            """
        )
        conn.commit()

    @router.get("/api/v1/emails")
    async def list_emails(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            emails = get_emails(node_service.list_nodes())

            stats = {}
            for row in conn.execute("SELECT * FROM stats").fetchall():
                stats[row["email"]] = {"count": row["count"], "last": row["last_download"]}

        return JSONResponse(content={"emails": emails, "stats": stats}, headers=_no_cache_headers())

    @router.get("/api/v1/sub/{email}")
    async def get_sub(request: Request, email: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
        allowed, retry_after = check_subscription_rate_limit(request, f"sub:{email.lower()}")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        no_cache_headers = _no_cache_headers()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()
            if nodes:
                node_names = [n.strip() for n in nodes.split(",")]
                all_nodes = [n for n in all_nodes if n["name"] in node_names]

            links = get_links_filtered(all_nodes, email, protocol)
            if links:
                now = datetime.datetime.now().strftime("%d.%m %H:%M")
                with sqlite3.connect(db_path) as db:
                    db.execute(
                        "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                        "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                        (email, now, now),
                    )
                    db.commit()
                return PlainTextResponse(
                    content=base64.b64encode("\n".join(links).encode()).decode(),
                    headers=no_cache_headers,
                )

        return PlainTextResponse(content="Not found", status_code=404, headers=no_cache_headers)

    @router.get("/api/v1/sub-grouped/{identifier}")
    async def get_sub_grouped(
        request: Request,
        identifier: str,
        protocol: Optional[str] = None,
        nodes: Optional[str] = None,
    ):
        allowed, retry_after = check_subscription_rate_limit(request, f"sub-grouped:{identifier.lower()}")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        no_cache_headers = _no_cache_headers()
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()

            custom_group = conn.execute(
                "SELECT * FROM subscription_groups WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            if custom_group:
                custom_group = dict(custom_group)
                if custom_group.get("node_filters"):
                    node_names = json.loads(custom_group["node_filters"])
                    all_nodes = [n for n in all_nodes if n["name"] in node_names]
                if custom_group.get("protocol_filter"):
                    protocol = custom_group["protocol_filter"]
                email_patterns = json.loads(custom_group.get("email_patterns", "[]"))
                all_emails = get_emails(all_nodes)
                matching_emails = []
                for pattern in email_patterns:
                    matching_emails.extend([e for e in all_emails if pattern.lower() in e.lower()])
                matching_emails = list(set(matching_emails))
            else:
                if nodes:
                    node_names = [n.strip() for n in nodes.split(",")]
                    all_nodes = [n for n in all_nodes if n["name"] in node_names]
                all_emails = get_emails(all_nodes)
                matching_emails = [e for e in all_emails if identifier.lower() in e.lower()]

            if not matching_emails:
                return PlainTextResponse(
                    content="No matching clients found",
                    status_code=404,
                    headers=no_cache_headers,
                )

            all_links = []
            for matched_email in matching_emails:
                all_links.extend(get_links_filtered(all_nodes, matched_email, protocol))

            if all_links:
                now = datetime.datetime.now().strftime("%d.%m %H:%M")
                with sqlite3.connect(db_path) as db:
                    for matched_email in matching_emails:
                        db.execute(
                            "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                            "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                            (matched_email, now, now),
                        )
                    db.commit()
                return PlainTextResponse(
                    content=base64.b64encode("\n".join(all_links).encode()).decode(),
                    headers=no_cache_headers,
                )

        return PlainTextResponse(content="Not found", status_code=404, headers=no_cache_headers)

    @router.get("/api/v1/subscription-groups")
    async def list_subscription_groups(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            groups = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM subscription_groups ORDER BY created_at DESC"
                ).fetchall()
            ]
            for group in groups:
                group["email_patterns"] = json.loads(group.get("email_patterns", "[]"))
                group["node_filters"] = json.loads(group.get("node_filters", "[]"))

        return {"groups": groups, "count": len(groups)}

    @router.post("/api/v1/subscription-groups")
    async def create_subscription_group(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        name = data.get("name")
        identifier = data.get("identifier")
        if not name or not identifier:
            raise HTTPException(status_code=400, detail="name and identifier required")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO subscription_groups
                    (name, identifier, description, email_patterns, node_filters, protocol_filter)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        identifier,
                        data.get("description", ""),
                        json.dumps(data.get("email_patterns", [])),
                        json.dumps(data.get("node_filters", [])),
                        data.get("protocol_filter"),
                    ),
                )
                conn.commit()
            invalidate_subscription_cache()
            return {"status": "success", "identifier": identifier}
        except Exception as exc:
            logger.error(f"Error creating subscription group: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

    @router.put("/api/v1/subscription-groups/{group_id}")
    async def update_subscription_group(request: Request, group_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        updates = []
        params = []
        if "name" in data:
            updates.append("name = ?")
            params.append(data["name"])
        if "identifier" in data:
            updates.append("identifier = ?")
            params.append(data["identifier"])
        if "description" in data:
            updates.append("description = ?")
            params.append(data["description"])
        if "email_patterns" in data:
            updates.append("email_patterns = ?")
            params.append(json.dumps(data["email_patterns"]))
        if "node_filters" in data:
            updates.append("node_filters = ?")
            params.append(json.dumps(data["node_filters"]))
        if "protocol_filter" in data:
            updates.append("protocol_filter = ?")
            params.append(data["protocol_filter"])
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(group_id)
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    f"UPDATE subscription_groups SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                conn.commit()
            invalidate_subscription_cache()
            return {"status": "success"}
        except Exception as exc:
            logger.error(f"Error updating subscription group: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

    @router.delete("/api/v1/subscription-groups/{group_id}")
    async def delete_subscription_group(request: Request, group_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("DELETE FROM subscription_groups WHERE id = ?", (group_id,))
                conn.commit()
            invalidate_subscription_cache()
            return {"status": "success"}
        except Exception as exc:
            logger.error(f"Error deleting subscription group: {exc}")
            raise HTTPException(status_code=500, detail=str(exc))

    return router
