import base64
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests

from crypto import decrypt
from utils import parse_field_as_dict
from xui_session import XUI_FAST_RETRIES, XUI_FAST_TIMEOUT_SEC, login_panel, xui_request

logger = logging.getLogger("sub_manager")

CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
VERIFY_TLS = os.getenv("VERIFY_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
CA_BUNDLE_PATH = os.getenv("CA_BUNDLE_PATH", "").strip()

emails_cache = {"ts": 0.0, "emails": []}
links_cache = {}


def _requests_verify_value():
    if not VERIFY_TLS:
        return False
    if CA_BUNDLE_PATH:
        return CA_BUNDLE_PATH
    return True


def invalidate_subscription_cache() -> None:
    emails_cache["ts"] = 0.0
    emails_cache["emails"] = []
    links_cache.clear()


def fetch_inbounds(node: Dict) -> List[Dict]:
    session = requests.Session()
    session.verify = _requests_verify_value()
    base_path = node.get("base_path", "").strip("/")
    prefix = f"/{base_path}" if base_path else ""
    base_url = f"https://{node['ip']}:{node['port']}{prefix}"

    try:
        if not login_panel(
            session,
            base_url,
            node["user"],
            decrypt(node.get("password", "")),
            timeout=XUI_FAST_TIMEOUT_SEC,
            retries=XUI_FAST_RETRIES,
        ):
            logger.warning("node panel login failed for node %s", node["name"])
            return []

        response = xui_request(
            session,
            "GET",
            f"{base_url}/panel/api/inbounds/list",
            timeout=XUI_FAST_TIMEOUT_SEC,
            retries=XUI_FAST_RETRIES,
        )
        if response.status_code != 200:
            logger.warning(
                "node panel %s inbounds list returned status %s; response (first 200 chars): %r",
                node["name"],
                response.status_code,
                response.text[:200],
            )
            return []
        data = response.json()
        return data.get("obj", []) if data.get("success", False) else []
    except Exception as exc:
        logger.warning("Failed to fetch inbounds from %s: %s", node["name"], exc)
        return []


def get_emails(nodes: List[Dict]) -> List[str]:
    now = time.time()
    if now - emails_cache["ts"] < CACHE_TTL:
        return emails_cache["emails"]

    def _collect_node_emails(node: Dict) -> set:
        node_emails = set()
        for inbound in fetch_inbounds(node):
            clients = parse_field_as_dict(
                inbound.get("settings"),
                node_id=node["name"],
                field_name="settings",
            ).get("clients", [])
            for client in clients:
                email = client.get("email")
                if email:
                    node_emails.add(email)
        return node_emails

    emails = set()
    if nodes:
        workers = min(8, len(nodes))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_collect_node_emails, node) for node in nodes]
            for future in as_completed(futures):
                try:
                    emails.update(future.result())
                except Exception as exc:
                    logger.warning("Failed to collect emails: %s", exc)

    emails_list = sorted(emails, key=lambda value: value.lower())
    emails_cache.update({"ts": now, "emails": emails_list})
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


def get_links_filtered(
    nodes: List[Dict],
    email: str,
    protocol_filter: Optional[str] = None,
) -> List[str]:
    cache_key = f"{email}_{protocol_filter or 'all'}_{','.join([node['name'] for node in nodes])}"
    now_link = time.time()
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
            fingerprint = reality.get("fingerprint", "chrome")
            network = stream_settings.get("network", "tcp")

            for client in settings.get("clients", []):
                if client.get("email") != email:
                    continue

                if protocol == "vless":
                    flow = client.get("flow", "")
                    flow_param = f"&flow={flow}" if flow else ""
                    if security == "reality":
                        links.append(
                            f"vless://{client['id']}@{node['ip']}:443?encryption=none&security=reality"
                            f"&sni={sni}&fp={fingerprint}&pbk={public_key}&sid={short_id}"
                            f"{flow_param}&type={network}#{node['name']}"
                        )
                    else:
                        links.append(
                            f"vless://{client['id']}@{node['ip']}:443?encryption=none&security=tls"
                            f"&sni={sni}&fp={fingerprint}{flow_param}&type={network}#{node['name']}"
                        )
                    continue

                if protocol == "vmess":
                    link_obj = {
                        "v": "2",
                        "ps": f"{client['email']} ({node['name']})",
                        "add": node["ip"],
                        "port": "443",
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
                            f"trojan://{password}@{node['ip']}:443?security=reality"
                            f"&sni={sni}&fp={fingerprint}&pbk={public_key}&sid={short_id}"
                            f"&type={network}#{node['name']}"
                        )
                    else:
                        links.append(
                            f"trojan://{password}@{node['ip']}:443?security=tls"
                            f"&sni={sni}&type={network}#{node['name']}"
                        )

    links_cache[cache_key] = (now_link, links)
    links_cache[email] = (now_link, links)
    return links
