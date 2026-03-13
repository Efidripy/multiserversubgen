from __future__ import annotations

import time
from typing import Dict, List, Optional


class ClientsRuntime:
    def __init__(
        self,
        *,
        client_mgr,
        clients_cache: Dict,
        clients_cache_ttl: int,
        clients_cache_stale_ttl: int,
        start_cache_refresh,
    ) -> None:
        self.client_mgr = client_mgr
        self.clients_cache = clients_cache
        self.clients_cache_ttl = clients_cache_ttl
        self.clients_cache_stale_ttl = clients_cache_stale_ttl
        self.start_cache_refresh = start_cache_refresh

    def get_cached_clients(self, nodes: List[Dict], email_filter: Optional[str] = None) -> List[Dict]:
        now = time.time()
        full_list = self.clients_cache["data"] if isinstance(self.clients_cache["data"], list) else []

        def _apply_filter(items: List[Dict]) -> List[Dict]:
            if not email_filter:
                return items
            needle = email_filter.lower()
            return [c for c in items if needle in str(c.get("email", "")).lower()]

        if full_list and now - self.clients_cache["ts"] < self.clients_cache_ttl:
            return _apply_filter(full_list)

        if full_list and now - self.clients_cache["ts"] < self.clients_cache_stale_ttl:
            def _refresh() -> None:
                fresh = self.client_mgr.get_all_clients(nodes, email_filter=None)
                self.clients_cache["ts"] = time.time()
                self.clients_cache["data"] = fresh

            self.start_cache_refresh("clients", _refresh)
            return _apply_filter(full_list)

        fresh = self.client_mgr.get_all_clients(nodes, email_filter=None)
        self.clients_cache["ts"] = now
        self.clients_cache["data"] = fresh
        return _apply_filter(fresh)
