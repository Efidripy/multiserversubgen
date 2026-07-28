import json
import sqlite3
from typing import Dict, List, Optional
from urllib.parse import urlparse

from services.db_bootstrap import connect


class NodeService:
    """Node access adapter with a canonical runtime schema.

    Storage may come from different eras of the project:
    - legacy/runtime keys: ``ip``, ``port``, ``user``, ``password``, ``base_path``
    - admin-panel keys: ``panel_url``, ``username``, ``access_path``, ``verify_tls``

    Everything returned by this service must be normalized to the runtime shape so
    all backend layers speak one node language regardless of DB column names.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    @staticmethod
    def _normalize_node(node: Dict) -> Dict:
        if not node.get("user") and node.get("username"):
            node["user"] = node["username"]
        if not node.get("base_path") and node.get("access_path"):
            node["base_path"] = str(node["access_path"]).strip("/")

        panel_url = str(node.get("panel_url") or "").strip()
        parsed = urlparse(panel_url) if panel_url else None
        if parsed:
            if parsed.scheme and not node.get("scheme"):
                node["scheme"] = parsed.scheme
            if not node.get("ip") and parsed.hostname:
                node["ip"] = parsed.hostname
            if not node.get("port"):
                node["port"] = str(parsed.port or 443)
            if not node.get("base_path") and parsed.path:
                node["base_path"] = parsed.path.strip("/")
        else:
            if not node.get("port"):
                node["port"] = "443"
        if not node.get("scheme"):
            node["scheme"] = "https"
        return node

    def list_nodes(self) -> List[Dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                self._normalize_node(dict(n))
                for n in conn.execute(
                    "SELECT * FROM nodes ORDER BY name COLLATE NOCASE ASC, id ASC"
                ).fetchall()
            ]

    def list_nodes_simple(self) -> List[Dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                {"id": n["id"], "name": n["name"]}
                for n in conn.execute(
                    "SELECT id, name FROM nodes ORDER BY name COLLATE NOCASE ASC, id ASC"
                ).fetchall()
            ]

    def get_node(self, node_id: int) -> Optional[Dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return self._normalize_node(dict(row)) if row else None

    def update_node(self, node_id: int, updates: Dict) -> Optional[Dict]:
        allowed = {"api_version", "panel_version", "name", "ip", "port", "user",
                   "password", "base_path", "read_only", "enabled", "tags"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return self.get_node(node_id)
        if "tags" in fields:
            fields["tags"] = self._serialize_tags(fields["tags"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        params = list(fields.values()) + [node_id]
        with connect(self.db_path) as conn:
            conn.execute(f"UPDATE nodes SET {set_clause} WHERE id = ?", params)
        return self.get_node(node_id)

    @staticmethod
    def _serialize_tags(value) -> str:
        if value is None or value == "":
            return "[]"
        if isinstance(value, list):
            return json.dumps([str(tag).strip() for tag in value if str(tag).strip()], ensure_ascii=False)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return "[]"
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return json.dumps([str(tag).strip() for tag in parsed if str(tag).strip()], ensure_ascii=False)
            except json.JSONDecodeError:
                pass
            return json.dumps([tag.strip() for tag in stripped.split(",") if tag.strip()], ensure_ascii=False)
        return "[]"
