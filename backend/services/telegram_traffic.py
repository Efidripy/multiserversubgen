"""Customer-scoped traffic ledger sourced from the existing read-only cache."""

from __future__ import annotations

from typing import Any, Callable

from services.telegram_registry import CustomerTrafficLedger, TelegramRegistry


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


class TelegramTrafficService:
    """Never triggers a node fetch; records only an existing client projection."""

    def __init__(self, registry: TelegramRegistry, projection_loader: Callable[[], dict[str, Any]] | None):
        self._registry = registry
        self._projection_loader = projection_loader

    def refresh_for_access(self, *, customer_id: int, email: str) -> CustomerTrafficLedger:
        if not self._projection_loader:
            return self._registry.get_customer_traffic(customer_id)
        try:
            projection = self._projection_loader()
            stats = projection.get("stats") if isinstance(projection, dict) else None
            entry = stats.get(email.casefold()) if isinstance(stats, dict) else None
            if not isinstance(entry, dict):
                entry = stats.get(email) if isinstance(stats, dict) else None
            if not isinstance(entry, dict):
                return self._registry.get_customer_traffic(customer_id)
            total = _nonnegative_int(entry.get("total"))
            if total == 0:
                total = _nonnegative_int(entry.get("up")) + _nonnegative_int(entry.get("down"))
            return self._registry.observe_customer_traffic(customer_id=customer_id, observed_bytes=total)
        except Exception:
            return self._registry.get_customer_traffic(customer_id)
