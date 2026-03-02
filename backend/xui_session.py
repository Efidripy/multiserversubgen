"""
Вспомогательный модуль для работы с node panel API.
Централизует логику авторизации с поддержкой sub-path установок.
"""
import logging
import os
import time
import requests

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


XUI_HTTP_TIMEOUT_SEC = max(1.0, _env_float("XUI_HTTP_TIMEOUT_SEC", 12.0))
XUI_HTTP_RETRIES = max(0, _env_int("XUI_HTTP_RETRIES", 2))
XUI_HTTP_RETRY_BACKOFF_SEC = max(0.0, _env_float("XUI_HTTP_RETRY_BACKOFF_SEC", 0.35))
XUI_HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}


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


def login_panel(session: requests.Session, base_url: str, username: str, password: str) -> bool:
    """Авторизоваться на node panel панели.

    Сначала пробует ``POST {base_url}/panel/login`` (корректный путь для
    установок под подпутём), при получении 404 делает fallback на
    ``POST {base_url}/login`` (стандартный путь без подпутья).

    Args:
        session: requests.Session для хранения cookie между запросами.
        base_url: Базовый URL вида ``https://host:port[/base_path]``.
        username: Логин пользователя node panel.
        password: Пароль пользователя node panel (уже расшифрованный).

    Returns:
        True если авторизация прошла успешно, False иначе.
    """
    credentials = {"username": username, "password": password}

    for login_path in ("/panel/login", "/login"):
        url = f"{base_url}{login_path}"
        try:
            resp = xui_request(
                session,
                "POST",
                url,
                data=credentials,
            )
        except requests.RequestException as exc:
            logger.warning(f"node panel login request to {url} failed: {exc}")
            return False

        if resp.status_code == 404 and login_path == "/panel/login":
            # Установка без подпутья — пробуем legacy-путь
            logger.debug(f"node panel {url} returned 404, trying legacy /login")
            continue

        if resp.status_code != 200:
            logger.warning(
                f"node panel login at {url} returned status {resp.status_code}; "
                f"response (first 200 chars): {resp.text[:200]!r}"
            )
            return False

        # Попытка определить успех через JSON (если панель отвечает JSON)
        try:
            data = resp.json()
            if not data.get("success", True):
                logger.warning(
                    f"node panel login at {url} returned success=false; "
                    f"response (first 200 chars): {resp.text[:200]!r}"
                )
                return False
        except ValueError:
            pass  # Ответ не JSON — считаем успехом если статус 200

        logger.debug(f"node panel login succeeded at {url}")
        return True

    return False
