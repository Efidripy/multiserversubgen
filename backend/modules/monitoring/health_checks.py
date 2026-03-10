"""Monitoring module health checks."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from core.module_registry import ModuleRegistry

logger = logging.getLogger(__name__)


class HealthCheckService:
    """Aggregates health check results from all registered modules.

    Args:
        registry: The :class:`~core.module_registry.ModuleRegistry` instance.
    """

    def __init__(self, registry: "ModuleRegistry") -> None:
        self._registry = registry

    async def check_all(self) -> Dict:
        """Run health checks for all enabled modules.

        Returns:
            A dict with overall status and per-module results.
        """
        results = await self._registry.health_check_all()
        overall = "ok"
        for module_result in results.values():
            state = module_result.get("state", "unknown")
            if state == "unhealthy":
                overall = "unhealthy"
                break
            if state in ("degraded", "unknown") and overall == "ok":
                overall = "degraded"

        return {"status": overall, "modules": results}
