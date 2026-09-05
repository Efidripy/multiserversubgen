"""Durable reconcile-first lifecycle worker for Telegram customers.

The registry creates immutable attempts only. This worker is the sole place
that may apply a previously approved Suspend, Resume or Delete to an existing
remote record. Each write is protected by an exact read before and after it.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from services.db_bootstrap import connect
from services.telegram_provisioning import (
    ProvisioningPermanentError,
    RemoteClient,
)
from services.telegram_registry import canonicalize_email


class LifecyclePort(Protocol):
    def list_clients(self, *, node: dict[str, Any], inbound_id: int, email: str) -> list[RemoteClient]: ...

    def set_client_enabled(
        self, *, node: dict[str, Any], inbound_id: int, client_id: str, enabled: bool
    ) -> None: ...

    def delete_client(self, *, node: dict[str, Any], inbound_id: int, client_id: str) -> None: ...


@dataclass(frozen=True)
class ClaimedLifecycleAttempt:
    operation_id: int
    attempt_id: int
    customer_id: int
    operation_type: str
    binding_id: int
    node_id: int
    inbound_id: int
    remote_client_id: str
    remote_sub_id: str
    remote_email: str
    action: str
    previous_enabled: bool | None
    attempt_count: int


@dataclass(frozen=True)
class LifecycleRunResult:
    processed: bool
    operation_id: int | None = None
    attempt_id: int | None = None
    outcome: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TelegramLifecycleWorker:
    """One-at-a-time worker with an operation lease and no blind write retry."""

    def __init__(
        self,
        *,
        db_path: str,
        node_loader: Callable[[int], dict[str, Any] | None],
        port: LifecyclePort,
        worker_id: str,
        now: Callable[[], datetime] = _utc_now,
        lease_seconds: int = 60,
    ):
        if not worker_id.strip() or lease_seconds <= 0:
            raise ValueError("worker_id and lease_seconds must be valid")
        self._db_path = db_path
        self._node_loader = node_loader
        self._port = port
        self._worker_id = worker_id.strip()
        self._now = now
        self._lease_seconds = lease_seconds

    def run_once(self) -> LifecycleRunResult:
        claimed = self._claim_next_attempt()
        if claimed is None:
            return LifecycleRunResult(processed=False)
        node = self._node_loader(claimed.node_id)
        if not self._node_is_writable(node):
            self._finish_attempt(claimed, status="blocked", error_code="node_unavailable")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "blocked")

        try:
            match, remote = self._find_exact(claimed, node)
        except ProvisioningPermanentError as exc:
            self._finish_attempt(claimed, status="failed", error_code="remote_read_rejected", error_summary=str(exc))
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "failed")
        except Exception:
            self._defer_reconcile(claimed, "remote_read_uncertain")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")

        if match == "conflict":
            self._finish_attempt(claimed, status="conflict", error_code="identity_conflict")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "conflict")
        if match == "missing":
            if claimed.action == "delete_client":
                self._succeed_attempt(claimed, previous_enabled=None, remote_missing=True)
                return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "succeeded")
            self._finish_attempt(claimed, status="missing", error_code="remote_client_missing")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "missing")
        assert remote is not None

        if claimed.action == "set_enabled_false":
            return self._set_enabled(claimed, node, remote, desired_enabled=False)
        if claimed.action == "restore_previous_enabled":
            if claimed.previous_enabled is None:
                self._finish_attempt(claimed, status="failed", error_code="missing_suspend_snapshot")
                return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "failed")
            return self._set_enabled(claimed, node, remote, desired_enabled=claimed.previous_enabled)
        if claimed.action == "delete_client":
            return self._delete_client(claimed, node)
        self._finish_attempt(claimed, status="failed", error_code="unsupported_action")
        return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "failed")

    @staticmethod
    def _node_is_writable(node: dict[str, Any] | None) -> bool:
        return bool(node) and bool(node.get("enabled", True)) and not bool(node.get("read_only", False))

    def _find_exact(
        self, claimed: ClaimedLifecycleAttempt, node: dict[str, Any]
    ) -> tuple[str, RemoteClient | None]:
        clients = self._port.list_clients(
            node=node, inbound_id=claimed.inbound_id, email=claimed.remote_email
        )
        exact = [
            client
            for client in clients
            if client.client_id == claimed.remote_client_id
            and client.sub_id == claimed.remote_sub_id
            and canonicalize_email(client.email) == canonicalize_email(claimed.remote_email)
        ]
        if len(exact) == 1:
            return "exact", exact[0]
        if exact or clients:
            return "conflict", None
        return "missing", None

    def _set_enabled(
        self,
        claimed: ClaimedLifecycleAttempt,
        node: dict[str, Any],
        remote: RemoteClient,
        *,
        desired_enabled: bool,
    ) -> LifecycleRunResult:
        previous_enabled = remote.enabled if claimed.action == "set_enabled_false" else claimed.previous_enabled
        if remote.enabled != desired_enabled:
            self._mark_writing(claimed, f"set_enabled:{int(desired_enabled)}")
            try:
                self._port.set_client_enabled(
                    node=node,
                    inbound_id=claimed.inbound_id,
                    client_id=claimed.remote_client_id,
                    enabled=desired_enabled,
                )
            except ProvisioningPermanentError as exc:
                self._finish_attempt(claimed, status="failed", error_code="remote_update_rejected", error_summary=str(exc))
                return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "failed")
            except Exception:
                self._defer_reconcile(claimed, "remote_update_uncertain")
                return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")
            try:
                match, after = self._find_exact(claimed, node)
            except Exception:
                self._defer_reconcile(claimed, "read_after_write_uncertain")
                return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")
            if match != "exact" or after is None or after.enabled != desired_enabled:
                self._defer_reconcile(claimed, "read_after_write_mismatch")
                return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")
        self._succeed_attempt(claimed, previous_enabled=previous_enabled, remote_missing=False)
        return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "succeeded")

    def _delete_client(self, claimed: ClaimedLifecycleAttempt, node: dict[str, Any]) -> LifecycleRunResult:
        self._mark_writing(claimed, "delete_client")
        try:
            self._port.delete_client(
                node=node, inbound_id=claimed.inbound_id, client_id=claimed.remote_client_id
            )
        except ProvisioningPermanentError as exc:
            self._finish_attempt(claimed, status="failed", error_code="remote_delete_rejected", error_summary=str(exc))
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "failed")
        except Exception:
            self._defer_reconcile(claimed, "remote_delete_uncertain")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")
        try:
            match, _ = self._find_exact(claimed, node)
        except Exception:
            self._defer_reconcile(claimed, "read_after_delete_uncertain")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")
        if match != "missing":
            self._defer_reconcile(claimed, "read_after_delete_mismatch")
            return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "ambiguous")
        self._succeed_attempt(claimed, previous_enabled=None, remote_missing=True)
        return LifecycleRunResult(True, claimed.operation_id, claimed.attempt_id, "succeeded")

    def _claim_next_attempt(self) -> ClaimedLifecycleAttempt | None:
        current = self._now()
        current_stamp = _timestamp(current)
        lease_until = _timestamp(current + timedelta(seconds=self._lease_seconds))
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT o.id, a.id, o.customer_id, o.operation_type, a.binding_id, a.node_id, a.inbound_id,
                       a.remote_client_id, a.remote_sub_id, a.remote_email, a.action, a.previous_enabled,
                       a.attempt_count
                FROM telegram_customer_operations AS o
                JOIN telegram_customer_operation_attempts AS a ON a.operation_id = o.id
                WHERE o.status IN ('queued', 'partial', 'running')
                  AND (o.lease_until IS NULL OR o.lease_until < ?)
                  AND a.status IN ('pending', 'ambiguous')
                  AND (a.next_attempt_at IS NULL OR a.next_attempt_at <= ?)
                ORDER BY o.created_at, o.id, a.id
                LIMIT 1
                """,
                (current_stamp, current_stamp),
            ).fetchone()
            if row is None:
                return None
            operation_id, attempt_id = int(row[0]), int(row[1])
            leased = conn.execute(
                """
                UPDATE telegram_customer_operations
                SET status = 'running', lease_owner = ?, lease_until = ?, attempt_count = attempt_count + 1,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('queued', 'partial', 'running')
                  AND (lease_until IS NULL OR lease_until < ?)
                """,
                (self._worker_id, lease_until, operation_id, current_stamp),
            )
            if leased.rowcount != 1:
                return None
            claimed = conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = 'reconciling', attempt_count = attempt_count + 1, error_code = NULL,
                    error_summary = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('pending', 'ambiguous')
                """,
                (attempt_id,),
            )
            if claimed.rowcount != 1:
                conn.execute(
                    """
                    UPDATE telegram_customer_operations
                    SET status = 'partial', lease_owner = NULL, lease_until = NULL,
                        row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (operation_id,),
                )
                return None
        return ClaimedLifecycleAttempt(
            operation_id=operation_id,
            attempt_id=attempt_id,
            customer_id=int(row[2]),
            operation_type=str(row[3]),
            binding_id=int(row[4]),
            node_id=int(row[5]),
            inbound_id=int(row[6]),
            remote_client_id=str(row[7]),
            remote_sub_id=str(row[8]),
            remote_email=str(row[9]),
            action=str(row[10]),
            previous_enabled=bool(row[11]) if row[11] is not None else None,
            attempt_count=int(row[12]) + 1,
        )

    def _mark_writing(self, claimed: ClaimedLifecycleAttempt, request_value: str) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = 'writing', request_digest = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'reconciling'
                """,
                (_digest(request_value), claimed.attempt_id),
            )

    def _succeed_attempt(
        self, claimed: ClaimedLifecycleAttempt, *, previous_enabled: bool | None, remote_missing: bool
    ) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = 'succeeded', previous_enabled = COALESCE(previous_enabled, ?),
                    response_digest = ?, error_code = NULL, error_summary = NULL,
                    finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    int(previous_enabled) if previous_enabled is not None else None,
                    _digest("remote_missing" if remote_missing else "confirmed"),
                    claimed.attempt_id,
                ),
            )
            if claimed.action == "set_enabled_false":
                conn.execute(
                    """
                    UPDATE customer_node_bindings
                    SET desired_enabled = 0, last_enabled = 0, suspended_by_operation_id = ?,
                        last_confirmed_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (claimed.operation_id, claimed.binding_id),
                )
            elif claimed.action == "restore_previous_enabled":
                desired_enabled = int(bool(claimed.previous_enabled))
                conn.execute(
                    """
                    UPDATE customer_node_bindings
                    SET desired_enabled = ?, last_enabled = ?, suspended_by_operation_id = NULL,
                        last_confirmed_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (desired_enabled, desired_enabled, claimed.binding_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE customer_node_bindings
                    SET management_state = 'missing', desired_enabled = 0, last_enabled = NULL,
                        last_confirmed_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (claimed.binding_id,),
                )
            self._finalize_operation(conn, claimed.operation_id)

    def _finish_attempt(
        self,
        claimed: ClaimedLifecycleAttempt,
        *,
        status: str,
        error_code: str,
        error_summary: str | None = None,
    ) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = ?, error_code = ?, error_summary = ?, finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, error_code, error_summary, claimed.attempt_id),
            )
            self._finalize_operation(conn, claimed.operation_id)

    def _defer_reconcile(self, claimed: ClaimedLifecycleAttempt, error_code: str) -> None:
        delay_seconds = min(300, 2 ** min(claimed.attempt_count, 8)) + secrets.randbelow(1000) / 1000
        next_attempt = _timestamp(self._now() + timedelta(seconds=delay_seconds))
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = 'ambiguous', error_code = ?, error_summary = NULL, next_attempt_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_code, next_attempt, claimed.attempt_id),
            )
            conn.execute(
                """
                UPDATE telegram_customer_operations
                SET status = 'partial', lease_owner = NULL, lease_until = NULL, next_attempt_at = ?,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_attempt, claimed.operation_id),
            )

    def _finalize_operation(self, conn, operation_id: int) -> None:
        operation = conn.execute(
            "SELECT customer_id, operation_type FROM telegram_customer_operations WHERE id = ?",
            (operation_id,),
        ).fetchone()
        if operation is None:
            return
        customer_id, operation_type = int(operation[0]), str(operation[1])
        counts = {
            str(status): int(count)
            for status, count in conn.execute(
                "SELECT status, COUNT(*) FROM telegram_customer_operation_attempts "
                "WHERE operation_id = ? GROUP BY status",
                (operation_id,),
            ).fetchall()
        }
        pending = sum(counts.get(name, 0) for name in ("pending", "ambiguous", "reconciling", "writing"))
        if pending:
            operation_status = "partial"
            customer_status = None if operation_type in {"suspend_node", "resume_node"} else f"{operation_type}_partial"
            finished = False
        elif counts and counts.get("succeeded", 0) == sum(counts.values()):
            operation_status = "succeeded"
            customer_status = (
                None
                if operation_type in {"suspend_node", "resume_node"}
                else {"suspend": "suspended", "resume": "active", "delete": "deleted"}[operation_type]
            )
            finished = True
        elif not counts:
            operation_status = "succeeded"
            customer_status = (
                None
                if operation_type in {"suspend_node", "resume_node"}
                else {"suspend": "suspended", "resume": "active", "delete": "deleted"}[operation_type]
            )
            finished = True
        else:
            operation_status = "partial"
            customer_status = None if operation_type in {"suspend_node", "resume_node"} else f"{operation_type}_partial"
            finished = True

        conn.execute(
            """
            UPDATE telegram_customer_operations
            SET status = ?, lease_owner = NULL, lease_until = NULL,
                next_attempt_at = CASE WHEN ? THEN NULL ELSE next_attempt_at END,
                finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (operation_status, int(finished), int(finished), operation_id),
        )
        if operation_type == "delete" and operation_status == "succeeded":
            conn.execute(
                """
                UPDATE customers
                SET status = 'deleted', deleted_at = CURRENT_TIMESTAMP,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (customer_id,),
            )
            conn.execute(
                """
                UPDATE telegram_identities
                SET customer_id = NULL, access_status = 'eligible', request_code = NULL,
                    updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                WHERE customer_id = ?
                """,
                (customer_id,),
            )
        elif customer_status is not None:
            conn.execute(
                """
                UPDATE customers
                SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND deleted_at IS NULL
                """,
                (customer_status, customer_id),
            )
