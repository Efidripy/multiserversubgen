"""Customer-scoped traffic ledger sourced from the existing read-only cache."""

from __future__ import annotations

import hashlib
import json
from threading import Lock
from typing import Any, Callable

from services.telegram_registry import TelegramRegistry


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

        observed: dict[int, dict[tuple[int, int], int]] = {}
        for customer_id, customer_bindings in bindings.items():
            customer_observed: dict[tuple[int, int], int] = {}
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
                value = _nonnegative_int(client.get("up")) + _nonnegative_int(
                    client.get("down")
                )
                customer_observed[(binding.node_id, binding.inbound_id)] = value
            if complete:
                observed[customer_id] = customer_observed

        if not observed:
            return 0
        digest_payload = sorted(
            (
                customer_id,
                sorted(
                    (node_id, inbound_id, value)
                    for (node_id, inbound_id), value in customer_observed.items()
                ),
            )
            for customer_id, customer_observed in observed.items()
        )
        digest = hashlib.sha256(
            json.dumps(digest_payload, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._reconcile_lock:
            if digest == self._last_observation_digest:
                return 0
            updated = self._registry.observe_customer_traffic_bindings(observed)
            self._last_observation_digest = digest
            return len(updated)
