"""Polling strategies – define how a set of nodes is polled.

Each strategy takes a list of node dicts and a poll coroutine, and
orchestrates the order and concurrency of calls.

Usage::

    strategy = AdaptiveStrategy(max_parallel=4)
    results = await strategy.poll_all(nodes, poll_func=my_poll_coroutine)
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

PollFunc = Callable[[Dict], Awaitable[Dict]]


class BaseStrategy(ABC):
    """Abstract polling strategy."""

    @abstractmethod
    async def poll_all(
        self, nodes: List[Dict], poll_func: PollFunc
    ) -> List[Dict]:
        """Poll all *nodes* using *poll_func* and return their results."""


class SequentialStrategy(BaseStrategy):
    """Poll nodes one at a time in list order."""

    async def poll_all(self, nodes: List[Dict], poll_func: PollFunc) -> List[Dict]:
        results = []
        for node in nodes:
            try:
                result = await poll_func(node)
            except Exception as exc:
                result = {"node_id": node.get("id"), "error": str(exc), "available": False}
            results.append(result)
        return results


class ParallelStrategy(BaseStrategy):
    """Poll all nodes concurrently (no concurrency limit)."""

    async def poll_all(self, nodes: List[Dict], poll_func: PollFunc) -> List[Dict]:
        tasks = [asyncio.create_task(poll_func(node)) for node in nodes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for node, result in zip(nodes, results):
            if isinstance(result, Exception):
                out.append({"node_id": node.get("id"), "error": str(result), "available": False})
            else:
                out.append(result)
        return out


class AdaptiveStrategy(BaseStrategy):
    """Poll nodes in parallel with a configurable concurrency cap.

    Adjusts behaviour based on previous poll results: nodes that recently
    failed are polled last to avoid holding up healthy nodes.

    Args:
        max_parallel: Maximum number of concurrent poll coroutines.
    """

    def __init__(self, max_parallel: int = 4) -> None:
        self.max_parallel = max(1, max_parallel)
        self._failure_counts: Dict[Any, int] = {}

    async def poll_all(self, nodes: List[Dict], poll_func: PollFunc) -> List[Dict]:
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def _bounded_poll(node: Dict) -> Dict:
            async with semaphore:
                start = time.perf_counter()
                try:
                    result = await poll_func(node)
                    nid = node.get("id")
                    self._failure_counts[nid] = 0
                    result["poll_ms"] = (time.perf_counter() - start) * 1000
                    return result
                except Exception as exc:
                    nid = node.get("id")
                    self._failure_counts[nid] = self._failure_counts.get(nid, 0) + 1
                    logger.debug("AdaptiveStrategy: node %s poll failed: %s", nid, exc)
                    return {
                        "node_id": nid,
                        "error": str(exc),
                        "available": False,
                        "poll_ms": (time.perf_counter() - start) * 1000,
                    }

        # Sort: less-failed nodes first
        sorted_nodes = sorted(
            nodes, key=lambda n: self._failure_counts.get(n.get("id"), 0)
        )

        tasks = [asyncio.create_task(_bounded_poll(n)) for n in sorted_nodes]
        return await asyncio.gather(*tasks)


def get_strategy(name: str, max_parallel: int = 4) -> BaseStrategy:
    """Return a strategy instance by name.

    Args:
        name: One of ``"sequential"``, ``"parallel"``, ``"adaptive"``.
        max_parallel: Used only by the ``adaptive`` strategy.
    """
    strategies = {
        "sequential": SequentialStrategy,
        "parallel": ParallelStrategy,
        "adaptive": lambda: AdaptiveStrategy(max_parallel=max_parallel),
    }
    factory = strategies.get(name, lambda: AdaptiveStrategy(max_parallel=max_parallel))
    return factory()  # type: ignore[operator]
