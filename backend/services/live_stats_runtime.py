from __future__ import annotations

import json
import time
from threading import Lock, Thread
from typing import Dict, List, Optional

from services.db_bootstrap import connect


class LiveStatsRuntime:
    _ROLLING_SNAPSHOT_CONFIG = {
        "hour": {"bucket_seconds": 3600, "ttl_seconds": 3 * 86400, "max_search_buckets": 48},
        "day": {"bucket_seconds": 86400, "ttl_seconds": 400 * 86400, "max_search_buckets": 400},
    }

    _PERIOD_SNAPSHOT_KIND = {
        "day": ("hour", 48),
        "week": ("day", 14),
        "month": ("day", 45),
        "year": ("day", 400),
    }

    def __init__(
        self,
        *,
        client_mgr,
        db_path: Optional[str],
        traffic_stats_cache: Dict[str, tuple],
        online_clients_cache: Dict,
        cache_refresh_state: Dict,
        state_lock,
        redis_get_json,
        redis_set_json,
        redis_delete,
        traffic_stats_cache_ttl: int,
        traffic_stats_stale_ttl: int,
        online_clients_cache_ttl: int,
        online_clients_stale_ttl: int,
        logger,
    ) -> None:
        self.client_mgr = client_mgr
        self.db_path = db_path
        self.traffic_stats_cache = traffic_stats_cache
        self.online_clients_cache = online_clients_cache
        self.cache_refresh_state = cache_refresh_state
        self.state_lock = state_lock
        self.redis_get_json = redis_get_json
        self.redis_set_json = redis_set_json
        self.redis_delete = redis_delete
        self.traffic_stats_cache_ttl = traffic_stats_cache_ttl
        self.traffic_stats_stale_ttl = traffic_stats_stale_ttl
        self.online_clients_cache_ttl = online_clients_cache_ttl
        self.online_clients_stale_ttl = online_clients_stale_ttl
        self.logger = logger
        # In-memory snapshot fallback when Redis is unavailable.
        # Key: "traffic_snapshot:{group_by}:{bucket_kind}:{bucket_id}"
        # Value: {"ts": float, "stats": dict}
        self._memory_snapshots: Dict[str, dict] = {}
        self._snapshot_cleanup_ts = 0.0
        self._snapshot_seed_check_ts = 0.0
        self._traffic_cold_load_locks: Dict[str, Lock] = {}

    def _get_traffic_cold_load_lock(self, group_by: str) -> Lock:
        with self.state_lock:
            lock = self._traffic_cold_load_locks.get(group_by)
            if lock is None:
                lock = Lock()
                self._traffic_cold_load_locks[group_by] = lock
            return lock

    def invalidate(self) -> None:
        self.traffic_stats_cache.clear()
        self.online_clients_cache["ts"] = 0.0
        self.online_clients_cache["data"] = []
        self.redis_delete("traffic_stats:client", "traffic_stats:inbound", "traffic_stats:node", "online_clients")

    def start_cache_refresh(self, flag_key: str, worker, worker_key: Optional[str] = None) -> None:
        with self.state_lock:
            if flag_key == "traffic":
                if not worker_key:
                    return
                if worker_key in self.cache_refresh_state["traffic"]:
                    return
                self.cache_refresh_state["traffic"].add(worker_key)
            else:
                if self.cache_refresh_state.get(flag_key):
                    return
                self.cache_refresh_state[flag_key] = True

        def _runner():
            try:
                worker()
            except Exception as exc:
                self.logger.warning(f"Cache refresh failed ({flag_key}): {exc}")
            finally:
                with self.state_lock:
                    if flag_key == "traffic":
                        if worker_key:
                            self.cache_refresh_state["traffic"].discard(worker_key)
                    else:
                        self.cache_refresh_state[flag_key] = False

        Thread(target=_runner, daemon=True).start()

    def get_cached_traffic_stats(self, nodes: List[Dict], group_by: str) -> Dict:
        redis_key = f"traffic_stats:{group_by}"
        redis_data = self.redis_get_json(redis_key)
        if redis_data is not None:
            if isinstance(redis_data, dict):
                self._save_period_snapshots(group_by, redis_data.get("stats", {}), time.time())
            return redis_data

        now = time.time()
        cached = self.traffic_stats_cache.get(group_by)
        if cached and now - cached[0] < self.traffic_stats_cache_ttl:
            self._save_period_snapshots(group_by, cached[1].get("stats", {}), now)
            return cached[1]

        if cached and now - cached[0] < self.traffic_stats_stale_ttl:
            def _refresh():
                fresh = self.client_mgr.get_traffic_stats(nodes, group_by)
                self.traffic_stats_cache[group_by] = (time.time(), fresh)
                self.redis_set_json(redis_key, fresh, self.traffic_stats_cache_ttl)
                self._save_period_snapshots(group_by, fresh.get("stats", {}), time.time())

            self.start_cache_refresh("traffic", _refresh, worker_key=group_by)
            self._save_period_snapshots(group_by, cached[1].get("stats", {}), now)
            return cached[1]

        # A cold navigation, header summary, or realtime retry can reach this
        # point concurrently. Coalesce the remote fleet fan-out per grouping.
        with self._get_traffic_cold_load_lock(group_by):
            redis_data = self.redis_get_json(redis_key)
            if isinstance(redis_data, dict):
                self._save_period_snapshots(group_by, redis_data.get("stats", {}), time.time())
                return redis_data

            now = time.time()
            cached = self.traffic_stats_cache.get(group_by)
            if cached and now - cached[0] < self.traffic_stats_cache_ttl:
                self._save_period_snapshots(group_by, cached[1].get("stats", {}), now)
                return cached[1]

            if cached and now - cached[0] < self.traffic_stats_stale_ttl:
                def _refresh():
                    fresh = self.client_mgr.get_traffic_stats(nodes, group_by)
                    self.traffic_stats_cache[group_by] = (time.time(), fresh)
                    self.redis_set_json(redis_key, fresh, self.traffic_stats_cache_ttl)
                    self._save_period_snapshots(group_by, fresh.get("stats", {}), time.time())

                self.start_cache_refresh("traffic", _refresh, worker_key=group_by)
                self._save_period_snapshots(group_by, cached[1].get("stats", {}), now)
                return cached[1]

            data = self.client_mgr.get_traffic_stats(nodes, group_by)
            self.traffic_stats_cache[group_by] = (time.time(), data)
            self.redis_set_json(redis_key, data, self.traffic_stats_cache_ttl)
            self._save_period_snapshots(group_by, data.get("stats", {}), time.time())
            return data

    def get_cached_traffic_stats_projection(self, group_by: str) -> Dict:
        """Return an existing traffic projection without triggering a fleet fetch.

        Dashboard summary must stay on its lightweight snapshot path.  The
        normal cache API intentionally refreshes or cold-loads data; this
        read-model is for surfaces that may show the last known client traffic
        but must never make a remote XUI request just to render.
        """
        redis_key = f"traffic_stats:{group_by}"
        redis_data = self.redis_get_json(redis_key)
        if isinstance(redis_data, dict):
            return {
                "stats": redis_data.get("stats", {}),
                "group_by": group_by,
                "cache_source": "redis",
            }

        cached = self.traffic_stats_cache.get(group_by)
        if cached and isinstance(cached[1], dict):
            return {
                "stats": cached[1].get("stats", {}),
                "group_by": group_by,
                "cache_source": "memory",
                "cache_timestamp": cached[0],
            }

        if not self.db_path:
            return {"stats": {}, "group_by": group_by, "cache_source": "empty"}

        try:
            with connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT snapshot_ts, stats_json
                    FROM traffic_stats_snapshots
                    WHERE group_by = ?
                    ORDER BY snapshot_ts DESC
                    LIMIT 1
                    """,
                    (group_by,),
                ).fetchone()
            stats = json.loads(row[1]) if row and row[1] else {}
            if isinstance(stats, dict) and stats:
                return {
                    "stats": stats,
                    "group_by": group_by,
                    "cache_source": "sqlite_snapshot",
                    "cache_timestamp": row[0] if row else None,
                }
        except Exception as exc:
            self.logger.warning("Failed to load cached traffic projection (%s): %s", group_by, exc)

        return {"stats": {}, "group_by": group_by, "cache_source": "empty"}

    def get_cached_traffic_stats_projection_by_period(self, group_by: str, period: str = "all_time") -> Dict:
        """Return a period projection without refreshing or cold-loading fleet data.

        The Dashboard refreshes frequently, so its read model must use only the
        last cached client projection and persisted baselines.  In particular,
        this method must never call ``get_cached_traffic_stats`` because that
        path may start a remote XUI fan-out when the cache is cold.
        """
        period_seconds = {
            "day": 86400,
            "week": 604800,
            "month": 2592000,
            "year": 31536000,
            "all_time": 0,
        }
        if period not in period_seconds:
            period = "all_time"

        projection = self.get_cached_traffic_stats_projection(group_by)
        current_stats = projection.get("stats") if isinstance(projection, dict) else {}
        current_stats = current_stats if isinstance(current_stats, dict) else {}
        payload = {
            "stats": current_stats,
            "group_by": group_by,
            "period": period,
            "current_count": len(current_stats),
            "cache_source": projection.get("cache_source", "empty") if isinstance(projection, dict) else "empty",
        }
        if isinstance(projection, dict) and projection.get("cache_timestamp") is not None:
            payload["cache_timestamp"] = projection["cache_timestamp"]

        if period == "all_time":
            return payload

        seconds_back = period_seconds[period]
        now = time.time()
        period_start_time = now - seconds_back
        snapshot, snapshot_stats, partial_window = self._load_period_snapshot(
            group_by,
            period,
            seconds_back,
            now,
        )
        if not isinstance(snapshot_stats, dict) or not snapshot_stats:
            if group_by in {"client", "inbound"}:
                note = (
                    "No historical snapshot is available before the requested window yet. "
                    "Older client/inbound history cannot be reconstructed from the current SQLite schema."
                )
            else:
                note = "No historical snapshot is available before the requested window yet."
            return {
                **payload,
                "stats": {},
                "period_start": period_start_time,
                "period_seconds": seconds_back,
                "note": note,
            }

        def metric(value) -> int:
            try:
                return max(0, int(float(value or 0)))
            except (TypeError, ValueError, OverflowError):
                return 0

        delta_stats: Dict[str, Dict[str, int]] = {}
        for key, current_value in current_stats.items():
            if not isinstance(current_value, dict):
                continue
            snapshot_value = snapshot_stats.get(key, {})
            snapshot_value = snapshot_value if isinstance(snapshot_value, dict) else {}
            current_up = metric(current_value.get("up", current_value.get("upload", 0)))
            current_down = metric(current_value.get("down", current_value.get("download", 0)))
            current_total = metric(current_value.get("total")) or current_up + current_down
            snapshot_up = metric(snapshot_value.get("up", snapshot_value.get("upload", 0)))
            snapshot_down = metric(snapshot_value.get("down", snapshot_value.get("download", 0)))
            snapshot_total = metric(snapshot_value.get("total")) or snapshot_up + snapshot_down
            delta_stats[str(key)] = {
                "up": max(0, current_up - snapshot_up),
                "down": max(0, current_down - snapshot_down),
                "total": max(0, current_total - snapshot_total),
                "count": metric(current_value.get("count", 1)) or 1,
            }

        result = {
            **payload,
            "stats": delta_stats,
            "period_start": period_start_time,
            "period_seconds": seconds_back,
            "snapshot_ts": snapshot.get("ts") if isinstance(snapshot, dict) else None,
        }
        if partial_window:
            result["note"] = (
                "Historical data covers only part of the requested window. "
                "Showing the earliest retained snapshot within that window."
            )
        return result

    def _snapshot_key(self, group_by: str, bucket_kind: str, bucket_id: int) -> str:
        return f"traffic_snapshot:{group_by}:{bucket_kind}:{bucket_id}"

    def _read_snapshot(self, key: str) -> Optional[dict]:
        snapshot = self.redis_get_json(key)
        if isinstance(snapshot, dict):
            return snapshot
        memory_snapshot = self._memory_snapshots.get(key)
        return memory_snapshot if isinstance(memory_snapshot, dict) else None

    def _write_snapshot(self, key: str, snapshot_value: dict, ttl_seconds: int) -> None:
        existing = self._read_snapshot(key)
        if existing is not None:
            return
        self.redis_set_json(key, snapshot_value, ttl_seconds)
        self._memory_snapshots[key] = snapshot_value

    def _persist_snapshot_to_db(
        self,
        group_by: str,
        bucket_kind: str,
        bucket_start: int,
        snapshot_value: dict,
    ) -> None:
        if not self.db_path:
            return

        try:
            snapshot_ts = int(float(snapshot_value.get("ts") or 0))
            stats_json = json.dumps(snapshot_value.get("stats", {}), separators=(",", ":"))
            with connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO traffic_stats_snapshots (
                        group_by, bucket_kind, bucket_start, snapshot_ts, stats_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (group_by, bucket_kind, bucket_start, snapshot_ts, stats_json),
                )

                if snapshot_ts - self._snapshot_cleanup_ts >= 3600:
                    self._snapshot_cleanup_ts = float(snapshot_ts)
                    conn.execute(
                        """
                        DELETE FROM traffic_stats_snapshots
                        WHERE (bucket_kind = 'hour' AND snapshot_ts < ?)
                           OR (bucket_kind = 'day' AND snapshot_ts < ?)
                        """,
                        (
                            snapshot_ts - self._ROLLING_SNAPSHOT_CONFIG["hour"]["ttl_seconds"],
                            snapshot_ts - self._ROLLING_SNAPSHOT_CONFIG["day"]["ttl_seconds"],
                        ),
                    )
                conn.commit()
        except Exception as exc:
            self.logger.warning(
                "Failed to persist traffic snapshot (%s/%s): %s",
                group_by,
                bucket_kind,
                exc,
            )

    def _load_snapshot_from_db(
        self,
        group_by: str,
        bucket_kind: str,
        target_ts: float,
    ) -> Optional[dict]:
        if not self.db_path:
            return None

        try:
            with connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT snapshot_ts, stats_json
                    FROM traffic_stats_snapshots
                    WHERE group_by = ?
                      AND bucket_kind = ?
                      AND snapshot_ts <= ?
                    ORDER BY snapshot_ts DESC
                    LIMIT 1
                    """,
                    (group_by, bucket_kind, int(target_ts)),
                ).fetchone()
            if not row:
                return None

            stats = json.loads(row[1]) if row[1] else {}
            if not isinstance(stats, dict) or not stats:
                return None
            return {"ts": float(row[0]), "stats": stats}
        except Exception as exc:
            self.logger.warning(
                "Failed to load traffic snapshot from DB (%s/%s): %s",
                group_by,
                bucket_kind,
                exc,
            )
            return None

    def _load_snapshot_after_from_db(
        self,
        group_by: str,
        bucket_kind: str,
        target_ts: float,
        max_bucket_id: int,
    ) -> Optional[dict]:
        if not self.db_path:
            return None

        try:
            with connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT snapshot_ts, stats_json
                    FROM traffic_stats_snapshots
                    WHERE group_by = ?
                      AND bucket_kind = ?
                      AND snapshot_ts >= ?
                      AND bucket_start <= ?
                    ORDER BY snapshot_ts ASC
                    LIMIT 1
                    """,
                    (group_by, bucket_kind, int(target_ts), int(max_bucket_id)),
                ).fetchone()
            if not row:
                return None

            stats = json.loads(row[1]) if row[1] else {}
            if not isinstance(stats, dict) or not stats:
                return None
            return {"ts": float(row[0]), "stats": stats}
        except Exception as exc:
            self.logger.warning(
                "Failed to load traffic snapshot after window start from DB (%s/%s): %s",
                group_by,
                bucket_kind,
                exc,
            )
            return None

    def _bucket_exists_in_db(self, group_by: str, bucket_kind: str, bucket_id: int) -> bool:
        if not self.db_path:
            return False

        try:
            with connect(self.db_path) as conn:
                row = conn.execute(
                    """
                    SELECT 1
                    FROM traffic_stats_snapshots
                    WHERE group_by = ?
                      AND bucket_kind = ?
                      AND bucket_start = ?
                    LIMIT 1
                    """,
                    (group_by, bucket_kind, int(bucket_id)),
                ).fetchone()
            return row is not None
        except Exception as exc:
            self.logger.warning(
                "Failed to check traffic snapshot bucket existence (%s/%s/%s): %s",
                group_by,
                bucket_kind,
                bucket_id,
                exc,
            )
            return False

    def _has_bucket_snapshot(self, group_by: str, bucket_kind: str, bucket_id: int) -> bool:
        if isinstance(self._read_snapshot(self._snapshot_key(group_by, bucket_kind, bucket_id)), dict):
            return True
        return self._bucket_exists_in_db(group_by, bucket_kind, bucket_id)

    def _save_period_snapshots(self, group_by: str, stats_data: Dict, now_ts: float) -> None:
        """Persist rolling snapshots used for period deltas."""
        if not isinstance(stats_data, dict):
            return

        snapshot_value = {"ts": now_ts, "stats": stats_data}
        for bucket_kind, config in self._ROLLING_SNAPSHOT_CONFIG.items():
            bucket_seconds = int(config["bucket_seconds"])
            bucket_id = int(now_ts / bucket_seconds)
            redis_key = self._snapshot_key(group_by, bucket_kind, bucket_id)
            self._write_snapshot(redis_key, snapshot_value, int(config["ttl_seconds"]))
            self._persist_snapshot_to_db(group_by, bucket_kind, bucket_id, snapshot_value)

    def ensure_current_period_snapshots(
        self,
        nodes: List[Dict],
        group_bys: Optional[List[str]] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, bool]:
        """Ensure current hour/day buckets are seeded even when Traffic Stats UI is unopened."""
        now = float(now_ts or time.time())
        if now - self._snapshot_seed_check_ts < 5.0:
            return {}
        self._snapshot_seed_check_ts = now

        targets = group_bys or ["client", "inbound", "node"]
        seeded: Dict[str, bool] = {}
        for group_by in targets:
            missing_bucket = False
            for bucket_kind, config in self._ROLLING_SNAPSHOT_CONFIG.items():
                bucket_id = int(now / int(config["bucket_seconds"]))
                if not self._has_bucket_snapshot(group_by, bucket_kind, bucket_id):
                    missing_bucket = True
                    break
            if not missing_bucket:
                continue

            self.get_cached_traffic_stats(nodes, group_by)
            seeded[group_by] = True

        return seeded

    def backfill_node_history_snapshots(self, now_ts: Optional[float] = None) -> Dict[str, int]:
        """Backfill node-group period snapshots from persisted node_history rows."""
        if not self.db_path:
            return {"hour": 0, "day": 0}

        now = float(now_ts or time.time())
        summary = {"hour": 0, "day": 0}

        try:
            with connect(self.db_path) as conn:
                for bucket_kind in ("hour", "day"):
                    config = self._ROLLING_SNAPSHOT_CONFIG[bucket_kind]
                    bucket_seconds = int(config["bucket_seconds"])
                    cutoff_ts = max(0, int(now - int(config["ttl_seconds"])))

                    existing_bucket_ids = {
                        int(row[0])
                        for row in conn.execute(
                            """
                            SELECT bucket_start
                            FROM traffic_stats_snapshots
                            WHERE group_by = 'node'
                              AND bucket_kind = ?
                            """,
                            (bucket_kind,),
                        ).fetchall()
                    }

                    first_rows_by_bucket_node = set()
                    bucket_payloads: Dict[int, Dict] = {}
                    for ts, node_id, node_name, traffic_total in conn.execute(
                        """
                        SELECT ts, node_id, node_name, traffic_total
                        FROM node_history
                        WHERE ts >= ?
                        ORDER BY ts ASC, node_id ASC
                        """,
                        (cutoff_ts,),
                    ):
                        bucket_id = int(int(ts) / bucket_seconds)
                        if bucket_id in existing_bucket_ids:
                            continue

                        pair = (bucket_id, int(node_id))
                        if pair in first_rows_by_bucket_node:
                            continue
                        first_rows_by_bucket_node.add(pair)

                        payload = bucket_payloads.setdefault(
                            bucket_id,
                            {"snapshot_ts": 0, "stats": {}},
                        )
                        payload["snapshot_ts"] = max(int(payload["snapshot_ts"]), int(ts))

                        node_key = str(node_name or f"node-{node_id}")
                        total = int(float(traffic_total or 0))
                        payload["stats"][node_key] = {
                            "up": 0,
                            "down": total,
                            "total": total,
                            "count": 1,
                        }

                    inserted = 0
                    for bucket_id, payload in sorted(bucket_payloads.items()):
                        if not payload["stats"]:
                            continue
                        result = conn.execute(
                            """
                            INSERT OR IGNORE INTO traffic_stats_snapshots (
                                group_by, bucket_kind, bucket_start, snapshot_ts, stats_json
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                "node",
                                bucket_kind,
                                int(bucket_id),
                                int(payload["snapshot_ts"]),
                                json.dumps(payload["stats"], separators=(",", ":")),
                            ),
                        )
                        if result.rowcount:
                            inserted += 1

                    summary[bucket_kind] = inserted

                conn.commit()
        except Exception as exc:
            self.logger.warning("Failed to backfill node traffic snapshots: %s", exc)
            return summary

        if summary["hour"] or summary["day"]:
            self.logger.info(
                "Backfilled node traffic snapshots from node_history: hour=%s day=%s",
                summary["hour"],
                summary["day"],
            )
        return summary

    def _find_snapshot_before(
        self,
        group_by: str,
        bucket_kind: str,
        target_ts: float,
        max_search_buckets: int,
    ):
        config = self._ROLLING_SNAPSHOT_CONFIG.get(bucket_kind)
        if not config:
            return None, None

        bucket_seconds = int(config["bucket_seconds"])
        start_bucket = int(target_ts / bucket_seconds)

        for offset in range(max(0, max_search_buckets) + 1):
            bucket_id = start_bucket - offset
            snapshot = self._read_snapshot(self._snapshot_key(group_by, bucket_kind, bucket_id))
            if not isinstance(snapshot, dict):
                continue

            snapshot_ts = float(snapshot.get("ts") or 0)
            if snapshot_ts <= 0 or snapshot_ts > target_ts:
                continue

            snapshot_stats = snapshot.get("stats", {})
            if isinstance(snapshot_stats, dict) and snapshot_stats:
                return snapshot, snapshot_stats

        snapshot = self._load_snapshot_from_db(group_by, bucket_kind, target_ts)
        if isinstance(snapshot, dict):
            snapshot_stats = snapshot.get("stats", {})
            if isinstance(snapshot_stats, dict) and snapshot_stats:
                return snapshot, snapshot_stats

        return None, None

    def _find_snapshot_after(
        self,
        group_by: str,
        bucket_kind: str,
        target_ts: float,
        now_ts: float,
        max_search_buckets: int,
    ):
        config = self._ROLLING_SNAPSHOT_CONFIG.get(bucket_kind)
        if not config:
            return None, None

        bucket_seconds = int(config["bucket_seconds"])
        start_bucket = int(target_ts / bucket_seconds)
        end_bucket = int(now_ts / bucket_seconds) - 1
        if end_bucket < start_bucket:
            return None, None

        for offset in range(max(0, max_search_buckets) + 1):
            bucket_id = start_bucket + offset
            if bucket_id > end_bucket:
                break

            snapshot = self._read_snapshot(self._snapshot_key(group_by, bucket_kind, bucket_id))
            if not isinstance(snapshot, dict):
                continue

            snapshot_ts = float(snapshot.get("ts") or 0)
            if snapshot_ts < target_ts or snapshot_ts > now_ts:
                continue

            snapshot_stats = snapshot.get("stats", {})
            if isinstance(snapshot_stats, dict) and snapshot_stats:
                return snapshot, snapshot_stats

        snapshot = self._load_snapshot_after_from_db(group_by, bucket_kind, target_ts, end_bucket)
        if isinstance(snapshot, dict):
            snapshot_ts = float(snapshot.get("ts") or 0)
            if snapshot_ts <= now_ts:
                snapshot_stats = snapshot.get("stats", {})
                if isinstance(snapshot_stats, dict) and snapshot_stats:
                    return snapshot, snapshot_stats

        return None, None

    def _load_period_snapshot(self, group_by: str, period: str, seconds_back: int, now_ts: float):
        """Load the best available snapshot around the requested period start."""
        target_ts = now_ts - seconds_back
        bucket_kind, max_search_buckets = self._PERIOD_SNAPSHOT_KIND.get(period, ("day", 14))
        snapshot, snapshot_stats = self._find_snapshot_before(
            group_by,
            bucket_kind,
            target_ts,
            max_search_buckets,
        )
        if snapshot_stats:
            return snapshot, snapshot_stats, False

        snapshot, snapshot_stats = self._find_snapshot_after(
            group_by,
            bucket_kind,
            target_ts,
            now_ts,
            max_search_buckets,
        )
        if snapshot_stats:
            return snapshot, snapshot_stats, True

        return None, None, False

    def get_cached_online_clients(self, nodes: List[Dict]) -> List[Dict]:
        redis_data = self.redis_get_json("online_clients")
        if isinstance(redis_data, list):
            return redis_data

        now = time.time()
        if now - self.online_clients_cache["ts"] < self.online_clients_cache_ttl:
            return self.online_clients_cache["data"]

        if self.online_clients_cache["data"] and now - self.online_clients_cache["ts"] < self.online_clients_stale_ttl:
            def _refresh():
                fresh = self.client_mgr.get_online_clients(nodes)
                self.online_clients_cache["ts"] = time.time()
                self.online_clients_cache["data"] = fresh
                self.redis_set_json("online_clients", fresh, self.online_clients_cache_ttl)

            self.start_cache_refresh("online_clients", _refresh)
            return self.online_clients_cache["data"]

        data = self.client_mgr.get_online_clients(nodes)
        self.online_clients_cache["ts"] = now
        self.online_clients_cache["data"] = data
        self.redis_set_json("online_clients", data, self.online_clients_cache_ttl)
        return data

    def get_traffic_stats_by_period(
        self, nodes: List[Dict], group_by: str, period: str = "all_time"
    ) -> Dict:
        """
        Get traffic stats for a specific period by comparing snapshots.
        
        Args:
            nodes: List of nodes
            group_by: Grouping ('client', 'inbound', 'node')
            period: 'day', 'week', 'month', 'year', or 'all_time'
        
        Returns:
            Traffic statistics for the specified period
        """
        # Period to seconds mapping
        period_seconds = {
            "day": 86400,        # 24 hours
            "week": 604800,      # 7 days
            "month": 2592000,    # 30 days
            "year": 31536000,    # 365 days
            "all_time": 0,       # Special: return current total
        }
        
        if period not in period_seconds:
            period = "all_time"
        
        # Get current stats
        current_stats = self.get_cached_traffic_stats(nodes, group_by)
        current_data = current_stats.get("stats", {})
        
        if period == "all_time":
            # Return current totals as all-time
            return current_stats
        
        seconds_back = period_seconds[period]
        now = time.time()
        period_start_time = now - seconds_back
        snapshot, snapshot_stats, partial_window = self._load_period_snapshot(group_by, period, seconds_back, now)
        
        if not snapshot_stats or not isinstance(snapshot_stats, dict):
            if group_by in {"client", "inbound"}:
                note = (
                    "No historical snapshot is available before the requested window yet. "
                    "Older client/inbound history cannot be reconstructed from the current SQLite schema."
                )
            else:
                note = "No historical snapshot is available before the requested window yet."
            return {
                "stats": {},
                "group_by": group_by,
                "period": period,
                "period_start": period_start_time,
                "note": note,
            }

        # Calculate delta between current and period snapshot
        delta_stats: Dict[str, Dict[str, int]] = {}
        for key, current_val in current_data.items():
            snapshot_val = snapshot_stats.get(key, {"up": 0, "down": 0, "total": 0})
            delta_stats[key] = {
                "up": max(0, current_val.get("up", 0) - snapshot_val.get("up", 0)),
                "down": max(0, current_val.get("down", 0) - snapshot_val.get("down", 0)),
                "total": max(0, current_val.get("total", 0) - snapshot_val.get("total", 0)),
                "count": current_val.get("count", 1)
            }
        
        return {
            "stats": delta_stats,
            "group_by": group_by,
            "period": period,
            "period_start": period_start_time,
            "period_seconds": seconds_back,
            "snapshot_ts": snapshot.get("ts") if isinstance(snapshot, dict) else None,
            **(
                {
                    "note": (
                        "Historical data covers only part of the requested window. "
                        "Showing the earliest retained snapshot within that window."
                    )
                }
                if partial_window
                else {}
            ),
        }

    def save_traffic_snapshot(self, nodes: List[Dict], group_by: str) -> None:
        """
        Save current traffic stats as a snapshot for period-based calculations.
        Called periodically (e.g., hourly) to enable period tracking.
        
        Args:
            nodes: List of nodes
            group_by: Grouping ('client', 'inbound', 'node')
        """
        current_stats = self.get_cached_traffic_stats(nodes, group_by)
        current_data = current_stats.get("stats", {})
        self._save_period_snapshots(group_by, current_data, time.time())
