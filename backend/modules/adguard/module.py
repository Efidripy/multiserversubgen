"""AdGuard module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue


class AdGuardModule(BaseModule):
    """Manages AdGuard Home source configuration and statistics collection.

    The actual collection logic lives in
    :class:`~services.adguard_monitor.AdGuardMonitor` (existing code).
    This module wraps it in the new modular lifecycle.
    """

    name = "adguard"
    version = "1.0.0"
    dependencies = []
    enabled: bool = True

    def __init__(self) -> None:
        super().__init__()

    async def initialize(self, container: "Container") -> None:
        self.logger.info("AdGuardModule initialized")

    async def start(self) -> None:
        self.logger.info("AdGuardModule started")

    async def stop(self) -> None:
        self.logger.info("AdGuardModule stopped")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            state=HealthState.HEALTHY,
            message="AdGuard module operational",
        )

    def register_routes(self, app: "FastAPI") -> None:
        # AdGuard endpoints are handled by main.py for backward compat.
        # Future: extract adguard routes here.
        pass

    def register_events(self, event_bus: "EventBus") -> None:
        pass

    def register_jobs(self, job_queue: "JobQueue") -> None:
        pass
