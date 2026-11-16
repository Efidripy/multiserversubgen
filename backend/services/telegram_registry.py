"""SQLite repository for the Telegram integration's local authority.

This module deliberately does not call Telegram or an x-ui node. It provides
small, transactional commands that later adapters can use after transport and
remote-capability checks have completed.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets  # noqa: F401
import sqlite3
import unicodedata
import uuid  # noqa: F401
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass  # noqa: F401
from typing import Any, Callable, Iterable

from services import telegram_registry_notices as _telegram_registry_notices
from services import telegram_registry_support as _telegram_registry_support
from services import telegram_registry_updates as _telegram_registry_updates
from services import telegram_registry_traffic as _telegram_registry_traffic
from services import telegram_registry_drafts as _telegram_registry_drafts
from services import telegram_registry_devices as _telegram_registry_devices
from services import telegram_registry_provisioning as _telegram_registry_provisioning
from services import telegram_registry_nodeops as _telegram_registry_nodeops
from services import telegram_registry_drift as _telegram_registry_drift
from services import telegram_registry_registration as _telegram_registry_registration
from services import telegram_registry_customerops as _telegram_registry_customerops
from services import telegram_registry_identity as _telegram_registry_identity
from services.db_bootstrap import connect
from services.telegram_access import SUSPENDED_STATUSES


BOT_INBOUND_ID = 1
BOT_CLIENT_FLOW = "xtls-rprx-vision"
SUPPORT_CATEGORIES = frozenset({"link", "connection", "device", "directions", "other"})
TRAFFIC_REMINDER_THRESHOLDS = frozenset({50, 80, 95, 100})
GUEST_LINK_DURATIONS_HOURS = frozenset({1, 3, 6, 12, 24})
NODE_STATES = ("active", "suspended", "available_to_add", "problem")


# SQL predicate for an initial job whose snapshot is complete. Alias: j.
INITIAL_JOB_COMPLETE_SQL = """(j.status = 'succeeded' OR (
    j.status IN ('cancelled', 'partial') AND j.finished_at IS NOT NULL
    AND EXISTS (SELECT 1 FROM telegram_provisioning_attempts a
                WHERE a.job_id = j.id AND a.status = 'succeeded')
    AND NOT EXISTS (SELECT 1 FROM telegram_provisioning_attempts a
                    WHERE a.job_id = j.id AND NOT (a.status = 'succeeded' OR
                        (a.status = 'skipped' AND a.error_code IS 'node_bulk_remove_cancelled')))
))"""


def initial_job_incomplete(conn: sqlite3.Connection, customer_id: int) -> bool:
    return conn.execute(
        f"SELECT 1 FROM telegram_provisioning_jobs j WHERE j.customer_id = ? "
        f"AND j.trigger = 'approve_new' AND NOT {INITIAL_JOB_COMPLETE_SQL} LIMIT 1",
        (customer_id,),
    ).fetchone() is not None


def mark_completed_initial_snapshot(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        f"UPDATE telegram_identities SET remote_snapshot_ready = 1, updated_at = CURRENT_TIMESTAMP "
        f"WHERE access_status = 'approved' AND remote_snapshot_ready = 0 AND customer_id IN ("
        f"SELECT j.customer_id FROM telegram_provisioning_jobs j WHERE j.id = ? "
        f"AND j.trigger = 'approve_new' AND {INITIAL_JOB_COMPLETE_SQL})",
        (job_id,),
    )


def _classify_customer_node_state(
    *,
    binding_present: bool,
    management_state: str | None,
    enabled: bool,
    read_only: bool,
    desired_enabled: bool | None,
    eligible: bool,
) -> str:
    """Classify one bound or unbound node using the customer node rules."""

    if not binding_present:
        return "available_to_add" if eligible else "problem"
    if management_state == "missing" and eligible:
        return "available_to_add"
    if management_state != "confirmed" or not enabled or read_only:
        return "problem"
    return "active" if bool(desired_enabled) else "suspended"


def _normalize_traffic_thresholds(value: object) -> tuple[int, ...]:
    """Return one safe, ordered preference set or the stable default."""

    raw = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except json.JSONDecodeError:
            raw = None
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return (80, 95, 100)
    if any(not isinstance(item, int) or isinstance(item, bool) for item in raw):
        return (80, 95, 100)
    thresholds = tuple(sorted(set(raw)))
    return thresholds if set(thresholds).issubset(TRAFFIC_REMINDER_THRESHOLDS) else (80, 95, 100)



def _fresh_snapshot_has_client(conn, node_id: int, remote_client_id: str) -> bool | None:
    """True/False from a snapshot of an online node taken in the last 15 minutes, else None."""
    row = conn.execute(
        "SELECT status_data FROM node_snapshots WHERE node_id = ? AND is_online = 1 "
        "AND updated_at >= datetime('now', '-15 minutes')", (node_id,),
    ).fetchone()
    if row is None or not remote_client_id:
        return None
    try:
        data = json.loads(row[0] or "{}")
    except (TypeError, ValueError):
        return None
    wanted = remote_client_id.strip().lower()
    seen_any = False
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            # Panel clients carry their identifier as "id" (inbound settings) or "uuid" (flattened rows).
            if "email" in item and ("uuid" in item or "id" in item):
                seen_any = True
                if wanted in {str(item[key]).strip().lower() for key in ("uuid", "id") if key in item}:
                    return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    # An empty snapshot proves nothing: only call the client absent when other clients were listed.
    return False if seen_any else None

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
    blocked_from_status: str | None
    initial_provisioning_ready: bool = True


@dataclass(frozen=True)
class TelegramNotificationPreferences:
    telegram_user_id: int
    background_notifications_enabled: bool
    expiry_reminders_enabled: bool
    traffic_reminders_enabled: bool
    traffic_reminder_thresholds: tuple[int, ...]
    row_version: int


@dataclass(frozen=True)
class TelegramSubscriptionMessageReceipt:
    """Safe pointer to the one interactive message that contains a subscription URL."""

    telegram_user_id: int
    token_digest: str
    chat_id: int
    message_id: int


@dataclass(frozen=True)
class TelegramTransportPreference:
    """Non-secret delivery mode selected by a panel administrator."""

    mode: str
    proxy_host: str | None
    proxy_port: int | None
    row_version: int
    updated_by: str
    updated_at: str


@dataclass(frozen=True)
class CustomerTrafficLedger:
    customer_id: int
    lifetime_bytes: int
    last_observed_bytes: int
    last_observed_at: str


@dataclass(frozen=True)
class CustomerTrafficObservationBinding:
    """One exact confirmed binding eligible for local traffic observation."""

    customer_id: int
    node_id: int
    inbound_id: int
    remote_email: str


@dataclass(frozen=True)
class CustomerTrafficQuotaBinding:
    """One current TG-managed client binding eligible for quota observation."""

    node_id: int
    inbound_id: int
    remote_client_id: str


@dataclass(frozen=True)
class CustomerTrafficQuotaCandidate:
    """A fully provisioned, finite traffic plan safe to evaluate locally."""

    telegram_user_id: int
    customer_id: int
    email_display: str
    quota_total_bytes: int
    quota_plan_digest: str
    bindings: tuple[CustomerTrafficQuotaBinding, ...]
    traffic_reminder_thresholds: tuple[int, ...]


@dataclass(frozen=True)
class TelegramGuestSubscriptionLink:
    """A short-lived guest bearer link, including its token when retrieved internally."""

    guest_link_id: int
    customer_id: int
    email_display: str
    expires_at: int
    status: str
    token: str | None = None


@dataclass(frozen=True)
class TelegramLogicalDevice:
    device_id: int
    customer_id: int
    kind: str
    label: str
    guest_link_id: int | None
    status: str
    created_at: str
    expires_at: int | None


@dataclass(frozen=True)
class TelegramSubscriptionDevice:
    """One persistent personal subscription URL owned by a Telegram customer."""

    device_id: int
    customer_id: int
    token_identifier: str
    label: str
    created_at: str


@dataclass(frozen=True)
class TelegramCustomerSubscriptionLink:
    """Non-secret link metadata intended for an administrator's customer card."""

    kind: str
    label: str
    status: str
    created_at: str
    expires_at: int | None = None


@dataclass(frozen=True)
class TelegramQualityReport:
    report_id: int
    telegram_user_id: int
    customer_id: int
    kind: str
    platform: str
    created_at: str


@dataclass(frozen=True)
class TelegramServiceNoticeDraft:
    admin_telegram_user_id: int
    expected_row_version: int


@dataclass(frozen=True)
class TelegramSubscriptionTokenEvent:
    event_type: str
    actor_type: str
    actor_id: str | None
    reason: str | None
    created_at: str


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
class NodeBulkActionPreview:
    """Durable, confirmation-gated action scoped to one Telegram node."""

    node_id: int
    node_name: str
    action: str
    target_count: int
    target_snapshot_digest: str
    page: int


@dataclass(frozen=True)
class NodeBulkActionQueueResult:
    node_id: int
    action: str
    target_count: int
    queued_count: int
    cancelled_attempt_count: int


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
class TelegramPreapproval:
    telegram_user_id: int
    profile_kind: str
    customer_id: int | None
    customer_email: str
    email_source: str | None
    target_node_ids: tuple[int, ...]
    target_snapshot_digest: str | None
    row_version: int
    created_by: str
    created_at: str


@dataclass(frozen=True)
class TelegramUnlinkResult:
    telegram_user_id: int
    customer_id: int
    identity_row_version: int


@dataclass(frozen=True)
class BlockedIdentity:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    row_version: int
    blocked_at: str | None
    decision_reason: str | None


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
class DeferredExistingApprovalResult:
    """Local existing-email association that is deliberately access-gated."""

    telegram_user_id: int
    customer_id: int
    discovery_job_id: int
    email_display: str
    target_node_ids: tuple[int, ...]
    identity_row_version: int


@dataclass(frozen=True)
class ExistingDiscoveryTargetStatus:
    node_id: int
    node_name: str
    status: str
    attempt_count: int
    error_code: str | None
    next_attempt_at: str | None


@dataclass(frozen=True)
class ExistingDiscoveryJobStatus:
    job_id: int
    customer_id: int
    telegram_user_id: int
    customer_email: str
    status: str
    row_version: int
    target_snapshot_digest: str
    created_at: str
    finished_at: str | None
    targets: tuple[ExistingDiscoveryTargetStatus, ...]


@dataclass(frozen=True)
class DiscoveredExistingBinding:
    """Trusted remote identity captured by the read-only legacy discovery adapter."""

    node_id: int
    inbound_id: int
    remote_client_id: str
    remote_sub_id: str
    remote_email: str
    enabled: bool


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
class TelegramSupportRequest:
    support_request_id: int
    telegram_user_id: int
    customer_id: int
    email_display: str
    category: str
    body: str
    status: str
    row_version: int
    created_at: str
    updated_at: str
    admin_response: str | None


@dataclass(frozen=True)
class TelegramSupportResolution:
    support_request_id: int
    status: str
    row_version: int


@dataclass(frozen=True)
class TelegramServiceNotice:
    body: str | None
    is_active: bool
    row_version: int
    updated_by: str
    updated_at: str | None


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
    telegram_username: str | None
    telegram_first_name: str | None
    telegram_last_name: str | None
    node_count: int
    nodes_active: int
    nodes_suspended: int
    nodes_available: int
    nodes_problem: int
    lifetime_bytes: int | None
    traffic_observed_at: str | None
    application_introduction: str | None
    created_at: str
    updated_at: str
    open_support_count: int = 0


@dataclass(frozen=True)
class CustomerPage:
    items: tuple[CustomerListItem, ...]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class TelegramAdminDraft:
    """A short-lived, durable input step of the primary admin's Telegram UI."""

    admin_telegram_user_id: int
    action: str
    telegram_user_id: int | None
    customer_id: int | None
    expected_row_version: int | None
    page: int
    value: str | None


@dataclass(frozen=True)
class TelegramAdminMessageDraft:
    """Durable, confirmation-gated message composition by the primary admin."""

    admin_telegram_user_id: int
    mode: str
    customer_id: int | None
    page: int
    body: str | None
    photo_file_ids: tuple[str, ...] | None = None
    media_group_id: str | None = None


@dataclass(frozen=True)
class TelegramCustomerNoteDraft:
    """Durable destination for one pending customer-note text input."""

    admin_telegram_user_id: int
    customer_id: int
    page: int


@dataclass(frozen=True)
class TelegramSupportReplyDraft:
    """One confirmation-gated reply to an unresolved customer support request."""

    admin_telegram_user_id: int
    support_request_id: int
    customer_id: int
    expected_row_version: int
    page: int
    body: str | None


@dataclass(frozen=True)
class CustomerTelegramProfile:
    customer_id: int
    telegram_user_id: int | None
    username: str | None
    first_name: str | None
    last_name: str | None
    phone_number: str | None


@dataclass(frozen=True)
class CustomerAdminNote:
    """One private, administrator-authored note attached to a customer."""

    customer_id: int
    body: str
    updated_by_telegram_user_id: int
    updated_at: str


@dataclass(frozen=True)
class BroadcastQueueResult:
    broadcast_id: int
    recipient_count: int


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


@dataclass(frozen=True)
class TelegramAdminDashboard:
    pending_requests: int
    active_customers: int
    suspended_customers: int
    lifecycle_attention: int
    provisioning_attention: int
    open_appeals: int
    open_support_requests: int
    open_drift_findings: int
    scheduled_lifecycle_actions: int


@dataclass(frozen=True)
class CustomerTimelineEvent:
    event_type: str
    entity_type: str
    entity_id: str
    created_at: str
    actor_type: str | None = None
    actor_id: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class CustomerTag:
    customer_id: int
    tag: str


@dataclass(frozen=True)
class TelegramSavedFilter:
    filter_id: int
    name: str
    query: str
    status: str | None
    tags: tuple[str, ...]
    updated_at: str


@dataclass(frozen=True)
class LifecycleSchedule:
    schedule_id: int
    customer_id: int
    customer_email: str
    operation_type: str
    expected_customer_version: int
    target_snapshot_digest: str
    execute_not_before: str
    status: str
    row_version: int
    operation_id: int | None
    created_at: str


@dataclass(frozen=True)
class BulkLifecyclePreviewItem:
    customer_id: int
    customer_email: str
    expected_customer_version: int
    target_snapshot_digest: str
    target_count: int


@dataclass(frozen=True)
class BulkLifecyclePreview:
    operation_type: str
    target_snapshot_digest: str
    items: tuple[BulkLifecyclePreviewItem, ...]


@dataclass(frozen=True)
class BulkLifecycleItemStatus:
    customer_id: int
    customer_email: str
    operation_id: int
    status: str


@dataclass(frozen=True)
class BulkLifecycleStatus:
    bulk_job_id: int
    operation_type: str
    created_at: str
    items: tuple[BulkLifecycleItemStatus, ...]


@dataclass(frozen=True)
class DriftFinding:
    finding_id: int
    kind: str
    customer_id: int | None
    customer_email: str | None
    node_id: int
    node_name: str
    remote_email: str
    remote_client_id: str
    remote_sub_id: str
    status: str
    row_version: int
    last_seen_at: str


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


def _normalize_phone_number(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    compact = re.sub(r"[^0-9+]", "", value)
    if compact.count("+") > 1 or "+" in compact[1:]:
        return None
    digits = compact.replace("+", "")
    return compact if 6 <= len(digits) <= 20 else None


def _normalize_admin_message_body(value: str) -> str:
    if not isinstance(value, str):
        raise TelegramRegistryError("message body must be text")
    body = value.strip()
    if not 1 <= len(body) <= 2000:
        raise TelegramRegistryError("message body must contain 1 to 2000 characters")
    return body


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat(sep=" ")


def _parse_future_timestamp(value: object, field: str, *, minimum_minutes: int = 5) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TelegramRegistryError(f"{field} must be an ISO timestamp")
    try:
        candidate = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise TelegramRegistryError(f"{field} must be an ISO timestamp") from exc
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    normalized = candidate.astimezone(timezone.utc).replace(microsecond=0)
    if normalized < _utc_now() + timedelta(minutes=minimum_minutes):
        raise TelegramRegistryError(f"{field} must be at least {minimum_minutes} minutes in the future")
    if normalized > _utc_now() + timedelta(days=366):
        raise TelegramRegistryError(f"{field} must be within one year")
    return _timestamp(normalized)


def _normalize_tag(value: object) -> str:
    if not isinstance(value, str):
        raise TelegramRegistryError("tag must be text")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not 1 <= len(normalized) <= 48 or any(char in normalized for char in "\r\n\t"):
        raise TelegramRegistryError("tag must contain 1 to 48 printable characters")
    return normalized


def _normalize_tags(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise TelegramRegistryError("tags must be a list")
    normalized = tuple(sorted({_normalize_tag(value) for value in values}))
    if len(normalized) > 12:
        raise TelegramRegistryError("at most 12 tags are allowed")
    return normalized


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


def _telegram_registry_identity_deps() -> dict[str, Any]:
    return {
        "TelegramRegistryError": TelegramRegistryError,
        "VersionConflictError": VersionConflictError,
        "NodePolicyUnavailableError": NodePolicyUnavailableError,
        "IdempotencyConflictError": IdempotencyConflictError,
        "ApprovalUnavailableError": ApprovalUnavailableError,
        "LifecycleUnavailableError": LifecycleUnavailableError,
        "TelegramIdentity": TelegramIdentity,
        "TelegramTransportPreference": TelegramTransportPreference,
        "TelegramPreapproval": TelegramPreapproval,
        "ApprovalResult": ApprovalResult,
        "ExistingApprovalResult": ExistingApprovalResult,
        "TelegramUnlinkResult": TelegramUnlinkResult,
        "TelegramCustomerAccess": TelegramCustomerAccess,
        "_normalize_phone_number": _normalize_phone_number,
        "_positive_int": _positive_int,
        "_nonempty": _nonempty,
        "_payload_digest": _payload_digest,
        "canonicalize_email": canonicalize_email,
        "_validate_email_choice": _validate_email_choice,
        "initial_job_incomplete": initial_job_incomplete,
        "BOT_INBOUND_ID": BOT_INBOUND_ID,
        "BOT_CLIENT_FLOW": BOT_CLIENT_FLOW,
        "connect": connect,
    }


class TelegramRegistry:
    """Transactional access to the Telegram-specific SQLite records."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    @property
    def database_path(self) -> str:
        """Configured local authority path for sibling local-only services."""

        return self._db_path

    @staticmethod
    def normalize_new_customer_email(value: str) -> str:
        """Validate the human-facing node email before it is shown for approval."""

        if not isinstance(value, str):
            raise TelegramRegistryError("email must be a string")
        return _validate_email_choice(value)

    def set_admin_draft(
        self,
        *,
        admin_telegram_user_id: int,
        action: str,
        telegram_user_id: int | None = None,
        customer_id: int | None = None,
        expected_row_version: int | None = None,
        page: int = 0,
        value: str | None = None,
    ) -> TelegramAdminDraft:
        return _telegram_registry_drafts.set_admin_draft(
            self,
            admin_telegram_user_id=admin_telegram_user_id,
            action=action,
            telegram_user_id=telegram_user_id,
            customer_id=customer_id,
            expected_row_version=expected_row_version,
            page=page,
            value=value,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            admin_draft_type=TelegramAdminDraft,
        )

    def get_admin_draft(self, admin_telegram_user_id: int) -> TelegramAdminDraft | None:
        return _telegram_registry_drafts.get_admin_draft(
            self, admin_telegram_user_id, positive_int=_positive_int, admin_draft_type=TelegramAdminDraft
        )

    def clear_admin_draft(self, admin_telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_admin_draft(
            self, admin_telegram_user_id, positive_int=_positive_int
        )

    def set_admin_message_draft(
        self,
        *,
        admin_telegram_user_id: int,
        mode: str,
        customer_id: int | None = None,
        page: int = 0,
        body: str | None = None,
        photo_file_ids: tuple[str, ...] | None = None,
        media_group_id: str | None = None,
    ) -> TelegramAdminMessageDraft:
        return _telegram_registry_drafts.set_admin_message_draft(
            self,
            admin_telegram_user_id=admin_telegram_user_id,
            mode=mode,
            customer_id=customer_id,
            page=page,
            body=body,
            photo_file_ids=photo_file_ids,
            media_group_id=media_group_id,
            positive_int=_positive_int,
            normalize_admin_message_body=_normalize_admin_message_body,
            error_type=TelegramRegistryError,
            admin_message_draft_type=TelegramAdminMessageDraft,
        )

    def get_admin_message_draft(self, admin_telegram_user_id: int) -> TelegramAdminMessageDraft | None:
        return _telegram_registry_drafts.get_admin_message_draft(
            self, admin_telegram_user_id, positive_int=_positive_int,
            admin_message_draft_type=TelegramAdminMessageDraft,
        )

    def clear_admin_message_draft(self, admin_telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_admin_message_draft(
            self, admin_telegram_user_id, positive_int=_positive_int
        )

    def set_customer_note_draft(
        self, *, admin_telegram_user_id: int, customer_id: int, page: int
    ) -> TelegramCustomerNoteDraft:
        return _telegram_registry_drafts.set_customer_note_draft(
            self,
            admin_telegram_user_id=admin_telegram_user_id,
            customer_id=customer_id,
            page=page,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            customer_note_draft_type=TelegramCustomerNoteDraft,
        )

    def get_customer_note_draft(self, admin_telegram_user_id: int) -> TelegramCustomerNoteDraft | None:
        return _telegram_registry_drafts.get_customer_note_draft(
            self, admin_telegram_user_id, positive_int=_positive_int,
            customer_note_draft_type=TelegramCustomerNoteDraft,
        )

    def clear_customer_note_draft(self, admin_telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_customer_note_draft(
            self, admin_telegram_user_id, positive_int=_positive_int
        )

    def set_support_reply_draft(
        self,
        *,
        admin_telegram_user_id: int,
        support_request_id: int,
        customer_id: int,
        expected_row_version: int,
        page: int,
        body: str | None = None,
    ) -> TelegramSupportReplyDraft:
        return _telegram_registry_drafts.set_support_reply_draft(
            self,
            admin_telegram_user_id=admin_telegram_user_id,
            support_request_id=support_request_id,
            customer_id=customer_id,
            expected_row_version=expected_row_version,
            page=page,
            body=body,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            version_conflict_type=VersionConflictError,
            support_reply_draft_type=TelegramSupportReplyDraft,
        )

    def get_support_reply_draft(self, admin_telegram_user_id: int) -> TelegramSupportReplyDraft | None:
        return _telegram_registry_drafts.get_support_reply_draft(
            self, admin_telegram_user_id, positive_int=_positive_int,
            support_reply_draft_type=TelegramSupportReplyDraft,
        )

    def clear_support_reply_draft(self, admin_telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_support_reply_draft(
            self, admin_telegram_user_id, positive_int=_positive_int
        )

    def get_customer_by_email(self, email: str) -> CustomerListItem:
        """Resolve one live customer by canonical exact email, without fuzzy matching."""

        canonical = canonicalize_email(email)
        with connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM customers WHERE email_canonical = ? AND deleted_at IS NULL", (canonical,)
            ).fetchone()
        if row is None:
            raise TelegramRegistryError("customer was not found")
        return self.get_customer(int(row[0]))

    def eligible_provisioning_node_count(self) -> int:
        """Return the local policy snapshot count shown before final approval."""

        return _telegram_registry_traffic.eligible_provisioning_node_count(self)

    def get_transport_preference(self) -> TelegramTransportPreference:
        return _telegram_registry_identity.get_transport_preference(self, **_telegram_registry_identity_deps())

    def set_transport_preference(
        self,
        *,
        mode: str,
        expected_row_version: int,
        updated_by: str,
        proxy_host: str | None = None,
        proxy_port: int | None = None,
    ) -> TelegramTransportPreference:
        return _telegram_registry_identity.set_transport_preference(self, mode=mode, expected_row_version=expected_row_version, updated_by=updated_by, proxy_host=proxy_host, proxy_port=proxy_port, **_telegram_registry_identity_deps())

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
    ) -> TelegramIdentity:
        return _telegram_registry_identity.get_or_create_identity(self, telegram_user_id=telegram_user_id, chat_id=chat_id, username=username, first_name=first_name, last_name=last_name, phone_number=phone_number, locale=locale, **_telegram_registry_identity_deps())

    def get_locale(self, telegram_user_id: int) -> str:
        return _telegram_registry_identity.get_locale(self, telegram_user_id, **_telegram_registry_identity_deps())

    def set_locale(self, telegram_user_id: int, locale: object) -> str:
        return _telegram_registry_identity.set_locale(self, telegram_user_id, locale, **_telegram_registry_identity_deps())

    def get_preapproval(self, telegram_user_id: int) -> TelegramPreapproval | None:
        return _telegram_registry_identity.get_preapproval(self, telegram_user_id, **_telegram_registry_identity_deps())

    @staticmethod
    def _preapproval_from_row(row: tuple[object, ...]) -> TelegramPreapproval:
        return _telegram_registry_identity._preapproval_from_row(row, **_telegram_registry_identity_deps())

    @staticmethod
    def _preapproval_from_receipt(payload: object) -> TelegramPreapproval:
        return _telegram_registry_identity._preapproval_from_receipt(payload, **_telegram_registry_identity_deps())

    def create_existing_customer_preapproval(
        self,
        *,
        telegram_user_id: int,
        customer_id: int,
        expected_preapproval_version: int,
        idempotency_key: str,
        created_by: str,
    ) -> TelegramPreapproval:
        return _telegram_registry_identity.create_existing_customer_preapproval(self, telegram_user_id=telegram_user_id, customer_id=customer_id, expected_preapproval_version=expected_preapproval_version, idempotency_key=idempotency_key, created_by=created_by, **_telegram_registry_identity_deps())

    def create_new_customer_preapproval(
        self,
        *,
        telegram_user_id: int,
        email_display: str,
        expected_preapproval_version: int,
        idempotency_key: str,
        created_by: str,
    ) -> TelegramPreapproval:
        return _telegram_registry_identity.create_new_customer_preapproval(self, telegram_user_id=telegram_user_id, email_display=email_display, expected_preapproval_version=expected_preapproval_version, idempotency_key=idempotency_key, created_by=created_by, **_telegram_registry_identity_deps())

    def activate_preapproval(self, telegram_user_id: int) -> ExistingApprovalResult | ApprovalResult | None:
        return _telegram_registry_identity.activate_preapproval(self, telegram_user_id, **_telegram_registry_identity_deps())

    def _activate_new_customer_preapproval(
        self,
        *,
        conn: sqlite3.Connection,
        telegram_user_id: int,
        identity: tuple[object, ...],
        preapproval: tuple[object, ...],
    ) -> ApprovalResult | None:
        return _telegram_registry_identity._activate_new_customer_preapproval(self, conn=conn, telegram_user_id=telegram_user_id, identity=identity, preapproval=preapproval, **_telegram_registry_identity_deps())

    def unlink_identity(
        self,
        *,
        telegram_user_id: int,
        customer_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        unlinked_by: str,
    ) -> TelegramUnlinkResult:
        return _telegram_registry_identity.unlink_identity(self, telegram_user_id=telegram_user_id, customer_id=customer_id, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, unlinked_by=unlinked_by, **_telegram_registry_identity_deps())

    def safe_subscription_node_ids(self, email: str) -> frozenset[int] | None:
        return _telegram_registry_identity.safe_subscription_node_ids(self, email, **_telegram_registry_identity_deps())

    def enabled_node_ids(self) -> frozenset[int]:
        return _telegram_registry_identity.enabled_node_ids(self, **_telegram_registry_identity_deps())

    def has_confirmed_enabled_subscription_binding(self, email: str) -> bool:
        return _telegram_registry_identity.has_confirmed_enabled_subscription_binding(self, email, **_telegram_registry_identity_deps())

    def get_customer_access(self, telegram_user_id: int) -> TelegramCustomerAccess:
        return _telegram_registry_identity.get_customer_access(self, telegram_user_id, **_telegram_registry_identity_deps())

    def get_interface_window(self, telegram_user_id: int) -> tuple[int, bool] | None:
        return _telegram_registry_identity.get_interface_window(self, telegram_user_id, **_telegram_registry_identity_deps())

    def set_interface_window(
        self, *, telegram_user_id: int, message_id: int, has_text: bool
    ) -> None:
        return _telegram_registry_identity.set_interface_window(self, telegram_user_id=telegram_user_id, message_id=message_id, has_text=has_text, **_telegram_registry_identity_deps())

    def get_notification_preferences(self, telegram_user_id: int) -> TelegramNotificationPreferences:
        return _telegram_registry_traffic.get_notification_preferences(
            self,
            telegram_user_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            preference_type=TelegramNotificationPreferences,
            normalize_traffic_thresholds=_normalize_traffic_thresholds,
        )

    def toggle_background_notifications(self, telegram_user_id: int) -> TelegramNotificationPreferences:
        """Toggle user-controlled background delivery after durable update dedupe."""

        return _telegram_registry_traffic.toggle_background_notifications(
            self, telegram_user_id, positive_int=_positive_int, error_type=TelegramRegistryError
        )

    def toggle_expiry_reminders(self, telegram_user_id: int) -> TelegramNotificationPreferences:
        """Toggle only pre-expiry reminders; command replies remain unaffected."""

        return _telegram_registry_traffic.toggle_expiry_reminders(
            self, telegram_user_id, positive_int=_positive_int, error_type=TelegramRegistryError
        )

    def toggle_traffic_reminders(self, telegram_user_id: int) -> TelegramNotificationPreferences:
        """Toggle opt-in finite-quota notices; command replies remain unaffected."""

        return _telegram_registry_traffic.toggle_traffic_reminders(
            self, telegram_user_id, positive_int=_positive_int, error_type=TelegramRegistryError
        )

    def toggle_traffic_reminder_threshold(
        self, telegram_user_id: int, threshold_percent: int
    ) -> TelegramNotificationPreferences:
        """Toggle one user-selected finite-traffic reminder threshold."""

        return _telegram_registry_traffic.toggle_traffic_reminder_threshold(
            self,
            telegram_user_id,
            threshold_percent,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            traffic_reminder_thresholds=TRAFFIC_REMINDER_THRESHOLDS,
            normalize_traffic_thresholds=_normalize_traffic_thresholds,
        )

    @staticmethod
    def _active_telegram_customer(conn: sqlite3.Connection, telegram_user_id: int) -> tuple[int, str]:
        return _telegram_registry_identity._active_telegram_customer(conn, telegram_user_id, **_telegram_registry_identity_deps())

    def create_guest_subscription_link(
        self, *, telegram_user_id: int, duration_hours: int
    ) -> TelegramGuestSubscriptionLink:
        return _telegram_registry_devices.create_guest_subscription_link(
            self,
            telegram_user_id=telegram_user_id,
            duration_hours=duration_hours,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            guest_link_durations_hours=GUEST_LINK_DURATIONS_HOURS,
            guest_link_type=TelegramGuestSubscriptionLink,
            payload_digest=_payload_digest,
        )

    def resolve_guest_subscription_link(self, token: str) -> TelegramGuestSubscriptionLink | None:
        return _telegram_registry_devices.resolve_guest_subscription_link(
            self, token, guest_link_type=TelegramGuestSubscriptionLink
        )

    def get_guest_subscription_link(
        self, *, telegram_user_id: int, guest_link_id: int
    ) -> TelegramGuestSubscriptionLink:
        return _telegram_registry_devices.get_guest_subscription_link(
            self,
            telegram_user_id=telegram_user_id,
            guest_link_id=guest_link_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            guest_link_type=TelegramGuestSubscriptionLink,
        )

    def _ensure_primary_logical_device(self, conn: sqlite3.Connection, customer_id: int) -> None:
        return _telegram_registry_devices._ensure_primary_logical_device(self, conn, customer_id)

    def list_logical_devices(
        self, telegram_user_id: int, *, include_inactive: bool = True
    ) -> tuple[TelegramLogicalDevice, ...]:
        return _telegram_registry_devices.list_logical_devices(
            self,
            telegram_user_id,
            include_inactive=include_inactive,
            positive_int=_positive_int,
            active_telegram_customer=self._active_telegram_customer,
            ensure_primary_logical_device=self._ensure_primary_logical_device,
            logical_device_type=TelegramLogicalDevice,
        )

    def list_subscription_devices(self, telegram_user_id: int) -> tuple[TelegramSubscriptionDevice, ...]:
        return _telegram_registry_devices.list_subscription_devices(
            self,
            telegram_user_id,
            positive_int=_positive_int,
            active_telegram_customer=self._active_telegram_customer,
            subscription_device_type=TelegramSubscriptionDevice,
        )

    def list_customer_subscription_links(
        self, customer_id: int
    ) -> tuple[TelegramCustomerSubscriptionLink, ...]:
        return _telegram_registry_devices.list_customer_subscription_links(
            self,
            customer_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            customer_subscription_link_type=TelegramCustomerSubscriptionLink,
        )

    def get_subscription_device(
        self, *, telegram_user_id: int, subscription_device_id: int
    ) -> TelegramSubscriptionDevice:
        return _telegram_registry_devices.get_subscription_device(
            self,
            telegram_user_id=telegram_user_id,
            subscription_device_id=subscription_device_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            subscription_device_type=TelegramSubscriptionDevice,
        )

    def create_subscription_device(
        self, *, telegram_user_id: int, label: str
    ) -> TelegramSubscriptionDevice:
        return _telegram_registry_devices.create_subscription_device(
            self,
            telegram_user_id=telegram_user_id,
            label=label,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            payload_digest=_payload_digest,
            subscription_device_type=TelegramSubscriptionDevice,
        )

    def set_subscription_device_label(
        self, *, telegram_user_id: int, subscription_device_id: int, label: str
    ) -> TelegramSubscriptionDevice:
        return _telegram_registry_devices.set_subscription_device_label(
            self,
            telegram_user_id=telegram_user_id,
            subscription_device_id=subscription_device_id,
            label=label,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            get_subscription_device=self.get_subscription_device,
        )

    def set_subscription_device_draft(
        self, *, telegram_user_id: int, subscription_device_id: int
    ) -> None:
        return _telegram_registry_drafts.set_subscription_device_draft(
            self,
            telegram_user_id=telegram_user_id,
            subscription_device_id=subscription_device_id,
            positive_int=_positive_int,
            get_subscription_device=self.get_subscription_device,
        )

    def get_subscription_device_draft(self, telegram_user_id: int) -> int | None:
        return _telegram_registry_drafts.get_subscription_device_draft(
            self, telegram_user_id, positive_int=_positive_int
        )

    def clear_subscription_device_draft(self, telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_subscription_device_draft(
            self, telegram_user_id, positive_int=_positive_int
        )

    def revoke_subscription_device(self, *, telegram_user_id: int, subscription_device_id: int) -> None:
        return _telegram_registry_devices.revoke_subscription_device(
            self,
            telegram_user_id=telegram_user_id,
            subscription_device_id=subscription_device_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
        )

    def resolve_subscription_device_email(self, token_identifier: str) -> str | None:
        return _telegram_registry_devices.resolve_subscription_device_email(self, token_identifier)

    def set_logical_device_label(
        self, *, telegram_user_id: int, device_id: int, label: str
    ) -> TelegramLogicalDevice:
        return _telegram_registry_devices.set_logical_device_label(
            self,
            telegram_user_id=telegram_user_id,
            device_id=device_id,
            label=label,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            list_logical_devices=self.list_logical_devices,
        )

    def set_logical_device_draft(self, *, telegram_user_id: int, device_id: int) -> None:
        return _telegram_registry_drafts.set_logical_device_draft(
            self,
            telegram_user_id=telegram_user_id,
            device_id=device_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
        )

    def get_logical_device_draft(self, telegram_user_id: int) -> int | None:
        return _telegram_registry_drafts.get_logical_device_draft(
            self, telegram_user_id, positive_int=_positive_int
        )

    def clear_logical_device_draft(self, telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_logical_device_draft(
            self, telegram_user_id, positive_int=_positive_int
        )

    def revoke_guest_subscription_link(self, *, telegram_user_id: int, guest_link_id: int) -> None:
        return _telegram_registry_devices.revoke_guest_subscription_link(
            self,
            telegram_user_id=telegram_user_id,
            guest_link_id=guest_link_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
        )

    def submit_quality_report(
        self, *, telegram_user_id: int, kind: str, platform: str
    ) -> TelegramQualityReport:
        return _telegram_registry_devices.submit_quality_report(
            self,
            telegram_user_id=telegram_user_id,
            kind=kind,
            platform=platform,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            active_telegram_customer=self._active_telegram_customer,
            quality_report_type=TelegramQualityReport,
        )

    def list_customer_quality_reports(
        self, customer_id: int, *, limit: int = 5
    ) -> tuple[TelegramQualityReport, ...]:
        return _telegram_registry_devices.list_customer_quality_reports(
            self,
            customer_id,
            limit=limit,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            quality_report_type=TelegramQualityReport,
        )

    def list_subscription_token_events(
        self, customer_id: int, *, limit: int = 5
    ) -> tuple[TelegramSubscriptionTokenEvent, ...]:
        return _telegram_registry_devices.list_subscription_token_events(
            self,
            customer_id,
            limit=limit,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            token_event_type=TelegramSubscriptionTokenEvent,
        )

    def list_traffic_reminder_candidates(self) -> tuple[CustomerTrafficQuotaCandidate, ...]:
        """Return only complete, finite TG traffic plans without node I/O.

        A customer is eligible only when every currently enabled confirmed
        binding has an exact successful immutable provisioning attempt. The
        finite quota is intentionally the sum of those per-node limits because
        each node enforces its own client counter.
        """

        return _telegram_registry_traffic.list_traffic_reminder_candidates(
            self,
            initial_job_complete_sql=INITIAL_JOB_COMPLETE_SQL,
            normalize_traffic_thresholds=_normalize_traffic_thresholds,
            payload_digest=_payload_digest,
            quota_binding_type=CustomerTrafficQuotaBinding,
            quota_candidate_type=CustomerTrafficQuotaCandidate,
        )

    def list_customer_traffic_observation_bindings(self) -> dict[int, tuple[CustomerTrafficObservationBinding, ...]]:
        """Return local exact bindings eligible to consume a collector snapshot."""

        return _telegram_registry_traffic.list_customer_traffic_observation_bindings(
            self,
            canonicalize_email=canonicalize_email,
            binding_type=CustomerTrafficObservationBinding,
            error_type=TelegramRegistryError,
        )

    def observe_customer_traffic_bindings(
        self, observations: dict[int, dict[tuple[int, int], int]]
    ) -> tuple[CustomerTrafficLedger, ...]:
        """Persist one complete collector observation batch by exact binding."""

        return _telegram_registry_traffic.observe_customer_traffic_bindings(
            self,
            observations,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            ledger_type=CustomerTrafficLedger,
        )

    def get_customer_traffic(self, customer_id: int) -> CustomerTrafficLedger:
        return _telegram_registry_traffic.get_customer_traffic(
            self, customer_id, positive_int=_positive_int, ledger_type=CustomerTrafficLedger
        )

    def submit_suspended_appeal(self, *, telegram_user_id: int, body: str) -> AppealResult:
        """Store one bounded appeal; it never changes customer access."""

        return _telegram_registry_support.submit_suspended_appeal(
            self,
            telegram_user_id=telegram_user_id,
            body=body,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            suspended_statuses=SUSPENDED_STATUSES,
            appeal_result_type=AppealResult,
        )

    def list_appeals(self, *, status: str = "open", limit: int = 100) -> list[AppealAdminItem]:
        return _telegram_registry_support.list_appeals(
            self,
            status=status,
            limit=limit,
            error_type=TelegramRegistryError,
            appeal_item_type=AppealAdminItem,
        )

    def resolve_appeal(
        self,
        *,
        appeal_id: int,
        expected_row_version: int,
        status: str,
        idempotency_key: str,
        resolved_by: str,
    ) -> AppealResolutionResult:
        return _telegram_registry_support.resolve_appeal(
            self,
            appeal_id=appeal_id,
            expected_row_version=expected_row_version,
            status=status,
            idempotency_key=idempotency_key,
            resolved_by=resolved_by,
            positive_int=_positive_int,
            nonempty=_nonempty,
            payload_digest=_payload_digest,
            error_type=TelegramRegistryError,
            idempotency_conflict_type=IdempotencyConflictError,
            version_conflict_type=VersionConflictError,
            resolution_type=AppealResolutionResult,
        )

    def begin_support_request(self, *, telegram_user_id: int, category: str) -> None:
        """Remember one bounded support category without creating a ticket yet."""

        return _telegram_registry_support.begin_support_request(
            self,
            telegram_user_id=telegram_user_id,
            category=category,
            positive_int=_positive_int,
            support_categories=SUPPORT_CATEGORIES,
            error_type=TelegramRegistryError,
        )

    def submit_pending_support_request(
        self, *, telegram_user_id: int, body: str
    ) -> TelegramSupportRequest | None:
        """Create a ticket only from an explicit support draft and bounded text."""

        return _telegram_registry_support.submit_pending_support_request(
            self,
            telegram_user_id=telegram_user_id,
            body=body,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            support_request_type=TelegramSupportRequest,
        )

    def clear_support_draft(self, telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_support_draft(
            self, telegram_user_id, positive_int=_positive_int
        )

    def list_support_requests(self, *, status: str = "open", limit: int = 100) -> list[TelegramSupportRequest]:
        return _telegram_registry_support.list_support_requests(
            self,
            status=status,
            limit=limit,
            error_type=TelegramRegistryError,
            support_request_type=TelegramSupportRequest,
        )

    def list_customer_support_requests(self, customer_id: int, *, limit: int = 20) -> list[TelegramSupportRequest]:
        return _telegram_registry_support.list_customer_support_requests(
            self,
            customer_id,
            limit=limit,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            support_request_type=TelegramSupportRequest,
        )

    def resolve_support_request(
        self,
        *,
        support_request_id: int,
        expected_row_version: int,
        response: str | None,
        idempotency_key: str,
        resolved_by: str,
    ) -> TelegramSupportResolution:
        return _telegram_registry_support.resolve_support_request(
            self,
            support_request_id=support_request_id,
            expected_row_version=expected_row_version,
            response=response,
            idempotency_key=idempotency_key,
            resolved_by=resolved_by,
            positive_int=_positive_int,
            nonempty=_nonempty,
            payload_digest=_payload_digest,
            error_type=TelegramRegistryError,
            idempotency_conflict_type=IdempotencyConflictError,
            version_conflict_type=VersionConflictError,
            resolution_type=TelegramSupportResolution,
        )

    def get_service_notice(self) -> TelegramServiceNotice:
        return _telegram_registry_notices.get_service_notice(
            self,
            notice_type=TelegramServiceNotice,
        )

    def set_service_notice(
        self,
        *,
        body: str | None,
        expected_row_version: int,
        idempotency_key: str,
        updated_by: str,
    ) -> TelegramServiceNotice:
        return _telegram_registry_notices.set_service_notice(
            self,
            body=body,
            expected_row_version=expected_row_version,
            idempotency_key=idempotency_key,
            updated_by=updated_by,
            nonempty=_nonempty,
            payload_digest=_payload_digest,
            error_type=TelegramRegistryError,
            idempotency_conflict_type=IdempotencyConflictError,
            version_conflict_type=VersionConflictError,
            notice_type=TelegramServiceNotice,
        )

    def set_service_notice_draft(
        self, *, admin_telegram_user_id: int, expected_row_version: int
    ) -> TelegramServiceNoticeDraft:
        return _telegram_registry_drafts.set_service_notice_draft(
            self,
            admin_telegram_user_id=admin_telegram_user_id,
            expected_row_version=expected_row_version,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
            version_conflict_type=VersionConflictError,
            service_notice_draft_type=TelegramServiceNoticeDraft,
        )

    def get_service_notice_draft(self, admin_telegram_user_id: int) -> TelegramServiceNoticeDraft | None:
        return _telegram_registry_drafts.get_service_notice_draft(
            self, admin_telegram_user_id, positive_int=_positive_int,
            service_notice_draft_type=TelegramServiceNoticeDraft,
        )

    def clear_service_notice_draft(self, admin_telegram_user_id: int) -> None:
        return _telegram_registry_drafts.clear_service_notice_draft(
            self, admin_telegram_user_id, positive_int=_positive_int
        )

    def create_customer(
        self,
        *,
        email_display: str,
        origin: str,
        email_source: str,
        public_code: str | None = None,
    ) -> int:
        return _telegram_registry_identity.create_customer(self, email_display=email_display, origin=origin, email_source=email_source, public_code=public_code, **_telegram_registry_identity_deps())

    def create_pending_application(self, telegram_user_id: int) -> PendingApplicationResult:
        return _telegram_registry_registration.create_pending_application(self, telegram_user_id, PendingApplicationResult=PendingApplicationResult, TelegramIdentity=TelegramIdentity, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def request_required_introduction(self, telegram_user_id: int) -> bool:
        return _telegram_registry_registration.request_required_introduction(self, telegram_user_id, _positive_int=_positive_int)

    def submit_required_introduction(
        self, telegram_user_id: int, text: str, *, maximum_chars: int
    ) -> PendingApplicationResult:
        return _telegram_registry_registration.submit_required_introduction(self, telegram_user_id, text, maximum_chars=maximum_chars, PendingApplicationResult=PendingApplicationResult, TelegramIdentity=TelegramIdentity, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def submit_introduction(self, telegram_user_id: int, text: str, *, maximum_chars: int) -> bool:
        return _telegram_registry_registration.submit_introduction(self, telegram_user_id, text, maximum_chars=maximum_chars, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def list_pending_applications(self) -> list[PendingApplication]:
        return _telegram_registry_registration.list_pending_applications(self, PendingApplication=PendingApplication, _suggested_email=_suggested_email, canonicalize_email=canonicalize_email)

    def list_blocked_identities(self, *, limit: int = 100) -> list[BlockedIdentity]:
        return _telegram_registry_registration.list_blocked_identities(self, limit=limit, BlockedIdentity=BlockedIdentity, TelegramRegistryError=TelegramRegistryError)

    def get_pending_application(self, telegram_user_id: int) -> PendingApplication:
        return _telegram_registry_registration.get_pending_application(self, telegram_user_id, PendingApplication=PendingApplication, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def approve_new_application(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        email_display: str | None,
        idempotency_key: str,
        approved_by: str,
    ) -> ApprovalResult:
        return _telegram_registry_registration.approve_new_application(self, telegram_user_id=telegram_user_id, expected_identity_version=expected_identity_version, email_display=email_display, idempotency_key=idempotency_key, approved_by=approved_by, ApprovalResult=ApprovalResult, ApprovalUnavailableError=ApprovalUnavailableError, BOT_CLIENT_FLOW=BOT_CLIENT_FLOW, BOT_INBOUND_ID=BOT_INBOUND_ID, IdempotencyConflictError=IdempotencyConflictError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int, _suggested_email=_suggested_email, _validate_email_choice=_validate_email_choice, canonicalize_email=canonicalize_email)

    def approve_existing_application(
        self,
        *,
        telegram_user_id: int,
        customer_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        approved_by: str,
    ) -> ExistingApprovalResult:
        return _telegram_registry_registration.approve_existing_application(self, telegram_user_id=telegram_user_id, customer_id=customer_id, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, approved_by=approved_by, ApprovalUnavailableError=ApprovalUnavailableError, ExistingApprovalResult=ExistingApprovalResult, IdempotencyConflictError=IdempotencyConflictError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int, canonicalize_email=canonicalize_email)

    def adopt_discovered_existing_application(
        self,
        *,
        telegram_user_id: int,
        email_display: str,
        bindings: Iterable[DiscoveredExistingBinding],
        expected_identity_version: int,
        idempotency_key: str,
        approved_by: str,
    ) -> ExistingApprovalResult:
        return _telegram_registry_registration.adopt_discovered_existing_application(self, telegram_user_id=telegram_user_id, email_display=email_display, bindings=bindings, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, approved_by=approved_by, ApprovalUnavailableError=ApprovalUnavailableError, BOT_INBOUND_ID=BOT_INBOUND_ID, DiscoveredExistingBinding=DiscoveredExistingBinding, ExistingApprovalResult=ExistingApprovalResult, IdempotencyConflictError=IdempotencyConflictError, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int, canonicalize_email=canonicalize_email)

    def queue_deferred_existing_discovery(
        self,
        *,
        telegram_user_id: int,
        email_display: str,
        expected_identity_version: int,
        idempotency_key: str,
        approved_by: str,
    ) -> DeferredExistingApprovalResult:
        return _telegram_registry_registration.queue_deferred_existing_discovery(self, telegram_user_id=telegram_user_id, email_display=email_display, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, approved_by=approved_by, ApprovalUnavailableError=ApprovalUnavailableError, BOT_CLIENT_FLOW=BOT_CLIENT_FLOW, BOT_INBOUND_ID=BOT_INBOUND_ID, DeferredExistingApprovalResult=DeferredExistingApprovalResult, IdempotencyConflictError=IdempotencyConflictError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int, canonicalize_email=canonicalize_email)

    def get_existing_discovery_job(self, job_id: int) -> ExistingDiscoveryJobStatus:
        return _telegram_registry_registration.get_existing_discovery_job(self, job_id, ExistingDiscoveryJobStatus=ExistingDiscoveryJobStatus, ExistingDiscoveryTargetStatus=ExistingDiscoveryTargetStatus, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def recover_existing_discovery_target(
        self, *, job_id: int, node_id: int, expected_job_version: int,
        idempotency_key: str, requested_by: str,
    ) -> ExistingDiscoveryJobStatus:
        return _telegram_registry_registration.recover_existing_discovery_target(self, job_id=job_id, node_id=node_id, expected_job_version=expected_job_version, idempotency_key=idempotency_key, requested_by=requested_by, ApprovalUnavailableError=ApprovalUnavailableError, ExistingDiscoveryJobStatus=ExistingDiscoveryJobStatus, IdempotencyConflictError=IdempotencyConflictError, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def reject_application(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        rejected_by: str,
        reason: str | None = None,
    ) -> TelegramIdentity:
        return _telegram_registry_registration.reject_application(self, telegram_user_id=telegram_user_id, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, rejected_by=rejected_by, reason=reason, TelegramIdentity=TelegramIdentity)

    def block_identity(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        blocked_by: str,
        reason: str | None = None,
    ) -> TelegramIdentity:
        return _telegram_registry_registration.block_identity(self, telegram_user_id=telegram_user_id, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, blocked_by=blocked_by, reason=reason, TelegramIdentity=TelegramIdentity)

    def unblock_identity(
        self,
        *,
        telegram_user_id: int,
        expected_identity_version: int,
        idempotency_key: str,
        unblocked_by: str,
    ) -> TelegramIdentity:
        return _telegram_registry_registration.unblock_identity(self, telegram_user_id=telegram_user_id, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, unblocked_by=unblocked_by, IdempotencyConflictError=IdempotencyConflictError, TelegramIdentity=TelegramIdentity, VersionConflictError=VersionConflictError, _identity_from_row=_identity_from_row, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def record_unapproved_noop(
        self,
        telegram_user_id: int,
        *,
        now: datetime | None = None,
        window_seconds: int = 600,
        soft_limit: int = 10,
        auto_block_at: int = 51,
    ) -> AbuseNoopResult:
        return _telegram_registry_registration.record_unapproved_noop(self, telegram_user_id, now=now, window_seconds=window_seconds, soft_limit=soft_limit, auto_block_at=auto_block_at, AbuseNoopResult=AbuseNoopResult, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _payload_digest=_payload_digest, _positive_int=_positive_int)

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
        return _telegram_registry_registration._change_unbound_application_state(self, telegram_user_id=telegram_user_id, expected_identity_version=expected_identity_version, idempotency_key=idempotency_key, actor=actor, action=action, reason=reason, IdempotencyConflictError=IdempotencyConflictError, TelegramIdentity=TelegramIdentity, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _identity_from_row=_identity_from_row, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def claim_update(
        self,
        *,
        update_id: int,
        telegram_user_id: int | None,
        update_type: str,
        payload_digest: str,
    ) -> bool:
        """Persist Telegram's update id before any state-changing handling."""

        return _telegram_registry_updates.claim_update(
            self,
            update_id=update_id,
            telegram_user_id=telegram_user_id,
            update_type=update_type,
            payload_digest=payload_digest,
            positive_int=_positive_int,
            nonempty=_nonempty,
        )

    def store_update_responses(
        self,
        *,
        update_id: int,
        responses: list[tuple],
    ) -> None:
        """Store retry-safe replies keyed by Telegram's immutable update id."""

        return _telegram_registry_updates.store_update_responses(
            self,
            update_id=update_id,
            responses=responses,
            positive_int=_positive_int,
            nonempty=_nonempty,
            error_type=TelegramRegistryError,
        )

    def pending_update_responses(
        self, update_id: int
    ) -> list[tuple[int, int, str, dict[str, Any] | None]]:
        return _telegram_registry_updates.pending_update_responses(
            self,
            update_id,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
        )

    def mark_update_response_delivered(self, *, update_id: int, response_index: int) -> None:
        return _telegram_registry_updates.mark_update_response_delivered(
            self,
            update_id=update_id,
            response_index=response_index,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
        )

    def mark_update_processed(self, update_id: int) -> None:
        """Record completion time without changing the durable update status."""

        return _telegram_registry_updates.mark_update_processed(
            self,
            update_id,
            positive_int=_positive_int,
        )

    def retry_update_response(self, *, update_id: int, response_index: int) -> None:
        return _telegram_registry_updates.retry_update_response(
            self,
            update_id=update_id,
            response_index=response_index,
            positive_int=_positive_int,
            error_type=TelegramRegistryError,
        )

    def get_subscription_message_receipt(
        self, telegram_user_id: int
    ) -> TelegramSubscriptionMessageReceipt | None:
        """Read a delivery pointer without ever exposing or storing the raw token."""

        return _telegram_registry_updates.get_subscription_message_receipt(
            self,
            telegram_user_id,
            positive_int=_positive_int,
            receipt_type=TelegramSubscriptionMessageReceipt,
        )

    def record_subscription_message_delivery(
        self,
        *,
        telegram_user_id: int,
        token_digest: str,
        chat_id: int,
        message_id: int,
    ) -> None:
        """Persist only the opaque token digest and Telegram message coordinates."""

        return _telegram_registry_updates.record_subscription_message_delivery(
            self,
            telegram_user_id=telegram_user_id,
            token_digest=token_digest,
            chat_id=chat_id,
            message_id=message_id,
            positive_int=_positive_int,
            nonempty=_nonempty,
        )

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
        return _telegram_registry_provisioning.set_node_provisioning_policy(self, node_id=node_id, provisioning_enabled=provisioning_enabled, total_bytes=total_bytes, validity_days=validity_days, client_enabled=client_enabled, expected_policy_version=expected_policy_version, idempotency_key=idempotency_key, updated_by=updated_by, node_is_compatible=node_is_compatible, _positive_int=_positive_int, _bounded_nonnegative=_bounded_nonnegative, _nonempty=_nonempty, _default_client_enabled=_default_client_enabled, _payload_digest=_payload_digest, TelegramRegistryError=TelegramRegistryError, IdempotencyConflictError=IdempotencyConflictError, NodePolicyUnavailableError=NodePolicyUnavailableError, VersionConflictError=VersionConflictError, _policy_from_row=_policy_from_row, NodeProvisioningPolicy=NodeProvisioningPolicy)

    def list_provisioning_jobs(self, *, limit: int = 100) -> list[ProvisioningJobStatus]:
        return _telegram_registry_provisioning.list_provisioning_jobs(self, limit=limit, ProvisioningJobStatus=ProvisioningJobStatus, ProvisioningAttemptStatus=ProvisioningAttemptStatus, TelegramRegistryError=TelegramRegistryError)

    def list_provisioning_jobs_page(self, *, limit: int = 100, offset: int = 0) -> tuple[list[ProvisioningJobStatus], int]:
        return _telegram_registry_provisioning.list_provisioning_jobs_page(self, limit=limit, offset=offset, ProvisioningJobStatus=ProvisioningJobStatus, ProvisioningAttemptStatus=ProvisioningAttemptStatus, TelegramRegistryError=TelegramRegistryError)

    def clear_terminal_provisioning_history(self, *, idempotency_key: object, cleared_by: object) -> int:
        return _telegram_registry_provisioning.clear_terminal_provisioning_history(self, idempotency_key=idempotency_key, cleared_by=cleared_by, _nonempty=_nonempty, _payload_digest=_payload_digest, TelegramRegistryError=TelegramRegistryError, IdempotencyConflictError=IdempotencyConflictError)

    def history_overview(self) -> dict[str, dict[str, int]]:
        return _telegram_registry_provisioning.history_overview(self)

    def history_clear_count(self, section: str, node_id: int | None = None) -> int:
        return _telegram_registry_provisioning.history_clear_count(self, section=section, node_id=node_id, _positive_int=_positive_int, TelegramRegistryError=TelegramRegistryError)

    def list_missing_binding_nodes(self) -> list[dict[str, Any]]:
        return _telegram_registry_provisioning.list_missing_binding_nodes(self)

    def list_customer_operations_page(self, *, limit: int = 100, offset: int = 0) -> tuple[list[CustomerOperationStatus], int]:
        return _telegram_registry_provisioning.list_customer_operations_page(self, limit=limit, offset=offset, TelegramRegistryError=TelegramRegistryError, CustomerOperationStatus=CustomerOperationStatus)

    def dismissed_operation_ids(self, operation_ids: list[int]) -> set[int]:
        return _telegram_registry_provisioning.dismissed_operation_ids(self, operation_ids=operation_ids)

    def list_bindings_page(self, *, management_state: str | None = None, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        return _telegram_registry_provisioning.list_bindings_page(self, management_state=management_state, limit=limit, offset=offset, TelegramRegistryError=TelegramRegistryError)

    def list_audit_page(self, *, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        return _telegram_registry_provisioning.list_audit_page(self, limit=limit, offset=offset, TelegramRegistryError=TelegramRegistryError)

    def clear_customer_operation_history(self, *, idempotency_key: object, cleared_by: object) -> int:
        return _telegram_registry_provisioning.clear_customer_operation_history(self, idempotency_key=idempotency_key, cleared_by=cleared_by, _nonempty=_nonempty, _payload_digest=_payload_digest, IdempotencyConflictError=IdempotencyConflictError)

    def clear_drift_history(self, *, idempotency_key: object, cleared_by: object) -> int:
        return _telegram_registry_provisioning.clear_drift_history(self, idempotency_key=idempotency_key, cleared_by=cleared_by, _nonempty=_nonempty, _payload_digest=_payload_digest, IdempotencyConflictError=IdempotencyConflictError)

    def forget_all_missing_bindings(self, *, node_id: int | None, actor: object, idempotency_key: object) -> dict[str, Any]:
        return _telegram_registry_provisioning.forget_all_missing_bindings(self, node_id=node_id, actor=actor, idempotency_key=idempotency_key, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int, IdempotencyConflictError=IdempotencyConflictError)

    def run_history_retention(self) -> dict[str, int]:
        return _telegram_registry_provisioning.run_history_retention(self)

    def get_provisioning_job(self, job_id: int) -> ProvisioningJobStatus:
        return _telegram_registry_provisioning.get_provisioning_job(self, job_id=job_id, _positive_int=_positive_int, TelegramRegistryError=TelegramRegistryError, ProvisioningJobStatus=ProvisioningJobStatus, ProvisioningAttemptStatus=ProvisioningAttemptStatus)

    def reschedule_provisioning_job(
        self,
        *,
        job_id: int,
        expected_job_version: int,
        idempotency_key: str,
        requested_by: str,
        action: str,
    ) -> ProvisioningRescheduleResult:
        return _telegram_registry_provisioning.reschedule_provisioning_job(self, job_id=job_id, expected_job_version=expected_job_version, idempotency_key=idempotency_key, requested_by=requested_by, action=action, _positive_int=_positive_int, _nonempty=_nonempty, _payload_digest=_payload_digest, TelegramRegistryError=TelegramRegistryError, IdempotencyConflictError=IdempotencyConflictError, VersionConflictError=VersionConflictError, ProvisioningRescheduleResult=ProvisioningRescheduleResult)

    def list_node_provisioning_policies(self) -> list[NodeProvisioningPolicy]:
        return _telegram_registry_provisioning.list_node_provisioning_policies(self, _policy_from_row=_policy_from_row, NodeProvisioningPolicy=NodeProvisioningPolicy)

    @staticmethod
    def _node_bulk_action(value: str) -> str:
        return _telegram_registry_nodeops._node_bulk_action(
            value, error_type=TelegramRegistryError
        )

    def _node_bulk_action_snapshot(
        self, conn: sqlite3.Connection, *, node_id: int, action: str, page: int
    ) -> tuple[NodeBulkActionPreview, tuple[dict[str, Any], ...]]:
        return _telegram_registry_nodeops._node_bulk_action_snapshot(
            self, conn, node_id=node_id, action=action, page=page,
            error_type=TelegramRegistryError,
            node_policy_error=NodePolicyUnavailableError,
            lifecycle_error=LifecycleUnavailableError,
            preview_type=NodeBulkActionPreview, payload_digest=_payload_digest,
        )

    def preview_node_bulk_action(
        self, *, node_id: int, action: str, page: int = 0
    ) -> NodeBulkActionPreview:
        return _telegram_registry_nodeops.preview_node_bulk_action(
            self, node_id=node_id, action=action, page=page,
            positive_int=_positive_int, error_type=TelegramRegistryError,
            node_policy_error=NodePolicyUnavailableError,
            lifecycle_error=LifecycleUnavailableError,
            preview_type=NodeBulkActionPreview, payload_digest=_payload_digest,
        )

    def begin_node_bulk_action_preview(
        self, *, admin_telegram_user_id: int, node_id: int, action: str, page: int
    ) -> NodeBulkActionPreview:
        return _telegram_registry_nodeops.begin_node_bulk_action_preview(
            self, admin_telegram_user_id=admin_telegram_user_id, node_id=node_id,
            action=action, page=page, positive_int=_positive_int,
            error_type=TelegramRegistryError,
            node_policy_error=NodePolicyUnavailableError,
            lifecycle_error=LifecycleUnavailableError,
            preview_type=NodeBulkActionPreview, payload_digest=_payload_digest,
        )

    def clear_node_bulk_action_preview(self, admin_telegram_user_id: int) -> None:
        return _telegram_registry_nodeops.clear_node_bulk_action_preview(
            self, admin_telegram_user_id, positive_int=_positive_int
        )

    def queue_node_bulk_action(
        self,
        *,
        admin_telegram_user_id: int,
        node_id: int,
        action: str,
        idempotency_key: str,
        created_by: str,
    ) -> NodeBulkActionQueueResult:
        return _telegram_registry_nodeops.queue_node_bulk_action(
            self, admin_telegram_user_id=admin_telegram_user_id, node_id=node_id,
            action=action, idempotency_key=idempotency_key, created_by=created_by,
            positive_int=_positive_int, nonempty=_nonempty,
            payload_digest=_payload_digest, error_type=TelegramRegistryError,
            node_policy_error=NodePolicyUnavailableError,
            lifecycle_error=LifecycleUnavailableError,
            version_conflict_error=VersionConflictError,
            idempotency_conflict_error=IdempotencyConflictError,
            queue_result_type=NodeBulkActionQueueResult,
            preview_type=NodeBulkActionPreview,
            mark_completed_initial_snapshot=mark_completed_initial_snapshot,
            inbound_id=BOT_INBOUND_ID, client_flow=BOT_CLIENT_FLOW,
        )

    @staticmethod
    def _customer_node_state_counts(conn: sqlite3.Connection, customer_ids: Iterable[int]) -> dict[int, dict[str, int]]:
        return _telegram_registry_nodeops._customer_node_state_counts(
            conn, customer_ids, classify_customer_node_state=_classify_customer_node_state,
            node_states=NODE_STATES,
        )

    def customer_node_matrix(self, customer_id: int) -> list[CustomerNodeMatrixRow]:
        return _telegram_registry_nodeops.customer_node_matrix(
            self, customer_id, positive_int=_positive_int,
            error_type=TelegramRegistryError,
            classify_customer_node_state=_classify_customer_node_state,
            matrix_row_type=CustomerNodeMatrixRow,
        )

    def queue_customer_node_add(
        self,
        *,
        customer_id: int,
        node_id: int,
        expected_customer_version: int,
        idempotency_key: str,
        created_by: str,
    ) -> NodeProvisioningQueueResult:
        return _telegram_registry_nodeops.queue_customer_node_add(
            self, customer_id=customer_id, node_id=node_id,
            expected_customer_version=expected_customer_version,
            idempotency_key=idempotency_key, created_by=created_by,
            positive_int=_positive_int, nonempty=_nonempty,
            payload_digest=_payload_digest, error_type=TelegramRegistryError,
            lifecycle_error=LifecycleUnavailableError,
            version_conflict_error=VersionConflictError,
            idempotency_conflict_error=IdempotencyConflictError,
            node_policy_error=NodePolicyUnavailableError,
            queue_result_type=NodeProvisioningQueueResult,
            inbound_id=BOT_INBOUND_ID, client_flow=BOT_CLIENT_FLOW,
        )

    def list_customers(self, *, query: str='', status: str | None=None, page: int=1, page_size: int=50, include_deleted: bool=False) -> CustomerPage:
        """Page local customers only; fleet discovery remains a separate safe workflow."""
        return _telegram_registry_customerops.list_customers(self, query=query, status=status, page=page, page_size=page_size, include_deleted=include_deleted, CustomerListItem=CustomerListItem, CustomerPage=CustomerPage, TelegramRegistryError=TelegramRegistryError)

    def get_customer(self, customer_id: int) -> CustomerListItem:
        return _telegram_registry_customerops.get_customer(self, customer_id, CustomerListItem=CustomerListItem, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def get_customer_telegram_profile(self, customer_id: int) -> CustomerTelegramProfile:
        """Return the one display-safe Telegram identity bound to a customer."""
        return _telegram_registry_customerops.get_customer_telegram_profile(self, customer_id, CustomerTelegramProfile=CustomerTelegramProfile, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def get_customer_admin_note(self, customer_id: int) -> CustomerAdminNote | None:
        """Return the private override note without exposing it through public APIs."""
        return _telegram_registry_customerops.get_customer_admin_note(self, customer_id, CustomerAdminNote=CustomerAdminNote, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def get_customer_registration_introduction(self, customer_id: int) -> str | None:
        """Return the approved registration text retained as the historical source."""
        return _telegram_registry_customerops.get_customer_registration_introduction(self, customer_id, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def set_customer_admin_note(self, *, customer_id: int, body: str, updated_by_telegram_user_id: int) -> CustomerAdminNote:
        """Create or replace an administrator-only customer note atomically."""
        return _telegram_registry_customerops.set_customer_admin_note(self, customer_id=customer_id, body=body, updated_by_telegram_user_id=updated_by_telegram_user_id, CustomerAdminNote=CustomerAdminNote, TelegramRegistryError=TelegramRegistryError, _payload_digest=_payload_digest, _positive_int=_positive_int)

    @staticmethod
    def _registered_broadcast_recipient_ids(conn: sqlite3.Connection) -> list[int]:
        return _telegram_registry_customerops._registered_broadcast_recipient_ids(conn)

    def registered_broadcast_recipient_count(self) -> int:
        return _telegram_registry_customerops.registered_broadcast_recipient_count(self)

    def queue_admin_direct_message(self, *, customer_id: int, body: str, created_by: int | str, idempotency_key: str, photo_file_ids: tuple[str, ...] | None=None) -> int:
        """Queue one admin message to an already approved, live Telegram user."""
        return _telegram_registry_customerops.queue_admin_direct_message(self, customer_id=customer_id, body=body, created_by=created_by, idempotency_key=idempotency_key, photo_file_ids=photo_file_ids, TelegramRegistryError=TelegramRegistryError, _nonempty=_nonempty, _normalize_admin_message_body=_normalize_admin_message_body, _positive_int=_positive_int)

    def queue_registered_broadcast(self, *, body: str, created_by: int, idempotency_key: str, photo_file_ids: tuple[str, ...] | None=None) -> BroadcastQueueResult:
        """Snapshot opted-in registered users into durable per-recipient outbox rows."""
        return _telegram_registry_customerops.queue_registered_broadcast(self, body=body, created_by=created_by, idempotency_key=idempotency_key, photo_file_ids=photo_file_ids, BroadcastQueueResult=BroadcastQueueResult, TelegramRegistryError=TelegramRegistryError, _normalize_admin_message_body=_normalize_admin_message_body, _positive_int=_positive_int)

    @staticmethod
    def _lifecycle_operation_type(value: str) -> str:
        return _telegram_registry_customerops._lifecycle_operation_type(value, TelegramRegistryError=TelegramRegistryError)

    @staticmethod
    def _forget_missing_binding(conn, binding_id: int, *, actor_type: str, actor_id: str) -> bool:
        return _telegram_registry_customerops._forget_missing_binding(conn, binding_id, actor_type=actor_type, actor_id=actor_id)

    def forget_missing_bindings(self, customer_id: int, actor: str) -> dict[str, Any]:
        """Drop bindings marked 'missing' (client is gone from the panel and the admin does not want it back).

            Traffic totals live in separate ledgers keyed by customer/node, so nothing is lost; a client that
            reappears on the panel is found by the drift scan as an unknown remote client again.
            """
        return _telegram_registry_customerops.forget_missing_bindings(self, customer_id, actor, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def repair_customer(self, customer_id: int, actor: str) -> dict[str, Any]:
        return _telegram_registry_customerops.repair_customer(self, customer_id, actor, INITIAL_JOB_COMPLETE_SQL=INITIAL_JOB_COMPLETE_SQL, TelegramRegistryError=TelegramRegistryError, _fresh_snapshot_has_client=_fresh_snapshot_has_client, _positive_int=_positive_int)

    def _customer_operation_snapshot(self, conn: sqlite3.Connection, *, customer_id: int, operation_type: str) -> tuple[CustomerOperationPreview, tuple[dict[str, Any], ...]]:
        """Build an exact, private target snapshot without doing remote I/O."""
        return _telegram_registry_customerops._customer_operation_snapshot(self, conn, customer_id=customer_id, operation_type=operation_type, CustomerOperationPreview=CustomerOperationPreview, CustomerOperationTarget=CustomerOperationTarget, LifecycleUnavailableError=LifecycleUnavailableError, TelegramRegistryError=TelegramRegistryError, _payload_digest=_payload_digest)

    def preview_customer_operation(self, *, customer_id: int, operation_type: str) -> CustomerOperationPreview:
        return _telegram_registry_customerops.preview_customer_operation(self, customer_id=customer_id, operation_type=operation_type, CustomerOperationPreview=CustomerOperationPreview, _positive_int=_positive_int)

    @staticmethod
    def _node_operation_type(value: str) -> str:
        return _telegram_registry_customerops._node_operation_type(value, TelegramRegistryError=TelegramRegistryError)

    def _customer_node_operation_snapshot(self, conn: sqlite3.Connection, *, customer_id: int, node_id: int, operation_type: str) -> tuple[CustomerOperationPreview, dict[str, Any]]:
        return _telegram_registry_customerops._customer_node_operation_snapshot(self, conn, customer_id=customer_id, node_id=node_id, operation_type=operation_type, CustomerOperationPreview=CustomerOperationPreview, CustomerOperationTarget=CustomerOperationTarget, LifecycleUnavailableError=LifecycleUnavailableError, TelegramRegistryError=TelegramRegistryError, _payload_digest=_payload_digest)

    def preview_customer_node_operation(self, *, customer_id: int, node_id: int, operation_type: str) -> CustomerOperationPreview:
        return _telegram_registry_customerops.preview_customer_node_operation(self, customer_id=customer_id, node_id=node_id, operation_type=operation_type, CustomerOperationPreview=CustomerOperationPreview, _positive_int=_positive_int)

    def queue_customer_node_operation(self, *, customer_id: int, node_id: int, operation_type: str, expected_customer_version: int, target_snapshot_digest: str, idempotency_key: str, created_by: str) -> CustomerOperationQueueResult:
        return _telegram_registry_customerops.queue_customer_node_operation(self, customer_id=customer_id, node_id=node_id, operation_type=operation_type, expected_customer_version=expected_customer_version, target_snapshot_digest=target_snapshot_digest, idempotency_key=idempotency_key, created_by=created_by, CustomerOperationQueueResult=CustomerOperationQueueResult, IdempotencyConflictError=IdempotencyConflictError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def _get_customer_operation_from_conn(self, conn: sqlite3.Connection, operation_id: int) -> CustomerOperationStatus:
        return _telegram_registry_customerops._get_customer_operation_from_conn(self, conn, operation_id, CustomerOperationAttemptStatus=CustomerOperationAttemptStatus, CustomerOperationStatus=CustomerOperationStatus, TelegramRegistryError=TelegramRegistryError)

    def queue_customer_operation(self, *, customer_id: int, operation_type: str, expected_customer_version: int, target_snapshot_digest: str, idempotency_key: str, created_by: str) -> CustomerOperationQueueResult:
        """Queue a lifecycle operation after proving its preview is still current.

            This transaction intentionally does not touch a node. A worker must later
            claim these immutable attempts, read the remote client, and reconcile
            before it writes anything.
            """
        return _telegram_registry_customerops.queue_customer_operation(self, customer_id=customer_id, operation_type=operation_type, expected_customer_version=expected_customer_version, target_snapshot_digest=target_snapshot_digest, idempotency_key=idempotency_key, created_by=created_by, CustomerOperationQueueResult=CustomerOperationQueueResult, IdempotencyConflictError=IdempotencyConflictError, LifecycleUnavailableError=LifecycleUnavailableError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def get_customer_operation(self, operation_id: int) -> CustomerOperationStatus:
        return _telegram_registry_customerops.get_customer_operation(self, operation_id, CustomerOperationStatus=CustomerOperationStatus, _positive_int=_positive_int)

    def list_customer_operations(self, *, customer_id: int, limit: int=100) -> list[CustomerOperationStatus]:
        return _telegram_registry_customerops.list_customer_operations(self, customer_id=customer_id, limit=limit, CustomerOperationStatus=CustomerOperationStatus, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def reschedule_customer_operation(self, *, operation_id: int, expected_operation_version: int, idempotency_key: str, requested_by: str, action: str) -> CustomerOperationRescheduleResult:
        """Queue a read-first lifecycle retry; conflict targets require manual repair."""
        return _telegram_registry_customerops.reschedule_customer_operation(self, operation_id=operation_id, expected_operation_version=expected_operation_version, idempotency_key=idempotency_key, requested_by=requested_by, action=action, CustomerOperationRescheduleResult=CustomerOperationRescheduleResult, IdempotencyConflictError=IdempotencyConflictError, LifecycleUnavailableError=LifecycleUnavailableError, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def get_admin_dashboard(self) -> TelegramAdminDashboard:
        """Return only local operational counts; never probes a node."""
        return _telegram_registry_customerops.get_admin_dashboard(self, TelegramAdminDashboard=TelegramAdminDashboard)

    def list_attention_items(self, *, limit: int=100) -> dict[str, list[Any]]:
        """Jobs and lifecycle operations counted by get_admin_dashboard, so the UI can act on them."""
        return _telegram_registry_customerops.list_attention_items(self, limit=limit, TelegramRegistryError=TelegramRegistryError)

    def list_customer_tags(self, customer_id: int) -> tuple[CustomerTag, ...]:
        return _telegram_registry_customerops.list_customer_tags(self, customer_id, CustomerTag=CustomerTag, _positive_int=_positive_int)

    def set_customer_tags(self, *, customer_id: int, tags: object, updated_by: str) -> tuple[CustomerTag, ...]:
        return _telegram_registry_customerops.set_customer_tags(self, customer_id=customer_id, tags=tags, updated_by=updated_by, CustomerTag=CustomerTag, TelegramRegistryError=TelegramRegistryError, _nonempty=_nonempty, _normalize_tags=_normalize_tags, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def list_saved_filters(self, *, admin_username: str) -> tuple[TelegramSavedFilter, ...]:
        return _telegram_registry_customerops.list_saved_filters(self, admin_username=admin_username, TelegramRegistryError=TelegramRegistryError, TelegramSavedFilter=TelegramSavedFilter, _nonempty=_nonempty, _normalize_tags=_normalize_tags)

    def save_filter(self, *, admin_username: str, name: object, query: object, status: object, tags: object) -> TelegramSavedFilter:
        return _telegram_registry_customerops.save_filter(self, admin_username=admin_username, name=name, query=query, status=status, tags=tags, TelegramRegistryError=TelegramRegistryError, TelegramSavedFilter=TelegramSavedFilter, _nonempty=_nonempty, _normalize_tags=_normalize_tags)

    def delete_saved_filter(self, *, admin_username: str, filter_id: int) -> None:
        return _telegram_registry_customerops.delete_saved_filter(self, admin_username=admin_username, filter_id=filter_id, TelegramRegistryError=TelegramRegistryError, _nonempty=_nonempty, _positive_int=_positive_int)

    def customer_timeline(self, *, customer_id: int, limit: int=100) -> tuple[CustomerTimelineEvent, ...]:
        return _telegram_registry_customerops.customer_timeline(self, customer_id=customer_id, limit=limit, CustomerTimelineEvent=CustomerTimelineEvent, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def get_customer_read_only_view(self, customer_id: int) -> dict[str, Any]:
        """A no-token projection of what the linked person can currently see."""
        return _telegram_registry_customerops.get_customer_read_only_view(self, customer_id, initial_job_incomplete=initial_job_incomplete)

    def create_lifecycle_schedule(self, *, customer_id: int, operation_type: object, execute_not_before: object, expected_customer_version: int, target_snapshot_digest: str, idempotency_key: str, created_by: str) -> LifecycleSchedule:
        """Store a cancellable grace-period command, without touching a node."""
        return _telegram_registry_customerops.create_lifecycle_schedule(self, customer_id=customer_id, operation_type=operation_type, execute_not_before=execute_not_before, expected_customer_version=expected_customer_version, target_snapshot_digest=target_snapshot_digest, idempotency_key=idempotency_key, created_by=created_by, IdempotencyConflictError=IdempotencyConflictError, LifecycleSchedule=LifecycleSchedule, LifecycleUnavailableError=LifecycleUnavailableError, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _parse_future_timestamp=_parse_future_timestamp, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def _schedule_from_row(self, row: tuple[Any, ...]) -> LifecycleSchedule:
        return _telegram_registry_customerops._schedule_from_row(self, row, LifecycleSchedule=LifecycleSchedule)

    def list_lifecycle_schedules(self, *, customer_id: int | None=None, status: str='all', limit: int=100) -> tuple[LifecycleSchedule, ...]:
        return _telegram_registry_customerops.list_lifecycle_schedules(self, customer_id=customer_id, status=status, limit=limit, LifecycleSchedule=LifecycleSchedule, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def cancel_lifecycle_schedule(self, *, schedule_id: int, expected_row_version: int, cancelled_by: str, reason: object=None) -> LifecycleSchedule:
        return _telegram_registry_customerops.cancel_lifecycle_schedule(self, schedule_id=schedule_id, expected_row_version=expected_row_version, cancelled_by=cancelled_by, reason=reason, LifecycleSchedule=LifecycleSchedule, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest, _positive_int=_positive_int)

    def claim_due_lifecycle_schedule(self, *, worker_id: str, now: datetime | None=None, lease_seconds: int=60) -> LifecycleSchedule | None:
        return _telegram_registry_customerops.claim_due_lifecycle_schedule(self, worker_id=worker_id, now=now, lease_seconds=lease_seconds, LifecycleSchedule=LifecycleSchedule, TelegramRegistryError=TelegramRegistryError, _nonempty=_nonempty, _timestamp=_timestamp, _utc_now=_utc_now)

    def complete_lifecycle_schedule(self, *, schedule_id: int, operation_id: int | None, outcome: str) -> None:
        return _telegram_registry_customerops.complete_lifecycle_schedule(self, schedule_id=schedule_id, operation_id=operation_id, outcome=outcome, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _positive_int=_positive_int)

    @staticmethod
    def _bulk_preview_digest(operation_type: str, items: Iterable[BulkLifecyclePreviewItem]) -> str:
        return _telegram_registry_customerops._bulk_preview_digest(operation_type, items, BulkLifecyclePreviewItem=BulkLifecyclePreviewItem, _payload_digest=_payload_digest)

    def preview_bulk_customer_operations(self, *, customer_ids: object, operation_type: object) -> BulkLifecyclePreview:
        return _telegram_registry_customerops.preview_bulk_customer_operations(self, customer_ids=customer_ids, operation_type=operation_type, BulkLifecyclePreview=BulkLifecyclePreview, BulkLifecyclePreviewItem=BulkLifecyclePreviewItem, LifecycleUnavailableError=LifecycleUnavailableError, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    @staticmethod
    def _parse_bulk_preview_items(values: object) -> tuple[BulkLifecyclePreviewItem, ...]:
        return _telegram_registry_customerops._parse_bulk_preview_items(values, BulkLifecyclePreviewItem=BulkLifecyclePreviewItem, TelegramRegistryError=TelegramRegistryError, _nonempty=_nonempty, _positive_int=_positive_int)

    def _insert_bulk_lifecycle_operation(self, conn: sqlite3.Connection, *, preview: CustomerOperationPreview, private_targets: list[dict[str, Any]], operation_type: str, idempotency_key: str, created_by: str) -> CustomerOperationQueueResult:
        """Insert the same immutable records as a normal lifecycle command.

            The caller has already revalidated every member in one transaction;
            this helper intentionally does no remote I/O and does not expose the
            target identifiers in its return value.
            """
        return _telegram_registry_customerops._insert_bulk_lifecycle_operation(self, conn, preview=preview, private_targets=private_targets, operation_type=operation_type, idempotency_key=idempotency_key, created_by=created_by, CustomerOperationPreview=CustomerOperationPreview, CustomerOperationQueueResult=CustomerOperationQueueResult, VersionConflictError=VersionConflictError)

    def queue_bulk_customer_operations(self, *, operation_type: object, target_snapshot_digest: object, items: object, idempotency_key: str, created_by: str) -> BulkLifecycleStatus:
        """Atomically queue a reviewed batch of normal lifecycle operations."""
        return _telegram_registry_customerops.queue_bulk_customer_operations(self, operation_type=operation_type, target_snapshot_digest=target_snapshot_digest, items=items, idempotency_key=idempotency_key, created_by=created_by, BulkLifecycleStatus=BulkLifecycleStatus, CustomerOperationPreview=CustomerOperationPreview, IdempotencyConflictError=IdempotencyConflictError, TelegramRegistryError=TelegramRegistryError, VersionConflictError=VersionConflictError, _nonempty=_nonempty, _payload_digest=_payload_digest)

    def get_bulk_lifecycle_status(self, bulk_job_id: int) -> BulkLifecycleStatus:
        return _telegram_registry_customerops.get_bulk_lifecycle_status(self, bulk_job_id, BulkLifecycleItemStatus=BulkLifecycleItemStatus, BulkLifecycleStatus=BulkLifecycleStatus, TelegramRegistryError=TelegramRegistryError, _positive_int=_positive_int)

    def drift_inventory(self, *, node_ids: object = None) -> dict[str, Any]:
        return _telegram_registry_drift.drift_inventory(
            self, node_ids=node_ids, error_type=TelegramRegistryError, positive_int=_positive_int
        )

    def sync_drift_binding_enabled(self, candidates: list[dict[str, Any]]) -> None:
        return _telegram_registry_drift.sync_drift_binding_enabled(self, candidates)

    def record_drift_findings(self, *, scanned_node_ids: object, findings: object) -> tuple[DriftFinding, ...]:
        return _telegram_registry_drift.record_drift_findings(
            self, scanned_node_ids=scanned_node_ids, findings=findings,
            error_type=TelegramRegistryError, positive_int=_positive_int,
            payload_digest=_payload_digest, list_drift_findings=self.list_drift_findings,
            finding_type=DriftFinding,
        )

    def auto_forget_drift_binding(self, finding_id: int, version: int) -> None:
        return _telegram_registry_drift.auto_forget_drift_binding(
            self, finding_id, version, forget_missing_binding=self._forget_missing_binding
        )

    def list_drift_findings(
        self, *, status: str = "open", limit: int = 100, offset: int = 0
    ) -> tuple[DriftFinding, ...]:
        return _telegram_registry_drift.list_drift_findings(
            self, status=status, limit=limit, offset=offset,
            error_type=TelegramRegistryError, finding_type=DriftFinding,
        )

    def resolve_drift_finding(
        self, *, finding_id: int, expected_row_version: int, status: str, resolved_by: str
    ) -> DriftFinding:
        return _telegram_registry_drift.resolve_drift_finding(
            self, finding_id=finding_id, expected_row_version=expected_row_version,
            status=status, resolved_by=resolved_by, positive_int=_positive_int,
            nonempty=_nonempty, error_type=TelegramRegistryError,
            version_conflict_error=VersionConflictError, list_drift_findings=self.list_drift_findings,
        )

    @staticmethod
    def _insert_adopted_binding(conn, *, customer_id, node_id, remote_client_id, remote_sub_id, remote_email, remote_enabled):
        return _telegram_registry_drift._insert_adopted_binding(
            conn, customer_id=customer_id, node_id=node_id, remote_client_id=remote_client_id,
            remote_sub_id=remote_sub_id, remote_email=remote_email, remote_enabled=remote_enabled,
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
    ) -> DriftFinding | None:
        return _telegram_registry_drift.adopt_drift_binding(
            self, finding_id=finding_id, expected_row_version=expected_row_version,
            remote_email=remote_email, remote_client_id=remote_client_id, remote_sub_id=remote_sub_id,
            remote_enabled=remote_enabled, adopted_by=adopted_by, automatic=automatic,
            positive_int=_positive_int, nonempty=_nonempty, canonicalize_email=canonicalize_email,
            version_conflict_error=VersionConflictError, insert_adopted_binding=self._insert_adopted_binding,
            list_drift_findings=self.list_drift_findings,
        )
