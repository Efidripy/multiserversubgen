from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from services.db_bootstrap import connect


def normalize_client_identifier(value: object) -> str:
    return str(value or "").strip()


def normalize_note(value: object) -> str:
    return str(value or "").strip()


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def client_identity(client: Dict, *, node_name_to_id: Optional[Dict[str, int]] = None) -> Optional[Tuple[int, int, str]]:
    node_id = _coerce_int(client.get("node_id"), default=0)
    if not node_id and node_name_to_id:
        node_id = node_name_to_id.get(str(client.get("node_name") or ""), 0)
    if not node_id:
        return None

    inbound_id = _coerce_int(client.get("inbound_id"), default=0)
    identifier = normalize_client_identifier(
        client.get("id") or client.get("password") or client.get("email")
    )
    if not identifier:
        return None
    return node_id, inbound_id, identifier


def enrich_clients_with_notes(db_path: str, clients: Iterable[Dict], *, nodes: Optional[List[Dict]] = None) -> List[Dict]:
    result = [dict(client) for client in clients]
    if not result:
        return result

    node_name_to_id = {
        str(node.get("name") or ""): _coerce_int(node.get("id"), default=0)
        for node in (nodes or [])
    }
    identities = [
        identity
        for identity in (client_identity(client, node_name_to_id=node_name_to_id) for client in result)
        if identity is not None
    ]
    if not identities:
        for client in result:
            client.setdefault("notes", "")
        return result

    # Query only notes for the clients returned by this request. The composite
    # unique key already supports this lookup; scanning every historical note
    # on each clients refresh becomes increasingly expensive over time.
    rows = []
    unique_identities = list(dict.fromkeys(identities))
    with connect(db_path) as conn:
        for offset in range(0, len(unique_identities), 300):
            chunk = unique_identities[offset:offset + 300]
            predicates = " OR ".join(
                "(node_id = ? AND inbound_id = ? AND client_identifier = ?)"
                for _ in chunk
            )
            parameters = [value for identity in chunk for value in identity]
            rows.extend(
                conn.execute(
                    f"""
                    SELECT node_id, inbound_id, client_identifier, notes
                    FROM client_notes
                    WHERE {predicates}
                    """,
                    parameters,
                ).fetchall()
            )

    notes_by_key = {
        (int(row[0]), int(row[1] or 0), str(row[2])): str(row[3] or "")
        for row in rows
    }
    identity_set = set(identities)
    for client in result:
        identity = client_identity(client, node_name_to_id=node_name_to_id)
        if identity and identity in identity_set:
            client["node_id"] = identity[0]
            client["notes"] = notes_by_key.get(identity, "")
        else:
            client.setdefault("notes", "")
    return result


def upsert_client_note(
    db_path: str,
    *,
    node_id: object,
    inbound_id: object,
    client_identifier: object,
    email: object,
    notes: object,
) -> Dict:
    normalized_node_id = _coerce_int(node_id, default=0)
    normalized_inbound_id = _coerce_int(inbound_id, default=0)
    normalized_identifier = normalize_client_identifier(client_identifier)
    normalized_email = str(email or "").strip()
    normalized_notes = normalize_note(notes)

    if not normalized_node_id:
        raise ValueError("node_id is required")
    if not normalized_identifier:
        raise ValueError("client_identifier is required")
    if not normalized_email:
        raise ValueError("email is required")

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO client_notes (
                node_id, inbound_id, client_identifier, email, notes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(node_id, inbound_id, client_identifier)
            DO UPDATE SET
                email = excluded.email,
                notes = excluded.notes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                normalized_node_id,
                normalized_inbound_id,
                normalized_identifier,
                normalized_email,
                normalized_notes,
            ),
        )

    return {
        "node_id": normalized_node_id,
        "inbound_id": normalized_inbound_id,
        "client_identifier": normalized_identifier,
        "email": normalized_email,
        "notes": normalized_notes,
    }
