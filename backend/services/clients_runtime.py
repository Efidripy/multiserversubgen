from __future__ import annotations

import json
import logging
import math
import sqlite3
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
        db_path: Optional[str] = None,
        encrypt: Optional[Callable[[str], str]] = None,
        decrypt: Optional[Callable[[str], str]] = None,
        get_inbound_metadata: Optional[Callable[[object], Dict]] = None,
    ) -> None:
        self.get_inbound_metadata = get_inbound_metadata
        self.client_mgr = client_mgr
        self.clients_cache = clients_cache
        self.clients_cache_ttl = clients_cache_ttl
        self.clients_cache_stale_ttl = clients_cache_stale_ttl
        self.start_cache_refresh = start_cache_refresh
        self.filter_reachable_nodes = filter_reachable_nodes or (lambda nodes: nodes)
        self._cold_load_lock = Lock()
        self._cache_state_lock = Lock()
        self._cache_generation = 0
        self._db_path = db_path if db_path and encrypt and decrypt else None
        self._encrypt = encrypt
        self._decrypt = decrypt
        self._restore_cache()

    def _restore_cache(self) -> None:
        if not (self._db_path and self._decrypt):
            return
        try:
            with sqlite3.connect(self._db_path, timeout=1) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS clients_cache_snapshot "
                    "(id INTEGER PRIMARY KEY CHECK (id = 1), ts REAL NOT NULL, data TEXT NOT NULL)"
                )
                row = conn.execute(
                    "SELECT ts, data FROM clients_cache_snapshot WHERE id = 1"
                ).fetchone()
            if not row:
                return
            ts = float(row[0])
            if not math.isfinite(ts) or not 0 <= time.time() - ts < self.clients_cache_stale_ttl:
                return
            data = json.loads(self._decrypt(row[1]))
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise ValueError("invalid cache")
            self.clients_cache.update(ts=ts, data=data, invalidated=False)
        except Exception:
            logger.warning("Could not restore clients cache")

    def _persist_cache(self, ts: float, data: List[Dict]) -> None:
        if not (self._db_path and self._encrypt):
            return
        try:
            encrypted = self._encrypt(json.dumps(data, ensure_ascii=False))
            with sqlite3.connect(self._db_path, timeout=1) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS clients_cache_snapshot "
                    "(id INTEGER PRIMARY KEY CHECK (id = 1), ts REAL NOT NULL, data TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT OR REPLACE INTO clients_cache_snapshot (id, ts, data) VALUES (1, ?, ?)",
                    (ts, encrypted),
                )
        except Exception:
            logger.warning("Could not save clients cache")

    def _delete_persisted_cache(self) -> None:
        if not self._db_path:
            return
        try:
            with sqlite3.connect(self._db_path, timeout=1) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS clients_cache_snapshot "
                             "(id INTEGER PRIMARY KEY CHECK (id = 1), ts REAL NOT NULL, data TEXT NOT NULL)")
                conn.execute("DELETE FROM clients_cache_snapshot WHERE id = 1")
        except Exception:
            logger.warning("Could not delete clients cache")

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

    def _fill_inbound_fields(self, data: List[Dict]) -> List[Dict]:
        """Keep inbound columns in the rows, so they outlive a node going offline."""
        fields = ("protocol", "inbound_remark", "network")
        known: Dict = {}
        for row in self._snapshot_cache()[1]:
            key = (row.get("node_id"), row.get("inbound_id"))
            known.setdefault(key, {}).update({f: row[f] for f in fields if row.get(f)})
        metadata: Dict = {}
        result = []
        for row in data:
            node_id, inbound_id = row.get("node_id"), row.get("inbound_id")
            if inbound_id is None:
                result.append(row)
                continue
            if node_id not in metadata:
                metadata[node_id] = (
                    self.get_inbound_metadata(node_id) if self.get_inbound_metadata else {}
                )
            current = metadata[node_id].get(str(inbound_id), {})
            previous = known.get((node_id, inbound_id), {})
            filled = {
                f: current.get(f) or previous.get(f)
                for f in fields
                if not row.get(f) and (current.get(f) or previous.get(f))
            }
            result.append({**row, **filled} if filled else row)
        return result

    def _store_cache(self, data: List[Dict], generation: int) -> bool:
        """Store a refresh only when no successful mutation invalidated it."""
        data = self._fill_inbound_fields(data)
        with self._cache_state_lock:
            if generation != self._cache_generation:
                return False
            self.clients_cache["ts"] = time.time()
            self.clients_cache["data"] = data
            self.clients_cache["invalidated"] = False
            self._persist_cache(self.clients_cache["ts"], data)
            return True

    def invalidate(self) -> None:
        """Invalidate a projection without discarding its last valid snapshot."""
        with self._cache_state_lock:
            self._cache_generation += 1
            self._delete_persisted_cache()
            if self.clients_cache.get("data"):
                self.clients_cache["invalidated"] = True
            else:
                self.clients_cache["ts"] = 0.0
                self.clients_cache["invalidated"] = False

    def _start_background_refresh(self, nodes: List[Dict], generation: int) -> None:
        def refresh() -> None:
            reachable = self._nodes_for_loader(nodes)
            inventory_ids = {node.get("id") for node in nodes}
            reachable_ids = {node.get("id") for node in reachable}
            loader = getattr(self.client_mgr, "_get_all_clients_with_status", None)
            if loader is None:
                fresh = self.client_mgr.get_all_clients(reachable, email_filter=None)
                failed = set()
            else:
                fresh, failed = loader(reachable, email_filter=None)
            retained = (inventory_ids - reachable_ids) | failed
            _, previous, _, _ = self._snapshot_cache()
            merged = [client for client in fresh if client.get("node_id") not in retained]
            merged.extend(client for client in previous if client.get("node_id") in retained)
            self._store_cache(merged, generation)

        self.start_cache_refresh("clients", refresh)

    def refresh_after_collector_cycle(self, nodes: List[Dict], mode: str) -> None:
        cached_at, _, generation, invalidated = self._snapshot_cache()
        threshold = 300 if mode in ("warming", "active") else 1800
        if not cached_at or invalidated or time.time() - cached_at >= threshold:
            self._start_background_refresh(nodes, generation)

    def get_cached_clients(
        self, nodes: List[Dict], email_filter: Optional[str] = None, force: bool = False
    ) -> List[Dict]:
        now = time.time()
        cached_at, full_list, generation, invalidated = self._snapshot_cache()

        def _apply_filter(items: List[Dict]) -> List[Dict]:
            if self._db_path:
                inventory_ids = {node.get("id") for node in nodes}
                items = [item for item in items if item.get("node_id") in inventory_ids]
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

            self._start_background_refresh(nodes, generation)
            return _apply_filter(full_list)

        if full_list and now - cached_at < self.clients_cache_ttl:
            record_cache("memory_fresh")
            return _apply_filter(full_list)

        if full_list and now - cached_at < self.clients_cache_stale_ttl:
            record_cache("memory_stale")

            self._start_background_refresh(nodes, generation)
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
