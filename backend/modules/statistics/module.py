"""Statistics module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue

from .service import StatisticsService
from .collectors.traffic import TrafficCollector
from .collectors.performance import PerformanceCollector
from .collectors.availability import AvailabilityCollector


class StatisticsModule(BaseModule):
    """Extensible statistics collection module.

    Uses a plugin-based collector system: new metric types are added by
    registering a :class:`~modules.statistics.collectors.base.BaseCollector`
    subclass.

    Built-in collectors: ``traffic``, ``performance``, ``availability``.
    """

    name = "statistics"
    version = "1.0.0"
    dependencies = ["nodes"]

    def __init__(self) -> None:
        super().__init__()
        self.service: Optional[StatisticsService] = None

    async def initialize(self, container: "Container") -> None:
        from core.config import get_settings

        settings = get_settings()
        self.service = StatisticsService(settings.db_path)

        # Register built-in collectors
        snapshot_collector = container.resolve_optional("snapshot_collector")
        snapshot_provider = (
            snapshot_collector.latest_snapshot if snapshot_collector else None
        )

        self.service.register_collector(TrafficCollector(snapshot_provider))
        self.service.register_collector(PerformanceCollector(snapshot_provider))
        self.service.register_collector(AvailabilityCollector(snapshot_provider))

        container.register_instance("statistics_service", self.service)
        self.logger.info("StatisticsModule initialized with %d collectors",
                         len(self.service.list_collectors()))

    async def start(self) -> None:
        self.logger.info("StatisticsModule started")

    async def stop(self) -> None:
        self.logger.info("StatisticsModule stopped")

    async def health_check(self) -> HealthStatus:
        if self.service is None:
            return HealthStatus(state=HealthState.UNKNOWN, message="Not initialized")
        return HealthStatus(
            state=HealthState.HEALTHY,
            message="Statistics module operational",
            details={"collectors": self.service.list_collectors()},
        )

    def register_routes(self, app: "FastAPI") -> None:
        from .routes import build_statistics_router

        if self.service:
            app.include_router(build_statistics_router(self.service))
            self.logger.debug("StatisticsModule: routes registered")

    def register_events(self, event_bus: "EventBus") -> None:
        self._event_bus = event_bus
        # Subscribe to poll.completed to trigger stats collection
        from modules.polling.events import POLL_COMPLETED

        async def on_poll_completed(data: dict) -> None:
            # Emit stats.collected for audit / downstream consumers
            await event_bus.emit("stats.collected", data)

        event_bus.subscribe(POLL_COMPLETED, on_poll_completed)

    def register_jobs(self, job_queue: "JobQueue") -> None:
        pass
