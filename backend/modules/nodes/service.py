"""Node management service – CRUD operations backed by SQLite."""

from __future__ import annotations

import logging
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class NodesService:
    """CRUD service for VPN nodes stored in SQLite.

    Args:
        db_path: Absolute path to the SQLite database file.
        encrypt_func: Callable used to encrypt passwords before storage.
        decrypt_func: Callable used to decrypt passwords after retrieval.
    """

    def __init__(
        self,
        db_path: str,
        *,
        encrypt_func=None,
        decrypt_func=None,
    ) -> None:
        self._db_path = db_path
        self._encrypt = encrypt_func or (lambda x: x)
        self._decrypt = decrypt_func or (lambda x: x)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_nodes(self, *, include_password: bool = False) -> List[Dict]:
        """Return all nodes from the database.

        Args:
            include_password: When ``True`` the returned dicts include the
                decrypted password.

        Returns:
            List of node dicts.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        nodes = []
        for row in rows:
            node = dict(row)
            if not include_password:
                node.pop("password", None)
            else:
                try:
                    node["password"] = self._decrypt(node["password"])
                except Exception:
                    pass
            nodes.append(node)
        return nodes

    def get_node(self, node_id: int, *, include_password: bool = False) -> Optional[Dict]:
        """Return a single node by *node_id*, or ``None``."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
        if row is None:
            return None
        node = dict(row)
        if not include_password:
            node.pop("password", None)
        else:
            try:
                node["password"] = self._decrypt(node["password"])
            except Exception:
                pass
        return node

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_node(self, data: Dict) -> Dict:
        """Insert a new node and return it with its assigned ``id``.

        The password is encrypted before storage.
        """
        encrypted_password = self._encrypt(data["password"])
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO nodes (name, ip, port, user, password, base_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"],
                    data["ip"],
                    data["port"],
                    data["user"],
                    encrypted_password,
                    data.get("base_path", ""),
                ),
            )
            if data.get("read_only") is not None:
                conn.execute(
                    "UPDATE nodes SET read_only = ? WHERE id = ?",
                    (1 if bool(data.get("read_only")) else 0, cur.lastrowid),
                )
            conn.commit()
            node_id = cur.lastrowid
        return self.get_node(node_id) or {"id": node_id, **data}

    def update_node(self, node_id: int, updates: Dict) -> Optional[Dict]:
        """Update fields of an existing node.

        Returns the updated node dict, or ``None`` if the node doesn't exist.
        """
        if not self.get_node(node_id):
            return None

        fields = []
        params = []
        if "name" in updates:
            fields.append("name = ?")
            params.append(updates["name"])
        if "ip" in updates:
            fields.append("ip = ?")
            params.append(updates["ip"])
        if "port" in updates:
            fields.append("port = ?")
            params.append(updates["port"])
        if "user" in updates:
            fields.append("user = ?")
            params.append(updates["user"])
        if "password" in updates:
            fields.append("password = ?")
            params.append(self._encrypt(updates["password"]))
        if "base_path" in updates:
            fields.append("base_path = ?")
            params.append(updates["base_path"])
        if "read_only" in updates:
            fields.append("read_only = ?")
            params.append(1 if bool(updates["read_only"]) else 0)

        if not fields:
            return self.get_node(node_id)

        params.append(node_id)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                f"UPDATE nodes SET {', '.join(fields)} WHERE id = ?", params
            )
            conn.commit()
        return self.get_node(node_id)

    def delete_node(self, node_id: int) -> bool:
        """Delete a node by *node_id*.

        Returns ``True`` if the node existed and was deleted.
        """
        with sqlite3.connect(self._db_path) as conn:
            cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            conn.commit()
        return cur.rowcount > 0
