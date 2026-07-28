"""3X-UI panel HTTP client.

Wraps the low-level :func:`~xui_session.login_panel` and
:func:`~xui_session.xui_request` functions in a stateful, reusable
client object.

Usage::

    from integrations.xui.client import XUIClient

    client = XUIClient(
        url="http://node1:2053",
        username="admin",
        password="secret",
        verify_tls=True,
    )
    response = client.request("GET", "/panel/api/inbounds/list")
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class XUIClient:
    """Stateful client for a single 3X-UI panel.

    Args:
        url: Base URL of the panel (e.g. ``"http://192.168.1.1:2053"``).
        username: Panel admin username.
        password: Panel admin password (plaintext).
        base_path: Optional URL path prefix for the panel.
        verify_tls: Whether to verify TLS certificates.
        decrypt_func: Callable used to decrypt stored passwords.
    """

    def __init__(
        self,
        *,
        url: str,
        username: str,
        password: str,
        base_path: str = "",
        verify_tls: bool = True,
        decrypt_func: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.username = username
        self._password = password
        self.base_path = base_path.strip("/")
        self.verify_tls = verify_tls if verify_tls else True
        self._decrypt = decrypt_func
        self._session: Optional[Any] = None  # requests.Session

    @property
    def _plain_password(self) -> str:
        if self._decrypt:
            try:
                return self._decrypt(self._password)
            except Exception:
                pass
        return self._password

    def login(self) -> bool:
        """Authenticate with the panel and cache the session.

        Supports both bearer-token nodes (password starts with ``bearer:``)
        and regular username/password nodes.

        Returns:
            ``True`` on success, ``False`` otherwise.
        """
        import requests as _requests
        from xui_session import login_panel  # type: ignore[import-untyped]

        session = _requests.Session()
        session.verify = self.verify_tls
        try:
            raw = self._plain_password
            if raw.startswith("bearer:"):
                bearer = raw[len("bearer:"):]
                ok = login_panel(session, self.url, "", "", bearer_token=bearer)
            else:
                ok = login_panel(session, self.url, self.username, raw)
            if ok:
                self._session = session
            return ok
        except Exception as exc:
            logger.warning("XUIClient.login failed: %s", exc)
            return False

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Make an authenticated request to the panel.

        Automatically logs in if no active session is cached.

        Args:
            method: HTTP method (``"GET"``, ``"POST"``, etc.).
            path: URL path relative to the panel base (e.g. ``"/panel/api/inbounds/list"``).
            json: JSON request body.
            params: URL query parameters.

        Returns:
            The parsed JSON response body.

        Raises:
            RuntimeError: If the request fails after login.
        """
        from xui_session import xui_request  # type: ignore[import-untyped]

        if not self._session:
            self.login()

        url = f"{self.url}/{path.lstrip('/')}"
        try:
            return xui_request(self._session, method, url, json=json, params=params)
        except Exception as exc:
            # Session may have expired — try once more after re-login
            logger.debug("XUIClient.request: retrying after session error: %s", exc)
            self._session = None
            if not self.login():
                raise RuntimeError(f"XUIClient: re-authentication failed for {self.url}") from exc
            return xui_request(self._session, method, url, json=json, params=params)

    @classmethod
    def from_node(
        cls,
        node: Dict[str, Any],
        *,
        verify_tls: bool = True,
        decrypt_func: Optional[Callable[[str], str]] = None,
    ) -> "XUIClient":
        """Create a client from a node dict (as stored in the DB).

        Args:
            node: Dict with keys ``ip``, ``port``, ``user``, ``password``,
                and optionally ``base_path``.
            verify_tls: TLS verification flag.
            decrypt_func: Optional password decryption callable.

        Returns:
            A configured :class:`XUIClient` instance.
        """
        # Берём схему из сохранённого panel_url, иначе https по умолчанию
        scheme = node.get("scheme") or "https"
        url = f"{scheme}://{node['ip']}:{node['port']}"
        return cls(
            url=url,
            username=node.get("user", ""),
            password=node.get("password", ""),
            base_path=node.get("base_path", ""),
            verify_tls=verify_tls,
            decrypt_func=decrypt_func,
        )
