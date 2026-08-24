import base64
import json
import logging
import os
import sqlite3
import time
from threading import Lock
from typing import Dict, List, Optional

from services.db_bootstrap import connect
from utils import parse_field_as_dict

logger = logging.getLogger("sub_manager")

CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
LINKS_CACHE_MAX_ENTRIES = int(os.getenv("SUBSCRIPTION_LINKS_CACHE_MAX_ENTRIES", "2048"))

_SNAPSHOT_DB_PATH: Optional[str] = None
_cache_lock = Lock()

emails_cache = {"ts": 0.0, "emails": [], "items": {}}
links_cache = {}
_inbounds_cache = {}


def configure_snapshot_db(db_path: str) -> None:
    global _SNAPSHOT_DB_PATH
    _SNAPSHOT_DB_PATH = db_path


def invalidate_subscription_cache() -> None:
    with _cache_lock:
        emails_cache["ts"] = 0.0
        emails_cache["emails"] = []
        emails_cache["items"] = {}
        links_cache.clear()
        _inbounds_cache.clear()


def _prune_links_cache(now: float) -> None:
    expired_keys = [
        key for key, (created_at, _) in links_cache.items()
        if now - created_at >= CACHE_TTL
    ]
    for key in expired_keys:
        links_cache.pop(key, None)

    overflow = len(links_cache) - LINKS_CACHE_MAX_ENTRIES + 1
    if overflow <= 0:
        return

    oldest_keys = sorted(links_cache, key=lambda key: links_cache[key][0])[:overflow]
    for key in oldest_keys:
        links_cache.pop(key, None)


def _node_cache_key(node: Dict) -> str:
    return "|".join(
        [
            str(_SNAPSHOT_DB_PATH or ""),
            str(node.get("id") or ""),
            str(node.get("name") or ""),
            str(node.get("ip") or ""),
            str(node.get("port") or ""),
            str(node.get("base_path") or ""),
        ]
    )


def _nodes_cache_key(nodes: List[Dict]) -> str:
    return ";".join(_node_cache_key(node) for node in nodes)


def _normalise_inbound_for_subscriptions(inbound: Dict, node: Dict) -> Dict:
    normalised = dict(inbound)
    normalised["streamSettings"] = parse_field_as_dict(
        inbound.get("streamSettings"),
        node_id=node.get("name"),
        field_name="streamSettings",
    )
    normalised["settings"] = parse_field_as_dict(
        inbound.get("settings"),
        node_id=node.get("name"),
        field_name="settings",
    )
    return normalised


def fetch_inbounds(node: Dict) -> List[Dict]:
    """Return subscription inbounds only from local persisted node snapshots."""
    cache_key = _node_cache_key(node)
    now = time.time()
    with _cache_lock:
        cached = _inbounds_cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]

    inbounds = _fetch_inbounds_from_snapshot(node)
    with _cache_lock:
        _inbounds_cache[cache_key] = (now, inbounds)
    return inbounds


def _fetch_inbounds_from_snapshot(node: Dict) -> List[Dict]:
    if not _SNAPSHOT_DB_PATH:
        return []

    row = None
    try:
        with connect(_SNAPSHOT_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            node_id = node.get("id")
            if node_id is not None:
                row = conn.execute(
                    "SELECT status_data FROM node_snapshots WHERE node_id = ?",
                    (node_id,),
                ).fetchone()
            if row is None and node.get("name"):
                row = conn.execute(
                    """
                    SELECT s.status_data
                    FROM node_snapshots s
                    INNER JOIN nodes n ON n.id = s.node_id
                    WHERE n.name = ?
                    """,
                    (node.get("name"),),
                ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("Failed to read node snapshot for %s: %s", node.get("name"), exc)
        return []

    if row is None:
        return []

    try:
        snapshot = json.loads(row["status_data"] or "{}")
    except Exception as exc:
        logger.warning("Invalid persisted node snapshot for %s: %s", node.get("name"), exc)
        return []

    if not isinstance(snapshot, dict):
        return []

    raw_inbounds = snapshot.get("inbounds")
    if not isinstance(raw_inbounds, list):
        inbounds_result = snapshot.get("inbounds_result")
        if isinstance(inbounds_result, dict):
            raw_inbounds = inbounds_result.get("inbounds")

    if not isinstance(raw_inbounds, list):
        return []

    return [
        _normalise_inbound_for_subscriptions(inbound, node)
        for inbound in raw_inbounds
        if isinstance(inbound, dict)
    ]


def get_emails(nodes: List[Dict]) -> List[str]:
    now = time.time()
    cache_key = _nodes_cache_key(nodes)
    with _cache_lock:
        cached = emails_cache.get("items", {}).get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]

    emails = set()
    for node in nodes:
        for inbound in fetch_inbounds(node):
            clients = parse_field_as_dict(
                inbound.get("settings"),
                node_id=node["name"],
                field_name="settings",
            ).get("clients", [])
            for client in clients:
                email = client.get("email")
                if email:
                    emails.add(email)

    emails_list = sorted(emails, key=lambda value: value.lower())
    with _cache_lock:
        emails_cache["ts"] = now
        emails_cache["emails"] = emails_list
        emails_cache.setdefault("items", {})[cache_key] = (now, emails_list)
    return emails_list


def get_links(nodes: List[Dict], email: str) -> List[str]:
    return get_links_filtered(nodes, email)


def _first_server_name(stream_settings: Dict) -> str:
    reality = stream_settings.get("realitySettings", {}) or {}
    reality_names = reality.get("serverNames") or []
    if reality_names:
        return reality_names[0]
    tls_settings = stream_settings.get("tlsSettings", {}) or {}
    tls_names = tls_settings.get("serverNames") or []
    if tls_names:
        return tls_names[0]
    return ""


def _fingerprint_from_stream_settings(stream_settings: Dict) -> str:
    reality = stream_settings.get("realitySettings", {}) or {}
    reality_settings = reality.get("settings") or {}
    tls_settings = (stream_settings.get("tlsSettings", {}) or {}).get("settings") or {}

    for value in (
        reality_settings.get("fingerprint"),
        reality.get("fingerprint"),
        tls_settings.get("fingerprint"),
    ):
        if value:
            return str(value)
    return "chrome"


def _subscription_port(inbound: Dict) -> str:
    """Return the public listener port from an inbound, with a legacy fallback."""
    raw_port = inbound.get("port")
    if isinstance(raw_port, bool):
        return "443"
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return "443"
    return str(port) if 1 <= port <= 65535 else "443"


def get_links_filtered(
    nodes: List[Dict],
    email: str,
    protocol_filter: Optional[str] = None,
) -> List[str]:
    cache_key = f"{email.lower()}|{protocol_filter or 'all'}|{_nodes_cache_key(nodes)}"
    now_link = time.time()
    with _cache_lock:
        cached = links_cache.get(cache_key)
        if cached and now_link - cached[0] < CACHE_TTL:
            return cached[1]

    links = []
    for node in nodes:
        for inbound in fetch_inbounds(node):
            protocol = inbound.get("protocol", "")
            if protocol_filter and protocol != protocol_filter:
                continue

            stream_settings = parse_field_as_dict(
                inbound.get("streamSettings"),
                node_id=node["name"],
                field_name="streamSettings",
            )
            security = stream_settings.get("security", "")
            if protocol not in ("vless", "vmess", "trojan"):
                continue
            if security not in ("reality", "tls"):
                continue

            settings = parse_field_as_dict(
                inbound.get("settings"),
                node_id=node["name"],
                field_name="settings",
            )
            reality = stream_settings.get("realitySettings", {}) or {}
            public_key = (reality.get("settings") or {}).get("publicKey", "")
            short_ids = reality.get("shortIds") or []
            short_id = short_ids[0] if short_ids else ""
            sni = _first_server_name(stream_settings)
            fingerprint = _fingerprint_from_stream_settings(stream_settings)
            network = stream_settings.get("network", "tcp")
            subscription_port = _subscription_port(inbound)

            for client in settings.get("clients", []):
                if client.get("email") != email:
                    continue

                if protocol == "vless":
                    flow = client.get("flow", "")
                    flow_param = f"&flow={flow}" if flow else ""
                    if security == "reality":
                        links.append(
                            f"vless://{client['id']}@{node['ip']}:{subscription_port}?encryption=none&security=reality"
                            f"&sni={sni}&fp={fingerprint}&pbk={public_key}&sid={short_id}"
                            f"{flow_param}&type={network}#{node['name']}"
                        )
                    else:
                        links.append(
                            f"vless://{client['id']}@{node['ip']}:{subscription_port}?encryption=none&security=tls"
                            f"&sni={sni}&fp={fingerprint}{flow_param}&type={network}#{node['name']}"
                        )
                    continue

                if protocol == "vmess":
                    link_obj = {
                        "v": "2",
                        "ps": f"{client['email']} ({node['name']})",
                        "add": node["ip"],
                        "port": subscription_port,
                        "id": client.get("id", ""),
                        "aid": "0",
                        "net": network,
                        "type": "none",
                        "tls": "" if security == "reality" else "tls",
                        "sni": sni,
                    }
                    if security == "reality":
                        link_obj.update(
                            {
                                "host": sni,
                                "pbk": public_key,
                                "sid": short_id,
                                "fp": fingerprint,
                            }
                        )
                    links.append(
                        "vmess://" + base64.b64encode(json.dumps(link_obj).encode()).decode()
                    )
                    continue

                if protocol == "trojan":
                    password = client.get("password", "")
                    if security == "reality":
                        links.append(
                            f"trojan://{password}@{node['ip']}:{subscription_port}?security=reality"
                            f"&sni={sni}&fp={fingerprint}&pbk={public_key}&sid={short_id}"
                            f"&type={network}#{node['name']}"
                        )
                    else:
                        links.append(
                            f"trojan://{password}@{node['ip']}:{subscription_port}?security=tls"
                            f"&sni={sni}&type={network}#{node['name']}"
                        )

    with _cache_lock:
        _prune_links_cache(now_link)
        links_cache[cache_key] = (now_link, links)
    return links
