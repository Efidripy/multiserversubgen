"""Monitoring module."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue
    from core.module_registry import ModuleRegistry

from .health_checks import HealthCheckService


class MonitoringModule(BaseModule):
    """Aggregates health checks from all modules and exposes the
    ``/api/v1/monitoring/health`` endpoint.
    """

    name = "monitoring"
    version = "1.0.0"
    dependencies = []

    def __init__(self) -> None:
        super().__init__()
        self._health_service: Optional[HealthCheckService] = None
        self._registry: Optional["ModuleRegistry"] = None

    async def initialize(self, container: "Container") -> None:
        registry = container.resolve_optional("module_registry")
        if registry is not None:
            self._health_service = HealthCheckService(registry)
        self.logger.info("MonitoringModule initialized")

    async def start(self) -> None:
        self.logger.info("MonitoringModule started")

    async def stop(self) -> None:
        self.logger.info("MonitoringModule stopped")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            state=HealthState.HEALTHY,
            message="Monitoring module operational",
        )

    def register_routes(self, app: "FastAPI") -> None:
        if self._health_service:
            from .routes import build_monitoring_router
            app.include_router(build_monitoring_router(self._health_service))
            self.logger.debug("MonitoringModule: routes registered")

    def register_events(self, event_bus: "EventBus") -> None:
        pass

    def register_jobs(self, job_queue: "JobQueue") -> None:
        pass
