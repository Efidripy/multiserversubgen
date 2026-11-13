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
    user_agent TEXT NOT NULL DEFAULT '',
    has_hwid INTEGER NOT NULL DEFAULT 1,
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
    cols = {row[1] for row in conn.execute("PRAGMA table_info(subscription_devices)").fetchall()}
    if "user_agent" not in cols:
        conn.execute("ALTER TABLE subscription_devices ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''")
    if "has_hwid" not in cols:
        conn.execute("ALTER TABLE subscription_devices ADD COLUMN has_hwid INTEGER NOT NULL DEFAULT 1")


def _parse_user_agent(ua: str) -> tuple[str, str, str]:
    """Extract only OS and model information explicitly present in a user agent."""
    patterns = (
        (r"Android[ /-]+([\d.]+)", "Android"),
        (r"(?:iPhone OS|iOS)[ /-]+([\d._]+)", "iOS"),
        (r"Windows NT[ /-]+([\d.]+)", "Windows"),
        (r"Mac OS X[ /-]+([\d._]+)", "macOS"),
    )
    os_name = version = model = ""
    for pattern, name in patterns:
        match = re.search(pattern, ua, re.I)
        if match:
            os_name, version = name, match.group(1).replace("_", ".")
            break
    if not os_name and re.search(r"\bLinux\b", ua, re.I):
        os_name = "Linux"
    match = re.search(r";\s*([^;()]+?)\s+Build(?:/|[; )])", ua, re.I)
    if not match:
        match = re.search(r"\b(iPhone\d+,\d+)\b", ua, re.I)
    if match:
        model = match.group(1).strip()
    return os_name, version, model


def _metadata(headers: Mapping[str, Any], ua: str) -> tuple[str, str, str]:
    parsed = _parse_user_agent(ua)
    names = (("X-Device-OS", "Sec-CH-UA-Platform"),
             ("X-Ver-OS", "Sec-CH-UA-Platform-Version"),
             ("X-Device-Model", "Sec-CH-UA-Model"))
    values = []
    for index, (primary, fallback) in enumerate(names):
        value = _clean_metadata(_header_value(headers, primary)).strip()
        if not value:
            value = _clean_metadata(_header_value(headers, fallback)).strip().strip('"').strip()
        values.append(value or _clean_metadata(parsed[index]))
    return tuple(values)


def _announce(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and not text.isascii():
        return "base64:" + base64.b64encode(text.encode("utf-8")).decode("ascii")
    return text


# A device that polls often must not take the database write lock on every fetch:
# the lock is shared with every other writer, so a busy window turns into "database is locked".
_TOUCH_INTERVAL_SEC = 60


def _is_fresh(db_path: str, subject: str, device_hash: str, metadata: tuple, ua: str, now: float) -> bool:
    """True when this exact device was recorded moments ago, so a write would change nothing."""
    try:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT device_os, os_version, model, user_agent, last_seen FROM subscription_devices "
                "WHERE subject = ? AND hwid_hash = ?", (subject, device_hash),
            ).fetchone()
    except sqlite3.Error:
        return False
    if row is None or not (0 <= now - float(row[4]) < _TOUCH_INTERVAL_SEC):
        return False
    return tuple(row[:3]) == tuple(metadata) and (not ua or row[3] == ua)


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
    raw_ua = _header_value(headers, "User-Agent")
    normalised_ua = " ".join(_CONTROL_CHARS.sub("", str(raw_ua or "")).split())
    ua = _clean_metadata(normalised_ua)
    metadata = _metadata(headers, normalised_ua)
    if not hwid or len(hwid) > 256:
        response["X-Hwid-Not-Supported"] = "true"
        device_hash = "nohwid:" + _hash_hwid(subject, normalised_ua)
        if _is_fresh(db_path, subject, device_hash, metadata, ua, now):
            return DeviceDecision(not bool(section.get("block_unsupported", False)), response)
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            _ensure_table(conn)
            conn.execute(
                """INSERT INTO subscription_devices
                   (subject, hwid_hash, device_os, os_version, model, first_seen, last_seen, user_agent, has_hwid)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                   ON CONFLICT(subject, hwid_hash) DO UPDATE SET
                   device_os=excluded.device_os, os_version=excluded.os_version, model=excluded.model,
                   last_seen=excluded.last_seen, user_agent=excluded.user_agent""",
                (subject, device_hash, *metadata, now, now, ua),
            )
            # shortcut: 20, revisit when more unsupported clients need to be retained
            conn.execute(
                """DELETE FROM subscription_devices WHERE id IN (
                   SELECT id FROM subscription_devices WHERE subject = ? AND has_hwid = 0
                   ORDER BY last_seen DESC, id DESC LIMIT -1 OFFSET 20)""", (subject,)
            )
        return DeviceDecision(not bool(section.get("block_unsupported", False)), response)

    device_hash = _hash_hwid(subject, hwid)
    maximum = _max_devices(section)

    if _is_fresh(db_path, subject, device_hash, metadata, ua, now):
        return DeviceDecision(True, response)

    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_table(conn)
        row = conn.execute(
            "SELECT id FROM subscription_devices WHERE subject = ? AND hwid_hash = ?",
            (subject, device_hash),
        ).fetchone()
        if row is not None:
            if ua:
                conn.execute(
                    """UPDATE subscription_devices
                       SET device_os = ?, os_version = ?, model = ?, user_agent = ?, last_seen = ?
                     WHERE id = ?""",
                    (*metadata, ua, now, row[0]),
                )
            else:
                conn.execute(
                    """UPDATE subscription_devices
                       SET device_os = ?, os_version = ?, model = ?, last_seen = ?
                     WHERE id = ?""",
                    (*metadata, now, row[0]),
                )
            allowed = True
        else:
            count = conn.execute(
                "SELECT COUNT(*) FROM subscription_devices WHERE subject = ? AND has_hwid = 1", (subject,)
            ).fetchone()[0]
            allowed = maximum <= 0 or count < maximum
            if allowed:
                conn.execute(
                    """INSERT INTO subscription_devices
                       (subject, hwid_hash, device_os, os_version, model, first_seen, last_seen, user_agent)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (subject, device_hash, *metadata, now, now, ua),
                )

    if allowed:
        return DeviceDecision(True, response)

    response["X-Hwid-Max-Devices-Reached"] = "true"
    # Clients read X-Hwid-Limit as "limit reached", so it must not appear on allowed responses.
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
    # shortcut: 5000, перейти на пагинацию при росте базы устройств
    try:
        bounded_limit = min(int(limit), 5000)
    except (TypeError, ValueError):
        bounded_limit = 200
    with connect(db_path) as conn:
        if not _table_exists(conn):
            return []
        cols = {row[1] for row in conn.execute("PRAGMA table_info(subscription_devices)").fetchall()}
        ua_select = "user_agent" if "user_agent" in cols else "'' AS user_agent"
        hwid_select = "has_hwid" if "has_hwid" in cols else "1 AS has_hwid"
        if subject is None:
            rows = conn.execute(
                f"""SELECT id, subject, device_os, os_version, model, first_seen, last_seen, {ua_select}, {hwid_select}
                   FROM subscription_devices ORDER BY id LIMIT ?""",
                (bounded_limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"""SELECT id, subject, device_os, os_version, model, first_seen, last_seen, {ua_select}, {hwid_select}
                   FROM subscription_devices WHERE subject = ? ORDER BY id LIMIT ?""",
                (subject, bounded_limit),
            ).fetchall()
    keys = ("id", "subject", "device_os", "os_version", "model", "first_seen", "last_seen", "user_agent", "has_hwid")
    return [{**dict(zip(keys, row)), "has_hwid": bool(row[-1])} for row in rows]


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
            cols = {row[1] for row in conn.execute("PRAGMA table_info(subscription_devices)")}
            condition = " AND has_hwid = 1" if "has_hwid" in cols else ""
            count = conn.execute(
                "SELECT COUNT(*) FROM subscription_devices WHERE subject = ?" + condition, (subject,)
            ).fetchone()[0]
    return {"count": count, "max_devices": maximum, "reached": maximum > 0 and count >= maximum}
