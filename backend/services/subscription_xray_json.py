from __future__ import annotations

import copy
import json
from typing import Any

from services.subscription_formats import _normalised

VALID_BALANCER_STRATEGIES = {"leastLoad", "leastPing", "random", "roundRobin"}
OBJECT_FIELDS = {"mux", "dns", "routing", "final_mask", "observatory"}
ARRAY_FIELDS = {"rules", "balancers"}


def _parse_field(section: dict[str, Any], key: str) -> Any:
    val = section.get(key)
    if val is None or val == "":
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception as exc:
            raise ValueError(key) from exc
    return val


def validate_xray_json_section(section: dict[str, Any]) -> None:
    if not isinstance(section, dict):
        raise ValueError("section")

    if "always_array" in section and section["always_array"] is not None:
        if not isinstance(section["always_array"], bool):
            raise ValueError("always_array")

    template = _parse_field(section, "template")
    if template is not None:
        if not isinstance(template, dict):
            raise ValueError("template")
        for field in ("inbounds", "outbounds"):
            if field in template:
                value = template[field]
                if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                    raise ValueError("template")
        if "routing" in template and not isinstance(template["routing"], dict):
            raise ValueError("template")

    for field in OBJECT_FIELDS:
        parsed = _parse_field(section, field)
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError(field)

    for field in ARRAY_FIELDS:
        parsed = _parse_field(section, field)
        if parsed is not None:
            if not isinstance(parsed, list):
                raise ValueError(field)
            if field == "rules":
                for r in parsed:
                    if not isinstance(r, dict):
                        raise ValueError("rules")
            elif field == "balancers":
                seen_tags: set[str] = set()
                for b in parsed:
                    if not isinstance(b, dict):
                        raise ValueError("balancers")
                    tag = b.get("tag")
                    if not isinstance(tag, str) or not tag.strip():
                        raise ValueError("balancers")
                    if tag in seen_tags:
                        raise ValueError("balancers")
                    seen_tags.add(tag)

                    if "selector" in b and not isinstance(b["selector"], list):
                        raise ValueError("balancers")

                    strategy = b.get("strategy")
                    if not isinstance(strategy, dict):
                        raise ValueError("balancers")
                    st_type = strategy.get("type")
                    if st_type not in VALID_BALANCER_STRATEGIES:
                        raise ValueError("balancers")


def _build_proxy_outbound(
    item: dict[str, Any],
    tag: str,
    mux: dict[str, Any] | None,
    final_mask: dict[str, Any] | None,
) -> dict[str, Any]:
    kind = item["kind"]
    outbound: dict[str, Any] = {
        "tag": tag,
        "protocol": kind,
    }

    if kind == "vless":
        user: dict[str, Any] = {
            "id": item["id"],
            "encryption": item.get("encryption") or "none",
        }
        if item.get("flow"):
            user["flow"] = item["flow"]
        outbound["settings"] = {
            "vnext": [
                {
                    "address": item["server"],
                    "port": item["port"],
                    "users": [user],
                }
            ]
        }
    elif kind == "vmess":
        user = {
            "id": item["id"],
            "security": item.get("scy") or item.get("security") or "auto",
        }
        if item.get("flow"):
            user["flow"] = item["flow"]
        outbound["settings"] = {
            "vnext": [
                {
                    "address": item["server"],
                    "port": item["port"],
                    "users": [user],
                }
            ]
        }
    elif kind == "trojan":
        outbound["settings"] = {
            "servers": [
                {
                    "address": item["server"],
                    "port": item["port"],
                    "password": item["password"],
                }
            ]
        }

    net = item["network"]
    network = "http" if net in {"http", "h2"} else net
    stream_settings: dict[str, Any] = {
        "network": network,
    }

    sec = item.get("security", "")
    if sec == "reality" or bool(item.get("pbk")):
        stream_settings["security"] = "reality"
        stream_settings["realitySettings"] = {
            "serverName": item.get("sni", ""),
            "fingerprint": item.get("fp", ""),
            "publicKey": item.get("pbk", ""),
            "shortId": item.get("sid", ""),
        }
    elif sec == "tls" or item.get("_tls") is True or (kind == "trojan" and sec != "none"):
        stream_settings["security"] = "tls"
        stream_settings["tlsSettings"] = {
            "serverName": item.get("sni", ""),
            "fingerprint": item.get("fp", ""),
        }
    else:
        stream_settings["security"] = "none"

    if net == "ws":
        stream_settings["wsSettings"] = {
            "path": item.get("path", ""),
            "headers": {"Host": item["host"]} if item.get("host") else {},
        }
    elif net == "grpc":
        stream_settings["grpcSettings"] = {
            "serviceName": item.get("service_name", ""),
            "multiMode": item.get("mode") == "multi" or bool(item.get("multiMode")),
        }
    elif net == "httpupgrade":
        stream_settings["httpupgradeSettings"] = {
            "path": item.get("path", ""),
            "host": item.get("host", ""),
        }
    elif net == "xhttp":
        stream_settings["xhttpSettings"] = {
            "path": item.get("path", ""),
            "host": item.get("host", ""),
            "mode": item.get("mode", ""),
        }
    elif net in {"http", "h2"}:
        hosts = [item["host"]] if item.get("host") else []
        stream_settings["httpSettings"] = {
            "path": item.get("path", ""),
            "host": hosts,
        }

    if final_mask is not None:
        stream_settings["finalmask"] = copy.deepcopy(final_mask)

    outbound["streamSettings"] = stream_settings

    if mux is not None:
        outbound["mux"] = copy.deepcopy(mux)

    return outbound


def _default_inbounds() -> list[dict[str, Any]]:
    return [
        {
            "tag": "socks",
            "port": 10808,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls"],
            },
            "settings": {
                "auth": "noauth",
                "udp": True,
            },
        },
        {
            "tag": "http",
            "port": 10809,
            "listen": "127.0.0.1",
            "protocol": "http",
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls"],
            },
            "settings": {
                "allowTransparent": False,
            },
        },
    ]


def _system_outbounds() -> list[dict[str, Any]]:
    return [
        {
            "tag": "direct",
            "protocol": "freedom",
            "settings": {},
        },
        {
            "tag": "block",
            "protocol": "blackhole",
            "settings": {},
        },
    ]


def _build_routing(
    user_rules: list[dict[str, Any]] | None,
    fallback_rule: dict[str, Any],
    routing_overlay: dict[str, Any] | None,
    balancers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    if user_rules:
        rules.extend(copy.deepcopy(user_rules))
    rules.append(copy.deepcopy(fallback_rule))

    routing: dict[str, Any] = {
        "domainStrategy": "AsIs",
        "rules": rules,
    }
    if balancers:
        routing["balancers"] = copy.deepcopy(balancers)

    if routing_overlay:
        for k, v in routing_overlay.items():
            if k == "rules":
                continue
            routing[k] = copy.deepcopy(v)

    return routing


def to_xray_json(links: list[str], section: dict[str, Any]) -> str:
    validate_xray_json_section(section)

    proxies = _normalised(links)
    if not proxies:
        return ""

    always_array = bool(section.get("always_array", False))
    template = _parse_field(section, "template")
    mux = _parse_field(section, "mux")
    dns = _parse_field(section, "dns")
    routing_overlay = _parse_field(section, "routing")
    user_rules = _parse_field(section, "rules")
    if user_rules is None and routing_overlay and "rules" in routing_overlay:
        user_rules = routing_overlay["rules"]
    final_mask = _parse_field(section, "final_mask")
    observatory_override = _parse_field(section, "observatory")
    balancers = _parse_field(section, "balancers")

    if template is not None:
        configs = []
        for item in proxies:
            config = copy.deepcopy(template)
            config["remarks"] = item["name"]
            proxy_outbound = _build_proxy_outbound(item, "proxy", mux, final_mask)
            if "outbounds" in config:
                template_outbounds = config["outbounds"]
                config["outbounds"] = [
                    proxy_outbound,
                    *[outbound for outbound in template_outbounds if outbound.get("tag") != "proxy"],
                ]
            else:
                config["outbounds"] = [proxy_outbound, *_system_outbounds()]
            if "inbounds" not in config:
                config["inbounds"] = _default_inbounds()
            if "routing" not in config:
                config["routing"] = _build_routing(
                    None,
                    {"type": "field", "outboundTag": "proxy"},
                    None,
                )
            configs.append(config)

        if len(configs) == 1 and not always_array:
            return json.dumps(configs[0], ensure_ascii=False, indent=2)
        return json.dumps(configs, ensure_ascii=False, indent=2)

    if balancers:
        # Xray matches selectors by tag prefix; an empty selector would leave the balancer with no outbounds.
        balancers = [{**b, "selector": b.get("selector") or ["proxy-"]} for b in balancers]
        proxy_outbounds = [
            _build_proxy_outbound(item, f"proxy-{idx + 1}", mux, final_mask)
            for idx, item in enumerate(proxies)
        ]
        fallback_rule = {
            "type": "field",
            "balancerTag": balancers[0]["tag"],
        }
        routing = _build_routing(user_rules, fallback_rule, routing_overlay, balancers)

        remarks = section.get("remarks") or balancers[0]["tag"]
        config: dict[str, Any] = {
            "remarks": remarks,
            "log": {
                "loglevel": "warning",
            },
            "inbounds": _default_inbounds(),
            "outbounds": [*proxy_outbounds, *_system_outbounds()],
            "routing": routing,
        }
        if dns is not None:
            config["dns"] = copy.deepcopy(dns)

        needs_observatory = any(
            b.get("strategy", {}).get("type") in {"leastLoad", "leastPing"}
            for b in balancers
        )
        if observatory_override is not None:
            config["observatory"] = copy.deepcopy(observatory_override)
        elif needs_observatory:
            all_selectors: list[str] = []
            for b in balancers:
                for s in b.get("selector", []):
                    if s not in all_selectors:
                        all_selectors.append(s)
            config["observatory"] = {
                "subjectSelector": all_selectors,
                "probeUrl": "https://www.gstatic.com/generate_204",
                "probeInterval": "5m",
            }

        result = [config] if always_array else config
        return json.dumps(result, ensure_ascii=False, indent=2)

    configs = []
    for item in proxies:
        proxy_outbound = _build_proxy_outbound(item, "proxy", mux, final_mask)
        fallback_rule = {
            "type": "field",
            "outboundTag": "proxy",
        }
        routing = _build_routing(user_rules, fallback_rule, routing_overlay)

        remarks = item["name"]
        config = {
            "remarks": remarks,
            "log": {
                "loglevel": "warning",
            },
            "inbounds": _default_inbounds(),
            "outbounds": [proxy_outbound, *_system_outbounds()],
            "routing": routing,
        }
        if dns is not None:
            config["dns"] = copy.deepcopy(dns)
        if observatory_override is not None:
            config["observatory"] = copy.deepcopy(observatory_override)

        configs.append(config)

    if len(configs) == 1 and not always_array:
        return json.dumps(configs[0], ensure_ascii=False, indent=2)

    return json.dumps(configs, ensure_ascii=False, indent=2)
