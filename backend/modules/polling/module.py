"""Polling module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue

from .service import PollingService


class PollingModule(BaseModule):
    """Manages the background polling of VPN nodes.

    Depends on the ``nodes`` module being available via the DI container.
    Emits ``poll.started``, ``poll.completed``, and ``poll.failed`` events
    for each polling cycle.
    """

    name = "polling"
    version = "1.0.0"
    dependencies = ["nodes"]

    def __init__(self) -> None:
        super().__init__()
        self.service: Optional[PollingService] = None

    async def initialize(self, container: "Container") -> None:
        # The SnapshotCollector is created and managed by main.py for backward
        # compatibility.  If a 'snapshot_collector' has been registered in the
        # container we wrap it; otherwise we no-op (graceful degradation).
        collector = container.resolve_optional("snapshot_collector")
        if collector is not None:
            self.service = PollingService(collector)
            container.register_instance("polling_service", self.service)
        self.logger.info("PollingModule initialized")

    async def start(self) -> None:
        if self.service is not None:
            await self.service.start()
        self.logger.info("PollingModule started")

    async def stop(self) -> None:
        if self.service is not None:
            await self.service.stop()
        self.logger.info("PollingModule stopped")

    async def health_check(self) -> HealthStatus:
        if self.service is None:
            return HealthStatus(
                state=HealthState.UNKNOWN,
                message="Polling service not initialized",
            )
        running = self.service.is_running()
        return HealthStatus(
            state=HealthState.HEALTHY if running else HealthState.DEGRADED,
            message=f"Polling {'running' if running else 'stopped'} "
                    f"(mode={self.service.get_mode()})",
            details=self.service.status(),
        )

    def register_routes(self, app: "FastAPI") -> None:
        pass  # Collector status endpoint is handled by observability router

    def register_events(self, event_bus: "EventBus") -> None:
        self._event_bus = event_bus

    def register_jobs(self, job_queue: "JobQueue") -> None:
        pass
