"""Fail-closed Bot API transport with an optional loopback HTTP proxy.

The application never alters global proxy variables. Direct delivery is the
portable default. Selecting ``local_proxy`` uses only a validated loopback
endpoint and raises instead of falling back to a direct Telegram connection.
"""

from __future__ import annotations

import socket
import io
import threading
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from services.telegram_registry import TelegramRegistry


class TelegramTransportError(RuntimeError):
    """The selected Bot API transport cannot safely deliver a request."""


class _TelegramResponse:
    def __init__(self, response: requests.Response):
        self._response = response
        self.status = response.status_code

    def read(self) -> bytes:
        return self._response.content

    def __enter__(self) -> "_TelegramResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._response.close()


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


def build_local_proxy_url(host: str, port: int) -> str:
    """Build a validated loopback HTTP CONNECT URL from panel-safe fields."""

    normalized_host = str(host or "").strip()
    try:
        parsed_host = ip_address(normalized_host)
        normalized_port = int(port)
    except ValueError as exc:
        raise ValueError("Telegram proxy must contain a valid loopback IP address and port") from exc
    if not parsed_host.is_loopback or not 1 <= normalized_port <= 65535:
        raise ValueError("Telegram proxy must contain a loopback IP address and port")
    host_for_url = f"[{parsed_host.compressed}]" if parsed_host.version == 6 else parsed_host.compressed
    return validate_local_proxy_url(f"http://{host_for_url}:{normalized_port}")


@dataclass(frozen=True)
class TelegramTransportStatus:
    mode: str
    row_version: int
    configured: bool
    reachable: bool
    proxy_host: str | None
    proxy_port: int | None
    updated_by: str
    updated_at: str


class TelegramApiTransport:
    """Build a request-local opener from the persisted non-secret mode."""

    def __init__(self, *, db_path: str, local_proxy_url: str):
        self._registry = TelegramRegistry(db_path)
        self._local_proxy_url = validate_local_proxy_url(local_proxy_url)
        self._sessions: dict[tuple[str, str | None], requests.Session] = {}
        self._sessions_lock = threading.Lock()

    def status(self) -> TelegramTransportStatus:
        preference = self._registry.get_transport_preference()
        proxy_url = self._effective_proxy_url(preference)
        parsed_proxy = urlparse(proxy_url) if proxy_url else None
        return TelegramTransportStatus(
            mode=preference.mode,
            row_version=preference.row_version,
            configured=bool(proxy_url),
            reachable=self._is_local_proxy_reachable(proxy_url),
            proxy_host=str(parsed_proxy.hostname) if parsed_proxy and parsed_proxy.hostname else None,
            proxy_port=int(parsed_proxy.port) if parsed_proxy and parsed_proxy.port else None,
            updated_by=preference.updated_by,
            updated_at=preference.updated_at,
        )

    def open(self, request: Request, *, timeout: float) -> Any:
        preference = self._registry.get_transport_preference()
        if preference.mode == "direct":
            proxy_url = None
        else:
            proxy_url = self._effective_proxy_url(preference)
        if preference.mode != "direct" and (
            preference.mode != "local_proxy" or not proxy_url or not self._is_local_proxy_reachable(proxy_url)
        ):
            raise TelegramTransportError("Telegram local proxy mode is unavailable")
        session = self._session(mode=preference.mode, proxy_url=proxy_url)
        kwargs: dict[str, Any] = {
            "data": request.data,
            "headers": dict(request.header_items()),
            "timeout": timeout,
            "allow_redirects": False,
        }
        method = request.get_method()
        request_error_name: str | None = None
        try:
            response = session.request(method, request.full_url, **kwargs)
        except requests.exceptions.RequestException as exc:
            request_error_name = type(exc).__name__
        if request_error_name is not None:
            raise URLError(request_error_name) from None
        if response.status_code < 200 or response.status_code >= 300:
            body = response.content
            response.close()
            raise HTTPError(
                request.full_url,
                response.status_code,
                response.reason or "HTTP error",
                response.headers,
                io.BytesIO(body),
            )
        return _TelegramResponse(response)

    def require_local_proxy_ready(self, proxy_url: str | None = None) -> None:
        candidate = proxy_url or self._effective_proxy_url(self._registry.get_transport_preference())
        if not candidate or not self._is_local_proxy_reachable(candidate):
            raise TelegramTransportError("Telegram local proxy is not configured or not reachable")

    def _effective_proxy_url(self, preference) -> str:
        if preference.proxy_host is not None and preference.proxy_port is not None:
            return build_local_proxy_url(preference.proxy_host, preference.proxy_port)
        return self._local_proxy_url

    def _session(self, *, mode: str, proxy_url: str | None) -> requests.Session:
        key = (mode, proxy_url)
        with self._sessions_lock:
            session = self._sessions.get(key)
            if session is not None:
                return session
            session = requests.Session()
            session.trust_env = False
            retry = Retry(total=0, connect=0, read=0, redirect=0, status=0, allowed_methods=False)
            adapter = HTTPAdapter(pool_connections=4, pool_maxsize=4, max_retries=retry)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            if proxy_url:
                session.proxies = {"http": proxy_url, "https": proxy_url}
            self._sessions[key] = session
            return session

    def _is_local_proxy_reachable(self, proxy_url: str) -> bool:
        if not proxy_url:
            return False
        parsed = urlparse(proxy_url)
        try:
            with socket.create_connection((str(parsed.hostname), int(parsed.port or 0)), timeout=0.25):
                return True
        except OSError:
            return False
