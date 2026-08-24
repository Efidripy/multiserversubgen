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
        # These projections are deliberately independent from the full DTO
        # cache: a slim/options response must never be returned to an edit
        # flow that requires settings, streamSettings and unknown v3 fields.
        self._slim_cache: Dict = {"ts": 0.0, "data": []}
        self._options_cache: Dict = {"ts": 0.0, "data": []}
        self._slim_cold_load_lock = Lock()
        self._options_cold_load_lock = Lock()
        self._cache_state_lock = Lock()
        self._cache_generations = {"inbounds": 0, "inbounds_slim": 0, "inbounds_options": 0}

    def _snapshot_cache(self, cache: Dict, cache_key: str) -> tuple[float, List[Dict], int]:
        with self._cache_state_lock:
            data = cache.get("data")
            return (
                float(cache.get("ts") or 0.0),
                data if isinstance(data, list) else [],
                self._cache_generations[cache_key],
            )

    def _store_cache(self, *, cache: Dict, cache_key: str, data: List[Dict], generation: int) -> bool:
        """Publish a refresh only if no control-plane write superseded it."""
        with self._cache_state_lock:
            if generation != self._cache_generations[cache_key]:
                return False
            cache["ts"] = time.time()
            cache["data"] = data
            return True

    def invalidate(self) -> None:
        """Discard full, slim and picker projections after a successful write."""
        with self._cache_state_lock:
            for cache_key, cache in (
                ("inbounds", self.inbounds_cache),
                ("inbounds_slim", self._slim_cache),
                ("inbounds_options", self._options_cache),
            ):
                self._cache_generations[cache_key] += 1
                cache["ts"] = 0.0
                cache["data"] = []

    def _cached_full_by_node(self) -> Dict[str, List[Dict]]:
        """Index already-held full cache rows for legacy projection fallback.

        This method intentionally does not refresh the full cache.  It lets an
        older node reuse the fleet result already fetched for the full inbound
        page, avoiding a second fan-out merely to populate a picker.
        """
        indexed: Dict[str, List[Dict]] = {}
        for inbound in self.inbounds_cache.get("data") or []:
            if not isinstance(inbound, dict):
                continue
            node_id = inbound.get("node_id")
            node_name = inbound.get("node_name")
            if node_id is not None:
                indexed.setdefault(str(node_id), []).append(inbound)
            if node_name:
                indexed.setdefault(str(node_name), []).append(inbound)
        return indexed

    def _get_cached_projection(self, *, cache: Dict, lock: Lock, cache_key: str, nodes: List[Dict], loader) -> List[Dict]:
        now = time.time()
        cached_at, cached, generation = self._snapshot_cache(cache, cache_key)
        if cached and now - cached_at < self.fresh_ttl:
            return cached

        if cached and now - cached_at < self.stale_ttl:
            def _refresh() -> None:
                fresh = loader(nodes, cached_full=self._cached_full_by_node())
                self._store_cache(cache=cache, cache_key=cache_key, data=fresh, generation=generation)

            self.start_cache_refresh(cache_key, _refresh)
            return cached

        with lock:
            now = time.time()
            cached_at, cached, generation = self._snapshot_cache(cache, cache_key)
            if cached and now - cached_at < self.fresh_ttl:
                return cached
            fresh = loader(nodes, cached_full=self._cached_full_by_node())
            self._store_cache(cache=cache, cache_key=cache_key, data=fresh, generation=generation)
            return fresh

    def get_cached_inbounds(self, nodes: List[Dict]) -> List[Dict]:
        now = time.time()
        cached_at, cached, generation = self._snapshot_cache(self.inbounds_cache, "inbounds")

        if cached and now - cached_at < self.fresh_ttl:
            return cached

        if cached and now - cached_at < self.stale_ttl:
            def _refresh() -> None:
                fresh = self.inbound_mgr.get_all_inbounds(nodes)
                self._store_cache(
                    cache=self.inbounds_cache,
                    cache_key="inbounds",
                    data=fresh,
                    generation=generation,
                )

            self.start_cache_refresh("inbounds", _refresh)
            return cached

        # Coalesce cache misses: only one caller may fan out to the fleet,
        # while concurrent callers reuse the value populated by that loader.
        with self._cold_load_lock:
            now = time.time()
            cached_at, cached, generation = self._snapshot_cache(self.inbounds_cache, "inbounds")
            if cached and now - cached_at < self.fresh_ttl:
                return cached
            fresh = self.inbound_mgr.get_all_inbounds(nodes)
            self._store_cache(
                cache=self.inbounds_cache,
                cache_key="inbounds",
                data=fresh,
                generation=generation,
            )
            return fresh

    def get_cached_slim_inbounds(self, nodes: List[Dict]) -> List[Dict]:
        """Read-only slim list cache, isolated from full edit DTOs."""
        return self._get_cached_projection(
            cache=self._slim_cache,
            lock=self._slim_cold_load_lock,
            cache_key="inbounds_slim",
            nodes=nodes,
            loader=self.inbound_mgr.get_all_slim_inbounds,
        )

    def get_cached_inbound_options(self, nodes: List[Dict]) -> List[Dict]:
        """Read-only inbound picker cache, isolated from full edit DTOs."""
        return self._get_cached_projection(
            cache=self._options_cache,
            lock=self._options_cold_load_lock,
            cache_key="inbounds_options",
            nodes=nodes,
            loader=self.inbound_mgr.get_all_inbound_options,
        )
