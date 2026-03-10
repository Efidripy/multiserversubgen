"""Polling service – wraps the SnapshotCollector for use within the module."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PollingService:
    """Facade over the existing :class:`~services.collector.SnapshotCollector`.

    Delegates lifecycle management to the collector while exposing a clean
    interface that the :class:`~modules.polling.module.PollingModule` can
    use.

    Args:
        snapshot_collector: The underlying SnapshotCollector instance.
    """

    def __init__(self, snapshot_collector) -> None:
        self._collector = snapshot_collector

    async def start(self) -> None:
        await self._collector.start()

    async def stop(self) -> None:
        await self._collector.stop()

    def is_running(self) -> bool:
        return self._collector.is_running()

    def get_mode(self) -> str:
        return self._collector.get_mode()

    def latest_snapshot(self) -> Dict:
        return self._collector.latest_snapshot()

    def status(self) -> Dict:
        return {
            "running": self.is_running(),
            "mode": self.get_mode(),
        }
