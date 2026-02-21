"""
Вспомогательный модуль для работы с 3X-UI API.
Централизует логику авторизации с поддержкой sub-path установок.
"""
import logging
import requests

logger = logging.getLogger("sub_manager")


def login_3xui(session: requests.Session, base_url: str, username: str, password: str) -> bool:
    """Авторизоваться на 3X-UI панели.

    Сначала пробует ``POST {base_url}/panel/login`` (корректный путь для
    установок под подпутём), при получении 404 делает fallback на
    ``POST {base_url}/login`` (стандартный путь без подпутья).

    Args:
        session: requests.Session для хранения cookie между запросами.
        base_url: Базовый URL вида ``https://host:port[/base_path]``.
        username: Логин пользователя 3X-UI.
        password: Пароль пользователя 3X-UI (уже расшифрованный).

    Returns:
        True если авторизация прошла успешно, False иначе.
    """
    credentials = {"username": username, "password": password}

    for login_path in ("/panel/login", "/login"):
        url = f"{base_url}{login_path}"
        try:
            resp = session.post(url, data=credentials, timeout=5)
        except requests.RequestException as exc:
            logger.warning(f"3X-UI login request to {url} failed: {exc}")
            return False

        if resp.status_code == 404 and login_path == "/panel/login":
            # Установка без подпутья — пробуем legacy-путь
            logger.debug(f"3X-UI {url} returned 404, trying legacy /login")
            continue

        if resp.status_code != 200:
            logger.warning(
                f"3X-UI login at {url} returned status {resp.status_code}; "
                f"response (first 200 chars): {resp.text[:200]!r}"
            )
            return False

        # Попытка определить успех через JSON (если панель отвечает JSON)
        try:
            data = resp.json()
            if not data.get("success", True):
                logger.warning(
                    f"3X-UI login at {url} returned success=false; "
                    f"response (first 200 chars): {resp.text[:200]!r}"
                )
                return False
        except ValueError:
            pass  # Ответ не JSON — считаем успехом если статус 200

        logger.debug(f"3X-UI login succeeded at {url}")
        return True

    return False
