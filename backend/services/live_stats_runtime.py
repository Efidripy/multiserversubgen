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
            return redis_data

        now = time.time()
        cached = self.traffic_stats_cache.get(group_by)
        if cached and now - cached[0] < self.traffic_stats_cache_ttl:
            return cached[1]

        if cached and now - cached[0] < self.traffic_stats_stale_ttl:
            def _refresh():
                fresh = self.client_mgr.get_traffic_stats(nodes, group_by)
                self.traffic_stats_cache[group_by] = (time.time(), fresh)
                self.redis_set_json(redis_key, fresh, self.traffic_stats_cache_ttl)

            self.start_cache_refresh("traffic", _refresh, worker_key=group_by)
            return cached[1]

        data = self.client_mgr.get_traffic_stats(nodes, group_by)
        self.traffic_stats_cache[group_by] = (now, data)
        self.redis_set_json(redis_key, data, self.traffic_stats_cache_ttl)
        return data

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
