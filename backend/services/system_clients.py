"""Classification helpers for operator-hidden system clients.

The 3x-ui ``comment`` field remains the source of truth. A standalone
``system`` marker (case-insensitive) marks an operational client that should
not appear in ordinary client and online-user views. Traffic accounting stays
unchanged; consumers decide whether a particular presentation filters it.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Set


_SYSTEM_MARKER = re.compile(r"(?<!\w)system(?!\w)", re.IGNORECASE)


def normalize_email(value: object) -> str:
    return str(value or "").strip().casefold()


def has_system_comment(value: object) -> bool:
    return isinstance(value, str) and bool(_SYSTEM_MARKER.search(value))


def is_system_client(client: Dict) -> bool:
    return has_system_comment(client.get("comment"))


def annotate_system_clients(clients: Iterable[Dict]) -> list[Dict]:
    """Return shallow copies with an explicit UI-safe ``is_system`` flag."""
    return [{**client, "is_system": is_system_client(client)} for client in clients]


def system_client_emails_from_inbounds(inbounds: Iterable[Dict]) -> Set[str]:
    """Extract SYSTEM client emails from already-collected inbound settings.

    ``ThreeXUIMonitor`` normalizes ``settings`` to a dict. Defensive checks
    keep an incomplete or legacy inbound from affecting unrelated clients.
    """
    emails: Set[str] = set()
    for inbound in inbounds:
        if not isinstance(inbound, dict):
            continue
        settings = inbound.get("settings")
        if not isinstance(settings, dict):
            continue
        clients = settings.get("clients")
        if not isinstance(clients, list):
            continue
        for client in clients:
            if not isinstance(client, dict) or not is_system_client(client):
                continue
            email = normalize_email(client.get("email"))
            if email:
                emails.add(email)
    return emails
