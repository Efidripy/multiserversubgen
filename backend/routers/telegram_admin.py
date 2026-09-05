"""Admin-only HTTP surface for the shared Telegram provisioning policy."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Dict

from fastapi import APIRouter, HTTPException, Request

from services.telegram_registry import (
    ApprovalUnavailableError,
    IdempotencyConflictError,
    LifecycleUnavailableError,
    NodePolicyUnavailableError,
    TelegramRegistry,
    TelegramRegistryError,
    VersionConflictError,
)
from services.telegram_transport import TelegramApiTransport, TelegramTransportError


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
    telegram_settings=None,
):
    router = APIRouter()
    registry = TelegramRegistry(db_path)
    transport = TelegramApiTransport(
        db_path=db_path, local_proxy_url=getattr(telegram_settings, "local_proxy_url", "")
    )

    def require_admin(request: Request) -> str:
        username = check_auth(request)
        if not username:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if get_user_role(username) != "admin":
            raise HTTPException(status_code=403, detail="Telegram administration requires admin role")
        return username

    def translate_registry_error(exc: TelegramRegistryError) -> HTTPException:
        if isinstance(
            exc,
            (VersionConflictError, IdempotencyConflictError, ApprovalUnavailableError, LifecycleUnavailableError),
        ):
            return HTTPException(status_code=409, detail=str(exc))
        return HTTPException(status_code=400, detail=str(exc))

    @router.get("/api/v1/telegram/transport")
    def get_telegram_transport(request: Request):
        require_admin(request)
        return {"transport": asdict(transport.status())}

    @router.put("/api/v1/telegram/transport")
    def set_telegram_transport(request: Request, data: Dict):
        username = require_admin(request)
        mode = data.get("mode")
        expected_row_version = data.get("expected_row_version")
        if mode == "local_proxy":
            try:
                transport.require_local_proxy_ready()
            except TelegramTransportError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            preference = registry.set_transport_preference(
                mode=mode, expected_row_version=expected_row_version, updated_by=username
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        status = transport.status()
        if status.row_version != preference.row_version:
            raise HTTPException(status_code=409, detail="Telegram transport preference changed concurrently")
        return {"transport": asdict(status)}

    @router.get("/api/v1/telegram/requests")
    def list_pending_requests(request: Request):
        require_admin(request)
        return {"items": [asdict(item) for item in registry.list_pending_applications()]}

    @router.get("/api/v1/telegram/identities/blocked")
    def list_blocked_identities(request: Request, limit: int = 100):
        require_admin(request)
        try:
            return {"items": [asdict(item) for item in registry.list_blocked_identities(limit=limit)]}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.get("/api/v1/telegram/appeals")
    def list_telegram_appeals(request: Request, status: str = "open", limit: int = 100):
        require_admin(request)
        try:
            return {"items": [asdict(item) for item in registry.list_appeals(status=status, limit=limit)]}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.post("/api/v1/telegram/appeals/{appeal_id}/resolve")
    def resolve_telegram_appeal(appeal_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.resolve_appeal(
                appeal_id=appeal_id,
                expected_row_version=data.get("expected_row_version"),
                status=data.get("status"),
                idempotency_key=data.get("idempotency_key"),
                resolved_by=username,
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"appeal": asdict(result), "remote_io": "not_started"}

    @router.get("/api/v1/telegram/requests/{telegram_user_id}")
    def get_pending_request(telegram_user_id: int, request: Request):
        require_admin(request)
        try:
            return {"item": asdict(registry.get_pending_application(telegram_user_id))}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.post("/api/v1/telegram/requests/{telegram_user_id}/approve-new")
    def approve_new_request(telegram_user_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.approve_new_application(
                telegram_user_id=telegram_user_id,
                expected_identity_version=data.get("expected_identity_version"),
                email_display=data.get("email_display"),
                idempotency_key=data.get("idempotency_key"),
                approved_by=username,
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"approval": asdict(result), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/requests/{telegram_user_id}/approve-existing")
    def approve_existing_request(telegram_user_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.approve_existing_application(
                telegram_user_id=telegram_user_id,
                customer_id=data.get("customer_id"),
                expected_identity_version=data.get("expected_identity_version"),
                idempotency_key=data.get("idempotency_key"),
                approved_by=username,
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"approval": asdict(result), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/requests/{telegram_user_id}/reject")
    def reject_request(telegram_user_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.reject_application(
                telegram_user_id=telegram_user_id,
                expected_identity_version=data.get("expected_identity_version"),
                idempotency_key=data.get("idempotency_key"),
                rejected_by=username,
                reason=data.get("reason"),
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"identity": asdict(result)}

    @router.post("/api/v1/telegram/identities/{telegram_user_id}/block")
    def block_identity(telegram_user_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.block_identity(
                telegram_user_id=telegram_user_id,
                expected_identity_version=data.get("expected_identity_version"),
                idempotency_key=data.get("idempotency_key"),
                blocked_by=username,
                reason=data.get("reason"),
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"identity": asdict(result)}

    @router.post("/api/v1/telegram/identities/{telegram_user_id}/unblock")
    def unblock_identity(telegram_user_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.unblock_identity(
                telegram_user_id=telegram_user_id,
                expected_identity_version=data.get("expected_identity_version"),
                idempotency_key=data.get("idempotency_key"),
                unblocked_by=username,
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"identity": asdict(result)}

    @router.get("/api/v1/telegram/jobs")
    def list_provisioning_jobs(request: Request, limit: int = 100):
        require_admin(request)
        try:
            return {"items": [asdict(item) for item in registry.list_provisioning_jobs(limit=limit)]}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.get("/api/v1/telegram/jobs/{job_id}")
    def get_provisioning_job(job_id: int, request: Request):
        require_admin(request)
        try:
            return {"item": asdict(registry.get_provisioning_job(job_id))}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.post("/api/v1/telegram/jobs/{job_id}/retry")
    def retry_provisioning_job(job_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.reschedule_provisioning_job(
                job_id=job_id,
                expected_job_version=data.get("expected_job_version"),
                idempotency_key=data.get("idempotency_key"),
                requested_by=username,
                action="retry",
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"job": asdict(result), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/jobs/{job_id}/reconcile")
    def reconcile_provisioning_job(job_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.reschedule_provisioning_job(
                job_id=job_id,
                expected_job_version=data.get("expected_job_version"),
                idempotency_key=data.get("idempotency_key"),
                requested_by=username,
                action="reconcile",
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"job": asdict(result), "remote_io": "not_started"}

    @router.get("/api/v1/telegram/customers")
    def list_customers(
        request: Request,
        query: str = "",
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
        include_deleted: bool = False,
    ):
        require_admin(request)
        try:
            return asdict(
                registry.list_customers(
                    query=query,
                    status=status,
                    page=page,
                    page_size=page_size,
                    include_deleted=include_deleted,
                )
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.get("/api/v1/telegram/customers/{customer_id}")
    def get_customer(customer_id: int, request: Request):
        require_admin(request)
        try:
            return {"item": asdict(registry.get_customer(customer_id))}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.get("/api/v1/telegram/customers/{customer_id}/nodes")
    def get_customer_nodes(customer_id: int, request: Request):
        require_admin(request)
        try:
            registry.get_customer(customer_id)
            return {"items": [asdict(item) for item in registry.customer_node_matrix(customer_id)]}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.get("/api/v1/telegram/customers/{customer_id}/traffic")
    def get_customer_traffic(customer_id: int, request: Request):
        require_admin(request)
        try:
            registry.get_customer(customer_id)
            return {"traffic": asdict(registry.get_customer_traffic(customer_id))}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.post("/api/v1/telegram/customers/{customer_id}/nodes/{node_id}/add")
    def add_customer_node(customer_id: int, node_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.queue_customer_node_add(
                customer_id=customer_id,
                node_id=node_id,
                expected_customer_version=data.get("expected_customer_version"),
                idempotency_key=data.get("idempotency_key"),
                created_by=username,
            )
        except (VersionConflictError, IdempotencyConflictError, NodePolicyUnavailableError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"job": asdict(result), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/customers/{customer_id}/nodes/{node_id}/operation/preview")
    def preview_customer_node_operation(customer_id: int, node_id: int, request: Request, data: Dict):
        require_admin(request)
        try:
            preview = registry.preview_customer_node_operation(
                customer_id=customer_id,
                node_id=node_id,
                operation_type=data.get("operation_type"),
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"preview": asdict(preview), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/customers/{customer_id}/nodes/{node_id}/operation")
    def queue_customer_node_operation(customer_id: int, node_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.queue_customer_node_operation(
                customer_id=customer_id,
                node_id=node_id,
                operation_type=data.get("operation_type"),
                expected_customer_version=data.get("expected_customer_version"),
                target_snapshot_digest=data.get("target_snapshot_digest"),
                idempotency_key=data.get("idempotency_key"),
                created_by=username,
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"operation": asdict(result), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/customers/{customer_id}/lifecycle/preview")
    def preview_customer_lifecycle(customer_id: int, request: Request, data: Dict):
        require_admin(request)
        try:
            preview = registry.preview_customer_operation(
                customer_id=customer_id,
                operation_type=data.get("operation_type"),
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"preview": asdict(preview), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/customers/{customer_id}/lifecycle")
    def queue_customer_lifecycle(customer_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.queue_customer_operation(
                customer_id=customer_id,
                operation_type=data.get("operation_type"),
                expected_customer_version=data.get("expected_customer_version"),
                target_snapshot_digest=data.get("target_snapshot_digest"),
                idempotency_key=data.get("idempotency_key"),
                created_by=username,
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"operation": asdict(result), "remote_io": "not_started"}

    @router.get("/api/v1/telegram/customers/{customer_id}/operations")
    def list_customer_lifecycle_operations(customer_id: int, request: Request, limit: int = 100):
        require_admin(request)
        try:
            registry.get_customer(customer_id)
            return {"items": [asdict(item) for item in registry.list_customer_operations(customer_id=customer_id, limit=limit)]}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.get("/api/v1/telegram/customer-operations/{operation_id}")
    def get_customer_lifecycle_operation(operation_id: int, request: Request):
        require_admin(request)
        try:
            return {"item": asdict(registry.get_customer_operation(operation_id))}
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc

    @router.post("/api/v1/telegram/customer-operations/{operation_id}/retry")
    def retry_customer_lifecycle_operation(operation_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.reschedule_customer_operation(
                operation_id=operation_id,
                expected_operation_version=data.get("expected_operation_version"),
                idempotency_key=data.get("idempotency_key"),
                requested_by=username,
                action="retry",
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"operation": asdict(result), "remote_io": "not_started"}

    @router.post("/api/v1/telegram/customer-operations/{operation_id}/reconcile")
    def reconcile_customer_lifecycle_operation(operation_id: int, request: Request, data: Dict):
        username = require_admin(request)
        try:
            result = registry.reschedule_customer_operation(
                operation_id=operation_id,
                expected_operation_version=data.get("expected_operation_version"),
                idempotency_key=data.get("idempotency_key"),
                requested_by=username,
                action="reconcile",
            )
        except TelegramRegistryError as exc:
            raise translate_registry_error(exc) from exc
        return {"operation": asdict(result), "remote_io": "not_started"}

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
