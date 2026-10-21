from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Callable, Dict, List, Optional

from shared.observability import record_cache


logger = logging.getLogger(__name__)


class ClientsRuntime:
    def __init__(
        self,
        *,
        client_mgr,
        clients_cache: Dict,
        clients_cache_ttl: int,
        clients_cache_stale_ttl: int,
        start_cache_refresh,
        filter_reachable_nodes: Optional[Callable[[List[Dict]], List[Dict]]] = None,
    ) -> None:
        self.client_mgr = client_mgr
        self.clients_cache = clients_cache
        self.clients_cache_ttl = clients_cache_ttl
        self.clients_cache_stale_ttl = clients_cache_stale_ttl
        self.start_cache_refresh = start_cache_refresh
        self.filter_reachable_nodes = filter_reachable_nodes or (lambda nodes: nodes)
        self._cold_load_lock = Lock()
        self._cache_state_lock = Lock()
        self._cache_generation = 0

    def _nodes_for_loader(self, nodes: List[Dict]) -> List[Dict]:
        filtered = self.filter_reachable_nodes(nodes)
        skipped = len(nodes) - len(filtered)
        if skipped:
            logger.debug("Filtered %d unavailable node(s) from clients projection", skipped)
        return filtered

    def _snapshot_cache(self) -> tuple[float, List[Dict], int, bool]:
        with self._cache_state_lock:
            data = self.clients_cache.get("data")
            return (
                float(self.clients_cache.get("ts") or 0.0),
                data if isinstance(data, list) else [],
                self._cache_generation,
                bool(self.clients_cache.get("invalidated")),
            )

    def _store_cache(self, data: List[Dict], generation: int) -> bool:
        """Store a refresh only when no successful mutation invalidated it."""
        with self._cache_state_lock:
            if generation != self._cache_generation:
                return False
            self.clients_cache["ts"] = time.time()
            self.clients_cache["data"] = data
            self.clients_cache["invalidated"] = False
            return True

    def invalidate(self) -> None:
        """Invalidate a projection without discarding its last valid snapshot."""
        with self._cache_state_lock:
            self._cache_generation += 1
            if self.clients_cache.get("data"):
                self.clients_cache["invalidated"] = True
            else:
                self.clients_cache["ts"] = 0.0
                self.clients_cache["invalidated"] = False

    def get_cached_clients(
        self, nodes: List[Dict], email_filter: Optional[str] = None, force: bool = False
    ) -> List[Dict]:
        now = time.time()
        cached_at, full_list, generation, invalidated = self._snapshot_cache()

        def _apply_filter(items: List[Dict]) -> List[Dict]:
            if not email_filter:
                return items
            needle = email_filter.lower()
            return [c for c in items if needle in str(c.get("email", "")).lower()]

        if force:
            with self._cold_load_lock:
                _, _, generation, _ = self._snapshot_cache()
                fresh = self.client_mgr.get_all_clients(
                    self._nodes_for_loader(nodes), email_filter=None
                )
                self._store_cache(fresh, generation)
                return _apply_filter(fresh)

        if full_list and invalidated:
            record_cache("memory_stale")

            def _refresh() -> None:
                fresh = self.client_mgr.get_all_clients(
                    self._nodes_for_loader(nodes), email_filter=None
                )
                self._store_cache(fresh, generation)

            self.start_cache_refresh("clients", _refresh)
            return _apply_filter(full_list)

        if full_list and now - cached_at < self.clients_cache_ttl:
            record_cache("memory_fresh")
            return _apply_filter(full_list)

        if full_list and now - cached_at < self.clients_cache_stale_ttl:
            record_cache("memory_stale")

            def _refresh() -> None:
                fresh = self.client_mgr.get_all_clients(
                    self._nodes_for_loader(nodes), email_filter=None
                )
                self._store_cache(fresh, generation)

            self.start_cache_refresh("clients", _refresh)
            return _apply_filter(full_list)

        # A simultaneous cold navigation and header request must share one
        # fleet fetch. The second caller rechecks the cache after the first
        # loader leaves the critical section.
        with self._cold_load_lock:
            now = time.time()
            cached_at, full_list, generation, invalidated = self._snapshot_cache()
            if full_list and invalidated:
                record_cache("memory_stale")
                return _apply_filter(full_list)
            if full_list and now - cached_at < self.clients_cache_ttl:
                record_cache("memory_fresh")
                return _apply_filter(full_list)
            record_cache("memory_miss")
            fresh = self.client_mgr.get_all_clients(
                self._nodes_for_loader(nodes), email_filter=None
            )
            self._store_cache(fresh, generation)
            return _apply_filter(fresh)
