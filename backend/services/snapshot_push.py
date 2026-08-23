from __future__ import annotations

from typing import Any, Dict, List

from services.system_clients import is_system_client
from utils import parse_field_as_dict


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


_SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "api_token", "bearer_token",
    "authorization", "cookie", "ws_ticket", "private_key", "client_secret",
}


def _redact_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_snapshot(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_redact_snapshot(item) for item in value]
    return value


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _traffic_by_email(inbound: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for item in _as_list(inbound.get("clientStats")):
        if not isinstance(item, dict):
            continue
        email = str(item.get("email") or "").strip()
        if email:
            stats[email] = item
    return stats


def flatten_snapshot_tables(snapshot: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Build REST-shaped table rows from one collector node snapshot."""

    node_name = str(snapshot.get("name") or snapshot.get("node") or "")
    node_id = snapshot.get("node_id")
    node_ip = str(snapshot.get("node_ip") or node_name)

    inbounds: List[Dict[str, Any]] = []
    clients: List[Dict[str, Any]] = []

    for inbound in _as_list(snapshot.get("inbounds")):
        if not isinstance(inbound, dict):
            continue

        stream_settings = parse_field_as_dict(
            inbound.get("streamSettings"),
            node_id=node_id or node_name,
            field_name="streamSettings",
        )
        settings = parse_field_as_dict(
            inbound.get("settings"),
            node_id=node_id or node_name,
            field_name="settings",
        )
        inbound_clients = [c for c in _as_list(settings.get("clients")) if isinstance(c, dict)]
        security = inbound.get("security") or stream_settings.get("security") or ""
        inbound_id = inbound.get("id")
        protocol = inbound.get("protocol")
        remark = inbound.get("remark", "")

        inbounds.append(
            {
                **inbound,
                "id": inbound_id,
                "node_id": node_id,
                "node_name": node_name,
                "node_ip": node_ip,
                "protocol": protocol,
                "port": inbound.get("port"),
                "remark": remark,
                "enable": inbound.get("enable", True),
                "client_count": len(inbound_clients),
                "streamSettings": stream_settings,
                "settings": settings,
                "security": security,
                "is_reality": security == "reality",
            }
        )

        client_stats = _traffic_by_email(inbound)
        for client in inbound_clients:
            email = str(client.get("email") or "").strip()
            if not email:
                continue
            traffic = client_stats.get(email, {})
            up = _to_int(traffic.get("up", client.get("up", 0)))
            down = _to_int(traffic.get("down", client.get("down", 0)))
            total = _to_int(client.get("total", traffic.get("total", client.get("totalGB", 0))))
            clients.append(
                {
                    "id": client.get("id") or client.get("uuid"),
                    "email": email,
                    "enable": client.get("enable", True),
                    "expiryTime": _to_int(client.get("expiryTime", 0)),
                    "total": total,
                    # Inbound client config still names its quota ``total``.
                    # Do not fall back to `clientStats.total`: that field is
                    # consumption telemetry, while a missing config quota is
                    # the explicit unlimited value (0).
                    "totalGB": _to_int(client.get("totalGB", client.get("total", 0))),
                    "up": up,
                    "down": down,
                    "flow": client.get("flow", ""),
                    "comment": client.get("comment", ""),
                    "is_system": is_system_client(client),
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_ip": node_ip,
                    "inbound_id": inbound_id,
                    "inbound_remark": remark,
                    "protocol": protocol,
                    "password": "",
                    "security": security,
                    "network": stream_settings.get("network", ""),
                }
            )

    return {"clients": clients, "inbounds": inbounds}


def build_snapshot_push_payload(
    *,
    key: str,
    snapshot: Dict[str, Any],
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    table_payload = flatten_snapshot_tables(snapshot) if snapshot.get("available") else {"clients": [], "inbounds": []}
    return {
        "source": "snapshot_collector",
        "action": "snapshot",
        "node": key,
        "node_id": snapshot.get("node_id"),
        "available": bool(snapshot.get("available")),
        "snapshot": _redact_snapshot(snapshot),
        "changes": _redact_snapshot(changes),
        "clients": table_payload["clients"],
        "inbounds": table_payload["inbounds"],
        "has_table_payload": bool(snapshot.get("available")),
    }
