"""Read-only Telegram-link marker for the panel's client projection."""

from __future__ import annotations

import unicodedata
from typing import Dict, Iterable, List

from services.db_bootstrap import connect


def _canonical_email(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def annotate_clients_with_telegram_link(db_path: str, clients: Iterable[Dict]) -> List[Dict]:
    """Add a boolean marker without disclosing Telegram identity details.

    The panel groups node records by email, while ``customers`` is the local
    identity authority. This bounded bulk lookup projects only whether a live
    customer has any Telegram binding; it never selects Telegram IDs, handles,
    names, or access-state details.
    """

    result = [dict(client) for client in clients]
    canonical_emails = {_canonical_email(client.get("email")) for client in result}
    canonical_emails.discard("")
    if not canonical_emails:
        for client in result:
            client["telegram_linked"] = False
        return result

    linked_emails: set[str] = set()
    email_values = sorted(canonical_emails)
    with connect(db_path) as conn:
        # Keep below SQLite's conventional 999-bind limit, with one lookup per
        # chunk instead of one read for each panel client row.
        for offset in range(0, len(email_values), 900):
            chunk = email_values[offset:offset + 900]
            placeholders = ", ".join("?" for _ in chunk)
            rows = conn.execute(
                f"""
                SELECT c.email_canonical
                FROM customers AS c
                WHERE c.deleted_at IS NULL
                  AND c.email_canonical IN ({placeholders})
                  AND EXISTS (
                      SELECT 1
                      FROM telegram_identities AS identity
                      WHERE identity.customer_id = c.id
                  )
                """,
                chunk,
            ).fetchall()
            linked_emails.update(str(row[0]) for row in rows)

    for client in result:
        client["telegram_linked"] = _canonical_email(client.get("email")) in linked_emails
    return result
