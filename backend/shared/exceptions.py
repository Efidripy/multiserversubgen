"""Custom exception hierarchy for the application.

All application-level exceptions inherit from :class:`AppError` so
callers can catch them with a single ``except AppError`` clause.

HTTP status codes are stored as class attributes to keep route handlers
lean::

    raise NotFoundError(f"Node {node_id} not found")
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class AppError(Exception):
    """Base exception for all application-level errors."""

    http_status: int = 500
    error_code: str = "internal_error"

    def __init__(
        self,
        message: str = "",
        *,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class AuthenticationError(AppError):
    """Raised when credentials are missing or invalid."""

    http_status = 401
    error_code = "authentication_error"


class AuthorizationError(AppError):
    """Raised when the authenticated user lacks the required permissions."""

    http_status = 403
    error_code = "authorization_error"


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    http_status = 404
    error_code = "not_found"


class ValidationError(AppError):
    """Raised when input data fails validation."""

    http_status = 422
    error_code = "validation_error"


class RateLimitError(AppError):
    """Raised when a client exceeds the configured rate limit."""

    http_status = 429
    error_code = "rate_limit_exceeded"

    def __init__(
        self,
        message: str = "Too many requests",
        *,
        retry_after: int = 60,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after = retry_after


class ServiceUnavailableError(AppError):
    """Raised when a downstream service or dependency is unavailable."""

    http_status = 503
    error_code = "service_unavailable"


class ConflictError(AppError):
    """Raised when an operation conflicts with existing state."""

    http_status = 409
    error_code = "conflict"


class ConfigurationError(AppError):
    """Raised when the application is misconfigured."""

    http_status = 500
    error_code = "configuration_error"
