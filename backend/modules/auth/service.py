"""Authentication business logic.

Extracted from main.py so it can be tested and used independently of
the FastAPI layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import time
from threading import Lock
from typing import Callable, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

ROLE_RANK: Dict[str, int] = {"viewer": 1, "operator": 2, "admin": 3}

# Auth cache (username → (expire_ts, role))
_auth_cache_lock = Lock()
_auth_cache: Dict[str, Tuple[float, str]] = {}
_AUTH_CACHE_SECRET = secrets.token_bytes(32)
AUTH_CACHE_TTL_SEC = 30
AUTH_CACHE_NEGATIVE_TTL_SEC = 5
WEB_SESSION_TTL_SEC = 8 * 60 * 60
WEB_SESSION_COOKIE_NAME = "sub_manager_session"
ROLE_LOOKUP_CACHE_TTL_SEC = 5


def parse_mfa_users(raw: str) -> Dict[str, str]:
    """Parse ``username:secret`` CSV into a mapping."""
    result: Dict[str, str] = {}
    if not raw:
        return result
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        username, secret = item.split(":", 1)
        username = username.strip()
        secret = secret.strip().replace(" ", "")
        if username and secret:
            result[username] = secret
    return result


class AuthService:
    """Stateless authentication and authorisation service.

    The RBAC role sets and MFA configuration are injected at construction
    time so the service can be used with different configurations (e.g. in
    tests).

    Args:
        role_operators: Set of usernames that have the ``operator`` role.
        role_owners: Set of usernames that always have effective ``admin`` role.
        mfa_totp_enabled: Whether TOTP MFA is globally enabled.
        mfa_totp_users: Mapping of ``username → TOTP_secret``.
    """

    def __init__(
        self,
        *,
        role_operators: Optional[Set[str]] = None,
        role_admins: Optional[Set[str]] = None,
        role_owners: Optional[Set[str]] = None,
        ws_auth_secret: str = "",
        mfa_totp_enabled: bool = False,
        mfa_totp_users: Optional[Dict[str, str]] = None,
        role_lookup: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.role_operators: Set[str] = role_operators or set()
        self.role_admins: Set[str] = role_admins or set()
        self.role_owners: Set[str] = role_owners or set()
        self.ws_auth_secret = ws_auth_secret or secrets.token_urlsafe(32)
        self._used_ws_tickets: Dict[str, int] = {}
        self._ws_ticket_lock = Lock()
        self.mfa_totp_enabled = mfa_totp_enabled
        self.mfa_totp_users: Dict[str, str] = mfa_totp_users or {}
        self.role_lookup = role_lookup
        self._role_cache: Dict[str, Tuple[float, str]] = {}
        self._role_cache_lock = Lock()
        self._role_cache_generation = 0

    # ------------------------------------------------------------------
    # Role resolution
    # ------------------------------------------------------------------

    def get_user_role(self, username: str) -> str:
        """Return the role string for *username*.

        Owners always resolve to ``admin``. For other users an explicit
        database role takes precedence over environment role sets.
        """
        if self.is_owner(username):
            return "admin"
        env_role = "admin" if username in self.role_admins else (
            "operator" if username in self.role_operators else "viewer"
        )
        if self.role_lookup is not None:
            with self._role_cache_lock:
                cached = self._role_cache.get(username)
                if cached is not None and cached[0] > time.monotonic():
                    return cached[1]
                generation = self._role_cache_generation
            try:
                role = self.role_lookup(username)
            except Exception:
                logger.exception("Role lookup failed for %s", username)
                return env_role
            resolved_role = role if role in ROLE_RANK else env_role
            with self._role_cache_lock:
                # A change that landed mid-lookup bumped the generation: do not publish the stale role.
                if generation == self._role_cache_generation:
                    self._role_cache[username] = (
                        time.monotonic() + ROLE_LOOKUP_CACHE_TTL_SEC,
                        resolved_role,
                    )
            return resolved_role
        return env_role

    def is_owner(self, username: str) -> bool:
        """Return whether *username* is configured as a panel owner."""
        return username in self.role_owners

    def invalidate_role_cache(self) -> None:
        with self._role_cache_lock:
            self._role_cache_generation += 1
            self._role_cache.clear()

    @staticmethod
    def has_min_role(user_role: str, min_role: str) -> bool:
        """Return ``True`` if *user_role* meets or exceeds *min_role*."""
        return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(min_role, 0)

    # ------------------------------------------------------------------
    # PAM authentication (delegates to system PAM)
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate *username*/*password* via PAM.

        Results are cached briefly to avoid repeated PAM calls.
        """
        password_fingerprint = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _AUTH_CACHE_SECRET,
            100_000,
            dklen=16,
        ).hex()
        cache_key = f"auth:{username}:{password_fingerprint}"

        with _auth_cache_lock:
            entry = _auth_cache.get(cache_key)
            if entry is not None:
                expire_ts, cached_result = entry
                if time.time() < expire_ts:
                    return cached_result == "ok"

        helper_socket = os.getenv("PAM_HELPER_SOCKET", "")
        if helper_socket:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.settimeout(5.0)
                    conn.connect(helper_socket)
                    request = json.dumps(
                        {"user": username, "password": password}, separators=(",", ":")
                    ).encode("utf-8") + b"\n"
                    conn.sendall(request)
                    response = conn.recv(64)
                parsed = json.loads(response.decode("utf-8"))
                ok = parsed.get("ok") is True if isinstance(parsed, dict) else False
            except Exception as exc:
                logger.warning("AuthService.authenticate PAM helper unavailable: %s", exc)
                ok = False
        else:
            try:
                import pam as _pam  # type: ignore[import-untyped]
                p = _pam.pam()
                ok = p.authenticate(username, password)
            except Exception as exc:
                logger.warning("AuthService.authenticate PAM error: %s", exc)
                ok = False

        ttl = AUTH_CACHE_TTL_SEC if ok else AUTH_CACHE_NEGATIVE_TTL_SEC
        with _auth_cache_lock:
            _auth_cache[cache_key] = (time.time() + ttl, "ok" if ok else "fail")

        return ok

    def issue_ws_ticket(self, username: str, ttl_sec: int = 60) -> str:
        expires = int(time.time()) + max(15, min(ttl_sec, 300))
        nonce = secrets.token_urlsafe(12)
        payload = f"{username}|{expires}|{nonce}".encode("utf-8")
        signature = hmac.new(self.ws_auth_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=") + "." + signature

    def verify_ws_ticket(self, ticket: Optional[str]) -> Optional[str]:
        if not ticket or "." not in ticket:
            return None
        encoded, signature = ticket.rsplit(".", 1)
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(padded.encode("ascii"))
            expected = hmac.new(self.ws_auth_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            username, expires, nonce = payload.decode("utf-8").split("|", 2)
            expires_at = int(expires)
            now = int(time.time())
            if expires_at < now or not username or not nonce:
                return None
            with self._ws_ticket_lock:
                self._used_ws_tickets = {key: exp for key, exp in self._used_ws_tickets.items() if exp >= now}
                if signature in self._used_ws_tickets:
                    return None
                self._used_ws_tickets[signature] = expires_at
            return username
        except (ValueError, TypeError, UnicodeError):
            return None

    def _web_session_signing_key(self) -> bytes:
        """Derive a distinct signing key for browser sessions."""
        return hmac.new(
            self.ws_auth_secret.encode("utf-8"),
            b"sub-manager-web-session-v1",
            hashlib.sha256,
        ).digest()

    def issue_web_session(self, username: str, ttl_sec: int = WEB_SESSION_TTL_SEC) -> str:
        """Issue an opaque signed browser session without credentials."""
        expires = int(time.time()) + max(60, min(ttl_sec, WEB_SESSION_TTL_SEC))
        payload = json.dumps(
            {"v": 1, "sub": username, "exp": expires, "nonce": secrets.token_urlsafe(12)},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signature = hmac.new(self._web_session_signing_key(), payload, hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def verify_web_session(self, token: Optional[str]) -> Optional[str]:
        """Return the session username only for an authentic, unexpired token."""
        if not token or "." not in token:
            return None
        encoded, signature = token.rsplit(".", 1)
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = base64.urlsafe_b64decode(padded.encode("ascii"))
            expected = hmac.new(self._web_session_signing_key(), payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            claims = json.loads(payload.decode("utf-8"))
            username = claims.get("sub")
            expires = claims.get("exp")
            nonce = claims.get("nonce")
            if (
                claims.get("v") != 1
                or not isinstance(username, str)
                or not username
                or not isinstance(expires, int)
                or expires <= int(time.time())
                or not isinstance(nonce, str)
                or not nonce
            ):
                return None
            return username
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
            return None

    # ------------------------------------------------------------------
    # Route-level RBAC policy
    # ------------------------------------------------------------------

    @staticmethod
    def required_role_for_request(method: str, path: str) -> str:
        """Return the minimum role required for a given HTTP request.

        Convention (same as original main.py logic):
        * ``DELETE`` → admin
        * ``POST`` to destructive/restart endpoints → admin
        * ``POST``/``PUT`` → operator
        * ``GET`` → viewer
        """
        method = method.upper()
        path = path.lower()
        if path == "/api/v1/users" or path.startswith("/api/v1/users/"):
            return "admin"
        if path.startswith("/api/v1/subscription-client-settings"):
            return "admin"
        if path in {"/api/v1/auth/session", "/api/v1/auth/logout"}:
            return "viewer"
        if path.startswith("/api/v1/telegram/"):
            return "admin"
        if method == "GET" and path.startswith("/api/v1/clients/") and (
            path.endswith("/links") or path.startswith("/api/v1/clients/sub-links/")
        ):
            return "admin"
        if method == "DELETE":
            return "admin"
        if method == "POST":
            if path in {
                "/api/v1/clients/del-depleted",
                "/api/v1/clients/bulk-reset-traffic",
            }:
                return "admin"
            admin_paths = (
                "/restart-xray", "/stop-xray", "/reset-traffic", "/reset-all-traffic",
                "/reset-all-traffics", "/del-all-clients", "/batch-delete", "/batch-del",
                "/bulkdel", "/bulkreset", "/resetclienttraffic", "/backup/", "/api-tokens",
                "/install-xray/", "/update-panel", "/update-geofile", "/backup-telegram",
                "/generate-", "/automation/reset-all-traffic", "/subscription-tokens/",
            )
            if any(p in path for p in admin_paths) or path.endswith("/backup"):
                return "admin"
            if path.startswith("/api/v1/subscription-groups"):
                return "admin"
            return "operator"
        if method == "GET" and (
            any(p in path for p in ("/backup/", "/api-tokens", "/generate-", "/xray-config", "/server-logs", "/xray-logs", "/emails", "/subscription-groups"))
            or path.endswith(("/backup", "/logs"))
        ):
            return "admin"
        if method == "GET" and path in {"/metrics", "/api/v1/metrics"}:
            return "admin"
        if method == "GET":
            # These reads carry client UUIDs/passwords and inbound key material.
            bare = path.rstrip("/")
            if (
                bare in {"/api/v1/inbounds", "/api/v1/clients", "/api/v1/snapshots/latest"}
                or bare.startswith((
                    "/api/v1/clients/paged", "/api/v1/clients/search", "/api/v1/clients/depleted",
                    "/api/v1/clients/expired", "/api/v1/clients/find-by-ip",
                ))
                or (bare.startswith("/api/v1/nodes/") and bare.endswith(("/inbounds", "/clients")))
            ):
                return "operator"
        if method == "PUT":
            # Node PUT can repoint panel_url, which makes the collector log in with stored credentials.
            if path.startswith(("/api/v1/nodes/", "/api/v1/subscription-groups")):
                return "admin"
            return "operator"
        return "viewer"
