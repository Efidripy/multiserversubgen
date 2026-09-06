"""Durable, reconcile-first provisioning worker for Telegram customers.

The worker has no knowledge of HTTP or Telegram. Its remote port is injected so
production wiring can stay disabled until a staged node contract is approved.
Every retry begins with a read; an uncertain add result is never replayed.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from services.db_bootstrap import connect
from services.telegram_registry import BOT_CLIENT_FLOW, BOT_INBOUND_ID, canonicalize_email


class ProvisioningRemoteError(RuntimeError):
    """A remote result is uncertain and needs reconciliation before any retry."""


class ProvisioningPermanentError(RuntimeError):
    """A remote target rejected a request that cannot safely be retried."""


@dataclass(frozen=True)
class RemoteClient:
    client_id: str
    email: str
    sub_id: str
    flow: str
    enabled: bool


@dataclass(frozen=True)
class ExistingRemoteBinding:
    """An exact, read-only discovery result for one legacy inbound-1 client."""

    node_id: int
    node_name: str
    inbound_id: int
    remote_client_id: str
    remote_sub_id: str
    remote_email: str
    enabled: bool


class ClientManagerLegacyDiscovery:
    """Discover an already-existing client without mutating any node.

    Existing panel users predate the local Telegram registry.  We only adopt an
    exact canonical email from inbound #1, and fail closed if any enabled node
    cannot be read.  This prevents a partial fleet read from becoming a false
    "safe to delete" local lifecycle record later.
    """

    def __init__(self, *, client_manager: Any, list_nodes: Callable[[], list[dict[str, Any]]]):
        self._client_manager = client_manager
        self._list_nodes = list_nodes

    def discover(self, email: str) -> tuple[ExistingRemoteBinding, ...]:
        wanted = canonicalize_email(email)
        matches: list[ExistingRemoteBinding] = []
        unreadable: list[str] = []
        for node in self._list_nodes():
            if not isinstance(node, dict) or not bool(node.get("enabled", True)):
                continue
            try:
                rows = self._client_manager.get_node_clients_strict(node)
            except Exception:
                unreadable.append(str(node.get("name") or node.get("id") or "node"))
                continue
            node_matches: list[ExistingRemoteBinding] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                inbound_ids = row.get("inbound_ids") if isinstance(row.get("inbound_ids"), list) else []
                if row.get("inbound_id") != BOT_INBOUND_ID and BOT_INBOUND_ID not in inbound_ids:
                    continue
                try:
                    same_email = canonicalize_email(str(row.get("email") or "")) == wanted
                except Exception:
                    continue
                if not same_email:
                    continue
                client_id = str(row.get("id") or "")
                if not client_id:
                    raise ProvisioningPermanentError("legacy client has no stable identifier")
                node_matches.append(
                    ExistingRemoteBinding(
                        node_id=int(node["id"]),
                        node_name=str(node.get("name") or node["id"]),
                        inbound_id=BOT_INBOUND_ID,
                        remote_client_id=client_id,
                        remote_sub_id=str(row.get("subId") or ""),
                        remote_email=str(row.get("email") or ""),
                        enabled=bool(row.get("enable", True)),
                    )
                )
            if len(node_matches) > 1:
                raise ProvisioningPermanentError("legacy email is ambiguous on a node")
            matches.extend(node_matches)
        if unreadable:
            raise ProvisioningRemoteError("legacy discovery is incomplete")
        return tuple(matches)


class ProvisioningPort(Protocol):
    def supports_fixed_contract(self, *, node: dict[str, Any], inbound_id: int) -> bool: ...

    def list_clients(self, *, node: dict[str, Any], inbound_id: int, email: str) -> list[RemoteClient]: ...

    def add_client(self, *, node: dict[str, Any], inbound_id: int, client: dict[str, Any]) -> None: ...


class ClientManagerProvisioningPort:
    """Strict adapter over the existing XUI client manager.

    It intentionally uses the manager's strict per-node read method rather
    than its dashboard aggregate, because an unavailable node must never look
    like an empty node to a reconcile-before-add workflow.
    """

    def __init__(self, client_manager: Any):
        self._client_manager = client_manager

    def supports_fixed_contract(self, *, node: dict[str, Any], inbound_id: int) -> bool:
        try:
            return self._client_manager.inbound_supports_telegram_contract_strict(node, inbound_id)
        except Exception as exc:
            raise ProvisioningRemoteError("remote inbound contract is unavailable") from exc

    def list_clients(self, *, node: dict[str, Any], inbound_id: int, email: str) -> list[RemoteClient]:
        try:
            rows = self._client_manager.get_node_clients_strict(node)
        except Exception as exc:
            raise ProvisioningRemoteError("remote client read is unavailable") from exc
        result: list[RemoteClient] = []
        wanted_email = canonicalize_email(email)
        for row in rows:
            if not isinstance(row, dict):
                continue
            inbound_ids = row.get("inbound_ids") if isinstance(row.get("inbound_ids"), list) else []
            if row.get("inbound_id") != inbound_id and inbound_id not in inbound_ids:
                continue
            client_email = str(row.get("email") or "")
            try:
                same_email = canonicalize_email(client_email) == wanted_email
            except Exception:
                same_email = False
            if not same_email:
                continue
            client_id = str(row.get("id") or "")
            if not client_id:
                raise ProvisioningPermanentError("remote client has no stable identifier")
            result.append(
                RemoteClient(
                    client_id=client_id,
                    email=client_email,
                    sub_id=str(row.get("subId") or ""),
                    flow=str(row.get("flow") or ""),
                    enabled=bool(row.get("enable", True)),
                )
            )
        return result

    def add_client(self, *, node: dict[str, Any], inbound_id: int, client: dict[str, Any]) -> None:
        try:
            added = self._client_manager.add_client(node, inbound_id, client)
        except Exception as exc:
            raise ProvisioningRemoteError("remote add outcome is unavailable") from exc
        if added is not True:
            raise ProvisioningRemoteError("remote add outcome is unavailable")

    def set_client_enabled(
        self, *, node: dict[str, Any], inbound_id: int, client_id: str, enabled: bool
    ) -> None:
        """Write only after a lifecycle worker has read the exact remote client."""

        try:
            updated = self._client_manager.update_client(node, inbound_id, client_id, {"enable": enabled})
        except Exception as exc:
            raise ProvisioningRemoteError("remote update outcome is unavailable") from exc
        if updated is not True:
            raise ProvisioningRemoteError("remote update outcome is unavailable")

    def delete_client(self, *, node: dict[str, Any], inbound_id: int, client_id: str) -> None:
        """Write only after a lifecycle worker has read the exact remote client."""

        try:
            deleted = self._client_manager.delete_client(node, inbound_id, client_id)
        except Exception as exc:
            raise ProvisioningRemoteError("remote delete outcome is unavailable") from exc
        if deleted is not True:
            raise ProvisioningRemoteError("remote delete outcome is unavailable")


@dataclass(frozen=True)
class ClaimedAttempt:
    job_id: int
    attempt_id: int
    customer_id: int
    node_id: int
    email: str
    inbound_id: int
    desired_client_id: str
    desired_sub_id: str
    desired_flow: str
    desired_total_bytes: int
    desired_expiry_time: int
    desired_client_enabled: bool
    attempt_count: int


@dataclass(frozen=True)
class ProvisioningRunResult:
    processed: bool
    job_id: int | None = None
    attempt_id: int | None = None
    outcome: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


class TelegramProvisioningWorker:
    """One-at-a-time worker with a per-job SQLite lease and exact identifiers."""

    def __init__(
        self,
        *,
        db_path: str,
        node_loader: Callable[[int], dict[str, Any] | None],
        port: ProvisioningPort,
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

    def run_once(self) -> ProvisioningRunResult:
        claimed = self._claim_next_attempt()
        if claimed is None:
            return ProvisioningRunResult(processed=False)
        node = self._node_loader(claimed.node_id)
        if not self._node_is_writable(node):
            self._finish_attempt(claimed, status="skipped", error_code="node_unavailable")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "skipped")
        try:
            compatible = self._port.supports_fixed_contract(node=node, inbound_id=claimed.inbound_id)
        except Exception:
            self._defer_reconcile(claimed, "inbound_contract_uncertain")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "ambiguous")
        if not compatible:
            self._finish_attempt(claimed, status="skipped", error_code="inbound_contract_incompatible")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "skipped")

        try:
            matches = self._find_matches(claimed, node)
        except ProvisioningPermanentError as exc:
            self._finish_attempt(claimed, status="failed", error_code="remote_read_rejected", error_summary=str(exc))
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "failed")
        except Exception:
            self._defer_reconcile(claimed, "remote_read_uncertain")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "ambiguous")

        if matches == "exact":
            return self._confirm_or_fail(claimed)
        if matches == "conflict":
            self._finish_attempt(claimed, status="failed", error_code="identity_conflict")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "failed")

        client = {
            "id": claimed.desired_client_id,
            "email": claimed.email,
            "subId": claimed.desired_sub_id,
            "flow": BOT_CLIENT_FLOW,
            "totalGB": claimed.desired_total_bytes,
            "expiryTime": claimed.desired_expiry_time,
            "enable": claimed.desired_client_enabled,
        }
        self._mark_creating(claimed)
        try:
            self._port.add_client(node=node, inbound_id=BOT_INBOUND_ID, client=client)
        except ProvisioningPermanentError as exc:
            self._finish_attempt(claimed, status="failed", error_code="remote_add_rejected", error_summary=str(exc))
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "failed")
        except Exception:
            # The add may have reached the node. Mark ambiguous and perform a
            # fresh lookup on the next lease instead of replaying the write.
            self._defer_reconcile(claimed, "remote_add_uncertain")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "ambiguous")

        try:
            matches = self._find_matches(claimed, node)
        except Exception:
            self._defer_reconcile(claimed, "read_after_write_uncertain")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "ambiguous")
        if matches == "exact":
            return self._confirm_or_fail(claimed)
        if matches == "conflict":
            self._finish_attempt(claimed, status="failed", error_code="identity_conflict")
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "failed")
        self._defer_reconcile(claimed, "read_after_write_missing")
        return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "ambiguous")

    @staticmethod
    def _node_is_writable(node: dict[str, Any] | None) -> bool:
        return bool(node) and bool(node.get("enabled", True)) and not bool(node.get("read_only", False))

    def _find_matches(self, claimed: ClaimedAttempt, node: dict[str, Any]) -> str:
        clients = self._port.list_clients(node=node, inbound_id=claimed.inbound_id, email=claimed.email)
        exact = [
            client
            for client in clients
            if canonicalize_email(client.email) == canonicalize_email(claimed.email)
            and client.client_id == claimed.desired_client_id
            and client.sub_id == claimed.desired_sub_id
            and client.flow == claimed.desired_flow
        ]
        if len(exact) == 1:
            return "exact"
        if exact or clients:
            return "conflict"
        return "missing"

    def _claim_next_attempt(self) -> ClaimedAttempt | None:
        current = self._now()
        current_stamp = _timestamp(current)
        lease_until = _timestamp(current + timedelta(seconds=self._lease_seconds))
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT j.id, a.id, j.customer_id, a.node_id, c.email_display, a.inbound_id,
                       a.desired_client_id, a.desired_sub_id, a.desired_flow,
                       a.desired_total_bytes, a.desired_expiry_time, a.desired_client_enabled,
                       a.attempt_count
                FROM telegram_provisioning_jobs AS j
                JOIN telegram_provisioning_attempts AS a ON a.job_id = j.id
                JOIN customers AS c ON c.id = j.customer_id
                WHERE j.status IN ('queued', 'partial', 'running')
                  AND (j.lease_until IS NULL OR j.lease_until < ?)
                  AND a.status IN ('pending', 'ambiguous')
                  AND (a.next_attempt_at IS NULL OR a.next_attempt_at <= ?)
                ORDER BY j.created_at, j.id, a.id
                LIMIT 1
                """,
                (current_stamp, current_stamp),
            ).fetchone()
            if row is None:
                return None
            job_id, attempt_id = int(row[0]), int(row[1])
            lease = conn.execute(
                """
                UPDATE telegram_provisioning_jobs
                SET status = 'running', lease_owner = ?, lease_until = ?, attempt_count = attempt_count + 1,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('queued', 'partial', 'running')
                  AND (lease_until IS NULL OR lease_until < ?)
                """,
                (self._worker_id, lease_until, job_id, current_stamp),
            )
            if lease.rowcount != 1:
                return None
            claimed = conn.execute(
                """
                UPDATE telegram_provisioning_attempts
                SET status = 'reconciling', attempt_count = attempt_count + 1,
                    last_checked_at = ?, error_code = NULL, error_summary = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('pending', 'ambiguous')
                """,
                (current_stamp, attempt_id),
            )
            if claimed.rowcount != 1:
                conn.execute(
                    "UPDATE telegram_provisioning_jobs SET status = 'partial', lease_owner = NULL, lease_until = NULL, row_version = row_version + 1 WHERE id = ?",
                    (job_id,),
                )
                return None
        return ClaimedAttempt(
            job_id=job_id,
            attempt_id=attempt_id,
            customer_id=int(row[2]),
            node_id=int(row[3]),
            email=str(row[4]),
            inbound_id=int(row[5]),
            desired_client_id=str(row[6]),
            desired_sub_id=str(row[7]),
            desired_flow=str(row[8]),
            desired_total_bytes=int(row[9]),
            desired_expiry_time=int(row[10]),
            desired_client_enabled=bool(row[11]),
            attempt_count=int(row[12]) + 1,
        )

    def _mark_creating(self, claimed: ClaimedAttempt) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_provisioning_attempts
                SET status = 'creating', updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'reconciling'
                """,
                (claimed.attempt_id,),
            )

    def _confirm_or_fail(self, claimed: ClaimedAttempt) -> ProvisioningRunResult:
        try:
            self._confirm_attempt(claimed)
        except ProvisioningPermanentError as exc:
            self._finish_attempt(claimed, status="failed", error_code="local_binding_conflict", error_summary=str(exc))
            return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "failed")
        return ProvisioningRunResult(True, claimed.job_id, claimed.attempt_id, "succeeded")

    def _confirm_attempt(self, claimed: ClaimedAttempt) -> None:
        with connect(self._db_path) as conn:
            existing = conn.execute(
                """
                SELECT id, remote_client_id FROM customer_node_bindings
                WHERE customer_id = ? AND node_id = ? AND inbound_id = ?
                """,
                (claimed.customer_id, claimed.node_id, claimed.inbound_id),
            ).fetchone()
            if existing is None:
                try:
                    conn.execute(
                        """
                        INSERT INTO customer_node_bindings
                            (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                             source, management_state, desired_enabled, last_enabled, last_confirmed_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'bot_provisioned', 'confirmed', ?, ?, CURRENT_TIMESTAMP)
                        """,
                        (
                            claimed.customer_id, claimed.node_id, claimed.inbound_id,
                            claimed.desired_client_id, claimed.desired_sub_id, claimed.email,
                            int(claimed.desired_client_enabled), int(claimed.desired_client_enabled),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ProvisioningPermanentError("local binding conflict") from exc
            elif str(existing[1]) != claimed.desired_client_id:
                raise ProvisioningPermanentError("local binding conflict")
            conn.execute(
                """
                UPDATE telegram_provisioning_attempts
                SET status = 'succeeded', remote_client_id = ?, error_code = NULL, error_summary = NULL,
                    last_checked_at = CURRENT_TIMESTAMP, finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (claimed.desired_client_id, claimed.attempt_id),
            )
            self._finalize_job(conn, claimed.job_id)

    def _finish_attempt(
        self,
        claimed: ClaimedAttempt,
        *,
        status: str,
        error_code: str,
        error_summary: str | None = None,
    ) -> None:
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_provisioning_attempts
                SET status = ?, error_code = ?, error_summary = ?, finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, error_code, error_summary, claimed.attempt_id),
            )
            self._finalize_job(conn, claimed.job_id)

    def _defer_reconcile(self, claimed: ClaimedAttempt, error_code: str) -> None:
        delay_seconds = min(300, 2 ** min(claimed.attempt_count, 8)) + secrets.randbelow(1000) / 1000
        next_attempt = _timestamp(self._now() + timedelta(seconds=delay_seconds))
        with connect(self._db_path) as conn:
            conn.execute(
                """
                UPDATE telegram_provisioning_attempts
                SET status = 'ambiguous', error_code = ?, error_summary = NULL, next_attempt_at = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_code, next_attempt, claimed.attempt_id),
            )
            conn.execute(
                """
                UPDATE telegram_provisioning_jobs
                SET status = 'partial', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_attempt, claimed.job_id),
            )

    def _finalize_job(self, conn, job_id: int) -> None:
        counts = {
            str(status): int(count)
            for status, count in conn.execute(
                "SELECT status, COUNT(*) FROM telegram_provisioning_attempts WHERE job_id = ? GROUP BY status",
                (job_id,),
            ).fetchall()
        }
        pending = counts.get("pending", 0) + counts.get("ambiguous", 0) + counts.get("reconciling", 0) + counts.get("creating", 0)
        if pending:
            status = "partial"
            finished_at = None
        elif counts.get("succeeded", 0) == sum(counts.values()):
            status = "succeeded"
            finished_at = "CURRENT_TIMESTAMP"
        elif counts.get("succeeded", 0):
            status = "partial"
            finished_at = "CURRENT_TIMESTAMP"
        else:
            status = "failed"
            finished_at = "CURRENT_TIMESTAMP"
        if finished_at:
            conn.execute(
                """
                UPDATE telegram_provisioning_jobs
                SET status = ?, lease_owner = NULL, lease_until = NULL, next_attempt_at = NULL,
                    finished_at = CURRENT_TIMESTAMP, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, job_id),
            )
            if status == "succeeded":
                recipients = conn.execute(
                    """
                    SELECT i.telegram_user_id
                    FROM telegram_provisioning_jobs AS j
                    JOIN telegram_identities AS i ON i.customer_id = j.customer_id
                    WHERE j.id = ? AND i.access_status = 'approved'
                    ORDER BY i.created_at ASC, i.telegram_user_id ASC
                    """,
                    (job_id,),
                ).fetchall()
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO telegram_outbox (event_type, entity_id, dedupe_key)
                    VALUES ('user_provisioning_completed', ?, ?)
                    """,
                    [
                        (str(int(row[0])), f"user:provisioning-completed:{job_id}:{int(row[0])}")
                        for row in recipients
                    ],
                )
        else:
            conn.execute(
                """
                UPDATE telegram_provisioning_jobs
                SET status = ?, lease_owner = NULL, lease_until = NULL, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, job_id),
            )
