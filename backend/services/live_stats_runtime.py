from __future__ import annotations

import json
import time
from threading import Lock, Thread
from typing import Callable, Dict, List, Optional

from services.db_bootstrap import connect


class LiveStatsRuntime:
    # Redis and SQLite keep the long period history. The process-local fallback
    # must remain a small hot set instead of retaining every full fleet snapshot.
    _MEMORY_SNAPSHOT_MAX_ENTRIES = 96
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
        get_latest_snapshot: Optional[Callable[[], Dict]] = None,
        get_expected_snapshot_nodes: Optional[Callable[[], int]] = None,
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
        self.get_latest_snapshot = get_latest_snapshot
        self.get_expected_snapshot_nodes = get_expected_snapshot_nodes
        # In-memory snapshot fallback when Redis is unavailable.
        # Key: "traffic_snapshot:{group_by}:{bucket_kind}:{bucket_id}"
        # Value: (monotonic expiry timestamp, {"ts": float, "stats": dict})
        self._memory_snapshots: Dict[str, tuple[float, dict]] = {}
        self._memory_snapshots_lock = Lock()
        self._memory_snapshot_max_entries = self._MEMORY_SNAPSHOT_MAX_ENTRIES
        self._snapshot_cleanup_ts = 0.0
        self._snapshot_seed_check_ts = 0.0
        self._snapshot_seed_lock = Lock()
        self._traffic_cold_load_locks: Dict[str, Lock] = {}
        self._cache_state_lock = Lock()
        self._cache_generation = 0
        self._snapshot_projection_lock = Lock()
        self._snapshot_projection_timestamp: Optional[float] = None
        self._snapshot_projections: Dict[str, Dict] = {}

    @staticmethod
    def _metric(value) -> int:
        try:
            return max(0, int(float(value or 0)))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _snapshot_system_client_emails(snapshot: Dict) -> list[str]:
        nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else None
        if not isinstance(nodes, list):
            return []
        return sorted({
            str(email).strip().casefold()
            for node in nodes
            if isinstance(node, dict)
            for email in node.get("system_client_emails") or []
            if isinstance(email, str) and email.strip()
        })

    @staticmethod
    def _stable_node_key(node_id, fallback_key: str) -> str:
        """Return a rename-safe identity for node period snapshots."""
        node_id = str(node_id).strip() if node_id is not None else ""
        return f"node:{node_id}" if node_id else fallback_key

    @classmethod
    def _stable_inbound_key(cls, node_id, inbound_id, fallback_key: str) -> str:
        """Return a node-scoped identity for inbound period snapshots."""
        node_key = cls._stable_node_key(node_id, "")
        inbound_id = str(inbound_id).strip() if inbound_id is not None else ""
        return f"{node_key}:inbound:{inbound_id}" if node_key and inbound_id else fallback_key

    @staticmethod
    def _public_stats_from_identity(identity_stats: Dict) -> Dict:
        """Rebuild readable keys when the only warm source is an ID snapshot."""
        public_stats: Dict[str, Dict] = {}
        for identity, value in identity_stats.items():
            if not isinstance(value, dict):
                continue
            display_key = str(value.get("_display_key") or identity)
            public_stats[display_key] = {
                "up": value.get("up", 0),
                "down": value.get("down", 0),
                "total": value.get("total", 0),
                "count": value.get("count", 1),
            }
        return public_stats

    def _build_snapshot_traffic_projections(
        self, snapshot: Optional[Dict] = None
    ) -> tuple[Optional[float], Dict[str, Dict]]:
        """Build all Statistics groupings from the collector's existing data.

        The collector already obtains inbounds once per poll.  Re-reading it
        here is strictly local work; this method must never call a panel or
        ``ClientManager``.  Keeping all groupings in one projection prevents a
        client -> inbound -> node switch from multiplying fleet work.
        """
        if snapshot is None:
            if not self.get_latest_snapshot:
                return None, {}
            snapshot = self.get_latest_snapshot()
        if not isinstance(snapshot, dict):
            return None, {}
        timestamp = snapshot.get("timestamp")
        try:
            timestamp = float(timestamp) if timestamp is not None else None
        except (TypeError, ValueError):
            timestamp = None
        nodes = snapshot.get("nodes")
        if timestamp is None or not isinstance(nodes, list):
            return timestamp, {}

        projections: Dict[str, Dict] = {
            "client": {"stats": {}},
            "inbound": {"stats": {}, "identity_stats": {}},
            "node": {"stats": {}, "identity_stats": {}},
        }

        def add(
            group_by: str,
            key: str,
            up: int,
            down: int,
            count: int = 1,
            *,
            identity: Optional[str] = None,
            legacy_key: Optional[str] = None,
        ) -> None:
            if not key:
                return
            current = projections[group_by]["stats"].setdefault(
                key, {"up": 0, "down": 0, "total": 0, "count": 0}
            )
            current["up"] += up
            current["down"] += down
            current["total"] += up + down
            current["count"] += count

            if identity:
                identity_current = projections[group_by]["identity_stats"].setdefault(
                    identity,
                    {
                        "up": 0,
                        "down": 0,
                        "total": 0,
                        "count": 0,
                        "_display_key": key,
                        "_legacy_key": legacy_key or key,
                    },
                )
                identity_current["up"] += up
                identity_current["down"] += down
                identity_current["total"] += up + down
                identity_current["count"] += count

        node_name_counts: Dict[str, int] = {}
        for node in nodes:
            if isinstance(node, dict):
                node_name = str(node.get("name") or node.get("node_id") or "")
                if node_name:
                    node_name_counts[node_name] = node_name_counts.get(node_name, 0) + 1

        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_name = str(node.get("name") or node.get("node_id") or "")
            node_id = str(node.get("node_id") or node.get("id") or "").strip()
            inbounds = node.get("inbounds")
            if not node_name or not isinstance(inbounds, list):
                continue
            node_key = node_name if node_name_counts.get(node_name, 0) == 1 else f"{node_name} #{node_id or 'unknown'}"
            node_identity = self._stable_node_key(node_id, node_key)

            for inbound in inbounds:
                if not isinstance(inbound, dict):
                    continue
                inbound_up = self._metric(inbound.get("up"))
                inbound_down = self._metric(inbound.get("down"))
                inbound_name = str(inbound.get("remark", inbound.get("id", "unknown")))
                inbound_key = f"{node_key}:{inbound_name}"
                inbound_identity = self._stable_inbound_key(node_id, inbound.get("id"), inbound_key)
                # Node and inbound totals are available even when an older
                # panel omits ``clientStats``.  Client-level rows stay absent
                # instead of causing the old per-client remote fallback.
                add("node", node_key, inbound_up, inbound_down, identity=node_identity, legacy_key=node_name)
                add(
                    "inbound",
                    inbound_key,
                    inbound_up,
                    inbound_down,
                    identity=inbound_identity,
                    legacy_key=f"{node_name}:{inbound_name}",
                )

                client_stats = inbound.get("clientStats")
                if not isinstance(client_stats, list):
                    continue
                for client in client_stats:
                    if not isinstance(client, dict):
                        continue
                    email = str(client.get("email") or "")
                    add("client", email, self._metric(client.get("up")), self._metric(client.get("down")))

        return timestamp, projections

    def _snapshot_projection(self, group_by: str) -> Optional[Dict]:
        """Return a memoized collector projection, or ``None`` while warming."""
        if group_by not in {"client", "inbound", "node"} or not self.get_latest_snapshot:
            return None
        snapshot = self.get_latest_snapshot()
        if not isinstance(snapshot, dict):
            return None
        try:
            timestamp = float(snapshot.get("timestamp"))
        except (TypeError, ValueError):
            return None
        system_client_emails = self._snapshot_system_client_emails(snapshot)

        with self._snapshot_projection_lock:
            if timestamp == self._snapshot_projection_timestamp:
                projection = self._snapshot_projections.get(group_by, {})
                return {
                    "stats": projection.get("stats", {}),
                    "group_by": group_by,
                    "cache_source": "snapshot_collector",
                    "cache_timestamp": timestamp,
                    "system_client_emails": system_client_emails,
                    **({"identity_stats": projection["identity_stats"]} if isinstance(projection.get("identity_stats"), dict) else {}),
                }

        _timestamp, projections = self._build_snapshot_traffic_projections(snapshot)
        with self._snapshot_projection_lock:
            # A concurrently completed request may already have indexed the
            # same collector revision; preserve that reusable projection.
            if self._snapshot_projection_timestamp is None or timestamp > self._snapshot_projection_timestamp:
                self._snapshot_projection_timestamp = timestamp
                self._snapshot_projections = projections
            projection = self._snapshot_projections.get(group_by, {})
            return {
                "stats": projection.get("stats", {}),
                "group_by": group_by,
                "cache_source": "snapshot_collector",
                "cache_timestamp": timestamp,
                "system_client_emails": system_client_emails,
                **({"identity_stats": projection["identity_stats"]} if isinstance(projection.get("identity_stats"), dict) else {}),
            }

    def seed_period_snapshots_from_collector(self, now_ts: Optional[float] = None) -> Dict[str, bool]:
        """Persist current period baselines from collector data, never a fleet read."""
        # Every completed node poll invokes this method.  Without a
        # single-flight guard, several callbacks can cross the timestamp check
        # together and each rebuild all fleet projections plus SQLite snapshots.
        if not self._snapshot_seed_lock.acquire(blocking=False):
            return {}
        try:
            now = float(now_ts or time.time())
            if now - self._snapshot_seed_check_ts < 5.0:
                return {}

            if self.get_expected_snapshot_nodes and self.get_latest_snapshot:
                snapshot = self.get_latest_snapshot()
                nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else []
                try:
                    expected_nodes = max(0, int(self.get_expected_snapshot_nodes()))
                except (TypeError, ValueError):
                    expected_nodes = 0
                # Do not establish a day/week/month baseline from only the first
                # few nodes during a cold collector start.  This is a local SQLite
                # count check, never a panel request.
                if expected_nodes and (not isinstance(nodes, list) or len(nodes) < expected_nodes):
                    return {"warming": False}

            self._snapshot_seed_check_ts = now

            seeded: Dict[str, bool] = {}
            for group_by in ("client", "inbound", "node"):
                projection = self._snapshot_projection(group_by)
                if not projection:
                    continue
                self._save_period_snapshots(
                    group_by,
                    projection.get("stats", {}),
                    now,
                    projection.get("identity_stats"),
                )
                seeded[group_by] = True
            return seeded
        finally:
            self._snapshot_seed_lock.release()

    def _get_traffic_cold_load_lock(self, group_by: str) -> Lock:
        with self.state_lock:
            lock = self._traffic_cold_load_locks.get(group_by)
            if lock is None:
                lock = Lock()
                self._traffic_cold_load_locks[group_by] = lock
            return lock

    def invalidate(self) -> None:
        with self._cache_state_lock:
            self._cache_generation += 1
            self.traffic_stats_cache.clear()
            self.online_clients_cache["ts"] = 0.0
            self.online_clients_cache["data"] = []
        self.redis_delete("traffic_stats:client", "traffic_stats:inbound", "traffic_stats:node", "online_clients")

    def _cache_generation_snapshot(self) -> int:
        with self._cache_state_lock:
            return self._cache_generation

    def _store_traffic_cache(self, group_by: str, data: Dict, generation: int) -> bool:
        """Publish only data that was fetched after the last invalidation."""
        with self._cache_state_lock:
            if generation != self._cache_generation:
                return False
            self.traffic_stats_cache[group_by] = (time.time(), data)
            self.redis_set_json(f"traffic_stats:{group_by}", data, self.traffic_stats_cache_ttl)
            self._save_period_snapshots(group_by, data.get("stats", {}), time.time(), data.get("identity_stats"))
            return True

    def _store_online_clients(self, data: List[Dict], generation: int) -> bool:
        """Publish only data that was fetched after the last invalidation."""
        with self._cache_state_lock:
            if generation != self._cache_generation:
                return False
            self.online_clients_cache["ts"] = time.time()
            self.online_clients_cache["data"] = data
            self.redis_set_json("online_clients", data, self.online_clients_cache_ttl)
            return True

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
                self._save_period_snapshots(group_by, redis_data.get("stats", {}), time.time(), redis_data.get("identity_stats"))
            return redis_data

        now = time.time()
        cached = self.traffic_stats_cache.get(group_by)
        if cached and now - cached[0] < self.traffic_stats_cache_ttl:
            self._save_period_snapshots(group_by, cached[1].get("stats", {}), now, cached[1].get("identity_stats"))
            return cached[1]

        if cached and now - cached[0] < self.traffic_stats_stale_ttl:
            generation = self._cache_generation_snapshot()
            def _refresh():
                fresh = self.client_mgr.get_traffic_stats(nodes, group_by)
                self._store_traffic_cache(group_by, fresh, generation)

            self.start_cache_refresh("traffic", _refresh, worker_key=group_by)
            self._save_period_snapshots(group_by, cached[1].get("stats", {}), now, cached[1].get("identity_stats"))
            return cached[1]

        # A cold navigation, header summary, or realtime retry can reach this
        # point concurrently. Coalesce the remote fleet fan-out per grouping.
        with self._get_traffic_cold_load_lock(group_by):
            redis_data = self.redis_get_json(redis_key)
            if isinstance(redis_data, dict):
                self._save_period_snapshots(group_by, redis_data.get("stats", {}), time.time(), redis_data.get("identity_stats"))
                return redis_data

            now = time.time()
            cached = self.traffic_stats_cache.get(group_by)
            if cached and now - cached[0] < self.traffic_stats_cache_ttl:
                self._save_period_snapshots(group_by, cached[1].get("stats", {}), now, cached[1].get("identity_stats"))
                return cached[1]

            if cached and now - cached[0] < self.traffic_stats_stale_ttl:
                generation = self._cache_generation_snapshot()
                def _refresh():
                    fresh = self.client_mgr.get_traffic_stats(nodes, group_by)
                    self._store_traffic_cache(group_by, fresh, generation)

                self.start_cache_refresh("traffic", _refresh, worker_key=group_by)
                self._save_period_snapshots(group_by, cached[1].get("stats", {}), now, cached[1].get("identity_stats"))
                return cached[1]

            generation = self._cache_generation_snapshot()
            data = self.client_mgr.get_traffic_stats(nodes, group_by)
            self._store_traffic_cache(group_by, data, generation)
            return data

    def get_cached_traffic_stats_projection(self, group_by: str) -> Dict:
        """Return an existing traffic projection without triggering a fleet fetch.

        Dashboard summary must stay on its lightweight snapshot path.  The
        normal cache API intentionally refreshes or cold-loads data; this
        read-model is for surfaces that may show the last known client traffic
        but must never make a remote XUI request just to render.
        """
        snapshot_projection = self._snapshot_projection(group_by)
        if snapshot_projection is not None:
            return snapshot_projection

        redis_key = f"traffic_stats:{group_by}"
        redis_data = self.redis_get_json(redis_key)
        if isinstance(redis_data, dict):
            return {
                "stats": redis_data.get("stats", {}),
                "group_by": group_by,
                "cache_source": "redis",
                **({"identity_stats": redis_data["identity_stats"]} if isinstance(redis_data.get("identity_stats"), dict) else {}),
            }

        cached = self.traffic_stats_cache.get(group_by)
        if cached and isinstance(cached[1], dict):
            return {
                "stats": cached[1].get("stats", {}),
                "group_by": group_by,
                "cache_source": "memory",
                "cache_timestamp": cached[0],
                **({"identity_stats": cached[1]["identity_stats"]} if isinstance(cached[1].get("identity_stats"), dict) else {}),
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
                identity_stats = (
                    stats
                    if group_by in {"node", "inbound"}
                    and any(isinstance(value, dict) and value.get("_display_key") for value in stats.values())
                    else None
                )
                return {
                    "stats": self._public_stats_from_identity(identity_stats) if identity_stats else stats,
                    "group_by": group_by,
                    "cache_source": "sqlite_snapshot",
                    "cache_timestamp": row[0] if row else None,
                    **({"identity_stats": identity_stats} if identity_stats else {}),
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
        if isinstance(projection, dict) and isinstance(projection.get("system_client_emails"), list):
            payload["system_client_emails"] = projection["system_client_emails"]
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

        identity_stats = projection.get("identity_stats") if isinstance(projection, dict) else None
        use_identity_stats = group_by in {"node", "inbound"} and isinstance(identity_stats, dict)
        comparison_stats = identity_stats if use_identity_stats else current_stats
        delta_stats: Dict[str, Dict[str, int]] = {}
        missing_baseline_count = 0
        for key, current_value in comparison_stats.items():
            if not isinstance(current_value, dict):
                continue
            snapshot_value = snapshot_stats.get(key)
            if not isinstance(snapshot_value, dict) and use_identity_stats:
                legacy_key = str(current_value.get("_legacy_key") or "")
                matches = [
                    item for item in comparison_stats.values()
                    if isinstance(item, dict) and item.get("_legacy_key") == legacy_key
                ]
                candidate = snapshot_stats.get(legacy_key) if len(matches) == 1 and legacy_key else None
                snapshot_value = candidate if isinstance(candidate, dict) else None
            if snapshot_value is None:
                if use_identity_stats and str(key).startswith("node:"):
                    missing_baseline_count += 1
                    continue
                snapshot_value = {}
            current_up = metric(current_value.get("up", current_value.get("upload", 0)))
            current_down = metric(current_value.get("down", current_value.get("download", 0)))
            current_total = metric(current_value.get("total")) or current_up + current_down
            snapshot_up = metric(snapshot_value.get("up", snapshot_value.get("upload", 0)))
            snapshot_down = metric(snapshot_value.get("down", snapshot_value.get("download", 0)))
            snapshot_total = metric(snapshot_value.get("total")) or snapshot_up + snapshot_down
            display_key = str(current_value.get("_display_key") or key) if use_identity_stats else str(key)
            delta_stats[display_key] = {
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
        if missing_baseline_count:
            note = "Some node rows have no unambiguous historical baseline yet and are omitted."
            result["note"] = f"{result.get('note')} {note}".strip()
            result["missing_baseline_count"] = missing_baseline_count
        return result

    def _snapshot_key(self, group_by: str, bucket_kind: str, bucket_id: int) -> str:
        return f"traffic_snapshot:{group_by}:{bucket_kind}:{bucket_id}"

    def _prune_memory_snapshots_locked(self, now: float) -> None:
        expired_keys = [
            key for key, (expires_at, _snapshot) in self._memory_snapshots.items()
            if expires_at <= now
        ]
        for key in expired_keys:
            self._memory_snapshots.pop(key, None)

        overflow = len(self._memory_snapshots) - self._memory_snapshot_max_entries
        if overflow <= 0:
            return
        oldest_keys = sorted(
            self._memory_snapshots,
            key=lambda key: self._memory_snapshots[key][0],
        )[:overflow]
        for key in oldest_keys:
            self._memory_snapshots.pop(key, None)

    def _read_snapshot(self, key: str) -> Optional[dict]:
        snapshot = self.redis_get_json(key)
        if isinstance(snapshot, dict):
            return snapshot
        now = time.monotonic()
        with self._memory_snapshots_lock:
            memory_entry = self._memory_snapshots.get(key)
            if not memory_entry:
                return None
            expires_at, memory_snapshot = memory_entry
            if expires_at <= now:
                self._memory_snapshots.pop(key, None)
                return None
            return memory_snapshot if isinstance(memory_snapshot, dict) else None

    def _write_snapshot(self, key: str, snapshot_value: dict, ttl_seconds: int) -> bool:
        existing = self._read_snapshot(key)
        if existing is not None:
            return False
        self.redis_set_json(key, snapshot_value, ttl_seconds)
        with self._memory_snapshots_lock:
            now = time.monotonic()
            self._memory_snapshots[key] = (now + max(1, ttl_seconds), snapshot_value)
            self._prune_memory_snapshots_locked(now)
        return True

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

    def _save_period_snapshots(
        self,
        group_by: str,
        stats_data: Dict,
        now_ts: float,
        identity_stats: Optional[Dict] = None,
    ) -> None:
        """Persist rolling snapshots used for period deltas."""
        if not isinstance(stats_data, dict):
            return

        snapshot_stats = identity_stats if group_by in {"node", "inbound"} and isinstance(identity_stats, dict) else stats_data
        snapshot_value = {"ts": now_ts, "stats": snapshot_stats}
        for bucket_kind, config in self._ROLLING_SNAPSHOT_CONFIG.items():
            bucket_seconds = int(config["bucket_seconds"])
            bucket_id = int(now_ts / bucket_seconds)
            redis_key = self._snapshot_key(group_by, bucket_kind, bucket_id)
            created = self._write_snapshot(redis_key, snapshot_value, int(config["ttl_seconds"]))
            if created:
                self._persist_snapshot_to_db(group_by, bucket_kind, bucket_id, snapshot_value)

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

                        node_key = self._stable_node_key(node_id, str(node_name or f"node-{node_id}"))
                        total = int(float(traffic_total or 0))
                        payload["stats"][node_key] = {
                            "up": 0,
                            "down": total,
                            "total": total,
                            "count": 1,
                            "_display_key": str(node_name or f"node-{node_id}"),
                            "_legacy_key": str(node_name or f"node-{node_id}"),
                        }

                    inserted = 0
                    for bucket_id, payload in sorted(bucket_payloads.items()):
                        if not payload["stats"]:
                            continue
                        name_counts: Dict[str, int] = {}
                        for value in payload["stats"].values():
                            if isinstance(value, dict):
                                name = str(value.get("_legacy_key") or "")
                                if name:
                                    name_counts[name] = name_counts.get(name, 0) + 1
                        for node_key, value in payload["stats"].items():
                            if not isinstance(value, dict):
                                continue
                            legacy_key = str(value.get("_legacy_key") or node_key)
                            node_id = str(node_key).removeprefix("node:")
                            value["_display_key"] = (
                                legacy_key if name_counts.get(legacy_key, 0) == 1 else f"{legacy_key} #{node_id or 'unknown'}"
                            )
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
