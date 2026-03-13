from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

import requests


class AdGuardRuntime:
    def __init__(
        self,
        *,
        db_path: str,
        requests_verify,
        collect_interval_sec: int,
        latest_state: Dict,
        latest_lock,
        adguard_monitor,
        source_available_metric,
        dns_queries_total_metric,
        dns_blocked_total_metric,
        dns_block_rate_metric,
        dns_latency_ms_metric,
        dns_cache_hit_ratio_metric,
        dns_upstream_errors_metric,
        logger,
    ) -> None:
        self.db_path = db_path
        self.requests_verify = requests_verify
        self.collect_interval_sec = collect_interval_sec
        self.latest_state = latest_state
        self.latest_lock = latest_lock
        self.adguard_monitor = adguard_monitor
        self.source_available_metric = source_available_metric
        self.dns_queries_total_metric = dns_queries_total_metric
        self.dns_blocked_total_metric = dns_blocked_total_metric
        self.dns_block_rate_metric = dns_block_rate_metric
        self.dns_latency_ms_metric = dns_latency_ms_metric
        self.dns_cache_hit_ratio_metric = dns_cache_hit_ratio_metric
        self.dns_upstream_errors_metric = dns_upstream_errors_metric
        self.logger = logger

    @staticmethod
    def _row_to_public(row: sqlite3.Row) -> Dict:
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "admin_url": row["admin_url"],
            "dns_url": row["dns_url"] or "",
            "username": row["username"],
            "verify_tls": bool(row["verify_tls"]),
            "enabled": bool(row["enabled"]),
            "last_error": row["last_error"] or "",
            "last_success_ts": int(row["last_success_ts"] or 0),
            "last_collected_ts": int(row["last_collected_ts"] or 0),
            "api_base": row["api_base"] or "",
            "has_password": bool(row["password"]),
        }

    def list_sources(self, include_password: bool = False) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, name, admin_url, dns_url, username, password, verify_tls, enabled,
                       last_error, last_success_ts, last_collected_ts, api_base
                FROM adguard_sources
                ORDER BY name COLLATE NOCASE ASC
                """
            ).fetchall()
        result = []
        for row in rows:
            item = self._row_to_public(row)
            if include_password:
                item["password"] = row["password"]
            result.append(item)
        return result

    def list_enabled_sources_raw(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, name, admin_url, dns_url, username, password, verify_tls, enabled
                FROM adguard_sources
                WHERE enabled = 1
                ORDER BY id ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def record_snapshot(self, snapshot: Dict) -> None:
        source_id = str(snapshot.get("source_id") or "0")
        source_name = str(snapshot.get("source_name") or f"adguard-{source_id}")
        available = bool(snapshot.get("available"))

        self.source_available_metric.labels(source_name=source_name, source_id=source_id).set(1 if available else 0)
        self.dns_queries_total_metric.labels(source_name=source_name, source_id=source_id).set(float(snapshot.get("queries_total", 0) or 0))
        self.dns_blocked_total_metric.labels(source_name=source_name, source_id=source_id).set(float(snapshot.get("blocked_total", 0) or 0))
        self.dns_block_rate_metric.labels(source_name=source_name, source_id=source_id).set(float(snapshot.get("blocked_rate", 0) or 0))
        self.dns_latency_ms_metric.labels(source_name=source_name, source_id=source_id).set(float(snapshot.get("avg_latency_ms", 0) or 0))
        self.dns_cache_hit_ratio_metric.labels(source_name=source_name, source_id=source_id).set(float(snapshot.get("cache_hit_ratio", 0) or 0))
        self.dns_upstream_errors_metric.labels(source_name=source_name, source_id=source_id).set(float(snapshot.get("upstream_errors", 0) or 0))

        now_ts = int(time.time())
        extra = {
            "top_domains": snapshot.get("top_domains", []),
            "top_blocked_domains": snapshot.get("top_blocked_domains", []),
            "top_clients": snapshot.get("top_clients", []),
            "status": snapshot.get("status", {}),
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO adguard_history (
                    ts, source_id, source_name, available, queries_total, blocked_total,
                    blocked_rate, cache_hit_ratio, avg_latency_ms, upstream_errors, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ts,
                    int(snapshot.get("source_id") or 0),
                    source_name,
                    1 if available else 0,
                    float(snapshot.get("queries_total", 0) or 0),
                    float(snapshot.get("blocked_total", 0) or 0),
                    float(snapshot.get("blocked_rate", 0) or 0),
                    float(snapshot.get("cache_hit_ratio", 0) or 0),
                    float(snapshot.get("avg_latency_ms", 0) or 0),
                    float(snapshot.get("upstream_errors", 0) or 0),
                    json.dumps(extra, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                UPDATE adguard_sources
                SET last_error = ?,
                    last_success_ts = CASE WHEN ? > 0 THEN ? ELSE last_success_ts END,
                    last_collected_ts = ?,
                    api_base = CASE WHEN ? != '' THEN ? ELSE api_base END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(snapshot.get("error") or ""),
                    now_ts if available else 0,
                    now_ts if available else 0,
                    now_ts,
                    str(snapshot.get("api_base") or ""),
                    str(snapshot.get("api_base") or ""),
                    int(snapshot.get("source_id") or 0),
                ),
            )
            conn.execute(
                "DELETE FROM adguard_history WHERE ts < ?",
                (int(time.time()) - 30 * 24 * 3600,),
            )
            conn.commit()

    @staticmethod
    def build_summary(snapshots: List[Dict]) -> Dict:
        live = [s for s in snapshots if s.get("available")]
        total_queries = sum(float(s.get("queries_total", 0) or 0) for s in live)
        total_blocked = sum(float(s.get("blocked_total", 0) or 0) for s in live)
        blocked_rate = (total_blocked / total_queries * 100.0) if total_queries > 0 else 0.0
        avg_latency = 0.0
        if live:
            avg_latency = sum(float(s.get("avg_latency_ms", 0) or 0) for s in live) / len(live)
        cache_hit = 0.0
        if live:
            cache_hit = sum(float(s.get("cache_hit_ratio", 0) or 0) for s in live) / len(live)
        upstream_errors = sum(float(s.get("upstream_errors", 0) or 0) for s in live)
        return {
            "sources_total": len(snapshots),
            "sources_online": len(live),
            "queries_total": round(total_queries, 2),
            "blocked_total": round(total_blocked, 2),
            "blocked_rate": round(blocked_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "cache_hit_ratio": round(cache_hit, 2),
            "upstream_errors": round(upstream_errors, 2),
        }

    @staticmethod
    def parse_basic_auth_pair(value: str) -> Optional[Tuple[str, str]]:
        if not value or ":" not in value:
            return None
        user, pwd = value.split(":", 1)
        user = user.strip()
        if not user:
            return None
        return user, pwd

    def http_probe(self, url: str, path: str, timeout: int = 4, basic_auth: Optional[Tuple[str, str]] = None) -> Dict:
        if not url:
            return {"enabled": False, "url": "", "ok": False, "status_code": None, "error": "disabled"}
        full = f"{url.rstrip('/')}{path}"
        try:
            resp = requests.get(full, timeout=timeout, verify=self.requests_verify, auth=basic_auth)
            return {
                "enabled": True,
                "url": url,
                "ok": 200 <= resp.status_code < 300,
                "status_code": int(resp.status_code),
                "error": "" if 200 <= resp.status_code < 300 else (resp.text[:120] if resp.text else f"HTTP {resp.status_code}"),
            }
        except Exception as exc:
            return {"enabled": True, "url": url, "ok": False, "status_code": None, "error": str(exc)}

    def prom_query(self, prom_url: str, query: str, basic_auth: Optional[Tuple[str, str]] = None) -> Optional[float]:
        if not prom_url:
            return None
        try:
            resp = requests.get(
                f"{prom_url.rstrip('/')}/api/v1/query",
                params={"query": query},
                timeout=5,
                verify=self.requests_verify,
                auth=basic_auth,
            )
            if resp.status_code != 200:
                return None
            payload = resp.json()
            if payload.get("status") != "success":
                return None
            result = payload.get("data", {}).get("result", [])
            if not result:
                return 0.0
            first = result[0]
            value = first.get("value", [None, None])[1]
            return float(value) if value is not None else 0.0
        except Exception:
            return None

    def build_history(self, range_sec: int, bucket_sec: int, source_id: Optional[int] = None) -> Dict:
        safe_range = max(300, min(range_sec, 30 * 24 * 3600))
        safe_bucket = max(30, min(bucket_sec, 6 * 3600))
        since_ts = int(time.time()) - safe_range

        sql = """
            SELECT ts, source_id, source_name, available, queries_total, blocked_total,
                   blocked_rate, cache_hit_ratio, avg_latency_ms, upstream_errors
            FROM adguard_history
            WHERE ts >= ?
        """
        params: List = [since_ts]
        if source_id is not None:
            sql += " AND source_id = ?"
            params.append(int(source_id))
        sql += " ORDER BY source_id ASC, ts ASC"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()

        latest_by_source_bucket: Dict[Tuple[int, int], Dict] = {}
        source_names: Dict[int, str] = {}
        for row in rows:
            sid = int(row["source_id"] or 0)
            bucket_ts = int(row["ts"] // safe_bucket * safe_bucket)
            key = (sid, bucket_ts)
            source_names[sid] = row["source_name"] or f"source-{sid}"
            prev = latest_by_source_bucket.get(key)
            if prev is None or int(row["ts"]) > int(prev["ts"]):
                latest_by_source_bucket[key] = dict(row)
                latest_by_source_bucket[key]["bucket_ts"] = bucket_ts

        buckets = sorted({v["bucket_ts"] for v in latest_by_source_bucket.values()})
        series: List[Dict] = []
        for sid, name in sorted(source_names.items(), key=lambda x: str(x[1]).lower()):
            points = []
            for bucket_ts in buckets:
                row = latest_by_source_bucket.get((sid, bucket_ts))
                if not row:
                    points.append(None)
                    continue
                points.append(
                    {
                        "ts": int(bucket_ts),
                        "available": bool(row["available"]),
                        "queries_total": float(row["queries_total"] or 0),
                        "blocked_total": float(row["blocked_total"] or 0),
                        "blocked_rate": float(row["blocked_rate"] or 0),
                        "cache_hit_ratio": float(row["cache_hit_ratio"] or 0),
                        "avg_latency_ms": float(row["avg_latency_ms"] or 0),
                        "upstream_errors": float(row["upstream_errors"] or 0),
                    }
                )
            series.append({"source_id": sid, "source_name": name, "points": points})

        total_queries_delta = 0.0
        total_blocked_delta = 0.0
        for src in series:
            src_points = [p for p in src["points"] if p]
            if len(src_points) >= 2:
                total_queries_delta += max(0.0, float(src_points[-1]["queries_total"]) - float(src_points[0]["queries_total"]))
                total_blocked_delta += max(0.0, float(src_points[-1]["blocked_total"]) - float(src_points[0]["blocked_total"]))

        queries_rate = total_queries_delta / float(safe_range) if safe_range > 0 else 0.0
        blocked_rate_per_sec = total_blocked_delta / float(safe_range) if safe_range > 0 else 0.0

        return {
            "ts": int(time.time()),
            "range_sec": safe_range,
            "bucket_sec": safe_bucket,
            "buckets": buckets,
            "series": series,
            "summary": {
                "queries_delta": round(total_queries_delta, 2),
                "blocked_delta": round(total_blocked_delta, 2),
                "queries_per_sec": round(queries_rate, 4),
                "blocked_per_sec": round(blocked_rate_per_sec, 4),
            },
        }

    async def collect_once(self) -> List[Dict]:
        sources = await asyncio.to_thread(self.list_enabled_sources_raw)
        if not sources:
            with self.latest_lock:
                self.latest_state["ts"] = time.time()
                self.latest_state["sources"] = []
                self.latest_state["summary"] = self.build_summary([])
            return []

        snapshots: List[Dict] = []
        for source in sources:
            snap = await asyncio.to_thread(self.adguard_monitor.collect_source, source)
            await asyncio.to_thread(self.record_snapshot, snap)
            snapshots.append(snap)

        with self.latest_lock:
            self.latest_state["ts"] = time.time()
            self.latest_state["sources"] = snapshots
            self.latest_state["summary"] = self.build_summary(snapshots)
        return snapshots

    async def collector_loop(self) -> None:
        interval = max(20, self.collect_interval_sec)
        while True:
            try:
                await self.collect_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning(f"AdGuard collector loop failed: {exc}")
            await asyncio.sleep(interval)
