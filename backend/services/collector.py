import asyncio
import json
import logging
import time
from typing import Callable, Dict, List, Optional


logger = logging.getLogger("sub_manager")


class SnapshotCollector:
    """Background collector with adaptive per-node polling and delta broadcasting."""

    def __init__(
        self,
        *,
        fetch_nodes: Callable[[], List[Dict]],
        xui_monitor,
        ws_manager,
        on_snapshot: Optional[Callable[[Dict], None]] = None,
        base_interval_sec: int = 5,
        max_interval_sec: int = 60,
        min_interval_sec: int = 3,
        max_parallel_polls: int = 8,
    ):
        self.fetch_nodes = fetch_nodes
        self.xui_monitor = xui_monitor
        self.ws_manager = ws_manager
        self.base_interval_sec = max(1, base_interval_sec)
        self.max_interval_sec = max(self.base_interval_sec, max_interval_sec)
        self.min_interval_sec = max(1, min_interval_sec)
        self.max_parallel_polls = max(1, max_parallel_polls)
        self.on_snapshot = on_snapshot

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._lock = asyncio.Lock()
        self._node_state: Dict[str, Dict] = {}
        self._latest = {"timestamp": None, "nodes": {}}

    def latest_snapshot(self) -> Dict:
        nodes = list(self._latest["nodes"].values())
        nodes.sort(key=lambda x: x.get("name", ""))
        return {"timestamp": self._latest["timestamp"], "nodes": nodes, "count": len(nodes)}

    def is_running(self) -> bool:
        return self._running

    async def start(self):
        if self._running:
            return
        self._running = True
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
        sem = asyncio.Semaphore(self.max_parallel_polls)
        while self._running:
            try:
                nodes = await asyncio.to_thread(self.fetch_nodes)
                now = time.time()
                active_names = {str(n.get("name", n.get("id", ""))) for n in nodes}

                # Cleanup state for removed nodes.
                for stale in list(self._node_state.keys()):
                    if stale not in active_names:
                        self._node_state.pop(stale, None)
                        self._latest["nodes"].pop(stale, None)

                tasks = []
                for node in nodes:
                    key = str(node.get("name", node.get("id", "")))
                    state = self._node_state.setdefault(
                        key,
                        {
                            "next_poll": 0.0,
                            "interval": float(self.base_interval_sec),
                            "failures": 0,
                            "stable_cycles": 0,
                            "last_hash": "",
                        },
                    )
                    if now >= state["next_poll"]:
                        tasks.append(self._poll_node(node, key, sem))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as exc:
                logger.error(f"Collector loop error: {exc}")

            await asyncio.sleep(1)

    async def _poll_node(self, node: Dict, key: str, sem: asyncio.Semaphore):
        async with sem:
            started = time.time()
            snapshot = await asyncio.to_thread(self._collect_node_snapshot, node)
            elapsed = time.time() - started
            state = self._node_state[key]

            if snapshot.get("available"):
                curr_hash = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
                changed = curr_hash != state["last_hash"]
                if changed:
                    state["stable_cycles"] = 0
                    await self._broadcast_delta(key, snapshot)
                else:
                    state["stable_cycles"] += 1

                state["last_hash"] = curr_hash
                state["failures"] = 0

                # Adaptive interval: stable nodes can be polled less frequently.
                stable_boost = min(4, 1 + state["stable_cycles"] // 3)
                interval = min(self.max_interval_sec, max(self.min_interval_sec, self.base_interval_sec * stable_boost))
                state["interval"] = float(interval)
            else:
                state["failures"] += 1
                backoff = self.base_interval_sec * (2 ** min(state["failures"], 4))
                state["interval"] = float(min(self.max_interval_sec, backoff))
                state["stable_cycles"] = 0

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

    def _collect_node_snapshot(self, node: Dict) -> Dict:
        name = node.get("name", "unknown")
        try:
            status = self.xui_monitor.get_server_status(node)
            online = self.xui_monitor.get_online_clients(node)
            traffic = self.xui_monitor.get_traffic(node)

            available = bool(status.get("available"))
            traffic_items = traffic.get("traffic", []) if isinstance(traffic, dict) else []
            total_traffic = sum((item.get("total", 0) or 0) for item in traffic_items if isinstance(item, dict))

            return {
                "name": name,
                "node_id": node.get("id"),
                "available": available,
                "xray_running": ((status.get("xray") or {}).get("running", False) if isinstance(status, dict) else False),
                "cpu": ((status.get("system") or {}).get("cpu", 0) if isinstance(status, dict) else 0),
                "online_clients": len((online.get("online_clients") or []) if isinstance(online, dict) else []),
                "traffic_total": total_traffic,
                "timestamp": time.time(),
            }
        except Exception as exc:
            logger.warning(f"Collector failed for node {name}: {exc}")
            return {
                "name": name,
                "node_id": node.get("id"),
                "available": False,
                "xray_running": False,
                "cpu": 0,
                "online_clients": 0,
                "traffic_total": 0,
                "timestamp": time.time(),
                "error": str(exc),
            }

    async def _broadcast_delta(self, key: str, snapshot: Dict):
        previous = self._latest["nodes"].get(key)
        delta = {"node": key, "snapshot": snapshot}
        if isinstance(previous, dict):
            delta_fields = {}
            for field in ("available", "xray_running", "cpu", "online_clients", "traffic_total"):
                old_v = previous.get(field)
                new_v = snapshot.get(field)
                if old_v != new_v:
                    delta_fields[field] = {"old": old_v, "new": new_v}
            delta["changes"] = delta_fields

        await self.ws_manager.broadcast(
            {"type": "snapshot_delta", "data": delta, "timestamp": time.time()},
            channel="snapshot_delta",
        )
