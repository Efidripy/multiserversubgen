"""Guest links, logical devices, subscription devices, and quality events."""

from __future__ import annotations

import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from services.db_bootstrap import connect


def create_guest_subscription_link(
    self,
    *,
    telegram_user_id: int,
    duration_hours: int,
    positive_int,
    error_type,
    active_telegram_customer,
    guest_link_durations_hours,
    guest_link_type,
    payload_digest,
) -> Any:
    """Issue one revocable guest link without changing the personal token.

    A new guest link revokes the user's previous active guest link. This
    deliberately makes the share surface easy to understand and bounds
    accidental exposure while keeping the primary subscription untouched.
    """

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    if (
        isinstance(duration_hours, bool)
        or duration_hours not in guest_link_durations_hours
    ):
        raise error_type("guest link duration is invalid")
    expires_at = int(datetime.now(timezone.utc).timestamp()) + duration_hours * 60 * 60
    with connect(self._db_path) as conn:
        customer_id, email_display = active_telegram_customer(conn, user_id)
        conn.execute(
            """
            UPDATE telegram_guest_subscription_links
            SET revoked_at = CURRENT_TIMESTAMP, revoked_by_telegram_user_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE customer_id = ? AND revoked_at IS NULL AND expires_at > ?
            """,
            (user_id, customer_id, int(datetime.now(timezone.utc).timestamp())),
        )
        for _ in range(5):
            token = secrets.token_urlsafe(32)
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO telegram_guest_subscription_links
                        (customer_id, email_display, token, expires_at, created_by_telegram_user_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (customer_id, email_display, token, expires_at, user_id),
                )
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise error_type("could not allocate guest link")
        guest_link_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO telegram_logical_devices (customer_id, kind, label, guest_link_id)
            VALUES (?, 'guest', 'Гостевая ссылка', ?)
            """,
            (customer_id, guest_link_id),
        )
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('guest_link_created', 'telegram_user', ?, 'telegram_guest_link', ?, ?)
            """,
            (
                str(user_id),
                str(guest_link_id),
                payload_digest({"duration_hours": duration_hours}),
            ),
        )
    return guest_link_type(
        guest_link_id=guest_link_id,
        customer_id=customer_id,
        email_display=email_display,
        expires_at=expires_at,
        status="active",
        token=token,
    )


def resolve_guest_subscription_link(self, token: str, *, guest_link_type) -> Any:
    """Resolve only a live guest bearer token for the anonymous endpoint."""

    if not isinstance(token, str) or not 20 <= len(token) <= 256:
        return None
    current_epoch = int(datetime.now(timezone.utc).timestamp())
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT g.id, g.customer_id, g.email_display, g.expires_at
            FROM telegram_guest_subscription_links AS g
            JOIN customers AS c ON c.id = g.customer_id
            WHERE g.token = ? AND g.revoked_at IS NULL AND g.expires_at > ?
              AND c.status = 'active' AND c.deleted_at IS NULL
            """,
            (token, current_epoch),
        ).fetchone()
    if row is None:
        return None
    return guest_link_type(
        guest_link_id=int(row[0]),
        customer_id=int(row[1]),
        email_display=str(row[2]),
        expires_at=int(row[3]),
        status="active",
    )


def get_guest_subscription_link(
    self,
    *,
    telegram_user_id: int,
    guest_link_id: int,
    positive_int,
    error_type,
    active_telegram_customer,
    guest_link_type,
) -> Any:
    """Return one live guest link owned by the Telegram user's customer."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    link_id = positive_int(guest_link_id, "guest_link_id")
    current_epoch = int(datetime.now(timezone.utc).timestamp())
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        row = conn.execute(
            """
            SELECT id, customer_id, email_display, expires_at, token
            FROM telegram_guest_subscription_links
            WHERE id = ? AND customer_id = ? AND revoked_at IS NULL AND expires_at > ?
            """,
            (link_id, customer_id, current_epoch),
        ).fetchone()
    if row is None:
        raise error_type("guest link was not found")
    return guest_link_type(
        guest_link_id=int(row[0]),
        customer_id=int(row[1]),
        email_display=str(row[2]),
        expires_at=int(row[3]),
        status="active",
        token=str(row[4]),
    )


def _ensure_primary_logical_device(
    self, conn: sqlite3.Connection, customer_id: int
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO telegram_logical_devices (customer_id, kind, label)
        VALUES (?, 'primary', 'Основное подключение')
        """,
        (customer_id,),
    )


def list_logical_devices(
    self,
    telegram_user_id: int,
    *,
    include_inactive: bool = True,
    positive_int,
    active_telegram_customer,
    ensure_primary_logical_device,
    logical_device_type,
) -> tuple[Any, ...]:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    current_epoch = int(datetime.now(timezone.utc).timestamp())
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        ensure_primary_logical_device(conn, customer_id)
        rows = conn.execute(
            """
            SELECT d.id, d.customer_id, d.kind, d.label, d.guest_link_id, d.created_at,
                   g.expires_at, g.revoked_at
            FROM telegram_logical_devices AS d
            LEFT JOIN telegram_guest_subscription_links AS g ON g.id = d.guest_link_id
            WHERE d.customer_id = ?
            ORDER BY CASE d.kind WHEN 'primary' THEN 0 ELSE 1 END, d.id DESC
            """,
            (customer_id,),
        ).fetchall()
    devices: list[logical_device_type] = []
    for row in rows:
        if str(row[2]) == "primary":
            status, expires_at = "active", None
        elif row[7] is not None:
            status, expires_at = "revoked", int(row[6]) if row[6] is not None else None
        elif row[6] is None or int(row[6]) <= current_epoch:
            status, expires_at = "expired", int(row[6]) if row[6] is not None else None
        else:
            status, expires_at = "active", int(row[6])
        device = logical_device_type(
            device_id=int(row[0]),
            customer_id=int(row[1]),
            kind=str(row[2]),
            label=str(row[3]),
            guest_link_id=int(row[4]) if row[4] is not None else None,
            status=status,
            created_at=str(row[5]),
            expires_at=expires_at,
        )
        if include_inactive or device.status == "active":
            devices.append(device)
    return tuple(devices)


def list_subscription_devices(
    self,
    telegram_user_id: int,
    *,
    positive_int,
    active_telegram_customer,
    subscription_device_type,
) -> tuple[Any, ...]:
    """List active customer's persistent device links without bearer tokens."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        rows = conn.execute(
            """
            SELECT id, customer_id, token_identifier, label, created_at
            FROM telegram_subscription_devices
            WHERE customer_id = ? AND revoked_at IS NULL
            ORDER BY id ASC
            """,
            (customer_id,),
        ).fetchall()
    return tuple(
        subscription_device_type(
            device_id=int(row[0]),
            customer_id=int(row[1]),
            token_identifier=str(row[2]),
            label=str(row[3]),
            created_at=str(row[4]),
        )
        for row in rows
    )


def list_customer_subscription_links(
    self, customer_id: int, *, positive_int, error_type, customer_subscription_link_type
) -> tuple[Any, ...]:
    """List issued link metadata for an admin card without exposing bearer tokens."""

    local_customer_id = positive_int(customer_id, "customer_id")
    current_epoch = int(datetime.now(timezone.utc).timestamp())
    with connect(self._db_path) as conn:
        customer = conn.execute(
            "SELECT email_display FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if customer is None:
            raise error_type("customer was not found")
        email_display = str(customer[0])
        primary = conn.execute(
            """
            SELECT COALESCE(d.label, 'Основная ссылка'), t.created_at
            FROM subscription_tokens AS t
            LEFT JOIN telegram_logical_devices AS d
              ON d.customer_id = ? AND d.kind = 'primary'
            WHERE t.kind = 'email' AND t.identifier = ?
            LIMIT 1
            """,
            (local_customer_id, email_display),
        ).fetchone()
        personal_rows = conn.execute(
            """
            SELECT d.label, d.created_at, d.revoked_at, t.created_at
            FROM telegram_subscription_devices AS d
            JOIN subscription_tokens AS t
              ON t.kind = 'telegram_device' AND t.identifier = d.token_identifier
            WHERE d.customer_id = ?
            ORDER BY d.id ASC
            """,
            (local_customer_id,),
        ).fetchall()
        guest_rows = conn.execute(
            """
            SELECT g.created_at, g.expires_at, g.revoked_at
            FROM telegram_guest_subscription_links AS g
            WHERE g.customer_id = ?
            ORDER BY g.id DESC
            LIMIT 5
            """,
            (local_customer_id,),
        ).fetchall()

    links: list[customer_subscription_link_type] = []
    if primary is not None:
        links.append(
            customer_subscription_link_type(
                kind="primary",
                label=str(primary[0]),
                status="active",
                created_at=str(primary[1]),
            )
        )
    for row in personal_rows:
        links.append(
            customer_subscription_link_type(
                kind="personal",
                label=str(row[0]),
                status="revoked" if row[2] is not None else "active",
                created_at=str(row[3] or row[1]),
            )
        )
    for row in guest_rows:
        expires_at = int(row[1])
        status = (
            "revoked"
            if row[2] is not None
            else "active"
            if expires_at > current_epoch
            else "expired"
        )
        links.append(
            customer_subscription_link_type(
                kind="guest",
                label="Гостевая ссылка",
                status=status,
                created_at=str(row[0]),
                expires_at=expires_at,
            )
        )
    return tuple(links)


def get_subscription_device(
    self,
    *,
    telegram_user_id: int,
    subscription_device_id: int,
    positive_int,
    error_type,
    active_telegram_customer,
    subscription_device_type,
) -> Any:
    """Return a device only when it belongs to the active calling customer."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    device_id = positive_int(subscription_device_id, "subscription_device_id")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        row = conn.execute(
            """
            SELECT id, customer_id, token_identifier, label, created_at
            FROM telegram_subscription_devices
            WHERE id = ? AND customer_id = ? AND revoked_at IS NULL
            """,
            (device_id, customer_id),
        ).fetchone()
    if row is None:
        raise error_type("subscription device was not found")
    return subscription_device_type(
        device_id=int(row[0]),
        customer_id=int(row[1]),
        token_identifier=str(row[2]),
        label=str(row[3]),
        created_at=str(row[4]),
    )


def create_subscription_device(
    self,
    *,
    telegram_user_id: int,
    label: str,
    positive_int,
    error_type,
    active_telegram_customer,
    payload_digest,
    subscription_device_type,
) -> Any:
    """Create a new independently rotatable personal device link record."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    normalized_label = label.strip() if isinstance(label, str) else ""
    if not 1 <= len(normalized_label) <= 80:
        raise error_type("subscription device label must contain 1 to 80 characters")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        for _ in range(5):
            token_identifier = uuid.uuid4().hex
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO telegram_subscription_devices (customer_id, token_identifier, label)
                    VALUES (?, ?, ?)
                    """,
                    (customer_id, token_identifier, normalized_label),
                )
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise error_type("could not allocate subscription device")
        device_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id, payload_digest)
            VALUES ('subscription_device_created', 'telegram_user', ?, 'telegram_subscription_device', ?, ?)
            """,
            (str(user_id), str(device_id), payload_digest({"label": normalized_label})),
        )
        row = conn.execute(
            """
            SELECT id, customer_id, token_identifier, label, created_at
            FROM telegram_subscription_devices WHERE id = ?
            """,
            (device_id,),
        ).fetchone()
    assert row is not None
    return subscription_device_type(
        device_id=int(row[0]),
        customer_id=int(row[1]),
        token_identifier=str(row[2]),
        label=str(row[3]),
        created_at=str(row[4]),
    )


def set_subscription_device_label(
    self,
    *,
    telegram_user_id: int,
    subscription_device_id: int,
    label: str,
    positive_int,
    error_type,
    active_telegram_customer,
    get_subscription_device,
) -> Any:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    device_id = positive_int(subscription_device_id, "subscription_device_id")
    normalized_label = label.strip() if isinstance(label, str) else ""
    if not 1 <= len(normalized_label) <= 80:
        raise error_type("subscription device label must contain 1 to 80 characters")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        cursor = conn.execute(
            """
            UPDATE telegram_subscription_devices
            SET label = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND customer_id = ? AND revoked_at IS NULL
            """,
            (normalized_label, device_id, customer_id),
        )
        if cursor.rowcount != 1:
            raise error_type("subscription device was not found")
    return get_subscription_device(
        telegram_user_id=user_id, subscription_device_id=device_id
    )


def revoke_subscription_device(
    self,
    *,
    telegram_user_id: int,
    subscription_device_id: int,
    positive_int,
    error_type,
    active_telegram_customer,
) -> None:
    """Soft-revoke one owned device link while preserving the audit trail."""

    user_id = positive_int(telegram_user_id, "telegram_user_id")
    device_id = positive_int(subscription_device_id, "subscription_device_id")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        cursor = conn.execute(
            """
            UPDATE telegram_subscription_devices
            SET revoked_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND customer_id = ? AND revoked_at IS NULL
            """,
            (device_id, customer_id),
        )
        if cursor.rowcount != 1:
            raise error_type("subscription device was not found")
        conn.execute(
            """
            INSERT INTO telegram_audit_log
                (event_type, actor_type, actor_id, entity_type, entity_id)
            VALUES ('subscription_device_revoked', 'telegram_user', ?, 'telegram_subscription_device', ?)
            """,
            (str(user_id), str(device_id)),
        )


def resolve_subscription_device_email(self, token_identifier: str) -> str | None:
    """Resolve a persistent device identifier only for active approved access."""

    normalized_identifier = (
        token_identifier.strip() if isinstance(token_identifier, str) else ""
    )
    if not normalized_identifier or len(normalized_identifier) > 128:
        return None
    with connect(self._db_path) as conn:
        row = conn.execute(
            """
            SELECT c.email_display
            FROM telegram_subscription_devices AS d
            JOIN customers AS c ON c.id = d.customer_id
            JOIN telegram_identities AS i ON i.customer_id = c.id
            WHERE d.token_identifier = ? AND i.access_status = 'approved'
              AND d.revoked_at IS NULL AND c.status = 'active' AND c.deleted_at IS NULL
            LIMIT 1
            """,
            (normalized_identifier,),
        ).fetchone()
    return str(row[0]) if row is not None else None


def set_logical_device_label(
    self,
    *,
    telegram_user_id: int,
    device_id: int,
    label: str,
    positive_int,
    error_type,
    active_telegram_customer,
    list_logical_devices,
) -> Any:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    local_device_id = positive_int(device_id, "device_id")
    normalized_label = label.strip() if isinstance(label, str) else ""
    if not 1 <= len(normalized_label) <= 80:
        raise error_type("logical device label must contain 1 to 80 characters")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        row = conn.execute(
            """
            SELECT id, kind, guest_link_id, created_at FROM telegram_logical_devices
            WHERE id = ? AND customer_id = ?
            """,
            (local_device_id, customer_id),
        ).fetchone()
        if row is None:
            raise error_type("logical device was not found")
        conn.execute(
            "UPDATE telegram_logical_devices SET label = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (normalized_label, local_device_id),
        )
    devices = {item.device_id: item for item in list_logical_devices(user_id)}
    return devices[local_device_id]


def revoke_guest_subscription_link(
    self,
    *,
    telegram_user_id: int,
    guest_link_id: int,
    positive_int,
    error_type,
    active_telegram_customer,
) -> None:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    link_id = positive_int(guest_link_id, "guest_link_id")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        row = conn.execute(
            "SELECT revoked_at FROM telegram_guest_subscription_links WHERE id = ? AND customer_id = ?",
            (link_id, customer_id),
        ).fetchone()
        if row is None:
            raise error_type("guest link was not found")
        if row[0] is None:
            conn.execute(
                """
                UPDATE telegram_guest_subscription_links
                SET revoked_at = CURRENT_TIMESTAMP, revoked_by_telegram_user_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (user_id, link_id),
            )
            conn.execute(
                """
                INSERT INTO telegram_audit_log
                    (event_type, actor_type, actor_id, entity_type, entity_id)
                VALUES ('guest_link_revoked', 'telegram_user', ?, 'telegram_guest_link', ?)
                """,
                (str(user_id), str(link_id)),
            )


def submit_quality_report(
    self,
    *,
    telegram_user_id: int,
    kind: str,
    platform: str,
    positive_int,
    error_type,
    active_telegram_customer,
    quality_report_type,
) -> Any:
    user_id = positive_int(telegram_user_id, "telegram_user_id")
    if kind not in {"ok", "slow", "connection", "routes"}:
        raise error_type("quality report type is invalid")
    if platform not in {"android", "ios", "desktop", "other"}:
        raise error_type("quality report platform is invalid")
    with connect(self._db_path) as conn:
        customer_id, _email_display = active_telegram_customer(conn, user_id)
        cursor = conn.execute(
            """
            INSERT INTO telegram_quality_reports (telegram_user_id, customer_id, kind, platform)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, customer_id, kind, platform),
        )
        report_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO telegram_outbox (event_type, entity_id, dedupe_key)
            VALUES ('admin_quality_report_created', ?, ?)
            """,
            (str(report_id), f"admin:quality-report:{report_id}"),
        )
        row = conn.execute(
            "SELECT created_at FROM telegram_quality_reports WHERE id = ?", (report_id,)
        ).fetchone()
    assert row is not None
    return quality_report_type(
        report_id, user_id, customer_id, kind, platform, str(row[0])
    )


def list_customer_quality_reports(
    self,
    customer_id: int,
    *,
    limit: int = 5,
    positive_int,
    error_type,
    quality_report_type,
) -> tuple[Any, ...]:
    local_customer_id = positive_int(customer_id, "customer_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise error_type("quality report limit is invalid")
    with connect(self._db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, telegram_user_id, customer_id, kind, platform, created_at
            FROM telegram_quality_reports WHERE customer_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (local_customer_id, limit),
        ).fetchall()
    return tuple(
        quality_report_type(
            report_id=int(row[0]),
            telegram_user_id=int(row[1]),
            customer_id=int(row[2]),
            kind=str(row[3]),
            platform=str(row[4]),
            created_at=str(row[5]),
        )
        for row in rows
    )


def list_subscription_token_events(
    self,
    customer_id: int,
    *,
    limit: int = 5,
    positive_int,
    error_type,
    token_event_type,
) -> tuple[Any, ...]:
    local_customer_id = positive_int(customer_id, "customer_id")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
        raise error_type("subscription token event limit is invalid")
    with connect(self._db_path) as conn:
        row = conn.execute(
            "SELECT email_display FROM customers WHERE id = ?", (local_customer_id,)
        ).fetchone()
        if row is None:
            raise error_type("customer was not found")
        events = conn.execute(
            """
            SELECT event_type, actor_type, actor_id, reason, created_at
            FROM subscription_token_events
            WHERE kind = 'email' AND identifier = ?
            ORDER BY id DESC LIMIT ?
            """,
            (str(row[0]), limit),
        ).fetchall()
    return tuple(
        token_event_type(
            event_type=str(event[0]),
            actor_type=str(event[1]),
            actor_id=str(event[2]) if event[2] is not None else None,
            reason=str(event[3]) if event[3] is not None else None,
            created_at=str(event[4]),
        )
        for event in events
    )
