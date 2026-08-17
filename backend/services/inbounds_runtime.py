from __future__ import annotations

import time
from threading import Lock
from typing import Dict, List


class InboundsRuntime:
    """Stale-while-revalidate cache for inbounds data.

    fresh_ttl  — serve directly from cache (default 30s)
    stale_ttl  — serve stale + kick background refresh (default 300s)
    After stale_ttl expires, blocks until a fresh fetch completes.
    """

    def __init__(
        self,
        *,
        inbound_mgr,
        inbounds_cache: Dict,
        fresh_ttl: int = 30,
        stale_ttl: int = 300,
        start_cache_refresh,
    ) -> None:
        self.inbound_mgr = inbound_mgr
        self.inbounds_cache = inbounds_cache
        self.fresh_ttl = fresh_ttl
        self.stale_ttl = stale_ttl
        self.start_cache_refresh = start_cache_refresh
        self._cold_load_lock = Lock()

    def get_cached_inbounds(self, nodes: List[Dict]) -> List[Dict]:
        now = time.time()
        cached = self.inbounds_cache.get("data") or []

        if cached and now - self.inbounds_cache["ts"] < self.fresh_ttl:
            return cached

        if cached and now - self.inbounds_cache["ts"] < self.stale_ttl:
            def _refresh() -> None:
                fresh = self.inbound_mgr.get_all_inbounds(nodes)
                self.inbounds_cache["ts"] = time.time()
                self.inbounds_cache["data"] = fresh

            self.start_cache_refresh("inbounds", _refresh)
            return cached

        # Coalesce cache misses: only one caller may fan out to the fleet,
        # while concurrent callers reuse the value populated by that loader.
        with self._cold_load_lock:
            now = time.time()
            cached = self.inbounds_cache.get("data") or []
            if cached and now - self.inbounds_cache["ts"] < self.fresh_ttl:
                return cached
            fresh = self.inbound_mgr.get_all_inbounds(nodes)
            self.inbounds_cache["ts"] = time.time()
            self.inbounds_cache["data"] = fresh
            return fresh
