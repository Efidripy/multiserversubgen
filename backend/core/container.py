"""Dependency Injection Container.

Usage::

    container = Container()

    # Singleton registration (same instance every time)
    container.register("database", lambda: DatabaseService(...), singleton=True)

    # Factory registration (new instance every call)
    container.register("request_context", RequestContext, singleton=False)

    # Direct instance registration
    db = DatabaseService(...)
    container.register_instance("database", db)

    # Resolution
    db = container.resolve("database")
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Type, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ContainerError(Exception):
    """Raised when a dependency cannot be resolved."""


class Container:
    """Simple Dependency Injection container.

    Supports singleton and factory (transient) lifecycles.  Singletons are
    created lazily on first resolution and cached for the lifetime of the
    container.
    """

    def __init__(self) -> None:
        # name -> (factory_or_class, is_singleton)
        self._registry: Dict[str, tuple] = {}
        # name -> cached singleton instance
        self._singletons: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        factory: Union[Callable[..., Any], Type[Any]],
        *,
        singleton: bool = True,
    ) -> None:
        """Register a factory or class under *name*.

        Args:
            name: Dependency identifier used in :meth:`resolve`.
            factory: A callable (function or class) that produces the
                dependency when called with no arguments.
            singleton: When ``True`` (default) the dependency is created
                once and reused; when ``False`` a fresh instance is created
                on every resolution.
        """
        self._registry[name] = (factory, singleton)
        # Invalidate any existing singleton so the new factory is used
        self._singletons.pop(name, None)
        logger.debug(
            "Container: registered '%s' (singleton=%s)", name, singleton
        )

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a pre-created *instance* as a singleton."""
        self._singletons[name] = instance
        self._registry[name] = (lambda: instance, True)
        logger.debug("Container: registered instance '%s' (%r)", name, instance)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> Any:
        """Resolve and return the dependency registered under *name*.

        Raises:
            ContainerError: If *name* is not registered.
        """
        if name in self._singletons:
            return self._singletons[name]

        if name not in self._registry:
            raise ContainerError(
                f"Dependency '{name}' is not registered in the container."
            )

        factory, is_singleton = self._registry[name]
        instance = factory()

        if is_singleton:
            self._singletons[name] = instance

        logger.debug("Container: resolved '%s' (%r)", name, instance)
        return instance

    def resolve_optional(self, name: str, default: Any = None) -> Any:
        """Like :meth:`resolve` but returns *default* if not registered."""
        try:
            return self.resolve(name)
        except ContainerError:
            return default

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def is_registered(self, name: str) -> bool:
        return name in self._registry

    def registered_names(self) -> list:
        return list(self._registry.keys())

    def reset(self) -> None:
        """Clear all registrations and singleton cache."""
        self._registry.clear()
        self._singletons.clear()
        logger.debug("Container: reset")

    def reset_singletons(self) -> None:
        """Clear only the singleton cache; keep registrations."""
        self._singletons.clear()

    # ------------------------------------------------------------------
    # Context manager support for test isolation
    # ------------------------------------------------------------------

    def __enter__(self) -> "Container":
        return self

    def __exit__(self, *_: Any) -> None:
        self.reset()

    def __repr__(self) -> str:
        return f"<Container registered={self.registered_names()!r}>"
