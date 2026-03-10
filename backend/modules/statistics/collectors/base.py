"""BaseCollector – plug-in interface for statistics collectors.

Any new type of metric can be added by creating a class that inherits
from :class:`BaseCollector` and implementing :meth:`collect`.  The
:class:`~modules.statistics.service.StatisticsService` discovers and
calls all registered collectors automatically.

Example::

    from modules.statistics.collectors.base import BaseCollector

    class DiskUsageCollector(BaseCollector):
        name = "disk_usage"

        async def collect(self, node_id: int, node: dict) -> dict:
            return {"disk_free_gb": get_disk_free(node["ip"])}
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseCollector(ABC):
    """Abstract base class for statistics collectors.

    Subclasses implement :meth:`collect` to gather one or more metrics for
    a node.  The returned dict is merged into the statistics snapshot for
    that node.

    Attributes:
        name: Unique collector identifier (used in config and registration).
        enabled: Whether this collector is active.
    """

    name: str = ""
    enabled: bool = True

    @abstractmethod
    async def collect(self, node_id: int, node: Dict[str, Any]) -> Dict[str, Any]:
        """Collect statistics for *node_id*.

        Args:
            node_id: The database ID of the node.
            node: The full node dict (as stored in the DB).

        Returns:
            A dict of metric name → value pairs for this collector.
            The keys should be unique across collectors to avoid conflicts.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} enabled={self.enabled}>"
