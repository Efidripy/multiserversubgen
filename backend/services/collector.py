import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

from services.db_bootstrap import connect
from core.lifecycle_work import LifecycleWorkAdmissionClosed
from services.snapshot_push import build_snapshot_push_payload
from services.system_clients import normalize_email, system_client_emails_from_inbounds
from services.xray_compatibility import summarize_node_inbounds
from xui_session import suppress_collector_transport_diagnostics


logger = logging.getLogger("sub_manager")


# Dashboard never needs full inbound inventories or raw panel responses.  They
# remain in the collector's internal snapshot for explicit operations and
# realtime table projections, but must not be serialized for every dashboard
# page visit.
_DASHBOARD_SNAPSHOT_FIELDS = (
    "name",
    "node_id",
    "available",
    "status",
    "reason",
    "error",
    "system",
    "xray",
    "network",
    "xray_running",
    "cpu",
    "online_clients",
    "traffic_total",
    "timestamp",
    "panel_version",
    "api_version",
    "xray_compatibility",
    "poll_ms",
    "circuit_open_until",
    "cached_from_db",
    "snapshot_updated_at",
    "stale",
    "last_success_at",
    "last_attempt_at",
)

_CLIENT_PRESENCE_RETENTION_SEC = 30 * 24 * 60 * 60
_TRANSPORT_FAILURE_BACKOFF_SEC = (300.0, 600.0, 900.0)
_TRANSPORT_DIAGNOSTIC_INTERVAL_SEC = 900.0


def _online_client_emails(payload: Any) -> List[str]:
    """Normalize the already-polled 3x-ui presence list for internal reuse."""
    if not isinstance(payload, dict):
        return []
    values = payload.get("online_clients")
    if not isinstance(values, list):
        return []
    return sorted({value.strip().casefold() for value in values if isinstance(value, str) and value.strip()})


def _detect_api_version(panel_version: str) -> str:
    """Return telemetry only; endpoint capability remains the authority.

    Absence of optional ``panelVersion`` is not proof of a v2 panel: current
    3x-ui builds can omit it in a reduced status response.  Consumers must
    probe the specific documented operation before using a legacy route.
    """
    if not panel_version:
        return "unknown"
    try:
        major = int(panel_version.split(".")[0])
        return "v3" if major >= 3 else "v2"
    except (ValueError, IndexError):
        return "unknown"


class CollectorMode(Enum):
    """Collector operating modes."""
    ULTRA_IDLE = "ultra_idle"  # No activity for 24h → lower-priority cadence
    IDLE = "idle"  # No activity after idle_after → default poll every 5min
    WARMING = "warming"  # First 10min after connect → polling ramps up
    ACTIVE = "active"  # Active WebSocket session → default poll every 90s


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
        on_snapshots: Optional[Callable[[List[Dict]], None]] = None,
        base_interval_sec: int = 5,
        max_interval_sec: int = 86400,
        min_interval_sec: int = 3,
        max_parallel_polls: int = 8,
        warming_interval_1_sec: int = 30,
        warming_interval_2_sec: int = 60,
        warming_interval_3_sec: int = 120,
        active_interval_sec: int = 90,
        idle_interval_sec: int = 300,
        ultra_idle_interval_sec: int = 86400,
        idle_after_sec: int = 900,
        ultra_idle_after_sec: int = 86400,
        poll_interval_ceiling_sec: Optional[int] = None,
        degraded_backoff_sec: int = 300,
        poll_jitter_sec: float = 3.0,
        collector_cycle_duration_metric=None,
        collector_poll_cycles_metric=None,
        collector_due_nodes_metric=None,
        sqlite_batch_rows_metric=None,
        cycle_clock: Callable[[], float] = time.perf_counter,
    ):
        self.fetch_nodes = fetch_nodes
        self.xui_monitor = xui_monitor
        self.ws_manager = ws_manager
        self.base_interval_sec = max(1, base_interval_sec)
        self.max_interval_sec = max(self.base_interval_sec, max_interval_sec)
        self.min_interval_sec = max(1, min_interval_sec)
        self.configured_max_parallel_polls = max(1, max_parallel_polls)
        # This is deliberately a fleet-wide limiter.  Do not silently replace
        # an operator's conservative production setting with a hard-coded
        # value: at 100 nodes that makes capacity planning impossible.
        self.max_parallel_polls = self.configured_max_parallel_polls
        self.semaphore = asyncio.Semaphore(self.max_parallel_polls)
        self.warming_interval_1_sec = max(3, warming_interval_1_sec)
        self.warming_interval_2_sec = max(self.warming_interval_1_sec, warming_interval_2_sec)
        self.warming_interval_3_sec = max(self.warming_interval_2_sec, warming_interval_3_sec)
        self.active_interval_sec = max(3, active_interval_sec)
        self.idle_interval_sec = max(self.active_interval_sec, idle_interval_sec)
        self.ultra_idle_interval_sec = max(self.idle_interval_sec, ultra_idle_interval_sec)
        self.idle_after_sec = max(60, idle_after_sec)
        self.ultra_idle_after_sec = max(self.idle_after_sec, ultra_idle_after_sec)
        effective_poll_interval_ceiling = (
            self.ultra_idle_interval_sec
            if poll_interval_ceiling_sec is None
            else poll_interval_ceiling_sec
        )
        self.poll_interval_ceiling_sec = max(
            30, min(self.max_interval_sec, effective_poll_interval_ceiling)
        )
        self.degraded_backoff_sec = max(180, min(300, degraded_backoff_sec))
        self.db_path = db_path
        self._collector_cycle_duration_metric = collector_cycle_duration_metric
        self._collector_poll_cycles_metric = collector_poll_cycles_metric
        self._collector_due_nodes_metric = collector_due_nodes_metric
        self._sqlite_batch_rows_metric = sqlite_batch_rows_metric
        self._cycle_clock = cycle_clock
        if on_snapshots is not None:
            self.on_snapshots = on_snapshots
        elif on_snapshot is not None:
            self.on_snapshots = lambda snapshots: [on_snapshot(snapshot) for snapshot in snapshots]
        else:
            self.on_snapshots = None
        # Ordinary due polls get a bounded, deterministic spread. Force-poll
        # remains immediate because it is an explicit operator request.
        self.poll_jitter_sec = max(0.0, min(3.0, float(poll_jitter_sec)))

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._worker_tracker = None
        self._lock = asyncio.Lock()
        self._snapshot_write_lock = asyncio.Lock()
        self._node_state: Dict[str, Dict] = {}
        self._last_transport_diagnostic_at: Dict[str, float] = {}
        self._latest = {"timestamp": None, "nodes": {}}
        # Observed presence is deliberately internal: Dashboard remains bounded
        # and never serializes client emails. Client Manager receives it through
        # a separate authenticated, snapshot-only projection.
        self._client_last_seen: Dict[str, float] = {}
        self._client_last_seen_by_node: Dict[str, Dict[str, float]] = {}
        # This mapping is replaced atomically after a completed poll. The API
        # reads it from a worker thread, so it must not iterate mutable node
        # snapshots while the collector is updating them on its event loop.
        self._client_presence = {
            "timestamp": None,
            "online_emails": (),
            "online_by_node": {},
            "node_names": {},
            "last_seen": {},
            "last_seen_by_node": {},
        }
        self._inflight_polls = 0
        self._last_cycle = {
            "started_at": None,
            "finished_at": None,
            "duration_ms": 0.0,
            "due_nodes": 0,
            "queued_nodes": 0,
            "mode": CollectorMode.IDLE.value,
            "trigger": "scheduled",
        }

        # Adaptive mode state
        self._mode = CollectorMode.IDLE
        self._last_ws_activity = 0.0
        self._mode_started_at = time.time()
        self._force_poll_event = asyncio.Event()

    @staticmethod
    def _observe_metric(metric, value: float, **labels) -> None:
        """Best-effort metrics must never alter collector behavior."""
        if metric is None:
            return
        try:
            target = metric.labels(**labels) if labels else metric
            target.observe(value)
        except Exception:
            pass

    @staticmethod
    def _increment_metric(metric, **labels) -> None:
        """Increment an optional bounded metric without changing collector outcome."""
        if metric is None:
            return
        try:
            target = metric.labels(**labels) if labels else metric
            target.inc()
        except Exception:
            pass

    @staticmethod
    def _node_key(node: Dict) -> str:
        """Return the internal collector key without relying on display names.

        Node names are operator-facing labels and may legitimately be duplicated
        or renamed. Poll state and snapshots must instead remain bound to the
        database identity so one node cannot replace another in memory.
        """
        node_id = node.get("id")
        if node_id is not None and str(node_id).strip():
            return f"id:{node_id}"
        return f"name:{str(node.get('name') or '').strip()}"

    def latest_snapshot(self) -> Dict:
        nodes = list(self._latest["nodes"].values())
        nodes.sort(key=lambda x: x.get("name", ""))
        return {
            "timestamp": self._latest["timestamp"],
            "nodes": nodes,
            "count": len(nodes),
            "mode": self._mode.value,
        }

    def latest_dashboard_snapshot(self) -> Dict:
        """Return the bounded, operator-safe projection used by Dashboard.

        The collector internally retains full inbounds so explicit client and
        inbound workflows can build their own projections.  Sending those
        records with every Dashboard navigation turns an O(nodes) status view
        into O(nodes * inbounds * clients) network and JSON work.
        """
        nodes = [
            {field: snapshot[field] for field in _DASHBOARD_SNAPSHOT_FIELDS if field in snapshot}
            for snapshot in self._latest["nodes"].values()
            if isinstance(snapshot, dict)
        ]
        nodes.sort(key=lambda item: str(item.get("name") or "").casefold())
        return {
            "timestamp": self._latest["timestamp"],
            "nodes": nodes,
            "count": len(nodes),
            "mode": self._mode.value,
            "projection": "dashboard-v1",
        }

    def latest_client_presence(self) -> Dict:
        """Return a no-RPC projection derived from already completed polls."""
        presence = self._client_presence
        return {
            "projection": "client-presence-v1",
            "timestamp": presence["timestamp"],
            "online_emails": list(presence["online_emails"]),
            "online_by_node": {
                node_id: list(emails)
                for node_id, emails in presence["online_by_node"].items()
            },
            "node_names": dict(presence["node_names"]),
            "last_seen": dict(presence["last_seen"]),
            "last_seen_by_node": {
                node_id: dict(last_seen)
                for node_id, last_seen in presence["last_seen_by_node"].items()
            },
        }

    def _refresh_client_presence_projection(self) -> None:
        """Publish an immutable presence view after collector-owned mutations."""
        online_emails = {
            email
            for snapshot in self._latest["nodes"].values()
            if isinstance(snapshot, dict)
            for email in snapshot.get("online_client_emails") or []
            if isinstance(email, str) and email
        }
        online_by_node = {
            str(snapshot["node_id"]): tuple(sorted({
                email
                for email in snapshot.get("online_client_emails") or []
                if isinstance(email, str) and email
            }))
            for snapshot in self._latest["nodes"].values()
            if isinstance(snapshot, dict) and snapshot.get("node_id") is not None
        }
        node_names = {
            str(snapshot["node_id"]): str(snapshot.get("name") or snapshot["node_id"])
            for snapshot in self._latest["nodes"].values()
            if isinstance(snapshot, dict) and snapshot.get("node_id") is not None
        }
        self._client_presence = {
            "timestamp": self._latest["timestamp"],
            "online_emails": tuple(sorted(online_emails)),
            "online_by_node": online_by_node,
            "node_names": node_names,
            "last_seen": dict(self._client_last_seen),
            "last_seen_by_node": {
                node_id: dict(last_seen)
                for node_id, last_seen in self._client_last_seen_by_node.items()
            },
        }

    def runtime_status(self) -> Dict:
        """Small operational receipt for sizing a collector before fleet growth."""
        return {
            "mode": self._mode.value,
            "configured_max_parallel_polls": self.configured_max_parallel_polls,
            "max_parallel_polls": self.max_parallel_polls,
            "poll_jitter_sec": self.poll_jitter_sec,
            "inflight_polls": self._inflight_polls,
            "last_cycle": dict(self._last_cycle),
            "snapshot_nodes": len(self._latest["nodes"]),
        }

    async def load_persisted_snapshots(self) -> int:
        if not self.db_path:
            return 0
        rows = await self._run_blocking(
            "collector.load_persisted_snapshots", self._load_persisted_snapshot_rows
        )
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
            loaded.append((self._node_key({"id": node_id, "name": node_name}), snapshot, ts))
        return loaded

    async def _persist_snapshot(self, snapshot: Dict) -> None:
        """Compatibility helper for one explicit snapshot persistence call."""
        await self._persist_snapshots([snapshot])

    async def _persist_snapshots(self, snapshots: List[Dict]) -> None:
        """Persist completed cycle snapshots in one SQLite transaction."""
        if not self.db_path:
            return
        valid_snapshots = [snapshot for snapshot in snapshots if isinstance(snapshot, dict) and snapshot.get("node_id") is not None]
        if not valid_snapshots:
            return
        try:
            async with self._snapshot_write_lock:
                await self._run_blocking(
                    "collector.persist_snapshots", self._upsert_snapshot_rows, valid_snapshots
                )
        except Exception as exc:
            logger.warning("Failed to persist %d collector snapshots: %s", len(valid_snapshots), exc)

    def _upsert_snapshot_row(self, snapshot: Dict) -> None:
        self._upsert_snapshot_rows([snapshot])

    def _upsert_snapshot_rows(self, snapshots: List[Dict]) -> None:
        if not self.db_path:
            return
        rows = []
        for snapshot in snapshots:
            try:
                node_id_int = int(snapshot.get("node_id"))
            except (TypeError, ValueError):
                continue
            payload = dict(snapshot)
            payload.pop("cached_from_db", None)
            payload.pop("snapshot_updated_at", None)
            rows.append((node_id_int, json.dumps(payload, ensure_ascii=False, sort_keys=True), 1 if bool(snapshot.get("available")) else 0))
        if not rows:
            return

        with connect(self.db_path) as conn:
            self._ensure_snapshot_table(conn)
            conn.executemany(
                """
                INSERT INTO node_snapshots (node_id, status_data, is_online, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(node_id) DO UPDATE SET
                    status_data = excluded.status_data,
                    is_online = excluded.is_online,
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )
            conn.commit()
        self._observe_metric(
            self._sqlite_batch_rows_metric,
            len(rows),
            operation="collector_snapshot_upsert",
        )

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

    @staticmethod
    def _status_object(status: Dict, field: str) -> Dict[str, Any]:
        value = status.get(field) if isinstance(status, dict) else None
        return value if isinstance(value, dict) else {}

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

    async def _run_blocking(self, label: str, function, *args):
        if self._worker_tracker is not None:
            return await self._worker_tracker.run(label, function, *args)
        return await asyncio.to_thread(function, *args)

    async def start(self, worker_tracker=None):
        if self._running:
            return
        self._worker_tracker = worker_tracker
        await self.load_persisted_snapshots()
        self._running = True
        self._last_ws_activity = time.time()
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        self._force_poll_event.set()
        if self._task:
            if self._worker_tracker is None:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            else:
                await self._task
            self._task = None

    async def _run(self):
        while self._running and (
            self._worker_tracker is None or self._worker_tracker.accepting
        ):
            cycle_started = time.time()
            cycle_started_monotonic = self._cycle_clock()
            try:
                self._update_mode_based_on_activity()
                current_interval = self._get_current_interval()
                cycle_mode = self._mode.value

                nodes = await self._run_blocking("collector.fetch_nodes", self.fetch_nodes)
                now = time.time()
                active_node_keys = {self._node_key(node) for node in nodes}

                # Cleanup state for removed nodes.
                for stale in list(self._node_state.keys()):
                    if stale not in active_node_keys:
                        self._node_state.pop(stale, None)
                        self._last_transport_diagnostic_at.pop(stale, None)
                        self._latest["nodes"].pop(stale, None)
                        self._refresh_client_presence_projection()

                due_nodes = []
                force_poll = self._force_poll_event.is_set()

                for node in nodes:
                    key = self._node_key(node)
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
                        due_nodes.append((node, key))

                completed_snapshots = await self._poll_due_nodes(due_nodes, force_poll=force_poll)
                if completed_snapshots:
                    # Keep transport degradation process-local: the last
                    # durable success remains the source after a restart.
                    durable_snapshots = [
                        snapshot for snapshot in completed_snapshots
                        if not snapshot.get("_transient_transport_failure")
                    ]
                    if durable_snapshots:
                        await self._persist_snapshots(durable_snapshots)
                        await self._notify_completed_snapshots(durable_snapshots)
                    for snapshot in completed_snapshots:
                        snapshot.pop("_transient_transport_failure", None)

                self._last_cycle = {
                    "started_at": cycle_started,
                    "finished_at": time.time(),
                    "duration_ms": round((time.time() - cycle_started) * 1000, 2),
                    "due_nodes": len(due_nodes),
                    "queued_nodes": max(0, len(due_nodes) - self.max_parallel_polls),
                    "mode": cycle_mode,
                    "trigger": "force_poll" if force_poll else "scheduled",
                }

                if due_nodes:
                    metric_labels = {
                        "mode": cycle_mode,
                        "trigger": "force_poll" if force_poll else "scheduled",
                    }
                    self._observe_metric(
                        self._collector_cycle_duration_metric,
                        max(0.0, self._cycle_clock() - cycle_started_monotonic),
                    )
                    self._increment_metric(
                        self._collector_poll_cycles_metric, **metric_labels
                    )
                    self._observe_metric(
                        self._collector_due_nodes_metric,
                        len(due_nodes),
                        **metric_labels,
                    )

                if force_poll:
                    self._force_poll_event.clear()
                    logger.info(f"Force poll completed: {len(due_nodes)} nodes polled")

            except LifecycleWorkAdmissionClosed:
                break
            except Exception as exc:
                logger.error(f"Collector loop error: {exc}")

            # Adaptive sleep: longer in idle modes; force_poll_event provides early wake-up.
            sleep_time = min(10.0, self.poll_interval_ceiling_sec / 10, self._get_current_interval() / 10)
            try:
                await asyncio.wait_for(self._force_poll_event.wait(), timeout=sleep_time)
            except asyncio.TimeoutError:
                pass

    def _poll_delay_for_position(self, position: int, total: int, *, force_poll: bool) -> float:
        """Return a deterministic, bounded ordinary-cycle start delay."""
        if force_poll or total <= 1 or self.poll_jitter_sec <= 0:
            return 0.0
        return self.poll_jitter_sec * position / (total - 1)

    async def _poll_due_nodes(self, due_nodes: List[tuple[Dict, str]], *, force_poll: bool) -> List[Dict]:
        """Poll due nodes with bounded spread and retain all completed states."""
        ordered = sorted(due_nodes, key=lambda item: item[1])
        total = len(ordered)
        tasks = [
            self._poll_node_after_delay(node, key, delay=self._poll_delay_for_position(index, total, force_poll=force_poll))
            for index, (node, key) in enumerate(ordered)
        ]
        if not tasks:
            return []
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [result for result in results if isinstance(result, dict)]

    async def _poll_node_after_delay(self, node: Dict, key: str, *, delay: float) -> Dict:
        if self._worker_tracker is not None and not self._worker_tracker.accepting:
            return None
        if delay > 0:
            await asyncio.sleep(delay)
        if self._worker_tracker is not None and not self._worker_tracker.accepting:
            return None
        return await self._poll_node(node, key)

    async def _notify_completed_snapshots(self, snapshots: List[Dict]) -> None:
        if self.on_snapshots is None:
            return
        try:
            await self._run_blocking(
                "collector.on_snapshots", self.on_snapshots, snapshots
            )
        except Exception as exc:
            logger.warning("Collector completed-snapshot callback failed: %s", exc)

    async def _poll_node(self, node: Dict, key: str, sem: Optional[asyncio.Semaphore] = None):
        self._inflight_polls += 1
        try:
            async with self.semaphore:
                started = time.time()
                snapshot = await self._run_blocking(
                    "collector.poll_node", self._collect_node_snapshot, node
                )
        finally:
            self._inflight_polls = max(0, self._inflight_polls - 1)
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
            prior_transport_failures = int(state.get("failures", 0))
            recovered_transport = bool(state.get("transport_degraded"))
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
            state["transport_degraded"] = False
            state["transport_failures_since_log"] = 0
            state["last_success_snapshot"] = dict(snapshot)
            self._last_transport_diagnostic_at.pop(key, None)
            if recovered_transport:
                logger.info(
                    "Collector transport recovered after %d failed attempt(s)",
                    prior_transport_failures,
                )

            # Adaptive interval per node based on current mode and stability.
            current_interval = self._get_current_interval()
            stable_boost = min(4, 1 + state["stable_cycles"] // 3)
            # Active and idle modes keep their configured freshness/cadence
            # bounds even after stable snapshots. Ultra-idle remains bounded by
            # its own configured interval or an explicit global ceiling.
            interval_ceiling = self.poll_interval_ceiling_sec
            if self._mode == CollectorMode.ACTIVE:
                interval_ceiling = min(interval_ceiling, self.active_interval_sec)
            elif self._mode == CollectorMode.IDLE:
                interval_ceiling = min(interval_ceiling, self.idle_interval_sec)
            interval = min(
                self.max_interval_sec,
                interval_ceiling,
                max(self.min_interval_sec, current_interval * stable_boost),
            )
            state["interval"] = float(interval)
        else:
            state["failures"] += 1
            if self._is_timeout_snapshot(snapshot):
                backoff = self._transport_backoff_for_failures(state["failures"])
                circuit_until = time.time() + backoff
                state["interval"] = backoff
                state["circuit_until"] = circuit_until
                state["transport_degraded"] = True
                snapshot = self._stale_snapshot_from_failure(state, previous, snapshot)
                snapshot["_transient_transport_failure"] = True
                snapshot["circuit_open_until"] = circuit_until
                snapshot["reason"] = "timeout"
                snapshot["status"] = "offline"
                self._log_transport_failure_once(key, state, backoff)
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

        async with self._lock:
            self._latest["timestamp"] = time.time()
            self._latest["nodes"][key] = snapshot
            observed_at = float(snapshot.get("timestamp") or self._latest["timestamp"])
            online_client_emails = snapshot.get("online_client_emails") or []
            for email in online_client_emails:
                self._client_last_seen[email] = observed_at
            node_id = snapshot.get("node_id")
            if node_id is not None:
                node_last_seen = self._client_last_seen_by_node.setdefault(str(node_id), {})
                for email in online_client_emails:
                    node_last_seen[email] = observed_at
            cutoff = observed_at - _CLIENT_PRESENCE_RETENTION_SEC
            stale_emails = [email for email, seen_at in self._client_last_seen.items() if seen_at < cutoff]
            for email in stale_emails:
                del self._client_last_seen[email]
            for node_id, node_last_seen in list(self._client_last_seen_by_node.items()):
                stale_node_emails = [email for email, seen_at in node_last_seen.items() if seen_at < cutoff]
                for email in stale_node_emails:
                    del node_last_seen[email]
                if not node_last_seen:
                    del self._client_last_seen_by_node[node_id]
            self._refresh_client_presence_projection()
        if should_broadcast:
            # WebSocket consumers display the operator-facing name; the
            # database ID below remains the unambiguous machine identity.
            await self._broadcast_delta(str(snapshot.get("name") or key), snapshot, previous=previous)
        return snapshot

    @staticmethod
    def _transport_backoff_for_failures(failures: int) -> float:
        """Bound consecutive transport failures without changing fleet fan-out."""
        position = min(max(1, int(failures)), len(_TRANSPORT_FAILURE_BACKOFF_SEC)) - 1
        return _TRANSPORT_FAILURE_BACKOFF_SEC[position]

    def _log_transport_failure_once(self, key: str, state: Dict, backoff_sec: float) -> None:
        """Emit a redacted transition/periodic collector summary for one node."""
        now = time.time()
        last_logged = self._last_transport_diagnostic_at.get(key, 0.0)
        repeated = int(state.get("transport_failures_since_log", 0)) + 1
        state["transport_failures_since_log"] = repeated
        if last_logged and now - last_logged < _TRANSPORT_DIAGNOSTIC_INTERVAL_SEC:
            return
        self._last_transport_diagnostic_at[key] = now
        if last_logged:
            logger.warning(
                "Collector transport failure persists: repeated_attempts=%d retry_in_sec=%d",
                repeated,
                int(backoff_sec),
            )
        else:
            logger.warning("Collector transport unavailable; retry_in_sec=%d", int(backoff_sec))
        state["transport_failures_since_log"] = 0

    @staticmethod
    def _stale_snapshot_from_failure(state: Dict, previous: Optional[Dict], failure: Dict) -> Dict:
        """Keep the last completed snapshot visible while marking a failed attempt."""
        last_success = state.get("last_success_snapshot")
        if not isinstance(last_success, dict) and isinstance(previous, dict) and previous.get("available"):
            last_success = previous
        attempted_at = float(failure.get("timestamp") or time.time())
        if not isinstance(last_success, dict):
            failure["stale"] = False
            failure["last_attempt_at"] = attempted_at
            return failure

        stale = dict(last_success)
        last_success_at = stale.get("timestamp")
        stale.update(
            {
                "available": False,
                "status": "offline",
                "reason": str(failure.get("reason") or "unavailable"),
                "error": "Node panel transport is unavailable",
                "stale": True,
                "last_success_at": last_success_at,
                "last_attempt_at": attempted_at,
            }
        )
        stale.pop("circuit_open_until", None)
        stale.pop("cached_from_db", None)
        stale.pop("snapshot_updated_at", None)
        return stale

    def _collect_node_snapshot(self, node: Dict) -> Dict:
        with suppress_collector_transport_diagnostics():
            return self._collect_node_snapshot_unfiltered(node)

    def _collect_node_snapshot_unfiltered(self, node: Dict) -> Dict:
        name = node.get("name", "unknown")
        try:
            status = self.xui_monitor.get_server_status(node)
            system_status = self._status_object(status, "system")
            xray_status = self._status_object(status, "xray")
            network_status = self._status_object(status, "network")
            if not bool(status.get("available")):
                return {
                    "name": name,
                    "node_id": node.get("id"),
                    "available": False,
                    "status": status.get("status", "offline"),
                    "reason": status.get("reason", "unavailable"),
                    "error": status.get("error", "Failed to connect"),
                    "server_status": status,
                    "system": system_status,
                    "xray": xray_status,
                    "network": network_status,
                    "panel_version": status.get("panel_version", "") if isinstance(status, dict) else "",
                    "xray_running": False,
                    "cpu": 0,
                    "online_clients": 0,
                    "traffic_total": 0,
                    "inbounds": [],
                    "timestamp": time.time(),
                }
            inbounds_result = self.xui_monitor.get_inbounds(node)
            available = bool(status.get("available"))
            inbounds = (
                inbounds_result.get("inbounds", [])
                if isinstance(inbounds_result, dict) and inbounds_result.get("available")
                else []
            )
            system_client_emails = system_client_emails_from_inbounds(inbounds)
            online = self.xui_monitor.get_online_clients(node)
            online_emails = [
                email
                for email in _online_client_emails(online)
                if normalize_email(email) not in system_client_emails
            ]
            total_traffic = sum(
                (inbound.get("up", 0) or 0) + (inbound.get("down", 0) or 0)
                for inbound in inbounds
                if isinstance(inbound, dict)
            )
            xray_compatibility = summarize_node_inbounds(inbounds)

            panel_version = status.get("panel_version", "") if isinstance(status, dict) else ""
            api_version = _detect_api_version(panel_version)

            return {
                "name": name,
                "node_id": node.get("id"),
                "available": available,
                "status": "online" if available else "offline",
                "reason": status.get("reason") or ("ok" if available else "unknown"),
                "error": status.get("error", "") if isinstance(status, dict) else "",
                "system": system_status,
                "xray": xray_status,
                "network": network_status,
                "xray_running": (xray_status.get("running", False) if isinstance(status, dict) else False),
                "cpu": (system_status.get("cpu", 0) if isinstance(status, dict) else 0),
                "online_clients": len(online_emails),
                "online_client_emails": online_emails,
                "system_client_emails": sorted(system_client_emails),
                "traffic_total": total_traffic,
                "timestamp": time.time(),
                "panel_version": panel_version,
                "api_version": api_version,
                "server_status": status,
                "inbounds": inbounds,
                "inbounds_result": inbounds_result,
                "xray_compatibility": xray_compatibility,
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
                "system": {},
                "xray": {},
                "network": {},
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
        if reason in {"timeout", "network_error", "request_failed", "connection_failed"}:
            return True
        return any(
            marker in error
            for marker in ("timed out", "timeout", "connection refused", "network is unreachable")
        )

    async def _broadcast_delta(self, key: str, snapshot: Dict, *, previous: Optional[Dict] = None):
        if not getattr(self.ws_manager, "active_connections", None):
            return
        if not hasattr(self.ws_manager, "broadcast"):
            return

        delta = {"node": key, "snapshot": snapshot}
        delta_fields = {}
        if isinstance(previous, dict):
            for field in (
                "available",
                "xray_running",
                "cpu",
                "system",
                "xray",
                "network",
                "online_clients",
                "traffic_total",
                "panel_version",
                "api_version",
                "xray_compatibility",
                "reason",
                "error",
            ):
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
                    "source": "snapshot_collector",
                    "action": "snapshot",
                    "node": key,
                    "node_id": snapshot.get("node_id"),
                    "available": snapshot.get("available"),
                    "status": snapshot.get("status"),
                    "reason": snapshot.get("reason"),
                    "error": snapshot.get("error"),
                    "cpu": snapshot.get("cpu"),
                    "system": snapshot.get("system"),
                    "xray": snapshot.get("xray"),
                    "network": snapshot.get("network"),
                    "xray_running": snapshot.get("xray_running"),
                    "panel_version": snapshot.get("panel_version"),
                    "api_version": snapshot.get("api_version"),
                    "xray_compatibility": snapshot.get("xray_compatibility"),
                    "online_clients": snapshot.get("online_clients"),
                    "traffic_total": snapshot.get("traffic_total"),
                    "poll_ms": snapshot.get("poll_ms"),
                    "timestamp": snapshot.get("timestamp"),
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
