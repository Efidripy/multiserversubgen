"""FastAPI application factory.

Using a factory function instead of a module-level ``app`` instance makes
it easy to create isolated instances for testing and allows the registry
to wire up routes before the ASGI server starts.

Usage::

    from core.app import create_app
    from core.config import get_settings

    settings = get_settings()
    app = create_app(settings)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

if TYPE_CHECKING:
    from .config import Settings


def create_app(
    settings: Optional["Settings"] = None,
    *,
    title: str = "Multi-Server Sub Manager",
    version: str = "3.0",
) -> FastAPI:
    """Create and configure a :class:`fastapi.FastAPI` application.

    Args:
        settings: :class:`~core.config.Settings` instance.  If *None* the
            singleton returned by :func:`~core.config.get_settings` is used.
        title: OpenAPI title.
        version: OpenAPI version.

    Returns:
        A fully configured :class:`fastapi.FastAPI` instance ready for route
        registration.
    """
    if settings is None:
        from .config import get_settings
        settings = get_settings()

    app = FastAPI(
        title=title,
        version=version,
        root_path=settings.root_path,
    )

    # GZip compression for responses > 1 KB
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app
