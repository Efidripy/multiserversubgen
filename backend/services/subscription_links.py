import base64
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set

import requests

from crypto import decrypt
from utils import parse_field_as_dict
from xui_session import (
    XUI_FAST_RETRIES, XUI_FAST_TIMEOUT_SEC,
    extract_node_auth, get_authenticated_session, make_node_key, xui_request,
    get_node_api_version, set_node_api_version,
)

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
    base_path = node.get("base_path", "").strip("/")
    prefix = f"/{base_path}" if base_path else ""
    scheme = node.get("scheme", "https")
    base_url = f"{scheme}://{node['ip']}:{node['port']}{prefix}"

    try:
        username, password, bearer_token = extract_node_auth(node, decrypt)
        auth = get_authenticated_session(
            node_key=make_node_key(node.get("ip"), node.get("port"), node.get("base_path", "")),
            base_url=base_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
            verify_value=_requests_verify_value(),
            timeout=XUI_FAST_TIMEOUT_SEC,
            retries=XUI_FAST_RETRIES,
        )
        if not auth.get("ok"):
            logger.warning("node panel login failed for node %s", node["name"])
            return []

        response = xui_request(
            auth["session"],
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


def _fetch_emails_v3(node: Dict) -> Optional[set]:
    """Попробовать получить emails через v3 /clients/list (быстрее — без парсинга inbound JSON)."""
    base_path = node.get("base_path", "").strip("/")
    prefix = f"/{base_path}" if base_path else ""
    base_url = f"{node.get('scheme', 'https')}://{node.get('ip', '')}:{node.get('port', '')}{prefix}"

    try:
        username, password, bearer_token = extract_node_auth(node, decrypt)
        auth = get_authenticated_session(
            node_key=make_node_key(node.get("ip"), node.get("port"), node.get("base_path", "")),
            base_url=base_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
            verify_value=_requests_verify_value(),
            timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES,
        )
        if not auth.get("ok"):
            return None

        res = xui_request(auth["session"], "GET", f"{base_url}/panel/api/clients/list",
                          timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES)
        if res.status_code == 404:
            set_node_api_version(base_url, "v2")
            return None  # v2 нода
        if res.status_code != 200:
            return None
        data = res.json()
        if not data.get("success"):
            return None
        set_node_api_version(base_url, "v3")
        return {c["email"] for c in (data.get("obj") or []) if c.get("email")}
    except Exception as exc:
        logger.warning("v3 email fetch failed for %s: %s", node.get("name"), exc)
        return None


def get_emails(nodes: List[Dict]) -> List[str]:
    now = time.time()
    if now - emails_cache["ts"] < CACHE_TTL:
        return emails_cache["emails"]

    def _collect_node_emails(node: Dict) -> set:
        node_emails = set()

        # Пробуем v3 если нода его поддерживает
        base_path = node.get("base_path", "").strip("/")
        prefix = f"/{base_path}" if base_path else ""
        base_url = f"{node.get('scheme', 'https')}://{node.get('ip', '')}:{node.get('port', '')}{prefix}"
        if get_node_api_version(base_url) != "v2":
            v3_emails = _fetch_emails_v3(node)
            if v3_emails is not None:
                return v3_emails

        # v2 fallback: извлекаем email из inbounds
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


def _fetch_links_v3(node: Dict, email: str) -> Optional[List[str]]:
    """Получить subscription links через v3 API /clients/links/{email}.
    Возвращает список URL или None если v2 нода.
    """
    base_path = node.get("base_path", "").strip("/")
    prefix = f"/{base_path}" if base_path else ""
    base_url = f"{node.get('scheme', 'https')}://{node.get('ip', '')}:{node.get('port', '')}{prefix}"

    try:
        username, password, bearer_token = extract_node_auth(node, decrypt)
        auth = get_authenticated_session(
            node_key=make_node_key(node.get("ip"), node.get("port"), node.get("base_path", "")),
            base_url=base_url,
            username=username,
            password=password,
            bearer_token=bearer_token,
            verify_value=_requests_verify_value(),
            timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES,
        )
        if not auth.get("ok"):
            return None
        res = xui_request(auth["session"], "GET",
                          f"{base_url}/panel/api/clients/links/{email}",
                          timeout=XUI_FAST_TIMEOUT_SEC, retries=XUI_FAST_RETRIES)
        if res.status_code == 404:
            set_node_api_version(base_url, "v2")
            return None
        if res.status_code == 200:
            data = res.json()
            if data.get("success"):
                set_node_api_version(base_url, "v3")
                return data.get("obj") or []
    except Exception as exc:
        logger.debug("v3 links fetch failed for %s/%s: %s", node.get("name"), email, exc)
    return None


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
        # v3: панель сама генерирует ссылки (только если нет фильтра по протоколу)
        base_path = node.get("base_path", "").strip("/")
        prefix = f"/{base_path}" if base_path else ""
        base_url = f"{node.get('scheme', 'https')}://{node.get('ip', '')}:{node.get('port', '')}{prefix}"
        if not protocol_filter and get_node_api_version(base_url) != "v2":
            v3_links = _fetch_links_v3(node, email)
            if v3_links is not None:
                links.extend(v3_links)
                continue
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
