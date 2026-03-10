"""Polling scheduler – drives periodic node polling.

The scheduler wraps the existing :class:`~services.collector.SnapshotCollector`
(or any compatible callable) and adds:

* Configurable polling interval
* EventBus integration
* Structured metrics
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .events import POLL_COMPLETED, POLL_CYCLE_COMPLETED, POLL_CYCLE_STARTED, POLL_FAILED, POLL_STARTED

logger = logging.getLogger(__name__)


class PollingScheduler:
    """Periodically polls all nodes using the injected *poll_func*.

    Args:
        poll_func: An async callable ``(node: dict) -> dict`` that returns
            a snapshot dict for a single node.
        fetch_nodes: Sync callable returning the current list of node dicts.
        interval_sec: Seconds between polling cycles.
        event_bus: Optional :class:`~core.event_bus.EventBus` for event
            emission.
        on_snapshot: Optional callback invoked after each successful poll.
    """

    def __init__(
        self,
        *,
        poll_func: Callable[[Dict], Any],
        fetch_nodes: Callable[[], List[Dict]],
        interval_sec: int = 60,
        event_bus=None,
        on_snapshot: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self._poll_func = poll_func
        self._fetch_nodes = fetch_nodes
        self._interval_sec = max(1, interval_sec)
        self._event_bus = event_bus
        self._on_snapshot = on_snapshot
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._poll_count = 0
        self._error_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "PollingScheduler: started (interval=%ds)", self._interval_sec
        )

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("PollingScheduler: stopped")

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while self._running:
            await self._poll_cycle()
            await asyncio.sleep(self._interval_sec)

    async def _poll_cycle(self) -> None:
        nodes = self._fetch_nodes()
        if not nodes:
            return

        cycle_start = time.perf_counter()
        if self._event_bus:
            await self._event_bus.emit(
                POLL_CYCLE_STARTED, {"node_count": len(nodes)}
            )

        for node in nodes:
            node_id = node.get("id")
            node_name = node.get("name", str(node_id))
            if self._event_bus:
                await self._event_bus.emit(POLL_STARTED, {"node_id": node_id})
            try:
                snapshot = await self._poll_func(node)
                self._poll_count += 1
                if self._on_snapshot:
                    self._on_snapshot(snapshot)
                if self._event_bus:
                    await self._event_bus.emit(
                        POLL_COMPLETED,
                        {
                            "node_id": node_id,
                            "node_name": node_name,
                            "poll_ms": snapshot.get("poll_ms", 0),
                        },
                    )
            except Exception as exc:
                self._error_count += 1
                logger.warning("PollingScheduler: node %s failed: %s", node_id, exc)
                if self._event_bus:
                    await self._event_bus.emit(
                        POLL_FAILED,
                        {"node_id": node_id, "error": str(exc)},
                    )

        elapsed_ms = (time.perf_counter() - cycle_start) * 1000
        if self._event_bus:
            await self._event_bus.emit(
                POLL_CYCLE_COMPLETED,
                {
                    "node_count": len(nodes),
                    "elapsed_ms": elapsed_ms,
                },
            )
        logger.debug(
            "PollingScheduler: cycle complete (%d nodes, %.1fms)", len(nodes), elapsed_ms
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict:
        return {
            "running": self._running,
            "interval_sec": self._interval_sec,
            "poll_count": self._poll_count,
            "error_count": self._error_count,
        }
