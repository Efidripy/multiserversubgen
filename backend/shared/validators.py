"""Common validators used across modules."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse


def is_valid_url(url: str, *, require_scheme: bool = True) -> bool:
    """Return ``True`` if *url* is a syntactically valid HTTP/HTTPS URL."""
    try:
        parsed = urlparse(url)
        if require_scheme and parsed.scheme not in ("http", "https"):
            return False
        return bool(parsed.netloc)
    except Exception:
        return False


def is_valid_hostname(value: str) -> bool:
    """Return ``True`` if *value* looks like a valid hostname or IP address."""
    if not value or len(value) > 253:
        return False
    allowed = re.compile(r"^(?!-)[A-Z\d-]{1,63}(?<!-)$", re.IGNORECASE)
    return all(allowed.match(part) for part in value.split("."))


def is_valid_port(value: Any) -> bool:
    """Return ``True`` if *value* is a valid TCP port number (1-65535)."""
    try:
        port = int(value)
        return 1 <= port <= 65535
    except (TypeError, ValueError):
        return False


def is_non_empty_string(value: Any) -> bool:
    """Return ``True`` if *value* is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def sanitize_string(value: str, max_length: int = 255) -> str:
    """Strip leading/trailing whitespace and truncate to *max_length*."""
    return value.strip()[:max_length]


def validate_node_config(config: dict) -> Optional[str]:
    """Validate a node configuration dict.

    Returns an error message string on failure, or ``None`` on success.
    """
    required = ("name", "ip", "port", "user", "password")
    for field in required:
        if not is_non_empty_string(config.get(field, "")):
            return f"Field '{field}' is required and must be a non-empty string."
    if not is_valid_port(config["port"]):
        return "Field 'port' must be a valid port number (1-65535)."
    return None
