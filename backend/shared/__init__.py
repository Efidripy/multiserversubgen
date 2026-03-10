"""Shared utilities for the modular backend."""

from .exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    ServiceUnavailableError,
)
from .logging import get_logger
from .metrics import Counter, Gauge, Histogram

__all__ = [
    "AppError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ServiceUnavailableError",
    "get_logger",
    "Counter",
    "Gauge",
    "Histogram",
]
