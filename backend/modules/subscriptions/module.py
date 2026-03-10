"""Subscriptions module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base_module import BaseModule, HealthState, HealthStatus

if TYPE_CHECKING:
    from fastapi import FastAPI

    from core.container import Container
    from core.event_bus import EventBus
    from core.job_queue import JobQueue


class SubscriptionsModule(BaseModule):
    """Manages subscription groups and client subscription endpoints."""

    name = "subscriptions"
    version = "1.0.0"
    dependencies = ["nodes"]

    def __init__(self) -> None:
        super().__init__()

    async def initialize(self, container: "Container") -> None:
        self.logger.info("SubscriptionsModule initialised")

    async def start(self) -> None:
        self.logger.info("SubscriptionsModule started")

    async def stop(self) -> None:
        self.logger.info("SubscriptionsModule stopped")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            state=HealthState.HEALTHY,
            message="Subscriptions module operational",
        )

    def register_routes(self, app: "FastAPI") -> None:
        # Subscription endpoints are handled by main.py for backward compat.
        # Future: extract them here.
        pass

    def register_events(self, event_bus: "EventBus") -> None:
        pass

    def register_jobs(self, job_queue: "JobQueue") -> None:
        @job_queue.schedule(cron="*/30 * * * *", name="subscriptions.check_expiry")
        async def check_expiry():
            """Periodically check for expired subscriptions."""
            # Implementation delegates to main.py for backward compat.
            pass
