"""Provisioning policies, jobs, retention, and history operations."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

from services.db_bootstrap import connect

def set_node_provisioning_policy(self, *, node_id: int, provisioning_enabled: bool, total_bytes: int | str | None, validity_days: int | str | None, client_enabled: bool | str | None, expected_policy_version: int, idempotency_key: str, updated_by: str, node_is_compatible: bool, _positive_int, _bounded_nonnegative, _nonempty, _default_client_enabled, _payload_digest, TelegramRegistryError, IdempotencyConflictError, NodePolicyUnavailableError, VersionConflictError, _policy_from_row, NodeProvisioningPolicy) -> Any:
    """Persist the one shared policy command used by both admin surfaces.

        The remote inbound compatibility result is passed in from a later
        capability service. It must be explicit to keep this repository free of
        hidden network I/O and to fail closed when a caller has no proof.
        """

    normalized_node_id = _positive_int(node_id, "node_id")
    if not isinstance(provisioning_enabled, bool):
        raise TelegramRegistryError("provisioning_enabled must be a boolean")
    expected_version = _bounded_nonnegative(expected_policy_version, "expected_policy_version")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(updated_by, "updated_by")
    payload = {
        "node_id": normalized_node_id,
        "provisioning_enabled": provisioning_enabled,
        "total_bytes": _bounded_nonnegative(total_bytes, "total_bytes"),
        "validity_days": _bounded_nonnegative(validity_days, "validity_days"),
        "client_enabled": _default_client_enabled(client_enabled),
        "expected_policy_version": expected_version,
        "node_is_compatible": node_is_compatible,
    }
    digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            """
                SELECT payload_digest, result_json
                FROM telegram_command_receipts
                WHERE scope = 'node_policy' AND idempotency_key = ?
                """,
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            result = json.loads(str(receipt[1]))
            return NodeProvisioningPolicy(**result)

        node = conn.execute(
            "SELECT enabled, read_only FROM nodes WHERE id = ?", (normalized_node_id,)
        ).fetchone()
        if node is None:
            raise NodePolicyUnavailableError("node does not exist")
        if provisioning_enabled and (not bool(node[0]) or bool(node[1]) or not node_is_compatible):
            raise NodePolicyUnavailableError("node is not eligible for Telegram provisioning")

        existing = conn.execute(
            """
                SELECT node_id, provisioning_enabled, total_bytes, validity_days,
                       client_enabled, policy_version, updated_by
                FROM telegram_node_policies WHERE node_id = ?
                """,
            (normalized_node_id,),
        ).fetchone()
        if existing is None:
            if expected_version != 0:
                raise VersionConflictError("node policy does not yet exist")
            policy = NodeProvisioningPolicy(
                node_id=normalized_node_id,
                provisioning_enabled=provisioning_enabled,
                total_bytes=int(payload["total_bytes"]),
                validity_days=int(payload["validity_days"]),
                client_enabled=bool(payload["client_enabled"]),
                policy_version=1,
                updated_by=actor,
            )
            conn.execute(
                """
                    INSERT INTO telegram_node_policies
                        (node_id, provisioning_enabled, total_bytes, validity_days,
                         client_enabled, policy_version, updated_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                (
                    policy.node_id,
                    int(policy.provisioning_enabled),
                    policy.total_bytes,
                    policy.validity_days,
                    int(policy.client_enabled),
                    policy.policy_version,
                    policy.updated_by,
                ),
            )
        else:
            current = _policy_from_row(existing)
            if current.policy_version != expected_version:
                raise VersionConflictError("node policy was updated by another administrator")
            policy = NodeProvisioningPolicy(
                node_id=normalized_node_id,
                provisioning_enabled=provisioning_enabled,
                total_bytes=int(payload["total_bytes"]),
                validity_days=int(payload["validity_days"]),
                client_enabled=bool(payload["client_enabled"]),
                policy_version=current.policy_version + 1,
                updated_by=actor,
            )
            conn.execute(
                """
                    UPDATE telegram_node_policies
                    SET provisioning_enabled = ?, total_bytes = ?, validity_days = ?,
                        client_enabled = ?, policy_version = ?, updated_by = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE node_id = ? AND policy_version = ?
                    """,
                (
                    int(policy.provisioning_enabled),
                    policy.total_bytes,
                    policy.validity_days,
                    int(policy.client_enabled),
                    policy.policy_version,
                    policy.updated_by,
                    normalized_node_id,
                    expected_version,
                ),
            )
        serialized = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
        conn.execute(
            """
                INSERT INTO telegram_command_receipts
                    (scope, idempotency_key, payload_digest, result_json)
                VALUES ('node_policy', ?, ?, ?)
                """,
            (key, digest, serialized),
        )
    return policy

def list_provisioning_jobs(self, *, limit: int=100, ProvisioningJobStatus, ProvisioningAttemptStatus, TelegramRegistryError) -> Any:
    """Admin projection for job state; deliberately excludes remote UUIDs/sub IDs."""

    items, _total = self.list_provisioning_jobs_page(limit=limit, offset=0)
    return items

def list_provisioning_jobs_page(self, *, limit: int=100, offset: int=0, status: str = "all", ProvisioningJobStatus, ProvisioningAttemptStatus, TelegramRegistryError) -> Any:
    """Return a bounded page plus the exact local history size for the admin UI."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise TelegramRegistryError("offset must be a non-negative integer")
    statuses = {"queued", "running", "partial", "succeeded", "failed", "cancelled"}
    if status != "all" and status not in statuses:
        raise TelegramRegistryError("job status is invalid")
    clause = "hidden_at IS NULL" if status == "all" else "hidden_at IS NULL AND status = ?"
    args = () if status == "all" else (status,)
    with connect(self._db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE {clause}", args).fetchone()[0])
        jobs = conn.execute(
            f"""
                SELECT j.id, j.customer_id, c.email_display, j.trigger, j.status, j.attempt_count,
                       j.row_version, j.created_at, j.finished_at
                FROM telegram_provisioning_jobs AS j
                JOIN customers AS c ON c.id = j.customer_id
                WHERE j.hidden_at IS NULL {"AND j.status = ?" if status != "all" else ""}
                ORDER BY j.created_at DESC, j.id DESC LIMIT ? OFFSET ?
                """,
            ((*args, limit, offset)),
        ).fetchall()
        attempts = conn.execute(
            """
                SELECT a.job_id, a.node_id, n.name, a.status, a.error_code, a.error_summary,
                       a.attempt_count, a.next_attempt_at
                FROM telegram_provisioning_attempts AS a
                JOIN nodes AS n ON n.id = a.node_id
                ORDER BY a.job_id DESC, n.name COLLATE NOCASE, a.node_id
                """
        ).fetchall()
    grouped: dict[int, list[ProvisioningAttemptStatus]] = {}
    for job_id, node_id, node_name, status, error_code, error_summary, attempt_count, next_attempt_at in attempts:
        grouped.setdefault(int(job_id), []).append(
            ProvisioningAttemptStatus(
                node_id=int(node_id), node_name=str(node_name), status=str(status),
                error_code=str(error_code) if error_code is not None else None,
                error_summary=str(error_summary) if error_summary is not None else None,
                attempt_count=int(attempt_count),
                next_attempt_at=str(next_attempt_at) if next_attempt_at is not None else None,
            )
        )
    return [
        ProvisioningJobStatus(
            job_id=int(job[0]), customer_id=int(job[1]), customer_email=str(job[2]),
            trigger=str(job[3]), status=str(job[4]), attempt_count=int(job[5]), row_version=int(job[6]),
            created_at=str(job[7]), finished_at=str(job[8]) if job[8] is not None else None,
            attempts=tuple(grouped.get(int(job[0]), [])),
        )
        for job in jobs
    ], total

def clear_terminal_provisioning_history(self, *, idempotency_key: object, cleared_by: object, mode: str = "safe", _nonempty, _payload_digest, TelegramRegistryError, IdempotencyConflictError) -> int | dict[str, int]:
    """Delete only completed local job history; active/recoverable work is never a target."""

    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(cleared_by, "cleared_by")
    if mode not in {"safe", "all"}:
        raise TelegramRegistryError("history clear mode is invalid")
    terminal_statuses = ("succeeded", "failed", "cancelled")
    payload = {"terminal_statuses": terminal_statuses, "mode": mode}
    digest = _payload_digest(payload)
    scope = "provisioning_history_clear"
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = ? AND idempotency_key = ?", (scope, key),
        ).fetchone()
        if receipt is not None:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            try:
                result = json.loads(str(receipt[1]))
                return result if mode == "all" else int(result["deleted_count"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise TelegramRegistryError("stored history-clear receipt is invalid") from exc
        placeholders = ",".join("?" for _ in terminal_statuses)
        deleted_count = conn.execute(
            f"DELETE FROM telegram_provisioning_jobs WHERE hidden_at IS NULL AND status IN ({placeholders}) AND NOT EXISTS (SELECT 1 FROM telegram_provisioning_attempts pa WHERE pa.job_id=telegram_provisioning_jobs.id AND pa.status='succeeded' AND pa.id=(SELECT MAX(a2.id) FROM telegram_provisioning_attempts a2 JOIN telegram_provisioning_jobs j2 ON j2.id=a2.job_id WHERE j2.customer_id=telegram_provisioning_jobs.customer_id AND a2.node_id=pa.node_id AND a2.remote_client_id IS pa.remote_client_id AND a2.status='succeeded'))",
            terminal_statuses,
        ).rowcount
        hidden_count = 0
        if mode == "all":
            hidden_count = conn.execute(
                "UPDATE telegram_provisioning_jobs SET hidden_at = CURRENT_TIMESTAMP "
                "WHERE hidden_at IS NULL AND status IN ('succeeded','failed','cancelled')",
            ).rowcount
        result = {"deleted_count": int(deleted_count), "hidden_count": int(hidden_count)}
        result_json = json.dumps(result, separators=(",", ":"))
        conn.execute(
            "INSERT INTO telegram_command_receipts(scope, idempotency_key, payload_digest, result_json) "
            "VALUES (?, ?, ?, ?)", (scope, key, digest, result_json),
        )
        conn.execute(
            """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('provisioning_history_cleared', 'admin', ?, 'provisioning_history', ?, ?)
                """,
            (actor, mode, _payload_digest(result)),
        )
    return result if mode == "all" else deleted_count

def history_overview(self) -> dict[str, dict[str, int]]:
    """Return cheap counts for the admin history dashboard."""
    with connect(self._db_path) as conn:
        def count(sql: str, args: tuple[Any, ...] = ()) -> int:
            row = conn.execute(sql, args).fetchone()
            return int(row[0]) if row else 0
        overview = {
            "jobs": {
                "total": count("SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE hidden_at IS NULL"),
                "needs_attention": count("SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE hidden_at IS NULL AND status IN ('partial','failed')"),
                "terminal": count("SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE hidden_at IS NULL AND status IN ('succeeded','failed','cancelled')"),
            },
            "operations": {
                "total": count("SELECT COUNT(*) FROM telegram_customer_operations WHERE hidden_at IS NULL"),
                "terminal": count("SELECT COUNT(*) FROM telegram_customer_operations WHERE hidden_at IS NULL AND (status IN ('succeeded','cancelled') OR dismissed_at IS NOT NULL)"),
                "needs_attention": count("SELECT COUNT(*) FROM telegram_customer_operations WHERE hidden_at IS NULL AND status IN ('partial','failed','running') AND dismissed_at IS NULL"),
            },
            "drift": {
                "open": count("SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NULL AND status = 'open'"),
                "ignored": count("SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NULL AND status = 'ignored'"),
                "resolved": count("SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NULL AND status = 'resolved'"),
                "adopted": count("SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NULL AND status = 'adopted'"),
            },
            "missing_bindings": {
                "missing": count("SELECT COUNT(*) FROM customer_node_bindings WHERE management_state = 'missing'"),
                "conflict": count("SELECT COUNT(*) FROM customer_node_bindings WHERE management_state = 'conflict'"),
            },
            "audit": {"total": count("SELECT COUNT(*) FROM telegram_audit_log")},
        }
    # Rows other features still read are kept by "clear"; tell the UI how many it can really remove.
    for section in ("jobs", "operations", "drift"):
        overview[section]["clearable"] = self.history_clear_count(section)
    return overview

def history_clear_count(self, section: str, node_id: int | None=None, mode: str = "safe", *, _positive_int, TelegramRegistryError) -> int:
    if mode not in {"safe", "all"}:
        raise TelegramRegistryError("history clear mode is invalid")
    if node_id is not None:
        node_id = _positive_int(node_id, "node_id")
    queries = {
        "jobs": "SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE hidden_at IS NULL AND status IN ('succeeded','failed','cancelled') AND NOT EXISTS (SELECT 1 FROM telegram_provisioning_attempts pa WHERE pa.job_id=telegram_provisioning_jobs.id AND pa.status='succeeded' AND pa.id=(SELECT MAX(a2.id) FROM telegram_provisioning_attempts a2 JOIN telegram_provisioning_jobs j2 ON j2.id=a2.job_id WHERE j2.customer_id=telegram_provisioning_jobs.customer_id AND a2.node_id=pa.node_id AND a2.remote_client_id IS pa.remote_client_id AND a2.status='succeeded'))",
        "operations": "SELECT COUNT(*) FROM telegram_customer_operations WHERE hidden_at IS NULL AND (status IN ('succeeded','cancelled') OR dismissed_at IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM telegram_bulk_lifecycle_items bi WHERE bi.operation_id=telegram_customer_operations.id) AND NOT EXISTS (SELECT 1 FROM customer_node_bindings sb WHERE sb.suspended_by_operation_id=telegram_customer_operations.id)",
        "drift": "SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NULL AND (status IN ('resolved','adopted') OR (status='ignored' AND kind IN ('binding_missing','binding_conflict') AND NOT EXISTS (SELECT 1 FROM customer_node_bindings b WHERE b.customer_id=telegram_drift_findings.customer_id AND b.node_id=telegram_drift_findings.node_id AND b.management_state IN ('missing','conflict'))))",
        "audit": "SELECT COUNT(*) FROM telegram_audit_log",
        "bindings": "SELECT COUNT(*) FROM customer_node_bindings b WHERE b.management_state='missing' AND (? IS NULL OR b.node_id=?) AND NOT EXISTS (SELECT 1 FROM telegram_customer_operation_attempts a JOIN telegram_customer_operations o ON o.id=a.operation_id WHERE a.binding_id=b.id AND o.status IN ('queued','running','partial') AND o.dismissed_at IS NULL)",
    }
    if section not in queries or (node_id is not None and section != "bindings"):
        raise TelegramRegistryError("invalid history section")
    with connect(self._db_path) as conn:
        if mode == "all" and section in {"jobs", "operations", "drift"}:
            all_queries = {"jobs": "SELECT COUNT(*) FROM telegram_provisioning_jobs WHERE hidden_at IS NULL AND status IN ('succeeded','failed','cancelled')", "operations": "SELECT COUNT(*) FROM telegram_customer_operations WHERE hidden_at IS NULL AND (status IN ('succeeded','cancelled') OR dismissed_at IS NOT NULL)", "drift": "SELECT COUNT(*) FROM telegram_drift_findings WHERE hidden_at IS NULL AND status <> 'open'"}
            return int(conn.execute(all_queries[section]).fetchone()[0])
        return int(conn.execute(queries[section], (node_id, node_id) if section == "bindings" else ()).fetchone()[0])

def list_missing_binding_nodes(self) -> list[dict[str, Any]]:
    with connect(self._db_path) as conn:
        rows = conn.execute("SELECT DISTINCT n.id, n.name FROM nodes n JOIN customer_node_bindings b ON b.node_id=n.id WHERE b.management_state='missing' ORDER BY n.name COLLATE NOCASE, n.id").fetchall()
    return [{"node_id": int(row[0]), "node_name": str(row[1])} for row in rows]

def list_customer_operations_page(self, *, limit: int=100, offset: int=0, status: str = "all", TelegramRegistryError, CustomerOperationStatus) -> Any:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise TelegramRegistryError("offset must be a non-negative integer")
    statuses = {"previewed", "queued", "running", "partial", "succeeded", "failed"}
    if status != "all" and status not in statuses:
        raise TelegramRegistryError("operation status is invalid")
    clause = "hidden_at IS NULL" if status == "all" else "hidden_at IS NULL AND status = ?"
    args = () if status == "all" else (status,)
    with connect(self._db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM telegram_customer_operations WHERE {clause}", args).fetchone()[0])
        ids = [int(row[0]) for row in conn.execute(
            f"SELECT id FROM telegram_customer_operations WHERE {clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()]
        return [self._get_customer_operation_from_conn(conn, item) for item in ids], total

def list_drift_page(self, *, status: str = "all", limit: int = 100, offset: int = 0, TelegramRegistryError, DriftFinding) -> tuple[list[Any], int]:
    if status not in {"all", "open", "resolved", "adopted", "ignored"}:
        raise TelegramRegistryError("drift status is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200 or not isinstance(offset, int) or offset < 0:
        raise TelegramRegistryError("invalid pagination")
    where = "hidden_at IS NULL" + (" AND status = ?" if status != "all" else "")
    args = (status,) if status != "all" else ()
    with connect(self._db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM telegram_drift_findings WHERE {where}", args).fetchone()[0])
        rows = conn.execute(f"SELECT id,kind,customer_id,node_id,remote_email,remote_client_id,remote_sub_id,status,row_version,last_seen_at FROM telegram_drift_findings WHERE {where} ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END,last_seen_at DESC,id DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
        result = []
        for row in rows:
            customer = conn.execute("SELECT email_display FROM customers WHERE id=?", (row[2],)).fetchone() if row[2] is not None else None
            node = conn.execute("SELECT name FROM nodes WHERE id=?", (row[3],)).fetchone()
            result.append(DriftFinding(finding_id=int(row[0]), kind=str(row[1]), customer_id=int(row[2]) if row[2] is not None else None, customer_email=str(customer[0]) if customer else None, node_id=int(row[3]), node_name=str(node[0]) if node else "", remote_email=str(row[4]), remote_client_id=str(row[5]), remote_sub_id=str(row[6]), status=str(row[7]), row_version=int(row[8]), last_seen_at=str(row[9])))
    return result, total

def dismissed_operation_ids(self, operation_ids: list[int]) -> set[int]:
    ids = [int(item) for item in operation_ids]
    if not ids:
        return set()
    with connect(self._db_path) as conn:
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(f"SELECT id FROM telegram_customer_operations WHERE dismissed_at IS NOT NULL AND id IN ({marks})", ids).fetchall()
    return {int(row[0]) for row in rows}

def list_bindings_page(self, *, management_state: str | None=None, limit: int=100, offset: int=0, TelegramRegistryError) -> tuple[list[dict[str, Any]], int]:
    if management_state not in (None, "missing", "conflict"):
        raise TelegramRegistryError("binding state is invalid")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200 or offset < 0:
        raise TelegramRegistryError("invalid pagination")
    clause = "WHERE b.management_state = ?" if management_state else "WHERE b.management_state IN ('missing','conflict')"
    args: tuple[Any, ...] = (management_state,) if management_state else ()
    with connect(self._db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM customer_node_bindings b {clause}", args).fetchone()[0])
        rows = conn.execute(
            f"SELECT b.id, b.customer_id, c.email_display, b.node_id, n.name, b.management_state, b.desired_enabled "
            f"FROM customer_node_bindings b JOIN customers c ON c.id=b.customer_id JOIN nodes n ON n.id=b.node_id {clause} "
            "ORDER BY b.id DESC LIMIT ? OFFSET ?", (*args, limit, offset),
        ).fetchall()
    return [{"binding_id": int(r[0]), "customer_id": int(r[1]), "customer_email": str(r[2]), "node_id": int(r[3]), "node_name": str(r[4]), "management_state": str(r[5]), "desired_enabled": bool(r[6]) if r[6] is not None else None} for r in rows], total

def list_audit_page(self, *, limit: int=100, offset: int=0, outcome: str = "all", TelegramRegistryError) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(limit, int) or not 1 <= limit <= 200 or not isinstance(offset, int) or offset < 0:
        raise TelegramRegistryError("invalid pagination")
    if outcome not in {"all", "error", "success"}:
        raise TelegramRegistryError("audit outcome is invalid")
    clause = ""
    if outcome == "error":
        clause = " WHERE lower(event_type) LIKE '%error%' OR lower(event_type) LIKE '%fail%'"
    elif outcome == "success":
        clause = " WHERE lower(event_type) NOT LIKE '%error%' AND lower(event_type) NOT LIKE '%fail%'"
    with connect(self._db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM telegram_audit_log{clause}").fetchone()[0])
        rows = conn.execute(f"SELECT id,event_type,actor_type,actor_id,entity_type,entity_id,created_at FROM telegram_audit_log{clause} ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return [{"id": int(r[0]), "event_type": str(r[1]), "actor_type": str(r[2]), "actor_id": r[3], "entity_type": str(r[4]), "entity_id": str(r[5]), "created_at": str(r[6])} for r in rows], total

def clear_customer_operation_history(self, *, idempotency_key: object, cleared_by: object, mode: str = "safe", _nonempty, _payload_digest, TelegramRegistryError, IdempotencyConflictError) -> int | dict[str, int]:
    key, actor = _nonempty(idempotency_key, "idempotency_key"), _nonempty(cleared_by, "cleared_by")
    if mode not in {"safe", "all"}:
        raise TelegramRegistryError("history clear mode is invalid")
    digest = _payload_digest({"statuses": ("succeeded", "cancelled", "dismissed"), "mode": mode})
    scope = "customer_operation_history_clear"
    with connect(self._db_path) as conn:
        receipt = conn.execute("SELECT payload_digest,result_json FROM telegram_command_receipts WHERE scope=? AND idempotency_key=?", (scope, key)).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            result = json.loads(str(receipt[1]))
            return result if mode == "all" else int(result["deleted_count"])
        ids = [r[0] for r in conn.execute("SELECT id FROM telegram_customer_operations WHERE hidden_at IS NULL AND (status IN ('succeeded','cancelled') OR dismissed_at IS NOT NULL) AND NOT EXISTS (SELECT 1 FROM telegram_bulk_lifecycle_items bi WHERE bi.operation_id=telegram_customer_operations.id) AND NOT EXISTS (SELECT 1 FROM customer_node_bindings sb WHERE sb.suspended_by_operation_id=telegram_customer_operations.id)").fetchall()]
        if ids:
            ph = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM telegram_customer_operations WHERE id IN ({ph})", ids)
        hidden = conn.execute("UPDATE telegram_customer_operations SET hidden_at = CURRENT_TIMESTAMP WHERE hidden_at IS NULL AND (status IN ('succeeded','cancelled') OR dismissed_at IS NOT NULL)").rowcount if mode == "all" else 0
        result = {"deleted_count": len(ids), "hidden_count": hidden}
        conn.execute("INSERT INTO telegram_command_receipts(scope,idempotency_key,payload_digest,result_json) VALUES(?,?,?,?)", (scope, key, digest, json.dumps(result, separators=(",", ":"))))
        conn.execute("INSERT INTO telegram_audit_log(event_type,actor_type,actor_id,entity_type,entity_id,payload_digest) VALUES('customer_operation_history_cleared','admin',?,'customer_operation_history',?,?)", (actor, mode, digest))
    return result if mode == "all" else len(ids)

def clear_drift_history(self, *, idempotency_key: object, cleared_by: object, mode: str = "safe", _nonempty, _payload_digest, TelegramRegistryError, IdempotencyConflictError) -> int | dict[str, int]:
    key, actor = _nonempty(idempotency_key, "idempotency_key"), _nonempty(cleared_by, "cleared_by")
    if mode not in {"safe", "all"}:
        raise TelegramRegistryError("history clear mode is invalid")
    digest = _payload_digest({"statuses": ("resolved", "adopted", "ignored_safe"), "mode": mode})
    scope = "drift_history_clear"
    with connect(self._db_path) as conn:
        receipt = conn.execute("SELECT payload_digest,result_json FROM telegram_command_receipts WHERE scope=? AND idempotency_key=?", (scope, key)).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            result = json.loads(str(receipt[1]))
            return result if mode == "all" else int(result["deleted_count"])
        deleted = conn.execute("DELETE FROM telegram_drift_findings WHERE hidden_at IS NULL AND (status IN ('resolved','adopted') OR (status='ignored' AND kind IN ('binding_missing','binding_conflict') AND NOT EXISTS (SELECT 1 FROM customer_node_bindings b WHERE b.customer_id=telegram_drift_findings.customer_id AND b.node_id=telegram_drift_findings.node_id AND b.management_state IN ('missing','conflict'))))").rowcount
        hidden = conn.execute("UPDATE telegram_drift_findings SET hidden_at = CURRENT_TIMESTAMP WHERE hidden_at IS NULL AND status <> 'open'").rowcount if mode == "all" else 0
        result = {"deleted_count": int(deleted), "hidden_count": int(hidden)}
        conn.execute("INSERT INTO telegram_command_receipts(scope,idempotency_key,payload_digest,result_json) VALUES(?,?,?,?)", (scope, key, digest, json.dumps(result, separators=(",", ":"))))
        conn.execute("INSERT INTO telegram_audit_log(event_type,actor_type,actor_id,entity_type,entity_id,payload_digest) VALUES('drift_history_cleared','admin',?,'drift_history',?,?)", (actor, mode, digest))
    return result if mode == "all" else int(deleted)

def clear_audit_history(self, *, idempotency_key: object, cleared_by: object, _nonempty, _payload_digest, IdempotencyConflictError) -> dict[str, int]:
    key, actor = _nonempty(idempotency_key, "idempotency_key"), _nonempty(cleared_by, "cleared_by")
    digest = _payload_digest({"section": "audit"})
    with connect(self._db_path) as conn:
        receipt = conn.execute("SELECT payload_digest,result_json FROM telegram_command_receipts WHERE scope='audit_history_clear' AND idempotency_key=?", (key,)).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return json.loads(str(receipt[1]))
        deleted = conn.execute("DELETE FROM telegram_audit_log").rowcount
        result = {"deleted_count": int(deleted), "hidden_count": 0}
        conn.execute("INSERT INTO telegram_audit_log(event_type,actor_type,actor_id,entity_type,entity_id,payload_digest) VALUES('audit_cleared','admin',?,'audit','all',?)", (actor, _payload_digest(result)))
        conn.execute("INSERT INTO telegram_command_receipts(scope,idempotency_key,payload_digest,result_json) VALUES('audit_history_clear',?,?,?)", (key, digest, json.dumps(result, separators=(",", ":"))))
    return result

def forget_all_missing_bindings(self, *, node_id: int | None, actor: object, idempotency_key: object, _nonempty, _payload_digest, _positive_int, IdempotencyConflictError) -> dict[str, Any]:
    actor_id = _nonempty(actor, "actor")
    key = _nonempty(idempotency_key, "idempotency_key")
    digest = _payload_digest({"node_id": node_id})
    if node_id is not None:
        node_id = _positive_int(node_id, "node_id")
    with connect(self._db_path) as conn:
        receipt = conn.execute("SELECT payload_digest,result_json FROM telegram_command_receipts WHERE scope='missing_bindings_forget' AND idempotency_key=?", (key,)).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return json.loads(str(receipt[1]))
        clause = "AND node_id = ?" if node_id is not None else ""
        args = (node_id,) if node_id is not None else ()
        ids = [int(r[0]) for r in conn.execute(f"SELECT id FROM customer_node_bindings WHERE management_state='missing' {clause}", args).fetchall()]
        forgotten = sum(self._forget_missing_binding(conn, item, actor_type="admin", actor_id=actor_id) for item in ids)
        result = {"forgotten": forgotten, "busy": len(ids) - forgotten}
        conn.execute("INSERT INTO telegram_audit_log(event_type,actor_type,actor_id,entity_type,entity_id,payload_digest) VALUES('missing_bindings_forgotten','admin',?,'missing_bindings',?,?)", (actor_id, str(node_id) if node_id is not None else 'all', digest))
        conn.execute("INSERT INTO telegram_command_receipts(scope,idempotency_key,payload_digest,result_json) VALUES('missing_bindings_forget',?,?,?)", (key, digest, json.dumps(result, separators=(",", ":"))))
    return result

def run_history_retention(self) -> dict[str, int]:
    days = int(os.getenv("TELEGRAM_HISTORY_RETENTION_DAYS", "60") or 60)
    audit_days = int(os.getenv("TELEGRAM_AUDIT_RETENTION_DAYS", "365") or 365)
    if days < 0 or audit_days < 0:
        return {"operations": 0, "findings": 0, "jobs": 0, "audit": 0}
    with connect(self._db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        params = (f"-{days} days",)
        op = conn.execute("DELETE FROM telegram_customer_operations WHERE hidden_at IS NULL AND (status IN ('succeeded','cancelled') OR dismissed_at IS NOT NULL) AND COALESCE(finished_at, dismissed_at, updated_at, created_at) < datetime('now', ?) AND NOT EXISTS (SELECT 1 FROM telegram_bulk_lifecycle_items bi WHERE bi.operation_id=telegram_customer_operations.id) AND NOT EXISTS (SELECT 1 FROM customer_node_bindings sb WHERE sb.suspended_by_operation_id=telegram_customer_operations.id)", params).rowcount if days else 0
        finding = conn.execute("DELETE FROM telegram_drift_findings WHERE hidden_at IS NULL AND status IN ('resolved','adopted') AND COALESCE(resolved_at,last_seen_at) < datetime('now', ?)", params).rowcount if days else 0
        jobs = 0  # provisioning snapshots feed expiry/traffic reminders and initial-job state: only the manual clear removes them
        audit = conn.execute("DELETE FROM telegram_audit_log WHERE created_at < datetime('now', ?)", (f"-{audit_days} days",)).rowcount if audit_days else 0
        conn.execute("UPDATE telegram_drift_findings SET status='resolved', resolved_at=CURRENT_TIMESTAMP, row_version=row_version+1 WHERE status='ignored' AND kind IN ('binding_missing','binding_conflict') AND NOT EXISTS (SELECT 1 FROM customer_node_bindings b WHERE b.customer_id=telegram_drift_findings.customer_id AND b.node_id=telegram_drift_findings.node_id AND b.management_state IN ('missing','conflict'))")
    return {"operations": int(op), "findings": int(finding), "jobs": int(jobs), "audit": int(audit)}

def get_provisioning_job(self, job_id: int, *, _positive_int, TelegramRegistryError, ProvisioningJobStatus, ProvisioningAttemptStatus) -> Any:
    normalized_job_id = _positive_int(job_id, "job_id")
    with connect(self._db_path) as conn:
        job = conn.execute(
            """
                SELECT j.id, j.customer_id, c.email_display, j.trigger, j.status, j.attempt_count,
                       j.row_version, j.created_at, j.finished_at
                FROM telegram_provisioning_jobs AS j
                JOIN customers AS c ON c.id = j.customer_id
                WHERE j.id = ?
                """,
            (normalized_job_id,),
        ).fetchone()
        attempts = conn.execute(
            """
                SELECT a.node_id, n.name, a.status, a.error_code, a.error_summary,
                       a.attempt_count, a.next_attempt_at
                FROM telegram_provisioning_attempts AS a
                JOIN nodes AS n ON n.id = a.node_id
                WHERE a.job_id = ?
                ORDER BY n.name COLLATE NOCASE, a.node_id
                """,
            (normalized_job_id,),
        ).fetchall()
    if job is None:
        raise TelegramRegistryError("provisioning job was not found")
    return ProvisioningJobStatus(
        job_id=int(job[0]), customer_id=int(job[1]), customer_email=str(job[2]),
        trigger=str(job[3]), status=str(job[4]), attempt_count=int(job[5]), row_version=int(job[6]),
        created_at=str(job[7]), finished_at=str(job[8]) if job[8] is not None else None,
        attempts=tuple(
            ProvisioningAttemptStatus(
                node_id=int(attempt[0]), node_name=str(attempt[1]), status=str(attempt[2]),
                error_code=str(attempt[3]) if attempt[3] is not None else None,
                error_summary=str(attempt[4]) if attempt[4] is not None else None,
                attempt_count=int(attempt[5]),
                next_attempt_at=str(attempt[6]) if attempt[6] is not None else None,
            )
            for attempt in attempts
        ),
    )

def reschedule_provisioning_job(self, *, job_id: int, expected_job_version: int, idempotency_key: str, requested_by: str, action: str, _positive_int, _nonempty, _payload_digest, TelegramRegistryError, IdempotencyConflictError, VersionConflictError, ProvisioningRescheduleResult) -> Any:
    """Queue a safe read-first retry/reconcile; it never calls a node inline."""

    normalized_job_id = _positive_int(job_id, "job_id")
    expected_version = _positive_int(expected_job_version, "expected_job_version")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(requested_by, "requested_by")
    if action not in {"retry", "reconcile", "dismiss"}:
        raise TelegramRegistryError("unsupported provisioning action")
    dismiss = action == "dismiss"
    payload = {"job_id": normalized_job_id, "expected_job_version": expected_version}
    digest = _payload_digest(payload)
    scope = f"provisioning_{action}"
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts WHERE scope = ? AND idempotency_key = ?",
            (scope, key),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return ProvisioningRescheduleResult(**json.loads(str(receipt[1])))
        job = conn.execute(
            "SELECT status, row_version, lease_until FROM telegram_provisioning_jobs WHERE id = ?",
            (normalized_job_id,),
        ).fetchone()
        if job is None:
            raise TelegramRegistryError("provisioning job was not found")
        if int(job[1]) != expected_version:
            raise VersionConflictError("provisioning job was updated by another worker or administrator")
        if str(job[0]) not in {"queued", "partial", "failed"} or job[2] is not None:
            raise VersionConflictError("provisioning job cannot be rescheduled in its current state")
        if not dismiss:
            changed = conn.execute(
                """
                    UPDATE telegram_provisioning_attempts
                    SET status = 'pending', error_code = NULL, error_summary = NULL, next_attempt_at = NULL,
                        finished_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE job_id = ? AND status IN ('failed', 'skipped', 'ambiguous')
                    """,
                (normalized_job_id,),
            )
            if changed.rowcount == 0:
                raise VersionConflictError("provisioning job has no retryable attempts")
        new_status = "cancelled" if dismiss else "queued"
        update = conn.execute(
            """
                UPDATE telegram_provisioning_jobs
                SET status = ?, next_attempt_at = NULL,
                    finished_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND lease_until IS NULL
                """,
            (new_status, dismiss, normalized_job_id, expected_version),
        )
        if update.rowcount != 1:
            raise VersionConflictError("provisioning job was updated by another worker or administrator")
        result = ProvisioningRescheduleResult(
            job_id=normalized_job_id, status=new_status, row_version=expected_version + 1
        )
        conn.execute(
            """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'telegram_provisioning_job', ?, ?)
                """,
            ("provisioning_dismissed" if dismiss else f"provisioning_{action}_queued", actor, str(normalized_job_id), digest),
        )
        conn.execute(
            """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES (?, ?, ?, ?)
                """,
            (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result

def list_node_provisioning_policies(self, *, _policy_from_row, NodeProvisioningPolicy) -> Any:
    """Return persisted policies only; absent rows mean the safe off default."""

    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
                SELECT node_id, provisioning_enabled, total_bytes, validity_days,
                       client_enabled, policy_version, updated_by
                FROM telegram_node_policies
                ORDER BY node_id
                """
        ).fetchall()
    return [_policy_from_row(row) for row in rows]
