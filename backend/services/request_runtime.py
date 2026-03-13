from __future__ import annotations

import base64
import logging
import time
from collections import deque
from threading import Lock
from typing import Callable, Dict, Optional, Tuple

from fastapi import Request


class RequestRuntime:
    def __init__(
        self,
        *,
        pam_client,
        auth_cache: Dict[str, Tuple[float, str]],
        auth_cache_lock: Lock,
        auth_cache_ttl_sec: int,
        auth_cache_negative_ttl_sec: int,
        mfa_totp_enabled: bool,
        mfa_totp_users: Dict[str, str],
        role_required_for_request: Callable[[str, str], str],
        subscription_rate_state,
        subscription_rate_lock: Lock,
        sub_rate_limit_count: int,
        sub_rate_limit_window_sec: int,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.pam_client = pam_client
        self.auth_cache = auth_cache
        self.auth_cache_lock = auth_cache_lock
        self.auth_cache_ttl_sec = auth_cache_ttl_sec
        self.auth_cache_negative_ttl_sec = auth_cache_negative_ttl_sec
        self.mfa_totp_enabled = mfa_totp_enabled
        self.mfa_totp_users = mfa_totp_users
        self.role_required_for_request = role_required_for_request
        self.subscription_rate_state = subscription_rate_state
        self.subscription_rate_lock = subscription_rate_lock
        self.sub_rate_limit_count = sub_rate_limit_count
        self.sub_rate_limit_window_sec = sub_rate_limit_window_sec
        self.logger = logger or logging.getLogger(__name__)

    def check_basic_auth_header(self, auth_header: Optional[str]) -> Optional[str]:
        if not auth_header:
            return None

        now = time.time()
        with self.auth_cache_lock:
            cached = self.auth_cache.get(auth_header)
            if cached:
                ts, cached_user = cached
                ttl = self.auth_cache_ttl_sec if cached_user else self.auth_cache_negative_ttl_sec
                if now - ts < ttl:
                    return cached_user or None
                self.auth_cache.pop(auth_header, None)

        try:
            scheme, credentials = auth_header.split()
            if scheme.lower() != "basic":
                with self.auth_cache_lock:
                    self.auth_cache[auth_header] = (now, "")
                return None
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, password = decoded.split(":", 1)
            if self.pam_client.authenticate(username, password):
                with self.auth_cache_lock:
                    self.auth_cache[auth_header] = (now, username)
                return username
        except Exception as exc:
            self.logger.warning("Auth error: %s", exc)

        with self.auth_cache_lock:
            self.auth_cache[auth_header] = (now, "")
        return None

    def verify_totp_code(self, username: str, totp_code: Optional[str]) -> bool:
        if not self.mfa_totp_enabled:
            return True
        if not totp_code:
            return False
        secret = self.mfa_totp_users.get(username)
        if not secret:
            return False
        try:
            import pyotp  # type: ignore[import-untyped]

            return bool(pyotp.TOTP(secret).verify(totp_code.strip(), valid_window=1))
        except Exception:
            return False

    @staticmethod
    def extract_basic_auth_username(auth_header: Optional[str]) -> Optional[str]:
        if not auth_header or not auth_header.lower().startswith("basic "):
            return None
        try:
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="replace")
            username, _, _password = decoded.partition(":")
            return username or None
        except Exception:
            return None

    @staticmethod
    def get_client_ip(request: Request) -> str:
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check_subscription_rate_limit(self, request: Request, resource_key: str) -> Tuple[bool, int]:
        now = time.time()
        key = f"{self.get_client_ip(request)}:{resource_key}"
        with self.subscription_rate_lock:
            q = self.subscription_rate_state[key]
            while q and now - q[0] > self.sub_rate_limit_window_sec:
                q.popleft()
            if len(q) >= self.sub_rate_limit_count:
                retry_after = max(1, int(self.sub_rate_limit_window_sec - (now - q[0])))
                return False, retry_after
            q.append(now)
        return True, 0

    @staticmethod
    def is_public_endpoint(path: str) -> bool:
        return (
            path == "/health"
            or path == "/api/v1/health"
            or path == "/api/v1/auth/mfa-status"
            or path.startswith("/api/v1/sub/")
            or path.startswith("/api/v1/sub-grouped/")
        )

    def required_role_for_request(self, method: str, path: str) -> str:
        return self.role_required_for_request(method, path)

    def check_auth(self, request: Request) -> Optional[str]:
        if hasattr(request.state, "auth_user"):
            return request.state.auth_user
        return self.check_basic_auth_header(request.headers.get("Authorization"))
