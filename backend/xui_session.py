"""
Вспомогательный модуль для работы с node panel API.
Централизует логику авторизации с поддержкой sub-path установок.
"""
import logging
import hashlib
import os
import time
from threading import Lock
import requests
from typing import Any, Dict
from urllib.parse import urlparse
from shared.security import validate_outbound_url

logger = logging.getLogger("sub_manager")

# Кеш метода авторизации: base_url → "csrf" | "legacy"
_AUTH_METHOD_CACHE: dict[str, str] = {}
_AUTH_METHOD_CACHE_LOCK = Lock()
_AUTH_METHOD_CACHE_MAX = 512

# Кеш версии API панели: base_url → "v3" | "v2"
# v3: 3x-ui >= 3.x — поддерживает /panel/api/clients/* first-class API
# v2: старые версии — клиенты вложены в inbound settings
_NODE_API_VERSION: dict[str, str] = {}
_NODE_API_VERSION_LOCK = Lock()
_SESSION_CACHE_LOCK = Lock()
_SESSION_LOGIN_LOCKS: dict[str, Lock] = {}
_SESSION_CACHE: dict[str, Dict[str, Any]] = {}
_SESSION_CACHE_MAX = 1024


def _clean_url_path(value: Any) -> str:
    return str(value or "").strip().strip("/")


def _parse_panel_url_candidate(value: str, default_scheme: str):
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return None
    candidate = raw if "://" in raw else f"{default_scheme}://{raw.lstrip('/')}"
    parsed = urlparse(candidate)
    if parsed.hostname:
        return parsed
    return None


def _safe_parsed_port(parsed) -> int | None:
    try:
        return parsed.port
    except ValueError:
        return None


def build_panel_base_url(node: Dict[str, Any]) -> str:
    """Return the canonical panel base URL, preserving any configured path prefix."""
    scheme = str(node.get("scheme") or "https").strip() or "https"
    node_port = str(node.get("port") or "").strip()
    base_path = _clean_url_path(node.get("base_path") or node.get("access_path"))

    parsed_source = None
    for field_name in ("panel_url", "ip"):
        parsed = _parse_panel_url_candidate(str(node.get(field_name) or ""), scheme)
        if not parsed:
            continue
        if parsed_source is None:
            parsed_source = (field_name, parsed)
        if not base_path and parsed.path:
            base_path = _clean_url_path(parsed.path)

    if parsed_source is None:
        raise ValueError("Node panel host is missing")

    source_field, parsed = parsed_source
    scheme = parsed.scheme or scheme
    host = parsed.hostname or ""
    parsed_port = _safe_parsed_port(parsed)
    port = parsed_port or (None if source_field == "panel_url" else node_port)

    if not host:
        raise ValueError("Node panel host is missing")

    netloc = host
    if port:
        netloc = f"{host}:{port}"

    base_url = f"{scheme}://{netloc}"
    if base_path:
        base_url = f"{base_url}/{base_path}"
    base_url = base_url.rstrip("/")
    valid_url, url_error = validate_outbound_url(base_url)
    if not valid_url:
        raise ValueError(url_error)
    return base_url


def join_panel_url(base_url: str, path: str) -> str:
    return f"{str(base_url).rstrip('/')}/{str(path or '').lstrip('/')}"


def make_node_key_for_node(node: Dict[str, Any]) -> str:
    base_url = build_panel_base_url(node)
    parsed = urlparse(base_url)
    port = parsed.port
    if port is None:
        port = 80 if parsed.scheme == "http" else 443
    return make_node_key(parsed.hostname or "", port, parsed.path.strip("/"))


def get_node_api_version(base_url: str) -> str | None:
    """Вернуть закешированную версию API ноды, или None если не определена."""
    with _NODE_API_VERSION_LOCK:
        return _NODE_API_VERSION.get(base_url)


def set_node_api_version(base_url: str, version: str) -> None:
    """Закешировать версию API ноды ('v3' или 'v2')."""
    with _NODE_API_VERSION_LOCK:
        if len(_NODE_API_VERSION) >= _AUTH_METHOD_CACHE_MAX:
            try:
                _NODE_API_VERSION.pop(next(iter(_NODE_API_VERSION)))
            except StopIteration:
                pass
        _NODE_API_VERSION[base_url] = version


def invalidate_node_api_version(base_url: str | None = None) -> None:
    """Сбросить кеш версии API. base_url=None сбрасывает всё."""
    with _NODE_API_VERSION_LOCK:
        if base_url is None:
            _NODE_API_VERSION.clear()
        else:
            _NODE_API_VERSION.pop(base_url, None)


def seed_node_api_versions(nodes: list) -> None:
    """Seed the in-memory API version cache from DB node records on startup.

    Call this once after node_service is available so every operation knows
    the correct API version immediately without probing.
    """
    seeded = 0
    with _NODE_API_VERSION_LOCK:
        for node in nodes:
            api_version = (node.get("api_version") or "").strip()
            if not api_version:
                continue
            try:
                base_url = build_panel_base_url(node)
            except ValueError:
                continue
            if base_url not in _NODE_API_VERSION:
                _NODE_API_VERSION[base_url] = api_version
                seeded += 1
    if seeded:
        logger.info("Seeded API version cache: %d nodes", seeded)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        return float(raw)
    except Exception:
        return default


VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")

XUI_MAX_CONNECT_TIMEOUT_SEC = 3.0
XUI_MAX_READ_TIMEOUT_SEC = 4.0
XUI_CONNECT_TIMEOUT_SEC = min(
    XUI_MAX_CONNECT_TIMEOUT_SEC,
    max(0.1, _env_float("XUI_CONNECT_TIMEOUT_SEC", XUI_MAX_CONNECT_TIMEOUT_SEC)),
)
XUI_READ_TIMEOUT_SEC = min(
    XUI_MAX_READ_TIMEOUT_SEC,
    max(
        0.1,
        _env_float(
            "XUI_READ_TIMEOUT_SEC",
            _env_float("XUI_HTTP_TIMEOUT_SEC", XUI_MAX_READ_TIMEOUT_SEC),
        ),
    ),
)
XUI_HTTP_TIMEOUT_SEC = XUI_READ_TIMEOUT_SEC
XUI_HTTP_RETRIES = max(0, _env_int("XUI_HTTP_RETRIES", 0))
XUI_HTTP_RETRY_BACKOFF_SEC = max(0.0, _env_float("XUI_HTTP_RETRY_BACKOFF_SEC", 0.35))
XUI_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}
XUI_FAST_TIMEOUT_SEC = min(XUI_READ_TIMEOUT_SEC, max(1.0, _env_float("XUI_FAST_TIMEOUT_SEC", XUI_READ_TIMEOUT_SEC)))
XUI_FAST_RETRIES = max(0, _env_int("XUI_FAST_RETRIES", 0))
XUI_SESSION_TTL_SEC = max(0, _env_int("XUI_SESSION_TTL_SEC", 0))


def bounded_xui_timeout(timeout: float | tuple | list | None = None) -> tuple[float, float]:
    """Return a requests timeout tuple capped to the XUI hard SLA."""
    connect_timeout = XUI_CONNECT_TIMEOUT_SEC
    read_timeout = XUI_READ_TIMEOUT_SEC

    if isinstance(timeout, (tuple, list)):
        if timeout:
            try:
                connect_timeout = min(connect_timeout, max(0.1, float(timeout[0])))
            except Exception:
                pass
        if len(timeout) > 1:
            try:
                read_timeout = min(read_timeout, max(0.1, float(timeout[1])))
            except Exception:
                pass
    elif timeout is not None:
        try:
            read_timeout = min(read_timeout, max(0.1, float(timeout)))
        except Exception:
            pass

    return (connect_timeout, read_timeout)


def make_node_key(ip: str, port: int | str, base_path: str = "") -> str:
    parsed = _parse_panel_url_candidate(str(ip or ""), "https")
    if parsed:
        ip = parsed.hostname or ip
        if not base_path and parsed.path:
            base_path = parsed.path.strip("/")
        parsed_port = _safe_parsed_port(parsed)
        if not port and parsed_port:
            port = parsed_port
    normalized_path = str(base_path or "").strip("/")
    return f"{ip}:{port}:{normalized_path}"


def _node_lock(node_key: str) -> Lock:
    with _SESSION_CACHE_LOCK:
        lock = _SESSION_LOGIN_LOCKS.get(node_key)
        if lock is None:
            lock = Lock()
            _SESSION_LOGIN_LOCKS[node_key] = lock
        return lock


def invalidate_session_cache(node_key: str | None = None) -> None:
    with _SESSION_CACHE_LOCK:
        if node_key is None:
            _SESSION_CACHE.clear()
            return
        for key in list(_SESSION_CACHE):
            if key == node_key or key.startswith(str(node_key) + ":"):
                _SESSION_CACHE.pop(key, None)


def _is_cached_session_usable(cached: Dict[str, Any] | None, now: float) -> bool:
    if not cached:
        return False
    if XUI_SESSION_TTL_SEC <= 0:
        return True
    return now - float(cached.get("ts", 0.0)) <= XUI_SESSION_TTL_SEC


def _cache_session(node_key: str, session: requests.Session, base_url: str) -> None:
    with _SESSION_CACHE_LOCK:
        if len(_SESSION_CACHE) >= _SESSION_CACHE_MAX:
            try:
                _SESSION_CACHE.pop(next(iter(_SESSION_CACHE)))
            except StopIteration:
                pass
    _SESSION_CACHE[node_key] = {"session": session, "base_url": base_url, "ts": time.time()}


def get_authenticated_session(
    *,
    node_key: str,
    base_url: str,
    username: str,
    password: str,
    bearer_token: str | None,
    verify_value: Any,
    timeout: float | None = None,
    retries: int | None = None,
    force_reauth: bool = False,
) -> Dict[str, Any]:
    credential_material = (bearer_token or (username + "\x00" + password)).encode("utf-8")
    cache_key = node_key + ":" + hashlib.sha256(credential_material).hexdigest()
    now = time.time()
    if not force_reauth:
        with _SESSION_CACHE_LOCK:
            cached = _SESSION_CACHE.get(cache_key)
            if _is_cached_session_usable(cached, now):
                return {
                    "ok": True,
                    "session": cached["session"],
                    "base_url": cached["base_url"],
                    "cached": True,
                    "reason": "ok",
                    "error": "",
                }

    lock = _node_lock(cache_key)
    with lock:
        now = time.time()
        if not force_reauth:
            with _SESSION_CACHE_LOCK:
                cached = _SESSION_CACHE.get(cache_key)
                if _is_cached_session_usable(cached, now):
                    return {
                        "ok": True,
                        "session": cached["session"],
                        "base_url": cached["base_url"],
                        "cached": True,
                        "reason": "ok",
                        "error": "",
                    }

        session = requests.Session()
        session.verify = verify_value
        detailed = login_panel_detailed(
            session,
            base_url,
            username,
            password,
            bearer_token=bearer_token,
            timeout=timeout,
            retries=retries,
        )
        if not detailed.get("ok"):
            return {
                "ok": False,
                "session": None,
                "base_url": base_url,
                "cached": False,
                "reason": detailed.get("reason", "auth_failed"),
                "error": detailed.get("error", "Failed to authenticate"),
            }

        _cache_session(cache_key, session, base_url)
        return {
            "ok": True,
            "session": session,
            "base_url": base_url,
            "cached": False,
            "reason": "ok",
            "error": "",
        }


def is_auth_failure_response(response: requests.Response) -> bool:
    status_code = getattr(response, "status_code", None)
    final_url = str(getattr(response, "url", "") or "")
    if not final_url:
        request_obj = getattr(response, "request", None)
        final_url = str(getattr(request_obj, "url", "") or "")

    if status_code in (401, 403):
        return True
    if status_code == 404 and final_url:
        # 3x-ui can mask expired/invalid panel sessions as 404 under /panel/api/*
        # instead of returning 401/403, so treat this as an auth-failure signal.
        path = urlparse(final_url).path.rstrip("/").lower()
        if "/panel/api/" in path or path.endswith("/panel/api"):
            return True

    final_url = final_url.lower()
    if final_url:
        path = urlparse(final_url).path.rstrip("/").lower()
        if path.endswith("/login") or path.endswith("/panel/login"):
            return True

    headers = getattr(response, "headers", {}) or {}
    content_type = ""
    if hasattr(headers, "get"):
        content_type = str(headers.get("content-type", "") or "").lower()
    text = str(getattr(response, "text", "") or "").lower()[:2000]
    if "text/html" in content_type and "password" in text and ("login" in text or "username" in text):
        return True
    if "window.location" in text and "login" in text:
        return True
    return False


def _cache_auth_method(base_url: str, method: str) -> None:
    with _AUTH_METHOD_CACHE_LOCK:
        if len(_AUTH_METHOD_CACHE) >= _AUTH_METHOD_CACHE_MAX:
            try:
                _AUTH_METHOD_CACHE.pop(next(iter(_AUTH_METHOD_CACHE)))
            except StopIteration:
                pass
        _AUTH_METHOD_CACHE[base_url] = method


def invalidate_auth_method_cache(base_url: str | None = None) -> None:
    """Сбросить кеш метода авторизации. base_url=None сбрасывает всё."""
    with _AUTH_METHOD_CACHE_LOCK:
        if base_url is None:
            _AUTH_METHOD_CACHE.clear()
        else:
            _AUTH_METHOD_CACHE.pop(base_url, None)


def extract_node_auth(node: dict, decrypt_func) -> tuple:
    """Извлечь (username, password, bearer_token) из dict-записи узла.

    Узлы с bearer-токеном хранят user='bearer_token' и password=encrypt('bearer:TOKEN').
    Возвращает (username, plaintext_password, bearer_token_or_None).
    """
    raw = decrypt_func(node.get("password", ""))
    if raw.startswith("bearer:"):
        return "", "", raw[len("bearer:"):]
    return node.get("user", ""), raw, None


def _infer_login_failure_reason(status_code: int | None, response_text: str, exc: Exception | None = None) -> str:
    text = (response_text or "").lower()
    exc_text = str(exc or "").lower()

    if "two-factor" in text or "totp" in text:
        return "two_factor_required"
    if "invalid username or password" in text or '"success":false' in text:
        return "auth_failed"
    if "certificate" in exc_text or "ssl" in exc_text or "tls" in exc_text:
        return "tls_error"
    if "timed out" in exc_text or "timeout" in exc_text:
        return "timeout"
    if status_code:
        return f"http_{status_code}"
    if exc is not None:
        return "network_error"
    return "unknown"


def xui_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: float | None = None,
    retries: int | None = None,
    **kwargs,
) -> requests.Response:
    """Выполнить HTTP-запрос к node panel c ретраями и backoff."""
    actual_timeout = bounded_xui_timeout(timeout)
    retry_budget = XUI_HTTP_RETRIES if retries is None else max(0, int(retries))
    attempts = retry_budget + 1
    last_exc: Exception | None = None

    for attempt in range(attempts):
        try:
            log_kwargs = {k: v for k, v in kwargs.items() if k not in ("data",)}
            logger.debug("XUI %s %s attempt=%d kwargs=%s", method.upper(), url, attempt, log_kwargs)
            response = session.request(
                method=method.upper(),
                url=url,
                timeout=actual_timeout,
                **kwargs,
            )
            logger.debug(
                "XUI %s %s -> HTTP %d body=%r",
                method.upper(), url, response.status_code,
                response.text[:500] if response.text else "",
            )
            if (
                response.status_code in XUI_HTTP_RETRY_STATUSES
                and attempt < attempts - 1
            ):
                sleep_for = XUI_HTTP_RETRY_BACKOFF_SEC * (2 ** attempt)
                logger.warning(
                    "XUI %s %s HTTP %d, retry in %.1fs (attempt %d/%d)",
                    method.upper(), url, response.status_code, sleep_for, attempt + 1, attempts,
                )
                if sleep_for > 0:
                    time.sleep(sleep_for)
                continue
            return response
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("XUI %s %s request error (attempt %d/%d): %s", method.upper(), url, attempt + 1, attempts, exc)
            if attempt >= attempts - 1:
                raise
            sleep_for = XUI_HTTP_RETRY_BACKOFF_SEC * (2 ** attempt)
            if sleep_for > 0:
                time.sleep(sleep_for)

    if last_exc is not None:
        raise last_exc
    raise requests.RequestException("xui_request failed without response")


def login_panel(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    *,
    bearer_token: str | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> bool:
    """Авторизоваться на node panel панели.

    Поддерживает три метода авторизации (в порядке приоритета):
    1. Bearer token (если передан) - пропускает CSRF, не нужна session cookie
    2. CSRF token (новые версии 3x-ui) - GET /csrf-token + POST /login с X-CSRF-Token header
    3. Legacy метод (старые версии) - POST /panel/login или /login

    Args:
        session: requests.Session для хранения cookie между запросами.
        base_url: Базовый URL вида ``https://host:port[/base_path]``.
        username: Логин пользователя node panel.
        password: Пароль пользователя node panel (уже расшифрованный).
        bearer_token: (Optional) API token для Bearer авторизации. Если передан, 
                     используется вместо username/password. Пропускает CSRF.
        timeout: Timeout для HTTP запросов.
        retries: Количество retry для HTTP запросов.

    Returns:
        True если авторизация прошла успешно, False иначе.
    """
    # Метод 1: Bearer token (если передан)
    if bearer_token:
        logger.debug("Attempting Bearer token authentication")
        if _validate_bearer_token(session, base_url, bearer_token, timeout, retries):
            logger.info("node panel Bearer token authentication succeeded")
            # Сохраняем token в session для последующих запросов
            session.headers.update({"Authorization": f"Bearer {bearer_token}"})
            return True
        logger.debug("Bearer token validation failed, falling back to credential auth")

    if not username and not password:
        logger.warning("Bearer token authentication failed and no fallback credentials provided")
        return False

    return _do_credential_login(session, base_url, username, password, timeout, retries).get("ok", False)


def _validate_bearer_token(
    session: requests.Session,
    base_url: str,
    bearer_token: str,
    timeout: float | None,
    retries: int | None,
) -> bool:
    """Валидировать Bearer token через API запрос к /panel/api/inbounds/list.

    Returns:
        True если token валиден, False иначе.
    """
    try:
        resp = xui_request(
            session,
            "GET",
            join_panel_url(base_url, "/panel/api/inbounds/list"),
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=timeout,
            retries=retries,
        )
    except requests.RequestException as exc:
        logger.debug(f"Bearer token validation request failed: {exc}")
        return False

    if resp.status_code != 200:
        logger.debug(
            f"Bearer token validation returned status {resp.status_code}"
        )
        return False

    # Проверить что это валидный ответ API
    try:
        data = resp.json()
        if not data.get("success", False):
            logger.debug("Bearer token validation returned success=false")
            return False
    except ValueError:
        logger.debug("Bearer token validation response is not JSON")
        return False

    logger.debug("Bearer token validation successful")
    return True


def _try_csrf_login(
    session: requests.Session,
    base_url: str,
    credentials: Dict[str, str],
    timeout: float | None,
    retries: int | None,
) -> Dict[str, Any] | None:
    """Попытка логина через CSRF token.

    Returns:
        Детальный result-dict при успехе или явной ошибке авторизации,
        None если CSRF не поддерживается (fallback на legacy).
    """
    try:
        resp = xui_request(session, "GET", join_panel_url(base_url, "/csrf-token"), timeout=timeout, retries=retries)
    except requests.RequestException as exc:
        logger.debug("Could not fetch CSRF token from %s: %s", base_url, exc)
        return None

    if resp.status_code != 200:
        logger.debug("CSRF endpoint %s returned %s, not supported", base_url, resp.status_code)
        return None

    try:
        csrf_token = resp.json().get("obj")
        if not csrf_token:
            return None
    except ValueError:
        return None

    logger.debug("Got CSRF token for %s, attempting login", base_url)

    for login_path in ("/login", "/panel/login"):
        url = join_panel_url(base_url, login_path)
        try:
            resp = xui_request(
                session, "POST", url,
                data=credentials,
                headers={"X-CSRF-Token": csrf_token},
                timeout=timeout, retries=retries,
            )
        except requests.RequestException as exc:
            logger.debug("CSRF login request to %s failed: %s", url, exc)
            continue

        if resp.status_code == 404:
            continue
        if resp.status_code != 200:
            logger.debug("CSRF login at %s returned %s", url, resp.status_code)
            continue

        try:
            data = resp.json()
            if not data.get("success", True):
                return {
                    "ok": False, "status_code": int(resp.status_code),
                    "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                    "error": str(data.get("msg") or "Login failed"),
                    "login_url": url,
                }
        except ValueError:
            pass

        # Persist CSRF token on session so all subsequent POST/PUT/DELETE carry it
        session.headers.update({"X-CSRF-Token": csrf_token})
        logger.info("CSRF login succeeded at %s (CSRF token pinned to session)", url)
        return {"ok": True, "status_code": int(resp.status_code), "reason": "ok", "error": "", "login_url": url}

    logger.debug("CSRF token obtained but login failed at all paths, falling back to legacy")
    return None


def _try_legacy_login(
    session: requests.Session,
    base_url: str,
    credentials: Dict[str, str],
    timeout: float | None,
    retries: int | None,
) -> Dict[str, Any]:
    """Попытка логина без CSRF (старый метод). Пробует все пути перед возвратом ошибки."""
    last_error: Dict[str, Any] | None = None

    for login_path in ("/panel/login", "/login"):
        url = join_panel_url(base_url, login_path)
        try:
            resp = xui_request(
                session, "POST", url,
                data=credentials,
                timeout=timeout, retries=retries,
            )
        except requests.RequestException as exc:
            logger.debug("Login request to %s failed: %s", url, exc)
            last_error = {
                "ok": False, "status_code": None,
                "reason": _infer_login_failure_reason(None, "", exc),
                "error": str(exc), "login_url": url,
            }
            continue

        if resp.status_code == 404:
            continue
        if resp.status_code != 200:
            last_error = {
                "ok": False, "status_code": int(resp.status_code),
                "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                "error": f"HTTP {resp.status_code}", "login_url": url,
            }
            continue

        try:
            data = resp.json()
            if not data.get("success", True):
                return {
                    "ok": False, "status_code": int(resp.status_code),
                    "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                    "error": str(data.get("msg") or "Login failed"),
                    "login_url": url,
                }
        except ValueError:
            pass

        logger.info("Legacy login succeeded at %s", url)
        return {"ok": True, "status_code": int(resp.status_code), "reason": "ok", "error": "", "login_url": url}

    if last_error:
        return last_error
    logger.warning("node panel login failed at all paths for %s", base_url)
    return {"ok": False, "status_code": 404, "reason": "login_endpoint_not_found",
            "error": "Login endpoint not found", "login_url": join_panel_url(base_url, "/login")}


def _do_credential_login(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    timeout: float | None,
    retries: int | None,
) -> Dict[str, Any]:
    """Единая реализация авторизации по credentials (CSRF → legacy).

    Возвращает детальный result-dict. Используется обеими публичными функциями.
    """
    credentials = {"username": username, "password": password}
    with _AUTH_METHOD_CACHE_LOCK:
        known_method = _AUTH_METHOD_CACHE.get(base_url)

    if known_method != "legacy":
        csrf_result = _try_csrf_login(session, base_url, credentials, timeout, retries)
        if csrf_result is not None:
            if csrf_result.get("ok"):
                _cache_auth_method(base_url, "csrf")
                return csrf_result
            # CSRF endpoint ответил, но credentials неверны (success=false).
            # Сервер явно отклонил пароль — legacy не поможет с теми же credentials.
            # Возвращаем ошибку только если статус был явным auth-failure, иначе пробуем legacy.
            reason = csrf_result.get("reason", "")
            if reason in ("auth_failed", "two_factor_required"):
                return csrf_result
            # Для прочих ошибок (сетевые, временные) — даём legacy шанс

    result = _try_legacy_login(session, base_url, credentials, timeout, retries)
    if result.get("ok"):
        _cache_auth_method(base_url, "legacy")
    return result


def login_panel_detailed(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
    *,
    bearer_token: str | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> Dict[str, Any]:
    """Детальный логин с информацией об ошибке. Поддерживает Bearer, CSRF и legacy методы."""
    # Метод 1: Bearer token (если передан)
    if bearer_token:
        logger.debug("Attempting Bearer token authentication (detailed)")
        if _validate_bearer_token(session, base_url, bearer_token, timeout, retries):
            logger.info("Bearer token authentication succeeded (detailed)")
            session.headers.update({"Authorization": f"Bearer {bearer_token}"})
            return {
                "ok": True,
                "status_code": 200,
                "reason": "bearer_token_validated",
                "error": "",
                "login_url": join_panel_url(base_url, "/panel/api"),
            }
        logger.debug("Bearer token validation failed (detailed), falling back to credential auth")

    if not username and not password:
        return {
            "ok": False,
            "status_code": None,
            "reason": "bearer_token_invalid",
            "error": "Bearer token authentication failed and no fallback credentials provided",
            "login_url": join_panel_url(base_url, "/panel/api"),
        }

    return _do_credential_login(session, base_url, username, password, timeout, retries)
