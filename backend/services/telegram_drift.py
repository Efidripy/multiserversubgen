"""Read-only Telegram binding drift discovery.

The scanner uses the strict per-node reader.  It never treats a failed node
read as an empty projection and never creates, enables, suspends or deletes a
remote client.  An intentional absence from a Telegram-enabled node is not a
finding; only a confirmed local binding that no longer matches remote state or
an already-present remote record without a local binding is reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from services.telegram_registry import TelegramRegistry, canonicalize_email


@dataclass(frozen=True)
class DriftScanResult:
    scanned_node_ids: tuple[int, ...]
    unavailable_node_ids: tuple[int, ...]
    finding_count: int


class TelegramDriftScanner:
    def __init__(self, *, registry: TelegramRegistry, list_nodes: Callable[[], list[dict[str, Any]]], client_manager: Any):
        self._registry = registry
        self._list_nodes = list_nodes
        self._client_manager = client_manager

    @staticmethod
    def _inbound_one_rows(rows: object) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            raise RuntimeError("strict client reader returned an invalid result")
        result: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            inbound_ids = row.get("inbound_ids") if isinstance(row.get("inbound_ids"), list) else []
            if row.get("inbound_id") != 1 and 1 not in inbound_ids:
                continue
            client_id = str(row.get("id") or "").strip()
            email = str(row.get("email") or "").strip()
            sub_id = str(row.get("subId") or "").strip()
            if not client_id or not email:
                continue
            try:
                canonicalize_email(email)
            except Exception:
                continue
            result.append({
                "remote_client_id": client_id,
                "remote_email": email,
                "remote_sub_id": sub_id,
                "remote_enabled": bool(row.get("enable", True)),
                "flow": str(row.get("flow") or ""),
            })
        return result

    def scan(self, *, node_ids: object = None) -> DriftScanResult:
        inventory = self._registry.drift_inventory(node_ids=node_ids)
        desired_nodes = {int(item["node_id"]): item for item in inventory["nodes"]}
        live_nodes = {int(node.get("id")): node for node in self._list_nodes() if isinstance(node, dict) and node.get("id")}
        bindings_by_node: dict[int, list[dict[str, Any]]] = {}
        for binding in inventory["bindings"]:
            bindings_by_node.setdefault(int(binding["node_id"]), []).append(binding)
        customers_by_email = {str(item["email_canonical"]): item for item in inventory["customers"]}

        scanned: list[int] = []
        unavailable: list[int] = []
        findings: list[dict[str, Any]] = []
        for node_id in desired_nodes:
            node = live_nodes.get(node_id)
            if node is None:
                unavailable.append(node_id)
                continue
            try:
                remote_rows = self._inbound_one_rows(self._client_manager.get_node_clients_strict(node))
            except Exception:
                unavailable.append(node_id)
                continue
            scanned.append(node_id)
            remote_by_identity = {
                (row["remote_client_id"], row["remote_sub_id"], canonicalize_email(row["remote_email"])): row
                for row in remote_rows
            }
            remote_by_email: dict[str, list[dict[str, Any]]] = {}
            for row in remote_rows:
                remote_by_email.setdefault(canonicalize_email(row["remote_email"]), []).append(row)
            local_binding_ids: set[tuple[str, str, str]] = set()
            local_bound_customer_ids: set[int] = set()
            for binding in bindings_by_node.get(node_id, []):
                identity = (
                    str(binding["remote_client_id"]), str(binding["remote_sub_id"]),
                    canonicalize_email(str(binding["remote_email"])),
                )
                local_binding_ids.add(identity)
                local_bound_customer_ids.add(int(binding["customer_id"]))
                if identity not in remote_by_identity:
                    same_email = remote_by_email.get(identity[2], [])
                    findings.append({
                        "kind": "binding_conflict" if same_email else "binding_missing",
                        "customer_id": int(binding["customer_id"]), "node_id": node_id,
                        "remote_email": str(binding["remote_email"]),
                        "remote_client_id": str(binding["remote_client_id"]),
                        "remote_sub_id": str(binding["remote_sub_id"]),
                        "details": {"same_email_candidates": len(same_email)},
                    })
            for remote in remote_rows:
                canonical = canonicalize_email(remote["remote_email"])
                customer = customers_by_email.get(canonical)
                identity = (remote["remote_client_id"], remote["remote_sub_id"], canonical)
                if customer is None or int(customer["customer_id"]) in local_bound_customer_ids or identity in local_binding_ids:
                    continue
                # A candidate remains adoptable only when it already conforms
                # to the fixed bot contract.  Other manual records are shown
                # nowhere and remain outside Telegram management.
                if remote["flow"] != "xtls-rprx-vision":
                    continue
                findings.append({
                    "kind": "orphan_remote", "customer_id": int(customer["customer_id"]), "node_id": node_id,
                    "remote_email": remote["remote_email"], "remote_client_id": remote["remote_client_id"],
                    "remote_sub_id": remote["remote_sub_id"],
                    "details": {"remote_enabled": remote["remote_enabled"], "flow": remote["flow"]},
                })
        recorded = self._registry.record_drift_findings(scanned_node_ids=scanned, findings=findings) if scanned else ()
        return DriftScanResult(
            scanned_node_ids=tuple(scanned), unavailable_node_ids=tuple(unavailable), finding_count=len(recorded)
        )

    def re_read_orphan(self, finding_id: int) -> dict[str, Any] | None:
        """Return the exact current remote record for an adoption re-check."""

        finding = next((item for item in self._registry.list_drift_findings(status="open", limit=200)
                        if item.finding_id == finding_id and item.kind == "orphan_remote"), None)
        if finding is None:
            return None
        node = next((item for item in self._list_nodes() if isinstance(item, dict) and item.get("id") == finding.node_id), None)
        if node is None:
            return None
        for remote in self._inbound_one_rows(self._client_manager.get_node_clients_strict(node)):
            if (
                remote["remote_client_id"] == finding.remote_client_id
                and remote["remote_sub_id"] == finding.remote_sub_id
                and canonicalize_email(remote["remote_email"]) == canonicalize_email(finding.remote_email)
                and remote["flow"] == "xtls-rprx-vision"
            ):
                return remote
        return None
