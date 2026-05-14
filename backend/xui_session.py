"""
Вспомогательный модуль для работы с node panel API.
Централизует логику авторизации с поддержкой sub-path установок.
"""
import logging
import os
import time
import requests
from typing import Any, Dict

logger = logging.getLogger("sub_manager")


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


# Default to VERIFY_TLS=false to support self-signed certificates
# Can be overridden with VERIFY_TLS=true environment variable
VERIFY_TLS = os.getenv("VERIFY_TLS", "false").strip().lower() in ("1", "true", "yes", "on")

XUI_HTTP_TIMEOUT_SEC = max(1.0, _env_float("XUI_HTTP_TIMEOUT_SEC", 12.0))
XUI_HTTP_RETRIES = max(0, _env_int("XUI_HTTP_RETRIES", 2))
XUI_HTTP_RETRY_BACKOFF_SEC = max(0.0, _env_float("XUI_HTTP_RETRY_BACKOFF_SEC", 0.35))
XUI_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}
XUI_FAST_TIMEOUT_SEC = max(1.0, _env_float("XUI_FAST_TIMEOUT_SEC", 5.0))
XUI_FAST_RETRIES = max(0, _env_int("XUI_FAST_RETRIES", 0))


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
    actual_timeout = XUI_HTTP_TIMEOUT_SEC if timeout is None else float(timeout)
    retry_budget = XUI_HTTP_RETRIES if retries is None else max(0, int(retries))
    attempts = retry_budget + 1
    last_exc: Exception | None = None

    for attempt in range(attempts):
        try:
            response = session.request(
                method=method.upper(),
                url=url,
                timeout=actual_timeout,
                **kwargs,
            )
            if (
                response.status_code in XUI_HTTP_RETRY_STATUSES
                and attempt < attempts - 1
            ):
                sleep_for = XUI_HTTP_RETRY_BACKOFF_SEC * (2 ** attempt)
                if sleep_for > 0:
                    time.sleep(sleep_for)
                continue
            return response
        except requests.RequestException as exc:
            last_exc = exc
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
        logger.debug(f"Attempting Bearer token authentication")
        if _validate_bearer_token(session, base_url, bearer_token, timeout, retries):
            logger.info("node panel Bearer token authentication succeeded")
            # Сохраняем token в session для последующих запросов
            session.headers.update({"Authorization": f"Bearer {bearer_token}"})
            return True
        logger.debug("Bearer token validation failed, falling back to credential auth")

    credentials = {"username": username, "password": password}

    # Метод 2: CSRF token (новые версии)
    csrf_login_result = _try_login_with_csrf(
        session, base_url, credentials, timeout, retries
    )
    if csrf_login_result is not None:
        return csrf_login_result

    # Метод 3: Legacy метод (старые версии, без CSRF)
    logger.debug("node panel CSRF login failed or not supported, trying legacy method")
    return _try_login_legacy(session, base_url, credentials, timeout, retries)


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
            f"{base_url}/panel/api/inbounds/list",
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


def _try_login_with_csrf(
    session: requests.Session,
    base_url: str,
    credentials: Dict[str, str],
    timeout: float | None,
    retries: int | None,
) -> bool | None:
    """Попытка логина с CSRF token (новый метод).

    Returns:
        True если вошли, False если ошибка, None если CSRF не поддерживается.
    """
    # Шаг 1: Получить CSRF token
    csrf_url = f"{base_url}/csrf-token"
    try:
        resp = xui_request(session, "GET", csrf_url, timeout=timeout, retries=retries)
    except requests.RequestException as exc:
        logger.debug(f"Could not fetch CSRF token from {csrf_url}: {exc}")
        return None

    if resp.status_code != 200:
        logger.debug(f"CSRF endpoint {csrf_url} returned {resp.status_code}, CSRF not supported")
        return None

    # Попытка извлечь CSRF token из JSON
    try:
        csrf_data = resp.json()
        csrf_token = csrf_data.get("obj")
        if not csrf_token:
            logger.debug("CSRF response has no 'obj' field, CSRF not supported")
            return None
    except ValueError:
        logger.debug("CSRF response is not JSON, CSRF not supported")
        return None

    logger.debug(f"Got CSRF token, attempting login with token")

    # Шаг 2: Логин с CSRF token
    for login_path in ("/login", "/panel/login"):
        url = f"{base_url}{login_path}"

        try:
            resp = xui_request(
                session,
                "POST",
                url,
                data=credentials,
                headers={"X-CSRF-Token": csrf_token},
                timeout=timeout,
                retries=retries,
            )
        except requests.RequestException as exc:
            logger.debug(f"CSRF login request to {url} failed: {exc}")
            continue

        if resp.status_code == 404:
            logger.debug(f"CSRF login path {url} not found, trying next path")
            continue

        if resp.status_code != 200:
            logger.debug(
                f"CSRF login at {url} returned {resp.status_code}; "
                f"response: {resp.text[:100]!r}"
            )
            continue

        # Проверить успех через JSON
        try:
            data = resp.json()
            if not data.get("success", True):
                logger.debug(f"CSRF login returned success=false: {resp.text[:100]}")
                continue
        except ValueError:
            pass  # Не JSON — считаем успехом если статус 200

        logger.info(f"node panel CSRF login succeeded at {url}")
        return True

    # CSRF токен получен, но логин не удался
    logger.debug("CSRF token obtained but login failed at all paths")
    return False


def _try_login_legacy(
    session: requests.Session,
    base_url: str,
    credentials: Dict[str, str],
    timeout: float | None,
    retries: int | None,
) -> bool:
    """Попытка логина без CSRF token (старый метод, для совместимости).

    Returns:
        True если вошли, False иначе.
    """
    for login_path in ("/panel/login", "/login"):
        url = f"{base_url}{login_path}"
        try:
            resp = xui_request(
                session,
                "POST",
                url,
                data=credentials,
                timeout=timeout,
                retries=retries,
            )
        except requests.RequestException as exc:
            logger.debug(f"node panel login request to {url} failed: {exc}")
            continue

        if resp.status_code == 404:
            logger.debug(f"node panel login path {url} returned 404, trying next path")
            continue

        if resp.status_code != 200:
            logger.debug(
                f"node panel login at {url} returned status {resp.status_code}; "
                f"response: {resp.text[:100]!r}"
            )
            continue

        # Попытка определить успех через JSON (если панель отвечает JSON)
        try:
            data = resp.json()
            if not data.get("success", True):
                logger.debug(
                    f"node panel login at {url} returned success=false"
                )
                continue
        except ValueError:
            pass  # Ответ не JSON — считаем успехом если статус 200

        logger.info(f"node panel login (legacy) succeeded at {url}")
        return True

    logger.warning(f"node panel login failed at all paths for {base_url}")
    return False


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
                "login_url": f"{base_url}/panel/api",
            }
        logger.debug("Bearer token validation failed (detailed), falling back to credential auth")

    credentials = {"username": username, "password": password}

    # Сначала пробуем CSRF метод
    csrf_result = _try_login_with_csrf_detailed(session, base_url, credentials, timeout, retries)
    if csrf_result is not None:
        return csrf_result

    # Fallback на legacy метод
    logger.debug("CSRF login failed or not supported, trying legacy method")
    return _try_login_legacy_detailed(session, base_url, credentials, timeout, retries)


def _try_login_with_csrf_detailed(
    session: requests.Session,
    base_url: str,
    credentials: Dict[str, str],
    timeout: float | None,
    retries: int | None,
) -> Dict[str, Any] | None:
    """При CSRF методе. Returns result dict if ok/error, None if not supported."""
    # Получить CSRF токен
    csrf_url = f"{base_url}/csrf-token"
    try:
        resp = xui_request(session, "GET", csrf_url, timeout=timeout, retries=retries)
    except requests.RequestException as exc:
        logger.debug(f"Could not fetch CSRF token: {exc}")
        return None

    if resp.status_code != 200:
        logger.debug(f"CSRF endpoint returned {resp.status_code}, not supported")
        return None

    try:
        csrf_data = resp.json()
        csrf_token = csrf_data.get("obj")
        if not csrf_token:
            return None
    except ValueError:
        return None

    # Логин с CSRF
    for login_path in ("/login", "/panel/login"):
        url = f"{base_url}{login_path}"
        try:
            resp = xui_request(
                session,
                "POST",
                url,
                data=credentials,
                headers={"X-CSRF-Token": csrf_token},
                timeout=timeout,
                retries=retries,
            )
        except requests.RequestException as exc:
            logger.debug(f"CSRF login request failed: {exc}")
            continue

        if resp.status_code == 404:
            continue

        if resp.status_code != 200:
            return {
                "ok": False,
                "status_code": int(resp.status_code),
                "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                "error": f"HTTP {resp.status_code}",
                "login_url": url,
            }

        try:
            data = resp.json()
            if not data.get("success", True):
                return {
                    "ok": False,
                    "status_code": int(resp.status_code),
                    "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                    "error": str(data.get("msg") or "Login failed"),
                    "login_url": url,
                }
        except ValueError:
            pass

        logger.info(f"CSRF login succeeded at {url}")
        return {
            "ok": True,
            "status_code": int(resp.status_code),
            "reason": "ok",
            "error": "",
            "login_url": url,
        }

    # CSRF токен получен но логин не вышел
    return {
        "ok": False,
        "status_code": None,
        "reason": "csrf_login_failed",
        "error": "CSRF token obtained but login failed",
        "login_url": f"{base_url}/login",
    }


def _try_login_legacy_detailed(
    session: requests.Session,
    base_url: str,
    credentials: Dict[str, str],
    timeout: float | None,
    retries: int | None,
) -> Dict[str, Any]:
    """Legacy логин без CSRF."""
    for login_path in ("/panel/login", "/login"):
        url = f"{base_url}{login_path}"
        try:
            resp = xui_request(
                session,
                "POST",
                url,
                data=credentials,
                timeout=timeout,
                retries=retries,
            )
        except requests.RequestException as exc:
            logger.debug(f"Login request to {url} failed: {exc}")
            return {
                "ok": False,
                "status_code": None,
                "reason": _infer_login_failure_reason(None, "", exc),
                "error": str(exc),
                "login_url": url,
            }

        if resp.status_code == 404:
            continue

        if resp.status_code != 200:
            return {
                "ok": False,
                "status_code": int(resp.status_code),
                "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                "error": f"HTTP {resp.status_code}",
                "login_url": url,
            }

        try:
            data = resp.json()
            if not data.get("success", True):
                return {
                    "ok": False,
                    "status_code": int(resp.status_code),
                    "reason": _infer_login_failure_reason(int(resp.status_code), resp.text),
                    "error": str(data.get("msg") or "Login failed"),
                    "login_url": url,
                }
        except ValueError:
            pass

        logger.info(f"Legacy login succeeded at {url}")
        return {
            "ok": True,
            "status_code": int(resp.status_code),
            "reason": "ok",
            "error": "",
            "login_url": url,
        }

    return {
        "ok": False,
        "status_code": 404,
        "reason": "login_endpoint_not_found",
        "error": "Login endpoint not found",
        "login_url": f"{base_url}/login",
    }
