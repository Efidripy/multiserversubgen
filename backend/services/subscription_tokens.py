"""Persistent, revocable public subscription tokens.

Tokens are generated once per subscription identity and kept in SQLite so the
public URL remains stable across panel refreshes and service restarts.  The
token value is a bearer credential; the database is already root-only in the
production installation, so it is intentionally not logged or returned in
diagnostic output.
"""

from __future__ import annotations

import secrets
import sqlite3
import hashlib
from typing import Dict, Iterable, Optional

from services.db_bootstrap import connect


TOKEN_BYTES = 32


def ensure_subscription_token_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_tokens (
            kind TEXT NOT NULL,
            identifier TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (kind, identifier)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_tokens_token "
        "ON subscription_tokens(token)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_token_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            identifier TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('created', 'rotated')),
            actor_type TEXT NOT NULL CHECK(actor_type IN ('telegram_user', 'admin', 'system')),
            actor_id TEXT DEFAULT NULL,
            reason TEXT DEFAULT NULL,
            token_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_token_events_identifier "
        "ON subscription_token_events(kind, identifier, id DESC)"
    )


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _record_event(
    conn: sqlite3.Connection,
    *,
    kind: str,
    identifier: str,
    event_type: str,
    token: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    reason: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO subscription_token_events
            (kind, identifier, event_type, actor_type, actor_id, reason, token_digest)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (kind, identifier, event_type, actor_type, actor_id, reason, _token_digest(token)),
    )


def ensure_tokens(db_path: str, kind: str, identifiers: Iterable[str]) -> Dict[str, str]:
    """Return stable tokens, creating only missing rows."""
    normalized = list(dict.fromkeys(str(value).strip() for value in identifiers if str(value).strip()))
    if not normalized:
        return {}

    with connect(db_path) as conn:
        ensure_subscription_token_table(conn)
        result: Dict[str, str] = {}
        for identifier in normalized:
            row = conn.execute(
                "SELECT token FROM subscription_tokens WHERE kind = ? AND identifier = ?",
                (kind, identifier),
            ).fetchone()
            if row:
                result[identifier] = str(row[0])
                continue

            for _ in range(5):
                token = _new_token()
                try:
                    conn.execute(
                        "INSERT INTO subscription_tokens (kind, identifier, token) VALUES (?, ?, ?)",
                        (kind, identifier, token),
                    )
                    _record_event(
                        conn,
                        kind=kind,
                        identifier=identifier,
                        event_type="created",
                        token=token,
                    )
                    result[identifier] = token
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise RuntimeError("Could not allocate a unique subscription token")
        conn.commit()
    return result


def get_token(db_path: str, kind: str, identifier: str) -> Optional[str]:
    with connect(db_path) as conn:
        ensure_subscription_token_table(conn)
        row = conn.execute(
            "SELECT token FROM subscription_tokens WHERE kind = ? AND identifier = ?",
            (kind, identifier),
        ).fetchone()
    return str(row[0]) if row else None


def resolve_token(db_path: str, kind: str, token: str) -> Optional[str]:
    with connect(db_path) as conn:
        ensure_subscription_token_table(conn)
        row = conn.execute(
            "SELECT identifier FROM subscription_tokens WHERE kind = ? AND token = ?",
            (kind, token),
        ).fetchone()
    return str(row[0]) if row else None


def regenerate_token(
    db_path: str,
    kind: str,
    identifier: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    reason: str | None = None,
) -> Optional[str]:
    """Rotate a token manually without retaining its bearer value in history."""
    if actor_type not in {"telegram_user", "admin", "system"}:
        raise ValueError("actor_type is invalid")
    with connect(db_path) as conn:
        ensure_subscription_token_table(conn)
        exists = conn.execute(
            "SELECT 1 FROM subscription_tokens WHERE kind = ? AND identifier = ?",
            (kind, identifier),
        ).fetchone()
        if not exists:
            return None

        for _ in range(5):
            token = _new_token()
            try:
                conn.execute(
                    "UPDATE subscription_tokens "
                    "SET token = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE kind = ? AND identifier = ?",
                    (token, kind, identifier),
                )
                _record_event(
                    conn,
                    kind=kind,
                    identifier=identifier,
                    event_type="rotated",
                    token=token,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason=reason,
                )
                conn.commit()
                return token
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("Could not rotate subscription token")


def regenerate_tokens(
    db_path: str,
    targets: Iterable[tuple[str, str]],
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    reason: str | None = None,
) -> Dict[tuple[str, str], str]:
    """Atomically rotate several existing tokens without retaining bearer values.

    Used for an explicit customer request to replace every personal device
    link.  All target rows are checked before the first token changes, so a
    missing row cannot leave the account with a half-applied replacement.
    """

    if actor_type not in {"telegram_user", "admin", "system"}:
        raise ValueError("actor_type is invalid")
    normalized = list(dict.fromkeys(
        (str(kind).strip(), str(identifier).strip())
        for kind, identifier in targets
        if str(kind).strip() and str(identifier).strip()
    ))
    if not normalized:
        return {}

    with connect(db_path) as conn:
        ensure_subscription_token_table(conn)
        for kind, identifier in normalized:
            if conn.execute(
                "SELECT 1 FROM subscription_tokens WHERE kind = ? AND identifier = ?",
                (kind, identifier),
            ).fetchone() is None:
                raise RuntimeError("Cannot rotate a missing subscription token")

        result: Dict[tuple[str, str], str] = {}
        for kind, identifier in normalized:
            for _ in range(5):
                token = _new_token()
                try:
                    conn.execute(
                        "UPDATE subscription_tokens SET token = ?, updated_at = CURRENT_TIMESTAMP "
                        "WHERE kind = ? AND identifier = ?",
                        (token, kind, identifier),
                    )
                    _record_event(
                        conn,
                        kind=kind,
                        identifier=identifier,
                        event_type="rotated",
                        token=token,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        reason=reason,
                    )
                    result[(kind, identifier)] = token
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise RuntimeError("Could not rotate subscription token")
        conn.commit()
    return result
