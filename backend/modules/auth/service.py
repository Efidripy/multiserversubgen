"""Authentication business logic.

Extracted from main.py so it can be tested and used independently of
the FastAPI layer.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

ROLE_RANK: Dict[str, int] = {"viewer": 1, "operator": 2, "admin": 3}

# Auth cache (username → (expire_ts, role))
_auth_cache_lock = Lock()
_auth_cache: Dict[str, Tuple[float, str]] = {}
AUTH_CACHE_TTL_SEC = 30
AUTH_CACHE_NEGATIVE_TTL_SEC = 5


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
        role_viewers: Set of usernames that have the ``viewer`` role.
        role_operators: Set of usernames that have the ``operator`` role.
        mfa_totp_enabled: Whether TOTP MFA is globally enabled.
        mfa_totp_users: Mapping of ``username → TOTP_secret``.
    """

    def __init__(
        self,
        *,
        role_viewers: Optional[Set[str]] = None,
        role_operators: Optional[Set[str]] = None,
        mfa_totp_enabled: bool = False,
        mfa_totp_users: Optional[Dict[str, str]] = None,
    ) -> None:
        self.role_viewers: Set[str] = role_viewers or set()
        self.role_operators: Set[str] = role_operators or set()
        self.mfa_totp_enabled = mfa_totp_enabled
        self.mfa_totp_users: Dict[str, str] = mfa_totp_users or {}

    # ------------------------------------------------------------------
    # Role resolution
    # ------------------------------------------------------------------

    def get_user_role(self, username: str) -> str:
        """Return the role string for *username*.

        Priority: ``admin`` (default) > ``operator`` > ``viewer``.
        """
        if username in self.role_viewers:
            return "viewer"
        if username in self.role_operators:
            return "operator"
        return "admin"

    @staticmethod
    def has_min_role(user_role: str, min_role: str) -> bool:
        """Return ``True`` if *user_role* meets or exceeds *min_role*."""
        return ROLE_RANK.get(user_role, 0) >= ROLE_RANK.get(min_role, 0)

    # ------------------------------------------------------------------
    # HTTP Basic Auth parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_basic_auth(auth_header: Optional[str]) -> Optional[Tuple[str, str]]:
        """Parse an HTTP Basic Auth header and return ``(username, password)``.

        Returns ``None`` if the header is absent or malformed.
        """
        if not auth_header or not auth_header.lower().startswith("basic "):
            return None
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="replace")
            username, _, password = decoded.partition(":")
            return username, password
        except Exception:
            return None

    @staticmethod
    def extract_username(auth_header: Optional[str]) -> Optional[str]:
        """Return just the username from a Basic Auth header."""
        pair = AuthService.parse_basic_auth(auth_header)
        return pair[0] if pair else None

    # ------------------------------------------------------------------
    # PAM authentication (delegates to system PAM)
    # ------------------------------------------------------------------

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate *username*/*password* via PAM.

        Results are cached briefly to avoid repeated PAM calls.
        """
        cache_key = f"auth:{username}:{hashlib.sha256(password.encode()).hexdigest()[:8]}"

        with _auth_cache_lock:
            entry = _auth_cache.get(cache_key)
            if entry is not None:
                expire_ts, cached_result = entry
                if time.time() < expire_ts:
                    return cached_result == "ok"

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

    # ------------------------------------------------------------------
    # TOTP verification
    # ------------------------------------------------------------------

    def verify_totp(self, username: str, code: Optional[str]) -> bool:
        """Verify a TOTP code for *username*.

        Returns ``True`` if TOTP is not required for the user or if the
        code is valid.
        """
        if not self.mfa_totp_enabled:
            return True
        secret = self.mfa_totp_users.get(username)
        if not secret:
            return True
        if not code:
            return False
        try:
            import pyotp  # type: ignore[import-untyped]
            return pyotp.TOTP(secret).verify(code)
        except Exception as exc:
            logger.warning("AuthService.verify_totp error: %s", exc)
            return False

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
        if method == "DELETE":
            return "admin"
        if method == "POST":
            admin_paths = ("/restart-xray", "/reset-traffic", "/reset-all-traffic")
            if any(path.endswith(p) for p in admin_paths):
                return "admin"
            return "operator"
        if method == "PUT":
            return "operator"
        return "viewer"
