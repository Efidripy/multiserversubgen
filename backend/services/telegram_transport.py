"""Fail-closed Bot API transport with an optional loopback HTTP proxy.

The application never alters global proxy variables. Direct delivery is the
portable default. Selecting ``local_proxy`` uses only a validated loopback
endpoint and raises instead of falling back to a direct Telegram connection.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from services.telegram_registry import TelegramRegistry


class TelegramTransportError(RuntimeError):
    """The selected Bot API transport cannot safely deliver a request."""


def validate_local_proxy_url(value: str) -> str:
    """Accept only a loopback HTTP CONNECT proxy with optional complete auth."""

    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    parsed = urlparse(raw_value)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise ValueError("TELEGRAM_LOCAL_PROXY_URL must be an http:// loopback URL")
    if bool(parsed.username) != bool(parsed.password):
        raise ValueError("TELEGRAM_LOCAL_PROXY_URL proxy authentication must include both username and password")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("TELEGRAM_LOCAL_PROXY_URL must not contain a path, query or fragment")
    try:
        host = ip_address(parsed.hostname)
        is_loopback = host.is_loopback
        port = parsed.port
    except ValueError as exc:
        raise ValueError("TELEGRAM_LOCAL_PROXY_URL must contain a valid loopback host and port") from exc
    if not is_loopback or port is None or port < 1 or port > 65535:
        raise ValueError("TELEGRAM_LOCAL_PROXY_URL must contain a loopback host and port")
    return raw_value.rstrip("/")


@dataclass(frozen=True)
class TelegramTransportStatus:
    mode: str
    row_version: int
    configured: bool
    reachable: bool
    updated_by: str
    updated_at: str


class TelegramApiTransport:
    """Build a request-local opener from the persisted non-secret mode."""

    def __init__(self, *, db_path: str, local_proxy_url: str):
        self._registry = TelegramRegistry(db_path)
        self._local_proxy_url = validate_local_proxy_url(local_proxy_url)

    def status(self) -> TelegramTransportStatus:
        preference = self._registry.get_transport_preference()
        return TelegramTransportStatus(
            mode=preference.mode,
            row_version=preference.row_version,
            configured=bool(self._local_proxy_url),
            reachable=self._is_local_proxy_reachable(),
            updated_by=preference.updated_by,
            updated_at=preference.updated_at,
        )

    def open(self, request: Request, *, timeout: float) -> Any:
        preference = self._registry.get_transport_preference()
        if preference.mode == "direct":
            return self._opener(proxy_url=None).open(request, timeout=timeout)
        if preference.mode != "local_proxy" or not self._local_proxy_url:
            raise TelegramTransportError("Telegram local proxy mode is unavailable")
        # There is intentionally no direct retry: a selected local proxy must
        # fail closed if the sidecar is stopped or its EU route is unavailable.
        return self._opener(proxy_url=self._local_proxy_url).open(request, timeout=timeout)

    def require_local_proxy_ready(self) -> None:
        if not self._local_proxy_url or not self._is_local_proxy_reachable():
            raise TelegramTransportError("Telegram local proxy is not configured or not reachable")

    @staticmethod
    def _opener(*, proxy_url: str | None) -> OpenerDirector:
        # Explicit empty handlers suppress ambient HTTP(S)_PROXY variables for
        # the direct mode. No other application HTTP clients are affected.
        proxies = {"https": proxy_url} if proxy_url else {}
        return build_opener(ProxyHandler(proxies))

    def _is_local_proxy_reachable(self) -> bool:
        if not self._local_proxy_url:
            return False
        parsed = urlparse(self._local_proxy_url)
        try:
            with socket.create_connection((str(parsed.hostname), int(parsed.port or 0)), timeout=0.25):
                return True
        except OSError:
            return False
