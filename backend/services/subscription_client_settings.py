from __future__ import annotations

import base64
import copy
import json
import re
import sqlite3
from typing import Any, Dict, Optional

from services.db_bootstrap import connect


from services.subscription_formats import FORMATS
from services.subscription_regex import validate_admin_regex
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.0-9A-Za-z^_`|~]+$")
_FORBIDDEN_HEADERS = {
    "content-type", "content-length", "content-encoding", "transfer-encoding", "connection",
    "keep-alive", "upgrade", "te", "trailer", "set-cookie", "location", "cache-control",
    "pragma", "expires", "vary", "subscription-userinfo", "x-subscription-cache",
    "strict-transport-security", "content-security-policy",
}

DEFAULT_CLIENTS = [
    {"id": "happ", "name": "Happ", "kind": "happ", "builtin": True, "enabled": False, "user_agent_regex": r"\bhapp\b", "format": "base64", "settings": {}, "headers": []},
    {"id": "incy", "name": "Incy", "kind": "incy", "builtin": True, "enabled": False, "user_agent_regex": r"\bincy\b", "format": "base64", "settings": {}, "headers": []},
    {"id": "mihomo", "name": "Mihomo", "kind": "mihomo", "builtin": True, "enabled": False, "user_agent_regex": r"^(?:flclash|rabbit|flowvy|murge|mihomo|prizrak-box|koala-clash|clash(?:-verge|-nyanpasu|x meta|[-.]?meta))", "format": "mihomo", "settings": {}, "headers": []},
    {"id": "stash", "name": "Stash", "kind": "mihomo", "builtin": True, "enabled": False, "user_agent_regex": r"^stash", "format": "mihomo", "settings": {}, "headers": []},
    {"id": "singbox", "name": "sing-box", "kind": "generic", "builtin": True, "enabled": False, "user_agent_regex": r"^(?:sfa|sfi|sfm|sft|karing|sing-?box)", "format": "singbox", "settings": {}, "headers": []},
    {"id": "clash", "name": "Clash", "kind": "mihomo", "builtin": True, "enabled": False, "user_agent_regex": r"^clash", "format": "clash", "settings": {}, "headers": []},
]

FIELD_SPECS = {
    "happ": [
        ("routing_enable", "Routing-Enable", "bool", "routing", None), ("routing", "Routing", "text", "routing", None), ("routing_url", None, "url", "routing", None),
        ("no_limit", "No-Limit-Enabled", "bool", "routing", None), ("hide_settings", "Hide-Settings", "bool", "routing", None),
        ("color_profile", "Color-Profile", "text", "appearance", None), ("sub_info_text", "Sub-Info-Text", "text", "appearance", None),
        ("sub_info_color", "Sub-Info-Color", "enum", "appearance", ["blue", "green", "red"]), ("sub_info_button_text", "Sub-Info-Button-Text", "text", "appearance", None),
        ("sub_info_button_link", "Sub-Info-Button-Link", "url", "appearance", None), ("sub_expire", "Sub-Expire", "bool", "appearance", None),
        ("sub_expire_button_link", "Sub-Expire-Button-Link", "url", "appearance", None), ("notification_expire", "Notification-Subs-Expire", "bool", "appearance", None),
        ("tun_mode", "Tun-Mode", "enum", "network", ["system", "gvisor"]), ("tun_type", "Tun-Type", "enum", "network", ["singbox", "tun2proxy", "default", "xray"]),
        ("exclude_routes", "Exclude-Routes", "text", "network", None), ("exclude_apns", "Exclude-Apns-Enable", "bool", "network", None),
        ("ping_type", "Ping-Type", "enum", "network", ["proxy", "proxy-head", "tcp", "icmp"]), ("autoconnect", "Subscription-Autoconnect", "bool", "network", None),
        ("autoconnect_type", "Subscription-Autoconnect-Type", "enum", "network", ["lowestdelay", "lastused", "random"]), ("per_app_mode", "Per-App-Proxy-Mode", "enum", "network", ["on", "bypass"]),
        ("per_app_list", "Per-App-Proxy-List", "text", "network", None), ("local_proxy_auth", "Socks-Auth-Mode", "enum", "network", ["auto", "disable"]),
        ("provider_id", "ProviderID", "text", "management", None), ("new_url", "New-Url", "url", "management", None), ("fallback_url", "Fallback-Url", "url", "management", None),
    ],
    "incy": [
        ("profile_description", "Profile-Description", "text", "app", None), ("sort_order", "Sort-Order", "enum", "app", ["none", "ping", "name"]), ("support_email", "Support-Email", "text", "app", None), ("announce_url", "Announce-Url", "url", "app", None), ("premium_url", "Premium-Url", "url", "app", None),
        ("banner_text", "Banner-Text", "text", "banners", None), ("banner_button_text", "Banner-Button-Text", "text", "banners", None), ("banner_button_url", "Banner-Button-Url", "url", "banners", None), ("banner_bg_color", "Banner-Bg-Color", "text", "banners", None), ("banner_button_color", "Banner-Button-Color", "text", "banners", None),
        ("hide_url", "Hide-Url", "tristate", "privacy", None), ("hide_check", "Hide-Check", "tristate", "privacy", None), ("no_limit_enabled", "No-Limit-Enabled", "tristate", "privacy", None), ("per_app_proxy_enable", "Per-App-Proxy-Enable", "tristate", "privacy", None), ("per_app_proxy_mode", "Per-App-Proxy-Mode", "enum", "privacy", ["bypass", "proxy"]), ("per_app_proxy_list", "Per-App-Proxy-List", "text", "privacy", None),
        ("fragmentation_enable", "Fragmentation-Enable", "tristate", "network", None), ("fragmentation_length", "Fragmentation-Length", "text", "network", None), ("fragmentation_interval", "Fragmentation-Interval", "text", "network", None), ("fragmentation_packets", "Fragmentation-Packets", "text", "network", None), ("noises_enable", "Noises-Enable", "tristate", "network", None), ("noises_type", "Noises-Type", "enum", "network", ["rand", "str", "hex"]), ("noises_packet", "Noises-Packet", "text", "network", None), ("noises_delay", "Noises-Delay", "text", "network", None), ("server_address_resolve_enable", "Server-Address-Resolve-Enable", "tristate", "network", None), ("server_address_resolve_dns_domain", "Server-Address-Resolve-Dns-Domain", "text", "network", None), ("server_address_resolve_dns_ip", "Server-Address-Resolve-Dns-Ip", "text", "network", None),
        ("routing_enable", None, "bool", "routing", None), ("routing", None, "text", "routing", None), ("routing_url", None, "url", "routing", None),
    ],
    "mihomo": [("enable_routing", None, "bool", "routing", None), ("rules", None, "lines", "routing", None), ("rules_url", None, "url", "routing", None)],
}


# Panel-wide sections, one per feature. (key, type, group, options, default)
SECTION_SPECS = {
    "content": [
        ("encode", "bool", "body", None, True),
        ("remark_template", "text", "body", None, ""),
        ("show_identity_on_all_links", "bool", "body", None, False),
        ("info_node", "bool", "body", None, False),
        ("expired_template", "text", "status", None, ""),
        ("depleted_template", "text", "status", None, ""),
        ("host_order", "enum", "body", ["name", "random"], ""),
    ],
    "remote_rules": [
        ("refresh_minutes", "number", "fetch", None, 60),
        ("user_agent", "text", "fetch", None, ""),
        ("use_remote_dns", "bool", "fetch", None, False),
    ],
    "xray_json": [
        ("always_array", "bool", "format", None, False),
        ("mux", "json", "format", None, ""),
        ("dns", "json", "format", None, ""),
        ("routing", "json", "format", None, ""),
        ("rules", "json", "format", None, ""),
        ("final_mask", "json", "format", None, ""),
        ("observatory", "json", "format", None, ""),
        ("balancers", "json", "format", None, ""),
    ],
    "response_rules": [
        ("rules", "json", "rules", None, ""),
    ],
    "page": [
        ("enabled", "bool", "page", None, False),
        ("brand_title", "text", "page", None, ""),
        ("theme", "enum", "page", ["remnawave", "3xui"], "remnawave"),
        ("profile_mode", "enum", "page", ["builtin", "custom"], ""),
        ("profile_url", "url", "page", None, ""),
    ],
    "devices": [
        ("enabled", "bool", "limit", None, False),
        ("max_devices", "number", "limit", None, 0),
        ("block_unsupported", "bool", "limit", None, False),
        ("limit_announce", "text", "limit", None, ""),
    ],
    "encryption": [
        ("happ_links", "bool", "links", None, False),
    ],
}


def ensure_subscription_client_settings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS subscription_client_settings (id INTEGER PRIMARY KEY CHECK (id = 1), settings_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )


def default_settings() -> Dict[str, Any]:
    return {
        "profile": {
            "title": "",
            "support_url": "",
            "web_page_url": "",
            "announce": "",
            "update_interval_hours": None,
        },
        "clients": [copy.deepcopy(client) for client in DEFAULT_CLIENTS],
        **{
            section: {key: default for key, _type, _group, _options, default in specs}
            for section, specs in SECTION_SPECS.items()
        },
    }


def _clean_header_value(value: Any) -> str:
    cleaned = str(value or "").replace("\r", "").replace("\n", "").strip()
    if not cleaned:
        return ""
    if cleaned.isascii():
        return cleaned
    return "base64:" + base64.b64encode(cleaned.encode()).decode()


def _validate_url(value: str) -> bool:
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return not value
    return bool(re.fullmatch(r"(?:https?://|tg://)[^\s]+", value, re.IGNORECASE))


# PROXY is the only proxy group the generated config has; the rest are built into Mihomo.
MIHOMO_RULE_TARGETS = ("PROXY", "DIRECT", "REJECT", "REJECT-DROP", "PASS")


def _split_rule(rule: str) -> list[str]:
    """Split on top-level commas: AND,((DOMAIN,a),(NETWORK,UDP)),DIRECT has three parts."""
    parts, current, depth = [], "", 0
    for char in rule:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return [*parts, current.strip()]


def _validate_rule_lines(value: Any) -> str:
    if isinstance(value, str):
        lines = value.splitlines()
    elif isinstance(value, list):
        if any(not isinstance(line, str) for line in value):
            raise ValueError("rules")
        lines = value
    else:
        raise ValueError("rules")
    if len(lines) > 500:
        raise ValueError("rules: more than 500 lines")
    result = []
    for number, line in enumerate(lines, 1):
        if len(line) > 512:
            raise ValueError(f"rules: line {number}: longer than 512 characters")
        stripped = line.strip()
        # Rules are often pasted from a YAML config: "rules:" and "- 'DOMAIN,a,DIRECT'".
        if stripped == "rules:":
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
            if len(stripped) > 1 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
                stripped = stripped[1:-1].strip()
        if not stripped or stripped.startswith("#"):
            result.append(line)
            continue
        parts = _split_rule(stripped)
        if not re.fullmatch(r"[A-Z][A-Z0-9-]*", parts[0]):
            raise ValueError(f"rules: line {number}: expected TYPE,VALUE,TARGET: {stripped}")
        target = parts[1] if parts[0] == "MATCH" and len(parts) > 1 else (parts[2] if len(parts) > 2 else "")
        if target not in MIHOMO_RULE_TARGETS:
            allowed = ", ".join(MIHOMO_RULE_TARGETS)
            raise ValueError(f'rules: line {number}: target "{target}" is not one of {allowed}: {stripped}')
        result.append(stripped)
    return "\n".join(result)


def _validate_field(kind: str, key: str, value: Any, spec: tuple) -> Any:
    _name, _header, field_type, _group, options = spec
    if field_type == "bool" and not isinstance(value, bool):
        raise ValueError(key)
    if field_type in {"text", "url", "enum", "tristate"} and not isinstance(value, str):
        raise ValueError(key)
    if field_type == "lines":
        return _validate_rule_lines(value)
    if field_type == "tristate" and value not in {"", "on", "off"}:
        raise ValueError(key)
    if field_type == "url" and not _validate_url(value):
        raise ValueError(key)
    if field_type == "enum" and options and value not in options and value != "":
        raise ValueError(key)
    if key == "routing" and value and kind == "happ" and not value.startswith("happ://"):
        raise ValueError(key)
    if key in {"banner_bg_color", "banner_button_color"} and value and not re.fullmatch(r"#[0-9a-fA-F]{3,8}", value):
        raise ValueError(key)
    if key in {"fragmentation_length", "fragmentation_interval", "noises_delay"} and value and not re.fullmatch(r"\d+(?:-\d+)?", value):
        raise ValueError(key)
    if key == "fragmentation_packets" and value and value not in {"tlshello", "all", "1"} and not re.fullmatch(r"\d+-\d+", value):
        raise ValueError(key)
    return value


def _validate_profile(raw: Any, result: Dict[str, Any]) -> None:
    if not isinstance(raw, dict):
        raise ValueError("profile")
    for key in result["profile"]:
        if key not in raw:
            continue
        value = raw[key]
        if key == "update_interval_hours":
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 8760):
                raise ValueError(key)
        elif not isinstance(value, str):
            raise ValueError(key)
        if key in {"support_url", "web_page_url"} and not _validate_url(value):
            raise ValueError(key)
        result["profile"][key] = value


def _validate_section_value(key: str, value: Any, field_type: str, options: Any) -> Any:
    if field_type == "bool":
        if not isinstance(value, bool):
            raise ValueError(key)
    elif field_type == "number":
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000000:
            raise ValueError(key)
    elif not isinstance(value, str):
        raise ValueError(key)
    elif len(value) > 65536:
        raise ValueError(key)
    elif field_type == "url" and not _validate_url(value):
        raise ValueError(key)
    elif field_type == "enum" and value and value not in options:
        raise ValueError(key)
    elif field_type == "json" and value:
        try:
            json.loads(value)
        except ValueError as exc:
            raise ValueError(key) from exc
    return value


def _validate_sections(raw: Dict[str, Any], result: Dict[str, Any]) -> None:
    for section, specs in SECTION_SPECS.items():
        values = raw.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(section)
        for key, field_type, _group, options, _default in specs:
            if key in values:
                result[section][key] = _validate_section_value(key, values[key], field_type, options)
    # Feature validators are imported lazily to avoid the intentional dependency
    # from the feature modules back to this module's header/rule helpers.
    from services.subscription_xray_json import validate_xray_json_section
    from services.subscription_response_rules import validate_response_rules
    from services.subscription_page import validate_page_section

    validate_xray_json_section(result.get("xray_json", {}))
    validate_response_rules(result.get("response_rules", {}).get("rules", ""))
    validate_page_section(result.get("page", {}))


def _validate_headers(headers: Any) -> list[dict[str, str]]:
    if not isinstance(headers, list) or len(headers) > 16:
        raise ValueError("headers")
    result = []
    for header in headers:
        if not isinstance(header, dict) or not isinstance(header.get("key"), str) or not isinstance(header.get("value", ""), str):
            raise ValueError("headers")
        key = header["key"]
        if not _HEADER_NAME.fullmatch(key) or key.lower() in _FORBIDDEN_HEADERS:
            raise ValueError("headers")
        result.append({"key": key, "value": header.get("value", "")})
    return result


def _validate_client(item: Any, builtins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("clients")
    client_id = item.get("id", "")
    if not isinstance(client_id, str):
        raise ValueError("id")
    if client_id in builtins:
        base = copy.deepcopy(builtins[client_id])
        for key in ("name", "enabled", "user_agent_regex", "format", "settings", "headers"):
            if key in item:
                base[key] = item[key]
        base["id"] = client_id
        base["kind"] = builtins[client_id]["kind"]
        base["builtin"] = True
    else:
        if not re.fullmatch(r"custom-[a-z0-9-]+", client_id):
            raise ValueError("id")
        base = {
            "id": client_id,
            "name": item.get("name", ""),
            "kind": "generic",
            "builtin": False,
            "enabled": item.get("enabled", False),
            "user_agent_regex": item.get("user_agent_regex", ""),
            "format": item.get("format", "base64"),
            "settings": {},
            "headers": item.get("headers", []),
        }
    if not isinstance(base["name"], str) or not 1 <= len(base["name"]) <= 64:
        raise ValueError("name")
    if not isinstance(base["enabled"], bool):
        raise ValueError("enabled")
    if not isinstance(base["user_agent_regex"], str) or len(base["user_agent_regex"]) > 300:
        raise ValueError("user_agent_regex")
    try:
        validate_admin_regex(base["user_agent_regex"])
    except ValueError as exc:
        raise ValueError("user_agent_regex") from exc
    if base["format"] not in FORMATS:
        raise ValueError("format")
    raw_settings = base["settings"]
    if not isinstance(raw_settings, dict):
        raise ValueError("settings")
    allowed = {spec[0]: spec for spec in FIELD_SPECS.get(base["kind"], [])}
    clean_settings = {}
    for key, value in raw_settings.items():
        spec = allowed.get(key)
        if spec is None:
            continue
        clean_settings[key] = _validate_field(base["kind"], key, value, spec)
    base["settings"] = clean_settings
    base["headers"] = _validate_headers(base["headers"])
    return base


def _headers_for_limit(settings: Dict[str, Any], client: Dict[str, Any]) -> Dict[str, str]:
    profile_only = {"profile": settings.get("profile", {})}
    _client, headers = build_headers(profile_only, None, fallback_title="", fallback_interval=1)
    for name, value in _field_headers(client).items():
        _put_header(headers, name, value)
    return headers


def validate_settings(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("settings")
    result = default_settings()
    _validate_profile(raw.get("profile", {}), result)
    _validate_sections(raw, result)
    clients = raw.get("clients", [])
    if not isinstance(clients, list) or len(clients) > 32:
        raise ValueError("clients")
    builtins = {client["id"]: client for client in DEFAULT_CLIENTS}
    seen = set()
    ordered = []
    for item in clients:
        client = _validate_client(item, builtins)
        if client["id"] in seen:
            raise ValueError("id")
        seen.add(client["id"])
        ordered.append(client)
    for client in DEFAULT_CLIENTS:
        if client["id"] not in seen:
            ordered.append(copy.deepcopy(client))
    if len(ordered) > 32:
        raise ValueError("clients")
    result["clients"] = ordered
    for client in ordered:
        headers = _headers_for_limit(result, client)
        if sum(len(name.encode()) + len(value.encode()) for name, value in headers.items()) > 3072:
            raise ValueError("headers")
    try:
        rules = json.loads(result.get("response_rules", {}).get("rules", "") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        rules = []
    if isinstance(rules, list):
        for rule in rules:
            rule_total = sum(
                len(str(item.get("key", "")).encode()) + len(str(item.get("value", "")).encode())
                for item in (rule.get("modifications", {}).get("headers", []) if isinstance(rule, dict) else [])
            )
            if rule_total > 3072:
                raise ValueError("headers")
            for client in ordered:
                if rule_total + sum(len(k.encode()) + len(v.encode()) for k, v in _headers_for_limit(result, client).items()) > 3072:
                    raise ValueError("headers")
    return result


def load_settings(db_path: str) -> Dict[str, Any]:
    with connect(db_path) as conn:
        ensure_subscription_client_settings_table(conn)
        row = conn.execute("SELECT settings_json FROM subscription_client_settings WHERE id=1").fetchone()
    if not row:
        return default_settings()
    try:
        return validate_settings(json.loads(row[0]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default_settings()


def save_settings(db_path: str, settings: Any) -> Dict[str, Any]:
    value = validate_settings(settings)
    with connect(db_path) as conn:
        ensure_subscription_client_settings_table(conn)
        conn.execute(
            "INSERT INTO subscription_client_settings(id,settings_json) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=CURRENT_TIMESTAMP",
            (json.dumps(value, ensure_ascii=False),),
        )
        conn.commit()
    return value


def match_client(settings: Dict[str, Any], user_agent: Optional[str]) -> Optional[Dict[str, Any]]:
    value = (user_agent or "")[:512]
    if not value:
        return None
    for client in settings.get("clients", []):
        if client.get("enabled") and client.get("user_agent_regex") and re.search(client["user_agent_regex"], value, re.IGNORECASE):
            return client
    return None


def _put_header(result: Dict[str, str], key: str, value: str) -> None:
    for existing in list(result):
        if existing.lower() == key.lower():
            del result[existing]
    result[key] = value


def _field_headers(client: Dict[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    values = client.get("settings", {})
    for key, header, field_type, _group, options in FIELD_SPECS.get(client.get("kind"), []):
        value = values.get(key, "")
        if field_type == "bool":
            if key not in values:
                continue
            if key == "exclude_apns":
                if not value:
                    continue
                value = "true"
            elif key in {"no_limit", "sub_expire", "notification_expire", "autoconnect"}:
                if not value:
                    continue
                value = "1"
            elif key == "routing_enable":
                value = "true" if value else "0"
            else:
                value = "1" if value else "0"
        elif field_type == "tristate":
            value = {"on": "1", "off": "0"}.get(value, "")
        elif field_type == "enum" and options and value not in options:
            value = ""
        if key == "sub_info_color" and values.get("sub_info_text") and not value:
            value = "blue"
        if not value or not header:
            continue
        if key in {"sub_info_color", "sub_info_button_text", "sub_info_button_link"} and not values.get("sub_info_text"):
            continue
        if key == "sub_expire_button_link" and not values.get("sub_expire"):
            continue
        if key == "autoconnect_type" and not values.get("autoconnect"):
            continue
        if key == "per_app_list" and not values.get("per_app_mode"):
            continue
        _put_header(result, header, _clean_header_value(value))
        if key == "local_proxy_auth":
            _put_header(result, "Http-Auth-Mode", _clean_header_value(value))
    for header in client.get("headers", []):
        value = _clean_header_value(header.get("value", ""))
        if value:
            _put_header(result, header["key"], value)
    return result


def build_headers(
    settings: Dict[str, Any],
    user_agent: Optional[str],
    *,
    fallback_title: str = "",
    fallback_interval: Optional[int] = 1,
):
    profile = settings.get("profile", {})
    result: Dict[str, str] = {}
    title = profile.get("title") or fallback_title
    interval = profile.get("update_interval_hours")
    if interval is None:
        interval = fallback_interval
    for name, value in (
        ("Profile-Title", title),
        ("Support-Url", profile.get("support_url", "")),
        ("Profile-Web-Page-Url", profile.get("web_page_url", "")),
        ("Announce", profile.get("announce", "")),
    ):
        cleaned = _clean_header_value(value)
        if cleaned:
            _put_header(result, name, cleaned)
    if interval is not None and interval != 0:
        _put_header(result, "Profile-Update-Interval", str(interval))
    client = match_client(settings, user_agent)
    if client:
        for name, value in _field_headers(client).items():
            _put_header(result, name, value)
    return client, result


def schema() -> Dict[str, Any]:
    result = {}
    for kind, specs in FIELD_SPECS.items():
        result[kind] = [
            {"key": key, "header": header, "type": field_type, "group": group, **({"options": options} if options else {})}
            for key, header, field_type, group, options in specs
        ]
    return result


def section_schema() -> Dict[str, Any]:
    return {
        section: [
            {"key": key, "type": field_type, "group": group, **({"options": options} if options else {})}
            for key, field_type, group, options, _default in specs
        ]
        for section, specs in SECTION_SPECS.items()
    }
