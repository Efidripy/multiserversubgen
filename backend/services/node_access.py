from __future__ import annotations

from fastapi import HTTPException


def get_node_or_404(node_service, node_id: int):
    node = node_service.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node
