"""Tracked executor work owned by the application lifespan.

``asyncio.to_thread`` cancellation only cancels its awaiter.  The underlying
thread may still hold SQLite or perform an external action, so a FastAPI
shutdown must not report completion while such work is unowned.  This module
keeps every lifecycle-managed blocking call registered until its actual
executor task finishes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


class LifecycleWorkAdmissionClosed(RuntimeError):
    """Raised when a worker tries to admit blocking work during shutdown."""


class LifecycleWorkTracker:
    """Own and drain lifecycle worker executor calls without pseudo-cancellation."""

    def __init__(self, *, asyncio_module=asyncio) -> None:
        self._asyncio = asyncio_module
        self._accepting = True
        self._stop_event = asyncio_module.Event()
        self._inflight: set[Any] = set()

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def inflight_count(self) -> int:
        return len(self._inflight)

    def close_admission(self) -> None:
        """Refuse new ordinary worker calls and wake managed idle loops."""
        self._accepting = False
        self._stop_event.set()

    async def run(self, label: str, function: Callable[..., Any], *args: Any) -> Any:
        """Run admitted blocking work and keep it owned until thread completion."""
        if not self._accepting:
            raise LifecycleWorkAdmissionClosed(
                f"lifecycle work admission is closed: {label}"
            )
        return await self._run_tracked(function, *args)

    async def run_shutdown(
        self, label: str, function: Callable[..., Any], *args: Any
    ) -> Any:
        """Run an explicit shutdown action under the same tracked ownership."""
        del label
        return await self._run_tracked(function, *args)

    async def _run_tracked(self, function: Callable[..., Any], *args: Any) -> Any:
        task = self._asyncio.create_task(self._asyncio.to_thread(function, *args))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        # Shielding matters if an outer server cancellation arrives: the
        # executor call remains registered and lifespan drain still waits for
        # its real completion.  It is deliberately never detached.
        return await self._asyncio.shield(task)

    async def wait_or_stop(self, delay_seconds: float) -> bool:
        """Wait for a loop interval; return false immediately once shutdown starts."""
        if not self._accepting:
            return False
        stop_waiter = self._asyncio.create_task(self._stop_event.wait())
        sleep_waiter = self._asyncio.create_task(
            self._asyncio.sleep(max(0.0, delay_seconds))
        )
        done, pending = await self._asyncio.wait(
            {stop_waiter, sleep_waiter}, return_when=self._asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if pending:
            await self._asyncio.gather(*pending, return_exceptions=True)
        return sleep_waiter in done and self._accepting

    async def drain(self) -> None:
        """Wait until every registered executor call has actually completed."""
        while self._inflight:
            await self._asyncio.gather(*tuple(self._inflight), return_exceptions=True)
