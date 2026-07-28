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
    log_file: str | None = None,
    log_file_max_bytes: int = 10 * 1024 * 1024,
    log_file_backup_count: int = 5,
) -> None:
    """Configure the root logger for the application.

    Args:
        level: Log level string (e.g. ``"INFO"``, ``"DEBUG"``).
        json_format: When ``True`` emit JSON lines (requires *pythonjsonlogger*).
        log_file: If set, also write logs to this file path (RotatingFileHandler).
        log_file_max_bytes: Max size per log file before rotation (default 10 MB).
        log_file_backup_count: Number of rotated files to keep (default 5).

    Environment overrides (take precedence over arguments):
        LOG_LEVEL: e.g. ``DEBUG``, ``INFO``, ``WARNING``
        LOG_FILE:  absolute path to log file, e.g. ``/var/log/sub-manager/app.log``
    """
    import os
    from logging.handlers import RotatingFileHandler

    level = os.getenv("LOG_LEVEL", level).upper()
    log_file = os.getenv("LOG_FILE", log_file or "") or None  # type: ignore[assignment]

    numeric_level = getattr(logging, level, logging.INFO)
    fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = []

    if json_format:
        try:
            from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]
            sh = logging.StreamHandler()
            sh.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
            handlers.append(sh)
        except ImportError:
            pass

    if not handlers:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        handlers.append(sh)

    if log_file:
        try:
            import pathlib
            pathlib.Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                log_file,
                maxBytes=log_file_max_bytes,
                backupCount=log_file_backup_count,
                encoding="utf-8",
            )
            fh.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
            handlers.append(fh)
        except OSError as exc:
            handlers[0].emit(
                logging.LogRecord(
                    "shared.logging", logging.WARNING, "", 0,
                    f"Could not open log file {log_file!r}: {exc}", (), None,
                )
            )

    logging.basicConfig(level=numeric_level, handlers=handlers, force=True)
