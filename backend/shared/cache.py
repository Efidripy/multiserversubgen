"""Cache abstraction with in-process and Redis backends.

Usage::

    # In-process cache (default, no dependencies)
    cache = MemoryCache(default_ttl=60)
    cache.set("key", {"data": 1})
    value = cache.get("key")

    # Redis-backed cache
    from integrations.redis.client import create_redis_client
    redis_client = create_redis_client("redis://localhost:6379")
    cache = RedisCache(redis_client, default_ttl=300)
"""

from __future__ import annotations

import json
import logging
import time
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class CacheBase:
    """Abstract cache interface."""

    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        raise NotImplementedError

    def delete(self, *keys: str) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        return self.get(key) is not None


class MemoryCache(CacheBase):
    """Thread-safe in-process LRU cache with TTL support.

    Args:
        default_ttl: Default TTL in seconds (``None`` means no expiry).
        max_size: Maximum number of entries; oldest are evicted first.
    """

    def __init__(
        self,
        default_ttl: Optional[int] = 60,
        max_size: int = 1024,
    ) -> None:
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if self._default_ttl is not None and time.time() - ts > self._default_ttl:
                del self._store[key]
                return None
            return value

    def get_with_ttl(self, key: str, ttl: int) -> Optional[Any]:
        """Get a value but treat it as expired if older than *ttl* seconds."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > ttl:
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        with self._lock:
            if len(self._store) >= self._max_size and key not in self._store:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (time.time(), value)

    def delete(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class RedisCache(CacheBase):
    """Redis-backed cache.

    Args:
        client: An active Redis client (``redis.Redis`` instance).
        default_ttl: Default TTL in seconds.
        key_prefix: Optional prefix for all keys.
    """

    def __init__(
        self,
        client: Any,
        *,
        default_ttl: int = 300,
        key_prefix: str = "sub_manager:",
    ) -> None:
        self._client = client
        self._default_ttl = default_ttl
        self._prefix = key_prefix

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._client.get(self._k(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.debug("RedisCache.get error: %s", exc)
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        try:
            self._client.setex(
                self._k(key),
                ttl or self._default_ttl,
                json.dumps(value),
            )
        except Exception as exc:
            logger.debug("RedisCache.set error: %s", exc)

    def delete(self, *keys: str) -> None:
        try:
            self._client.delete(*[self._k(k) for k in keys])
        except Exception as exc:
            logger.debug("RedisCache.delete error: %s", exc)

    def clear(self) -> None:
        try:
            pattern = f"{self._prefix}*"
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
        except Exception as exc:
            logger.debug("RedisCache.clear error: %s", exc)


def create_cache(redis_url: str = "", **kwargs: Any) -> CacheBase:
    """Factory that returns a :class:`RedisCache` when a URL is provided,
    otherwise an in-process :class:`MemoryCache`.

    Args:
        redis_url: Redis connection URL (empty string → MemoryCache).
        **kwargs: Additional kwargs forwarded to the cache constructor.

    Returns:
        A :class:`CacheBase` implementation.
    """
    if redis_url:
        try:
            import redis  # type: ignore[import-untyped]
            client = redis.from_url(redis_url)
            client.ping()
            logger.info("Cache: using Redis at %s", redis_url)
            return RedisCache(client, **kwargs)
        except Exception as exc:
            logger.warning(
                "Cache: Redis unavailable (%s), falling back to in-process cache", exc
            )
    return MemoryCache(**kwargs)
