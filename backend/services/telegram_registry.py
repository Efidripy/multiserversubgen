"""SQLite repository for the Telegram integration's local authority.

This module deliberately does not call Telegram or an x-ui node. It provides
small, transactional commands that later adapters can use after transport and
remote-capability checks have completed.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from services.db_bootstrap import connect


BOT_INBOUND_ID = 1
BOT_CLIENT_FLOW = "xtls-rprx-vision"


class TelegramRegistryError(RuntimeError):
    """Base error for a safely rejectable Telegram-domain command."""


class VersionConflictError(TelegramRegistryError):
    """The caller based a mutation on an obsolete projection."""


class NodePolicyUnavailableError(TelegramRegistryError):
    """The node cannot safely accept a newly provisioned Telegram client."""


class IdempotencyConflictError(TelegramRegistryError):
    """An idempotency key was replayed with a different command payload."""


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_user_id: int
    chat_id: int
    access_status: str
    application_attempt: int
    customer_id: int | None
    row_version: int


@dataclass(frozen=True)
class NodeProvisioningPolicy:
    node_id: int
    provisioning_enabled: bool
    total_bytes: int
    validity_days: int
    client_enabled: bool
    policy_version: int
    updated_by: str


@dataclass(frozen=True)
class CustomerNodeMatrixRow:
    node_id: int
    node_name: str
    state: str
    binding_id: int | None
    desired_enabled: bool | None
    management_state: str | None


@dataclass(frozen=True)
class PendingApplicationResult:
    identity: TelegramIdentity
    created: bool
    request_code: str | None


def canonicalize_email(value: str) -> str:
    """Return the stable comparison form used by the local customer registry."""

    canonical = unicodedata.normalize("NFKC", value).strip().casefold()
    if not canonical:
        raise TelegramRegistryError("email must not be empty")
    return canonical


def _positive_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TelegramRegistryError(f"{field} must be a positive integer")
    return value


def _nonempty(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TelegramRegistryError(f"{field} must not be empty")
    return normalized


def _bounded_nonnegative(value: Any, field: str) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise TelegramRegistryError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TelegramRegistryError(f"{field} must be a non-negative integer") from exc
    if parsed < 0 or parsed > 2**63 - 1:
        raise TelegramRegistryError(f"{field} must be a non-negative integer")
    return parsed


def _default_client_enabled(value: Any) -> bool:
    if value is None or value == "":
        return True
    if not isinstance(value, bool):
        raise TelegramRegistryError("client_enabled must be a boolean")
    return value


def _payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _policy_from_row(row: tuple[Any, ...]) -> NodeProvisioningPolicy:
    return NodeProvisioningPolicy(
        node_id=int(row[0]),
        provisioning_enabled=bool(row[1]),
        total_bytes=int(row[2]),
        validity_days=int(row[3]),
        client_enabled=bool(row[4]),
        policy_version=int(row[5]),
        updated_by=str(row[6]),
    )


class TelegramRegistry:
    """Transactional access to the Telegram-specific SQLite records."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    def get_or_create_identity(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        locale: str = "ru",
    ) -> TelegramIdentity:
        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        normalized_locale = locale if locale in {"ru", "en"} else "ru"
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
                        (telegram_user_id, chat_id, username, first_name, last_name, locale)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, chat_id, username, first_name, last_name, normalized_locale),
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
                    SET chat_id = ?, username = ?, first_name = ?, last_name = ?, locale = ?,
                        updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                    WHERE telegram_user_id = ?
                    """,
                    (chat_id, username, first_name, last_name, normalized_locale, user_id),
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

    def create_customer(
        self,
        *,
        email_display: str,
        origin: str,
        email_source: str,
        public_code: str | None = None,
    ) -> int:
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

    def create_pending_application(self, telegram_user_id: int) -> PendingApplicationResult:
        """Atomically create exactly one admin-notified pending attempt."""

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        with connect(self._db_path) as conn:
            identity = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt,
                       customer_id, row_version
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if identity is None:
                raise TelegramRegistryError("identity must be registered before creating an application")
            access_status = str(identity[2])
            existing_identity = TelegramIdentity(
                telegram_user_id=int(identity[0]),
                chat_id=int(identity[1]),
                access_status=access_status,
                application_attempt=int(identity[3]),
                customer_id=int(identity[4]) if identity[4] is not None else None,
                row_version=int(identity[5]),
            )
            if access_status == "blocked":
                return PendingApplicationResult(existing_identity, created=False, request_code=None)
            if access_status in {"pending", "approved"}:
                return PendingApplicationResult(existing_identity, created=False, request_code=None)

            next_attempt = existing_identity.application_attempt + 1
            request_code = secrets.token_urlsafe(6)
            conn.execute(
                """
                UPDATE telegram_identities
                SET access_status = 'pending', request_code = ?, application_attempt = ?,
                    requested_at = CURRENT_TIMESTAMP, rejected_at = NULL,
                    decision_reason = NULL, updated_at = CURRENT_TIMESTAMP,
                    row_version = row_version + 1
                WHERE telegram_user_id = ?
                """,
                (request_code, next_attempt, user_id),
            )
            conn.execute(
                """
                INSERT INTO telegram_applications (telegram_user_id, application_attempt)
                VALUES (?, ?)
                """,
                (user_id, next_attempt),
            )
            conn.execute(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('admin_request_created', ?, ?)
                """,
                (str(user_id), f"admin:request-created:{user_id}:{next_attempt}"),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id)
                VALUES ('request_created', 'telegram_user', ?, 'telegram_identity', ?)
                """,
                (str(user_id), str(user_id)),
            )
            row = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt,
                       customer_id, row_version
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
        assert row is not None
        return PendingApplicationResult(
            identity=TelegramIdentity(
                telegram_user_id=int(row[0]),
                chat_id=int(row[1]),
                access_status=str(row[2]),
                application_attempt=int(row[3]),
                customer_id=int(row[4]) if row[4] is not None else None,
                row_version=int(row[5]),
            ),
            created=True,
            request_code=request_code,
        )

    def submit_introduction(self, telegram_user_id: int, text: str, *, maximum_chars: int) -> bool:
        """Store one plain-text voluntary introduction for the active attempt."""

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        normalized = text.strip()
        if not normalized or len(normalized) > maximum_chars:
            raise TelegramRegistryError("introduction length is invalid")
        with connect(self._db_path) as conn:
            identity = conn.execute(
                """
                SELECT access_status, application_attempt
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if identity is None or str(identity[0]) != "pending":
                return False
            result = conn.execute(
                """
                UPDATE telegram_applications
                SET introduction_text = ?, introduction_submitted_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND application_attempt = ?
                  AND status = 'pending' AND introduction_text IS NULL
                """,
                (normalized, user_id, int(identity[1])),
            )
        return result.rowcount == 1

    def claim_update(
        self,
        *,
        update_id: int,
        telegram_user_id: int | None,
        update_type: str,
        payload_digest: str,
    ) -> bool:
        """Persist Telegram's update id before any state-changing handling."""

        normalized_update_id = _positive_int(update_id, "update_id")
        normalized_user_id = (
            _positive_int(telegram_user_id, "telegram_user_id")
            if telegram_user_id is not None
            else None
        )
        with connect(self._db_path) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO telegram_updates (update_id, telegram_user_id, update_type, payload_digest)
                    VALUES (?, ?, ?, ?)
                    """,
                    (normalized_update_id, normalized_user_id, _nonempty(update_type, "update_type"), _nonempty(payload_digest, "payload_digest")),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def set_node_provisioning_policy(
        self,
        *,
        node_id: int,
        provisioning_enabled: bool,
        total_bytes: int | str | None,
        validity_days: int | str | None,
        client_enabled: bool | str | None,
        expected_policy_version: int,
        idempotency_key: str,
        updated_by: str,
        node_is_compatible: bool,
    ) -> NodeProvisioningPolicy:
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

    def list_eligible_provisioning_nodes(self) -> list[NodeProvisioningPolicy]:
        with connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT p.node_id, p.provisioning_enabled, p.total_bytes, p.validity_days,
                       p.client_enabled, p.policy_version, p.updated_by
                FROM telegram_node_policies AS p
                JOIN nodes AS n ON n.id = p.node_id
                WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
                ORDER BY n.name COLLATE NOCASE, n.id
                """
            ).fetchall()
        return [_policy_from_row(row) for row in rows]

    def list_node_provisioning_policies(self) -> list[NodeProvisioningPolicy]:
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

    def customer_node_matrix(self, customer_id: int) -> list[CustomerNodeMatrixRow]:
        """Return only bindings plus genuine Telegram-enabled add targets."""

        normalized_customer_id = _positive_int(customer_id, "customer_id")
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
            bound_node_ids = {int(row[1]) for row in bound_rows}
            available_rows = conn.execute(
                """
                SELECT n.id, n.name
                FROM telegram_node_policies AS p
                JOIN nodes AS n ON n.id = p.node_id
                WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
                ORDER BY n.name COLLATE NOCASE, n.id
                """
            ).fetchall()

        result: list[CustomerNodeMatrixRow] = []
        for binding_id, node_id, name, enabled, read_only, desired_enabled, management_state in bound_rows:
            if str(management_state) != "confirmed" or not bool(enabled) or bool(read_only):
                state = "problem"
            elif bool(desired_enabled):
                state = "active"
            else:
                state = "suspended"
            result.append(
                CustomerNodeMatrixRow(
                    node_id=int(node_id),
                    node_name=str(name),
                    state=state,
                    binding_id=int(binding_id),
                    desired_enabled=bool(desired_enabled),
                    management_state=str(management_state),
                )
            )
        for node_id, name in available_rows:
            if int(node_id) not in bound_node_ids:
                result.append(
                    CustomerNodeMatrixRow(
                        node_id=int(node_id),
                        node_name=str(name),
                        state="available_to_add",
                        binding_id=None,
                        desired_enabled=None,
                        management_state=None,
                    )
                )
        return result


def exact_node_ids(rows: Iterable[CustomerNodeMatrixRow]) -> set[int]:
    """Small helper for later preview commands; never infer IDs from labels."""

    return {row.node_id for row in rows}
