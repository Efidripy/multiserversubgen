"""Admin-only HTTP surface for the shared Telegram provisioning policy."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Dict

from fastapi import APIRouter, HTTPException, Request

from services.telegram_registry import (
    IdempotencyConflictError,
    NodePolicyUnavailableError,
    TelegramRegistry,
    TelegramRegistryError,
    VersionConflictError,
)


def _inbound_one_supports_bot_contract(node_id: int, inbound_options: list[Dict]) -> bool:
    """Accept only enabled VLESS inbound #1 with explicit flow capability."""

    for inbound in inbound_options:
        if not isinstance(inbound, dict):
            continue
        if inbound.get("node_id") != node_id or inbound.get("id") != 1:
            continue
        return (
            bool(inbound.get("enable"))
            and str(inbound.get("protocol") or "").lower() == "vless"
            and bool(inbound.get("tlsFlowCapable"))
        )
    return False


def build_telegram_admin_router(
    *,
    check_auth: Callable[[Request], str | None],
    get_user_role: Callable[[str], str],
    db_path: str,
    list_nodes: Callable[[], list[Dict]],
    get_cached_inbound_options: Callable[[list[Dict]], list[Dict]],
):
    router = APIRouter()
    registry = TelegramRegistry(db_path)

    def require_admin(request: Request) -> str:
        username = check_auth(request)
        if not username:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if get_user_role(username) != "admin":
            raise HTTPException(status_code=403, detail="Telegram administration requires admin role")
        return username

    @router.get("/api/v1/telegram/node-policies")
    def list_node_policies(request: Request):
        require_admin(request)
        return {
            "items": [asdict(policy) for policy in registry.list_node_provisioning_policies()],
            "fixed_contract": {"inbound_id": 1, "flow": "xtls-rprx-vision"},
        }

    @router.put("/api/v1/telegram/node-policies/{node_id}")
    def set_node_policy(node_id: int, request: Request, data: Dict):
        username = require_admin(request)
        provisioning_enabled = data.get("provisioning_enabled")
        if not isinstance(provisioning_enabled, bool):
            raise HTTPException(status_code=400, detail="provisioning_enabled must be a boolean")

        compatible = False
        if provisioning_enabled:
            try:
                compatible = _inbound_one_supports_bot_contract(
                    node_id, get_cached_inbound_options(list_nodes())
                )
            except Exception:
                # Do not enable if the runtime cannot prove the exact target.
                raise HTTPException(
                    status_code=409,
                    detail="Cannot validate inbound 1 compatibility for this node",
                )

        try:
            policy = registry.set_node_provisioning_policy(
                node_id=node_id,
                provisioning_enabled=provisioning_enabled,
                total_bytes=data.get("total_bytes"),
                validity_days=data.get("validity_days"),
                client_enabled=data.get("client_enabled"),
                expected_policy_version=data.get("expected_policy_version"),
                idempotency_key=data.get("idempotency_key"),
                updated_by=username,
                node_is_compatible=compatible,
            )
        except (VersionConflictError, IdempotencyConflictError, NodePolicyUnavailableError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TelegramRegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "policy": asdict(policy),
            "fixed_contract": {"inbound_id": 1, "flow": "xtls-rprx-vision"},
        }

    return router
