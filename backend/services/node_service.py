import sqlite3
from typing import Dict, List, Optional
from urllib.parse import urlparse


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
            if not node.get("ip") and parsed.hostname:
                node["ip"] = parsed.hostname
            if not node.get("port"):
                node["port"] = str(parsed.port or (443 if parsed.scheme == "https" else 80))
            if not node.get("base_path") and parsed.path:
                node["base_path"] = parsed.path.strip("/")
        else:
            if not node.get("port"):
                node["port"] = "443"
        return node

    def list_nodes(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                self._normalize_node(dict(n))
                for n in conn.execute(
                    "SELECT * FROM nodes ORDER BY name COLLATE NOCASE ASC, id ASC"
                ).fetchall()
            ]

    def list_nodes_simple(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [
                {"id": n["id"], "name": n["name"]}
                for n in conn.execute(
                    "SELECT id, name FROM nodes ORDER BY name COLLATE NOCASE ASC, id ASC"
                ).fetchall()
            ]

    def get_node(self, node_id: int) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return self._normalize_node(dict(row)) if row else None
