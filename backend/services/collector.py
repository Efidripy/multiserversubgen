import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from enum import Enum

from services.db_bootstrap import connect
from services.snapshot_push import build_snapshot_push_payload


logger = logging.getLogger("sub_manager")


def _detect_api_version(panel_version: str) -> str:
    """Return 'v3' if panelVersion >= 3.x, else 'v2'.
    v2 panels don't return panelVersion at all, so absence means v2."""
    if not panel_version:
        return "v2"
    try:
        major = int(panel_version.split(".")[0])
        return "v3" if major >= 3 else "v2"
    except (ValueError, IndexError):
        return "v2"


class CollectorMode(Enum):
    """Collector operating modes."""
    ULTRA_IDLE = "ultra_idle"     # No activity for 24h → poll once a day
    IDLE = "idle"                 # No activity for 10min → poll once an hour
    WARMING = "warming"           # First 10min after connect → poll every 5-20s
    ACTIVE = "active"             # Long active session → poll every 30s


class SnapshotCollector:
    """Background collector with 4 adaptive modes based on WebSocket activity."""

    def __init__(
        self,
        *,
        fetch_nodes: Callable[[], List[Dict]],
        xui_monitor,
        ws_manager,
        db_path: Optional[str] = None,
        on_snapshot: Optional[Callable[[Dict], None]] = None,
        base_interval_sec: int = 5,
        max_interval_sec: int = 86400,
        min_interval_sec: int = 3,
        max_parallel_polls: int = 8,
        warming_interval_1_sec: int = 30,
        warming_interval_2_sec: int = 60,
        warming_interval_3_sec: int = 120,
        active_interval_sec: int = 120,
        idle_interval_sec: int = 3600,
        ultra_idle_interval_sec: int = 86400,
        idle_after_sec: int = 900,
        ultra_idle_after_sec: int = 86400,
        poll_interval_ceiling_sec: int = 60,
        degraded_backoff_sec: int = 300,
    ):
        self.fetch_nodes = fetch_nodes
        self.xui_monitor = xui_monitor
        self.ws_manager = ws_manager
        self.base_interval_sec = max(1, base_interval_sec)
        self.max_interval_sec = max(self.base_interval_sec, max_interval_sec)
        self.min_interval_sec = max(1, min_interval_sec)
        self.configured_max_parallel_polls = max(1, max_parallel_polls)
        self.max_parallel_polls = 5
        self.semaphore = asyncio.Semaphore(5)
        self.warming_interval_1_sec = max(3, warming_interval_1_sec)
        self.warming_interval_2_sec = max(self.warming_interval_1_sec, warming_interval_2_sec)
        self.warming_interval_3_sec = max(self.warming_interval_2_sec, warming_interval_3_sec)
        self.active_interval_sec = max(3, active_interval_sec)
        self.idle_interval_sec = max(self.active_interval_sec, idle_interval_sec)
        self.ultra_idle_interval_sec = max(self.idle_interval_sec, ultra_idle_interval_sec)
        self.idle_after_sec = max(60, idle_after_sec)
        self.ultra_idle_after_sec = max(self.idle_after_sec, ultra_idle_after_sec)
        self.poll_interval_ceiling_sec = max(30, min(60, poll_interval_ceiling_sec))
        self.degraded_backoff_sec = max(180, min(300, degraded_backoff_sec))
        self.db_path = db_path
        self.on_snapshot = on_snapshot

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
        self._snapshot_write_lock = asyncio.Lock()
        self._node_state: Dict[str, Dict] = {}
        self._latest = {"timestamp": None, "nodes": {}}

        # Adaptive mode state
        self._mode = CollectorMode.IDLE
        self._last_ws_activity = 0.0
        self._mode_started_at = time.time()
        self._force_poll_event = asyncio.Event()

    def latest_snapshot(self) -> Dict:
        nodes = list(self._latest["nodes"].values())
        nodes.sort(key=lambda x: x.get("name", ""))
        return {
            "timestamp": self._latest["timestamp"],
            "nodes": nodes,
            "count": len(nodes),
            "mode": self._mode.value,
        }

    async def load_persisted_snapshots(self) -> int:
        if not self.db_path:
            return 0
        rows = await asyncio.to_thread(self._load_persisted_snapshot_rows)
        if not rows:
            return 0

        latest_nodes: Dict[str, Dict] = {}
        restored_node_state: Dict[str, Dict] = {}
        latest_ts = 0.0
        now = time.time()
        for key, snapshot, ts in rows:
            latest_nodes[key] = snapshot
            circuit_until = self._coerce_float(snapshot.get("circuit_open_until"), 0.0)
            if circuit_until > now:
                interval = float(min(self.max_interval_sec, max(1.0, circuit_until - now)))
                next_poll = circuit_until
                failures = 1
            else:
                interval = float(self._get_current_interval())
                next_poll = 0.0
                failures = 0
            restored_node_state[key] = {
                "next_poll": next_poll,
                "interval": interval,
                "failures": failures,
                "stable_cycles": 0,
                "last_hash": json.dumps(snapshot, sort_keys=True, ensure_ascii=False) if snapshot.get("available") else "",
                "circuit_until": circuit_until if circuit_until > now else 0.0,
            }
            latest_ts = max(latest_ts, ts)

        async with self._lock:
            if self._latest["nodes"]:
                return 0
            self._latest["nodes"] = latest_nodes
            self._latest["timestamp"] = latest_ts or time.time()
            self._node_state.update(restored_node_state)
        logger.info("Loaded %d node snapshots from SQLite cache", len(latest_nodes))
        return len(latest_nodes)

    def _load_persisted_snapshot_rows(self) -> List[tuple[str, Dict, float]]:
        if not self.db_path:
            return []
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            self._ensure_snapshot_table(conn)
            rows = conn.execute(
                """
                SELECT s.node_id, s.status_data, s.is_online, s.updated_at, n.name AS node_name
                FROM node_snapshots s
                INNER JOIN nodes n ON n.id = s.node_id
                ORDER BY n.name COLLATE NOCASE ASC, s.node_id ASC
                """
            ).fetchall()

        loaded: List[tuple[str, Dict, float]] = []
        for row in rows:
            try:
                snapshot = json.loads(row["status_data"] or "{}")
            except Exception as exc:
                logger.warning("Ignoring invalid node snapshot row %s: %s", row["node_id"], exc)
                continue
            if not isinstance(snapshot, dict):
                continue

            node_id = int(row["node_id"])
            node_name = row["node_name"] or snapshot.get("name") or str(node_id)
            is_online = bool(row["is_online"])
            snapshot = dict(snapshot)
            snapshot["node_id"] = snapshot.get("node_id") or node_id
            snapshot["name"] = node_name
            snapshot.setdefault("available", is_online)
            snapshot.setdefault("status", "online" if is_online else "offline")
            snapshot.setdefault("reason", "loaded_from_snapshot")
            snapshot["cached_from_db"] = True
            snapshot["snapshot_updated_at"] = row["updated_at"]
            ts = self._coerce_snapshot_timestamp(snapshot.get("timestamp"), row["updated_at"])
            snapshot["timestamp"] = ts
            loaded.append((str(node_name), snapshot, ts))
        return loaded

    async def _persist_snapshot(self, snapshot: Dict) -> None:
        if not self.db_path or snapshot.get("node_id") is None:
            return
        try:
            async with self._snapshot_write_lock:
                await asyncio.to_thread(self._upsert_snapshot_row, snapshot)
        except Exception as exc:
            logger.warning("Failed to persist node snapshot %s: %s", snapshot.get("node_id"), exc)

    def _upsert_snapshot_row(self, snapshot: Dict) -> None:
        if not self.db_path:
            return
        node_id = snapshot.get("node_id")
        try:
            node_id_int = int(node_id)
        except (TypeError, ValueError):
            return

        payload = dict(snapshot)
        payload.pop("cached_from_db", None)
        payload.pop("snapshot_updated_at", None)
        status_data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        is_online = 1 if bool(snapshot.get("available")) else 0

        with connect(self.db_path) as conn:
            self._ensure_snapshot_table(conn)
            conn.execute(
                """
                INSERT INTO node_snapshots (node_id, status_data, is_online, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(node_id) DO UPDATE SET
                    status_data = excluded.status_data,
                    is_online = excluded.is_online,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (node_id_int, status_data, is_online),
            )
            conn.commit()

    @staticmethod
    def _ensure_snapshot_table(conn) -> None:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS node_snapshots
                     (node_id INTEGER PRIMARY KEY,
                      status_data TEXT NOT NULL,
                      is_online INTEGER NOT NULL DEFAULT 0,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      FOREIGN KEY(node_id) REFERENCES nodes(id) ON DELETE CASCADE)"""
        )

    @staticmethod
    def _coerce_snapshot_timestamp(value, updated_at) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        try:
            return (
                datetime.strptime(str(updated_at), "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
        except Exception:
            return time.time()

    @staticmethod
    def _coerce_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def is_running(self) -> bool:
        return self._running

    def get_mode(self) -> str:
        """Return current operating mode name."""
        return self._mode.value

    def on_websocket_activity(self):
        """Called on any WebSocket activity to trigger faster polling."""
        now = time.time()
        self._last_ws_activity = now
        if self._mode in (CollectorMode.IDLE, CollectorMode.ULTRA_IDLE):
            self._switch_mode(CollectorMode.WARMING)

    async def force_poll_all(self):
        """Force an immediate poll of all nodes (triggered by UI button)."""
        logger.info("Force poll all nodes requested")
        self._force_poll_event.set()

    def _switch_mode(self, new_mode: CollectorMode):
        """Switch to a new operating mode."""
        if self._mode != new_mode:
            old_mode = self._mode
            self._mode = new_mode
            self._mode_started_at = time.time()
            logger.info(f"Collector mode changed: {old_mode.value} → {new_mode.value}")

    def _get_current_interval(self) -> float:
        """Return polling interval in seconds based on current mode."""
        now = time.time()
        time_in_mode = now - self._mode_started_at

        if self._mode == CollectorMode.ULTRA_IDLE:
            return float(self.ultra_idle_interval_sec)

        elif self._mode == CollectorMode.IDLE:
            return float(self.idle_interval_sec)

        elif self._mode == CollectorMode.WARMING:
            if time_in_mode < 120:
                return float(self.warming_interval_1_sec)
            elif time_in_mode < 300:
                return float(self.warming_interval_2_sec)
            elif time_in_mode < 600:
                return float(self.warming_interval_3_sec)
            else:
                self._switch_mode(CollectorMode.ACTIVE)
                return float(self.active_interval_sec)

        elif self._mode == CollectorMode.ACTIVE:
            return float(self.active_interval_sec)

        return float(self.base_interval_sec)

    def _update_mode_based_on_activity(self):
        """Automatically switch modes based on WebSocket connection activity."""
        now = time.time()
        ws_connections = len(self.ws_manager.active_connections) if hasattr(self.ws_manager, 'active_connections') else 0
        time_since_last_activity = now - self._last_ws_activity if self._last_ws_activity > 0 else float('inf')

        if ws_connections > 0:
            self._last_ws_activity = now
            if self._mode in (CollectorMode.IDLE, CollectorMode.ULTRA_IDLE):
                self._switch_mode(CollectorMode.WARMING)
        else:
            if time_since_last_activity > self.ultra_idle_after_sec and self._mode != CollectorMode.ULTRA_IDLE:
                self._switch_mode(CollectorMode.ULTRA_IDLE)
            elif time_since_last_activity > self.idle_after_sec and self._mode not in (CollectorMode.IDLE, CollectorMode.ULTRA_IDLE):
                self._switch_mode(CollectorMode.IDLE)

    async def start(self):
        if self._running:
            return
        await self.load_persisted_snapshots()
        self._running = True
        self._last_ws_activity = time.time()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self):
        while self._running:
            try:
                self._update_mode_based_on_activity()
                current_interval = self._get_current_interval()

                nodes = await asyncio.to_thread(self.fetch_nodes)
                now = time.time()
                active_names = {str(n.get("name", n.get("id", ""))) for n in nodes}

                # Cleanup state for removed nodes.
                for stale in list(self._node_state.keys()):
                    if stale not in active_names:
                        self._node_state.pop(stale, None)
                        self._latest["nodes"].pop(stale, None)

                tasks = []
                force_poll = self._force_poll_event.is_set()

                for node in nodes:
                    key = str(node.get("name", node.get("id", "")))
                    state = self._node_state.setdefault(
                        key,
                        {
                            "next_poll": 0.0,
                            "interval": float(current_interval),
                            "failures": 0,
                            "stable_cycles": 0,
                            "last_hash": "",
                            "circuit_until": 0.0,
                        },
                    )
                    if not force_poll and float(state.get("circuit_until", 0.0)) > now:
                        continue
                    if now >= state["next_poll"] or force_poll:
                        tasks.append(self._poll_node(node, key))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                if force_poll:
                    self._force_poll_event.clear()
                    logger.info(f"Force poll completed: {len(tasks)} nodes polled")

            except Exception as exc:
                logger.error(f"Collector loop error: {exc}")

            # Adaptive sleep: longer in idle modes; force_poll_event provides early wake-up.
            sleep_time = min(10.0, self.poll_interval_ceiling_sec / 10, self._get_current_interval() / 10)
            try:
                await asyncio.wait_for(self._force_poll_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                pass

    async def _poll_node(self, node: Dict, key: str, sem: Optional[asyncio.Semaphore] = None):
        async with self.semaphore:
            started = time.time()
            snapshot = await asyncio.to_thread(self._collect_node_snapshot, node)
        elapsed = time.time() - started
        previous = self._latest["nodes"].get(key)
        should_broadcast = False
        state = self._node_state.setdefault(
            key,
            {
                "next_poll": 0.0,
                "interval": float(self._get_current_interval()),
                "failures": 0,
                "stable_cycles": 0,
                "last_hash": "",
                "circuit_until": 0.0,
            },
        )

        if snapshot.get("available"):
            curr_hash = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
            changed = curr_hash != state["last_hash"]
            if changed:
                state["stable_cycles"] = 0
                should_broadcast = True
            else:
                state["stable_cycles"] += 1

            state["last_hash"] = curr_hash
            state["failures"] = 0
            state["circuit_until"] = 0.0

            # Adaptive interval per node based on current mode and stability.
            current_interval = self._get_current_interval()
            stable_boost = min(4, 1 + state["stable_cycles"] // 3)
            interval = min(
                self.max_interval_sec,
                self.poll_interval_ceiling_sec,
                max(self.min_interval_sec, current_interval * stable_boost),
            )
            state["interval"] = float(interval)
        else:
            state["failures"] += 1
            if self._is_timeout_snapshot(snapshot):
                circuit_until = time.time() + self.degraded_backoff_sec
                state["interval"] = float(self.degraded_backoff_sec)
                state["circuit_until"] = circuit_until
                snapshot["circuit_open_until"] = circuit_until
                snapshot["reason"] = "timeout"
                snapshot["status"] = "offline"
            else:
                current_interval = min(self._get_current_interval(), self.poll_interval_ceiling_sec)
                backoff = current_interval * (2 ** min(state["failures"], 4))
                state["interval"] = float(min(self.max_interval_sec, backoff))
            state["stable_cycles"] = 0
            curr_hash = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
            should_broadcast = curr_hash != state["last_hash"]
            state["last_hash"] = curr_hash

        state["next_poll"] = time.time() + state["interval"]
        snapshot["poll_ms"] = round(elapsed * 1000, 2)

        if self.on_snapshot is not None:
            try:
                await asyncio.to_thread(self.on_snapshot, snapshot)
            except Exception as exc:
                logger.warning(f"Collector on_snapshot callback failed for {key}: {exc}")

        async with self._lock:
            self._latest["timestamp"] = time.time()
            self._latest["nodes"][key] = snapshot
        await self._persist_snapshot(snapshot)
        if should_broadcast:
            await self._broadcast_delta(key, snapshot, previous=previous)

    def _collect_node_snapshot(self, node: Dict) -> Dict:
        name = node.get("name", "unknown")
        try:
            status = self.xui_monitor.get_server_status(node)
            if not bool(status.get("available")):
                return {
                    "name": name,
                    "node_id": node.get("id"),
                    "available": False,
                    "status": status.get("status", "offline"),
                    "reason": status.get("reason", "unavailable"),
                    "error": status.get("error", "Failed to connect"),
                    "server_status": status,
                    "xray_running": False,
                    "cpu": 0,
                    "online_clients": 0,
                    "traffic_total": 0,
                    "inbounds": [],
                    "timestamp": time.time(),
                }
            online = self.xui_monitor.get_online_clients(node)
            inbounds_result = self.xui_monitor.get_inbounds(node)

            available = bool(status.get("available"))
            inbounds = (
                inbounds_result.get("inbounds", [])
                if isinstance(inbounds_result, dict) and inbounds_result.get("available")
                else []
            )
            total_traffic = sum(
                (inbound.get("up", 0) or 0) + (inbound.get("down", 0) or 0)
                for inbound in inbounds
                if isinstance(inbound, dict)
            )

            panel_version = status.get("panel_version", "") if isinstance(status, dict) else ""
            api_version = _detect_api_version(panel_version)

            return {
                "name": name,
                "node_id": node.get("id"),
                "available": available,
                "status": "online" if available else "offline",
                "reason": status.get("reason") or ("ok" if available else "unknown"),
                "error": status.get("error", "") if isinstance(status, dict) else "",
                "xray_running": ((status.get("xray") or {}).get("running", False) if isinstance(status, dict) else False),
                "cpu": ((status.get("system") or {}).get("cpu", 0) if isinstance(status, dict) else 0),
                "online_clients": len((online.get("online_clients") or []) if isinstance(online, dict) else []),
                "traffic_total": total_traffic,
                "timestamp": time.time(),
                "panel_version": panel_version,
                "api_version": api_version,
                "server_status": status,
                "inbounds": inbounds,
                "inbounds_result": inbounds_result,
            }
        except Exception as exc:
            logger.warning(f"Collector failed for node {name}: {exc}")
            return {
                "name": name,
                "node_id": node.get("id"),
                "available": False,
                "status": "offline",
                "reason": "collector_exception",
                "error": str(exc),
                "server_status": {
                    "node": name,
                    "available": False,
                    "status": "offline",
                    "reason": "collector_exception",
                    "error": str(exc),
                },
                "xray_running": False,
                "cpu": 0,
                "online_clients": 0,
                "traffic_total": 0,
                "inbounds": [],
                "timestamp": time.time(),
            }

    @staticmethod
    def _is_timeout_snapshot(snapshot: Dict) -> bool:
        reason = str(snapshot.get("reason") or "").lower()
        error = str(snapshot.get("error") or "").lower()
        return "timeout" in reason or "timed out" in error or "read timed out" in error

    async def _broadcast_delta(self, key: str, snapshot: Dict, *, previous: Optional[Dict] = None):
        if not getattr(self.ws_manager, "active_connections", None):
            return
        if not hasattr(self.ws_manager, "broadcast"):
            return

        delta = {"node": key, "snapshot": snapshot}
        delta_fields = {}
        if isinstance(previous, dict):
            for field in ("available", "xray_running", "cpu", "online_clients", "traffic_total", "reason", "error"):
                old_v = previous.get(field)
                new_v = snapshot.get(field)
                if old_v != new_v:
                    delta_fields[field] = {"old": old_v, "new": new_v}
            delta["changes"] = delta_fields
        else:
            delta["changes"] = {
                "available": {"old": None, "new": snapshot.get("available")},
                "online_clients": {"old": None, "new": snapshot.get("online_clients")},
                "traffic_total": {"old": None, "new": snapshot.get("traffic_total")},
            }
            delta_fields = delta["changes"]

        try:
            push_payload = build_snapshot_push_payload(key=key, snapshot=snapshot, changes=delta_fields)
            await self.ws_manager.broadcast(
                {"type": "snapshot_delta", "data": delta, "timestamp": time.time()},
                channel="snapshot_delta",
            )

            await self.ws_manager.broadcast_server_status(
                {
                    "node": key,
                    "node_id": snapshot.get("node_id"),
                    "available": snapshot.get("available"),
                    "status": snapshot.get("status"),
                    "reason": snapshot.get("reason"),
                    "cpu": snapshot.get("cpu"),
                    "xray_running": snapshot.get("xray_running"),
                    "_delta": bool(delta_fields),
                    "changes": delta_fields,
                }
            )

            await self.ws_manager.broadcast_client_update(
                {
                    **push_payload,
                    "_delta": bool(delta_fields),
                    "count": len(push_payload["clients"]),
                }
            )

            await self.ws_manager.broadcast_inbound_update(
                {
                    **push_payload,
                    "_delta": bool(delta_fields),
                    "count": len(push_payload["inbounds"]),
                }
            )

            await self.ws_manager.broadcast_traffic_update(
                {
                    "source": "snapshot_collector",
                    "action": "snapshot",
                    "node": key,
                    "node_id": snapshot.get("node_id"),
                    "traffic_total": snapshot.get("traffic_total", 0),
                    "online_clients": snapshot.get("online_clients", 0),
                    "_delta": bool(delta_fields),
                    "changes": {
                        field: delta_fields[field]
                        for field in ("traffic_total", "online_clients")
                        if field in delta_fields
                    },
                }
            )
        except Exception as exc:
            logger.warning(f"Collector websocket broadcast failed for {key}: {exc}")
