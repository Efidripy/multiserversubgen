import base64
import datetime
import hashlib
import hmac
import json
import sqlite3
import time
from threading import Lock
from services.db_bootstrap import connect
from shared.sql import update_by_id_query
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
    subscription_signing_secret,
    invalidate_subscription_cache,
    logger,
):
    router = APIRouter()
    subscription_response_cache: Dict[str, tuple[float, str]] = {}
    subscription_response_cache_lock = Lock()
    subscription_response_cache_ttl = 300
    subscription_response_cache_max_size = 1024
    subscription_token_ttl_sec = 30 * 24 * 60 * 60

    def _no_cache_headers():
        return {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }

    def _subscription_headers(cache_status: str):
        headers = _no_cache_headers()
        headers["X-Subscription-Cache"] = cache_status
        return headers

    def _subscription_cache_key(request: Request, identifier: str) -> str:
        query_items = sorted((key, value) for key, value in request.query_params.multi_items())
        raw_key = json.dumps(
            {"identifier": identifier, "query": query_items},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _get_subscription_response_cache(cache_key: str) -> Optional[str]:
        now = time.time()
        with subscription_response_cache_lock:
            cached = subscription_response_cache.get(cache_key)
            if not cached:
                return None
            ts, content = cached
            if now - ts > subscription_response_cache_ttl:
                subscription_response_cache.pop(cache_key, None)
                return None
            return content

    def _set_subscription_response_cache(cache_key: str, content: str) -> None:
        with subscription_response_cache_lock:
            if len(subscription_response_cache) >= subscription_response_cache_max_size and cache_key not in subscription_response_cache:
                oldest_key = min(subscription_response_cache, key=lambda item: subscription_response_cache[item][0])
                subscription_response_cache.pop(oldest_key, None)
            subscription_response_cache[cache_key] = (time.time(), content)

    def _clear_subscription_response_cache() -> None:
        with subscription_response_cache_lock:
            subscription_response_cache.clear()

    def _issue_subscription_token(kind: str, identifier: str) -> str:
        expires = int(time.time()) + subscription_token_ttl_sec
        payload = f"{kind}|{identifier}|{expires}".encode("utf-8")
        signature = hmac.new(subscription_signing_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        return f"{encoded}.{signature}"

    def _verify_subscription_token(token: str, expected_kind: str) -> Optional[str]:
        if not token or "." not in token:
            return None
        encoded, signature = token.rsplit(".", 1)
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(padded.encode("ascii"))
            expected = hmac.new(subscription_signing_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            kind, identifier, expires = payload.decode("utf-8").split("|", 2)
            if kind != expected_kind or int(expires) < int(time.time()) or not identifier:
                return None
            return identifier
        except (ValueError, TypeError, UnicodeError):
            return None

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

    # These handlers intentionally remain synchronous: FastAPI runs sync route
    # functions in its worker thread pool, keeping SQLite and panel I/O out of
    # the event loop as one coherent transaction boundary.
    @router.get("/api/v1/emails")
    def list_emails(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            emails = get_emails(node_service.list_nodes())

            stats = {}
            for row in conn.execute("SELECT * FROM stats").fetchall():
                stats[row["email"]] = {"count": row["count"], "last": row["last_download"]}

        return JSONResponse(
            content={
                "emails": emails,
                "stats": stats,
                "subscription_tokens": {email: _issue_subscription_token("email", email) for email in emails},
            },
            headers=_no_cache_headers(),
        )

    @router.get("/api/v1/sub/{email}")
    def get_sub(request: Request, email: str, protocol: Optional[str] = None, nodes: Optional[str] = None):
        resolved_email = _verify_subscription_token(email, "email")
        if not resolved_email:
            return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
        allowed, retry_after = check_subscription_rate_limit(request, f"sub:{hashlib.sha256(email.encode()).hexdigest()}")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        no_cache_headers = _no_cache_headers()
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()
            if nodes:
                node_names = [n.strip() for n in nodes.split(",")]
                all_nodes = [n for n in all_nodes if n["name"] in node_names]

            links = get_links_filtered(all_nodes, resolved_email, protocol)
            if links:
                now = datetime.datetime.now().strftime("%d.%m %H:%M")
                with connect(db_path) as db:
                    db.execute(
                        "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                        "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                        (resolved_email, now, now),
                    )
                    db.commit()
                return PlainTextResponse(
                    content=base64.b64encode("\n".join(links).encode()).decode(),
                    headers=no_cache_headers,
                )

        return PlainTextResponse(content="Not found", status_code=404, headers=no_cache_headers)

    @router.get("/api/v1/sub-grouped/{identifier}")
    def get_sub_grouped(
        request: Request,
        identifier: str,
        protocol: Optional[str] = None,
        nodes: Optional[str] = None,
    ):
        resolved_identifier = _verify_subscription_token(identifier, "group")
        if not resolved_identifier:
            return PlainTextResponse(content="Not found", status_code=404, headers=_no_cache_headers())
        allowed, retry_after = check_subscription_rate_limit(request, f"sub-grouped:{hashlib.sha256(identifier.encode()).hexdigest()}")
        if not allowed:
            return PlainTextResponse(
                content=f"Rate limit exceeded. Retry after {retry_after}s",
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        cache_key = _subscription_cache_key(request, resolved_identifier)
        cached_response = _get_subscription_response_cache(cache_key)
        if cached_response is not None:
            return PlainTextResponse(
                content=cached_response,
                headers=_subscription_headers("hit"),
            )

        no_cache_headers = _subscription_headers("miss")
        with connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            _ensure_stats_table(conn)
            all_nodes = node_service.list_nodes()

            custom_group = conn.execute(
                "SELECT * FROM subscription_groups WHERE identifier = ?",
                (resolved_identifier,),
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
                matching_emails = [
                    email for email in all_emails
                    if any(email.lower() == pattern.lower() for pattern in email_patterns)
                ]
            else:
                matching_emails = []

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
                content = base64.b64encode("\n".join(all_links).encode()).decode()
                with connect(db_path) as db:
                    for matched_email in matching_emails:
                        db.execute(
                            "INSERT INTO stats (email, count, last_download) VALUES (?, 1, ?) "
                            "ON CONFLICT(email) DO UPDATE SET count=count+1, last_download=?",
                            (matched_email, now, now),
                        )
                    db.commit()
                _set_subscription_response_cache(cache_key, content)
                return PlainTextResponse(
                    content=content,
                    headers=no_cache_headers,
                )

        return PlainTextResponse(content="Not found", status_code=404, headers=no_cache_headers)

    @router.get("/api/v1/subscription-groups")
    def list_subscription_groups(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with connect(db_path) as conn:
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
                group["subscription_token"] = _issue_subscription_token("group", group["identifier"])

        return {"groups": groups, "count": len(groups)}

    @router.post("/api/v1/subscription-groups")
    def create_subscription_group(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        name = data.get("name")
        identifier = data.get("identifier")
        if not name or not identifier:
            raise HTTPException(status_code=400, detail="name and identifier required")

        try:
            with connect(db_path) as conn:
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
            _clear_subscription_response_cache()
            return {"status": "success", "identifier": identifier}
        except Exception as exc:
            logger.error(f"Error creating subscription group: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.put("/api/v1/subscription-groups/{group_id}")
    def update_subscription_group(request: Request, group_id: int, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        updates = []
        params = []
        if "name" in data:
            updates.append("name")
            params.append(data["name"])
        if "identifier" in data:
            updates.append("identifier")
            params.append(data["identifier"])
        if "description" in data:
            updates.append("description")
            params.append(data["description"])
        if "email_patterns" in data:
            updates.append("email_patterns")
            params.append(json.dumps(data["email_patterns"]))
        if "node_filters" in data:
            updates.append("node_filters")
            params.append(json.dumps(data["node_filters"]))
        if "protocol_filter" in data:
            updates.append("protocol_filter")
            params.append(data["protocol_filter"])
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        params.append(group_id)
        try:
            with connect(db_path) as conn:
                conn.execute(
                    update_by_id_query(
                        "subscription_groups",
                        updates,
                        extra_set=("updated_at = CURRENT_TIMESTAMP",),
                    ),
                    params,
                )
                conn.commit()
            invalidate_subscription_cache()
            _clear_subscription_response_cache()
            return {"status": "success"}
        except Exception as exc:
            logger.error(f"Error updating subscription group: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete("/api/v1/subscription-groups/{group_id}")
    def delete_subscription_group(request: Request, group_id: int):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        try:
            with connect(db_path) as conn:
                conn.execute("DELETE FROM subscription_groups WHERE id = ?", (group_id,))
                conn.commit()
            invalidate_subscription_cache()
            _clear_subscription_response_cache()
            return {"status": "success"}
        except Exception as exc:
            logger.error(f"Error deleting subscription group: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router
