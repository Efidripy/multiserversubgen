"""EventBus – lightweight publish/subscribe system for inter-module communication.

Usage::

    bus = EventBus()

    # Subscribe a handler (sync or async)
    async def on_node_created(data: dict) -> None:
        print("Node created:", data)

    bus.subscribe("node.created", on_node_created)

    # Publish an event (async)
    await bus.emit("node.created", {"node_id": 1, "name": "Server1"})

    # Or publish from sync context (fire-and-forget)
    bus.emit_sync("node.created", {"node_id": 1, "name": "Server1"})
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List, Union

logger = logging.getLogger(__name__)

Handler = Union[Callable[[Dict], None], Callable[[Dict], Awaitable[None]]]


class EventBus:
    """Central event bus for publish/subscribe messaging between modules.

    All handlers are called in order of subscription.  Async handlers are
    awaited; sync handlers are called directly in the current coroutine via
    ``asyncio.get_event_loop().run_in_executor``.

    Wildcard subscriptions are supported using ``*`` as the event name.
    """

    def __init__(self, *, audit_log: bool = True) -> None:
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)
        self._audit_log = audit_log

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, event: str, handler: Handler) -> None:
        """Register *handler* to be called when *event* is emitted.

        Args:
            event: Event name (e.g. ``"node.created"``), or ``"*"`` for all
                events.
            handler: A sync or async callable that receives the event payload
                dict.
        """
        if handler not in self._handlers[event]:
            self._handlers[event].append(handler)
            logger.debug("EventBus: subscribed %s to '%s'", handler.__qualname__, event)

    def unsubscribe(self, event: str, handler: Handler) -> None:
        """Remove *handler* from *event* subscribers."""
        try:
            self._handlers[event].remove(handler)
            logger.debug(
                "EventBus: unsubscribed %s from '%s'", handler.__qualname__, event
            )
        except ValueError:
            pass

    def unsubscribe_all(self, event: str) -> None:
        """Remove all handlers for *event*."""
        self._handlers.pop(event, None)

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    async def emit(self, event: str, data: Any = None) -> None:
        """Emit *event* and await all registered handlers.

        Handlers for the exact event name are called first, followed by any
        wildcard (``"*"``) handlers.

        Args:
            event: Event name.
            data: Payload passed to each handler.  Defaults to an empty dict.
        """
        if data is None:
            data = {}
        if self._audit_log:
            logger.debug("EventBus: emit '%s' %s", event, data)

        handlers: List[Handler] = list(self._handlers.get(event, []))
        handlers += [h for h in self._handlers.get("*", []) if h not in handlers]

        for handler in handlers:
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "EventBus: handler %s raised an exception for event '%s'",
                    getattr(handler, "__qualname__", repr(handler)),
                    event,
                )

    def emit_sync(self, event: str, data: Any = None) -> None:
        """Fire-and-forget emit from a synchronous context.

        If an event loop is already running the coroutine is scheduled as a
        task; otherwise a new event loop is used.
        """
        coro = self.emit(event, data)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def listeners(self, event: str) -> List[Handler]:
        """Return a copy of the handler list for *event*."""
        return list(self._handlers.get(event, []))

    def all_events(self) -> List[str]:
        """Return all event names that have at least one subscriber."""
        return [e for e, h in self._handlers.items() if h]

    def __repr__(self) -> str:
        return f"<EventBus events={self.all_events()!r}>"
