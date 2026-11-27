"""Telegram node bulk operations and customer-node matrix helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from services.db_bootstrap import connect


def _node_bulk_action(value: str, *, error_type) -> str:
    if value not in {"add_all", "remove_all"}:
        raise error_type("unsupported node bulk action")
    return value


def _node_bulk_action_snapshot(
    self, conn: sqlite3.Connection, *, node_id: int, action: str, page: int,
    error_type, node_policy_error, lifecycle_error, preview_type, payload_digest
) -> tuple[Any, tuple[dict[str, Any], ...]]:
    """Build a local-only immutable target snapshot for one node action."""

    node = conn.execute(
        """
        SELECT n.id, n.name, n.enabled, n.read_only, p.provisioning_enabled,
               p.total_bytes, p.validity_days, p.client_enabled, p.policy_version
        FROM nodes AS n
        LEFT JOIN telegram_node_policies AS p ON p.node_id = n.id
        WHERE n.id = ?
        """,
        (node_id,),
    ).fetchone()
    if node is None:
        raise error_type("node was not found")
    node_name = str(node[1])

    if action == "add_all":
        if node[4] is None or not bool(node[4]) or not bool(node[2]) or bool(node[3]):
            raise node_policy_error("node is not eligible for Telegram provisioning")
        rows = conn.execute(
            """
            SELECT c.id, c.row_version, c.email_display
            FROM customers AS c
            LEFT JOIN customer_node_bindings AS b
              ON b.customer_id = c.id AND b.node_id = ? AND b.inbound_id = 1
            WHERE c.status = 'active' AND c.deleted_at IS NULL
              AND EXISTS (
                  SELECT 1 FROM telegram_identities AS i
                  WHERE i.customer_id = c.id AND i.access_status = 'approved'
              )
              AND (b.id IS NULL OR b.management_state = 'missing')
              AND NOT EXISTS (
                  SELECT 1
                  FROM telegram_provisioning_jobs AS j
                  JOIN telegram_provisioning_attempts AS a ON a.job_id = j.id
                  WHERE j.customer_id = c.id AND a.node_id = ? AND a.inbound_id = 1
                    AND j.status IN ('queued', 'running', 'partial')
                    AND a.status IN ('pending', 'reconciling', 'creating', 'ambiguous')
              )
            ORDER BY c.id
            """,
            (node_id, node_id),
        ).fetchall()
        targets = tuple(
            {
                "customer_id": int(row[0]),
                "customer_version": int(row[1]),
                "email": str(row[2]),
            }
            for row in rows
        )
    else:
        inflight = conn.execute(
            """
            SELECT 1
            FROM telegram_provisioning_attempts AS a
            JOIN telegram_provisioning_jobs AS j ON j.id = a.job_id
            WHERE a.node_id = ? AND j.status IN ('queued', 'running', 'partial')
              AND a.status IN ('reconciling', 'creating')
            UNION ALL
            SELECT 1
            FROM telegram_customer_operation_attempts AS a
            JOIN telegram_customer_operations AS o ON o.id = a.operation_id
            WHERE a.node_id = ? AND o.status IN ('queued', 'running', 'partial')
              AND o.dismissed_at IS NULL
              AND a.status IN ('pending', 'ambiguous', 'reconciling', 'writing')
            LIMIT 1
            """,
            (node_id, node_id),
        ).fetchone()
        if inflight is not None:
            raise lifecycle_error("node has an in-flight remote operation")
        rows = conn.execute(
            """
            SELECT b.id, c.id, c.row_version, b.inbound_id, b.remote_client_id,
                   b.remote_sub_id, b.remote_email
            FROM customer_node_bindings AS b
            JOIN customers AS c ON c.id = b.customer_id
            WHERE b.node_id = ? AND b.inbound_id = 1
              AND b.management_state = 'confirmed' AND b.remote_client_id IS NOT NULL
              AND b.remote_client_id <> ''
              AND c.deleted_at IS NULL AND c.status <> 'deleted'
              AND EXISTS (
                  SELECT 1 FROM telegram_identities AS i WHERE i.customer_id = c.id
              )
            ORDER BY b.id
            """,
            (node_id,),
        ).fetchall()
        targets = tuple(
            {
                "binding_id": int(row[0]),
                "customer_id": int(row[1]),
                "customer_version": int(row[2]),
                "inbound_id": int(row[3]),
                "remote_client_id": str(row[4]),
                "remote_sub_id": str(row[5] or ""),
                "remote_email": str(row[6]),
            }
            for row in rows
        )

    snapshot = {
        "node_id": node_id,
        "node_name": node_name,
        "policy_version": int(node[8]) if node[8] is not None else 0,
        "action": action,
        "targets": targets,
    }
    return (
        preview_type(
            node_id=node_id,
            node_name=node_name,
            action=action,
            target_count=len(targets),
            target_snapshot_digest=payload_digest(snapshot),
            page=page,
        ),
        targets,
    )


def preview_node_bulk_action(
    self, *, node_id: int, action: str, page: int = 0,
    positive_int, error_type, node_policy_error, lifecycle_error, preview_type, payload_digest
) -> Any:
    normalized_node_id = positive_int(node_id, "node_id")
    normalized_action = self._node_bulk_action(action)
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise error_type("page is invalid")
    with connect(self._db_path) as conn:
        preview, _ = self._node_bulk_action_snapshot(
            conn, node_id=normalized_node_id, action=normalized_action, page=page
        )
    return preview


def begin_node_bulk_action_preview(
    self, *, admin_telegram_user_id: int, node_id: int, action: str, page: int,
    positive_int, error_type, node_policy_error, lifecycle_error, preview_type, payload_digest
) -> Any:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    normalized_node_id = positive_int(node_id, "node_id")
    normalized_action = self._node_bulk_action(action)
    if isinstance(page, bool) or not isinstance(page, int) or page < 0:
        raise error_type("page is invalid")
    with connect(self._db_path) as conn:
        preview, _ = self._node_bulk_action_snapshot(
            conn, node_id=normalized_node_id, action=normalized_action, page=page
        )
        conn.execute(
            """
            INSERT INTO telegram_node_bulk_action_previews
                (admin_telegram_user_id, node_id, action, target_snapshot_digest, target_count, page)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(admin_telegram_user_id) DO UPDATE SET
                node_id = excluded.node_id, action = excluded.action,
                target_snapshot_digest = excluded.target_snapshot_digest,
                target_count = excluded.target_count, page = excluded.page,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                admin_id, preview.node_id, preview.action, preview.target_snapshot_digest,
                preview.target_count, preview.page,
            ),
        )
    return preview


def clear_node_bulk_action_preview(self, admin_telegram_user_id: int, *, positive_int) -> None:
    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    with connect(self._db_path) as conn:
        conn.execute(
            "DELETE FROM telegram_node_bulk_action_previews WHERE admin_telegram_user_id = ?",
            (admin_id,),
        )


def queue_node_bulk_action(
    self,
    *,
    admin_telegram_user_id: int,
    node_id: int,
    action: str,
    idempotency_key: str,
    created_by: str,
    notify: bool = True,
    positive_int, nonempty, payload_digest, error_type, node_policy_error,
    lifecycle_error, version_conflict_error, idempotency_conflict_error,
    queue_result_type, preview_type, mark_completed_initial_snapshot,
    inbound_id, client_flow
) -> Any:
    """Queue a confirmed node-wide action without doing remote I/O.

    `remove_all` deliberately uses node-scoped lifecycle rows with the
    real `delete_client` action.  Its operation type remains
    `suspend_node` for backwards-compatible SQLite constraints; the
    lifecycle worker keys behavior off the immutable attempt action, and
    therefore never changes the global customer lifecycle state.
    """

    admin_id = positive_int(admin_telegram_user_id, "admin_telegram_user_id")
    normalized_node_id = positive_int(node_id, "node_id")
    normalized_action = self._node_bulk_action(action)
    key = nonempty(idempotency_key, "idempotency_key")
    actor = nonempty(created_by, "created_by")
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            """
            SELECT result_json FROM telegram_command_receipts
            WHERE scope = 'node_bulk_action' AND idempotency_key = ?
            """,
            (key,),
        ).fetchone()
        if receipt is not None:
            replay = queue_result_type(**json.loads(str(receipt[0])))
            if replay.node_id != normalized_node_id or replay.action != normalized_action:
                raise idempotency_conflict_error("idempotency key was already used for another command")
            return replay
        stored_preview = conn.execute(
            """
            SELECT target_snapshot_digest, target_count, page
            FROM telegram_node_bulk_action_previews
            WHERE admin_telegram_user_id = ? AND node_id = ? AND action = ?
            """,
            (admin_id, normalized_node_id, normalized_action),
        ).fetchone()
        if stored_preview is None:
            raise version_conflict_error("node bulk confirmation is missing")
        preview, targets = self._node_bulk_action_snapshot(
            conn, node_id=normalized_node_id, action=normalized_action,
            page=int(stored_preview[2])
        )
        if (
            preview.target_snapshot_digest != str(stored_preview[0])
            or preview.target_count != int(stored_preview[1])
        ):
            raise version_conflict_error("node bulk preview is stale")
        payload = {
            "node_id": normalized_node_id,
            "action": normalized_action,
            "target_snapshot_digest": preview.target_snapshot_digest,
        }
        digest = payload_digest(payload)
        cancelled_attempt_count = 0
        if normalized_action == "add_all":
            policy = conn.execute(
                """
                SELECT total_bytes, validity_days, client_enabled, policy_version
                FROM telegram_node_policies WHERE node_id = ? AND provisioning_enabled = 1
                """,
                (normalized_node_id,),
            ).fetchone()
            if policy is None:
                raise node_policy_error("node is not eligible for Telegram provisioning")
            desired_expiry_time = (
                int(datetime.now(timezone.utc).timestamp() * 1000)
                + int(policy[1]) * 24 * 60 * 60 * 1000
                if int(policy[1]) > 0
                else 0
            )
            for target in targets:
                job = conn.execute(
                    """
                    INSERT INTO telegram_provisioning_jobs
                        (customer_id, trigger, idempotency_key, policy_snapshot_digest, created_by, notify_user)
                    VALUES (?, 'node_backfill', ?, ?, ?, ?)
                    """,
                    (
                        target["customer_id"], f"node-bulk-add:{key}:{target['customer_id']}",
                        payload_digest({
                            "customer_id": target["customer_id"], "node_id": normalized_node_id,
                            "email": target["email"], "inbound_id": inbound_id,
                            "flow": client_flow, "policy_version": int(policy[3]),
                        }),
                        actor, int(notify),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO telegram_provisioning_attempts
                        (job_id, node_id, inbound_id, desired_client_id, desired_sub_id,
                         desired_flow, desired_total_bytes, desired_validity_days,
                         desired_expiry_time, desired_client_enabled, policy_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(job.lastrowid), normalized_node_id, inbound_id,
                        str(uuid.uuid4()), str(uuid.uuid4()), client_flow,
                        int(policy[0]), int(policy[1]), desired_expiry_time,
                        int(bool(policy[2])), int(policy[3]),
                    ),
                )
            queued_count = len(targets)
        else:
            cancelled_attempt_count = conn.execute(
                """
                UPDATE telegram_provisioning_attempts
                SET status = 'skipped', error_code = 'node_bulk_remove_cancelled',
                    error_summary = NULL, finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE node_id = ? AND status IN ('pending', 'ambiguous')
                  AND job_id IN (
                      SELECT id FROM telegram_provisioning_jobs
                      WHERE status IN ('queued', 'running', 'partial')
                  )
                """,
                (normalized_node_id,),
            ).rowcount
            conn.execute(
                """
                UPDATE telegram_provisioning_jobs AS j
                SET status = 'cancelled', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = NULL, finished_at = CURRENT_TIMESTAMP,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE j.status IN ('queued', 'running', 'partial')
                  AND EXISTS (
                      SELECT 1 FROM telegram_provisioning_attempts AS a
                      WHERE a.job_id = j.id AND a.node_id = ?
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM telegram_provisioning_attempts AS a
                      WHERE a.job_id = j.id
                        AND a.status IN ('pending', 'ambiguous', 'reconciling', 'creating')
                  )
                """,
                (normalized_node_id,),
            )
            for (job_id,) in conn.execute(
                "SELECT DISTINCT j.id FROM telegram_provisioning_jobs j "
                "JOIN telegram_provisioning_attempts a ON a.job_id = j.id "
                "WHERE a.node_id = ? AND j.trigger = 'approve_new' AND j.status = 'cancelled'",
                (normalized_node_id,),
            ).fetchall():
                mark_completed_initial_snapshot(conn, int(job_id))
            policy = conn.execute(
                "SELECT node_id FROM telegram_node_policies WHERE node_id = ?", (normalized_node_id,)
            ).fetchone()
            if policy is None:
                conn.execute(
                    """
                    INSERT INTO telegram_node_policies
                        (node_id, provisioning_enabled, total_bytes, validity_days,
                         client_enabled, policy_version, updated_by)
                    VALUES (?, 0, 0, 0, 1, 1, ?)
                    """,
                    (normalized_node_id, actor),
                )
            else:
                conn.execute(
                    """
                    UPDATE telegram_node_policies
                    SET provisioning_enabled = 0, policy_version = policy_version + 1,
                        updated_by = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE node_id = ?
                    """,
                    (actor, normalized_node_id),
                )
            for target in targets:
                target_snapshot = {
                    "customer_id": target["customer_id"], "node_id": normalized_node_id,
                    "operation_type": "remove_node_binding", "target": target,
                }
                operation = conn.execute(
                    """
                    INSERT INTO telegram_customer_operations
                        (customer_id, operation_type, status, target_snapshot_digest,
                         expected_customer_version, idempotency_key, created_by)
                    VALUES (?, 'suspend_node', 'queued', ?, ?, ?, ?)
                    """,
                    (
                        target["customer_id"], payload_digest(target_snapshot), target["customer_version"],
                        f"node-bulk-remove:{key}:{target['binding_id']}", actor,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO telegram_customer_operation_attempts
                        (operation_id, binding_id, node_id, inbound_id, remote_client_id,
                         remote_sub_id, remote_email, action, previous_enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'delete_client', NULL)
                    """,
                    (
                        int(operation.lastrowid), target["binding_id"], normalized_node_id,
                        target["inbound_id"], target["remote_client_id"],
                        target["remote_sub_id"], target["remote_email"],
                    ),
                )
            queued_count = len(targets)

        result = queue_result_type(
            node_id=normalized_node_id, action=normalized_action, target_count=len(targets),
            queued_count=queued_count, cancelled_attempt_count=cancelled_attempt_count,
        )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES ('node_bulk_action', ?, ?, ?)
            """,
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES (?, 'admin', ?, 'node', ?, ?)
            """,
            (f"node_bulk_{normalized_action}_queued", actor, str(normalized_node_id), digest),
        )
        conn.execute(
            "DELETE FROM telegram_node_bulk_action_previews WHERE admin_telegram_user_id = ?",
            (admin_id,),
        )
    return result


def _customer_node_state_counts(conn: sqlite3.Connection, customer_ids: Iterable[int], *, classify_customer_node_state, node_states) -> dict[int, dict[str, int]]:
    """Count customer node states with local data for a set of customers."""

    normalized_customer_ids = tuple(sorted({int(customer_id) for customer_id in customer_ids}))
    if not normalized_customer_ids:
        return {}
    placeholders = ", ".join("?" for _ in normalized_customer_ids)
    eligible_rows = conn.execute(
        """
        SELECT n.id
        FROM telegram_node_policies AS p
        JOIN nodes AS n ON n.id = p.node_id
        WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
        """
    ).fetchall()
    eligible_node_ids = {int(row[0]) for row in eligible_rows}
    counts = {
        customer_id: {state: 0 for state in node_states}
        for customer_id in normalized_customer_ids
    }
    bound_eligible_node_ids: dict[int, set[int]] = {
        customer_id: set() for customer_id in normalized_customer_ids
    }
    bound_rows = conn.execute(
        f"""
        SELECT b.customer_id, b.node_id, n.enabled, n.read_only,
               b.desired_enabled, b.management_state
        FROM customer_node_bindings AS b
        JOIN nodes AS n ON n.id = b.node_id
        WHERE b.customer_id IN ({placeholders})
        """,
        normalized_customer_ids,
    ).fetchall()
    for customer_id, node_id, enabled, read_only, desired_enabled, management_state in bound_rows:
        local_customer_id = int(customer_id)
        local_node_id = int(node_id)
        if management_state == "missing" and local_node_id not in eligible_node_ids:
            continue
        state = classify_customer_node_state(
            binding_present=True,
            management_state=str(management_state) if management_state is not None else None,
            enabled=bool(enabled),
            read_only=bool(read_only),
            desired_enabled=bool(desired_enabled) if desired_enabled is not None else None,
            eligible=local_node_id in eligible_node_ids,
        )
        counts[local_customer_id][state] += 1
        if local_node_id in eligible_node_ids:
            bound_eligible_node_ids[local_customer_id].add(local_node_id)
    for customer_id in normalized_customer_ids:
        state = classify_customer_node_state(
            binding_present=False,
            management_state=None,
            enabled=True,
            read_only=False,
            desired_enabled=None,
            eligible=True,
        )
        if state == "available_to_add":
            counts[customer_id][state] += len(eligible_node_ids) - len(bound_eligible_node_ids[customer_id])
    return counts


def customer_node_matrix(self, customer_id: int, *, positive_int, error_type, classify_customer_node_state, matrix_row_type) -> list[Any]:
    """Return only bindings plus genuine Telegram-enabled add targets."""

    normalized_customer_id = positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        bound_rows = conn.execute(
            """
            SELECT b.id, n.id, n.name, n.enabled, n.read_only,
                   b.desired_enabled, b.management_state
            FROM customer_node_bindings AS b
            JOIN nodes AS n ON n.id = b.node_id
            WHERE b.customer_id = ?
            ORDER BY n.name COLLATE NOCASE, n.id
            """,
            (normalized_customer_id,),
        ).fetchall()
        available_rows = conn.execute(
            """
            SELECT n.id, n.name
            FROM telegram_node_policies AS p
            JOIN nodes AS n ON n.id = p.node_id
            WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
            ORDER BY n.name COLLATE NOCASE, n.id
            """
        ).fetchall()
        eligible_node_ids = {int(row[0]) for row in available_rows}

    result: list[Any] = []
    for binding_id, node_id, name, enabled, read_only, desired_enabled, management_state in bound_rows:
        if management_state == "missing" and int(node_id) not in eligible_node_ids:
            continue
        state = classify_customer_node_state(
            binding_present=True,
            management_state=str(management_state) if management_state is not None else None,
            enabled=bool(enabled),
            read_only=bool(read_only),
            desired_enabled=bool(desired_enabled) if desired_enabled is not None else None,
            eligible=int(node_id) in eligible_node_ids,
        )
        result.append(
            matrix_row_type(
                node_id=int(node_id),
                node_name=str(name),
                state=state,
                binding_id=int(binding_id),
                desired_enabled=bool(desired_enabled),
                management_state=str(management_state),
            )
        )
    bound_node_ids = {int(bound[1]) for bound in bound_rows}
    for node_id, name in available_rows:
        state = classify_customer_node_state(
            binding_present=False,
            management_state=None,
            enabled=True,
            read_only=False,
            desired_enabled=None,
            eligible=True,
        )
        if state == "available_to_add" and int(node_id) not in bound_node_ids:
            result.append(
                matrix_row_type(
                    node_id=int(node_id),
                    node_name=str(name),
                    state="available_to_add",
                    binding_id=None,
                    desired_enabled=None,
                    management_state=None,
                )
            )
    return result


def queue_customer_node_add(
    self,
    *,
    customer_id: int,
    node_id: int,
    expected_customer_version: int,
    idempotency_key: str,
    created_by: str,
    notify: bool = True,
    positive_int, nonempty, payload_digest, error_type, lifecycle_error,
    version_conflict_error, idempotency_conflict_error, node_policy_error,
    queue_result_type, inbound_id, client_flow
) -> Any:
    """Queue one exact node add using the same reconcile-first worker as approval."""

    local_customer_id = positive_int(customer_id, "customer_id")
    local_node_id = positive_int(node_id, "node_id")
    expected_version = positive_int(expected_customer_version, "expected_customer_version")
    key = nonempty(idempotency_key, "idempotency_key")
    actor = nonempty(created_by, "created_by")
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'customer_node_add' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        payload = {
            "customer_id": local_customer_id,
            "node_id": local_node_id,
            "expected_customer_version": expected_version,
        }
        if not notify:
            payload["notify"] = False
        digest = payload_digest(payload)
        if receipt:
            if str(receipt[0]) != digest:
                raise idempotency_conflict_error("idempotency key was already used for another command")
            return queue_result_type(**json.loads(str(receipt[1])))

        customer = conn.execute(
            "SELECT email_display, status, row_version FROM customers "
            "WHERE id = ? AND deleted_at IS NULL",
            (local_customer_id,),
        ).fetchone()
        if customer is None:
            raise error_type("customer was not found")
        if str(customer[1]) != "active":
            raise lifecycle_error("node can be added only to an active customer")
        if int(customer[2]) != expected_version:
            raise version_conflict_error("customer was updated by another operation")
        existing = conn.execute(
            "SELECT id, management_state FROM customer_node_bindings "
            "WHERE customer_id = ? AND node_id = ? AND inbound_id = 1",
            (local_customer_id, local_node_id),
        ).fetchone()
        if existing is not None and str(existing[1]) != "missing":
            raise version_conflict_error("customer is already assigned to this node")
        pending = conn.execute(
            """
            SELECT 1
            FROM telegram_provisioning_jobs AS j
            JOIN telegram_provisioning_attempts AS a ON a.job_id = j.id
            WHERE j.customer_id = ? AND a.node_id = ? AND a.inbound_id = 1
              AND j.status IN ('queued', 'running', 'partial')
              AND a.status IN ('pending', 'reconciling', 'creating', 'ambiguous')
            LIMIT 1
            """,
            (local_customer_id, local_node_id),
        ).fetchone()
        if pending is not None:
            raise lifecycle_error("customer is already being added to this node")
        policy = conn.execute(
            """
            SELECT p.provisioning_enabled, p.total_bytes, p.validity_days,
                   p.client_enabled, p.policy_version, n.enabled, n.read_only
            FROM telegram_node_policies AS p
            JOIN nodes AS n ON n.id = p.node_id
            WHERE p.node_id = ?
            """,
            (local_node_id,),
        ).fetchone()
        if policy is None or not bool(policy[0]) or not bool(policy[5]) or bool(policy[6]):
            raise node_policy_error("node is not eligible for Telegram provisioning")

        desired_expiry_time = (
            int(datetime.now(timezone.utc).timestamp() * 1000)
            + int(policy[2]) * 24 * 60 * 60 * 1000
            if int(policy[2]) > 0
            else 0
        )
        snapshot = {
            "customer_id": local_customer_id,
            "node_id": local_node_id,
            "email": str(customer[0]),
            "inbound_id": inbound_id,
            "flow": client_flow,
            "policy_version": int(policy[4]),
        }
        job = conn.execute(
            """
            INSERT INTO telegram_provisioning_jobs
                (customer_id, trigger, idempotency_key, policy_snapshot_digest, created_by, notify_user)
            VALUES (?, 'node_backfill', ?, ?, ?, ?)
            """,
            (local_customer_id, f"node-add:{key}", payload_digest(snapshot), actor, int(notify)),
        )
        job_id = int(job.lastrowid)
        conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, inbound_id, desired_client_id, desired_sub_id,
                 desired_flow, desired_total_bytes, desired_validity_days,
                 desired_expiry_time, desired_client_enabled, policy_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, local_node_id, inbound_id, str(uuid.uuid4()), str(uuid.uuid4()),
                client_flow, int(policy[1]), int(policy[2]), desired_expiry_time,
                int(bool(policy[3])), int(policy[4]),
            ),
        )
        update = conn.execute(
            "UPDATE customers SET row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND row_version = ? AND deleted_at IS NULL",
            (local_customer_id, expected_version),
        )
        if update.rowcount != 1:
            raise version_conflict_error("customer was updated by another operation")
        result = queue_result_type(
            job_id=job_id, customer_id=local_customer_id, node_id=local_node_id,
            status="queued", row_version=expected_version + 1,
        )
        conn.execute(
            "INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('customer_node_add', ?, ?, ?)",
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('customer_node_add_queued', 'admin', ?, 'customer', ?, ?)
            """,
            (actor, str(local_customer_id), digest),
        )
    return result
