"""Authentication module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue

from .service import AuthService


class AuthModule(BaseModule):
    """Handles authentication, authorisation and MFA.

    Depends on no other modules.  Registers the ``/api/v1/auth/*``
    endpoints and fires ``user.logged_in`` / ``user.logged_out`` events.
    """

    name = "auth"
    version = "1.0.0"
    dependencies = []

    def __init__(self) -> None:
        super().__init__()
        self.service: AuthService

    async def initialize(self, container: "Container") -> None:
        from core.config import get_settings

        settings = get_settings()
        self.service = AuthService(
            role_viewers=settings.role_viewers,
            role_operators=settings.role_operators,
            mfa_totp_enabled=settings.mfa_totp_enabled,
        )
        container.register_instance("auth_service", self.service)
        self.logger.info("AuthModule initialized")

    async def start(self) -> None:
        self.logger.info("AuthModule started")

    async def stop(self) -> None:
        self.logger.info("AuthModule stopped")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            state=HealthState.HEALTHY,
            message="Auth module is operational",
        )

    def register_routes(self, app: "FastAPI") -> None:
        from .routes import build_auth_router

        app.include_router(build_auth_router(self.service))
        self.logger.debug("AuthModule: routes registered")

    def register_events(self, event_bus: "EventBus") -> None:
        # The auth module fires events but doesn't subscribe to any
        self._event_bus = event_bus

    def register_jobs(self, job_queue: "JobQueue") -> None:
        pass  # No background jobs needed
