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
    ) -> TelegramTransportPreference:
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
        return self.get_transport_preference()

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

    def get_locale(self, telegram_user_id: int) -> str:
        user_id = _positive_int(telegram_user_id, "telegram_user_id")
        with connect(self._db_path) as conn:
            row = conn.execute("SELECT locale FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise TelegramRegistryError("telegram identity is unavailable")
        return "en" if row[0] == "en" else "ru"

    def set_locale(self, telegram_user_id: int, locale: object) -> str:
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

    def get_preapproval(self, telegram_user_id: int) -> TelegramPreapproval | None:
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
        return self._preapproval_from_row(row)

    @staticmethod
    def _preapproval_from_row(row: tuple[object, ...]) -> TelegramPreapproval:
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

    @staticmethod
    def _preapproval_from_receipt(payload: object) -> TelegramPreapproval:
        """Read both current and pre-profile idempotency receipts safely."""

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
    ) -> TelegramPreapproval:
        """Pre-authorize one numeric Telegram ID for one verified existing customer.

        The command is local-only. It cannot create remote clients, reveal a
        subscription URL, or overwrite a blocked/linked Telegram identity.
        Activation waits for the exact ID's first private ``/start``.
        """

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
                return self._preapproval_from_receipt(json.loads(str(receipt[1])))

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
            result = self._preapproval_from_row(preapproval)
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
    ) -> TelegramPreapproval:
        """Persist a future customer profile before its first private ``/start``.

        The selected Telegram provisioning targets are copied into the profile
        at command time. Activation later uses that immutable copy rather than
        whichever node-policy values happen to exist at activation time.
        """

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
                return self._preapproval_from_receipt(json.loads(str(receipt[1])))

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
            result = self._preapproval_from_row(row)
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

    def activate_preapproval(self, telegram_user_id: int) -> ExistingApprovalResult | ApprovalResult | None:
        """Consume a preapproval after the authorized user starts a private chat.

        Existing-customer profiles only bind a verified local customer. New
        profiles create a customer and queue attempts from their persisted
        target snapshot; they never re-read mutable node policies here.
        """

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
                return self._activate_new_customer_preapproval(
                    conn=conn, telegram_user_id=user_id, identity=identity, preapproval=preapproval
                )
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
    ) -> ApprovalResult | None:
        """Commit a new profile and its immutable provisioning attempts once."""

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
    ) -> TelegramUnlinkResult:
        """Remove only the local Telegram association; remote clients are untouched."""

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

    def safe_subscription_node_ids(self, email: str) -> frozenset[int] | None:
        """Return exact confirmed Telegram targets, or ``None`` for legacy users.

        This is local metadata only. A partial existing-adoption customer may
        receive artifacts only for bindings that the durable workers confirmed.
        """
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

    def enabled_node_ids(self) -> frozenset[int]:
        """Return enabled node ids from the local database only."""

        with connect(self._db_path) as conn:
            rows = conn.execute("SELECT id FROM nodes WHERE enabled = 1").fetchall()
        return frozenset(int(row[0]) for row in rows)

    def has_confirmed_enabled_subscription_binding(self, email: str) -> bool:
        """Return whether an older customer has a locally usable subscription target."""

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

    def get_customer_access(self, telegram_user_id: int) -> TelegramCustomerAccess:
        """Resolve approved access strictly from the numeric Telegram identity."""

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

    def get_interface_window(self, telegram_user_id: int) -> tuple[int, bool] | None:
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
    ) -> None:
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
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT username FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT first_name FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT last_name FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT COUNT(*) FROM customer_node_bindings AS b WHERE b.customer_id = c.id),
                       (SELECT lifetime_bytes FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                       (SELECT last_observed_at FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                       (SELECT a.introduction_text
                        FROM telegram_identities AS i
                        JOIN telegram_applications AS a
                          ON a.telegram_user_id = i.telegram_user_id
                         AND a.application_attempt = i.application_attempt
                        WHERE i.customer_id = c.id AND a.status = 'approved'
                          AND a.introduction_text IS NOT NULL
                        ORDER BY a.introduction_submitted_at DESC, a.id DESC LIMIT 1),
                       c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM telegram_support_requests AS tsr
                        WHERE tsr.customer_id = c.id AND tsr.status IN ('open', 'read'))
                """
                + base
                + " ORDER BY c.updated_at DESC, c.id DESC LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size],
            ).fetchall()
            node_state_counts = self._customer_node_state_counts(conn, [int(row[0]) for row in rows])
        return CustomerPage(
            items=tuple(
                CustomerListItem(
                    customer_id=int(row[0]), email_display=str(row[1]), origin=str(row[2]),
                    status=str(row[3]), row_version=int(row[4]),
                    telegram_user_id=int(row[5]) if row[5] is not None else None,
                    telegram_username=str(row[6]) if row[6] is not None else None,
                    telegram_first_name=str(row[7]) if row[7] is not None else None,
                    telegram_last_name=str(row[8]) if row[8] is not None else None,
                    node_count=int(row[9]),
                    nodes_active=node_state_counts[int(row[0])]["active"],
                    nodes_suspended=node_state_counts[int(row[0])]["suspended"],
                    nodes_available=node_state_counts[int(row[0])]["available_to_add"],
                    nodes_problem=node_state_counts[int(row[0])]["problem"],
                    lifetime_bytes=int(row[10]) if row[10] is not None else None,
                    traffic_observed_at=str(row[11]) if row[11] is not None else None,
                    application_introduction=str(row[12]) if row[12] is not None else None,
                    created_at=str(row[13]), updated_at=str(row[14]), open_support_count=int(row[15]),
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
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT username FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT first_name FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT last_name FROM telegram_identities AS ti
                        WHERE ti.customer_id = c.id
                        ORDER BY ti.access_status = 'approved' DESC, ti.created_at ASC, ti.telegram_user_id ASC LIMIT 1),
                       (SELECT COUNT(*) FROM customer_node_bindings AS b WHERE b.customer_id = c.id),
                       (SELECT lifetime_bytes FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                       (SELECT last_observed_at FROM customer_traffic_ledger AS ctl WHERE ctl.customer_id = c.id),
                       (SELECT a.introduction_text
                        FROM telegram_identities AS i
                        JOIN telegram_applications AS a
                          ON a.telegram_user_id = i.telegram_user_id
                         AND a.application_attempt = i.application_attempt
                        WHERE i.customer_id = c.id AND a.status = 'approved'
                          AND a.introduction_text IS NOT NULL
                        ORDER BY a.introduction_submitted_at DESC, a.id DESC LIMIT 1),
                       c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM telegram_support_requests AS tsr
                        WHERE tsr.customer_id = c.id AND tsr.status IN ('open', 'read'))
                FROM customers AS c
                WHERE c.id = ?
                """,
                (normalized_customer_id,),
            ).fetchone()
        if row is None:
            raise TelegramRegistryError("customer was not found")
        with connect(self._db_path) as conn:
            node_state_counts = self._customer_node_state_counts(conn, [normalized_customer_id])
        customer_counts = node_state_counts[normalized_customer_id]
        return CustomerListItem(
            customer_id=int(row[0]), email_display=str(row[1]), origin=str(row[2]), status=str(row[3]),
            row_version=int(row[4]), telegram_user_id=int(row[5]) if row[5] is not None else None,
            telegram_username=str(row[6]) if row[6] is not None else None,
            telegram_first_name=str(row[7]) if row[7] is not None else None,
            telegram_last_name=str(row[8]) if row[8] is not None else None,
            node_count=int(row[9]),
            nodes_active=customer_counts["active"],
            nodes_suspended=customer_counts["suspended"],
            nodes_available=customer_counts["available_to_add"],
            nodes_problem=customer_counts["problem"],
            lifetime_bytes=int(row[10]) if row[10] is not None else None,
            traffic_observed_at=str(row[11]) if row[11] is not None else None,
            application_introduction=str(row[12]) if row[12] is not None else None,
            created_at=str(row[13]), updated_at=str(row[14]), open_support_count=int(row[15]),
        )

    def get_customer_telegram_profile(self, customer_id: int) -> CustomerTelegramProfile:
        """Return the one display-safe Telegram identity bound to a customer."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            customer_exists = conn.execute(
                "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
            ).fetchone()
            if customer_exists is None:
                raise TelegramRegistryError("customer was not found")
            row = conn.execute(
                """
                SELECT telegram_user_id, username, first_name, last_name, phone_number
                FROM telegram_identities
                WHERE customer_id = ?
                ORDER BY access_status = 'approved' DESC, created_at ASC, telegram_user_id ASC
                LIMIT 1
                """,
                (local_customer_id,),
            ).fetchone()
        if row is None:
            return CustomerTelegramProfile(local_customer_id, None, None, None, None, None)
        return CustomerTelegramProfile(
            customer_id=local_customer_id,
            telegram_user_id=int(row[0]),
            username=str(row[1]) if row[1] is not None else None,
            first_name=str(row[2]) if row[2] is not None else None,
            last_name=str(row[3]) if row[3] is not None else None,
            phone_number=str(row[4]) if row[4] is not None else None,
        )

    def get_customer_admin_note(self, customer_id: int) -> CustomerAdminNote | None:
        """Return the private override note without exposing it through public APIs."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            customer_exists = conn.execute(
                "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
            ).fetchone()
            if customer_exists is None:
                raise TelegramRegistryError("customer was not found")
            row = conn.execute(
                """
                SELECT body, updated_by_telegram_user_id, updated_at
                FROM telegram_customer_notes
                WHERE customer_id = ?
                """,
                (local_customer_id,),
            ).fetchone()
        if row is None:
            return None
        return CustomerAdminNote(
            customer_id=local_customer_id,
            body=str(row[0]),
            updated_by_telegram_user_id=int(row[1]),
            updated_at=str(row[2]),
        )

    def get_customer_registration_introduction(self, customer_id: int) -> str | None:
        """Return the approved registration text retained as the historical source."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            customer_exists = conn.execute(
                "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
            ).fetchone()
            if customer_exists is None:
                raise TelegramRegistryError("customer was not found")
            row = conn.execute(
                """
                SELECT a.introduction_text
                FROM telegram_identities AS i
                JOIN telegram_applications AS a
                  ON a.telegram_user_id = i.telegram_user_id
                 AND a.application_attempt = i.application_attempt
                WHERE i.customer_id = ?
                  AND a.status = 'approved'
                  AND a.introduction_text IS NOT NULL
                ORDER BY a.introduction_submitted_at DESC, a.id DESC
                LIMIT 1
                """,
                (local_customer_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def set_customer_admin_note(
        self,
        *,
        customer_id: int,
        body: str,
        updated_by_telegram_user_id: int,
    ) -> CustomerAdminNote:
        """Create or replace an administrator-only customer note atomically."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        admin_id = _positive_int(updated_by_telegram_user_id, "updated_by_telegram_user_id")
        normalized_body = body.strip() if isinstance(body, str) else ""
        if not 1 <= len(normalized_body) <= 1000:
            raise TelegramRegistryError("customer note must contain 1 to 1000 characters")
        with connect(self._db_path) as conn:
            customer_exists = conn.execute(
                "SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)
            ).fetchone()
            if customer_exists is None:
                raise TelegramRegistryError("customer was not found")
            identity_exists = conn.execute(
                "SELECT 1 FROM telegram_identities WHERE telegram_user_id = ?", (admin_id,)
            ).fetchone()
            if identity_exists is None:
                raise TelegramRegistryError("note author was not found")
            conn.execute(
                """
                INSERT INTO telegram_customer_notes (customer_id, body, updated_by_telegram_user_id)
                VALUES (?, ?, ?)
                ON CONFLICT(customer_id) DO UPDATE SET
                    body = excluded.body,
                    updated_by_telegram_user_id = excluded.updated_by_telegram_user_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (local_customer_id, normalized_body, admin_id),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('customer_note_updated', 'admin', ?, 'customer', ?, ?)
                """,
                (str(admin_id), str(local_customer_id), _payload_digest({"body": normalized_body})),
            )
            row = conn.execute(
                """
                SELECT body, updated_by_telegram_user_id, updated_at
                FROM telegram_customer_notes WHERE customer_id = ?
                """,
                (local_customer_id,),
            ).fetchone()
        assert row is not None
        return CustomerAdminNote(
            customer_id=local_customer_id,
            body=str(row[0]),
            updated_by_telegram_user_id=int(row[1]),
            updated_at=str(row[2]),
        )

    @staticmethod
    def _registered_broadcast_recipient_ids(conn: sqlite3.Connection) -> list[int]:
        rows = conn.execute(
            """
            SELECT DISTINCT i.telegram_user_id
            FROM telegram_identities AS i
            JOIN customers AS c ON c.id = i.customer_id
            LEFT JOIN telegram_notification_preferences AS p ON p.telegram_user_id = i.telegram_user_id
            WHERE i.access_status = 'approved'
              AND c.deleted_at IS NULL
              AND c.status NOT IN ('deleting', 'delete_partial', 'deleted')
              AND COALESCE(p.background_notifications_enabled, 1) = 1
            ORDER BY i.telegram_user_id
            """
        ).fetchall()
        return [int(row[0]) for row in rows]

    def registered_broadcast_recipient_count(self) -> int:
        with connect(self._db_path) as conn:
            return len(self._registered_broadcast_recipient_ids(conn))

    def queue_admin_direct_message(
        self,
        *,
        customer_id: int,
        body: str,
        created_by: int | str,
        idempotency_key: str,
        photo_file_ids: tuple[str, ...] | None = None,
    ) -> int:
        """Queue one admin message to an already approved, live Telegram user."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        if isinstance(created_by, bool):
            raise TelegramRegistryError("created_by is invalid")
        if isinstance(created_by, int):
            admin_id = str(_positive_int(created_by, "created_by"))
        elif isinstance(created_by, str):
            admin_id = _nonempty(created_by, "created_by")
        else:
            raise TelegramRegistryError("created_by is invalid")
        normalized_body = _normalize_admin_message_body(body)
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 180:
            raise TelegramRegistryError("idempotency key is invalid")
        if photo_file_ids and (len(photo_file_ids) > 10 or len(normalized_body) > 1024 or
                               any(not isinstance(item, str) or not item for item in photo_file_ids)):
            raise TelegramRegistryError("invalid direct message photos")
        photos_json = json.dumps(photo_file_ids, ensure_ascii=False) if photo_file_ids else None
        digest = hashlib.sha256((normalized_body + (photos_json or "")).encode("utf-8")).hexdigest()
        with connect(self._db_path) as conn:
            recipient = conn.execute(
                """
                SELECT i.telegram_user_id
                FROM telegram_identities AS i
                JOIN customers AS c ON c.id = i.customer_id
                WHERE c.id = ? AND c.deleted_at IS NULL AND c.status NOT IN ('deleting', 'delete_partial', 'deleted')
                  AND i.access_status = 'approved'
                ORDER BY i.created_at ASC, i.telegram_user_id ASC
                LIMIT 1
                """,
                (local_customer_id,),
            ).fetchone()
            if recipient is None:
                raise TelegramRegistryError("customer has no active Telegram contact")
            recipient_id = int(recipient[0])
            cursor = conn.execute(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key, payload_json)
                VALUES ('admin_direct_message', ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (str(recipient_id), f"admin-direct:{key}", json.dumps({"body": normalized_body, **({"photo_file_ids": photo_file_ids} if photo_file_ids else {})}, ensure_ascii=False)),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT id FROM telegram_outbox WHERE dedupe_key = ?", (f"admin-direct:{key}",)
                ).fetchone()
                assert row is not None
                return int(row[0])
            outbox_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('admin_direct_message_queued', 'admin', ?, 'customer', ?, ?)
                """,
                (admin_id, str(local_customer_id), digest),
            )
        return outbox_id

    def queue_registered_broadcast(
        self, *, body: str, created_by: int, idempotency_key: str,
        photo_file_ids: tuple[str, ...] | None = None,
    ) -> BroadcastQueueResult:
        """Snapshot opted-in registered users into durable per-recipient outbox rows."""

        admin_id = _positive_int(created_by, "created_by")
        normalized_body = _normalize_admin_message_body(body)
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 180:
            raise TelegramRegistryError("idempotency key is invalid")
        if photo_file_ids and (len(photo_file_ids) > 10 or len(normalized_body) > 1024 or
                               any(not isinstance(item, str) or not item for item in photo_file_ids)):
            raise TelegramRegistryError("invalid broadcast photos")
        photos_json = json.dumps(photo_file_ids, ensure_ascii=False) if photo_file_ids else None
        digest = hashlib.sha256((normalized_body + (photos_json or "")).encode("utf-8")).hexdigest()
        with connect(self._db_path) as conn:
            recipient_ids = self._registered_broadcast_recipient_ids(conn)
            if not recipient_ids:
                raise TelegramRegistryError("no registered recipients are available")
            existing = conn.execute(
                "SELECT id, recipient_count FROM telegram_broadcast_jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                return BroadcastQueueResult(int(existing[0]), int(existing[1]))
            cursor = conn.execute(
                """
                INSERT INTO telegram_broadcast_jobs (created_by, idempotency_key, body, recipient_count, photo_file_ids)
                VALUES (?, ?, ?, ?, ?)
                """,
                (admin_id, key, normalized_body, len(recipient_ids), photos_json),
            )
            broadcast_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('registered_broadcast', ?, ?)
                """,
                [
                    (f"{broadcast_id}:{recipient_id}", f"registered-broadcast:{broadcast_id}:{recipient_id}")
                    for recipient_id in recipient_ids
                ],
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('registered_broadcast_queued', 'admin', ?, 'broadcast', ?, ?)
                """,
                (str(admin_id), str(broadcast_id), digest),
            )
        return BroadcastQueueResult(broadcast_id=broadcast_id, recipient_count=len(recipient_ids))

    @staticmethod
    def _lifecycle_operation_type(value: str) -> str:
        if value not in {"suspend", "resume", "delete"}:
            raise TelegramRegistryError("unsupported customer lifecycle operation")
        return value

    @staticmethod
    def _forget_missing_binding(conn, binding_id: int, *, actor_type: str, actor_id: str) -> bool:
        row = conn.execute(
            "SELECT customer_id, node_id, remote_email FROM customer_node_bindings "
            "WHERE id = ? AND management_state = 'missing'", (binding_id,),
        ).fetchone()
        if row is None or conn.execute(
            "SELECT 1 FROM telegram_customer_operation_attempts a "
            "JOIN telegram_customer_operations o ON o.id = a.operation_id "
            "WHERE a.binding_id = ? AND o.status IN ('queued', 'running', 'partial') "
            "AND o.dismissed_at IS NULL LIMIT 1", (binding_id,),
        ).fetchone():
            return False
        conn.execute("DELETE FROM telegram_customer_operation_attempts WHERE binding_id = ?", (binding_id,))
        conn.execute(
            "UPDATE telegram_drift_findings SET status = 'resolved', resolved_at = CURRENT_TIMESTAMP, "
            "row_version = row_version + 1 WHERE customer_id = ? AND node_id = ? "
            "AND kind = 'binding_missing' AND status IN ('open', 'ignored') "
            "AND lower(remote_email) = lower(?)", (row[0], row[1], row[2] or ""),
        )
        conn.execute("DELETE FROM customer_node_bindings WHERE id = ?", (binding_id,))
        event = "drift_binding_auto_forgotten" if actor_type == "system" else "binding_forgotten"
        conn.execute(
            "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id) "
            "VALUES (?, ?, ?, 'customer_node_binding', ?)", (event, actor_type, actor_id, str(binding_id)),
        )
        return True

    def forget_missing_bindings(self, customer_id: int, actor: str) -> dict[str, Any]:
        """Drop bindings marked 'missing' (client is gone from the panel and the admin does not want it back).

        Traffic totals live in separate ledgers keyed by customer/node, so nothing is lost; a client that
        reappears on the panel is found by the drift scan as an unknown remote client again.
        """
        customer_id = _positive_int(customer_id, "customer_id")
        forgotten: list[str] = []
        busy: list[str] = []
        with connect(self._db_path) as conn:
            if conn.execute("SELECT 1 FROM customers WHERE id = ?", (customer_id,)).fetchone() is None:
                raise TelegramRegistryError("customer was not found")
            rows = conn.execute(
                "SELECT b.id, b.node_id, b.remote_email, n.name FROM customer_node_bindings b "
                "JOIN nodes n ON n.id = b.node_id WHERE b.customer_id = ? AND b.management_state = 'missing'",
                (customer_id,),
            ).fetchall()
            for binding_id, node_id, remote_email, name in rows:
                if not self._forget_missing_binding(conn, binding_id, actor_type="admin", actor_id=str(actor)):
                    busy.append(str(name))
                    continue
                forgotten.append(str(name))
        return {"forgotten": forgotten, "busy": busy}

    def repair_customer(self, customer_id: int, actor: str) -> dict[str, Any]:
        customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            customer = conn.execute(
                "SELECT status, deleted_at FROM customers WHERE id = ?", (customer_id,)
            ).fetchone()
            if customer is None:
                raise TelegramRegistryError("customer was not found")
            problems: list[dict[str, Any]] = []
            identity = conn.execute(
                "SELECT remote_snapshot_ready FROM telegram_identities "
                "WHERE customer_id = ? AND access_status = 'approved' LIMIT 1", (customer_id,)
            ).fetchone()
            if customer[0] != 'active' or customer[1] is not None:
                problems.append({"code": "customer_inactive"})
            if identity is None:
                problems.append({"code": "identity_not_approved"})
            jobs = conn.execute(
                f"SELECT j.id, j.status FROM telegram_provisioning_jobs j WHERE j.customer_id = ? "
                f"AND j.trigger = 'approve_new' AND NOT {INITIAL_JOB_COMPLETE_SQL}", (customer_id,)
            ).fetchall()
            for job_id, status in jobs:
                problems.append({"code": "unfinished_job", "job_id": int(job_id), "status": str(status)})
            unresolved = conn.execute(
                """SELECT t.id FROM telegram_existing_discovery_jobs j
                JOIN telegram_existing_discovery_targets t ON t.job_id = j.id
                WHERE j.customer_id = ? AND (
                    t.status IN ('pending', 'reconciling', 'deferred', 'blocked_after_retry_limit', 'conflict')
                    OR (t.status = 'confirmed_absent' AND EXISTS (
                        SELECT 1 FROM telegram_provisioning_jobs p
                        WHERE p.id = t.provisioning_job_id AND p.status != 'succeeded'
                    ))
                )""", (customer_id,)
            ).fetchall()
            for (target_id,) in unresolved:
                problems.append({"code": "unfinished_discovery", "target_id": int(target_id)})
            bindings = conn.execute(
                "SELECT b.management_state, n.name, b.id, b.node_id, b.remote_client_id, COALESCE(n.enabled, 1) "
                "FROM customer_node_bindings b "
                "JOIN nodes n ON n.id = b.node_id WHERE b.customer_id = ?", (customer_id,)
            ).fetchall()
            # Re-check missing bindings against a fresh node snapshot so the admin gets a real answer:
            # a client that is really gone is a note, not a repairable problem; one that is visible
            # again is left for the drift scan to confirm (it checks the full identity).
            notes: list[dict[str, Any]] = []
            resolved: list[tuple] = []
            for state, name, binding_id, node_id, remote_client_id, node_enabled in bindings:
                if state == 'missing':
                    present = _fresh_snapshot_has_client(conn, int(node_id), str(remote_client_id or ""))
                    if present is True:
                        # Not confirmed here: the drift scan verifies inbound, id, sub id and email together.
                        notes.append({"code": "binding_present", "node_name": str(name)})
                        state = 'present'
                    elif present is False or (present is None and not node_enabled):
                        # A node taken out of service has no fresh snapshot: that is an expected note too.
                        notes.append({"code": "binding_absent", "node_name": str(name)})
                        state = 'absent'
                resolved.append((state, name))
            confirmed = any(row[0] == 'confirmed' for row in resolved)
            if not confirmed:
                problems.append({"code": "no_confirmed_binding"})
            for state, name in resolved:
                if state in ('missing', 'conflict'):
                    problems.append({"code": 'binding_' + str(state), "node_name": str(name)})
            for operation_id, node_name in conn.execute(
                "SELECT DISTINCT o.id, n.name FROM telegram_customer_operations o "
                "LEFT JOIN telegram_customer_operation_attempts a ON a.operation_id = o.id "
                "LEFT JOIN nodes n ON n.id = a.node_id WHERE o.customer_id = ? "
                "AND o.status IN ('queued', 'running', 'partial') AND o.dismissed_at IS NULL",
                (customer_id,),
            ):
                problems.append({"code": "unfinished_operation", "operation_id": int(operation_id),
                                 "node_name": str(node_name) if node_name is not None else None})
            changed = False
            if (customer[0] == 'active' and customer[1] is None and identity is not None
                    and not jobs and not unresolved and confirmed):
                changed = bool(conn.execute(
                    "UPDATE telegram_identities SET remote_snapshot_ready = 1, updated_at = CURRENT_TIMESTAMP "
                    "WHERE customer_id = ? AND access_status = 'approved' AND remote_snapshot_ready = 0",
                    (customer_id,),
                ).rowcount)
                if changed:
                    conn.execute(
                        "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id) "
                        "VALUES ('customer_repaired', 'admin', ?, 'customer', ?)", (str(actor), str(customer_id))
                    )
            if identity is not None and not bool(identity[0]) and not changed:
                problems.append({"code": "snapshot_incomplete"})
        result: dict[str, Any] = {"fixed": ["remote_snapshot_ready"] if changed else [], "problems": problems}
        if notes:
            result["notes"] = notes
        return result

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
        remote_snapshot = conn.execute(
            "SELECT remote_snapshot_ready FROM telegram_identities "
            "WHERE customer_id = ? AND access_status = 'approved' ORDER BY telegram_user_id LIMIT 1",
            (customer_id,),
        ).fetchone()
        if remote_snapshot is not None and not bool(remote_snapshot[0]):
            raise LifecycleUnavailableError("customer remote snapshot is incomplete")
        unresolved = conn.execute(
            """SELECT 1 FROM telegram_existing_discovery_jobs AS j
                JOIN telegram_existing_discovery_targets AS t ON t.job_id = j.id
                WHERE j.customer_id = ? AND (
                    t.status IN ('pending', 'reconciling', 'deferred', 'blocked_after_retry_limit', 'conflict')
                    OR (t.status = 'confirmed_absent' AND EXISTS (
                        SELECT 1 FROM telegram_provisioning_jobs AS p
                        WHERE p.id = t.provisioning_job_id AND p.status != 'succeeded'
                    ))
                ) LIMIT 1""",
            (customer_id,),
        ).fetchone()
        if unresolved is not None:
            raise LifecycleUnavailableError("customer remote snapshot remains degraded")
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
                   b.remote_email, b.management_state, b.desired_enabled, b.suspended_by_operation_id,
                   b.last_enabled
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

            # Disabled by hand on the panel (drift sync keeps last_enabled = 1): global resume re-enables it too.
            panel_disabled = (
                operation_type == "resume" and suspended_by_operation_id is None
                and not bool(row[8]) and row[10] == 1
            )
            if operation_type == "resume" and suspended_by_operation_id is None and not panel_disabled:
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
                if panel_disabled:
                    previous = (1,)
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
        remote_snapshot = conn.execute(
            "SELECT remote_snapshot_ready FROM telegram_identities "
            "WHERE customer_id = ? AND access_status = 'approved' ORDER BY telegram_user_id LIMIT 1",
            (customer_id,),
        ).fetchone()
        if remote_snapshot is not None and not bool(remote_snapshot[0]):
            raise LifecycleUnavailableError("customer remote snapshot is incomplete")
        unresolved = conn.execute(
            """SELECT 1 FROM telegram_existing_discovery_jobs AS j
                JOIN telegram_existing_discovery_targets AS t ON t.job_id = j.id
                WHERE j.customer_id = ? AND (
                    t.status IN ('pending', 'reconciling', 'deferred', 'blocked_after_retry_limit', 'conflict')
                    OR (t.status = 'confirmed_absent' AND EXISTS (
                        SELECT 1 FROM telegram_provisioning_jobs AS p
                        WHERE p.id = t.provisioning_job_id AND p.status != 'succeeded'
                    ))
                ) LIMIT 1""",
            (customer_id,),
        ).fetchone()
        if unresolved is not None:
            raise LifecycleUnavailableError("customer remote snapshot remains degraded")
        binding = conn.execute(
            """
            SELECT b.id, b.node_id, n.name, b.inbound_id, b.remote_client_id,
                   b.remote_sub_id, b.remote_email, b.management_state,
                   b.desired_enabled, b.suspended_by_operation_id, b.last_enabled
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
            panel_disabled = not bool(binding[8]) and binding[9] is None and binding[10] == 1
            if bool(binding[8]) or (binding[9] is None and not panel_disabled):
                raise LifecycleUnavailableError("customer is not suspended by a node operation")
            previous = None if panel_disabled else conn.execute(
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
            if panel_disabled:
                # Disabled by hand on the panel (drift sync recorded it as previously enabled): Resume re-enables.
                previous = (1,)
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
              AND o.status IN ('queued', 'running', 'partial') AND o.dismissed_at IS NULL
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
        if action not in {"retry", "reconcile", "dismiss"}:
            raise TelegramRegistryError("unsupported customer operation action")
        dismiss = action == "dismiss"
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
                "SELECT status, row_version, lease_until, dismissed_at FROM telegram_customer_operations WHERE id = ?",
                (normalized_operation_id,),
            ).fetchone()
            if operation is None:
                raise TelegramRegistryError("customer operation was not found")
            if int(operation[1]) != expected_version:
                raise VersionConflictError("customer operation was updated by another worker or administrator")
            if str(operation[0]) not in {"partial", "failed"} or operation[2] is not None or operation[3] is not None:
                raise VersionConflictError("customer operation cannot be rescheduled in its current state")
            if dismiss:
                # No status means "abandoned"; hide it from the attention list but keep the history.
                update = conn.execute(
                    """
                    UPDATE telegram_customer_operations
                    SET dismissed_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND row_version = ? AND lease_until IS NULL
                    """,
                    (normalized_operation_id, expected_version),
                )
            else:
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
                status=str(operation[0]) if dismiss else "queued",
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
                ("customer_operation_dismissed" if dismiss else f"customer_operation_{action}_queued",
                 actor, str(normalized_operation_id), digest),
            )
        return result

    def get_admin_dashboard(self) -> TelegramAdminDashboard:
        """Return only local operational counts; never probes a node."""

        with connect(self._db_path) as conn:
            def count(sql: str, parameters: tuple[Any, ...] = ()) -> int:
                row = conn.execute(sql, parameters).fetchone()
                return int(row[0]) if row is not None else 0

            return TelegramAdminDashboard(
                pending_requests=count("SELECT COUNT(*) FROM telegram_identities WHERE access_status = 'pending'"),
                active_customers=count("SELECT COUNT(*) FROM customers WHERE status = 'active' AND deleted_at IS NULL"),
                suspended_customers=count("SELECT COUNT(*) FROM customers WHERE status = 'suspended' AND deleted_at IS NULL"),
                lifecycle_attention=count(
                    "SELECT COUNT(*) FROM telegram_customer_operations "
                    "WHERE status IN ('partial', 'failed', 'running') AND dismissed_at IS NULL"
                ),
                provisioning_attention=count(
                    "SELECT COUNT(*) FROM telegram_provisioning_jobs "
                    "WHERE status IN ('partial', 'failed', 'running')"
                ),
                open_appeals=count("SELECT COUNT(*) FROM telegram_appeals WHERE status = 'open'"),
                open_support_requests=count(
                    "SELECT COUNT(*) FROM telegram_support_requests WHERE status IN ('open', 'read')"
                ),
                open_drift_findings=count("SELECT COUNT(*) FROM telegram_drift_findings WHERE status = 'open'"),
                scheduled_lifecycle_actions=count(
                    "SELECT COUNT(*) FROM telegram_lifecycle_schedules WHERE status = 'scheduled'"
                ),
            )

    def list_attention_items(self, *, limit: int = 100) -> dict[str, list[Any]]:
        """Jobs and lifecycle operations counted by get_admin_dashboard, so the UI can act on them."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TelegramRegistryError("limit must be an integer from 1 to 200")
        with connect(self._db_path) as conn:
            def ids(table: str, extra: str = "") -> list[int]:
                return [int(row[0]) for row in conn.execute(
                    f"SELECT id FROM {table} WHERE status IN ('partial', 'failed', 'running'){extra} "
                    "ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()]
            operation_ids = ids("telegram_customer_operations", " AND dismissed_at IS NULL")
            lifecycle = [self._get_customer_operation_from_conn(conn, i) for i in operation_ids]
            job_ids = ids("telegram_provisioning_jobs")
        return {
            "provisioning": [self.get_provisioning_job(i) for i in job_ids],
            "lifecycle": lifecycle,
        }

    def list_customer_tags(self, customer_id: int) -> tuple[CustomerTag, ...]:
        local_customer_id = _positive_int(customer_id, "customer_id")
        with connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT customer_id, tag FROM telegram_customer_tags WHERE customer_id = ? ORDER BY tag",
                (local_customer_id,),
            ).fetchall()
        return tuple(CustomerTag(customer_id=int(row[0]), tag=str(row[1])) for row in rows)

    def set_customer_tags(
        self, *, customer_id: int, tags: object, updated_by: str
    ) -> tuple[CustomerTag, ...]:
        local_customer_id = _positive_int(customer_id, "customer_id")
        normalized_tags = _normalize_tags(tags)
        actor = _nonempty(updated_by, "updated_by")
        with connect(self._db_path) as conn:
            customer = conn.execute(
                "SELECT 1 FROM customers WHERE id = ? AND deleted_at IS NULL", (local_customer_id,)
            ).fetchone()
            if customer is None:
                raise TelegramRegistryError("customer was not found")
            conn.execute("DELETE FROM telegram_customer_tags WHERE customer_id = ?", (local_customer_id,))
            conn.executemany(
                "INSERT INTO telegram_customer_tags(customer_id, tag, created_by) VALUES (?, ?, ?)",
                [(local_customer_id, tag, actor) for tag in normalized_tags],
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('customer_tags_updated', 'admin', ?, 'customer', ?, ?)
                """,
                (actor, str(local_customer_id), _payload_digest({"tags": normalized_tags})),
            )
        return tuple(CustomerTag(customer_id=local_customer_id, tag=tag) for tag in normalized_tags)

    def list_saved_filters(self, *, admin_username: str) -> tuple[TelegramSavedFilter, ...]:
        actor = _nonempty(admin_username, "admin_username")
        with connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, name, query, status, tags_json, updated_at
                FROM telegram_admin_saved_filters
                WHERE admin_username = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (actor,),
            ).fetchall()
        result: list[TelegramSavedFilter] = []
        for row in rows:
            try:
                tags = _normalize_tags(json.loads(str(row[4])))
            except (ValueError, TypeError, json.JSONDecodeError, TelegramRegistryError):
                tags = ()
            result.append(TelegramSavedFilter(
                filter_id=int(row[0]), name=str(row[1]), query=str(row[2]),
                status=str(row[3]) if row[3] is not None else None,
                tags=tags, updated_at=str(row[5]),
            ))
        return tuple(result)

    def save_filter(
        self, *, admin_username: str, name: object, query: object, status: object, tags: object
    ) -> TelegramSavedFilter:
        actor = _nonempty(admin_username, "admin_username")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise TelegramRegistryError("filter name must contain 1 to 80 characters")
        if not isinstance(query, str) or len(query.strip()) > 160:
            raise TelegramRegistryError("filter query must contain at most 160 characters")
        normalized_status = status.strip() if isinstance(status, str) else None
        allowed_statuses = {
            "active", "suspending", "suspended", "suspend_partial", "resuming", "resume_partial",
            "deleting", "delete_partial", "deleted", "conflict",
        }
        if normalized_status == "":
            normalized_status = None
        if normalized_status not in allowed_statuses and normalized_status is not None:
            raise TelegramRegistryError("filter status is invalid")
        normalized_tags = _normalize_tags(tags)
        normalized_name = unicodedata.normalize("NFKC", name).strip()
        normalized_query = unicodedata.normalize("NFKC", query).strip()
        tags_json = json.dumps(normalized_tags, ensure_ascii=False, separators=(",", ":"))
        with connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO telegram_admin_saved_filters(admin_username, name, query, status, tags_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(admin_username, name) DO UPDATE SET
                    query = excluded.query, status = excluded.status, tags_json = excluded.tags_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (actor, normalized_name, normalized_query, normalized_status, tags_json),
            )
            row = conn.execute(
                """
                SELECT id, name, query, status, tags_json, updated_at
                FROM telegram_admin_saved_filters WHERE admin_username = ? AND name = ?
                """,
                (actor, normalized_name),
            ).fetchone()
        assert row is not None
        return TelegramSavedFilter(
            filter_id=int(row[0]), name=str(row[1]), query=str(row[2]),
            status=str(row[3]) if row[3] is not None else None,
            tags=normalized_tags, updated_at=str(row[5]),
        )

    def delete_saved_filter(self, *, admin_username: str, filter_id: int) -> None:
        actor = _nonempty(admin_username, "admin_username")
        normalized_filter_id = _positive_int(filter_id, "filter_id")
        with connect(self._db_path) as conn:
            deleted = conn.execute(
                "DELETE FROM telegram_admin_saved_filters WHERE id = ? AND admin_username = ?",
                (normalized_filter_id, actor),
            )
            if deleted.rowcount != 1:
                raise TelegramRegistryError("saved filter was not found")

    def customer_timeline(self, *, customer_id: int, limit: int = 100) -> tuple[CustomerTimelineEvent, ...]:
        local_customer_id = _positive_int(customer_id, "customer_id")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TelegramRegistryError("limit must be an integer from 1 to 200")
        with connect(self._db_path) as conn:
            exists = conn.execute("SELECT 1 FROM customers WHERE id = ?", (local_customer_id,)).fetchone()
            if exists is None:
                raise TelegramRegistryError("customer was not found")
            rows = conn.execute(
                """
                SELECT event_type, entity_type, entity_id, created_at, actor_type, actor_id, status
                FROM (
                    SELECT event_type, entity_type, entity_id, created_at, actor_type, actor_id, NULL AS status
                    FROM telegram_audit_log
                    WHERE (entity_type = 'customer' AND entity_id = ?)
                       OR (entity_type = 'customer_operation' AND entity_id IN (
                           SELECT CAST(id AS TEXT) FROM telegram_customer_operations WHERE customer_id = ?
                       ))
                    UNION ALL
                    SELECT 'lifecycle:' || operation_type, 'customer_operation', CAST(id AS TEXT),
                           updated_at, 'system', NULL, status
                    FROM telegram_customer_operations WHERE customer_id = ?
                    UNION ALL
                    SELECT 'provisioning:' || trigger, 'provisioning_job', CAST(id AS TEXT),
                           created_at, 'system', NULL, status
                    FROM telegram_provisioning_jobs WHERE customer_id = ?
                ) ORDER BY created_at DESC LIMIT ?
                """,
                (str(local_customer_id), local_customer_id, local_customer_id, local_customer_id, limit),
            ).fetchall()
        return tuple(CustomerTimelineEvent(
            event_type=str(row[0]), entity_type=str(row[1]), entity_id=str(row[2]), created_at=str(row[3]),
            actor_type=str(row[4]) if row[4] is not None else None,
            actor_id=str(row[5]) if row[5] is not None else None,
            status=str(row[6]) if row[6] is not None else None,
        ) for row in rows)

    def get_customer_read_only_view(self, customer_id: int) -> dict[str, Any]:
        """A no-token projection of what the linked person can currently see."""

        customer = self.get_customer(customer_id)
        profile = self.get_customer_telegram_profile(customer.customer_id)
        with connect(self._db_path) as conn:
            initial_ready = not initial_job_incomplete(conn, customer.customer_id)
        return {
            "customer_id": customer.customer_id,
            "identity_linked": profile.telegram_user_id is not None,
            "identity_access_status": "approved" if profile.telegram_user_id is not None else None,
            "customer_status": customer.status,
            "connection_available": customer.status == "active" and initial_ready,
            "connection_reason": None if customer.status == "active" and initial_ready else (
                "initial_provisioning" if not initial_ready else "lifecycle"
            ),
            "token_revealed": False,
        }

    def create_lifecycle_schedule(
        self,
        *,
        customer_id: int,
        operation_type: object,
        execute_not_before: object,
        expected_customer_version: int,
        target_snapshot_digest: str,
        idempotency_key: str,
        created_by: str,
    ) -> LifecycleSchedule:
        """Store a cancellable grace-period command, without touching a node."""

        local_customer_id = _positive_int(customer_id, "customer_id")
        if operation_type not in {"suspend", "delete"}:
            raise TelegramRegistryError("only suspend and delete may be scheduled")
        expected_version = _positive_int(expected_customer_version, "expected_customer_version")
        expected_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
        execute_at = _parse_future_timestamp(execute_not_before, "execute_not_before")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(created_by, "created_by")
        payload = {
            "customer_id": local_customer_id, "operation_type": operation_type,
            "expected_customer_version": expected_version, "target_snapshot_digest": expected_digest,
            "execute_not_before": execute_at,
        }
        payload_digest = _payload_digest(payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = 'lifecycle_schedule' AND idempotency_key = ?", (key,)
            ).fetchone()
            if receipt is not None:
                if str(receipt[0]) != payload_digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return LifecycleSchedule(**json.loads(str(receipt[1])))
            preview, _targets = self._customer_operation_snapshot(
                conn, customer_id=local_customer_id, operation_type=str(operation_type)
            )
            if preview.expected_customer_version != expected_version or preview.target_snapshot_digest != expected_digest:
                raise VersionConflictError("lifecycle target preview is stale")
            if preview.blocked_binding_ids:
                raise LifecycleUnavailableError("customer has bindings without an exact confirmed remote target")
            cursor = conn.execute(
                """
                INSERT INTO telegram_lifecycle_schedules
                    (customer_id, operation_type, expected_customer_version, target_snapshot_digest,
                     execute_not_before, idempotency_key, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (local_customer_id, operation_type, expected_version, expected_digest, execute_at, key, actor),
            )
            schedule = LifecycleSchedule(
                schedule_id=int(cursor.lastrowid), customer_id=local_customer_id,
                customer_email=self.get_customer(local_customer_id).email_display,
                operation_type=str(operation_type), expected_customer_version=expected_version,
                target_snapshot_digest=expected_digest, execute_not_before=execute_at,
                status="scheduled", row_version=1, operation_id=None, created_at="",
            )
            created_at = conn.execute(
                "SELECT created_at FROM telegram_lifecycle_schedules WHERE id = ?", (schedule.schedule_id,)
            ).fetchone()
            assert created_at is not None
            schedule = LifecycleSchedule(**{**asdict(schedule), "created_at": str(created_at[0])})
            conn.execute(
                "INSERT INTO telegram_command_receipts(scope, idempotency_key, payload_digest, result_json) "
                "VALUES ('lifecycle_schedule', ?, ?, ?)",
                (key, payload_digest, json.dumps(asdict(schedule), separators=(",", ":"))),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('customer_lifecycle_scheduled', 'admin', ?, 'customer', ?, ?)
                """,
                (actor, str(local_customer_id), payload_digest),
            )
        return schedule

    def _schedule_from_row(self, row: tuple[Any, ...]) -> LifecycleSchedule:
        return LifecycleSchedule(
            schedule_id=int(row[0]), customer_id=int(row[1]), customer_email=str(row[2]),
            operation_type=str(row[3]), expected_customer_version=int(row[4]),
            target_snapshot_digest=str(row[5]), execute_not_before=str(row[6]), status=str(row[7]),
            row_version=int(row[8]), operation_id=int(row[9]) if row[9] is not None else None,
            created_at=str(row[10]),
        )

    def list_lifecycle_schedules(
        self, *, customer_id: int | None = None, status: str = "all", limit: int = 100
    ) -> tuple[LifecycleSchedule, ...]:
        if status not in {"all", "scheduled", "activating", "queued", "cancelled", "stale", "failed"}:
            raise TelegramRegistryError("schedule status is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise TelegramRegistryError("limit must be an integer from 1 to 200")
        where: list[str] = []
        values: list[Any] = []
        if customer_id is not None:
            where.append("s.customer_id = ?")
            values.append(_positive_int(customer_id, "customer_id"))
        if status != "all":
            where.append("s.status = ?")
            values.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        values.append(limit)
        with connect(self._db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT s.id, s.customer_id, c.email_display, s.operation_type, s.expected_customer_version,
                       s.target_snapshot_digest, s.execute_not_before, s.status, s.row_version,
                       s.operation_id, s.created_at
                FROM telegram_lifecycle_schedules AS s
                JOIN customers AS c ON c.id = s.customer_id
                {clause}
                ORDER BY s.execute_not_before DESC, s.id DESC LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return tuple(self._schedule_from_row(row) for row in rows)

    def cancel_lifecycle_schedule(
        self, *, schedule_id: int, expected_row_version: int, cancelled_by: str, reason: object = None
    ) -> LifecycleSchedule:
        local_schedule_id = _positive_int(schedule_id, "schedule_id")
        expected_version = _positive_int(expected_row_version, "expected_row_version")
        actor = _nonempty(cancelled_by, "cancelled_by")
        normalized_reason = str(reason).strip()[:240] if reason is not None else None
        with connect(self._db_path) as conn:
            updated = conn.execute(
                """
                UPDATE telegram_lifecycle_schedules
                SET status = 'cancelled', cancel_reason = ?, row_version = row_version + 1,
                    lease_owner = NULL, lease_until = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'scheduled' AND row_version = ?
                """,
                (normalized_reason or None, local_schedule_id, expected_version),
            )
            if updated.rowcount != 1:
                raise VersionConflictError("schedule is no longer cancellable")
            row = conn.execute(
                """
                SELECT s.id, s.customer_id, c.email_display, s.operation_type, s.expected_customer_version,
                       s.target_snapshot_digest, s.execute_not_before, s.status, s.row_version,
                       s.operation_id, s.created_at
                FROM telegram_lifecycle_schedules AS s JOIN customers AS c ON c.id = s.customer_id
                WHERE s.id = ?
                """,
                (local_schedule_id,),
            ).fetchone()
            assert row is not None
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                VALUES ('customer_lifecycle_schedule_cancelled', 'admin', ?, 'customer_schedule', ?, ?)
                """,
                (actor, str(local_schedule_id), _payload_digest({"reason": normalized_reason or ""})),
            )
        return self._schedule_from_row(row)

    def claim_due_lifecycle_schedule(
        self, *, worker_id: str, now: datetime | None = None, lease_seconds: int = 60
    ) -> LifecycleSchedule | None:
        actor = _nonempty(worker_id, "worker_id")
        if lease_seconds <= 0:
            raise TelegramRegistryError("lease_seconds must be positive")
        current = _timestamp(now or _utc_now())
        lease_until = _timestamp((now or _utc_now()) + timedelta(seconds=lease_seconds))
        with connect(self._db_path) as conn:
            row = conn.execute(
                """
                SELECT s.id, s.customer_id, c.email_display, s.operation_type, s.expected_customer_version,
                       s.target_snapshot_digest, s.execute_not_before, s.status, s.row_version,
                       s.operation_id, s.created_at
                FROM telegram_lifecycle_schedules AS s JOIN customers AS c ON c.id = s.customer_id
                WHERE s.status IN ('scheduled', 'activating') AND s.execute_not_before <= ?
                  AND (s.lease_until IS NULL OR s.lease_until < ?)
                ORDER BY s.execute_not_before, s.id LIMIT 1
                """,
                (current, current),
            ).fetchone()
            if row is None:
                return None
            claimed = conn.execute(
                """
                UPDATE telegram_lifecycle_schedules
                SET status = 'activating', lease_owner = ?, lease_until = ?,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('scheduled', 'activating')
                  AND (lease_until IS NULL OR lease_until < ?)
                """,
                (actor, lease_until, int(row[0]), current),
            )
            if claimed.rowcount != 1:
                return None
            row = list(row)
            row[7] = "activating"
            row[8] = int(row[8]) + 1
        return self._schedule_from_row(tuple(row))

    def complete_lifecycle_schedule(
        self, *, schedule_id: int, operation_id: int | None, outcome: str
    ) -> None:
        if outcome not in {"queued", "stale", "failed"}:
            raise TelegramRegistryError("schedule outcome is invalid")
        with connect(self._db_path) as conn:
            updated = conn.execute(
                """
                UPDATE telegram_lifecycle_schedules
                SET status = ?, operation_id = ?, lease_owner = NULL, lease_until = NULL,
                    row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'activating'
                """,
                (outcome, operation_id, _positive_int(schedule_id, "schedule_id")),
            )
            if updated.rowcount != 1:
                raise VersionConflictError("schedule completion lost its lease")

    @staticmethod
    def _bulk_preview_digest(operation_type: str, items: Iterable[BulkLifecyclePreviewItem]) -> str:
        return _payload_digest({
            "operation_type": operation_type,
            "items": [
                {
                    "customer_id": item.customer_id,
                    "expected_customer_version": item.expected_customer_version,
                    "target_snapshot_digest": item.target_snapshot_digest,
                }
                for item in sorted(items, key=lambda item: item.customer_id)
            ],
        })

    def preview_bulk_customer_operations(
        self, *, customer_ids: object, operation_type: object
    ) -> BulkLifecyclePreview:
        if operation_type not in {"suspend", "resume", "delete"}:
            raise TelegramRegistryError("bulk operation is invalid")
        if not isinstance(customer_ids, (list, tuple)):
            raise TelegramRegistryError("customer_ids must be a list")
        normalized_ids = tuple(sorted({_positive_int(value, "customer_id") for value in customer_ids}))
        if not 1 <= len(normalized_ids) <= 100:
            raise TelegramRegistryError("bulk preview requires 1 to 100 customers")
        with connect(self._db_path) as conn:
            items: list[BulkLifecyclePreviewItem] = []
            for customer_id in normalized_ids:
                preview, _targets = self._customer_operation_snapshot(
                    conn, customer_id=customer_id, operation_type=str(operation_type)
                )
                if preview.blocked_binding_ids:
                    raise LifecycleUnavailableError(
                        f"customer {customer_id} has bindings without an exact confirmed remote target"
                    )
                email = conn.execute("SELECT email_display FROM customers WHERE id = ?", (customer_id,)).fetchone()
                assert email is not None
                items.append(BulkLifecyclePreviewItem(
                    customer_id=customer_id, customer_email=str(email[0]),
                    expected_customer_version=preview.expected_customer_version,
                    target_snapshot_digest=preview.target_snapshot_digest,
                    target_count=len(preview.targets),
                ))
        return BulkLifecyclePreview(
            operation_type=str(operation_type),
            target_snapshot_digest=self._bulk_preview_digest(str(operation_type), items),
            items=tuple(items),
        )

    @staticmethod
    def _parse_bulk_preview_items(values: object) -> tuple[BulkLifecyclePreviewItem, ...]:
        if not isinstance(values, list) or not values:
            raise TelegramRegistryError("bulk preview items are required")
        items: list[BulkLifecyclePreviewItem] = []
        seen: set[int] = set()
        for value in values:
            if not isinstance(value, dict):
                raise TelegramRegistryError("bulk preview item is invalid")
            customer_id = _positive_int(value.get("customer_id"), "customer_id")
            if customer_id in seen:
                raise TelegramRegistryError("bulk preview contains a duplicate customer")
            seen.add(customer_id)
            version = _positive_int(value.get("expected_customer_version"), "expected_customer_version")
            digest = _nonempty(value.get("target_snapshot_digest"), "target_snapshot_digest")
            items.append(BulkLifecyclePreviewItem(
                customer_id=customer_id, customer_email="", expected_customer_version=version,
                target_snapshot_digest=digest, target_count=0,
            ))
        if len(items) > 100:
            raise TelegramRegistryError("bulk preview may contain at most 100 customers")
        return tuple(sorted(items, key=lambda item: item.customer_id))

    def _insert_bulk_lifecycle_operation(
        self,
        conn: sqlite3.Connection,
        *,
        preview: CustomerOperationPreview,
        private_targets: list[dict[str, Any]],
        operation_type: str,
        idempotency_key: str,
        created_by: str,
    ) -> CustomerOperationQueueResult:
        """Insert the same immutable records as a normal lifecycle command.

        The caller has already revalidated every member in one transaction;
        this helper intentionally does no remote I/O and does not expose the
        target identifiers in its return value.
        """

        queued_status = "queued" if private_targets else "succeeded"
        next_customer_status = {
            "suspend": "suspending" if private_targets else "suspended",
            "resume": "resuming" if private_targets else "active",
            "delete": "deleting" if private_targets else "deleted",
        }[operation_type]
        if operation_type == "delete" and not private_targets:
            update = conn.execute(
                """
                UPDATE customers
                SET status = ?, deleted_at = CURRENT_TIMESTAMP, row_version = row_version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND deleted_at IS NULL
                """,
                (next_customer_status, preview.customer_id, preview.expected_customer_version),
            )
        else:
            update = conn.execute(
                """
                UPDATE customers SET status = ?, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND row_version = ? AND deleted_at IS NULL
                """,
                (next_customer_status, preview.customer_id, preview.expected_customer_version),
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
                preview.customer_id, operation_type, queued_status, preview.target_snapshot_digest,
                preview.expected_customer_version, idempotency_key, created_by, queued_status,
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
                    target["remote_client_id"], target["remote_sub_id"], target["remote_email"],
                    target["action"], int(target["previous_enabled"])
                    if target["previous_enabled"] is not None else None,
                ),
            )
        return CustomerOperationQueueResult(
            operation_id=operation_id, customer_id=preview.customer_id,
            operation_type=operation_type, status=queued_status, row_version=1,
        )

    def queue_bulk_customer_operations(
        self,
        *,
        operation_type: object,
        target_snapshot_digest: object,
        items: object,
        idempotency_key: str,
        created_by: str,
    ) -> BulkLifecycleStatus:
        """Atomically queue a reviewed batch of normal lifecycle operations."""

        if operation_type not in {"suspend", "resume", "delete"}:
            raise TelegramRegistryError("bulk operation is invalid")
        parsed_items = self._parse_bulk_preview_items(items)
        expected_bulk_digest = _nonempty(target_snapshot_digest, "target_snapshot_digest")
        if self._bulk_preview_digest(str(operation_type), parsed_items) != expected_bulk_digest:
            raise VersionConflictError("bulk lifecycle preview is stale")
        key = _nonempty(idempotency_key, "idempotency_key")
        actor = _nonempty(created_by, "created_by")
        payload = {"operation_type": operation_type, "target_snapshot_digest": expected_bulk_digest}
        payload_digest = _payload_digest(payload)
        with connect(self._db_path) as conn:
            receipt = conn.execute(
                "SELECT payload_digest, result_json FROM telegram_command_receipts "
                "WHERE scope = 'bulk_customer_lifecycle' AND idempotency_key = ?", (key,)
            ).fetchone()
            if receipt is not None:
                if str(receipt[0]) != payload_digest:
                    raise IdempotencyConflictError("idempotency key was already used for another command")
                return self.get_bulk_lifecycle_status(int(json.loads(str(receipt[1]))["bulk_job_id"]))

            snapshots: list[tuple[CustomerOperationPreview, list[dict[str, Any]], str]] = []
            for item in parsed_items:
                preview, private_targets = self._customer_operation_snapshot(
                    conn, customer_id=item.customer_id, operation_type=str(operation_type)
                )
                if (
                    preview.expected_customer_version != item.expected_customer_version
                    or preview.target_snapshot_digest != item.target_snapshot_digest
                    or preview.blocked_binding_ids
                ):
                    raise VersionConflictError("at least one bulk lifecycle target is stale")
                email = conn.execute("SELECT email_display FROM customers WHERE id = ?", (item.customer_id,)).fetchone()
                assert email is not None
                snapshots.append((preview, private_targets, str(email[0])))
            cursor = conn.execute(
                """
                INSERT INTO telegram_bulk_lifecycle_jobs
                    (operation_type, target_snapshot_digest, created_by, idempotency_key)
                VALUES (?, ?, ?, ?)
                """,
                (operation_type, expected_bulk_digest, actor, key),
            )
            bulk_job_id = int(cursor.lastrowid)
            for preview, private_targets, _email in snapshots:
                result = self._insert_bulk_lifecycle_operation(
                    conn, preview=preview, private_targets=private_targets, operation_type=str(operation_type),
                    idempotency_key=f"bulk:{bulk_job_id}:{preview.customer_id}", created_by=actor,
                )
                conn.execute(
                    "INSERT INTO telegram_bulk_lifecycle_items(bulk_job_id, customer_id, operation_id) VALUES (?, ?, ?)",
                    (bulk_job_id, preview.customer_id, result.operation_id),
                )
                conn.execute(
                    """
                    INSERT INTO telegram_audit_log
                        (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
                    VALUES (?, 'admin', ?, 'customer_operation', ?, ?)
                    """,
                    (f"customer_{operation_type}_queued_bulk", actor, str(result.operation_id), expected_bulk_digest),
                )
            conn.execute(
                "INSERT INTO telegram_command_receipts(scope, idempotency_key, payload_digest, result_json) "
                "VALUES ('bulk_customer_lifecycle', ?, ?, ?)",
                (key, payload_digest, json.dumps({"bulk_job_id": bulk_job_id}, separators=(",", ":"))),
            )
        return self.get_bulk_lifecycle_status(bulk_job_id)

    def get_bulk_lifecycle_status(self, bulk_job_id: int) -> BulkLifecycleStatus:
        local_bulk_job_id = _positive_int(bulk_job_id, "bulk_job_id")
        with connect(self._db_path) as conn:
            job = conn.execute(
                "SELECT operation_type, created_at FROM telegram_bulk_lifecycle_jobs WHERE id = ?",
                (local_bulk_job_id,),
            ).fetchone()
            if job is None:
                raise TelegramRegistryError("bulk lifecycle job was not found")
            rows = conn.execute(
                """
                SELECT item.customer_id, customer.email_display, item.operation_id, operation.status
                FROM telegram_bulk_lifecycle_items AS item
                JOIN customers AS customer ON customer.id = item.customer_id
                JOIN telegram_customer_operations AS operation ON operation.id = item.operation_id
                WHERE item.bulk_job_id = ? ORDER BY customer.email_display COLLATE NOCASE, item.customer_id
                """,
                (local_bulk_job_id,),
            ).fetchall()
        return BulkLifecycleStatus(
            bulk_job_id=local_bulk_job_id, operation_type=str(job[0]), created_at=str(job[1]),
            items=tuple(BulkLifecycleItemStatus(
                customer_id=int(row[0]), customer_email=str(row[1]), operation_id=int(row[2]), status=str(row[3])
            ) for row in rows),
        )

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
