"""Identity, access, and preapproval operations for the Telegram registry."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

TelegramTransportPreference = Any
TelegramIdentity = Any
TelegramPreapproval = Any
ApprovalResult = Any
ExistingApprovalResult = Any
TelegramUnlinkResult = Any
TelegramCustomerAccess = Any


def get_transport_preference(self, **deps) -> TelegramTransportPreference:
    TelegramRegistryError = deps["TelegramRegistryError"]
    TelegramTransportPreference = deps["TelegramTransportPreference"]
    connect = deps["connect"]
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT mode, proxy_host, proxy_port, row_version, updated_by, updated_at
            FROM telegram_transport_preferences
            WHERE singleton_id = 1
            """
        ).fetchone()
    if row is None:
        raise TelegramRegistryError("Telegram transport preference is unavailable")
    return TelegramTransportPreference(
        mode=str(row[0]),
        proxy_host=str(row[1]) if row[1] is not None else None,
        proxy_port=int(row[2]) if row[2] is not None else None,
        row_version=int(row[3]),
        updated_by=str(row[4]),
        updated_at=str(row[5]),
    )


def set_transport_preference(
    self,
    *,
    mode: str,
    expected_row_version: int,
    updated_by: str,
    proxy_host: str | None = None,
    proxy_port: int | None = None,
 **deps) -> TelegramTransportPreference:
    TelegramRegistryError = deps["TelegramRegistryError"]
    VersionConflictError = deps["VersionConflictError"]
    connect = deps["connect"]
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"direct", "local_proxy"}:
        raise TelegramRegistryError("Telegram transport mode is invalid")
    if not isinstance(expected_row_version, int) or expected_row_version < 1:
        raise TelegramRegistryError("expected_row_version must be a positive integer")
    actor = str(updated_by or "").strip()
    if not actor:
        raise TelegramRegistryError("updated_by is required")
    normalized_host = str(proxy_host or "").strip() or None
    try:
        normalized_port = int(proxy_port) if proxy_port is not None else None
    except (TypeError, ValueError) as exc:
        raise TelegramRegistryError("Telegram proxy port is invalid") from exc
    if normalized_port is not None and not 1 <= normalized_port <= 65535:
        raise TelegramRegistryError("Telegram proxy port is invalid")
    if normalized_mode == "local_proxy" and (normalized_host is None or normalized_port is None):
        raise TelegramRegistryError("Telegram proxy host and port are required")
    with connect(self._db_path) as conn:
        update = conn.execute(
            """
            UPDATE telegram_transport_preferences
            SET mode = ?,
                proxy_host = CASE WHEN ? = 'local_proxy' THEN ? ELSE proxy_host END,
                proxy_port = CASE WHEN ? = 'local_proxy' THEN ? ELSE proxy_port END,
                row_version = row_version + 1,
                updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE singleton_id = 1 AND row_version = ?
            """,
            (
                normalized_mode,
                normalized_mode,
                normalized_host,
                normalized_mode,
                normalized_port,
                actor[:120],
                expected_row_version,
            ),
        )
        if update.rowcount != 1:
            raise VersionConflictError("Telegram transport preference was changed by another administrator")
    return get_transport_preference(self, **deps)


def get_or_create_identity(
    self,
    *,
    telegram_user_id: int,
    chat_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    phone_number: str | None = None,
    locale: str | None = None,
 **deps) -> TelegramIdentity:
    TelegramIdentity = deps["TelegramIdentity"]
    _normalize_phone_number = deps["_normalize_phone_number"]
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    normalized_locale = locale if locale in {"ru", "en"} else None
    normalized_phone = _normalize_phone_number(phone_number)
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT telegram_user_id, chat_id, access_status, application_attempt,
                   customer_id, row_version
            FROM telegram_identities
            WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO telegram_identities
                    (telegram_user_id, chat_id, username, first_name, last_name, phone_number, locale)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, chat_id, username, first_name, last_name, normalized_phone, normalized_locale or "ru"),
            )
            row = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt,
                       customer_id, row_version
                FROM telegram_identities
                WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
        else:
            conn.execute(
                """
                UPDATE telegram_identities
                SET chat_id = ?, username = ?, first_name = ?, last_name = ?,
                    phone_number = COALESCE(?, phone_number),
                    updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                WHERE telegram_user_id = ?
                """,
                (chat_id, username, first_name, last_name, normalized_phone, user_id),
            )
            row = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt,
                       customer_id, row_version
                FROM telegram_identities
                WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
    assert row is not None
    return TelegramIdentity(
        telegram_user_id=int(row[0]),
        chat_id=int(row[1]),
        access_status=str(row[2]),
        application_attempt=int(row[3]),
        customer_id=int(row[4]) if row[4] is not None else None,
        row_version=int(row[5]),
    )


def get_locale(self, telegram_user_id: int, **deps) -> str:
    TelegramRegistryError = deps["TelegramRegistryError"]
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute("SELECT locale FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)).fetchone()
    if row is None:
        raise TelegramRegistryError("telegram identity is unavailable")
    return "en" if row[0] == "en" else "ru"


def set_locale(self, telegram_user_id: int, locale: object, **deps) -> str:
    TelegramRegistryError = deps["TelegramRegistryError"]
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    normalized = "en" if locale == "en" else "ru"
    with connect(self._db_path) as conn:
        updated = conn.execute(
            "UPDATE telegram_identities SET locale = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP WHERE telegram_user_id = ?",
            (normalized, user_id),
        )
        if updated.rowcount != 1:
            raise TelegramRegistryError("telegram identity is unavailable")
    return normalized


def get_preapproval(self, telegram_user_id: int, **deps) -> TelegramPreapproval | None:
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT p.telegram_user_id, p.profile_kind, p.customer_id,
                   COALESCE(c.email_display, p.email_display), p.email_source,
                   p.target_snapshot_json, p.target_snapshot_digest,
                   p.row_version, p.created_by, p.created_at
            FROM telegram_preapprovals AS p
            LEFT JOIN customers AS c ON c.id = p.customer_id
            WHERE p.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return _preapproval_from_row(row, **deps)


def _preapproval_from_row(row: tuple[object, ...], **deps) -> TelegramPreapproval:
    TelegramPreapproval = deps["TelegramPreapproval"]
    TelegramRegistryError = deps["TelegramRegistryError"]
    raw_snapshot = row[5]
    try:
        targets = json.loads(str(raw_snapshot)) if raw_snapshot is not None else []
    except json.JSONDecodeError as exc:
        raise TelegramRegistryError("preapproval snapshot is invalid") from exc
    if not isinstance(targets, list):
        raise TelegramRegistryError("preapproval snapshot is invalid")
    target_node_ids = tuple(
        int(item["node_id"])
        for item in targets
        if isinstance(item, dict) and isinstance(item.get("node_id"), int)
    )
    return TelegramPreapproval(
        telegram_user_id=int(row[0]), profile_kind=str(row[1]),
        customer_id=int(row[2]) if row[2] is not None else None,
        customer_email=str(row[3]), email_source=str(row[4]) if row[4] is not None else None,
        target_node_ids=target_node_ids,
        target_snapshot_digest=str(row[6]) if row[6] is not None else None,
        row_version=int(row[7]), created_by=str(row[8]), created_at=str(row[9]),
    )


def _preapproval_from_receipt(payload: object, **deps) -> TelegramPreapproval:
    """Read both current and pre-profile idempotency receipts safely."""
    TelegramPreapproval = deps["TelegramPreapproval"]
    TelegramRegistryError = deps["TelegramRegistryError"]

    if not isinstance(payload, dict):
        raise TelegramRegistryError("preapproval receipt is invalid")
    if "profile_kind" not in payload:
        # Receipts written by the existing-customer-only release retain
        # their original result shape. The bound customer proves the
        # missing profile kind without inventing a new-customer snapshot.
        payload = {**payload, "profile_kind": "existing", "email_source": None,
                   "target_node_ids": (), "target_snapshot_digest": None}
    normalized = dict(payload)
    normalized["target_node_ids"] = tuple(normalized.get("target_node_ids") or ())
    try:
        return TelegramPreapproval(**normalized)
    except (TypeError, ValueError) as exc:
        raise TelegramRegistryError("preapproval receipt is invalid") from exc


def create_existing_customer_preapproval(
    self,
    *,
    telegram_user_id: int,
    customer_id: int,
    expected_preapproval_version: int,
    idempotency_key: str,
    created_by: str,
 **deps) -> TelegramPreapproval:
    """Pre-authorize one numeric Telegram ID for one verified existing customer.

    The command is local-only. It cannot create remote clients, reveal a
    subscription URL, or overwrite a blocked/linked Telegram identity.
    Activation waits for the exact ID's first private ``/start``.
    """
    ApprovalUnavailableError = deps["ApprovalUnavailableError"]
    IdempotencyConflictError = deps["IdempotencyConflictError"]
    TelegramRegistryError = deps["TelegramRegistryError"]
    VersionConflictError = deps["VersionConflictError"]
    _nonempty = deps["_nonempty"]
    _payload_digest = deps["_payload_digest"]
    _positive_int = deps["_positive_int"]
    canonicalize_email = deps["canonicalize_email"]
    connect = deps["connect"]

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    local_customer_id = _positive_int(customer_id, "customer_id")
    if (
        isinstance(expected_preapproval_version, bool)
        or not isinstance(expected_preapproval_version, int)
        or expected_preapproval_version < 0
    ):
        raise TelegramRegistryError("expected_preapproval_version is invalid")
    expected_version = expected_preapproval_version
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(created_by, "created_by")
    payload = {
        "telegram_user_id": user_id,
        "customer_id": local_customer_id,
        "expected_preapproval_version": expected_version,
    }
    digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'create_preapproval' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return _preapproval_from_receipt(json.loads(str(receipt[1])), **deps)

        customer = conn.execute(
            """
            SELECT email_display, email_canonical, status
            FROM customers WHERE id = ? AND deleted_at IS NULL
            """,
            (local_customer_id,),
        ).fetchone()
        if customer is None or str(customer[2]) not in {"active", "suspended", "suspend_partial", "resume_partial"}:
            raise ApprovalUnavailableError("customer is not available for Telegram preapproval")
        bindings = conn.execute(
            """
            SELECT remote_email FROM customer_node_bindings
            WHERE customer_id = ? AND management_state = 'confirmed'
            """,
            (local_customer_id,),
        ).fetchall()
        if not bindings or any(canonicalize_email(str(item[0])) != str(customer[1]) for item in bindings):
            raise ApprovalUnavailableError("customer has no confirmed exact node binding")
        linked = conn.execute(
            "SELECT telegram_user_id FROM telegram_identities WHERE customer_id = ?",
            (local_customer_id,),
        ).fetchone()
        if linked is not None and int(linked[0]) != user_id:
            raise ApprovalUnavailableError("customer is already linked to another Telegram identity")
        identity = conn.execute(
            "SELECT access_status, customer_id FROM telegram_identities WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
        if identity is not None:
            if str(identity[0]) == "blocked":
                raise ApprovalUnavailableError("blocked identity cannot receive a preapproval")
            if identity[1] is not None and int(identity[1]) != local_customer_id:
                raise ApprovalUnavailableError("Telegram identity is already linked to another customer")
            if str(identity[0]) == "approved" and identity[1] is not None and int(identity[1]) == local_customer_id:
                raise ApprovalUnavailableError("Telegram identity is already approved for this customer")
            if str(identity[0]) == "pending":
                raise ApprovalUnavailableError("pending application must be decided before preapproval")

        existing = conn.execute(
            "SELECT customer_id, row_version FROM telegram_preapprovals WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
        if existing is None:
            if expected_version != 0:
                raise VersionConflictError("preapproval does not exist")
            conn.execute(
                """
                INSERT INTO telegram_preapprovals
                    (telegram_user_id, profile_kind, customer_id, created_by)
                VALUES (?, 'existing', ?, ?)
                """,
                (user_id, local_customer_id, actor),
            )
        else:
            if int(existing[1]) != expected_version:
                raise VersionConflictError("preapproval was updated by another administrator")
            conn.execute(
                """
                UPDATE telegram_preapprovals
                SET profile_kind = 'existing', customer_id = ?, email_display = NULL,
                    email_canonical = NULL, email_source = NULL,
                    target_snapshot_json = NULL, target_snapshot_digest = NULL,
                    created_by = ?, row_version = row_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND row_version = ?
                """,
                (local_customer_id, actor, user_id, expected_version),
            )
        preapproval = conn.execute(
            """
            SELECT p.telegram_user_id, p.profile_kind, p.customer_id,
                   COALESCE(c.email_display, p.email_display), p.email_source,
                   p.target_snapshot_json, p.target_snapshot_digest,
                   p.row_version, p.created_by, p.created_at
            FROM telegram_preapprovals AS p
            LEFT JOIN customers AS c ON c.id = p.customer_id
            WHERE p.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        assert preapproval is not None
        result = _preapproval_from_row(preapproval, **deps)
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('preapproval_saved', 'admin', ?, 'telegram_preapproval', ?, ?)
            """,
            (actor, str(user_id), digest),
        )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES ('create_preapproval', ?, ?, ?)
            """,
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result


def create_new_customer_preapproval(
    self,
    *,
    telegram_user_id: int,
    email_display: str,
    expected_preapproval_version: int,
    idempotency_key: str,
    created_by: str,
 **deps) -> TelegramPreapproval:
    """Persist a future customer profile before its first private ``/start``.

    The selected Telegram provisioning targets are copied into the profile
    at command time. Activation later uses that immutable copy rather than
    whichever node-policy values happen to exist at activation time.
    """
    ApprovalUnavailableError = deps["ApprovalUnavailableError"]
    BOT_CLIENT_FLOW = deps["BOT_CLIENT_FLOW"]
    BOT_INBOUND_ID = deps["BOT_INBOUND_ID"]
    IdempotencyConflictError = deps["IdempotencyConflictError"]
    TelegramRegistryError = deps["TelegramRegistryError"]
    VersionConflictError = deps["VersionConflictError"]
    _nonempty = deps["_nonempty"]
    _payload_digest = deps["_payload_digest"]
    _positive_int = deps["_positive_int"]
    _validate_email_choice = deps["_validate_email_choice"]
    canonicalize_email = deps["canonicalize_email"]
    connect = deps["connect"]

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    selected_email = _validate_email_choice(email_display)
    canonical = canonicalize_email(selected_email)
    if (
        isinstance(expected_preapproval_version, bool)
        or not isinstance(expected_preapproval_version, int)
        or expected_preapproval_version < 0
    ):
        raise TelegramRegistryError("expected_preapproval_version is invalid")
    expected_version = expected_preapproval_version
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(created_by, "created_by")
    payload = {
        "telegram_user_id": user_id,
        "email_display": selected_email,
        "expected_preapproval_version": expected_version,
    }
    digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'create_new_preapproval' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return _preapproval_from_receipt(json.loads(str(receipt[1])), **deps)

        if conn.execute(
            "SELECT 1 FROM customers WHERE email_canonical = ? AND deleted_at IS NULL", (canonical,)
        ).fetchone() is not None:
            raise ApprovalUnavailableError("customer email is already in use")
        identity = conn.execute(
            "SELECT access_status, customer_id FROM telegram_identities WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
        if identity is not None:
            if str(identity[0]) == "blocked":
                raise ApprovalUnavailableError("blocked identity cannot receive a preapproval")
            if identity[1] is not None:
                raise ApprovalUnavailableError("Telegram identity is already linked to a customer")
            if str(identity[0]) == "pending":
                raise ApprovalUnavailableError("pending application must be decided before preapproval")

        policies = conn.execute(
            """
            SELECT p.node_id, p.total_bytes, p.validity_days, p.client_enabled, p.policy_version
            FROM telegram_node_policies AS p
            JOIN nodes AS n ON n.id = p.node_id
            WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
            ORDER BY p.node_id
            """
        ).fetchall()
        if not policies:
            raise ApprovalUnavailableError("there are no eligible Telegram provisioning nodes")
        snapshot = [
            {
                "node_id": int(item[0]), "total_bytes": int(item[1]),
                "validity_days": int(item[2]), "client_enabled": bool(item[3]),
                "policy_version": int(item[4]), "inbound_id": BOT_INBOUND_ID,
                "flow": BOT_CLIENT_FLOW,
            }
            for item in policies
        ]
        snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        snapshot_digest = _payload_digest({"email": canonical, "targets": snapshot})
        existing = conn.execute(
            "SELECT row_version FROM telegram_preapprovals WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if existing is None:
            if expected_version != 0:
                raise VersionConflictError("preapproval does not exist")
            conn.execute(
                """
                INSERT INTO telegram_preapprovals
                    (telegram_user_id, profile_kind, email_display, email_canonical, email_source,
                     target_snapshot_json, target_snapshot_digest, created_by)
                VALUES (?, 'new', ?, ?, 'admin', ?, ?, ?)
                """,
                (user_id, selected_email, canonical, snapshot_json, snapshot_digest, actor),
            )
        else:
            if int(existing[0]) != expected_version:
                raise VersionConflictError("preapproval was updated by another administrator")
            updated = conn.execute(
                """
                UPDATE telegram_preapprovals
                SET profile_kind = 'new', customer_id = NULL, email_display = ?, email_canonical = ?,
                    email_source = 'admin', target_snapshot_json = ?, target_snapshot_digest = ?,
                    created_by = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND row_version = ?
                """,
                (selected_email, canonical, snapshot_json, snapshot_digest, actor, user_id, expected_version),
            )
            if updated.rowcount != 1:
                raise VersionConflictError("preapproval was updated by another administrator")
        row = conn.execute(
            """
            SELECT telegram_user_id, profile_kind, customer_id, email_display, email_source,
                   target_snapshot_json, target_snapshot_digest, row_version, created_by, created_at
            FROM telegram_preapprovals WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        assert row is not None
        result = _preapproval_from_row(row, **deps)
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('preapproval_new_saved', 'admin', ?, 'telegram_preapproval', ?, ?)
            """,
            (actor, str(user_id), _payload_digest({"command": digest, "snapshot": snapshot_digest})),
        )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES ('create_new_preapproval', ?, ?, ?)
            """,
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result


def activate_preapproval(self, telegram_user_id: int, **deps) -> ExistingApprovalResult | ApprovalResult | None:
    """Consume a preapproval after the authorized user starts a private chat.

    Existing-customer profiles only bind a verified local customer. New
    profiles create a customer and queue attempts from their persisted
    target snapshot; they never re-read mutable node policies here.
    """
    ExistingApprovalResult = deps["ExistingApprovalResult"]
    _payload_digest = deps["_payload_digest"]
    _positive_int = deps["_positive_int"]
    canonicalize_email = deps["canonicalize_email"]
    connect = deps["connect"]

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        preapproval = conn.execute(
            """
            SELECT profile_kind, customer_id, email_display, email_canonical, email_source,
                   target_snapshot_json, target_snapshot_digest
            FROM telegram_preapprovals WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if preapproval is None:
            return None
        identity = conn.execute(
            """
            SELECT access_status, customer_id, application_attempt, row_version
            FROM telegram_identities WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if identity is None or str(identity[0]) == "blocked":
            return None
        if str(identity[0]) not in {"eligible", "rejected"} or identity[1] is not None:
            return None

        if str(preapproval[0]) == "new":
            return _activate_new_customer_preapproval(
                self, conn=conn, telegram_user_id=user_id, identity=identity, preapproval=preapproval, **deps)
        if str(preapproval[0]) != "existing" or preapproval[1] is None:
            return None
        customer_id = int(preapproval[1])
        customer = conn.execute(
            """
            SELECT email_display, email_canonical, status
            FROM customers WHERE id = ? AND deleted_at IS NULL
            """,
            (customer_id,),
        ).fetchone()
        if customer is None or str(customer[2]) not in {"active", "suspended", "suspend_partial", "resume_partial"}:
            return None
        bindings = conn.execute(
            """
            SELECT remote_email FROM customer_node_bindings
            WHERE customer_id = ? AND management_state = 'confirmed'
            """,
            (customer_id,),
        ).fetchall()
        if not bindings or any(canonicalize_email(str(item[0])) != str(customer[1]) for item in bindings):
            return None
        linked = conn.execute(
            "SELECT telegram_user_id FROM telegram_identities WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        if linked is not None and int(linked[0]) != user_id:
            return None
        update = conn.execute(
            """
            UPDATE telegram_identities
            SET customer_id = ?, access_status = 'approved', approved_at = CURRENT_TIMESTAMP,
                approved_by = 'preapproval', decision_reason = NULL,
                introduction_requested_at = NULL, updated_at = CURRENT_TIMESTAMP,
                row_version = row_version + 1
            WHERE telegram_user_id = ? AND access_status IN ('eligible', 'rejected')
              AND customer_id IS NULL
            """,
            (customer_id, user_id),
        )
        if update.rowcount != 1:
            return None
        conn.execute("DELETE FROM telegram_preapprovals WHERE telegram_user_id = ?", (user_id,))
        next_version = int(identity[3]) + 1
        conn.execute(
            """
            INSERT OR IGNORE INTO telegram_outbox (event_type, entity_id, dedupe_key)
            VALUES ('user_existing_access_approved', ?, ?)
            """,
            (str(user_id), f"user:preapproval-activated:{user_id}:{customer_id}"),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('preapproval_activated', 'telegram_user', ?, 'telegram_identity', ?, ?)
            """,
            (str(user_id), str(user_id), _payload_digest({"customer_id": customer_id})),
        )
    return ExistingApprovalResult(
        telegram_user_id=user_id, customer_id=customer_id, email_display=str(customer[0]),
        confirmed_binding_count=len(bindings), identity_row_version=next_version,
    )


def _activate_new_customer_preapproval(
    self,
    *,
    conn: sqlite3.Connection,
    telegram_user_id: int,
    identity: tuple[object, ...],
    preapproval: tuple[object, ...],
 **deps) -> ApprovalResult | None:
    """Commit a new profile and its immutable provisioning attempts once."""
    ApprovalResult = deps["ApprovalResult"]
    BOT_CLIENT_FLOW = deps["BOT_CLIENT_FLOW"]
    BOT_INBOUND_ID = deps["BOT_INBOUND_ID"]
    VersionConflictError = deps["VersionConflictError"]
    _payload_digest = deps["_payload_digest"]

    email_display = str(preapproval[2] or "")
    email_canonical = str(preapproval[3] or "")
    email_source = str(preapproval[4] or "")
    snapshot_digest = str(preapproval[6] or "")
    if not email_display or not email_canonical or email_source != "admin" or not snapshot_digest:
        return None
    try:
        snapshot = json.loads(str(preapproval[5]))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(snapshot, list) or not snapshot:
        return None
    target_ids: set[int] = set()
    for target in snapshot:
        if not isinstance(target, dict):
            return None
        node_id = target.get("node_id")
        total_bytes = target.get("total_bytes")
        validity_days = target.get("validity_days")
        policy_version = target.get("policy_version")
        if (
            isinstance(node_id, bool) or not isinstance(node_id, int) or node_id <= 0
            or isinstance(total_bytes, bool) or not isinstance(total_bytes, int) or total_bytes < 0
            or isinstance(validity_days, bool) or not isinstance(validity_days, int) or validity_days < 0
            or isinstance(policy_version, bool) or not isinstance(policy_version, int) or policy_version <= 0
            or not isinstance(target.get("client_enabled"), bool)
            or target.get("inbound_id") != BOT_INBOUND_ID
            or target.get("flow") != BOT_CLIENT_FLOW
            or node_id in target_ids
        ):
            return None
        target_ids.add(node_id)
    if _payload_digest({"email": email_canonical, "targets": snapshot}) != snapshot_digest:
        return None
    if conn.execute(
        "SELECT 1 FROM customers WHERE email_canonical = ? AND deleted_at IS NULL", (email_canonical,)
    ).fetchone() is not None:
        return None
    for _ in range(20):
        public_code = secrets.token_urlsafe(9)
        if conn.execute("SELECT 1 FROM customers WHERE public_code = ?", (public_code,)).fetchone() is None:
            break
    else:
        return None
    try:
        customer = conn.execute(
            """
            INSERT INTO customers
                (email_display, email_canonical, origin, public_code, email_source)
            VALUES (?, ?, 'telegram', ?, ?)
            """,
            (email_display, email_canonical, public_code, email_source),
        )
    except sqlite3.IntegrityError:
        return None
    customer_id = int(customer.lastrowid)
    job_snapshot_digest = _payload_digest(
        {"customer_id": customer_id, "email": email_canonical, "targets": snapshot}
    )
    job = conn.execute(
        """
        INSERT INTO telegram_provisioning_jobs
            (customer_id, trigger, idempotency_key, policy_snapshot_digest, created_by)
        VALUES (?, 'approve_new', ?, ?, 'preapproval')
        """,
        (customer_id, f"preapproval-new:{telegram_user_id}:{snapshot_digest}", job_snapshot_digest),
    )
    job_id = int(job.lastrowid)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for target in snapshot:
        validity_days = int(target["validity_days"])
        expiry_time = now_ms + validity_days * 24 * 60 * 60 * 1000 if validity_days else 0
        conn.execute(
            """
            INSERT INTO telegram_provisioning_attempts
                (job_id, node_id, inbound_id, desired_client_id, desired_sub_id,
                 desired_flow, desired_total_bytes, desired_validity_days,
                 desired_expiry_time, desired_client_enabled, policy_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, int(target["node_id"]), BOT_INBOUND_ID, str(uuid.uuid4()), str(uuid.uuid4()),
                BOT_CLIENT_FLOW, int(target["total_bytes"]), validity_days, expiry_time,
                int(bool(target["client_enabled"])), int(target["policy_version"]),
            ),
        )
    update = conn.execute(
        """
        UPDATE telegram_identities
        SET customer_id = ?, access_status = 'approved', approved_at = CURRENT_TIMESTAMP,
            approved_by = 'preapproval', decision_reason = NULL,
            introduction_requested_at = NULL, updated_at = CURRENT_TIMESTAMP,
            row_version = row_version + 1
        WHERE telegram_user_id = ? AND access_status IN ('eligible', 'rejected') AND customer_id IS NULL
        """,
        (customer_id, telegram_user_id),
    )
    if update.rowcount != 1:
        raise VersionConflictError("preapproval activation raced with another identity update")
    conn.execute("DELETE FROM telegram_preapprovals WHERE telegram_user_id = ?", (telegram_user_id,))
    conn.execute(
        """
        INSERT OR IGNORE INTO telegram_outbox (event_type, entity_id, dedupe_key)
        VALUES ('user_provisioning_queued', ?, ?)
        """,
        (str(telegram_user_id), f"user:preapproval-new-provisioning:{telegram_user_id}:{snapshot_digest}"),
    )
    conn.execute(
        """
        INSERT INTO telegram_audit_log
            (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
        VALUES ('preapproval_new_activated', 'telegram_user', ?, 'telegram_identity', ?, ?)
        """,
        (str(telegram_user_id), str(telegram_user_id), job_snapshot_digest),
    )
    return ApprovalResult(
        telegram_user_id=telegram_user_id, customer_id=customer_id, job_id=job_id,
        email_display=email_display, email_source=email_source,
        target_node_ids=tuple(item["node_id"] for item in snapshot),
        identity_row_version=int(identity[3]) + 1,
    )


def unlink_identity(
    self,
    *,
    telegram_user_id: int,
    customer_id: int,
    expected_identity_version: int,
    idempotency_key: str,
    unlinked_by: str,
 **deps) -> TelegramUnlinkResult:
    """Remove only the local Telegram association; remote clients are untouched."""
    IdempotencyConflictError = deps["IdempotencyConflictError"]
    LifecycleUnavailableError = deps["LifecycleUnavailableError"]
    TelegramUnlinkResult = deps["TelegramUnlinkResult"]
    VersionConflictError = deps["VersionConflictError"]
    _nonempty = deps["_nonempty"]
    _payload_digest = deps["_payload_digest"]
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    local_customer_id = _positive_int(customer_id, "customer_id")
    expected_version = _positive_int(expected_identity_version, "expected_identity_version")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(unlinked_by, "unlinked_by")
    payload = {
        "telegram_user_id": user_id, "customer_id": local_customer_id,
        "expected_identity_version": expected_version,
    }
    digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'unlink_identity' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return TelegramUnlinkResult(**json.loads(str(receipt[1])))
        identity = conn.execute(
            """
            SELECT access_status, customer_id, row_version
            FROM telegram_identities WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if identity is None or str(identity[0]) != "approved" or identity[1] != local_customer_id:
            raise VersionConflictError("identity is not approved for this customer")
        if int(identity[2]) != expected_version:
            raise VersionConflictError("identity was updated by another administrator")
        customer = conn.execute(
            "SELECT status FROM customers WHERE id = ? AND deleted_at IS NULL", (local_customer_id,)
        ).fetchone()
        if customer is None or str(customer[0]) in {"deleting", "delete_partial", "deleted"}:
            raise LifecycleUnavailableError("customer cannot be unlinked during deletion")
        update = conn.execute(
            """
            UPDATE telegram_identities
            SET customer_id = NULL, access_status = 'eligible', request_code = NULL,
                approved_at = NULL, approved_by = NULL, decision_reason = 'unlinked',
                blocked_from_status = NULL, introduction_requested_at = NULL,
                updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
            WHERE telegram_user_id = ? AND customer_id = ? AND access_status = 'approved'
              AND row_version = ?
            """,
            (user_id, local_customer_id, expected_version),
        )
        if update.rowcount != 1:
            raise VersionConflictError("identity was updated by another administrator")
        result = TelegramUnlinkResult(user_id, local_customer_id, expected_version + 1)
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('identity_unlinked', 'admin', ?, 'telegram_identity', ?, ?)
            """,
            (actor, str(user_id), digest),
        )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES ('unlink_identity', ?, ?, ?)
            """,
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result


def safe_subscription_node_ids(self, email: str, **deps) -> frozenset[int] | None:
    """Return exact confirmed Telegram targets, or ``None`` for legacy users.

    This is local metadata only. A partial existing-adoption customer may
    receive artifacts only for bindings that the durable workers confirmed.
    """
    canonicalize_email = deps["canonicalize_email"]
    connect = deps["connect"]
    canonical = canonicalize_email(email)
    with connect(self._db_path) as conn:
        identities = conn.execute(
            """SELECT i.customer_id FROM telegram_identities AS i
                JOIN customers AS c ON c.id = i.customer_id
                WHERE c.email_canonical = ? AND c.deleted_at IS NULL
                  AND i.access_status = 'approved'""",
            (canonical,),
        ).fetchall()
        if not identities:
            return None
        customer_ids = {int(row[0]) for row in identities if row[0] is not None}
        if len(customer_ids) != 1:
            return frozenset()
        customer_id = next(iter(customer_ids))
        # Existing Telegram customers predating immutable discovery retain
        # their legacy link contract. Filtering begins only for the new
        # deferred existing-email snapshot that explicitly carries targets.
        has_snapshot = conn.execute(
            "SELECT 1 FROM telegram_existing_discovery_jobs WHERE customer_id = ? LIMIT 1",
            (customer_id,),
        ).fetchone()
        if has_snapshot is None:
            return None
        rows = conn.execute(
            """SELECT node_id FROM customer_node_bindings
                WHERE customer_id = ? AND inbound_id = 1
                  AND management_state = 'confirmed' AND remote_client_id IS NOT NULL""",
            (customer_id,),
        ).fetchall()
    return frozenset(int(row[0]) for row in rows)


def enabled_node_ids(self, **deps) -> frozenset[int]:
    """Return enabled node ids from the local database only."""
    connect = deps["connect"]

    with connect(self._db_path) as conn:
        rows = conn.execute("SELECT id FROM nodes WHERE enabled = 1").fetchall()
    return frozenset(int(row[0]) for row in rows)


def has_confirmed_enabled_subscription_binding(self, email: str, **deps) -> bool:
    """Return whether an older customer has a locally usable subscription target."""
    canonicalize_email = deps["canonicalize_email"]
    connect = deps["connect"]

    canonical = canonicalize_email(email)
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM customers AS c
            JOIN customer_node_bindings AS b ON b.customer_id = c.id
            JOIN nodes AS n ON n.id = b.node_id
            WHERE c.email_canonical = ? AND c.deleted_at IS NULL
              AND b.management_state = 'confirmed'
              AND b.desired_enabled = 1
              AND n.enabled = 1
            LIMIT 1
            """,
            (canonical,),
        ).fetchone()
    return row is not None


def get_customer_access(self, telegram_user_id: int, **deps) -> TelegramCustomerAccess:
    """Resolve approved access strictly from the numeric Telegram identity."""
    TelegramCustomerAccess = deps["TelegramCustomerAccess"]
    TelegramRegistryError = deps["TelegramRegistryError"]
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    initial_job_incomplete = deps["initial_job_incomplete"]

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT i.telegram_user_id, i.chat_id, i.access_status, i.customer_id,
                   c.email_display, c.status, c.row_version, i.blocked_from_status,
                   i.remote_snapshot_ready
            FROM telegram_identities AS i
            LEFT JOIN customers AS c ON c.id = i.customer_id
            WHERE i.telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        raise TelegramRegistryError("Telegram identity was not found")
    initial_provisioning_ready = bool(row[8])
    customer_id = int(row[3]) if row[3] is not None else None
    if customer_id is not None and initial_provisioning_ready:
        # Compatibility for records created before remote_snapshot_ready
        # existed.  The gate is source-agnostic: any unfinished initial
        # snapshot job denies access even if its identity column carries
        # the migration default.
        with connect(self._db_path) as conn:
            initial_provisioning_ready = not initial_job_incomplete(conn, customer_id)
    return TelegramCustomerAccess(
        telegram_user_id=int(row[0]),
        chat_id=int(row[1]),
        access_status=str(row[2]),
        customer_id=customer_id,
        email_display=str(row[4]) if row[4] is not None else None,
        customer_status=str(row[5]) if row[5] is not None else None,
        customer_row_version=int(row[6]) if row[6] is not None else None,
        blocked_from_status=str(row[7]) if row[7] is not None else None,
        initial_provisioning_ready=initial_provisioning_ready,
    )


def get_interface_window(self, telegram_user_id: int, **deps) -> tuple[int, bool] | None:
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        row = conn.execute(
            "SELECT interface_message_id, interface_message_has_text "
            "FROM telegram_identities WHERE telegram_user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0]), bool(row[1])


def set_interface_window(
    self, *, telegram_user_id: int, message_id: int, has_text: bool
, **deps) -> None:
    TelegramRegistryError = deps["TelegramRegistryError"]
    _positive_int = deps["_positive_int"]
    connect = deps["connect"]
    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    normalized_message_id = _positive_int(message_id, "message_id")
    if not isinstance(has_text, bool):
        raise TelegramRegistryError("has_text must be a boolean")
    with connect(self._db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities "
            "SET interface_message_id = ?, interface_message_has_text = ? "
            "WHERE telegram_user_id = ?",
            (normalized_message_id, int(has_text), user_id),
        )


def _active_telegram_customer(conn: sqlite3.Connection, telegram_user_id: int, **deps) -> tuple[int, str]:
    TelegramRegistryError = deps["TelegramRegistryError"]
    row = conn.execute(
        """
        SELECT c.id, c.email_display
        FROM telegram_identities AS i
        JOIN customers AS c ON c.id = i.customer_id
        WHERE i.telegram_user_id = ? AND i.access_status = 'approved'
          AND c.status = 'active' AND c.deleted_at IS NULL
        """,
        (telegram_user_id,),
    ).fetchone()
    if row is None:
        raise TelegramRegistryError("active Telegram customer access is required")
    return int(row[0]), str(row[1])


def create_customer(
    self,
    *,
    email_display: str,
    origin: str,
    email_source: str,
    public_code: str | None = None,
 **deps) -> int:
    TelegramRegistryError = deps["TelegramRegistryError"]
    _nonempty = deps["_nonempty"]
    canonicalize_email = deps["canonicalize_email"]
    connect = deps["connect"]
    display = _nonempty(email_display, "email_display")
    canonical = canonicalize_email(display)
    if origin not in {"existing", "telegram", "manual"}:
        raise TelegramRegistryError("unsupported customer origin")
    if email_source not in {
        "telegram_username",
        "telegram_name",
        "fallback",
        "admin",
        "existing",
    }:
        raise TelegramRegistryError("unsupported email source")
    code = public_code or secrets.token_urlsafe(9)
    with connect(self._db_path) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO customers
                    (email_display, email_canonical, origin, public_code, email_source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (display, canonical, origin, code, email_source),
            )
        except sqlite3.IntegrityError as exc:
            raise TelegramRegistryError("customer email or public code already exists") from exc
    return int(cursor.lastrowid)


