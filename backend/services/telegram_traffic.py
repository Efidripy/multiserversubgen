"""Customer-scoped traffic ledger sourced from the existing read-only cache."""

from __future__ import annotations

import hashlib
import json
from threading import Lock
from typing import Any, Callable

from services.telegram_registry import CustomerTrafficLedger, TelegramRegistry


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _node_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class TelegramTrafficService:
    """Never triggers a node fetch; records only an existing client projection."""

    def __init__(
        self,
        registry: TelegramRegistry,
        projection_loader: Callable[[], dict[str, Any]] | None,
    ):
        self._registry = registry
        self._projection_loader = projection_loader
        self._reconcile_lock = Lock()
        self._last_observation_digest = ""

    def refresh_for_access(
        self, *, customer_id: int, email: str
    ) -> CustomerTrafficLedger:
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
                total = _nonnegative_int(entry.get("up")) + _nonnegative_int(
                    entry.get("down")
                )
            return self._registry.observe_customer_traffic(
                customer_id=customer_id, observed_bytes=total
            )
        except Exception:
            return self._registry.get_customer_traffic(customer_id)

    def reconcile_collector_snapshot(self, snapshot: dict[str, Any]) -> int:
        """Observe complete exact bindings from an already collected snapshot.

        This method is deliberately local-only.  It never calls XUI or asks the
        collector to refresh.  One customer is observed only when every current
        confirmed binding has exactly one matching `clientStats` record on its
        bound node and inbound.  Missing, unavailable, stale or duplicate
        records leave the existing ledger untouched instead of manufacturing a
        zero or a partial lifetime total.
        """

        bindings = self._registry.list_customer_traffic_observation_bindings()
        if not bindings or not isinstance(snapshot, dict):
            return 0
        nodes = snapshot.get("nodes")
        if not isinstance(nodes, list):
            return 0

        nodes_by_id: dict[int, dict[str, Any]] = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = _node_id(node.get("node_id", node.get("id")))
            if node_id is None or node_id in nodes_by_id:
                return 0
            nodes_by_id[node_id] = node

        observed: dict[int, int] = {}
        for customer_id, customer_bindings in bindings.items():
            total = 0
            complete = True
            for binding in customer_bindings:
                node = nodes_by_id.get(binding.node_id)
                if (
                    not isinstance(node, dict)
                    or not bool(node.get("available"))
                    or node.get("inbounds_available") is False
                ):
                    complete = False
                    break
                inbounds = node.get("inbounds")
                if not isinstance(inbounds, list):
                    complete = False
                    break
                matching_inbounds = [
                    inbound
                    for inbound in inbounds
                    if isinstance(inbound, dict)
                    and _node_id(inbound.get("id")) == binding.inbound_id
                ]
                if len(matching_inbounds) != 1:
                    complete = False
                    break
                client_stats = matching_inbounds[0].get("clientStats")
                if not isinstance(client_stats, list):
                    complete = False
                    break
                matching_clients = [
                    client
                    for client in client_stats
                    if isinstance(client, dict)
                    and str(client.get("email") or "").strip().casefold()
                    == binding.remote_email.casefold()
                ]
                if len(matching_clients) != 1:
                    complete = False
                    break
                client = matching_clients[0]
                value = _nonnegative_int(client.get("total"))
                if value == 0:
                    value = _nonnegative_int(client.get("up")) + _nonnegative_int(
                        client.get("down")
                    )
                total += value
            if complete:
                observed[customer_id] = total

        if not observed:
            return 0
        digest = hashlib.sha256(
            json.dumps(sorted(observed.items()), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._reconcile_lock:
            if digest == self._last_observation_digest:
                return 0
            updated = self._registry.observe_customer_traffic_batch(observed)
            self._last_observation_digest = digest
            return len(updated)
