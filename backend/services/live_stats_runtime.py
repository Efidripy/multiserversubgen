from __future__ import annotations

import time
from threading import Thread
from typing import Dict, List, Optional


class LiveStatsRuntime:
    def __init__(
        self,
        *,
        client_mgr,
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
        # Key: "traffic_snapshot:{group_by}:{period}:{bucket_id}"
        # Value: {"ts": float, "stats": dict}
        self._memory_snapshots: Dict[str, dict] = {}

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

        data = self.client_mgr.get_traffic_stats(nodes, group_by)
        self.traffic_stats_cache[group_by] = (now, data)
        self.redis_set_json(redis_key, data, self.traffic_stats_cache_ttl)
        self._save_period_snapshots(group_by, data.get("stats", {}), now)
        return data

    def _save_period_snapshots(self, group_by: str, stats_data: Dict, now_ts: float) -> None:
        """Persist earliest snapshot per period bucket (do not overwrite)."""
        if not isinstance(stats_data, dict):
            return

        period_configs = [
            ("day", 86400),
            ("week", 604800),
            ("month", 2592000),
            ("year", 31536000),
        ]

        for period_name, seconds in period_configs:
            bucket_id = int(now_ts / seconds)
            redis_key = f"traffic_snapshot:{group_by}:{period_name}:{bucket_id}"
            existing = self.redis_get_json(redis_key)
            if existing is not None:
                continue
            # Check in-memory fallback before writing
            if redis_key in self._memory_snapshots:
                continue
            snapshot_value = {"ts": now_ts, "stats": stats_data}
            ttl_seconds = seconds * 2
            self.redis_set_json(redis_key, snapshot_value, ttl_seconds)
            # Always keep in-memory copy as fallback when Redis is absent
            self._memory_snapshots[redis_key] = snapshot_value

    def _load_period_snapshot(self, group_by: str, period: str, seconds_back: int, now_ts: float):
        """Load the best available snapshot around the requested period start."""
        target_ts = now_ts - seconds_back
        target_bucket = int(target_ts / seconds_back)
        current_bucket = int(now_ts / seconds_back)

        candidate_buckets = []
        for bucket in [
            target_bucket,
            target_bucket + 1,
            target_bucket - 1,
            current_bucket,
            current_bucket - 1,
        ]:
            if bucket not in candidate_buckets:
                candidate_buckets.append(bucket)

        for bucket in candidate_buckets:
            redis_key_snapshot = f"traffic_snapshot:{group_by}:{period}:{bucket}"
            snapshot = self.redis_get_json(redis_key_snapshot)
            if not isinstance(snapshot, dict):
                # Fallback to in-memory when Redis is unavailable
                snapshot = self._memory_snapshots.get(redis_key_snapshot)
            if not isinstance(snapshot, dict):
                continue
            snapshot_stats = snapshot.get("stats", {})
            if isinstance(snapshot_stats, dict) and snapshot_stats:
                return snapshot, snapshot_stats

        return None, None

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
        snapshot, snapshot_stats = self._load_period_snapshot(group_by, period, seconds_back, now)
        
        if not snapshot_stats or not isinstance(snapshot_stats, dict):
            # If no snapshot exists for this period, we can't calculate delta
            # Return current stats as estimate (assumes values only increase)
            # In production, snapshots should be saved periodically
            return {
                "stats": current_data,
                "group_by": group_by,
                "period": period,
                "period_start": period_start_time,
                "note": "No historical snapshot available; showing current total"
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
