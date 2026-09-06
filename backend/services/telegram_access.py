"""Fail-closed access decisions shared by Telegram and public subscriptions.

The Telegram identity is the authority for bot interaction.  A public
subscription URL is a bearer credential, so an already-issued URL remains
usable for a customer who was only bot-blocked after approval.  Lifecycle
states still deny both surfaces immediately.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from services.db_bootstrap import connect


SUSPENDED_STATUSES = frozenset({"suspending", "suspended", "suspend_partial", "resuming", "resume_partial"})
REVOKING_STATUSES = frozenset({"deleting", "delete_partial", "deleted"})


@dataclass(frozen=True)
class TelegramEffectiveAccess:
    """One deterministic decision for a linked Telegram customer."""

    state: str
    can_receive_subscription: bool
    can_use_public_subscription: bool
    can_submit_appeal: bool


def resolve_effective_access(
    *,
    access_status: str,
    customer_id: int | None,
    email_display: str | None,
    customer_status: str | None,
    blocked_from_status: str | None = None,
) -> TelegramEffectiveAccess:
    """Resolve access without performing I/O.

    Unknown combinations are deliberately unavailable.  This prevents a
    partial migration or a future status from accidentally granting a link.
    """

    if customer_id is None or not email_display or not customer_status:
        return TelegramEffectiveAccess("binding_incomplete", False, False, False)
    if customer_status in SUSPENDED_STATUSES:
        return TelegramEffectiveAccess(
            "suspended",
            False,
            False,
            access_status == "approved" and customer_status in {"suspended", "suspend_partial"},
        )
    if customer_status in REVOKING_STATUSES:
        return TelegramEffectiveAccess("revoking", False, False, False)
    if customer_status != "active":
        return TelegramEffectiveAccess("unavailable", False, False, False)
    if access_status == "approved":
        return TelegramEffectiveAccess("active", True, True, False)
    if access_status == "blocked":
        # A block applied to an already approved user blocks bot interaction,
        # but does not revoke an existing bearer URL. Lifecycle changes do.
        return TelegramEffectiveAccess(
            "blocked",
            False,
            blocked_from_status == "approved",
            False,
        )
    return TelegramEffectiveAccess("approval_required", False, False, False)


def _canonical_email(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


class TelegramSubscriptionAccessGate:
    """Read-only gate for opaque email subscription URLs.

    Customers with no Telegram-local record retain the pre-existing panel
    behavior.  A Telegram-origin customer without one unambiguous linked
    identity is denied instead of being treated as an ordinary legacy email.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    def can_serve_email(self, email: str) -> bool:
        canonical = _canonical_email(email)
        if not canonical:
            return False
        with connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.email_display, c.origin, c.status, c.deleted_at,
                       i.access_status, i.blocked_from_status
                FROM customers AS c
                LEFT JOIN telegram_identities AS i ON i.customer_id = c.id
                WHERE c.email_canonical = ?
                ORDER BY c.deleted_at IS NULL DESC, c.id DESC, i.telegram_user_id ASC
                """,
                (canonical,),
            ).fetchall()
        if not rows:
            return True

        live_rows = [row for row in rows if row[4] is None]
        if not live_rows:
            # An email belonging only to a deleted Telegram customer must not
            # turn into a valid legacy subscription merely because its old
            # opaque token remains in SQLite.
            return not any(str(row[2]) == "telegram" for row in rows)
        if len(live_rows) != 1:
            return False

        customer_id, display, origin, status, _deleted_at, identity_status, blocked_from = live_rows[0]
        if identity_status is None:
            return str(origin) != "telegram"
        decision = resolve_effective_access(
            access_status=str(identity_status),
            customer_id=int(customer_id),
            email_display=str(display),
            customer_status=str(status),
            blocked_from_status=str(blocked_from) if blocked_from is not None else None,
        )
        return decision.can_use_public_subscription
