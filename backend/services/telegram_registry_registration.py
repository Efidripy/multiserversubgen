"""Registration and onboarding operations for the Telegram registry."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from services.db_bootstrap import connect

PendingApplicationResult = Any
TelegramIdentity = Any
TelegramRegistryError = Any
_positive_int = Any
PendingApplication = Any
_suggested_email = Any
canonicalize_email = Any
BlockedIdentity = Any
ApprovalResult = Any
ApprovalUnavailableError = Any
BOT_CLIENT_FLOW = Any
BOT_INBOUND_ID = Any
IdempotencyConflictError = Any
VersionConflictError = Any
_nonempty = Any
_payload_digest = Any
_validate_email_choice = Any
ExistingApprovalResult = Any
DiscoveredExistingBinding = Any
DeferredExistingApprovalResult = Any
ExistingDiscoveryJobStatus = Any
ExistingDiscoveryTargetStatus = Any
_identity_from_row = Any
AbuseNoopResult = Any

def create_pending_application(self, telegram_user_id: int, **deps) -> PendingApplicationResult:
    """Atomically create exactly one admin-notified pending attempt."""
    TelegramIdentity = deps['TelegramIdentity']
    PendingApplicationResult = deps['PendingApplicationResult']
    TelegramRegistryError = deps['TelegramRegistryError']
    _positive_int = deps['_positive_int']

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

def request_required_introduction(self, telegram_user_id: int, **deps) -> bool:
    """Open the non-sensitive local registration step without creating an application.

    A pending application and its administrator notifications are created
    only after :meth:`submit_required_introduction` validates non-empty
    user text. This makes an empty application impossible through the bot
    command path while keeping the public pre-approval copy neutral.
    """
    _positive_int = deps['_positive_int']

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        update = conn.execute(
            """
            UPDATE telegram_identities
            SET introduction_requested_at = COALESCE(introduction_requested_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_user_id = ? AND access_status IN ('eligible', 'rejected')
            """,
            (user_id,),
        )
    return update.rowcount == 1

def submit_required_introduction(
    self, telegram_user_id: int, text: str, *, maximum_chars: int
, **deps) -> PendingApplicationResult:
    """Atomically turn a prompted introduction into one pending application.

    The update requires an explicit locally-recorded prompt, one bounded
    non-whitespace body and an eligible identity. It creates the complete
    review object, stores the text and queues administrator delivery in
    the same SQLite transaction, so retries cannot create an empty or
    duplicate request.
    """
    TelegramIdentity = deps['TelegramIdentity']
    PendingApplicationResult = deps['PendingApplicationResult']
    TelegramRegistryError = deps['TelegramRegistryError']
    _positive_int = deps['_positive_int']

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    normalized = text.strip()
    if not normalized or len(normalized) > maximum_chars:
        raise TelegramRegistryError("introduction length is invalid")
    with connect(self._db_path) as conn:
        identity = conn.execute(
            """
            SELECT telegram_user_id, chat_id, access_status, application_attempt,
                   customer_id, row_version, introduction_requested_at
            FROM telegram_identities WHERE telegram_user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if identity is None:
            raise TelegramRegistryError("identity must be registered before creating an application")
        existing_identity = TelegramIdentity(
            telegram_user_id=int(identity[0]),
            chat_id=int(identity[1]),
            access_status=str(identity[2]),
            application_attempt=int(identity[3]),
            customer_id=int(identity[4]) if identity[4] is not None else None,
            row_version=int(identity[5]),
        )
        if str(identity[2]) not in {"eligible", "rejected"} or identity[6] is None:
            return PendingApplicationResult(existing_identity, created=False, request_code=None)

        next_attempt = existing_identity.application_attempt + 1
        request_code = secrets.token_urlsafe(6)
        update = conn.execute(
            """
            UPDATE telegram_identities
            SET access_status = 'pending', request_code = ?, application_attempt = ?,
                introduction_requested_at = NULL, requested_at = CURRENT_TIMESTAMP,
                rejected_at = NULL, decision_reason = NULL, updated_at = CURRENT_TIMESTAMP,
                row_version = row_version + 1
            WHERE telegram_user_id = ? AND access_status IN ('eligible', 'rejected')
              AND introduction_requested_at IS NOT NULL
            """,
            (request_code, next_attempt, user_id),
        )
        if update.rowcount != 1:
            return PendingApplicationResult(existing_identity, created=False, request_code=None)
        conn.execute(
            """
            INSERT INTO telegram_applications
                (telegram_user_id, application_attempt, introduction_text, introduction_submitted_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (user_id, next_attempt, normalized),
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
            INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
            VALUES ('admin_introduction_submitted', ?, ?)
            """,
            (
                f"{user_id}:{next_attempt}",
                f"admin:introduction-submitted:{user_id}:{next_attempt}",
            ),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id)
            VALUES ('request_created', 'telegram_user', ?, 'telegram_identity', ?)
            """,
            (str(user_id), str(user_id)),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id)
            VALUES ('introduction_submitted', 'telegram_user', ?, 'telegram_application', ?)
            """,
            (str(user_id), f"{user_id}:{next_attempt}"),
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

def submit_introduction(self, telegram_user_id: int, text: str, *, maximum_chars: int, **deps) -> bool:
    """Store one plain-text voluntary introduction for the active attempt."""
    TelegramRegistryError = deps['TelegramRegistryError']
    _positive_int = deps['_positive_int']

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
        if result.rowcount == 1:
            conn.execute(
                """
                INSERT OR IGNORE INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('admin_introduction_submitted', ?, ?)
                """,
                (
                    f"{user_id}:{int(identity[1])}",
                    f"admin:introduction-submitted:{user_id}:{int(identity[1])}",
                ),
            )
    return result.rowcount == 1

def list_pending_applications(self, **deps) -> list[PendingApplication]:
    """Return the review queue without treating display metadata as identity."""
    PendingApplication = deps['PendingApplication']
    _suggested_email = deps['_suggested_email']
    canonicalize_email = deps['canonicalize_email']

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

def list_blocked_identities(self, *, limit: int = 100, **deps) -> list[BlockedIdentity]:
    BlockedIdentity = deps['BlockedIdentity']
    TelegramRegistryError = deps['TelegramRegistryError']
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise TelegramRegistryError("limit must be an integer from 1 to 200")
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT telegram_user_id, username, first_name, row_version, blocked_at, decision_reason
            FROM telegram_identities WHERE access_status = 'blocked'
            ORDER BY blocked_at DESC, telegram_user_id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        BlockedIdentity(int(row[0]), str(row[1]) if row[1] is not None else None,
                        str(row[2]) if row[2] is not None else None, int(row[3]),
                        str(row[4]) if row[4] is not None else None,
                        str(row[5]) if row[5] is not None else None)
        for row in rows
    ]

def get_pending_application(self, telegram_user_id: int, **deps) -> PendingApplication:
    TelegramRegistryError = deps['TelegramRegistryError']
    _positive_int = deps['_positive_int']
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
    approved_by: str, **deps
) -> ApprovalResult:
    """Approve a pending person and atomically queue, but never run, provisioning.

    The policy values and generated remote identifiers are persisted with
    each attempt. A future worker may therefore safely reconcile before
    touching a node, even if a node policy changes after approval.
    """
    ApprovalResult = deps['ApprovalResult']
    ApprovalUnavailableError = deps['ApprovalUnavailableError']
    BOT_CLIENT_FLOW = deps['BOT_CLIENT_FLOW']
    BOT_INBOUND_ID = deps['BOT_INBOUND_ID']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    VersionConflictError = deps['VersionConflictError']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']
    _suggested_email = deps['_suggested_email']
    _validate_email_choice = deps['_validate_email_choice']
    canonicalize_email = deps['canonicalize_email']

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
                approved_by = ?, decision_reason = NULL, remote_snapshot_ready = 0, updated_at = CURRENT_TIMESTAMP,
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
    approved_by: str, **deps
) -> ExistingApprovalResult:
    """Link only a locally known customer with confirmed exact bindings.

    This command intentionally accepts a local `customer_id`, not a free
    email string. Discovery/import is a separate reviewed workflow, so a
    guessed or similarly named remote client can never be claimed here.
    """
    ApprovalUnavailableError = deps['ApprovalUnavailableError']
    ExistingApprovalResult = deps['ExistingApprovalResult']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    VersionConflictError = deps['VersionConflictError']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']
    canonicalize_email = deps['canonicalize_email']

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

def adopt_discovered_existing_application(
    self,
    *,
    telegram_user_id: int,
    email_display: str,
    bindings: Iterable[DiscoveredExistingBinding],
    expected_identity_version: int,
    idempotency_key: str,
    approved_by: str, **deps
) -> ExistingApprovalResult:
    """Bind an old panel client after an adapter proved its exact remote identity.

    The caller must obtain ``bindings`` from a strict read-only discovery.
    This method never performs remote I/O: it atomically persists the local
    customer/binding mirror and links the pending Telegram identity.
    """
    ApprovalUnavailableError = deps['ApprovalUnavailableError']
    BOT_INBOUND_ID = deps['BOT_INBOUND_ID']
    DiscoveredExistingBinding = deps['DiscoveredExistingBinding']
    ExistingApprovalResult = deps['ExistingApprovalResult']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    TelegramRegistryError = deps['TelegramRegistryError']
    VersionConflictError = deps['VersionConflictError']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']
    canonicalize_email = deps['canonicalize_email']

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    expected_version = _positive_int(expected_identity_version, "expected_identity_version")
    display = _nonempty(email_display, "email_display")
    canonical = canonicalize_email(display)
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(approved_by, "approved_by")
    exact_bindings = tuple(bindings)
    if not exact_bindings:
        raise ApprovalUnavailableError("existing service username was not found on inbound 1")

    node_ids: set[int] = set()
    normalized_bindings: list[DiscoveredExistingBinding] = []
    for binding in exact_bindings:
        if not isinstance(binding, DiscoveredExistingBinding):
            raise TelegramRegistryError("existing discovery binding is invalid")
        node_id = _positive_int(binding.node_id, "node_id")
        if binding.inbound_id != BOT_INBOUND_ID or node_id in node_ids:
            raise TelegramRegistryError("existing discovery binding is ambiguous")
        if not binding.remote_client_id.strip() or canonicalize_email(binding.remote_email) != canonical:
            raise TelegramRegistryError("existing discovery binding is not an exact email match")
        node_ids.add(node_id)
        normalized_bindings.append(binding)

    payload = {
        "telegram_user_id": user_id,
        "email": canonical,
        "expected_identity_version": expected_version,
        "bindings": [
            {"node_id": item.node_id, "client_id": item.remote_client_id, "sub_id": item.remote_sub_id}
            for item in normalized_bindings
        ],
    }
    digest = _payload_digest(payload)
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'adopt_existing' AND idempotency_key = ?",
            (key,),
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return ExistingApprovalResult(**json.loads(str(receipt[1])))

        identity = conn.execute(
            "SELECT access_status, row_version, customer_id, application_attempt "
            "FROM telegram_identities WHERE telegram_user_id = ?",
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
        known_nodes = {
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM nodes WHERE id IN (%s)" % ",".join("?" for _ in node_ids),
                tuple(node_ids),
            ).fetchall()
        }
        if known_nodes != node_ids:
            raise ApprovalUnavailableError("existing discovery contains an unavailable node")

        customer = conn.execute(
            "SELECT id, email_display, status FROM customers WHERE email_canonical = ? AND deleted_at IS NULL",
            (canonical,),
        ).fetchone()
        if customer is None:
            customer_id = int(
                conn.execute(
                    "INSERT INTO customers (email_display, email_canonical, origin, public_code, email_source) "
                    "VALUES (?, ?, 'existing', ?, 'existing')",
                    (display, canonical, secrets.token_urlsafe(9)),
                ).lastrowid
            )
            customer_display = display
        else:
            customer_id, customer_display, customer_status = int(customer[0]), str(customer[1]), str(customer[2])
            if customer_status not in {"active", "suspended", "suspend_partial", "resume_partial"}:
                raise ApprovalUnavailableError("customer is not available for Telegram linking")
            linked_identity = conn.execute(
                "SELECT telegram_user_id FROM telegram_identities WHERE customer_id = ?", (customer_id,)
            ).fetchone()
            if linked_identity is not None:
                raise ApprovalUnavailableError("customer is already linked to another Telegram identity")

        for binding in normalized_bindings:
            existing = conn.execute(
                "SELECT id, remote_client_id, remote_sub_id, remote_email FROM customer_node_bindings "
                "WHERE customer_id = ? AND node_id = ? AND inbound_id = ?",
                (customer_id, binding.node_id, BOT_INBOUND_ID),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing[1] or "") != binding.remote_client_id
                    or str(existing[2] or "") != binding.remote_sub_id
                    or canonicalize_email(str(existing[3])) != canonical
                ):
                    raise ApprovalUnavailableError("existing node binding conflicts with remote discovery")
                conn.execute(
                    "UPDATE customer_node_bindings SET desired_enabled = ?, last_enabled = ?, "
                    "management_state = 'confirmed', last_confirmed_at = CURRENT_TIMESTAMP, "
                    "row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (int(binding.enabled), int(binding.enabled), int(existing[0])),
                )
                continue
            conn.execute(
                "INSERT INTO customer_node_bindings "
                "(customer_id, node_id, inbound_id, remote_client_id, remote_sub_id, remote_email, "
                "source, management_state, desired_enabled, last_enabled, last_confirmed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'existing_bound', 'confirmed', ?, ?, CURRENT_TIMESTAMP)",
                (
                    customer_id, binding.node_id, BOT_INBOUND_ID, binding.remote_client_id,
                    binding.remote_sub_id, binding.remote_email, int(binding.enabled), int(binding.enabled),
                ),
            )

        update = conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved', approved_at = CURRENT_TIMESTAMP, "
            "approved_by = ?, decision_reason = NULL, updated_at = CURRENT_TIMESTAMP, row_version = row_version + 1 "
            "WHERE telegram_user_id = ? AND access_status = 'pending' AND row_version = ?",
            (customer_id, actor, user_id, expected_version),
        )
        if update.rowcount != 1:
            raise VersionConflictError("application was updated by another administrator")
        conn.execute(
            "UPDATE telegram_applications SET status = 'approved', updated_at = CURRENT_TIMESTAMP "
            "WHERE telegram_user_id = ? AND application_attempt = ? AND status = 'pending'",
            (user_id, int(identity[3])),
        )
        conn.execute(
            "INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key) VALUES ('user_existing_access_approved', ?, ?)",
            (str(user_id), f"user:existing-access-approved:{user_id}:{int(identity[3])}"),
        )
        result = ExistingApprovalResult(
            telegram_user_id=user_id,
            customer_id=customer_id,
            email_display=customer_display,
            confirmed_binding_count=len(normalized_bindings),
            identity_row_version=expected_version + 1,
        )
        conn.execute(
            "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest) "
            "VALUES ('request_adopted_existing', 'admin', ?, 'telegram_identity', ?, ?)",
            (actor, str(user_id), _payload_digest({"customer_id": customer_id, "binding_count": len(normalized_bindings)})),
        )
        conn.execute(
            "INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('adopt_existing', ?, ?, ?)",
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result

def queue_deferred_existing_discovery(
    self,
    *,
    telegram_user_id: int,
    email_display: str,
    expected_identity_version: int,
    idempotency_key: str,
    approved_by: str, **deps
) -> DeferredExistingApprovalResult:
    """Associate locally, then reconcile every enabled node without writes.

    A failed remote read is represented by its immutable target instead of
    being treated as an absent customer.  No access or completion outbox is
    created here; only the discovery worker may release that gate.
    """
    ApprovalUnavailableError = deps['ApprovalUnavailableError']
    BOT_CLIENT_FLOW = deps['BOT_CLIENT_FLOW']
    BOT_INBOUND_ID = deps['BOT_INBOUND_ID']
    DeferredExistingApprovalResult = deps['DeferredExistingApprovalResult']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    VersionConflictError = deps['VersionConflictError']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']
    canonicalize_email = deps['canonicalize_email']

    user_id = _positive_int(telegram_user_id, "telegram_user_id")
    expected_version = _positive_int(expected_identity_version, "expected_identity_version")
    display = _nonempty(email_display, "email_display")
    canonical = canonicalize_email(display)
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(approved_by, "approved_by")
    digest = _payload_digest({
        "telegram_user_id": user_id, "email": canonical,
        "expected_identity_version": expected_version,
    })
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'defer_existing_discovery' AND idempotency_key = ?", (key,)
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            result = json.loads(str(receipt[1]))
            result["target_node_ids"] = tuple(result["target_node_ids"])
            return DeferredExistingApprovalResult(**result)

        identity = conn.execute(
            "SELECT access_status, row_version, customer_id, application_attempt "
            "FROM telegram_identities WHERE telegram_user_id = ?", (user_id,)
        ).fetchone()
        if identity is None or str(identity[0]) != "pending" or identity[2] is not None:
            raise VersionConflictError("application is no longer eligible for an existing customer link")
        if int(identity[1]) != expected_version:
            raise VersionConflictError("application was updated by another administrator")
        application_attempt = int(identity[3])
        application = conn.execute(
            "SELECT status FROM telegram_applications WHERE telegram_user_id = ? AND application_attempt = ?",
            (user_id, application_attempt),
        ).fetchone()
        if application is None or str(application[0]) != "pending":
            raise VersionConflictError("application attempt is no longer pending")
        targets = conn.execute(
            """
            SELECT p.node_id, p.total_bytes, p.validity_days, p.client_enabled, p.policy_version
            FROM telegram_node_policies AS p
            JOIN nodes AS n ON n.id = p.node_id
            WHERE p.provisioning_enabled = 1 AND n.enabled = 1 AND n.read_only = 0
            ORDER BY p.node_id
            """
        ).fetchall()
        if not targets:
            raise ApprovalUnavailableError("there are no eligible Telegram nodes for existing customer discovery")
        target_node_ids = tuple(int(row[0]) for row in targets)
        target_snapshot = tuple({
            "node_id": int(row[0]), "total_bytes": int(row[1]),
            "validity_days": int(row[2]), "client_enabled": bool(row[3]),
            "policy_version": int(row[4]), "inbound_id": BOT_INBOUND_ID, "flow": BOT_CLIENT_FLOW,
        } for row in targets)
        snapshot_digest = _payload_digest({
            "telegram_user_id": user_id, "email": canonical, "targets": target_snapshot,
        })
        customer = conn.execute(
            "SELECT id, email_display, status FROM customers WHERE email_canonical = ? AND deleted_at IS NULL",
            (canonical,),
        ).fetchone()
        if customer is None:
            customer_id = int(conn.execute(
                "INSERT INTO customers (email_display, email_canonical, origin, public_code, email_source) "
                "VALUES (?, ?, 'existing', ?, 'existing')",
                (display, canonical, secrets.token_urlsafe(9)),
            ).lastrowid)
            customer_display = display
        else:
            customer_id, customer_display, customer_status = int(customer[0]), str(customer[1]), str(customer[2])
            if customer_status not in {"active", "suspended", "suspend_partial", "resume_partial"}:
                raise ApprovalUnavailableError("customer is not available for Telegram linking")
            if conn.execute(
                "SELECT 1 FROM telegram_identities WHERE customer_id = ?", (customer_id,)
            ).fetchone() is not None:
                raise ApprovalUnavailableError("customer is already linked to another Telegram identity")

        job_id = int(conn.execute(
            "INSERT INTO telegram_existing_discovery_jobs "
            "(customer_id, telegram_user_id, application_attempt, idempotency_key, target_snapshot_digest, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, user_id, application_attempt, key, snapshot_digest, actor),
        ).lastrowid)
        conn.executemany(
            """
            INSERT INTO telegram_existing_discovery_targets
                (job_id, node_id, desired_total_bytes, desired_validity_days,
                 desired_client_enabled, policy_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (job_id, int(row[0]), int(row[1]), int(row[2]), int(bool(row[3])), int(row[4]))
                for row in targets
            ],
        )
        update = conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved', approved_at = CURRENT_TIMESTAMP, "
            "approved_by = ?, decision_reason = NULL, remote_snapshot_ready = 0, updated_at = CURRENT_TIMESTAMP, "
            "row_version = row_version + 1 WHERE telegram_user_id = ? AND access_status = 'pending' AND row_version = ?",
            (customer_id, actor, user_id, expected_version),
        )
        if update.rowcount != 1:
            raise VersionConflictError("application was updated by another administrator")
        conn.execute(
            "UPDATE telegram_applications SET status = 'approved', updated_at = CURRENT_TIMESTAMP "
            "WHERE telegram_user_id = ? AND application_attempt = ? AND status = 'pending'",
            (user_id, application_attempt),
        )
        result = DeferredExistingApprovalResult(
            telegram_user_id=user_id, customer_id=customer_id, discovery_job_id=job_id,
            email_display=customer_display, target_node_ids=target_node_ids,
            identity_row_version=expected_version + 1,
        )
        conn.execute(
            "INSERT INTO telegram_audit_log "
            "(event_type, actor_type, actor_id, entity_type, entity_id, payload_digest) "
            "VALUES ('request_existing_discovery_deferred', 'admin', ?, 'telegram_existing_discovery_job', ?, ?)",
            (actor, str(job_id), _payload_digest({"customer_id": customer_id, "target_count": len(target_node_ids)})),
        )
        conn.execute(
            "INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('defer_existing_discovery', ?, ?, ?)",
            (key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result

def get_existing_discovery_job(self, job_id: int, **deps) -> ExistingDiscoveryJobStatus:
    ExistingDiscoveryJobStatus = deps['ExistingDiscoveryJobStatus']
    ExistingDiscoveryTargetStatus = deps['ExistingDiscoveryTargetStatus']
    TelegramRegistryError = deps['TelegramRegistryError']
    _positive_int = deps['_positive_int']
    normalized_job_id = _positive_int(job_id, "job_id")
    with connect(self._db_path) as conn:
        job = conn.execute(
            "SELECT j.id, j.customer_id, j.telegram_user_id, c.email_display, j.status, j.row_version, "
            "j.target_snapshot_digest, j.created_at, j.finished_at "
            "FROM telegram_existing_discovery_jobs AS j JOIN customers AS c ON c.id = j.customer_id WHERE j.id = ?",
            (normalized_job_id,),
        ).fetchone()
        if job is None:
            raise TelegramRegistryError("existing discovery job was not found")
        targets = conn.execute(
            "SELECT t.node_id, n.name, t.status, t.attempt_count, t.error_code, t.next_attempt_at, p.status "
            "FROM telegram_existing_discovery_targets AS t JOIN nodes AS n ON n.id = t.node_id "
            "LEFT JOIN telegram_provisioning_jobs AS p ON p.id = t.provisioning_job_id "
            "WHERE t.job_id = ? ORDER BY t.node_id", (normalized_job_id,),
        ).fetchall()
    return ExistingDiscoveryJobStatus(
        job_id=int(job[0]), customer_id=int(job[1]), telegram_user_id=int(job[2]),
        customer_email=str(job[3]), status=str(job[4]), row_version=int(job[5]),
        target_snapshot_digest=str(job[6]), created_at=str(job[7]),
        finished_at=str(job[8]) if job[8] is not None else None,
        targets=tuple(ExistingDiscoveryTargetStatus(
            node_id=int(row[0]), node_name=str(row[1]),
            status=("provisioned" if str(row[2]) == "confirmed_absent" and row[6] == "succeeded" else str(row[2])),
            attempt_count=int(row[3]), error_code=str(row[4]) if row[4] is not None else None,
            next_attempt_at=str(row[5]) if row[5] is not None else None,
        ) for row in targets),
    )

def recover_existing_discovery_target(
    self, *, job_id: int, node_id: int, expected_job_version: int,
    idempotency_key: str, requested_by: str, **deps
) -> ExistingDiscoveryJobStatus:
    """Reset one terminal target only after an explicit operator command."""
    ApprovalUnavailableError = deps['ApprovalUnavailableError']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    TelegramRegistryError = deps['TelegramRegistryError']
    VersionConflictError = deps['VersionConflictError']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']

    normalized_job_id = _positive_int(job_id, "job_id")
    normalized_node_id = _positive_int(node_id, "node_id")
    expected_version = _positive_int(expected_job_version, "expected_job_version")
    key = _nonempty(idempotency_key, "idempotency_key")
    actor = _nonempty(requested_by, "requested_by")
    digest = _payload_digest({"job_id": normalized_job_id, "node_id": normalized_node_id,
                              "expected_job_version": expected_version})
    with connect(self._db_path) as conn:
        receipt = conn.execute(
            "SELECT payload_digest, result_json FROM telegram_command_receipts "
            "WHERE scope = 'recover_existing_discovery_target' AND idempotency_key = ?", (key,)
        ).fetchone()
        if receipt:
            if str(receipt[0]) != digest:
                raise IdempotencyConflictError("idempotency key was already used for another command")
            return self.get_existing_discovery_job(int(json.loads(str(receipt[1]))["job_id"]))
        job = conn.execute("SELECT row_version FROM telegram_existing_discovery_jobs WHERE id = ?", (normalized_job_id,)).fetchone()
        if job is None:
            raise TelegramRegistryError("existing discovery job was not found")
        if int(job[0]) != expected_version:
            raise VersionConflictError("existing discovery job was updated by another administrator")
        target = conn.execute(
            "SELECT id FROM telegram_existing_discovery_targets WHERE job_id = ? AND node_id = ? "
            "AND status = 'blocked_after_retry_limit'", (normalized_job_id, normalized_node_id),
        ).fetchone()
        if target is None:
            raise ApprovalUnavailableError("only a retry-limit target can be recovered")
        conn.execute(
            "UPDATE telegram_existing_discovery_targets SET status = 'pending', attempt_count = 0, error_code = NULL, "
            "error_summary = NULL, next_attempt_at = NULL, recovered_at = CURRENT_TIMESTAMP, finished_at = NULL, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(target[0]),),
        )
        conn.execute(
            "UPDATE telegram_existing_discovery_jobs SET status = 'queued', lease_owner = NULL, lease_until = NULL, "
            "next_attempt_at = NULL, finished_at = NULL, row_version = row_version + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (normalized_job_id,),
        )
        conn.execute(
            "INSERT INTO telegram_audit_log (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest) "
            "VALUES ('existing_discovery_target_recovered', 'admin', ?, 'telegram_existing_discovery_target', ?, ?)",
            (actor, f"{normalized_job_id}:{normalized_node_id}", digest),
        )
        conn.execute(
            "INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json) "
            "VALUES ('recover_existing_discovery_target', ?, ?, ?)",
            (key, digest, json.dumps({"job_id": normalized_job_id}, separators=(",", ":"))),
        )
    return self.get_existing_discovery_job(normalized_job_id)

def reject_application(
    self,
    *,
    telegram_user_id: int,
    expected_identity_version: int,
    idempotency_key: str,
    rejected_by: str,
    reason: str | None = None, **deps
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
    reason: str | None = None, **deps
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
    unblocked_by: str, **deps
) -> TelegramIdentity:
    TelegramIdentity = deps['TelegramIdentity']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    VersionConflictError = deps['VersionConflictError']
    _identity_from_row = deps['_identity_from_row']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']
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
    auto_block_at: int = 51, **deps
) -> AbuseNoopResult:
    """Count an already-deduplicated no-op and auto-block only on the 51st.

    The caller must invoke this after `claim_update`; otherwise Telegram's
    delivery retries would be able to inflate the counter.
    """
    AbuseNoopResult = deps['AbuseNoopResult']
    TelegramRegistryError = deps['TelegramRegistryError']
    VersionConflictError = deps['VersionConflictError']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']

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
    reason: str | None, **deps
) -> TelegramIdentity:
    TelegramIdentity = deps['TelegramIdentity']
    IdempotencyConflictError = deps['IdempotencyConflictError']
    TelegramRegistryError = deps['TelegramRegistryError']
    VersionConflictError = deps['VersionConflictError']
    _identity_from_row = deps['_identity_from_row']
    _nonempty = deps['_nonempty']
    _payload_digest = deps['_payload_digest']
    _positive_int = deps['_positive_int']
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
        if action == "reject":
            conn.execute(
                """
                INSERT OR IGNORE INTO telegram_outbox (event_type, entity_id, dedupe_key)
                VALUES ('user_application_rejected', ?, ?)
                """,
                (str(user_id), f"user:application-rejected:{user_id}:{int(row[3])}"),
            )
        conn.execute(
            """
            INSERT INTO telegram_command_receipts (scope, idempotency_key, payload_digest, result_json)
            VALUES (?, ?, ?, ?)
            """,
            (scope, key, digest, json.dumps(asdict(result), separators=(",", ":"))),
        )
    return result
