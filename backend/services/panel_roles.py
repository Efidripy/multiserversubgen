from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, List, Optional

from services.db_bootstrap import connect


class PanelRoleStore:
    """Persistence access for panel RBAC roles."""

    def __init__(self, db_path: str, on_change: Optional[Callable[[], None]] = None) -> None:
        self.db_path = db_path
        self._on_change = on_change

    def set_on_change(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_change = callback

    def get_role(self, username: str) -> Optional[str]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT role FROM panel_user_roles WHERE username = ?", (username,)
            ).fetchone()
        return row[0] if row else None

    def is_blocked(self, username: str) -> bool:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT 1 FROM panel_user_blocks WHERE username = ?", (username,)).fetchone()
        return row is not None

    def list_roles(self) -> List[Dict[str, str]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT username, role, updated_by, updated_at "
                "FROM panel_user_roles ORDER BY username"
            ).fetchall()
        return [
            {
                "username": row[0],
                "role": row[1],
                "updated_by": row[2],
                "updated_at": row[3],
            }
            for row in rows
        ]

    def set_role(self, username: str, role: str, updated_by: str) -> Optional[str]:
        with connect(self.db_path) as conn:
            previous = conn.execute(
                "SELECT role FROM panel_user_roles WHERE username = ?", (username,)
            ).fetchone()
            conn.execute(
                "INSERT INTO panel_user_roles(username, role, updated_by, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(username) DO UPDATE SET role=excluded.role, "
                "updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP",
                (username, role, updated_by),
            )
            conn.execute("DELETE FROM panel_user_blocks WHERE username = ?", (username,))
        if self._on_change is not None:
            self._on_change()
        return previous[0] if previous else None

    def remove_user(self, username: str, blocked_by: str) -> bool:
        with connect(self.db_path) as conn:
            previous = conn.execute("SELECT 1 FROM panel_user_roles WHERE username = ?", (username,)).fetchone()
            conn.execute("DELETE FROM panel_user_roles WHERE username = ?", (username,))
            conn.execute(
                "INSERT INTO panel_user_blocks(username, blocked_by, blocked_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(username) DO UPDATE SET blocked_by=excluded.blocked_by, blocked_at=CURRENT_TIMESTAMP",
                (username, blocked_by),
            )
            conn.execute("DELETE FROM panel_user_notes WHERE username = ?", (username,))
        if self._on_change is not None:
            self._on_change()
        return previous is not None

    def get_note(self, username: str) -> str:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT note FROM panel_user_notes WHERE username = ?", (username,)).fetchone()
        return row[0] if row else ""

    def set_note(self, username: str, note: str, updated_by: str) -> bool:
        with connect(self.db_path) as conn:
            # Refuse in the same transaction so a late save cannot resurrect a deleted user's note.
            if conn.execute("SELECT 1 FROM panel_user_blocks WHERE username = ?", (username,)).fetchone():
                return False
            if note:
                conn.execute(
                    "INSERT INTO panel_user_notes(username, note, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(username) DO UPDATE SET note=excluded.note, updated_by=excluded.updated_by, updated_at=CURRENT_TIMESTAMP",
                    (username, note, updated_by),
                )
            else:
                conn.execute("DELETE FROM panel_user_notes WHERE username = ?", (username,))
        return True

    def delete_role(self, username: str) -> bool:
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM panel_user_roles WHERE username = ?", (username,)
            )
            removed = cursor.rowcount > 0
        if removed and self._on_change is not None:
            self._on_change()
        return removed


PanelRoles = PanelRoleStore

_configured_store: Optional[PanelRoleStore] = None


def configure(db_path: str, on_change: Optional[Callable[[], None]] = None) -> PanelRoleStore:
    global _configured_store
    _configured_store = PanelRoleStore(db_path, on_change=on_change)
    return _configured_store


def _store() -> PanelRoleStore:
    global _configured_store
    if _configured_store is None:
        project_dir = os.getenv("PROJECT_DIR", ".")
        _configured_store = PanelRoleStore(str(Path(project_dir) / "admin.db"))
    return _configured_store


def get_role(username: str) -> Optional[str]:
    return _store().get_role(username)


def list_roles() -> List[Dict[str, str]]:
    return _store().list_roles()


def set_role(username: str, role: str, updated_by: str) -> Optional[str]:
    return _store().set_role(username, role, updated_by)


def delete_role(username: str) -> bool:
    return _store().delete_role(username)


def is_blocked(username: str) -> bool:
    return _store().is_blocked(username)
