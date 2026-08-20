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


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


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


def regenerate_token(db_path: str, kind: str, identifier: str) -> Optional[str]:
    """Rotate a token manually; returns None when the identity is unknown."""
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
                conn.commit()
                return token
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("Could not rotate subscription token")
