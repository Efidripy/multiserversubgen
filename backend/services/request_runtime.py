from __future__ import annotations

import base64
import hashlib
import logging
import time
from threading import Lock
from typing import Callable, Dict, Optional, Set, Tuple

from fastapi import Request


# Максимальный размер auth_cache чтобы избежать DoS через memory exhaustion
_AUTH_CACHE_MAX_SIZE = 4096

# Окно для TOTP replay-защиты (секунды) — чуть больше окна valid_window=1 (90с)
_TOTP_REPLAY_WINDOW_SEC = 120
_SUBSCRIPTION_RATE_MAX_KEYS = 8192


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
        # TOTP replay cache: {username → set of (ts_bucket, code)}
        self._totp_used: Dict[str, Set[str]] = {}
        self._totp_used_lock = Lock()

    @staticmethod
    def _cache_key(auth_header: str) -> str:
        return hashlib.sha256(auth_header.encode(), usedforsecurity=False).hexdigest()

    def check_basic_auth_header(self, auth_header: Optional[str]) -> Optional[str]:
        if not auth_header:
            return None

        cache_key = self._cache_key(auth_header)
        now = time.time()
        with self.auth_cache_lock:
            cached = self.auth_cache.get(cache_key)
            if cached:
                ts, cached_user = cached
                ttl = self.auth_cache_ttl_sec if cached_user else self.auth_cache_negative_ttl_sec
                if now - ts < ttl:
                    return cached_user or None
                self.auth_cache.pop(cache_key, None)

        def _set_cache(value: str) -> None:
            with self.auth_cache_lock:
                if len(self.auth_cache) >= _AUTH_CACHE_MAX_SIZE:
                    try:
                        self.auth_cache.pop(next(iter(self.auth_cache)))
                    except StopIteration:
                        pass
                self.auth_cache[cache_key] = (now, value)

        try:
            scheme, credentials = auth_header.split()
            if scheme.lower() != "basic":
                _set_cache("")
                return None
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, password = decoded.split(":", 1)
            if self.pam_client.authenticate(username, password):
                _set_cache(username)
                return username
        except Exception as exc:
            self.logger.warning("Auth error: %s", exc)

        _set_cache("")
        return None

    def verify_totp_code(self, username: str, totp_code: Optional[str]) -> bool:
        if not self.mfa_totp_enabled:
            return True
        if not totp_code:
            return False
        secret = self.mfa_totp_users.get(username)
        if not secret:
            return False
        code = totp_code.strip()
        try:
            import pyotp  # type: ignore[import-untyped]
            if not pyotp.TOTP(secret).verify(code, valid_window=1):
                return False
        except Exception:
            return False

        # Replay protection: reject code that was already used within the window
        now = time.time()
        bucket = str(int(now // 30))  # 30-second TOTP window
        replay_key = f"{bucket}:{code}"
        with self._totp_used_lock:
            used = self._totp_used.get(username, set())
            if replay_key in used:
                return False
            # Purge old buckets (keep only last _TOTP_REPLAY_WINDOW_SEC / 30 buckets)
            max_buckets = (_TOTP_REPLAY_WINDOW_SEC // 30) + 1
            current_bucket_int = int(now // 30)
            used = {k for k in used if int(k.split(":", 1)[0]) >= current_bucket_int - max_buckets}
            used.add(replay_key)
            self._totp_used[username] = used
        return True

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
        """Получить реальный IP клиента.

        X-Forwarded-For доверяем только когда запрос пришёл с loopback/private-адреса
        (т.е. через реальный reverse proxy на том же хосте или в той же сети).
        Если запрос пришёл напрямую из интернета — не доверяем заголовку.
        """
        direct_ip = request.client.host if request.client else ""
        # Доверяем X-Forwarded-For только от loopback или private-адресов
        is_from_proxy = direct_ip in {"127.0.0.1", "::1"}
        if is_from_proxy:
            forwarded_for = request.headers.get("X-Forwarded-For", "")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        return direct_ip or "unknown"

    def check_subscription_rate_limit(self, request: Request, resource_key: str) -> Tuple[bool, int]:
        now = time.time()
        key = f"{self.get_client_ip(request)}:{resource_key}"
        with self.subscription_rate_lock:
            expired_keys = []
            for existing_key, existing_q in self.subscription_rate_state.items():
                while existing_q and now - existing_q[0] > self.sub_rate_limit_window_sec:
                    existing_q.popleft()
                if not existing_q:
                    expired_keys.append(existing_key)
            for expired_key in expired_keys:
                self.subscription_rate_state.pop(expired_key, None)
            if len(self.subscription_rate_state) >= _SUBSCRIPTION_RATE_MAX_KEYS and key not in self.subscription_rate_state:
                oldest_key = min(self.subscription_rate_state, key=lambda item: self.subscription_rate_state[item][0])
                self.subscription_rate_state.pop(oldest_key, None)
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
