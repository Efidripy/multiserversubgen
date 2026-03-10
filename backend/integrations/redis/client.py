"""Redis client factory and helpers."""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def create_redis_client(url: str) -> Optional[Any]:
    """Create and return a Redis client connected to *url*.

    Returns ``None`` if Redis is not installed or the connection fails.

    Args:
        url: Redis URL, e.g. ``"redis://localhost:6379/0"``.

    Returns:
        A ``redis.Redis`` instance or ``None``.
    """
    if not url:
        return None

    try:
        import redis  # type: ignore[import-untyped]
        client = redis.from_url(url)
        client.ping()
        logger.info("Redis: connected to %s", url)
        return client
    except ImportError:
        logger.warning("Redis: redis package not installed")
        return None
    except Exception as exc:
        logger.warning("Redis: could not connect to %s: %s", url, exc)
        return None


def get_json(client: Any, key: str) -> Optional[Any]:
    """Get and JSON-decode a value from Redis."""
    import json
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug("Redis.get_json error: %s", exc)
        return None


def set_json(client: Any, key: str, value: Any, ttl: int = 300) -> None:
    """JSON-encode and store *value* in Redis with TTL *ttl* seconds."""
    import json
    try:
        client.setex(key, ttl, json.dumps(value))
    except Exception as exc:
        logger.debug("Redis.set_json error: %s", exc)


def delete_keys(client: Any, *keys: str) -> None:
    """Delete one or more keys from Redis (ignoring errors)."""
    try:
        client.delete(*keys)
    except Exception as exc:
        logger.debug("Redis.delete error: %s", exc)
