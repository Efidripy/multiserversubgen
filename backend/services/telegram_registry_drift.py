"""Telegram drift inventory, findings, and adoption operations."""

from __future__ import annotations

import json
from typing import Any

from services.db_bootstrap import connect


def drift_inventory(self, *, node_ids: object = None, error_type, positive_int) -> dict[str, Any]:
        """Return a minimal local comparison set for a strictly read-only scan."""

        selected: tuple[int, ...] | None = None
        if node_ids is not None:
            if not isinstance(node_ids, (list, tuple)):
                raise error_type("node_ids must be a list")
            selected = tuple(sorted({positive_int(value, "node_id") for value in node_ids}))
            if not 1 <= len(selected) <= 20:
                raise error_type("drift scan requires 1 to 20 nodes")
        clause = ""
        parameters: list[Any] = []
        if selected:
            placeholders = ",".join("?" for _ in selected)
            clause = f" AND n.id IN ({placeholders})"
            parameters.extend(selected)
        with connect(self._db_path) as conn:
            nodes = conn.execute(
                f"""
                SELECT n.id, n.name FROM nodes AS n
                WHERE n.enabled = 1{clause}
                ORDER BY n.name COLLATE NOCASE, n.id
                """,
                tuple(parameters),
            ).fetchall()
            node_id_values = tuple(int(row[0]) for row in nodes)
            if not node_id_values:
                return {"nodes": (), "bindings": (), "customers": ()}
            placeholders = ",".join("?" for _ in node_id_values)
            bindings = conn.execute(
                f"""
                SELECT b.id, b.customer_id, b.node_id, b.remote_client_id, b.remote_sub_id, b.remote_email,
                       b.desired_enabled, c.email_display, c.email_canonical, b.management_state, b.row_version
                FROM customer_node_bindings AS b
                JOIN customers AS c ON c.id = b.customer_id
                WHERE b.inbound_id = 1 AND b.node_id IN ({placeholders})
                """,
                node_id_values,
            ).fetchall()
            customers = conn.execute(
                "SELECT id, email_display, email_canonical FROM customers WHERE deleted_at IS NULL"
            ).fetchall()
        return {
            "nodes": tuple({"node_id": int(row[0]), "node_name": str(row[1])} for row in nodes),
            "bindings": tuple({
                "binding_id": int(row[0]), "customer_id": int(row[1]), "node_id": int(row[2]),
                "remote_client_id": str(row[3] or ""), "remote_sub_id": str(row[4] or ""),
                "remote_email": str(row[5]), "desired_enabled": bool(row[6]),
                "customer_email": str(row[7]), "customer_canonical": str(row[8]),
                "management_state": str(row[9]), "row_version": int(row[10]),
            } for row in bindings),
            "customers": tuple({
                "customer_id": int(row[0]), "email_display": str(row[1]), "email_canonical": str(row[2]),
            } for row in customers),
        }


def sync_drift_binding_enabled(self, candidates: list[dict[str, Any]]) -> None:
        """Apply panel state only while the scanned binding is still unchanged and idle."""
        with connect(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            for item in candidates:
                enabled = int(item["remote_enabled"])
                cursor = conn.execute(
                    """
                    UPDATE customer_node_bindings
                    SET desired_enabled = ?, last_enabled = 1,
                        suspended_by_operation_id = CASE WHEN ? = 1 THEN NULL ELSE suspended_by_operation_id END,
                        row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND node_id = ? AND inbound_id = 1 AND management_state = 'confirmed'
                      AND remote_client_id = ? AND COALESCE(remote_sub_id, '') = ? AND remote_email = ?
                      AND desired_enabled = ? AND row_version = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM telegram_customer_operation_attempts AS a
                          JOIN telegram_customer_operations AS o ON o.id = a.operation_id
                          WHERE a.binding_id = customer_node_bindings.id
                            AND o.status IN ('queued', 'running', 'partial') AND o.dismissed_at IS NULL
                      )
                    """,
                    (enabled, enabled, item["binding_id"], item["node_id"], item["remote_client_id"],
                     item["remote_sub_id"], item["remote_email"], int(item["desired_enabled"]), item["row_version"]),
                )
                if cursor.rowcount:
                    conn.execute(
                        "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id) "
                        "VALUES ('drift_binding_enabled_synced', 'system', 'drift_scan', 'customer_node_binding', ?)",
                        (str(item["binding_id"]),),
                    )


def record_drift_findings(self, *, scanned_node_ids: object, findings: object, error_type, positive_int, payload_digest, list_drift_findings, finding_type) -> tuple[Any, ...]:
        if not isinstance(scanned_node_ids, (list, tuple)):
            raise error_type("scanned_node_ids must be a list")
        node_ids = tuple(sorted({positive_int(value, "node_id") for value in scanned_node_ids}))
        if not node_ids:
            return ()
        if not isinstance(findings, list):
            raise error_type("drift findings must be a list")
        normalized: list[dict[str, Any]] = []
        for item in findings:
            if not isinstance(item, dict) or item.get("kind") not in {"binding_missing", "binding_conflict", "orphan_remote"}:
                raise error_type("drift finding is invalid")
            node_id = positive_int(item.get("node_id"), "node_id")
            if node_id not in node_ids:
                raise error_type("drift finding refers to an unscanned node")
            customer_id = item.get("customer_id")
            if customer_id is not None:
                customer_id = positive_int(customer_id, "customer_id")
            remote_email = str(item.get("remote_email") or "").strip()
            remote_client_id = str(item.get("remote_client_id") or "").strip()
            remote_sub_id = str(item.get("remote_sub_id") or "").strip()
            if len(remote_email) > 128 or len(remote_client_id) > 128 or len(remote_sub_id) > 128:
                raise error_type("drift finding identity is too long")
            key = payload_digest({
                "kind": item["kind"], "customer_id": customer_id, "node_id": node_id,
                "remote_email": remote_email.casefold(), "remote_client_id": remote_client_id,
                "remote_sub_id": remote_sub_id,
            })
            normalized.append({
                "finding_key": key, "kind": item["kind"], "customer_id": customer_id, "node_id": node_id,
                "remote_email": remote_email, "remote_client_id": remote_client_id,
                "remote_sub_id": remote_sub_id,
                "details_json": json.dumps(item.get("details") if isinstance(item.get("details"), dict) else {},
                                           ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            })
        with connect(self._db_path) as conn:
            placeholders = ",".join("?" for _ in node_ids)
            current_keys = {item["finding_key"] for item in normalized}
            if current_keys:
                key_placeholders = ",".join("?" for _ in current_keys)
                conn.execute(
                    f"""
                    UPDATE telegram_drift_findings SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP,
                        row_version = row_version + 1
                    WHERE status IN ('open', 'ignored') AND node_id IN ({placeholders}) AND finding_key NOT IN ({key_placeholders})
                    """,
                    (*node_ids, *current_keys),
                )
            else:
                conn.execute(
                    f"""
                    UPDATE telegram_drift_findings SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP,
                        row_version = row_version + 1
                    WHERE status IN ('open', 'ignored') AND node_id IN ({placeholders})
                    """,
                    node_ids,
                )
            unique_findings = {item["finding_key"]: item for item in normalized}
            for item in unique_findings.values():
                existing = conn.execute(
                    "SELECT status, details_json FROM telegram_drift_findings WHERE finding_key = ?",
                    (item["finding_key"],),
                ).fetchone()
                details = json.loads(item["details_json"])
                previous_seen = 0
                if existing and existing[0] in ("open", "ignored"):
                    previous_seen = int(json.loads(existing[1]).get("seen_scans", 0))
                details["seen_scans"] = previous_seen + 1
                item["details_json"] = json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                conn.execute(
                    """
                    INSERT INTO telegram_drift_findings
                        (finding_key, kind, customer_id, node_id, remote_email, remote_client_id,
                         remote_sub_id, details_json)
                    VALUES (:finding_key, :kind, :customer_id, :node_id, :remote_email, :remote_client_id,
                            :remote_sub_id, :details_json)
                    ON CONFLICT(finding_key) DO UPDATE SET
                        details_json = excluded.details_json, last_seen_at = CURRENT_TIMESTAMP,
                        status = CASE WHEN telegram_drift_findings.status IN ('resolved', 'adopted') THEN 'open'
                                      ELSE telegram_drift_findings.status END,
                        resolved_at = CASE WHEN telegram_drift_findings.status IN ('resolved', 'adopted') THEN NULL
                                           ELSE telegram_drift_findings.resolved_at END,
                        row_version = telegram_drift_findings.row_version + 1
                    """,
                    item,
                )
            # A completed remote scan is authoritative for just the scanned
            # nodes. Restore bindings that are exact again, then mark only the
            # current mismatches. Nodes that could not be read are not passed
            # here, so a transport failure never makes a client look absent.
            conn.execute(
                f"""
                INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id)
                SELECT 'drift_binding_missing', 'system', 'drift_scan', 'customer_node_binding', CAST(b.id AS TEXT)
                FROM customer_node_bindings AS b
                JOIN telegram_drift_findings AS f ON f.customer_id = b.customer_id AND f.node_id = b.node_id
                    AND f.remote_client_id = COALESCE(b.remote_client_id, '')
                    AND f.remote_sub_id = COALESCE(b.remote_sub_id, '')
                    AND lower(f.remote_email) = lower(b.remote_email)
                WHERE b.node_id IN ({placeholders}) AND b.inbound_id = 1 AND b.desired_enabled = 0
                    AND b.management_state != 'missing' AND f.kind = 'binding_missing'
                    AND f.status IN ('open', 'ignored')
                """, node_ids,
            )
            conn.execute(
                f"""
                UPDATE customer_node_bindings
                SET management_state = 'confirmed', row_version = row_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE node_id IN ({placeholders})
                  AND management_state IN ('missing', 'conflict')
                  AND NOT EXISTS (
                    SELECT 1 FROM telegram_drift_findings AS f
                    WHERE f.status IN ('open', 'ignored') AND f.kind IN ('binding_missing', 'binding_conflict')
                      AND f.customer_id = customer_node_bindings.customer_id
                      AND f.node_id = customer_node_bindings.node_id AND customer_node_bindings.inbound_id = 1
                      AND f.remote_client_id = COALESCE(customer_node_bindings.remote_client_id, '')
                      AND f.remote_sub_id = COALESCE(customer_node_bindings.remote_sub_id, '')
                      AND lower(f.remote_email) = lower(customer_node_bindings.remote_email)
                  )
                """,
                node_ids,
            )
            conn.execute(
                f"""
                UPDATE customer_node_bindings
                SET management_state = CASE finding.kind
                        WHEN 'binding_missing' THEN 'missing'
                        ELSE 'conflict'
                    END,
                    row_version = customer_node_bindings.row_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                FROM telegram_drift_findings AS finding
                WHERE finding.status IN ('open', 'ignored')
                  AND finding.kind IN ('binding_missing', 'binding_conflict')
                  AND finding.node_id IN ({placeholders})
                  AND customer_node_bindings.customer_id = finding.customer_id
                  AND customer_node_bindings.node_id = finding.node_id
                  AND customer_node_bindings.inbound_id = 1
                  AND COALESCE(customer_node_bindings.remote_client_id, '') = finding.remote_client_id
                  AND COALESCE(customer_node_bindings.remote_sub_id, '') = finding.remote_sub_id
                  AND lower(customer_node_bindings.remote_email) = lower(finding.remote_email)
                  AND customer_node_bindings.management_state != CASE finding.kind
                      WHEN 'binding_missing' THEN 'missing' ELSE 'conflict' END
                """,
                node_ids,
            )
        return list_drift_findings(status="open", limit=200)


def auto_forget_drift_binding(self, finding_id: int, version: int, *, forget_missing_binding) -> None:
        with connect(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT b.id FROM telegram_drift_findings f JOIN customer_node_bindings b "
                "ON b.customer_id = f.customer_id AND b.node_id = f.node_id AND b.inbound_id = 1 "
                "AND COALESCE(b.remote_client_id, '') = f.remote_client_id "
                "AND COALESCE(b.remote_sub_id, '') = f.remote_sub_id "
                "AND lower(b.remote_email) = lower(f.remote_email) "
                "WHERE f.id = ? AND f.row_version = ? AND f.status = 'open' AND f.kind = 'binding_missing' "
                "AND COALESCE(json_extract(f.details_json, '$.seen_scans'), 0) >= 2",
                (finding_id, version),
            ).fetchone()
            if row:
                forget_missing_binding(conn, int(row[0]), actor_type="system", actor_id="drift_scan")


def list_drift_findings(self, *, status: str = "open", limit: int = 100, offset: int = 0, error_type, finding_type) -> tuple[Any, ...]:
        if status not in {"open", "adopted", "ignored", "resolved", "all"}:
            raise error_type("drift status is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise error_type("limit must be an integer from 1 to 200")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise error_type("offset must be a non-negative integer")
        clause = "" if status == "all" else "WHERE finding.status = ?"
        parameters = (limit, offset) if status == "all" else (status, limit, offset)
        with connect(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT finding.id, finding.kind, finding.customer_id, customer.email_display, finding.node_id,
                       node.name, finding.remote_email, finding.remote_client_id, finding.remote_sub_id,
                       finding.status, finding.row_version, finding.last_seen_at
                FROM telegram_drift_findings AS finding
                JOIN nodes AS node ON node.id = finding.node_id
                LEFT JOIN customers AS customer ON customer.id = finding.customer_id
                {clause}
                ORDER BY CASE finding.status WHEN 'open' THEN 0 ELSE 1 END, finding.last_seen_at DESC, finding.id DESC
                LIMIT ? OFFSET ?
                """,
                parameters,
            ).fetchall()
        return tuple(finding_type(
            finding_id=int(row[0]), kind=str(row[1]), customer_id=int(row[2]) if row[2] is not None else None,
            customer_email=str(row[3]) if row[3] is not None else None, node_id=int(row[4]), node_name=str(row[5]),
            remote_email=str(row[6]), remote_client_id=str(row[7]), remote_sub_id=str(row[8]),
            status=str(row[9]), row_version=int(row[10]), last_seen_at=str(row[11]),
        ) for row in rows)


def resolve_drift_finding(
        self, *, finding_id: int, expected_row_version: int, status: str, resolved_by: str,
        positive_int, nonempty, error_type, version_conflict_error, list_drift_findings
    ) -> Any:
        if status not in {"ignored", "resolved"}:
            raise error_type("drift resolution is invalid")
        local_finding_id = positive_int(finding_id, "finding_id")
        expected_version = positive_int(expected_row_version, "expected_row_version")
        actor = nonempty(resolved_by, "resolved_by")
        with connect(self._db_path) as conn:
            updated = conn.execute(
                """
                UPDATE telegram_drift_findings
                SET status = ?, resolved_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                WHERE id = ? AND status = 'open' AND row_version = ?
                """,
                (status, local_finding_id, expected_version),
            )
            if updated.rowcount != 1:
                raise version_conflict_error("drift finding is stale")
            event_type = "drift_finding_ignored" if status == "ignored" else "drift_finding_resolved"
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id)
                VALUES (?, 'admin', ?, 'drift_finding', ?)
                """,
                (event_type, actor, str(local_finding_id)),
            )
        return next(item for item in list_drift_findings(status="all", limit=200) if item.finding_id == local_finding_id)


def _insert_adopted_binding(conn, *, customer_id, node_id, remote_client_id, remote_sub_id, remote_email, remote_enabled):
        conn.execute(
            """INSERT INTO customer_node_bindings
                (customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email,
                 source, management_state, desired_enabled, last_enabled, last_confirmed_at)
                VALUES (?, ?, 1, ?, ?, ?, 'admin_confirmed', 'confirmed', ?, ?, CURRENT_TIMESTAMP)""",
            (customer_id, node_id, remote_client_id, remote_sub_id, remote_email,
             int(remote_enabled), int(remote_enabled)),
        )
        conn.execute(
            "UPDATE customers SET row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (customer_id,),
        )


def adopt_drift_binding(
        self,
        *,
        finding_id: int,
        expected_row_version: int,
        remote_email: str,
        remote_client_id: str,
        remote_sub_id: str,
        remote_enabled: bool,
        adopted_by: str,
        automatic: bool = False,
        positive_int, nonempty, canonicalize_email, version_conflict_error,
        insert_adopted_binding, list_drift_findings,
    ) -> Any:
        """Adopt a re-read exact orphan as a local binding; never writes a node."""

        local_finding_id = positive_int(finding_id, "finding_id")
        expected_version = positive_int(expected_row_version, "expected_row_version")
        actor = nonempty(adopted_by, "adopted_by")
        canonical = canonicalize_email(remote_email)
        with connect(self._db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            finding = conn.execute(
                """
                SELECT customer_id, node_id, remote_email, remote_client_id, remote_sub_id
                FROM telegram_drift_findings
                WHERE id = ? AND kind = 'orphan_remote' AND status = 'open' AND row_version = ?
                  AND (? = 0 OR COALESCE(json_extract(details_json, '$.seen_scans'), 0) >= 2)
                """,
                (local_finding_id, expected_version, int(automatic)),
            ).fetchone()
            if finding is None or finding[0] is None:
                raise version_conflict_error("drift finding is not adoptable")
            if (
                canonicalize_email(str(finding[2])) != canonical
                or str(finding[3]) != str(remote_client_id)
                or str(finding[4]) != str(remote_sub_id)
            ):
                raise version_conflict_error("remote record changed; scan it again")
            exists = conn.execute(
                "SELECT 1 FROM customer_node_bindings WHERE customer_id = ? AND node_id = ? AND inbound_id = 1",
                (int(finding[0]), int(finding[1])),
            ).fetchone()
            if exists is not None:
                raise version_conflict_error("customer already has an inbound 1 binding on this node")
            if automatic and conn.execute(
                "SELECT 1 FROM telegram_customer_operations WHERE customer_id = ? "
                "AND status IN ('queued', 'running', 'partial') AND dismissed_at IS NULL LIMIT 1",
                (int(finding[0]),),
            ).fetchone():
                # A new binding would fall outside that operation's immutable target snapshot: retry next scan.
                raise version_conflict_error("customer has a lifecycle operation in progress")
            insert_adopted_binding(
                conn, customer_id=int(finding[0]), node_id=int(finding[1]), remote_client_id=str(remote_client_id),
                remote_sub_id=str(remote_sub_id), remote_email=remote_email, remote_enabled=remote_enabled,
            )
            updated = conn.execute(
                """
                UPDATE telegram_drift_findings
                SET status = 'adopted', resolved_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                WHERE id = ? AND row_version = ?
                """,
                (local_finding_id, expected_version),
            )
            if updated.rowcount != 1:
                raise version_conflict_error("drift finding changed while adopting")
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id)
                VALUES (?, ?, ?, 'drift_finding', ?)
                """,
                ("drift_binding_auto_adopted" if automatic else "drift_binding_adopted",
                 "system" if automatic else "admin", actor, str(local_finding_id)),
            )
        if automatic:
            return None
        return next(item for item in list_drift_findings(status="all", limit=200) if item.finding_id == local_finding_id)
