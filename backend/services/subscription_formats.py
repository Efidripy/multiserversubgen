from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit

import yaml


SUPPORTED_NETWORKS = {"tcp", "ws", "http", "h2", "grpc", "xhttp", "httpupgrade"}


def _links(value):
    for raw in value or []:
        if isinstance(raw, str) and raw.startswith(("vless://", "vmess://", "trojan://")):
            yield raw


def _name(raw, vmess=None):
    value = (vmess or {}).get("ps") if vmess else ""
    if not value:
        value = unquote(urlsplit(raw).fragment or "proxy")
    return value or "proxy"


def _unique(name, used):
    if name not in used:
        used.add(name)
        return name
    index = 2
    while f"{name} {index}" in used:
        index += 1
    result = f"{name} {index}"
    used.add(result)
    return result


def _parse(raw):
    try:
        parsed = urlsplit(raw)
        query = {
            key: values[0]
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        }
        if parsed.scheme == "vmess":
            payload = parsed.netloc + parsed.path
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            obj = json.loads(decoded.decode())
            server = obj.get("add")
            port = int(obj.get("port")) if obj.get("port") not in (None, "") else None
            if not server or port is None or not obj.get("id"):
                return None, None
            obj.update(
                {
                    "server": server,
                    "port": port,
                    "_name": _name(raw, obj),
                    "_network": obj.get("net", "tcp"),
                    "_tls": str(obj.get("tls", "")).lower() in {"tls", "true", "1"},
                }
            )
            return "vmess", obj
        server = parsed.hostname
        port = parsed.port
        identifier = unquote(parsed.username or "")
        if not server or port is None:
            return None, None
        if parsed.scheme == "vless" and not identifier:
            return None, None
        if parsed.scheme == "trojan" and not identifier:
            return None, None
        return parsed.scheme, {
            "server": server,
            "port": port,
            "id": identifier,
            "password": identifier,
            "query": query,
            "network": query.get("type", "tcp"),
            "name": _name(raw),
        }
    except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        return None, None


def _normalised(links):
    result = []
    used = set()
    for raw in _links(links):
        kind, obj = _parse(raw)
        if not obj:
            continue
        name = _unique(obj.get("_name") or obj.get("name") or "proxy", used)
        network = obj.get("_network") or obj.get("network") or "tcp"
        if network not in SUPPORTED_NETWORKS:
            continue
        query = obj.get("query", {})
        security = query.get("security", "")
        if kind == "vmess" and obj.get("pbk"):
            continue
        obj.update(
            {
                "kind": kind,
                "name": name,
                "network": network,
                "security": security,
                "sni": query.get("sni", obj.get("sni", "")),
                "fp": query.get("fp", obj.get("fp", "")),
                "pbk": query.get("pbk", obj.get("pbk", "")),
                "sid": query.get("sid", obj.get("sid", "")),
                "flow": query.get("flow", obj.get("flow", "")),
                "path": query.get("path", obj.get("path", "")),
                "host": query.get("host", obj.get("host", "")),
                "service_name": query.get("serviceName", obj.get("path", "") if kind == "vmess" and network == "grpc" else ""),
                "mode": query.get("mode", ""),
            }
        )
        result.append(obj)
    return result


def _rule_lines(rules):
    if isinstance(rules, str):
        return rules.splitlines()
    if isinstance(rules, list):
        return [rule for rule in rules if isinstance(rule, str)]
    return []


def to_mihomo(links, *, mode="mihomo", enable_routing=False, rules=None, customize=None):
    proxies = []
    for item in _normalised(links):
        if mode == "clash" and item["kind"] == "vless":
            continue
        if mode == "clash" and item.get("security") == "reality":
            continue
        if mode == "clash" and item["network"] == "xhttp":
            continue
        proxy = {
            "name": item["name"],
            "type": item["kind"],
            "server": item["server"],
            "port": item["port"],
            "udp": True,
        }
        if item["kind"] == "vless":
            proxy.update(uuid=item["id"], network=item["network"], tls=True)
        elif item["kind"] == "vmess":
            proxy.update(
                uuid=item["id"],
                alterId=0,
                cipher="auto",
                network=item["network"],
                tls=item.get("_tls", False),
            )
        else:
            proxy.update(password=item["password"], network=item["network"])
        if item.get("sni"):
            proxy["servername" if item["kind"] != "trojan" else "sni"] = item["sni"]
        if item.get("flow"):
            proxy["flow"] = item["flow"]
        if item.get("fp") and mode != "clash":
            proxy["client-fingerprint"] = item["fp"]
        if item.get("pbk") and mode != "clash":
            proxy["reality-opts"] = {
                "public-key": item["pbk"],
                "short-id": item.get("sid", ""),
            }
        if item["network"] == "tcp":
            proxy.pop("network", None)
        proxies.append(proxy)
    if not proxies:
        return ""
    names = [proxy["name"] for proxy in proxies]
    if enable_routing:
        clean_rules = [
            rule.strip()
            for rule in _rule_lines(rules)
            if rule.strip() and not rule.lstrip().startswith("#")
        ]
        if not clean_rules or not clean_rules[-1].startswith("MATCH,"):
            clean_rules.append("MATCH,PROXY")
    else:
        clean_rules = ["MATCH,PROXY"]
    body = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "PROXY", "type": "select", "proxies": names + ["DIRECT"]}
        ],
        "rules": clean_rules,
    }
    if customize:
        customize(body)
    return yaml.safe_dump(body, allow_unicode=True, sort_keys=False)


def to_singbox(links):
    proxies = []
    for item in _normalised(links):
        proxy = {
            "type": item["kind"],
            "tag": item["name"],
            "server": item["server"],
            "server_port": item["port"],
        }
        if item["kind"] == "vless":
            proxy["uuid"] = item["id"]
            if item.get("flow"):
                proxy["flow"] = item["flow"]
        elif item["kind"] == "vmess":
            proxy.update(uuid=item["id"], security="auto", alter_id=0)
        else:
            proxy["password"] = item["password"]
        tls = None
        if item["kind"] != "vmess" or item.get("_tls", False) or item.get("pbk"):
            tls = {"enabled": True}
            if item.get("sni"):
                tls["server_name"] = item["sni"]
            if item.get("fp"):
                tls["utls"] = {"enabled": True, "fingerprint": item["fp"]}
            if item.get("pbk"):
                tls["reality"] = {
                    "enabled": True,
                    "public_key": item["pbk"],
                    "short_id": item.get("sid", ""),
                }
        if tls is not None:
            proxy["tls"] = tls
        network = item["network"]
        if network in {"ws", "grpc", "http", "h2"}:
            proxy["transport"] = {"type": "http" if network == "h2" else network}
        elif network != "tcp":
            continue
        proxies.append(proxy)
    if not proxies:
        return ""
    names = [proxy["tag"] for proxy in proxies]
    body = {
        "log": {"disabled": True},
        "dns": {
            "servers": [
                {"tag": "remote", "type": "tls", "server": "1.1.1.1", "detour": "PROXY"},
                {"tag": "local", "type": "udp", "server": "1.1.1.1"},
            ],
            "final": "remote",
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
                "auto_route": True,
                "strict_route": True,
                "stack": "mixed",
            }
        ],
        "outbounds": [
            {"type": "selector", "tag": "PROXY", "outbounds": names},
            *proxies,
            {"type": "direct", "tag": "direct"},
        ],
        "route": {
            "rules": [
                {"action": "sniff"},
                {"protocol": "dns", "action": "hijack-dns"},
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "final": "PROXY",
            "auto_detect_interface": True,
            "default_domain_resolver": "local",
        },
    }
    return json.dumps(body, ensure_ascii=False, indent=2)


def convert_links(links, format="base64", *, enable_routing=False, rules=None, extra_text=None, customize=None, encode=True):
    if format in {"mihomo", "clash"}:
        return to_mihomo(
            links,
            mode=format,
            enable_routing=enable_routing,
            rules=rules,
            customize=customize,
        )
    if format == "singbox":
        return to_singbox(links)
    lines = list(links or [])
    if extra_text:
        lines.append(extra_text)
    text = "\n".join(lines)
    return base64.b64encode(text.encode()).decode() if encode else text
