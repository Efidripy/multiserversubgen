"""Traffic and notification operations for the Telegram registry."""

from __future__ import annotations

import json
from typing import Any

from services.db_bootstrap import connect


def eligible_provisioning_node_count(self) -> int:
    """Return the local policy snapshot count shown before final approval."""

    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM telegram_node_policies AS p
            JOIN nodes AS n ON n.id = p.node_id
            WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
            """
        ).fetchone()
    return int(row[0]) if row else 0

def get_notification_preferences(
    self,
    telegram_user_id: int,
    *,
    positive_int,
    error_type,
    preference_type,
    normalize_traffic_thresholds,
):
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if identity is None:
            raise error_type("Telegram identity was not found")
        conn.execute(
            "INSERT OR IGNORE INTO telegram_notification_preferences (telegram_user_id) VALUES (?)",
            (user_id,),
        )
        row = conn.execute(
            """
            SELECT background_notifications_enabled, expiry_reminders_enabled,
                   traffic_reminders_enabled, traffic_reminder_thresholds, row_version
            FROM telegram_notification_preferences WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
    assert row is not None
    return preference_type(
        user_id,
        bool(row[0]),
        bool(row[1]),
        bool(row[2]),
        normalize_traffic_thresholds(row[3]),
        int(row[4]),
    )

def toggle_background_notifications(self, telegram_user_id: int, *, positive_int, error_type):
    """Toggle user-controlled background delivery after durable update dedupe."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if identity is None:
            raise error_type("Telegram identity was not found")
        conn.execute(
            "INSERT OR IGNORE INTO telegram_notification_preferences (telegram_user_id) VALUES (?)",
            (user_id,),
        )
        conn.execute(
            """
            UPDATE telegram_notification_preferences
            SET background_notifications_enabled = CASE background_notifications_enabled WHEN 1 THEN 0 ELSE 1 END,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_user_id = ?
            """,
            (user_id,),
        )
    return self.get_notification_preferences(user_id)

def toggle_expiry_reminders(self, telegram_user_id: int, *, positive_int, error_type):
    """Toggle only pre-expiry reminders; command replies remain unaffected."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if identity is None:
            raise error_type("Telegram identity was not found")
        conn.execute(
            "INSERT OR IGNORE INTO telegram_notification_preferences (telegram_user_id) VALUES (?)",
            (user_id,),
        )
        conn.execute(
            """
            UPDATE telegram_notification_preferences
            SET expiry_reminders_enabled = CASE expiry_reminders_enabled WHEN 1 THEN 0 ELSE 1 END,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_user_id = ?
            """,
            (user_id,),
        )
    return self.get_notification_preferences(user_id)

def toggle_traffic_reminders(self, telegram_user_id: int, *, positive_int, error_type):
    """Toggle opt-in finite-quota notices; command replies remain unaffected."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if identity is None:
            raise error_type("Telegram identity was not found")
        conn.execute(
            "INSERT OR IGNORE INTO telegram_notification_preferences (telegram_user_id) VALUES (?)",
            (user_id,),
        )
        conn.execute(
            """
            UPDATE telegram_notification_preferences
            SET traffic_reminders_enabled = CASE traffic_reminders_enabled WHEN 1 THEN 0 ELSE 1 END,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_user_id = ?
            """,
            (user_id,),
        )
    return self.get_notification_preferences(user_id)

def toggle_traffic_reminder_threshold(
    self, telegram_user_id: int, threshold_percent: int, *,
    positive_int, error_type, traffic_reminder_thresholds, normalize_traffic_thresholds,
):
    """Toggle one user-selected finite-traffic reminder threshold."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    if isinstance(threshold_percent, bool) or threshold_percent not in traffic_reminder_thresholds:
        raise error_type("traffic reminder threshold is invalid")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if identity is None:
            raise error_type("Telegram identity was not found")
        conn.execute(
            "INSERT OR IGNORE INTO telegram_notification_preferences (telegram_user_id) VALUES (?)",
            (user_id,),
        )
        current = conn.execute(
            "SELECT traffic_reminder_thresholds FROM telegram_notification_preferences WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
        thresholds = set(normalize_traffic_thresholds(current[0] if current else None))
        if threshold_percent in thresholds:
            thresholds.remove(threshold_percent)
        else:
            thresholds.add(threshold_percent)
        # A traffic category with no selected bands is equivalent to off,
        # but retain the empty selection so the user's next enable is explicit.
        conn.execute(
            """
            UPDATE telegram_notification_preferences
            SET traffic_reminder_thresholds = ?,
                traffic_reminders_enabled = ?,
                row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE telegram_user_id = ?
            """,
            (json.dumps(sorted(thresholds), separators=(",", ":")), int(bool(thresholds)), user_id),
        )
    return self.get_notification_preferences(user_id)

def list_traffic_reminder_candidates(
    self, *, initial_job_complete_sql, normalize_traffic_thresholds, payload_digest,
    quota_binding_type, quota_candidate_type,
):
    """Return only complete, finite TG traffic plans without node I/O.

    A customer is eligible only when every currently enabled confirmed
    binding has an exact successful immutable provisioning attempt. The
    finite quota is intentionally the sum of those per-node limits because
    each node enforces its own client counter.
    """

    with connect(self._db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT i.telegram_user_id, c.id, c.email_display,
                   b.node_id, b.inbound_id, b.remote_client_id,
                   a.desired_total_bytes,
                   COALESCE(p.traffic_reminder_thresholds, '[80,95,100]')
            FROM telegram_identities AS i
            JOIN customers AS c ON c.id = i.customer_id
            JOIN customer_node_bindings AS b ON b.customer_id = c.id
            JOIN nodes AS n ON n.id = b.node_id
            LEFT JOIN telegram_notification_preferences AS p
              ON p.telegram_user_id = i.telegram_user_id
            LEFT JOIN telegram_provisioning_attempts AS a ON a.id = (
                SELECT candidate.id
                FROM telegram_provisioning_attempts AS candidate
                JOIN telegram_provisioning_jobs AS j ON j.id = candidate.job_id
                WHERE j.customer_id = c.id
                  AND candidate.node_id = b.node_id
                  AND candidate.inbound_id = b.inbound_id
                  AND candidate.remote_client_id = b.remote_client_id
                  AND candidate.status = 'succeeded'
                ORDER BY candidate.id DESC
                LIMIT 1
            )
            WHERE i.access_status = 'approved'
              AND c.status = 'active' AND c.deleted_at IS NULL
              AND b.management_state = 'confirmed' AND b.desired_enabled = 1
              AND n.enabled = 1
              AND COALESCE(p.background_notifications_enabled, 1) = 1
              AND COALESCE(p.traffic_reminders_enabled, 0) = 1
              AND (
                c.origin != 'telegram'
                OR NOT EXISTS (
                    SELECT 1 FROM telegram_provisioning_jobs AS j
                    WHERE j.customer_id = c.id
                      AND j.trigger = 'approve_new'
                      AND NOT {initial_job_complete_sql}
                )
              )
            ORDER BY i.telegram_user_id, b.node_id, b.inbound_id
            """
        ).fetchall()

    grouped: dict[tuple[int, int, str, tuple[int, ...]], list[tuple[int, int, str, int | None]]] = {}
    for row in rows:
        key = (int(row[0]), int(row[1]), str(row[2]), normalize_traffic_thresholds(row[7]))
        grouped.setdefault(key, []).append((int(row[3]), int(row[4]), str(row[5]), row[6]))

    candidates: list[Any] = []
    for (telegram_user_id, customer_id, email_display, thresholds), bindings in grouped.items():
        if not bindings or any(item[3] is None or int(item[3]) <= 0 for item in bindings):
            continue
        quota_bindings = tuple(
            quota_binding_type(node_id=node_id, inbound_id=inbound_id, remote_client_id=remote_client_id)
            for node_id, inbound_id, remote_client_id, _quota in bindings
        )
        quota_plan = {
            "customer_id": customer_id,
            "bindings": [
                {
                    "node_id": binding.node_id,
                    "inbound_id": binding.inbound_id,
                    "remote_client_id": binding.remote_client_id,
                    "total_bytes": int(quota),
                }
                for binding, (_node_id, _inbound_id, _remote_client_id, quota) in zip(quota_bindings, bindings)
            ],
        }
        candidates.append(
            quota_candidate_type(
                telegram_user_id=telegram_user_id,
                customer_id=customer_id,
                email_display=email_display,
                quota_total_bytes=sum(int(item[3]) for item in bindings),
                quota_plan_digest=payload_digest(quota_plan),
                bindings=quota_bindings,
                traffic_reminder_thresholds=thresholds,
            )
        )
    return tuple(candidates)

def list_customer_traffic_observation_bindings(
    self, *, canonicalize_email, binding_type, error_type,
):
    """Return local exact bindings eligible to consume a collector snapshot."""

    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.id, b.node_id, b.inbound_id, b.remote_email
            FROM customers AS c
            JOIN customer_node_bindings AS b ON b.customer_id = c.id
            JOIN nodes AS n ON n.id = b.node_id
            WHERE c.status = 'active' AND c.deleted_at IS NULL
              AND b.management_state = 'confirmed' AND b.desired_enabled = 1
              AND n.enabled = 1
              AND EXISTS (
                  SELECT 1 FROM telegram_identities AS i
                  WHERE i.customer_id = c.id AND i.access_status = 'approved'
              )
            ORDER BY c.id, b.node_id, b.inbound_id
            """
        ).fetchall()
    grouped: dict[int, list[Any]] = {}
    unsafe_customers: set[int] = set()
    seen: set[tuple[int, int, int]] = set()
    for customer_id, node_id, inbound_id, remote_email in rows:
        identity = (int(customer_id), int(node_id), int(inbound_id))
        if identity in seen:
            unsafe_customers.add(identity[0])
            continue
        seen.add(identity)
        try:
            email = canonicalize_email(str(remote_email))
        except error_type:
            unsafe_customers.add(identity[0])
            continue
        grouped.setdefault(identity[0], []).append(
            binding_type(*identity, remote_email=email)
        )
    return {
        customer_id: tuple(bindings)
        for customer_id, bindings in grouped.items()
        if customer_id not in unsafe_customers and bindings
    }

def observe_customer_traffic_bindings(
    self, observations: dict[int, dict[tuple[int, int], int]], *,
    positive_int, error_type, ledger_type,
) -> tuple:
    """Persist one complete collector observation batch by exact binding."""

    normalized: dict[int, dict[tuple[int, int], int]] = {}
    for raw_customer_id, raw_bindings in observations.items():
        customer_id = positive_int(raw_customer_id, "customer_id")
        if not isinstance(raw_bindings, dict) or not raw_bindings:
            raise error_type("observations must contain at least one binding")
        customer_bindings: dict[tuple[int, int], int] = {}
        for raw_binding, observed_bytes in raw_bindings.items():
            if (
                not isinstance(raw_binding, tuple)
                or len(raw_binding) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) for value in raw_binding)
            ):
                raise error_type("binding must be a (node_id, inbound_id) tuple")
            node_id = positive_int(raw_binding[0], "node_id")
            inbound_id = positive_int(raw_binding[1], "inbound_id")
            if (
                isinstance(observed_bytes, bool)
                or not isinstance(observed_bytes, int)
                or observed_bytes < 0
            ):
                raise error_type("observed_bytes must be a non-negative integer")
            customer_bindings[(node_id, inbound_id)] = observed_bytes
        normalized[customer_id] = customer_bindings

    with connect(self._db_path) as conn:
        result: list[Any] = []
        for customer_id, customer_bindings in sorted(normalized.items()):
            if conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is None:
                raise error_type("customer was not found")

            observed_bytes = sum(customer_bindings.values())
            binding_rows = conn.execute(
                """
                SELECT node_id, inbound_id, last_observed_bytes
                FROM customer_traffic_binding_ledger
                WHERE customer_id = ?
                """,
                (customer_id,),
            ).fetchall()
            has_binding_ledger = bool(binding_rows)
            lifetime_delta = 0

            if not has_binding_ledger:
                ledger_row = conn.execute(
                    "SELECT lifetime_bytes FROM customer_traffic_ledger WHERE customer_id = ?",
                    (customer_id,),
                ).fetchone()
                if ledger_row is None:
                    conn.execute(
                        """
                        INSERT INTO customer_traffic_ledger
                            (customer_id, lifetime_bytes, last_observed_bytes)
                        VALUES (?, ?, ?)
                        """,
                        (customer_id, observed_bytes, observed_bytes),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE customer_traffic_ledger
                        SET lifetime_bytes = ?, last_observed_bytes = ?,
                            last_observed_at = CURRENT_TIMESTAMP,
                            row_version = row_version + 1
                        WHERE customer_id = ?
                        """,
                        (observed_bytes, observed_bytes, customer_id),
                    )
                for (node_id, inbound_id), value in customer_bindings.items():
                    conn.execute(
                        """
                        INSERT INTO customer_traffic_binding_ledger
                            (customer_id, node_id, inbound_id, last_observed_bytes)
                        VALUES (?, ?, ?, ?)
                        """,
                        (customer_id, node_id, inbound_id, value),
                    )
            else:
                previous_by_binding = {
                    (int(row[0]), int(row[1])): int(row[2]) for row in binding_rows
                }
                for (node_id, inbound_id), value in customer_bindings.items():
                    previous = previous_by_binding.get((node_id, inbound_id))
                    if previous is None:
                        lifetime_delta += value
                        conn.execute(
                            """
                            INSERT INTO customer_traffic_binding_ledger
                                (customer_id, node_id, inbound_id, last_observed_bytes)
                            VALUES (?, ?, ?, ?)
                            """,
                            (customer_id, node_id, inbound_id, value),
                        )
                    else:
                        lifetime_delta += value - previous if value >= previous else value
                        conn.execute(
                            """
                            UPDATE customer_traffic_binding_ledger
                            SET last_observed_bytes = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE customer_id = ? AND node_id = ? AND inbound_id = ?
                            """,
                            (value, customer_id, node_id, inbound_id),
                        )

                ledger_row = conn.execute(
                    "SELECT lifetime_bytes FROM customer_traffic_ledger WHERE customer_id = ?",
                    (customer_id,),
                ).fetchone()
                if ledger_row is None:
                    conn.execute(
                        """
                        INSERT INTO customer_traffic_ledger
                            (customer_id, lifetime_bytes, last_observed_bytes)
                        VALUES (?, ?, ?)
                        """,
                        (customer_id, lifetime_delta, observed_bytes),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE customer_traffic_ledger
                        SET lifetime_bytes = lifetime_bytes + ?, last_observed_bytes = ?,
                            last_observed_at = CURRENT_TIMESTAMP,
                            row_version = row_version + 1
                        WHERE customer_id = ?
                        """,
                        (lifetime_delta, observed_bytes, customer_id),
                    )

            stored = conn.execute(
                """
                SELECT customer_id, lifetime_bytes, last_observed_bytes, last_observed_at
                FROM customer_traffic_ledger WHERE customer_id = ?
                """,
                (customer_id,),
            ).fetchone()
            assert stored is not None
            result.append(
                ledger_type(
                    int(stored[0]), int(stored[1]), int(stored[2]), str(stored[3])
                )
            )
        return tuple(result)

def get_customer_traffic(
    self, customer_id: int, *, positive_int, ledger_type,
) -> object:
    local_customer_id = positive_int(customer_id, "customer_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT customer_id, lifetime_bytes, last_observed_bytes, last_observed_at
            FROM customer_traffic_ledger WHERE customer_id = ?
            """,
            (local_customer_id,),
        ).fetchone()
    if row is None:
        return ledger_type(local_customer_id, 0, 0, "")
    return ledger_type(
        customer_id=int(row[0]), lifetime_bytes=int(row[1]),
        last_observed_bytes=int(row[2]), last_observed_at=str(row[3]),
    )

