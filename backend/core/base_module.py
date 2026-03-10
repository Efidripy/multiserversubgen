"""Base module interface for the modular architecture."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .container import Container
    from .event_bus import EventBus
    from .job_queue import JobQueue

logger = logging.getLogger(__name__)


class HealthState(str, Enum):
    """Health state for a module."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthStatus:
    """Health status returned by a module's health_check()."""

    state: HealthState = HealthState.UNKNOWN
    message: str = ""
    details: dict = field(default_factory=dict)

    def is_healthy(self) -> bool:
        return self.state == HealthState.HEALTHY

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "message": self.message,
            "details": self.details,
        }


class BaseModule(ABC):
    """Abstract base class for all pluggable modules.

    Every module must implement :meth:`initialize`, :meth:`start`,
    :meth:`stop`, and :meth:`health_check`.  Optional hooks allow each
    module to register FastAPI routes, EventBus subscriptions and
    background job definitions without touching the core.

    Attributes:
        name: Unique module identifier (used in config and registry).
        version: Module version string.
        dependencies: Names of other modules that must be started first.
        enabled: Whether the module is active.
    """

    name: str = ""
    version: str = "1.0.0"
    dependencies: List[str] = []
    enabled: bool = True

    def __init__(self) -> None:
        self._initialized = False
        self._running = False
        self._middlewares: list = []
        self.logger = logging.getLogger(f"module.{self.name or type(self).__name__}")

    # ------------------------------------------------------------------
    # Required lifecycle hooks
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self, container: "Container") -> None:
        """Called once when the module is first loaded.

        Use this to resolve dependencies from the DI container and perform
        any one-time setup (e.g. creating DB tables, loading config).
        """

    @abstractmethod
    async def start(self) -> None:
        """Start the module (e.g. launch background tasks)."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the module (e.g. cancel background tasks)."""

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Return the current health of the module."""

    # ------------------------------------------------------------------
    # Optional extension hooks
    # ------------------------------------------------------------------

    def register_routes(self, app: "FastAPI") -> None:
        """Register FastAPI routers/routes with the application.

        Override in subclasses that expose HTTP endpoints.
        """

    def register_events(self, event_bus: "EventBus") -> None:
        """Subscribe to EventBus events.

        Override in subclasses that react to domain events.
        """

    def register_jobs(self, job_queue: "JobQueue") -> None:
        """Register background jobs / cron tasks.

        Override in subclasses that need periodic or deferred work.
        """

    # ------------------------------------------------------------------
    # Middleware support
    # ------------------------------------------------------------------

    def add_middleware(self, middleware) -> None:
        """Attach a middleware to this module's processing pipeline."""
        self._middlewares.append(middleware)

    def get_middlewares(self) -> list:
        return list(self._middlewares)

    # ------------------------------------------------------------------
    # Internal state helpers
    # ------------------------------------------------------------------

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_running(self) -> bool:
        return self._running

    def _mark_initialized(self) -> None:
        self._initialized = True

    def _mark_started(self) -> None:
        self._running = True

    def _mark_stopped(self) -> None:
        self._running = False

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} name={self.name!r} "
            f"version={self.version!r} enabled={self.enabled}>"
        )
