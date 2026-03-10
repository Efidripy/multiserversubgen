"""ModuleRegistry – manages module discovery, lifecycle and health checks.

Usage::

    registry = ModuleRegistry(container)
    registry.register(AuthModule())
    registry.register(NodesModule())

    await registry.start_all()
    # ... application runs ...
    await registry.stop_all()
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from fastapi import FastAPI

    from .base_module import BaseModule, HealthStatus
    from .container import Container
    from .event_bus import EventBus
    from .job_queue import JobQueue

logger = logging.getLogger(__name__)


class RegistryError(Exception):
    """Raised on module registration or lifecycle errors."""


class ModuleRegistry:
    """Central registry that manages the full lifecycle of all modules.

    Responsibilities:

    * Register and store :class:`~core.base_module.BaseModule` instances.
    * Resolve startup order based on ``dependencies``.
    * Drive ``initialize → start`` and ``stop`` lifecycles.
    * Propagate route, event and job registrations to the appropriate
      subsystems.
    * Aggregate health-check results.
    """

    def __init__(self, container: "Container") -> None:
        self._container = container
        self._modules: Dict[str, "BaseModule"] = {}
        self._start_order: List[str] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, module: "BaseModule") -> None:
        """Register a module instance.

        Args:
            module: A :class:`~core.base_module.BaseModule` subclass instance.

        Raises:
            RegistryError: If a module with the same ``name`` is already
                registered.
        """
        if not module.name:
            raise RegistryError(
                f"Module {type(module).__name__} has no 'name' attribute set."
            )
        if module.name in self._modules:
            raise RegistryError(
                f"A module named '{module.name}' is already registered."
            )
        self._modules[module.name] = module
        logger.info("ModuleRegistry: registered module '%s'", module.name)

    def get(self, name: str) -> Optional["BaseModule"]:
        """Return the module registered under *name*, or ``None``."""
        return self._modules.get(name)

    def all_modules(self) -> List["BaseModule"]:
        """Return all registered modules (enabled and disabled)."""
        return list(self._modules.values())

    def enabled_modules(self) -> List["BaseModule"]:
        """Return only enabled modules in dependency order."""
        self._resolve_order()
        return [self._modules[n] for n in self._start_order]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize_all(self) -> None:
        """Initialize all enabled modules in dependency order."""
        self._resolve_order()
        for name in self._start_order:
            module = self._modules[name]
            if not module.enabled:
                continue
            try:
                logger.info("ModuleRegistry: initializing '%s'", name)
                await module.initialize(self._container)
                module._mark_initialized()
            except Exception:
                logger.exception(
                    "ModuleRegistry: failed to initialize module '%s'", name
                )
                raise

    async def start_all(self) -> None:
        """Start all enabled modules (calls initialize first if needed)."""
        self._resolve_order()
        for name in self._start_order:
            module = self._modules[name]
            if not module.enabled:
                continue
            if not module.is_initialized:
                await module.initialize(self._container)
                module._mark_initialized()
            try:
                logger.info("ModuleRegistry: starting '%s'", name)
                await module.start()
                module._mark_started()
            except Exception:
                logger.exception(
                    "ModuleRegistry: failed to start module '%s'", name
                )
                raise

    async def stop_all(self) -> None:
        """Stop all running modules in reverse start order."""
        for name in reversed(self._start_order):
            module = self._modules.get(name)
            if module is None or not module.is_running:
                continue
            try:
                logger.info("ModuleRegistry: stopping '%s'", name)
                await module.stop()
                module._mark_stopped()
            except Exception:
                logger.exception(
                    "ModuleRegistry: error stopping module '%s'", name
                )

    async def reload_module(self, name: str) -> None:
        """Reload a single module (stop → re-initialize → start)."""
        module = self._modules.get(name)
        if module is None:
            raise RegistryError(f"Module '{name}' is not registered.")
        if module.is_running:
            await module.stop()
            module._mark_stopped()
        await module.initialize(self._container)
        module._mark_initialized()
        await module.start()
        module._mark_started()
        logger.info("ModuleRegistry: reloaded module '%s'", name)

    # ------------------------------------------------------------------
    # Route / event / job wiring
    # ------------------------------------------------------------------

    def register_routes(self, app: "FastAPI") -> None:
        """Call ``register_routes(app)`` on every enabled module."""
        for module in self.enabled_modules():
            try:
                module.register_routes(app)
            except Exception:
                logger.exception(
                    "ModuleRegistry: error registering routes for '%s'",
                    module.name,
                )

    def register_events(self, event_bus: "EventBus") -> None:
        """Call ``register_events(event_bus)`` on every enabled module."""
        for module in self.enabled_modules():
            try:
                module.register_events(event_bus)
            except Exception:
                logger.exception(
                    "ModuleRegistry: error registering events for '%s'",
                    module.name,
                )

    def register_jobs(self, job_queue: "JobQueue") -> None:
        """Call ``register_jobs(job_queue)`` on every enabled module."""
        for module in self.enabled_modules():
            try:
                module.register_jobs(job_queue)
            except Exception:
                logger.exception(
                    "ModuleRegistry: error registering jobs for '%s'",
                    module.name,
                )

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def health_check_all(self) -> Dict[str, dict]:
        """Run health checks on all enabled modules concurrently.

        Returns:
            A dict mapping module name to its :meth:`health_check` result
            serialised via ``to_dict()``.
        """
        results: Dict[str, dict] = {}
        tasks = {
            name: asyncio.create_task(mod.health_check())
            for name, mod in self._modules.items()
            if mod.enabled
        }
        for name, task in tasks.items():
            try:
                status: "HealthStatus" = await task
                results[name] = status.to_dict()
            except Exception as exc:
                results[name] = {
                    "state": "unhealthy",
                    "message": str(exc),
                    "details": {},
                }
        return results

    # ------------------------------------------------------------------
    # Dependency resolution (topological sort)
    # ------------------------------------------------------------------

    def _resolve_order(self) -> None:
        """Compute and cache the dependency-respecting start order."""
        enabled = {n for n, m in self._modules.items() if m.enabled}
        visited: set = set()
        order: List[str] = []

        def visit(name: str, chain: List[str]) -> None:
            if name in chain:
                raise RegistryError(
                    f"Circular dependency detected: {' -> '.join(chain + [name])}"
                )
            if name in visited:
                return
            module = self._modules.get(name)
            if module is None:
                raise RegistryError(
                    f"Module '{name}' is listed as a dependency but not registered."
                )
            for dep in module.dependencies:
                if dep in enabled:
                    visit(dep, chain + [name])
            visited.add(name)
            order.append(name)

        for name in enabled:
            visit(name, [])

        self._start_order = order

    def __repr__(self) -> str:
        names = list(self._modules.keys())
        return f"<ModuleRegistry modules={names!r}>"
