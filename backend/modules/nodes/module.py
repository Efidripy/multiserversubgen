"""Node management module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue

from .service import NodesService


class NodesModule(BaseModule):
    """Manages VPN node CRUD operations and fires domain events."""

    name = "nodes"
    version = "1.0.0"
    dependencies = []

    def __init__(self) -> None:
        super().__init__()
        self.service: NodesService
        self._event_bus: "EventBus"

    async def initialize(self, container: "Container") -> None:
        from core.config import get_settings

        settings = get_settings()
        from crypto import encrypt, decrypt  # type: ignore[import-untyped]

        self.service = NodesService(
            settings.db_path,
            encrypt_func=encrypt,
            decrypt_func=decrypt,
        )
        container.register_instance("nodes_service", self.service)
        self.logger.info("NodesModule initialised")

    async def start(self) -> None:
        self.logger.info("NodesModule started")

    async def stop(self) -> None:
        self.logger.info("NodesModule stopped")

    async def health_check(self) -> HealthStatus:
        try:
            nodes = self.service.list_nodes()
            return HealthStatus(
                state=HealthState.HEALTHY,
                message=f"Nodes module operational ({len(nodes)} nodes)",
                details={"node_count": len(nodes)},
            )
        except Exception as exc:
            return HealthStatus(
                state=HealthState.UNHEALTHY,
                message=str(exc),
            )

    def register_routes(self, app: "FastAPI") -> None:
        from .routes import build_nodes_router

        app.include_router(
            build_nodes_router(self.service, event_bus=self._event_bus)
        )
        self.logger.debug("NodesModule: routes registered")

    def register_events(self, event_bus: "EventBus") -> None:
        self._event_bus = event_bus

    def register_jobs(self, job_queue: "JobQueue") -> None:
        pass
