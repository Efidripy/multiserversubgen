"""SQLite repository for the Telegram integration's local authority.

This module deliberately does not call Telegram or an x-ui node. It provides
small, transactional commands that later adapters can use after transport and
remote-capability checks have completed.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable

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


class ApprovalUnavailableError(TelegramRegistryError):
    """A request cannot be approved without a safe local target snapshot."""


class LifecycleUnavailableError(TelegramRegistryError):
    """A lifecycle command has no safe, exact set of remote targets."""


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_user_id: int
    chat_id: int
    access_status: str
    application_attempt: int
    customer_id: int | None
    row_version: int


@dataclass(frozen=True)
class TelegramCustomerAccess:
    telegram_user_id: int
    chat_id: int
    access_status: str
    customer_id: int | None
    email_display: str | None
    customer_status: str | None
    customer_row_version: int | None


@dataclass(frozen=True)
class TelegramNotificationPreferences:
    telegram_user_id: int
    background_notifications_enabled: bool
    row_version: int


@dataclass(frozen=True)
class CustomerTrafficLedger:
    customer_id: int
    lifetime_bytes: int
    last_observed_bytes: int
    last_observed_at: str


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


@dataclass(frozen=True)
class PendingApplication:
    telegram_user_id: int
    chat_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    application_attempt: int
    request_code: str
    row_version: int
    requested_at: str | None
    introduction_text: str | None
    suggested_email: str
    suggested_email_source: str


@dataclass(frozen=True)
class ApprovalResult:
    telegram_user_id: int
    customer_id: int
    job_id: int
    email_display: str
    email_source: str
    target_node_ids: tuple[int, ...]
    identity_row_version: int


@dataclass(frozen=True)
class ExistingApprovalResult:
    telegram_user_id: int
    customer_id: int
    email_display: str
    confirmed_binding_count: int
    identity_row_version: int


@dataclass(frozen=True)
class AbuseNoopResult:
    auto_blocked: bool
    suppress_response: bool
    noop_count: int


@dataclass(frozen=True)
class AppealResult:
    appeal_id: int
    created: bool
    status: str


@dataclass(frozen=True)
class AppealAdminItem:
    appeal_id: int
    telegram_user_id: int
    customer_id: int
    email_display: str
    body: str
    status: str
    row_version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AppealResolutionResult:
    appeal_id: int
    status: str
    row_version: int


@dataclass(frozen=True)
class ProvisioningAttemptStatus:
    node_id: int
    node_name: str
    status: str
    error_code: str | None
    error_summary: str | None
    attempt_count: int
    next_attempt_at: str | None


@dataclass(frozen=True)
class ProvisioningJobStatus:
    job_id: int
    customer_id: int
    customer_email: str
    trigger: str
    status: str
    attempt_count: int
    row_version: int
    created_at: str
    finished_at: str | None
    attempts: tuple[ProvisioningAttemptStatus, ...]


@dataclass(frozen=True)
class ProvisioningRescheduleResult:
    job_id: int
    status: str
    row_version: int


@dataclass(frozen=True)
class NodeProvisioningQueueResult:
    job_id: int
    customer_id: int
    node_id: int
    status: str
    row_version: int


@dataclass(frozen=True)
class CustomerListItem:
    customer_id: int
    email_display: str
    origin: str
    status: str
    row_version: int
    telegram_user_id: int | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CustomerPage:
    items: tuple[CustomerListItem, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class CustomerOperationTarget:
    binding_id: int
    node_id: int
    node_name: str
    inbound_id: int
    action: str
    previous_enabled: bool | None


@dataclass(frozen=True)
class CustomerOperationPreview:
    customer_id: int
    operation_type: str
    expected_customer_version: int
    target_snapshot_digest: str
    targets: tuple[CustomerOperationTarget, ...]
    blocked_binding_ids: tuple[int, ...]


@dataclass(frozen=True)
class CustomerOperationAttemptStatus:
    binding_id: int
    node_id: int
    node_name: str
    action: str
    status: str
    error_code: str | None
    error_summary: str | None
    attempt_count: int


@dataclass(frozen=True)
class CustomerOperationStatus:
    operation_id: int
    customer_id: int
    customer_email: str
    operation_type: str
    status: str
    row_version: int
    attempt_count: int
    target_snapshot_digest: str
    created_at: str
    finished_at: str | None
    attempts: tuple[CustomerOperationAttemptStatus, ...]


@dataclass(frozen=True)
class CustomerOperationQueueResult:
    operation_id: int
    customer_id: int
    operation_type: str
    status: str
    row_version: int


@dataclass(frozen=True)
class CustomerOperationRescheduleResult:
    operation_id: int
    status: str
    row_version: int


_RESERVED_EMAILS = {"admin", "root", "support", "system", "telegram", "bot", "null", "undefined"}
_TRANSLITERATION = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
        "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
)


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


def _stable_identity_suffix(telegram_user_id: int) -> str:
    """A non-reversible suffix prevents collisions without exposing a TG id."""

    return hashlib.sha256(f"tg-email:{telegram_user_id}".encode("ascii")).hexdigest()[:6]


def _transliterate(value: str) -> str:
    return value.casefold().translate(_TRANSLITERATION)


def _normalize_service_name(value: str) -> str:
    normalized = _transliterate(unicodedata.normalize("NFKC", value).strip())
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"[-._]{2,}", "-", normalized).strip("-._")
    return normalized[:64]


def _normalize_explicit_email(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if normalized.count("@") != 1:
        return _normalize_service_name(normalized)
    local_part, domain = normalized.split("@", 1)
    local = _normalize_service_name(local_part)
    domain_normalized = _transliterate(domain)
    domain_normalized = re.sub(r"[^a-z0-9.-]+", "-", domain_normalized)
    domain_normalized = re.sub(r"[.]{2,}", ".", domain_normalized).strip(".-")
    if not local or not domain_normalized or "." not in domain_normalized:
        raise TelegramRegistryError("email is invalid")
    result = f"{local}@{domain_normalized}"
    if len(result) > 64:
        raise TelegramRegistryError("email is too long")
    return result


def _validate_email_choice(value: str) -> str:
    normalized = _normalize_explicit_email(value)
    if len(normalized) < 3:
        raise TelegramRegistryError("email must contain at least 3 safe characters")
    local_part = normalized.split("@", 1)[0]
    if local_part in _RESERVED_EMAILS:
        raise TelegramRegistryError("email is reserved")
    return normalized


def _suggestion_source(username: str | None, first_name: str | None, last_name: str | None) -> tuple[str, str]:
    if username and username.strip().lstrip("@"):
        return username.strip().lstrip("@"), "telegram_username"
    name = " ".join(part.strip() for part in (first_name or "", last_name or "") if part.strip())
    if name:
        return name, "telegram_name"
    return "", "fallback"


def _suggested_email(
    *, telegram_user_id: int, username: str | None, first_name: str | None, last_name: str | None,
    canonical_exists: Callable[[str], bool],
) -> tuple[str, str]:
    source_value, source = _suggestion_source(username, first_name, last_name)
    candidate = _normalize_service_name(source_value)
    if len(candidate) < 3 or candidate in _RESERVED_EMAILS:
        candidate = f"user-{_stable_identity_suffix(telegram_user_id)}"
        source = "fallback"
    if not canonical_exists(canonicalize_email(candidate)):
        return candidate, source
    suffix = _stable_identity_suffix(telegram_user_id)
    for index in range(1, 101):
        postfix = f"-{suffix}" if index == 1 else f"-{suffix}-{index}"
        variant = f"{candidate[:64 - len(postfix)].rstrip('-._')}{postfix}"
        if not canonical_exists(canonicalize_email(variant)):
            return variant, source
    raise ApprovalUnavailableError("unable to allocate a unique customer email")


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


def _identity_from_row(row: tuple[Any, ...]) -> TelegramIdentity:
    return TelegramIdentity(
        telegram_user_id=int(row[0]),
        chat_id=int(row[1]),
        access_status=str(row[2]),
        application_attempt=int(row[3]),
        customer_id=int(row[4]) if row[4] is not None else None,
        row_version=int(row[5]),
    )


class TelegramRegistry:
    """Transactional access to the Telegram-specific SQLite records."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    @property
    def database_path(self) -> str:
        """Configured local authority path for sibling local-only services."""

        return self._db_path

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

    def get_customer_access(self, telegram_user_id: int) -> TelegramCustomerAccess:
        """Resolve approved access strictly from the numeric Telegram identity."""

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT i.telegram_user_id, i.chat_id, i.access_status, i.customer_id,
                       c.email_display, c.status, c.row_version
                FROM telegram_identities AS i
                LEFT JOIN customers AS c ON c.id = i.customer_id
                WHERE i.telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            raise TelegramRegistryError("Telegram identity was not found")
        return TelegramCustomerAccess(
            telegram_user_id=int(row[0]),
            chat_id=int(row[1]),
            access_status=str(row[2]),
            customer_id=int(row[3]) if row[3] is not None else None,
            email_display=str(row[4]) if row[4] is not None else None,
            customer_status=str(row[5]) if row[5] is not None else None,
            customer_row_version=int(row[6]) if row[6] is not None else None,
        )

    def get_notification_preferences(self, telegram_user_id: int) -> TelegramNotificationPreferences:
        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        with connect(self._db_path) as conn:
            identity = conn.execute(
                "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
            ).fetchone()
            if identity is None:
                raise TelegramRegistryError("Telegram identity was not found")
            conn.execute(
                "INSERT OR IGNORE INTO telegram_notification_preferences (telegram_user_id) VALUES (?)",
                (user_id,),
            )
            row = conn.execute(
                """
                SELECT background_notifications_enabled, row_version
                FROM telegram_notification_preferences WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
        assert row is not None
        return TelegramNotificationPreferences(user_id, bool(row[0]), int(row[1]))

    def toggle_background_notifications(self, telegram_user_id: int) -> TelegramNotificationPreferences:
        """Toggle user-controlled background delivery after durable update dedupe."""

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        with connect(self._db_path) as conn:
            identity = conn.execute(
                "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
            ).fetchone()
            if identity is None:
                raise TelegramRegistryError("Telegram identity was not found")
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

    def observe_customer_traffic(self, *, customer_id: int, observed_bytes: int) -> CustomerTrafficLedger:
        """Accumulate a customer lifetime counter independent of subscription tokens.

        The source is an aggregate client counter. A lower next observation is
        treated as a panel-side counter reset and starts a fresh epoch without
        subtracting historical usage already recorded for this customer.
        """

        local_customer_id = _positive_int(customer_id, "customer_id")
        if isinstance(observed_bytes, bool) or not isinstance(observed_bytes, int) or observed_bytes < 0:
            raise TelegramRegistryError("observed_bytes must be a non-negative integer")
        with connect(self._db_path) as conn:
            customer = conn.execute("SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)).fetchone()
            if customer is None:
                raise TelegramRegistryError("customer was not found")
            row = conn.execute(
                "SELECT lifetime_bytes, last_observed_bytes FROM customer_traffic_ledger WHERE customer_id = ?",
                (local_customer_id,),
            ).fetchone()
            if row is None:
                lifetime, previous = observed_bytes, observed_bytes
                conn.execute(
                    """
                    INSERT INTO customer_traffic_ledger
                        (customer_id, lifetime_bytes, last_observed_bytes)
                    VALUES (?, ?, ?)
                    """,
                    (local_customer_id, lifetime, previous),
                )
            else:
                lifetime, previous = int(row[0]), int(row[1])
                increment = observed_bytes - previous if observed_bytes >= previous else observed_bytes
                lifetime += increment
                conn.execute(
                    """
                    UPDATE customer_traffic_ledger
                    SET lifetime_bytes = ?, last_observed_bytes = ?, last_observed_at = CURRENT_TIMESTAMP,
                        row_version = row_version + 1
                    WHERE customer_id = ?
                    """,
                    (lifetime, observed_bytes, local_customer_id),
                )
            result = conn.execute(
                """
                SELECT customer_id, lifetime_bytes, last_observed_bytes, last_observed_at
                FROM customer_traffic_ledger WHERE customer_id = ?
                """,
                (local_customer_id,),
            ).fetchone()
        assert result is not None
        return CustomerTrafficLedger(
            customer_id=int(result[0]), lifetime_bytes=int(result[1]),
            last_observed_bytes=int(result[2]), last_observed_at=str(result[3]),
        )

    def get_customer_traffic(self, customer_id: int) -> CustomerTrafficLedger:
        local_customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT customer_id, lifetime_bytes, last_observed_bytes, last_observed_at
                FROM customer_traffic_ledger WHERE customer_id = ?
                """,
                (local_customer_id,),
            ).fetchone()
        if row is None:
            return CustomerTrafficLedger(local_customer_id, 0, 0, "")
        return CustomerTrafficLedger(
            customer_id=int(row[0]), lifetime_bytes=int(row[1]),
            last_observed_bytes=int(row[2]), last_observed_at=str(row[3]),
        )

    def submit_suspended_appeal(self, *, telegram_user_id: int, body: str) -> AppealResult:
        """Store one bounded appeal; it never changes customer access."""

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        normalized_body = body.strip()
        if not 1 <= len(normalized_body) <= 1000:
            raise TelegramRegistryError("appeal body must contain 1 to 1000 characters")
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT i.customer_id, i.access_status, c.status
                FROM telegram_identities AS i
                JOIN customers AS c ON c.id = i.customer_id
                WHERE i.telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None or str(row[1]) != "approved" or str(row[2]) not in {
                "suspended", "suspend_partial", "resume_partial"
            }:
                raise TelegramRegistryError("appeal is available only for a suspended customer")
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO telegram_appeals (telegram_user_id, customer_id, body)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, int(row[0]), normalized_body),
                )
                appeal_id = int(cursor.lastrowid)
                result = AppealResult(appeal_id=appeal_id, created=True, status="open")
                conn.execute(
                    """
                    INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json)
                    VALUES ('admin_appeal_created', ?, ?, ?)
                    """,
                    (str(appeal_id), f"admin:appeal-created:{appeal_id}", json.dumps({"appeal_id": appeal_id})),
                )
                conn.execute(
                    """
                    INSERT INTO telegram_audit_log
                        (event_type, actor_type, actor_id, entity_type, entity_id)
                    VALUES ('appeal_created', 'telegram_user', ?, 'telegram_appeal', ?)
                    """,
                    (str(user_id), str(appeal_id)),
                )
            except sqlite3.IntegrityError:
                existing = conn.execute(
                    """
                    SELECT id, status FROM telegram_appeals
                    WHERE telegram_user_id = ? AND status = 'open'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                if existing is None:
                    raise TelegramRegistryError("appeal could not be stored")
                return AppealResult(appeal_id=int(existing[0]), created=False, status=str(existing[1]))
        return result

    def list_appeals(self, *, status: str = "open", limit: int = 100) -> list[AppealAdminItem]:
        if status not in {"open", "handled", "rejected", "all"}:
            raise TelegramRegistryError("appeal status is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TelegramRegistryError("limit must be an integer from 1 to 200")
        where = "" if status == "all" else "WHERE a.status = ?"
        params: tuple[Any, ...] = (status, limit) if status != "all" else (limit,)
        with connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.telegram_user_id, a.customer_id, c.email_display, a.body, a.status,
                       a.row_version, a.created_at, a.updated_at
                FROM telegram_appeals AS a
                JOIN customers AS c ON c.id = a.customer_id
                """
                + where
                + " ORDER BY a.created_at DESC, a.id DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            AppealAdminItem(
                appeal_id=int(row[0]), telegram_user_id=int(row[1]), customer_id=int(row[2]),
                email_display=str(row[3]), body=str(row[4]), status=str(row[5]), row_version=int(row[6]),
                created_at=str(row[7]), updated_at=str(row[8]),
            )
            for row in rows
        ]

    def resolve_appeal(
        self,
        *,
        appeal_id: int,
        expected_row_version: int,
        status: str,
        idempotency_key: str,
        resolved_by: str,
    ) -> AppealResolutionResult:
        normalized_id = _positive_int(appeal_id, "appeal_id")
        expected_version = _positive_int(expected_row_version, "expected_row_version")
        if status not in {"handled", "rejected"}:
            raise TelegramRegistryError("appeal resolution status is invalid")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(resolved_by, "resolved_by")
        digest = _payload_digest({"appeal_id": normalized_id, "expected_row_version": expected_version, "status": status})
        scope = "resolve_appeal"
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts WHERE scope = ? AND idempotency_key = ?",
                (scope, key),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return AppealResolutionResult(**json.loads(str(receipt[1])))
            row = conn.execute(
                "SELECT row_version, status FROM telegram_appeals WHERE id = ?", (normalized_id,)
            ).fetchone()
            if row is None:
                raise TelegramRegistryError("appeal was not found")
            if int(row[0]) != expected_version or str(row[1]) != "open":
                raise VersionConflictError("appeal was updated by another administrator")
            update = conn.execute(
                """
                UPDATE telegram_appeals
                SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'open' AND row_version = ?
                """,
                (status, normalized_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("appeal was updated by another administrator")
            result = AppealResolutionResult(normalized_id, status, expected_version + 1)
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('appeal_resolved', 'admin', ?, 'telegram_appeal', ?, ?)
                """,
                (actor, str(normalized_id), digest),
            )
        return result

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

    def list_pending_applications(self) -> list[PendingApplication]:
        """Return the review queue without treating display metadata as identity."""

        with connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT i.telegram_user_id, i.chat_id, i.username, i.first_name, i.last_name,
                       i.application_attempt, i.request_code, i.row_version, i.requested_at,
                       a.introduction_text
                FROM telegram_identities AS i
                JOIN telegram_applications AS a
                  ON a.telegram_user_id = i.telegram_user_id
                 AND a.application_attempt = i.application_attempt
                WHERE i.access_status = 'pending' AND a.status = 'pending'
                ORDER BY i.requested_at ASC, i.telegram_user_id ASC
                """
            ).fetchall()
            canonical_values = {
                str(row[0])
                for row in conn.execute(
                    "SELECT email_canonical FROM customers WHERE deleted_at IS NULL"
                ).fetchall()
            }
        result: list[PendingApplication] = []
        for row in rows:
            suggestion, source = _suggested_email(
                telegram_user_id=int(row[0]),
                username=str(row[2]) if row[2] is not None else None,
                first_name=str(row[3]) if row[3] is not None else None,
                last_name=str(row[4]) if row[4] is not None else None,
                canonical_exists=canonical_values.__contains__,
            )
            # Keep one queue response internally collision-free as well. The
            # values are suggestions only; final uniqueness is rechecked in
            # the approval transaction.
            canonical_values.add(canonicalize_email(suggestion))
            result.append(PendingApplication(
                telegram_user_id=int(row[0]),
                chat_id=int(row[1]),
                username=str(row[2]) if row[2] is not None else None,
                first_name=str(row[3]) if row[3] is not None else None,
                last_name=str(row[4]) if row[4] is not None else None,
                application_attempt=int(row[5]),
                request_code=str(row[6]),
                row_version=int(row[7]),
                requested_at=str(row[8]) if row[8] is not None else None,
                introduction_text=str(row[9]) if row[9] is not None else None,
                suggested_email=suggestion,
                suggested_email_source=source,
            ))
        return result

    def get_pending_application(self, telegram_user_id: int) -> PendingApplication:
        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        applications = [item for item in self.list_pending_applications() if item.telegram_user_id == user_id]
        if not applications:
            raise TelegramRegistryError("pending application was not found")
        return applications[0]

    def approve_new_application(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        email_display: str | None,
        idempotency_key: str,
        approved_by: str,
    ) -> ApprovalResult:
        """Approve a pending person and atomically queue, but never run, provisioning.

        The policy values and generated remote identifiers are persisted with
        each attempt. A future worker may therefore safely reconcile before
        touching a node, even if a node policy changes after approval.
        """

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        expected_version = _positive_int(expected_identity_version, "expected_identity_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(approved_by, "approved_by")
        selected_email = email_display.strip() if isinstance(email_display, str) else ""
        payload = {
            "telegram_user_id": user_id,
            "expected_identity_version": expected_version,
            "email_display": selected_email,
        }
        digest = _payload_digest(payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                """
                SELECT payload_digest, result_json FROM telegram_command_receipts
                WHERE scope = 'approve_new' AND idempotency_key = ?
                """,
                (key,),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                result = json.loads(str(receipt[1]))
                result["target_node_ids"] = tuple(result["target_node_ids"])
                return ApprovalResult(**result)

            identity = conn.execute(
                """
                SELECT telegram_user_id, username, first_name, last_name, access_status,
                       application_attempt, row_version, customer_id
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if identity is None or str(identity[4]) != "pending":
                raise VersionConflictError("application is no longer pending")
            if int(identity[6]) != expected_version:
                raise VersionConflictError("application was updated by another administrator")
            if identity[7] is not None:
                raise ApprovalUnavailableError("pending application is already bound to a customer")

            application = conn.execute(
                """
                SELECT status FROM telegram_applications
                WHERE telegram_user_id = ? AND application_attempt = ?
                """,
                (user_id, int(identity[5])),
            ).fetchone()
            if application is None or str(application[0]) != "pending":
                raise VersionConflictError("application attempt is no longer pending")

            def canonical_exists(value: str) -> bool:
                return conn.execute(
                    "SELECT 1 FROM customers WHERE email_canonical = ? AND deleted_at IS NULL", (value,)
                ).fetchone() is not None

            suggestion, suggestion_source = _suggested_email(
                telegram_user_id=user_id,
                username=str(identity[1]) if identity[1] is not None else None,
                first_name=str(identity[2]) if identity[2] is not None else None,
                last_name=str(identity[3]) if identity[3] is not None else None,
                canonical_exists=canonical_exists,
            )
            chosen = _validate_email_choice(selected_email) if selected_email else suggestion
            source = "admin" if selected_email else suggestion_source
            canonical = canonicalize_email(chosen)
            if canonical_exists(canonical):
                raise ApprovalUnavailableError("customer email is already in use")

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

            for _ in range(20):
                public_code = secrets.token_urlsafe(9)
                if conn.execute("SELECT 1 FROM customers WHERE public_code = ?", (public_code,)).fetchone() is None:
                    break
            else:
                raise ApprovalUnavailableError("unable to allocate a customer code")
            try:
                customer = conn.execute(
                    """
                    INSERT INTO customers
                        (email_display, email_canonical, origin, public_code, email_source)
                    VALUES (?, ?, 'telegram', ?, ?)
                    """,
                    (chosen, canonical, public_code, source),
                )
            except sqlite3.IntegrityError as exc:
                raise ApprovalUnavailableError("customer email is already in use") from exc
            customer_id = int(customer.lastrowid)
            snapshot = [
                {
                    "node_id": int(row[0]), "total_bytes": int(row[1]),
                    "validity_days": int(row[2]), "client_enabled": bool(row[3]),
                    "policy_version": int(row[4]), "inbound_id": BOT_INBOUND_ID,
                    "flow": BOT_CLIENT_FLOW,
                }
                for row in policies
            ]
            snapshot_digest = _payload_digest({"customer_id": customer_id, "email": canonical, "targets": snapshot})
            job = conn.execute(
                """
                INSERT INTO telegram_provisioning_jobs
                    (customer_id, trigger, idempotency_key, policy_snapshot_digest, created_by)
                VALUES (?, 'approve_new', ?, ?, ?)
                """,
                (customer_id, f"approve-new:{user_id}:{int(identity[5])}", snapshot_digest, actor),
            )
            job_id = int(job.lastrowid)
            for policy in policies:
                desired_expiry_time = (
                    int(datetime.now(timezone.utc).timestamp() * 1000)
                    + int(policy[2]) * 24 * 60 * 60 * 1000
                    if int(policy[2]) > 0
                    else 0
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
                        job_id, int(policy[0]), BOT_INBOUND_ID, str(uuid.uuid4()), str(uuid.uuid4()),
                        BOT_CLIENT_FLOW, int(policy[1]), int(policy[2]), desired_expiry_time,
                        int(bool(policy[3])), int(policy[4]),
                    ),
                )
            identity_update = conn.execute(
                """
                UPDATE telegram_identities
                SET customer_id = ?, access_status = 'approved', approved_at = CURRENT_TIMESTAMP,
                    approved_by = ?, decision_reason = NULL, updated_at = CURRENT_TIMESTAMP,
                    row_version = row_version + 1
                WHERE telegram_user_id = ? AND access_status = 'pending' AND row_version = ?
                """,
                (customer_id, actor, user_id, expected_version),
            )
            if identity_update.rowcount != 1:
                raise VersionConflictError("application was updated by another administrator")
            conn.execute(
                """
                UPDATE telegram_applications SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND application_attempt = ? AND status = 'pending'
                """,
                (user_id, int(identity[5])),
            )
            conn.execute(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('user_provisioning_queued', ?, ?)
                """,
                (str(user_id), f"user:provisioning-queued:{user_id}:{int(identity[5])}"),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('request_approved', 'admin', ?, 'telegram_identity', ?, ?)
                """,
                (actor, str(user_id), _payload_digest({"customer_id": customer_id, "job_id": job_id, "target_node_ids": [item["node_id"] for item in snapshot]})),
            )
            result = ApprovalResult(
                telegram_user_id=user_id,
                customer_id=customer_id,
                job_id=job_id,
                email_display=chosen,
                email_source=source,
                target_node_ids=tuple(item["node_id"] for item in snapshot),
                identity_row_version=expected_version + 1,
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES ('approve_new', ?, ?, ?)
                """,
                (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
        return result

    def approve_existing_application(
        self,
        *,
        telegram_user_id: int,
        customer_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        approved_by: str,
    ) -> ExistingApprovalResult:
        """Link only a locally known customer with confirmed exact bindings.

        This command intentionally accepts a local `customer_id`, not a free
        email string. Discovery/import is a separate reviewed workflow, so a
        guessed or similarly named remote client can never be claimed here.
        """

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        local_customer_id = _positive_int(customer_id, "customer_id")
        expected_version = _positive_int(expected_identity_version, "expected_identity_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(approved_by, "approved_by")
        payload = {
            "telegram_user_id": user_id,
            "customer_id": local_customer_id,
            "expected_identity_version": expected_version,
        }
        digest = _payload_digest(payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = 'approve_existing' AND idempotency_key = ?",
                (key,),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return ExistingApprovalResult(**json.loads(str(receipt[1])))
            identity = conn.execute(
                """
                SELECT access_status, row_version, customer_id, application_attempt
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if identity is None or str(identity[0]) != "pending" or identity[2] is not None:
                raise VersionConflictError("application is no longer eligible for an existing customer link")
            if int(identity[1]) != expected_version:
                raise VersionConflictError("application was updated by another administrator")
            application = conn.execute(
                "SELECT status FROM telegram_applications WHERE telegram_user_id = ? AND application_attempt = ?",
                (user_id, int(identity[3])),
            ).fetchone()
            if application is None or str(application[0]) != "pending":
                raise VersionConflictError("application attempt is no longer pending")
            customer = conn.execute(
                """
                SELECT email_display, email_canonical, status FROM customers
                WHERE id = ? AND deleted_at IS NULL
                """,
                (local_customer_id,),
            ).fetchone()
            if customer is None or str(customer[2]) not in {"active", "suspended", "suspend_partial", "resume_partial"}:
                raise ApprovalUnavailableError("customer is not available for Telegram linking")
            linked_identity = conn.execute(
                "SELECT telegram_user_id FROM telegram_identities WHERE customer_id = ?",
                (local_customer_id,),
            ).fetchone()
            if linked_identity is not None:
                raise ApprovalUnavailableError("customer is already linked to another Telegram identity")
            bindings = conn.execute(
                """
                SELECT remote_email FROM customer_node_bindings
                WHERE customer_id = ? AND management_state = 'confirmed'
                """,
                (local_customer_id,),
            ).fetchall()
            if not bindings or any(canonicalize_email(str(binding[0])) != str(customer[1]) for binding in bindings):
                raise ApprovalUnavailableError("customer has no confirmed exact node binding")
            update = conn.execute(
                """
                UPDATE telegram_identities
                SET customer_id = ?, access_status = 'approved', approved_at = CURRENT_TIMESTAMP,
                    approved_by = ?, decision_reason = NULL, updated_at = CURRENT_TIMESTAMP,
                    row_version = row_version + 1
                WHERE telegram_user_id = ? AND access_status = 'pending' AND row_version = ?
                """,
                (local_customer_id, actor, user_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("application was updated by another administrator")
            conn.execute(
                """
                UPDATE telegram_applications SET status = 'approved', updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND application_attempt = ? AND status = 'pending'
                """,
                (user_id, int(identity[3])),
            )
            conn.execute(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('user_existing_access_approved', ?, ?)
                """,
                (str(user_id), f"user:existing-access-approved:{user_id}:{int(identity[3])}"),
            )
            result = ExistingApprovalResult(
                telegram_user_id=user_id,
                customer_id=local_customer_id,
                email_display=str(customer[0]),
                confirmed_binding_count=len(bindings),
                identity_row_version=expected_version + 1,
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('request_approved_existing', 'admin', ?, 'telegram_identity', ?, ?)
                """,
                (actor, str(user_id), _payload_digest({"customer_id": local_customer_id, "binding_count": len(bindings)})),
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES ('approve_existing', ?, ?, ?)
                """,
                (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
        return result

    def reject_application(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        rejected_by: str,
        reason: str | None = None,
    ) -> TelegramIdentity:
        """Reject exactly the displayed pending attempt without deleting history."""

        return self._change_unbound_application_state(
            telegram_user_id=telegram_user_id,
            expected_identity_version=expected_identity_version,
            idempotency_key=idempotency_key,
            actor=rejected_by,
            action="reject",
            reason=reason,
        )

    def block_identity(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        blocked_by: str,
        reason: str | None = None,
    ) -> TelegramIdentity:
        """Block an applicant. Approved customers require lifecycle actions instead."""

        return self._change_unbound_application_state(
            telegram_user_id=telegram_user_id,
            expected_identity_version=expected_identity_version,
            idempotency_key=idempotency_key,
            actor=blocked_by,
            action="block",
            reason=reason,
        )

    def unblock_identity(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        unblocked_by: str,
    ) -> TelegramIdentity:
        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        expected_version = _positive_int(expected_identity_version, "expected_identity_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(unblocked_by, "unblocked_by")
        payload = {"telegram_user_id": user_id, "expected_identity_version": expected_version}
        digest = _payload_digest(payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = 'unblock_identity' AND idempotency_key = ?",
                (key,),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return TelegramIdentity(**json.loads(str(receipt[1])))
            row = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt, customer_id, row_version
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None or str(row[2]) != "blocked" or row[4] is not None:
                raise VersionConflictError("only an unbound blocked applicant can be unblocked")
            if int(row[5]) != expected_version:
                raise VersionConflictError("identity was updated by another administrator")
            update = conn.execute(
                """
                UPDATE telegram_identities
                SET access_status = 'eligible', unblocked_at = CURRENT_TIMESTAMP,
                    decision_reason = NULL, blocked_from_status = NULL,
                    updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                WHERE telegram_user_id = ? AND access_status = 'blocked' AND row_version = ?
                """,
                (user_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("identity was updated by another administrator")
            conn.execute(
                """
                UPDATE telegram_abuse_state
                SET window_started_at = NULL, last_event_at = NULL, consecutive_noop_count = 0,
                    soft_limited_until = NULL, row_version = row_version + 1
                WHERE telegram_user_id = ?
                """,
                (user_id,),
            )
            updated = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt, customer_id, row_version
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            assert updated is not None
            result = _identity_from_row(updated)
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id)
                VALUES ('identity_unblocked', 'admin', ?, 'telegram_identity', ?)
                """,
                (actor, str(user_id)),
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES ('unblock_identity', ?, ?, ?)
                """,
                (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
        return result

    def record_unapproved_noop(
        self,
        telegram_user_id: int,
        *,
        now: datetime | None = None,
        window_seconds: int = 600,
        soft_limit: int = 10,
        auto_block_at: int = 51,
    ) -> AbuseNoopResult:
        """Count an already-deduplicated no-op and auto-block only on the 51st.

        The caller must invoke this after `claim_update`; otherwise Telegram's
        delivery retries would be able to inflate the counter.
        """

        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        if min(window_seconds, soft_limit, auto_block_at) <= 0 or auto_block_at <= soft_limit:
            raise TelegramRegistryError("invalid abuse limits")
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
        with connect(self._db_path) as conn:
            identity = conn.execute(
                """
                SELECT access_status, row_version FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if identity is None:
                raise TelegramRegistryError("identity must be registered before abuse accounting")
            if str(identity[0]) not in {"eligible", "pending", "rejected"}:
                return AbuseNoopResult(auto_blocked=False, suppress_response=True, noop_count=0)
            state = conn.execute(
                """
                SELECT window_started_at, consecutive_noop_count, soft_limited_until, auto_block_count
                FROM telegram_abuse_state WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            window_start = None
            if state and state[0]:
                try:
                    window_start = datetime.fromisoformat(str(state[0]))
                except ValueError:
                    window_start = None
            in_window = window_start is not None and current - window_start < timedelta(seconds=window_seconds)
            count = (int(state[1]) if state and in_window else 0) + 1
            start = window_start if in_window else current
            existing_soft_until = None
            if state and state[2]:
                try:
                    existing_soft_until = datetime.fromisoformat(str(state[2]))
                except ValueError:
                    existing_soft_until = None
            suppress_response = bool(existing_soft_until and existing_soft_until > current)
            soft_until = existing_soft_until if suppress_response else None
            if count > soft_limit:
                soft_until = current + timedelta(seconds=60)
                suppress_response = True
            timestamp = current.isoformat(sep=" ")
            if state is None:
                conn.execute(
                    """
                    INSERT INTO telegram_abuse_state
                        (telegram_user_id, window_started_at, last_event_at, consecutive_noop_count,
                         soft_limited_until, last_reason_code)
                    VALUES (?, ?, ?, ?, ?, 'noop')
                    """,
                    (user_id, start.isoformat(sep=" "), timestamp, count, soft_until.isoformat(sep=" ") if soft_until else None),
                )
            else:
                conn.execute(
                    """
                    UPDATE telegram_abuse_state
                    SET window_started_at = ?, last_event_at = ?, consecutive_noop_count = ?,
                        soft_limited_until = ?, last_reason_code = 'noop', row_version = row_version + 1
                    WHERE telegram_user_id = ?
                    """,
                    (start.isoformat(sep=" "), timestamp, count, soft_until.isoformat(sep=" ") if soft_until else None, user_id),
                )
            if count < auto_block_at:
                return AbuseNoopResult(auto_blocked=False, suppress_response=suppress_response, noop_count=count)
            blocked = conn.execute(
                """
                UPDATE telegram_identities
                SET access_status = 'blocked', blocked_at = ?, blocked_from_status = ?,
                    decision_reason = 'auto_spam', updated_at = ?, row_version = row_version + 1
                WHERE telegram_user_id = ? AND access_status = ? AND row_version = ?
                """,
                (timestamp, str(identity[0]), timestamp, user_id, str(identity[0]), int(identity[1])),
            )
            if blocked.rowcount != 1:
                raise VersionConflictError("identity was updated during abuse accounting")
            block_number = (int(state[3]) if state else 0) + 1
            conn.execute(
                """
                UPDATE telegram_abuse_state
                SET auto_block_count = ?, last_auto_blocked_at = ?, last_reason_code = 'auto_spam',
                    soft_limited_until = NULL, row_version = row_version + 1
                WHERE telegram_user_id = ?
                """,
                (block_number, timestamp, user_id),
            )
            conn.execute(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('admin_identity_auto_blocked', ?, ?)
                """,
                (str(user_id), f"admin:auto-spam:{user_id}:{block_number}"),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('identity_auto_blocked', 'system', NULL, 'telegram_identity', ?, ?)
                """,
                (str(user_id), _payload_digest({"reason": "auto_spam", "count": count, "block_number": block_number})),
            )
        return AbuseNoopResult(auto_blocked=True, suppress_response=True, noop_count=count)

    def _change_unbound_application_state(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        actor: str,
        action: str,
        reason: str | None,
    ) -> TelegramIdentity:
        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        expected_version = _positive_int(expected_identity_version, "expected_identity_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        normalized_actor = _nonempty(actor, "actor")
        if action not in {"reject", "block"}:
            raise TelegramRegistryError("unsupported application state change")
        normalized_reason = reason.strip() if isinstance(reason, str) else None
        if normalized_reason and len(normalized_reason) > 300:
            raise TelegramRegistryError("reason is too long")
        payload = {
            "telegram_user_id": user_id,
            "expected_identity_version": expected_version,
            "reason": normalized_reason or "",
        }
        digest = _payload_digest(payload)
        scope = f"{action}_identity"
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = ? AND idempotency_key = ?",
                (scope, key),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return TelegramIdentity(**json.loads(str(receipt[1])))
            row = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt, customer_id, row_version
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            current_status = str(row[2]) if row is not None else ""
            allowed_statuses = {"pending"} if action == "reject" else {"eligible", "pending", "rejected"}
            if row is None or current_status not in allowed_statuses or row[4] is not None:
                raise VersionConflictError("identity cannot be changed in its current state")
            if int(row[5]) != expected_version:
                raise VersionConflictError("identity was updated by another administrator")
            next_status = "rejected" if action == "reject" else "blocked"
            update = conn.execute(
                """
                UPDATE telegram_identities
                SET access_status = ?, rejected_at = CASE WHEN ? = 'rejected' THEN CURRENT_TIMESTAMP ELSE rejected_at END,
                    blocked_at = CASE WHEN ? = 'blocked' THEN CURRENT_TIMESTAMP ELSE blocked_at END,
                    blocked_from_status = CASE WHEN ? = 'blocked' THEN ? ELSE NULL END,
                    decision_reason = ?, updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1
                WHERE telegram_user_id = ? AND access_status = ? AND row_version = ?
                """,
                (next_status, action, action, action, current_status, normalized_reason, user_id, current_status, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("identity was updated by another administrator")
            conn.execute(
                """
                UPDATE telegram_applications SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE telegram_user_id = ? AND application_attempt = ? AND status = 'pending'
                """,
                (next_status, user_id, int(row[3])),
            )
            updated = conn.execute(
                """
                SELECT telegram_user_id, chat_id, access_status, application_attempt, customer_id, row_version
                FROM telegram_identities WHERE telegram_user_id = ?
                """,
                (user_id,),
            ).fetchone()
            assert updated is not None
            result = _identity_from_row(updated)
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'telegram_identity', ?, ?)
                """,
                (f"application_{action}ed" if action == "reject" else "identity_blocked", normalized_actor, str(user_id), _payload_digest({"reason": normalized_reason or ""})),
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
        return result

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

    def list_provisioning_jobs(self, *, limit: int = 100) -> list[ProvisioningJobStatus]:
        """Admin projection for job state; deliberately excludes remote UUIDs/sub IDs."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TelegramRegistryError("limit must be an integer from 1 to 200")
        with connect(self._db_path) as conn:
            jobs = conn.execute(
                """
                SELECT j.id, j.customer_id, c.email_display, j.trigger, j.status, j.attempt_count,
                       j.row_version, j.created_at, j.finished_at
                FROM telegram_provisioning_jobs AS j
                JOIN customers AS c ON c.id = j.customer_id
                ORDER BY j.created_at DESC, j.id DESC LIMIT ?
                """,
                (limit,),
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
        ]

    def get_provisioning_job(self, job_id: int) -> ProvisioningJobStatus:
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

    def reschedule_provisioning_job(
        self,
        *,
        job_id: int,
        expected_job_version: int,
        idempotency_key: str,
        requested_by: str,
        action: str,
    ) -> ProvisioningRescheduleResult:
        """Queue a safe read-first retry/reconcile; it never calls a node inline."""

        normalized_job_id = _positive_int(job_id, "job_id")
        expected_version = _positive_int(expected_job_version, "expected_job_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(requested_by, "requested_by")
        if action not in {"retry", "reconcile"}:
            raise TelegramRegistryError("unsupported provisioning action")
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
            update = conn.execute(
                """
                UPDATE telegram_provisioning_jobs
                SET status = 'queued', next_attempt_at = NULL, finished_at = NULL,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND lease_until IS NULL
                """,
                (normalized_job_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("provisioning job was updated by another worker or administrator")
            result = ProvisioningRescheduleResult(
                job_id=normalized_job_id, status="queued", row_version=expected_version + 1
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'telegram_provisioning_job', ?, ?)
                """,
                (f"provisioning_{action}_queued", actor, str(normalized_job_id), digest),
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
        return result

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

    def queue_customer_node_add(
        self,
        *,
        customer_id: int,
        node_id: int,
        expected_customer_version: int,
        idempotency_key: str,
        created_by: str,
    ) -> NodeProvisioningQueueResult:
        """Queue one exact node add using the same reconcile-first worker as approval."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        local_node_id = _positive_int(node_id, "node_id")
        expected_version = _positive_int(expected_customer_version, "expected_customer_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(created_by, "created_by")
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
            digest = _payload_digest(payload)
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return NodeProvisioningQueueResult(**json.loads(str(receipt[1])))

            customer = conn.execute(
                "SELECT email_display, status, row_version FROM customers "
                "WHERE id = ? AND deleted_at IS NULL",
                (local_customer_id,),
            ).fetchone()
            if customer is None:
                raise TelegramRegistryError("customer was not found")
            if str(customer[1]) != "active":
                raise LifecycleUnavailableError("node can be added only to an active customer")
            if int(customer[2]) != expected_version:
                raise VersionConflictError("customer was updated by another operation")
            existing = conn.execute(
                "SELECT id FROM customer_node_bindings WHERE customer_id = ? AND node_id = ? AND inbound_id = 1",
                (local_customer_id, local_node_id),
            ).fetchone()
            if existing is not None:
                raise VersionConflictError("customer is already assigned to this node")
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
                raise LifecycleUnavailableError("customer is already being added to this node")
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
                raise NodePolicyUnavailableError("node is not eligible for Telegram provisioning")

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
                "inbound_id": BOT_INBOUND_ID,
                "flow": BOT_CLIENT_FLOW,
                "policy_version": int(policy[4]),
            }
            job = conn.execute(
                """
                INSERT INTO telegram_provisioning_jobs
                    (customer_id, trigger, idempotency_key, policy_snapshot_digest, created_by)
                VALUES (?, 'node_backfill', ?, ?, ?)
                """,
                (local_customer_id, f"node-add:{key}", _payload_digest(snapshot), actor),
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
                    job_id, local_node_id, BOT_INBOUND_ID, str(uuid.uuid4()), str(uuid.uuid4()),
                    BOT_CLIENT_FLOW, int(policy[1]), int(policy[2]), desired_expiry_time,
                    int(bool(policy[3])), int(policy[4]),
                ),
            )
            update = conn.execute(
                "UPDATE customers SET row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND row_version = ? AND deleted_at IS NULL",
                (local_customer_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("customer was updated by another operation")
            result = NodeProvisioningQueueResult(
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

    def list_customers(
        self,
        *,
        query: str = "",
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
        include_deleted: bool = False,
    ) -> CustomerPage:
        """Page local customers only; fleet discovery remains a separate safe workflow."""

        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise TelegramRegistryError("page must be a positive integer")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 200:
            raise TelegramRegistryError("page_size must be an integer from 1 to 200")
        allowed_statuses = {
            "active", "suspending", "suspended", "suspend_partial", "resuming", "resume_partial",
            "deleting", "delete_partial", "deleted", "conflict",
        }
        if status is not None and status not in allowed_statuses:
            raise TelegramRegistryError("customer status is invalid")
        if not isinstance(query, str) or len(query.strip()) > 128:
            raise TelegramRegistryError("query is invalid")
        filters: list[str] = []
        params: list[Any] = []
        if not include_deleted:
            filters.append("c.deleted_at IS NULL")
        if status is not None:
            filters.append("c.status = ?")
            params.append(status)
        if query.strip():
            like = f"%{query.strip().casefold()}%"
            filters.append(
                "(c.email_canonical LIKE ? OR EXISTS ("
                "SELECT 1 FROM telegram_identities AS ti WHERE ti.customer_id = c.id "
                "AND (CAST(ti.telegram_user_id AS TEXT) LIKE ? OR lower(COALESCE(ti.username, '')) LIKE ?)"
                "))"
            )
            params.extend([like, like, like])
        where = " WHERE " + " AND ".join(filters) if filters else ""
        base = (
            " FROM customers AS c "
            + where
        )
        with connect(self._db_path) as conn:
            total = int(conn.execute("SELECT COUNT(*)" + base, params).fetchone()[0])
            rows = conn.execute(
                """
                SELECT c.id, c.email_display, c.origin, c.status, c.row_version,
                       (SELECT telegram_user_id FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id ORDER BY ti.created_at LIMIT 1),
                       c.created_at, c.updated_at
                """
                + base
                + " ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
        return CustomerPage(
            items=tuple(
                CustomerListItem(
                    customer_id=int(row[0]), email_display=str(row[1]), origin=str(row[2]),
                    status=str(row[3]), row_version=int(row[4]),
                    telegram_user_id=int(row[5]) if row[5] is not None else None,
                    created_at=str(row[6]), updated_at=str(row[7]),
                )
                for row in rows
            ),
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_customer(self, customer_id: int) -> CustomerListItem:
        normalized_customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT c.id, c.email_display, c.origin, c.status, c.row_version,
                       (SELECT telegram_user_id FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id ORDER BY ti.created_at LIMIT 1),
                       c.created_at, c.updated_at
                FROM customers AS c
                WHERE c.id = ?
                """,
                (normalized_customer_id,),
            ).fetchone()
        if row is None:
            raise TelegramRegistryError("customer was not found")
        return CustomerListItem(
            customer_id=int(row[0]), email_display=str(row[1]), origin=str(row[2]), status=str(row[3]),
            row_version=int(row[4]), telegram_user_id=int(row[5]) if row[5] is not None else None,
            created_at=str(row[6]), updated_at=str(row[7]),
        )

    @staticmethod
    def _lifecycle_operation_type(value: str) -> str:
        if value not in {"suspend", "resume", "delete"}:
            raise TelegramRegistryError("unsupported customer lifecycle operation")
        return value

    def _customer_operation_snapshot(
        self,
        conn: sqlite3.Connection,
        *,
        customer_id: int,
        operation_type: str,
    ) -> tuple[CustomerOperationPreview, tuple[dict[str, Any], ...]]:
        """Build an exact, private target snapshot without doing remote I/O."""

        customer = conn.execute(
            "SELECT status, deleted_at, row_version FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        if customer is None:
            raise TelegramRegistryError("customer was not found")
        current_status, deleted_at, row_version = str(customer[0]), customer[1], int(customer[2])
        if deleted_at is not None or current_status == "deleted":
            raise LifecycleUnavailableError("deleted customer cannot be changed")
        allowed_states = {
            "suspend": {"active", "resume_partial"},
            "resume": {"suspended", "suspend_partial", "resume_partial"},
            "delete": {"active", "suspended", "suspend_partial", "resume_partial"},
        }
        if current_status not in allowed_states[operation_type]:
            raise LifecycleUnavailableError("customer is busy or not in a compatible lifecycle state")

        rows = conn.execute(
            """
            SELECT b.id, b.node_id, n.name, b.inbound_id, b.remote_client_id, b.remote_sub_id,
                   b.remote_email, b.management_state, b.desired_enabled, b.suspended_by_operation_id
            FROM customer_node_bindings AS b
            JOIN nodes AS n ON n.id = b.node_id
            WHERE b.customer_id = ?
            ORDER BY b.node_id, b.id
            """,
            (customer_id,),
        ).fetchall()

        targets: list[CustomerOperationTarget] = []
        private_targets: list[dict[str, Any]] = []
        blocked_binding_ids: list[int] = []
        for row in rows:
            binding_id, node_id, node_name, inbound_id = int(row[0]), int(row[1]), str(row[2]), int(row[3])
            remote_client_id = str(row[4]) if row[4] is not None else ""
            remote_sub_id = str(row[5]) if row[5] is not None else ""
            remote_email = str(row[6])
            management_state = str(row[7])
            suspended_by_operation_id = int(row[9]) if row[9] is not None else None

            if operation_type == "resume" and suspended_by_operation_id is None:
                continue
            if management_state != "confirmed" or not remote_client_id:
                blocked_binding_ids.append(binding_id)
                continue

            previous_enabled: bool | None = None
            if operation_type == "resume":
                previous = conn.execute(
                    """
                    SELECT a.previous_enabled
                    FROM telegram_customer_operation_attempts AS a
                    JOIN telegram_customer_operations AS o ON o.id = a.operation_id
                    WHERE a.binding_id = ? AND o.operation_type = 'suspend'
                      AND a.action = 'set_enabled_false' AND a.status = 'succeeded'
                    ORDER BY a.id DESC LIMIT 1
                    """,
                    (binding_id,),
                ).fetchone()
                if previous is None or previous[0] is None:
                    blocked_binding_ids.append(binding_id)
                    continue
                previous_enabled = bool(previous[0])

            action = {
                "suspend": "set_enabled_false",
                "resume": "restore_previous_enabled",
                "delete": "delete_client",
            }[operation_type]
            targets.append(
                CustomerOperationTarget(
                    binding_id=binding_id,
                    node_id=node_id,
                    node_name=node_name,
                    inbound_id=inbound_id,
                    action=action,
                    previous_enabled=previous_enabled,
                )
            )
            private_targets.append(
                {
                    "binding_id": binding_id,
                    "node_id": node_id,
                    "inbound_id": inbound_id,
                    "remote_client_id": remote_client_id,
                    "remote_sub_id": remote_sub_id,
                    "remote_email": remote_email,
                    "action": action,
                    "previous_enabled": previous_enabled,
                }
            )

        snapshot = {
            "customer_id": customer_id,
            "operation_type": operation_type,
            "expected_customer_version": row_version,
            "targets": private_targets,
            "blocked_binding_ids": blocked_binding_ids,
        }
        return (
            CustomerOperationPreview(
                customer_id=customer_id,
                operation_type=operation_type,
                expected_customer_version=row_version,
                target_snapshot_digest=_payload_digest(snapshot),
                targets=tuple(targets),
                blocked_binding_ids=tuple(blocked_binding_ids),
            ),
            tuple(private_targets),
        )

    def preview_customer_operation(
        self, *, customer_id: int, operation_type: str
    ) -> CustomerOperationPreview:
        normalized_customer_id = _positive_int(customer_id, "customer_id")
        normalized_operation = self._lifecycle_operation_type(operation_type)
        with connect(self._db_path) as conn:
            preview, _ = self._customer_operation_snapshot(
                conn, customer_id=normalized_customer_id, operation_type=normalized_operation
            )
        return preview

    @staticmethod
    def _node_operation_type(value: str) -> str:
        if value not in {"suspend_node", "resume_node"}:
            raise TelegramRegistryError("unsupported customer node operation")
        return value

    def _customer_node_operation_snapshot(
        self,
        conn: sqlite3.Connection,
        *,
        customer_id: int,
        node_id: int,
        operation_type: str,
    ) -> tuple[CustomerOperationPreview, dict[str, Any]]:
        customer = conn.execute(
            "SELECT status, row_version FROM customers WHERE id = ? AND deleted_at IS NULL",
            (customer_id,),
        ).fetchone()
        if customer is None:
            raise TelegramRegistryError("customer was not found")
        if str(customer[0]) != "active":
            raise LifecycleUnavailableError("node operation requires an active customer")
        binding = conn.execute(
            """
            SELECT b.id, b.node_id, n.name, b.inbound_id, b.remote_client_id,
                   b.remote_sub_id, b.remote_email, b.management_state,
                   b.desired_enabled, b.suspended_by_operation_id
            FROM customer_node_bindings AS b
            JOIN nodes AS n ON n.id = b.node_id
            WHERE b.customer_id = ? AND b.node_id = ? AND b.inbound_id = 1
            """,
            (customer_id, node_id),
        ).fetchone()
        if binding is None:
            raise LifecycleUnavailableError("customer is not assigned to this node")
        if str(binding[7]) != "confirmed" or not binding[4]:
            raise LifecycleUnavailableError("node binding has no exact confirmed remote target")
        if operation_type == "suspend_node":
            if not bool(binding[8]):
                raise LifecycleUnavailableError("customer is already suspended on this node")
            action = "set_enabled_false"
            previous_enabled = None
        else:
            if bool(binding[8]) or binding[9] is None:
                raise LifecycleUnavailableError("customer is not suspended by a node operation")
            previous = conn.execute(
                """
                SELECT a.previous_enabled
                FROM telegram_customer_operation_attempts AS a
                JOIN telegram_customer_operations AS o ON o.id = a.operation_id
                WHERE a.binding_id = ? AND o.operation_type = 'suspend_node'
                  AND a.action = 'set_enabled_false' AND a.status = 'succeeded'
                ORDER BY a.id DESC LIMIT 1
                """,
                (int(binding[0]),),
            ).fetchone()
            if previous is None or previous[0] is None:
                raise LifecycleUnavailableError("suspend snapshot is unavailable")
            action = "restore_previous_enabled"
            previous_enabled = bool(previous[0])

        active_operation = conn.execute(
            """
            SELECT 1
            FROM telegram_customer_operations AS o
            JOIN telegram_customer_operation_attempts AS a ON a.operation_id = o.id
            WHERE o.customer_id = ? AND a.node_id = ?
              AND o.status IN ('queued', 'running', 'partial')
            LIMIT 1
            """,
            (customer_id, node_id),
        ).fetchone()
        if active_operation is not None:
            raise LifecycleUnavailableError("this node already has an active operation")

        target = {
            "binding_id": int(binding[0]),
            "node_id": int(binding[1]),
            "inbound_id": int(binding[3]),
            "remote_client_id": str(binding[4]),
            "remote_sub_id": str(binding[5] or ""),
            "remote_email": str(binding[6]),
            "action": action,
            "previous_enabled": previous_enabled,
        }
        snapshot = {
            "customer_id": customer_id,
            "node_id": node_id,
            "operation_type": operation_type,
            "expected_customer_version": int(customer[1]),
            "target": target,
        }
        preview = CustomerOperationPreview(
            customer_id=customer_id,
            operation_type=operation_type,
            expected_customer_version=int(customer[1]),
            target_snapshot_digest=_payload_digest(snapshot),
            targets=(CustomerOperationTarget(
                binding_id=int(binding[0]), node_id=int(binding[1]), node_name=str(binding[2]),
                inbound_id=int(binding[3]), action=action, previous_enabled=previous_enabled,
            ),),
            blocked_binding_ids=(),
        )
        return preview, target

    def preview_customer_node_operation(
        self, *, customer_id: int, node_id: int, operation_type: str
    ) -> CustomerOperationPreview:
        normalized_customer_id = _positive_int(customer_id, "customer_id")
        normalized_node_id = _positive_int(node_id, "node_id")
        normalized_operation = self._node_operation_type(operation_type)
        with connect(self._db_path) as conn:
            preview, _ = self._customer_node_operation_snapshot(
                conn, customer_id=normalized_customer_id, node_id=normalized_node_id,
                operation_type=normalized_operation,
            )
        return preview

    def queue_customer_node_operation(
        self,
        *,
        customer_id: int,
        node_id: int,
        operation_type: str,
        expected_customer_version: int,
        target_snapshot_digest: str,
        idempotency_key: str,
        created_by: str,
    ) -> CustomerOperationQueueResult:
        normalized_customer_id = _positive_int(customer_id, "customer_id")
        normalized_node_id = _positive_int(node_id, "node_id")
        normalized_operation = self._node_operation_type(operation_type)
        expected_version = _positive_int(expected_customer_version, "expected_customer_version")
        expected_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(created_by, "created_by")
        payload = {
            "customer_id": normalized_customer_id,
            "node_id": normalized_node_id,
            "operation_type": normalized_operation,
            "expected_customer_version": expected_version,
            "target_snapshot_digest": expected_digest,
        }
        digest = _payload_digest(payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = 'customer_node_operation' AND idempotency_key = ?",
                (key,),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return CustomerOperationQueueResult(**json.loads(str(receipt[1])))
            preview, target = self._customer_node_operation_snapshot(
                conn, customer_id=normalized_customer_id, node_id=normalized_node_id,
                operation_type=normalized_operation,
            )
            if preview.expected_customer_version != expected_version or preview.target_snapshot_digest != expected_digest:
                raise VersionConflictError("node operation preview is stale")
            update = conn.execute(
                "UPDATE customers SET row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND row_version = ? AND status = 'active' AND deleted_at IS NULL",
                (normalized_customer_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("customer was updated by another operation")
            operation = conn.execute(
                """
                INSERT INTO telegram_customer_operations
                    (customer_id, operation_type, status, target_snapshot_digest,
                     expected_customer_version, idempotency_key, created_by)
                VALUES (?, ?, 'queued', ?, ?, ?, ?)
                """,
                (normalized_customer_id, normalized_operation, expected_digest, expected_version, key, actor),
            )
            operation_id = int(operation.lastrowid)
            conn.execute(
                """
                INSERT INTO telegram_customer_operation_attempts
                    (operation_id, binding_id, node_id, inbound_id, remote_client_id,
                     remote_sub_id, remote_email, action, previous_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, target["binding_id"], target["node_id"], target["inbound_id"],
                    target["remote_client_id"], target["remote_sub_id"], target["remote_email"],
                    target["action"], int(target["previous_enabled"]) if target["previous_enabled"] is not None else None,
                ),
            )
            result = CustomerOperationQueueResult(
                operation_id=operation_id, customer_id=normalized_customer_id,
                operation_type=normalized_operation, status="queued", row_version=1,
            )
            conn.execute(
                "INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json) "
                "VALUES ('customer_node_operation', ?, ?, ?)",
                (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
                """,
                (f"customer_{normalized_operation}_queued", actor, str(operation_id), digest),
            )
        return result

    def _get_customer_operation_from_conn(
        self, conn: sqlite3.Connection, operation_id: int
    ) -> CustomerOperationStatus:
        operation = conn.execute(
            """
            SELECT o.id, o.customer_id, c.email_display, o.operation_type, o.status, o.row_version,
                   o.attempt_count, o.target_snapshot_digest, o.created_at, o.finished_at
            FROM telegram_customer_operations AS o
            JOIN customers AS c ON c.id = o.customer_id
            WHERE o.id = ?
            """,
            (operation_id,),
        ).fetchone()
        if operation is None:
            raise TelegramRegistryError("customer operation was not found")
        attempts = conn.execute(
            """
            SELECT a.binding_id, a.node_id, n.name, a.action, a.status, a.error_code,
                   a.error_summary, a.attempt_count
            FROM telegram_customer_operation_attempts AS a
            JOIN nodes AS n ON n.id = a.node_id
            WHERE a.operation_id = ?
            ORDER BY a.node_id, a.id
            """,
            (operation_id,),
        ).fetchall()
        return CustomerOperationStatus(
            operation_id=int(operation[0]),
            customer_id=int(operation[1]),
            customer_email=str(operation[2]),
            operation_type=str(operation[3]),
            status=str(operation[4]),
            row_version=int(operation[5]),
            attempt_count=int(operation[6]),
            target_snapshot_digest=str(operation[7]),
            created_at=str(operation[8]),
            finished_at=str(operation[9]) if operation[9] is not None else None,
            attempts=tuple(
                CustomerOperationAttemptStatus(
                    binding_id=int(row[0]), node_id=int(row[1]), node_name=str(row[2]),
                    action=str(row[3]), status=str(row[4]),
                    error_code=str(row[5]) if row[5] is not None else None,
                    error_summary=str(row[6]) if row[6] is not None else None,
                    attempt_count=int(row[7]),
                )
                for row in attempts
            ),
        )

    def queue_customer_operation(
        self,
        *,
        customer_id: int,
        operation_type: str,
        expected_customer_version: int,
        target_snapshot_digest: str,
        idempotency_key: str,
        created_by: str,
    ) -> CustomerOperationQueueResult:
        """Queue a lifecycle operation after proving its preview is still current.

        This transaction intentionally does not touch a node. A worker must later
        claim these immutable attempts, read the remote client, and reconcile
        before it writes anything.
        """

        normalized_customer_id = _positive_int(customer_id, "customer_id")
        normalized_operation = self._lifecycle_operation_type(operation_type)
        expected_version = _positive_int(expected_customer_version, "expected_customer_version")
        expected_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(created_by, "created_by")
        command_payload = {
            "customer_id": normalized_customer_id,
            "operation_type": normalized_operation,
            "expected_customer_version": expected_version,
            "target_snapshot_digest": expected_digest,
        }
        command_digest = _payload_digest(command_payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = 'customer_lifecycle' AND idempotency_key = ?",
                (key,),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != command_digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return CustomerOperationQueueResult(**json.loads(str(receipt[1])))

            preview, private_targets = self._customer_operation_snapshot(
                conn, customer_id=normalized_customer_id, operation_type=normalized_operation
            )
            if preview.expected_customer_version != expected_version:
                raise VersionConflictError("customer was updated by another operation")
            if preview.target_snapshot_digest != expected_digest:
                raise VersionConflictError("lifecycle target preview is stale")
            if preview.blocked_binding_ids:
                raise LifecycleUnavailableError("customer has bindings without an exact confirmed remote target")

            queued_status = "queued" if private_targets else "succeeded"
            next_customer_status = {
                "suspend": "suspending" if private_targets else "suspended",
                "resume": "resuming" if private_targets else "active",
                "delete": "deleting" if private_targets else "deleted",
            }[normalized_operation]
            if normalized_operation == "delete" and not private_targets:
                update = conn.execute(
                    """
                    UPDATE customers
                    SET status = ?, deleted_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND row_version = ? AND deleted_at IS NULL
                    """,
                    (next_customer_status, normalized_customer_id, expected_version),
                )
            else:
                update = conn.execute(
                    """
                    UPDATE customers
                    SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND row_version = ? AND deleted_at IS NULL
                    """,
                    (next_customer_status, normalized_customer_id, expected_version),
                )
            if update.rowcount != 1:
                raise VersionConflictError("customer was updated by another operation")

            cursor = conn.execute(
                """
                INSERT INTO telegram_customer_operations
                    (customer_id, operation_type, status, target_snapshot_digest,
                     expected_customer_version, idempotency_key, created_by, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'succeeded' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (
                    normalized_customer_id, normalized_operation, queued_status,
                    preview.target_snapshot_digest, expected_version, key, actor, queued_status,
                ),
            )
            operation_id = int(cursor.lastrowid)
            for target in private_targets:
                conn.execute(
                    """
                    INSERT INTO telegram_customer_operation_attempts
                        (operation_id, binding_id, node_id, inbound_id, remote_client_id, remote_sub_id,
                         remote_email, action, previous_enabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id, target["binding_id"], target["node_id"], target["inbound_id"],
                        target["remote_client_id"], target["remote_sub_id"], target["remote_email"], target["action"],
                        int(target["previous_enabled"]) if target["previous_enabled"] is not None else None,
                    ),
                )
            result = CustomerOperationQueueResult(
                operation_id=operation_id,
                customer_id=normalized_customer_id,
                operation_type=normalized_operation,
                status=queued_status,
                row_version=1,
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES ('customer_lifecycle', ?, ?, ?)
                """,
                (key, command_digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
                """,
                (f"customer_{normalized_operation}_queued", actor, str(operation_id), command_digest),
            )
        return result

    def get_customer_operation(self, operation_id: int) -> CustomerOperationStatus:
        normalized_operation_id = _positive_int(operation_id, "operation_id")
        with connect(self._db_path) as conn:
            return self._get_customer_operation_from_conn(conn, normalized_operation_id)

    def list_customer_operations(
        self, *, customer_id: int, limit: int = 100
    ) -> list[CustomerOperationStatus]:
        normalized_customer_id = _positive_int(customer_id, "customer_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TelegramRegistryError("limit must be an integer from 1 to 200")
        with connect(self._db_path) as conn:
            operation_ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM telegram_customer_operations WHERE customer_id = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (normalized_customer_id, limit),
                ).fetchall()
            ]
            return [self._get_customer_operation_from_conn(conn, operation_id) for operation_id in operation_ids]

    def reschedule_customer_operation(
        self,
        *,
        operation_id: int,
        expected_operation_version: int,
        idempotency_key: str,
        requested_by: str,
        action: str,
    ) -> CustomerOperationRescheduleResult:
        """Queue a read-first lifecycle retry; conflict targets require manual repair."""

        normalized_operation_id = _positive_int(operation_id, "operation_id")
        expected_version = _positive_int(expected_operation_version, "expected_operation_version")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(requested_by, "requested_by")
        if action not in {"retry", "reconcile"}:
            raise TelegramRegistryError("unsupported customer operation action")
        payload = {
            "operation_id": normalized_operation_id,
            "expected_operation_version": expected_version,
        }
        digest = _payload_digest(payload)
        scope = f"customer_operation_{action}"
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = ? AND idempotency_key = ?",
                (scope, key),
            ).fetchone()
            if receipt:
                if str(receipt[0]) != digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return CustomerOperationRescheduleResult(**json.loads(str(receipt[1])))
            operation = conn.execute(
                "SELECT status, row_version, lease_until FROM telegram_customer_operations WHERE id = ?",
                (normalized_operation_id,),
            ).fetchone()
            if operation is None:
                raise TelegramRegistryError("customer operation was not found")
            if int(operation[1]) != expected_version:
                raise VersionConflictError("customer operation was updated by another worker or administrator")
            if str(operation[0]) not in {"partial", "failed"} or operation[2] is not None:
                raise VersionConflictError("customer operation cannot be rescheduled in its current state")
            changed = conn.execute(
                """
                UPDATE telegram_customer_operation_attempts
                SET status = 'pending', error_code = NULL, error_summary = NULL, next_attempt_at = NULL,
                    finished_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE operation_id = ? AND status IN ('failed', 'blocked', 'ambiguous', 'missing')
                """,
                (normalized_operation_id,),
            )
            if changed.rowcount == 0:
                raise LifecycleUnavailableError("customer operation has no safe retryable attempts")
            update = conn.execute(
                """
                UPDATE telegram_customer_operations
                SET status = 'queued', next_attempt_at = NULL, finished_at = NULL,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND lease_until IS NULL
                """,
                (normalized_operation_id, expected_version),
            )
            if update.rowcount != 1:
                raise VersionConflictError("customer operation was updated by another worker or administrator")
            result = CustomerOperationRescheduleResult(
                operation_id=normalized_operation_id,
                status="queued",
                row_version=expected_version + 1,
            )
            conn.execute(
                """
                INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
                """,
                (f"customer_operation_{action}_queued", actor, str(normalized_operation_id), digest),
            )
        return result


def exact_node_ids(rows: Iterable[CustomerNodeMatrixRow]) -> set[int]:
    """Small helper for later preview commands; never infer IDs from labels."""

    return {row.node_id for row in rows}
