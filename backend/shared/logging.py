"""Application logging configuration."""

from __future__ import annotations

import logging


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
