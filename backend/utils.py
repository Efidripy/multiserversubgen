"""
Общие утилиты бэкенда
"""
import json
import logging

logger = logging.getLogger("sub_manager")


def parse_field_as_dict(value, *, node_id=None, field_name=None) -> dict:
    """Безопасно привести значение поля к dict.

    Обрабатывает три варианта, которые node panel может вернуть для полей
    ``settings``, ``streamSettings``, ``sniffing`` и аналогичных:

    * ``None``  → ``{}``
    * ``dict``  → возвращает как есть
    * ``str``   → пытается распарсить через ``json.loads``; при ошибке
                  логирует предупреждение и возвращает ``{}``
    * остальное → ``{}``

    Args:
        value: Значение поля для парсинга.
        node_id: Идентификатор узла — используется в сообщении лога.
        field_name: Имя поля — используется в сообщении лога.

    Returns:
        dict — всегда dict, никогда не кидает исключений наружу.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
            logger.warning(
                "Expected dict from JSON for field %r on node %r, got %s",
                field_name, node_id, type(parsed).__name__,
            )
        except (TypeError, ValueError) as exc:
            logger.warning(
                "Failed to parse JSON for field %r on node %r: %s",
                field_name, node_id, exc,
            )
        return {}
    return {}
