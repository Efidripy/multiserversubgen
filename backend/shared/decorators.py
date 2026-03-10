"""Reusable decorators for cross-cutting concerns.

Available decorators:

* :func:`retry` – retry a function with exponential back-off.
* :func:`timeout` – raise :class:`TimeoutError` if the call takes too long.
* :func:`cached` – cache the return value in a :class:`~shared.cache.MemoryCache`.
* :func:`log_call` – log entry and exit of every call.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------

def retry(
    times: int = 3,
    *,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    """Retry decorator with exponential back-off.

    Args:
        times: Maximum number of attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier applied to *delay* after each failure.
        max_delay: Upper bound on the delay.
        exceptions: Exception types that trigger a retry.

    Example::

        @retry(times=3, delay=0.5, exceptions=(IOError,))
        async def fetch_data():
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, times + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt < times:
                        logger.debug(
                            "retry: %s attempt %d/%d failed – retrying in %.1fs",
                            func.__qualname__,
                            attempt,
                            times,
                            current_delay,
                        )
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * backoff, max_delay)
            raise last_exc  # type: ignore[misc]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            import time as _time
            current_delay = delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[misc]
                    last_exc = exc
                    if attempt < times:
                        _time.sleep(current_delay)
                        current_delay = min(current_delay * backoff, max_delay)
            raise last_exc  # type: ignore[misc]

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------

def timeout(seconds: float) -> Callable[[F], F]:
    """Raise :class:`asyncio.TimeoutError` if the coroutine takes longer than
    *seconds*.

    Only works with async functions.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# cached
# ---------------------------------------------------------------------------

def cached(
    ttl: int = 60,
    *,
    key_func: Optional[Callable[..., str]] = None,
    cache_attr: str = "_cache",
) -> Callable[[F], F]:
    """Cache the return value of a function using :class:`~shared.cache.MemoryCache`.

    The cache is stored as an attribute on the decorated function itself.

    Args:
        ttl: Cache TTL in seconds.
        key_func: Callable that derives a string key from the function
            arguments.  Defaults to ``str(args) + str(sorted(kwargs.items()))``.
        cache_attr: Attribute name on the function for the cache store.
    """
    from .cache import MemoryCache

    def decorator(func: F) -> F:
        _cache = MemoryCache(default_ttl=ttl)

        def _key(*args: Any, **kwargs: Any) -> str:
            if key_func:
                return key_func(*args, **kwargs)
            return f"{args!r}{sorted(kwargs.items())!r}"

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            k = _key(*args, **kwargs)
            hit = _cache.get(k)
            if hit is not None:
                return hit
            result = await func(*args, **kwargs)
            _cache.set(k, result)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            k = _key(*args, **kwargs)
            hit = _cache.get(k)
            if hit is not None:
                return hit
            result = func(*args, **kwargs)
            _cache.set(k, result)
            return result

        wrapper = async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        setattr(wrapper, cache_attr, _cache)
        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# log_call
# ---------------------------------------------------------------------------

def log_call(
    _func: Optional[F] = None,
    *,
    level: str = "DEBUG",
    include_result: bool = False,
) -> Any:
    """Log entry and optionally the return value of every call.

    Can be used with or without arguments::

        @log_call
        def my_func(): ...

        @log_call(level="INFO", include_result=True)
        async def my_async_func(): ...
    """
    numeric_level = getattr(logging, level.upper(), logging.DEBUG)

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.log(numeric_level, "→ %s(%s)", func.__qualname__, _fmt_args(args, kwargs))
            start = time.perf_counter()
            result = await func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            if include_result:
                logger.log(numeric_level, "← %s → %r (%.1fms)", func.__qualname__, result, elapsed)
            else:
                logger.log(numeric_level, "← %s (%.1fms)", func.__qualname__, elapsed)
            return result

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            logger.log(numeric_level, "→ %s(%s)", func.__qualname__, _fmt_args(args, kwargs))
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            if include_result:
                logger.log(numeric_level, "← %s → %r (%.1fms)", func.__qualname__, result, elapsed)
            else:
                logger.log(numeric_level, "← %s (%.1fms)", func.__qualname__, elapsed)
            return result

        return (async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper)  # type: ignore[return-value]

    if _func is not None:
        return decorator(_func)
    return decorator


def _fmt_args(args: tuple, kwargs: dict, max_len: int = 80) -> str:
    parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
    s = ", ".join(parts)
    return s[:max_len] + "…" if len(s) > max_len else s
