import sqlite3
from typing import Dict, List, Optional


class NodeService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def list_nodes(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(n) for n in conn.execute("SELECT * FROM nodes").fetchall()]

    def list_nodes_simple(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [{"id": n["id"], "name": n["name"]} for n in conn.execute("SELECT id, name FROM nodes").fetchall()]

    def get_node(self, node_id: int) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            return dict(row) if row else None
