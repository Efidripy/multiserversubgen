import json
import sqlite3
import time
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse


def build_monitoring_router(
    *,
    check_auth,
    db_path,
    verify_tls_default,
    encrypt,
    list_adguard_sources,
    collect_adguard_once,
    adguard_latest,
    adguard_latest_lock,
    adguard_collect_interval_sec,
    build_adguard_summary,
    build_adguard_history,
    parse_basic_auth_pair,
    http_probe,
    prom_query,
    prometheus_url,
    loki_url,
    grafana_url,
    prometheus_basic_auth,
    loki_basic_auth,
    grafana_basic_auth,
    web_path,
    grafana_web_path,
):
    router = APIRouter()

    @router.get("/api/v1/adguard/sources")
    async def list_adguard_sources_route(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return JSONResponse(
            content=list_adguard_sources(include_password=False),
            headers={"Cache-Control": "private, max-age=30"},
        )

    @router.post("/api/v1/adguard/sources")
    async def add_adguard_source(request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        name = str(data.get("name") or "").strip()
        admin_url = str(data.get("admin_url") or "").strip()
        dns_url = str(data.get("dns_url") or "").strip()
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "").strip()
        verify_tls = bool(data.get("verify_tls", verify_tls_default))
        enabled = bool(data.get("enabled", True))

        if not all([name, admin_url, username, password]):
            raise HTTPException(status_code=400, detail="Missing required fields")
        if not admin_url.startswith(("http://", "https://")):
            admin_url = "https://" + admin_url
        if dns_url and not dns_url.startswith(("http://", "https://")):
            dns_url = "http://" + dns_url

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO adguard_sources (name, admin_url, dns_url, username, password, verify_tls, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    admin_url,
                    dns_url,
                    username,
                    encrypt(password),
                    1 if verify_tls else 0,
                    1 if enabled else 0,
                ),
            )
            conn.commit()
        return {"status": "success"}

    @router.put("/api/v1/adguard/sources/{source_id}")
    async def update_adguard_source(source_id: int, request: Request, data: Dict):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM adguard_sources WHERE id = ?", (source_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Source not found")

            name = str(data.get("name") if data.get("name") is not None else row["name"]).strip()
            admin_url = str(data.get("admin_url") if data.get("admin_url") is not None else row["admin_url"]).strip()
            dns_url = str(data.get("dns_url") if data.get("dns_url") is not None else row["dns_url"]).strip()
            username = str(data.get("username") if data.get("username") is not None else row["username"]).strip()
            verify_tls = bool(data.get("verify_tls")) if data.get("verify_tls") is not None else bool(row["verify_tls"])
            enabled = bool(data.get("enabled")) if data.get("enabled") is not None else bool(row["enabled"])
            encrypted_password = row["password"]
            password_plain = str(data.get("password") or "").strip()
            if password_plain:
                encrypted_password = encrypt(password_plain)

            if not all([name, admin_url, username, encrypted_password]):
                raise HTTPException(status_code=400, detail="Missing required fields")
            if not admin_url.startswith(("http://", "https://")):
                admin_url = "https://" + admin_url
            if dns_url and not dns_url.startswith(("http://", "https://")):
                dns_url = "http://" + dns_url

            conn.execute(
                """
                UPDATE adguard_sources
                SET name = ?, admin_url = ?, dns_url = ?, username = ?, password = ?,
                    verify_tls = ?, enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name,
                    admin_url,
                    dns_url,
                    username,
                    encrypted_password,
                    1 if verify_tls else 0,
                    1 if enabled else 0,
                    source_id,
                ),
            )
            conn.commit()
        return {"status": "success"}

    @router.delete("/api/v1/adguard/sources/{source_id}")
    async def delete_adguard_source(source_id: int, request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM adguard_sources WHERE id = ?", (source_id,))
            conn.execute("DELETE FROM adguard_history WHERE source_id = ?", (source_id,))
            conn.commit()
        return {"status": "success"}

    @router.post("/api/v1/adguard/collect-now")
    async def adguard_collect_now(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        snapshots = await collect_adguard_once()
        return {"status": "success", "count": len(snapshots), "sources": snapshots}

    @router.get("/api/v1/adguard/overview")
    async def adguard_overview(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        with adguard_latest_lock:
            latest_ts = float(adguard_latest.get("ts") or 0)
            latest_sources = list(adguard_latest.get("sources") or [])
            latest_summary = dict(adguard_latest.get("summary") or {})

        if latest_sources and time.time() - latest_ts < max(20, adguard_collect_interval_sec * 2):
            return {
                "ts": int(latest_ts),
                "sources": latest_sources,
                "summary": latest_summary or build_adguard_summary(latest_sources),
            }

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT h.*
                FROM adguard_history h
                INNER JOIN (
                    SELECT source_id, MAX(ts) AS max_ts
                    FROM adguard_history
                    GROUP BY source_id
                ) x ON x.source_id = h.source_id AND x.max_ts = h.ts
                ORDER BY h.source_name COLLATE NOCASE ASC
                """
            ).fetchall()

        sources = []
        for row in rows:
            extra = {}
            if row["extra_json"]:
                try:
                    extra = json.loads(row["extra_json"])
                except Exception:
                    extra = {}
            sources.append(
                {
                    "source_id": int(row["source_id"]),
                    "source_name": row["source_name"],
                    "available": bool(row["available"]),
                    "queries_total": float(row["queries_total"] or 0),
                    "blocked_total": float(row["blocked_total"] or 0),
                    "blocked_rate": float(row["blocked_rate"] or 0),
                    "cache_hit_ratio": float(row["cache_hit_ratio"] or 0),
                    "avg_latency_ms": float(row["avg_latency_ms"] or 0),
                    "upstream_errors": float(row["upstream_errors"] or 0),
                    "top_domains": extra.get("top_domains", []),
                    "top_blocked_domains": extra.get("top_blocked_domains", []),
                    "top_clients": extra.get("top_clients", []),
                }
            )
        return {"ts": int(time.time()), "sources": sources, "summary": build_adguard_summary(sources)}

    @router.get("/api/v1/adguard/history")
    async def adguard_history(request: Request, range_sec: int = 24 * 3600, bucket_sec: int = 300, source_id: Optional[int] = None):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return build_adguard_history(range_sec=range_sec, bucket_sec=bucket_sec, source_id=source_id)

    @router.get("/api/v1/monitoring/stack")
    async def monitoring_stack(request: Request):
        user = check_auth(request)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")

        prom_auth = parse_basic_auth_pair(prometheus_basic_auth)
        loki_auth = parse_basic_auth_pair(loki_basic_auth)
        graf_auth = parse_basic_auth_pair(grafana_basic_auth)

        prometheus = http_probe(prometheus_url, "/-/ready", basic_auth=prom_auth)
        loki = http_probe(loki_url, "/ready", basic_auth=loki_auth)
        grafana = http_probe(grafana_url, "/api/health", basic_auth=graf_auth)

        prom_metrics = {}
        if prometheus.get("ok"):
            prom_metrics = {
                "up_sum": prom_query(prometheus_url, "sum(up)", basic_auth=prom_auth),
                "adguard_queries_sum": prom_query(prometheus_url, "sum(sub_manager_adguard_dns_queries_total)", basic_auth=prom_auth),
                "adguard_blocked_sum": prom_query(prometheus_url, "sum(sub_manager_adguard_dns_blocked_total)", basic_auth=prom_auth),
                "adguard_block_rate_avg": prom_query(prometheus_url, "avg(sub_manager_adguard_dns_block_rate_percent)", basic_auth=prom_auth),
                "node_online_sum": prom_query(prometheus_url, "sum(sub_manager_node_available)", basic_auth=prom_auth),
                "node_clients_sum": prom_query(prometheus_url, "sum(sub_manager_node_online_clients)", basic_auth=prom_auth),
            }

        return {
            "ts": int(time.time()),
            "public_paths": {"panel": web_path, "grafana": grafana_web_path},
            "services": {"prometheus": prometheus, "loki": loki, "grafana": grafana},
            "prometheus_metrics": prom_metrics,
        }

    return router
