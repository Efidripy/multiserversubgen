from __future__ import annotations

import copy
import json
from typing import Any

from services.subscription_formats import _normalised

VALID_BALANCER_STRATEGIES = {"leastLoad", "leastPing", "random", "roundRobin"}

DEFAULT_XRAY_TEMPLATE: dict[str, Any] = {
    "dns": {"servers": ["1.1.1.1", "1.0.0.1"], "queryStrategy": "UseIP"},
    "routing": {
        "domainMatcher": "hybrid",
        "domainStrategy": "IPIfNonMatch",
        "rules": [{"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"}],
    },
    "inbounds": [
        {
            "tag": "socks", "port": 10808, "listen": "127.0.0.1", "protocol": "socks",
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            "settings": {"auth": "noauth", "udp": True},
        },
        {
            "tag": "http", "port": 10809, "listen": "127.0.0.1", "protocol": "http",
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            "settings": {"allowTransparent": False},
        },
    ],
    "outbounds": [
        {"tag": "direct", "protocol": "freedom"},
        {"tag": "block", "protocol": "blackhole"},
    ],
}


def _validate_template(template: Any, error_key: str = "template") -> None:
    if isinstance(template, str):
        try:
            template = json.loads(template)
        except Exception as exc:
            raise ValueError(error_key) from exc
    if not isinstance(template, dict):
        raise ValueError(error_key)
    for field in ("inbounds", "outbounds"):
        if field in template and (
            not isinstance(template[field], list)
            or any(not isinstance(item, dict) for item in template[field])
        ):
            raise ValueError(error_key)
    routing = template.get("routing")
    if routing is not None and not isinstance(routing, dict):
        raise ValueError(error_key)
    if isinstance(routing, dict):
        rules = routing.get("rules")
        if rules is not None and (
            not isinstance(rules, list) or any(not isinstance(item, dict) for item in rules)
        ):
            raise ValueError(error_key)
        balancers = routing.get("balancers")
        if balancers is not None:
            if not isinstance(balancers, list):
                raise ValueError(error_key)
            seen_tags: set[str] = set()
            for balancer in balancers:
                if not isinstance(balancer, dict):
                    raise ValueError(error_key)
                tag = balancer.get("tag")
                if not isinstance(tag, str) or not tag.strip() or tag in seen_tags:
                    raise ValueError(error_key)
                seen_tags.add(tag)
                selector = balancer.get("selector")
                if selector is not None and (
                    not isinstance(selector, list) or any(not isinstance(item, str) for item in selector)
                ):
                    raise ValueError(error_key)
                strategy = balancer.get("strategy")
                if not isinstance(strategy, dict) or strategy.get("type") not in VALID_BALANCER_STRATEGIES:
                    raise ValueError(error_key)


def validate_xray_json_section(section: dict[str, Any]) -> None:
    if not isinstance(section, dict):
        raise ValueError("section")

    if "always_array" in section and section["always_array"] is not None:
        if not isinstance(section["always_array"], bool):
            raise ValueError("always_array")

    if "enabled" in section and not isinstance(section["enabled"], bool):
        raise ValueError("enabled")
    if "active" in section and not isinstance(section["active"], str):
        raise ValueError("active")

    templates = section.get("templates", [])
    if not isinstance(templates, list) or len(templates) > 20:
        raise ValueError("templates")
    names: set[str] = set()
    exact_names: set[str] = set()
    for item in templates:
        if not isinstance(item, dict):
            raise ValueError("templates")
        name = item.get("name")
        template = item.get("template")
        if not isinstance(name, str):
            raise ValueError("templates")
        name = name.strip()
        if not name or len(name) > 64 or name.lower() == "default" or name.casefold() in names:
            raise ValueError("templates")
        names.add(name.casefold())
        exact_names.add(name)
        if not isinstance(template, str):
            raise ValueError("templates")
        _validate_template(template, "templates")
    active = section.get("active", "Default")
    if active != "Default" and active not in exact_names:
        raise ValueError("active")


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


def _proxy_skeleton(template: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    for outbound in template.get("outbounds", []):
        if outbound.get("tag") != "proxy":
            continue
        stream = outbound.get("streamSettings")
        stream = stream if isinstance(stream, dict) else {}
        mux = copy.deepcopy(outbound.get("mux")) if "mux" in outbound else None
        sockopt = copy.deepcopy(stream.get("sockopt")) if "sockopt" in stream else None
        finalmask = copy.deepcopy(stream.get("finalmask")) if "finalmask" in stream else None
        return mux, sockopt, finalmask
    return None, None, None


def _node_outbound(
    item: dict[str, Any],
    tag: str,
    mux: dict[str, Any] | None,
    sockopt: dict[str, Any] | None,
    finalmask: dict[str, Any] | None,
) -> dict[str, Any]:
    outbound = _build_proxy_outbound(item, tag, mux, finalmask)
    if sockopt is not None:
        outbound.setdefault("streamSettings", {})["sockopt"] = copy.deepcopy(sockopt)
    return outbound


def to_xray_json(links: list[str], section: dict[str, Any]) -> str:
    validate_xray_json_section(section)
    proxies = _normalised(links)
    if not proxies:
        return ""

    always_array = bool(section.get("always_array", False))
    enabled = bool(section.get("enabled", False))
    if not enabled:
        configs = []
        for item in proxies:
            config = {
                "remarks": item["name"],
                "log": {"loglevel": "warning"},
                "inbounds": _default_inbounds(),
                "outbounds": [_build_proxy_outbound(item, "proxy", None, None), *_system_outbounds()],
                "routing": {
                    "domainStrategy": "AsIs",
                    "rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}],
                },
            }
            configs.append(config)
        result = configs if always_array or len(configs) != 1 else configs[0]
        return json.dumps(result, ensure_ascii=False, indent=2)

    active = section.get("active", "Default")
    selected = DEFAULT_XRAY_TEMPLATE
    for entry in section.get("templates", []):
        if entry["name"].strip() == active:
            selected = json.loads(entry["template"])
            break
    template = copy.deepcopy(selected)
    mux, sockopt, finalmask = _proxy_skeleton(template)
    template_outbounds = [
        copy.deepcopy(outbound)
        for outbound in template.get("outbounds", [])
        if outbound.get("tag") != "proxy"
    ]

    routing_template = template.get("routing")
    balancers = routing_template.get("balancers") if isinstance(routing_template, dict) else None
    if isinstance(balancers, list) and balancers:
        balancers = [copy.deepcopy(item) for item in balancers]
        for balancer in balancers:
            if not balancer.get("selector"):
                balancer["selector"] = ["proxy-"]
        config = copy.deepcopy(template)
        config["remarks"] = template.get("remarks") or balancers[0]["tag"]
        config["outbounds"] = [
            _node_outbound(item, f"proxy-{index + 1}", mux, sockopt, finalmask)
            for index, item in enumerate(proxies)
        ]
        config["outbounds"].extend(template_outbounds or _system_outbounds())
        if "inbounds" not in config:
            config["inbounds"] = _default_inbounds()
        routing = copy.deepcopy(routing_template)
        routing["balancers"] = balancers
        rules = routing.get("rules")
        if not isinstance(rules, list):
            rules = []
        if not any(isinstance(rule, dict) and "balancerTag" in rule for rule in rules):
            rules.append({"type": "field", "network": "tcp,udp", "balancerTag": balancers[0]["tag"]})
        routing["rules"] = rules
        config["routing"] = routing
        needs_observatory = any(
            item.get("strategy", {}).get("type") in {"leastLoad", "leastPing"} for item in balancers
        )
        if needs_observatory and "observatory" not in config and "burstObservatory" not in config:
            selectors: list[str] = []
            for balancer in balancers:
                for selector in balancer.get("selector", []):
                    if selector not in selectors:
                        selectors.append(selector)
            config["observatory"] = {
                "subjectSelector": selectors,
                "probeUrl": "https://www.gstatic.com/generate_204",
                "probeInterval": "5m",
            }
        result: Any = [config] if always_array else config
        return json.dumps(result, ensure_ascii=False, indent=2)

    configs = []
    for item in proxies:
        config = copy.deepcopy(template)
        config["remarks"] = item["name"]
        config["outbounds"] = [_node_outbound(item, "proxy", mux, sockopt, finalmask)]
        config["outbounds"].extend(template_outbounds or _system_outbounds())
        if "inbounds" not in config:
            config["inbounds"] = _default_inbounds()
        if "routing" not in config:
            config["routing"] = {
                "domainStrategy": "AsIs",
                "rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}],
            }
        configs.append(config)

    result = configs if always_array or len(configs) != 1 else configs[0]
    return json.dumps(result, ensure_ascii=False, indent=2)
