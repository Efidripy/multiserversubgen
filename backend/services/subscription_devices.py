from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from services.db_bootstrap import connect


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS subscription_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    hwid_hash TEXT NOT NULL,
    device_os TEXT NOT NULL DEFAULT '',
    os_version TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    UNIQUE(subject, hwid_hash)
)
"""
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


@dataclass(frozen=True)
class DeviceDecision:
    allowed: bool
    headers: dict[str, str]


def _section_enabled(section: Mapping[str, Any]) -> bool:
    return bool(section.get("enabled", False))


def _max_devices(section: Mapping[str, Any]) -> int:
    value = section.get("max_devices", 0)
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _header_value(headers: Mapping[str, Any], name: str) -> Any:
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted:
            return value
    return None


def _clean_metadata(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = _CONTROL_CHARS.sub("", text)
    text = "".join(char for char in text if not unicodedata.category(char).startswith("C"))
    return text[:64]


def _normalise_hwid(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value


def _hash_hwid(subject: str, hwid: str) -> str:
    return hashlib.sha256((subject + "\0" + hwid).encode("utf-8")).hexdigest()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_TABLE_SQL)


def _announce(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and not text.isascii():
        return "base64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")
    return text


def check_device(
    db_path: str,
    subject: str,
    headers: Mapping[str, Any],
    section: Mapping[str, Any],
    *,
    now: float,
) -> DeviceDecision:
    """Check and, when permitted, record the device identified by ``X-HWID``."""
    if not _section_enabled(section):
        return DeviceDecision(True, {})

    response: dict[str, str] = {"X-Hwid-Active": "true"}
    hwid = _normalise_hwid(_header_value(headers, "X-HWID"))
    if not hwid or len(hwid) > 256:
        response["X-Hwid-Not-Supported"] = "true"
        allowed = not bool(section.get("block_unsupported", False))
        if allowed and _max_devices(section) > 0:
            response["X-Hwid-Limit"] = "true"
        return DeviceDecision(allowed, response)

    device_hash = _hash_hwid(subject, hwid)
    metadata = (
        _clean_metadata(_header_value(headers, "X-Device-OS")),
        _clean_metadata(_header_value(headers, "X-Ver-OS")),
        _clean_metadata(_header_value(headers, "X-Device-Model")),
    )
    maximum = _max_devices(section)

    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_table(conn)
        row = conn.execute(
            "SELECT id FROM subscription_devices WHERE subject = ? AND hwid_hash = ?",
            (subject, device_hash),
        ).fetchone()
        if row is not None:
            conn.execute(
                """UPDATE subscription_devices
                   SET device_os = ?, os_version = ?, model = ?, last_seen = ?
                 WHERE id = ?""",
                (*metadata, now, row[0]),
            )
            allowed = True
        else:
            count = conn.execute(
                "SELECT COUNT(*) FROM subscription_devices WHERE subject = ?", (subject,)
            ).fetchone()[0]
            allowed = maximum <= 0 or count < maximum
            if allowed:
                conn.execute(
                    """INSERT INTO subscription_devices
                       (subject, hwid_hash, device_os, os_version, model, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (subject, device_hash, *metadata, now, now),
                )

    if allowed:
        if maximum > 0:
            response["X-Hwid-Limit"] = "true"
        return DeviceDecision(True, response)

    response["X-Hwid-Max-Devices-Reached"] = "true"
    response["X-Hwid-Limit"] = "true"
    announce = _announce(section.get("limit_announce", ""))
    if announce:
        response["Announce"] = announce
    return DeviceDecision(False, response)


def list_devices(
    db_path: str,
    *,
    subject: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return public device metadata; the HWID digest is intentionally omitted."""
    if limit <= 0:
        return []
    try:
        bounded_limit = min(int(limit), 200)
    except (TypeError, ValueError):
        bounded_limit = 200
    with connect(db_path) as conn:
        if not _table_exists(conn):
            return []
        if subject is None:
            rows = conn.execute(
                """SELECT id, subject, device_os, os_version, model, first_seen, last_seen
                   FROM subscription_devices ORDER BY id LIMIT ?""",
                (bounded_limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, subject, device_os, os_version, model, first_seen, last_seen
                   FROM subscription_devices WHERE subject = ? ORDER BY id LIMIT ?""",
                (subject, bounded_limit),
            ).fetchall()
    keys = ("id", "subject", "device_os", "os_version", "model", "first_seen", "last_seen")
    return [dict(zip(keys, row)) for row in rows]


def _table_exists(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'subscription_devices'"
        ).fetchone()
        is not None
    )


def delete_device(db_path: str, device_id: int) -> bool:
    with connect(db_path) as conn:
        if not _table_exists(conn):
            return False
        result = conn.execute("DELETE FROM subscription_devices WHERE id = ?", (device_id,))
        return result.rowcount > 0


def device_status(db_path: str, subject: str, section: Mapping[str, Any]) -> dict[str, Any]:
    maximum = _max_devices(section)
    with connect(db_path) as conn:
        if not _table_exists(conn):
            count = 0
        else:
            count = conn.execute(
                "SELECT COUNT(*) FROM subscription_devices WHERE subject = ?", (subject,)
            ).fetchone()[0]
    return {"count": count, "max_devices": maximum, "reached": maximum > 0 and count >= maximum}
