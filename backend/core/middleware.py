"""Middleware pipeline for modules.

Provides reusable middleware classes that modules can attach via
:meth:`~core.base_module.BaseModule.add_middleware`.  Each class is also a
valid FastAPI/Starlette middleware and can be added directly to the
application.

Usage (module level)::

    class PollingModule(BaseModule):
        def __init__(self):
            super().__init__()
            self.add_middleware(RateLimitMiddleware(rate="100/minute"))
            self.add_middleware(CachingMiddleware(ttl=60))
            self.add_middleware(LoggingMiddleware())
            self.add_middleware(MetricsMiddleware())

Usage (app level)::

    from core.middleware import setup_middleware
    setup_middleware(app)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate limiting middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware:
    """Token-bucket rate limiter.

    Can be used as a standalone helper or wired into a module's middleware
    pipeline.

    Args:
        rate: String in ``"N/unit"`` format, e.g. ``"60/minute"``,
              ``"100/second"``, ``"1000/hour"``.
        key_func: Callable that extracts the client key from a
            :class:`fastapi.Request`.  Defaults to remote IP.
    """

    _UNITS = {"second": 1, "minute": 60, "hour": 3600}

    def __init__(
        self,
        rate: str = "60/minute",
        *,
        key_func: Optional[Callable[[Request], str]] = None,
    ) -> None:
        count_str, unit = rate.split("/")
        self._limit = int(count_str)
        self._window = self._UNITS.get(unit.lower().rstrip("s"), 60)
        self._key_func = key_func or (lambda req: _get_client_ip(req))
        self._state: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def is_allowed(self, request: Request) -> Tuple[bool, int]:
        """Check whether the request should be allowed.

        Returns:
            A tuple of *(allowed, retry_after_seconds)*.
        """
        key = self._key_func(request)
        now = time.time()
        with self._lock:
            window: Deque[float] = self._state[key]
            # Remove timestamps outside the current window
            while window and now - window[0] >= self._window:
                window.popleft()
            if len(window) >= self._limit:
                retry = int(self._window - (now - window[0]))
                return False, max(retry, 1)
            window.append(now)
            return True, 0

    def __repr__(self) -> str:
        return f"<RateLimitMiddleware {self._limit}/{self._window}s>"


# ---------------------------------------------------------------------------
# Caching middleware
# ---------------------------------------------------------------------------

class CachingMiddleware:
    """Simple in-process response cache keyed by URL path + query string.

    Args:
        ttl: Cache TTL in seconds.
        max_size: Maximum number of entries to keep (LRU eviction).
    """

    def __init__(self, ttl: int = 60, max_size: int = 256) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > self._ttl:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._cache) >= self._max_size:
                # Evict the oldest entry
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
            self._cache[key] = (time.time(), value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __repr__(self) -> str:
        return f"<CachingMiddleware ttl={self._ttl}s>"


# ---------------------------------------------------------------------------
# Logging middleware
# ---------------------------------------------------------------------------

class LoggingMiddleware:
    """Structured access logger.

    Logs method, path, status code, and duration for every request that
    passes through the module.
    """

    def __init__(self, logger_name: str = "access") -> None:
        self._logger = logging.getLogger(logger_name)

    def log_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        *,
        user: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        self._logger.info(
            "%s %s %d %.1fms",
            method,
            path,
            status_code,
            duration_ms,
            extra={
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "user": user,
                "correlation_id": correlation_id,
            },
        )

    def __repr__(self) -> str:
        return "<LoggingMiddleware>"


# ---------------------------------------------------------------------------
# Metrics middleware
# ---------------------------------------------------------------------------

class MetricsMiddleware:
    """Collects request-level counters and latency histograms.

    Counters are stored in-process (no external dependency).  For
    Prometheus integration see :mod:`shared.metrics`.
    """

    def __init__(self) -> None:
        self._request_count: Dict[str, int] = defaultdict(int)
        self._total_duration: Dict[str, float] = defaultdict(float)
        self._lock = Lock()

    def record(self, method: str, path: str, status: int, duration_sec: float) -> None:
        key = f"{method}:{path}:{status}"
        with self._lock:
            self._request_count[key] += 1
            self._total_duration[key] += duration_sec

    def snapshot(self) -> Dict[str, dict]:
        with self._lock:
            return {
                key: {
                    "count": self._request_count[key],
                    "total_duration_sec": round(self._total_duration[key], 4),
                    "avg_duration_ms": round(
                        self._total_duration[key] / self._request_count[key] * 1000, 2
                    ),
                }
                for key in self._request_count
            }

    def __repr__(self) -> str:
        return f"<MetricsMiddleware keys={len(self._request_count)}>"


# ---------------------------------------------------------------------------
# Application-level middleware setup
# ---------------------------------------------------------------------------

def setup_middleware(
    app: FastAPI,
    *,
    allow_origins: Optional[list] = None,
    gzip_min_size: int = 1000,
) -> None:
    """Attach standard middleware to a FastAPI application.

    Args:
        app: The :class:`fastapi.FastAPI` instance.
        allow_origins: CORS allowed origins.  Defaults to ``["*"]``.
        gzip_min_size: Minimum response size in bytes for GZip compression.
    """
    app.add_middleware(GZipMiddleware, minimum_size=gzip_min_size)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
