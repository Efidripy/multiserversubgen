from __future__ import annotations

from typing import Dict

from fastapi import HTTPException


def get_node_or_404(node_service, node_id: int):
    node = node_service.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


def snapshot_by_node(snapshot) -> tuple[Dict[str, Dict], Dict[str, Dict], Dict]:
    """Index a collector snapshot's node rows by node id and by name."""
    snapshot_nodes = snapshot.get("nodes") if isinstance(snapshot, dict) else []
    by_id: Dict[str, Dict] = {}
    by_name: Dict[str, Dict] = {}
    if isinstance(snapshot_nodes, list):
        for item in snapshot_nodes:
            if not isinstance(item, dict):
                continue
            node_id = item.get("node_id")
            name = item.get("name") or item.get("node")
            if node_id is not None:
                by_id[str(node_id)] = item
            if name:
                by_name[str(name)] = item
    return by_id, by_name, snapshot


def snapshot_for_node(node: Dict, by_id: Dict[str, Dict], by_name: Dict[str, Dict]) -> Dict | None:
    node_id = node.get("id")
    if node_id is not None and str(node_id) in by_id:
        return by_id[str(node_id)]
    name = node.get("name")
    if name and str(name) in by_name:
        return by_name[str(name)]
    return None
