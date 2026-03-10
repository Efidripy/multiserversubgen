"""Structured logging helpers.

Provides a factory function :func:`get_logger` that returns a standard
:class:`logging.Logger` enriched with a context adapter so that extra
fields (``correlation_id``, ``user``, ``node_id`` …) can be attached to
every log record emitted by a module.

Usage::

    from shared.logging import get_logger

    logger = get_logger(__name__)

    logger.info("Node polled", extra={
        "node_id": 42,
        "duration_ms": 125,
        "correlation_id": "abc-123",
    })
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, MutableMapping, Optional, Tuple


class ContextAdapter(logging.LoggerAdapter):
    """Logger adapter that merges default context with per-call *extra* dicts.

    Attributes:
        context: Base context dict merged into every log record.
    """

    def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(logger, context or {})

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> Tuple[str, MutableMapping[str, Any]]:
        extra = dict(self.extra)
        extra.update(kwargs.get("extra") or {})
        kwargs["extra"] = extra
        return msg, kwargs

    def with_context(self, **ctx: Any) -> "ContextAdapter":
        """Return a new adapter that inherits this context plus *ctx*."""
        merged = {**self.extra, **ctx}
        return ContextAdapter(self.logger, merged)


def get_logger(
    name: str,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> ContextAdapter:
    """Return a :class:`ContextAdapter` wrapping the named logger.

    Args:
        name: Logger name (typically ``__name__``).
        context: Default key/value pairs attached to every record.

    Returns:
        A :class:`ContextAdapter` that supports ``.with_context(**kwargs)``
        to create child loggers with additional fields.
    """
    return ContextAdapter(logging.getLogger(name), context)


def configure_logging(
    level: str = "INFO",
    *,
    json_format: bool = False,
) -> None:
    """Configure the root logger for the application.

    Args:
        level: Log level string (e.g. ``"INFO"``, ``"DEBUG"``).
        json_format: When ``True`` emit JSON lines (requires *pythonjsonlogger*).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    if json_format:
        try:
            from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]
            handler = logging.StreamHandler()
            handler.setFormatter(
                jsonlogger.JsonFormatter(
                    "%(asctime)s %(name)s %(levelname)s %(message)s"
                )
            )
            logging.basicConfig(level=numeric_level, handlers=[handler])
            return
        except ImportError:
            pass  # Fall through to plain text

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
