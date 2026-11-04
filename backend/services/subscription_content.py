"""Rendering of subscription content and per-link presentation options."""

from __future__ import annotations

import base64
import json
import math
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit, urlunsplit

from services.subscription_formats import _normalised


_EMOJI = {"active": "✅", "expired": "⌛", "depleted": "🚫"}


def _human_bytes(value: float) -> str:
    value = max(0.0, float(value or 0))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.1f}".rstrip("0").rstrip(".") + f" {units[index]}"


def subscription_status(ctx: dict, now: float) -> str:
    expire = float(ctx.get("expire") or 0)
    if expire > 0 and now >= expire:
        return "expired"
    total = float(ctx.get("total") or 0)
    used = float(ctx.get("upload") or 0) + float(ctx.get("download") or 0)
    if total > 0 and used >= total:
        return "depleted"
    return "active"


def _link_details(link):
    if isinstance(link, dict):
        details = dict(link)
    else:
        parsed = _normalised([link] if isinstance(link, str) else [])
        details = parsed[0] if parsed else {}
        if not details and isinstance(link, str) and link.startswith("vmess://"):
            payload = link[len("vmess://") :]
            try:
                decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
                obj = json.loads(decoded.decode())
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                obj = {}
            if obj:
                details = {
                    **obj,
                    "kind": "vmess",
                    "protocol": "vmess",
                    "network": obj.get("net", "tcp"),
                    "name": obj.get("ps", ""),
                }
    if details.get("kind") == "vmess":
        raw_name = str(details.get("name") or details.get("ps") or "")
        match = re.search(r"\s\(([^()]*)\)$", raw_name)
        if match:
            details["name"] = match.group(1)
            details["_name"] = match.group(1)
    return details


def render_tokens(template: str, ctx: dict, link: dict | None = None) -> str:
    """Replace known ``{{TOKEN}}`` values while retaining unknown tokens."""
    data = dict(ctx or {})
    details = _link_details(link)
    email = str(data.get("email") or "")
    upload = float(data.get("upload") or 0)
    download = float(data.get("download") or 0)
    total = float(data.get("total") or 0)
    used = upload + download
    left = max(0.0, total - used) if total else 0.0
    now = float(data.get("now") or time.time())
    status = data.get("status") or subscription_status(data, now)
    expire = float(data.get("expire") or 0)
    if expire:
        days_left = max(0, math.ceil((expire - now) / 86400))
        expire_date = datetime.fromtimestamp(expire, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        days_left = "∞"
        expire_date = "∞"
    name = str(details.get("name") or details.get("_name") or details.get("node") or "")
    protocol = str(details.get("kind") or details.get("protocol") or details.get("type") or "")
    inbound = str(details.get("inbound") or details.get("inbound_remark") or details.get("remark") or "")
    values = {
        "EMAIL": email,
        "USERNAME": email.split("@", 1)[0] if "@" in email else email,
        "SUB_ID": str(data.get("sub_id") or ""),
        "NODE": name,
        "PROTOCOL": protocol,
        "INBOUND": inbound,
        "TRAFFIC_USED": _human_bytes(used),
        "TRAFFIC_LEFT": "∞" if not total else _human_bytes(left),
        "TRAFFIC_TOTAL": "∞" if not total else _human_bytes(total),
        "DAYS_LEFT": str(days_left),
        "EXPIRE_DATE": expire_date,
        "STATUS": str(status),
        "STATUS_EMOJI": _EMOJI.get(status, ""),
    }
    result = str(template or "")
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def _replace_name(raw: str, name: str) -> str:
    if raw.startswith("vmess://"):
        payload = raw[len("vmess://") :]
        try:
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            obj = json.loads(decoded.decode())
            obj["ps"] = name
            encoded = base64.b64encode(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()).decode()
            return "vmess://" + encoded
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, quote(name, safe="")))


def _info_link(text: str) -> str:
    return "vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1?encryption=none&security=none&type=tcp#" + quote(text, safe="")


def apply_content(
    links: list[str],
    section: dict,
    ctx: dict,
    *,
    now: float,
    shuffle=None,
    inbound_remark=None,
) -> list[str]:
    section = section or {}
    if not section or not any(section.get(key) for key in ("expired_template", "depleted_template", "remark_template", "show_identity_on_all_links", "host_order", "info_node")):
        return links
    status = subscription_status(ctx, now)
    template = section.get(status + "_template")
    if status != "active" and template:
        local_ctx = dict(ctx or {})
        local_ctx["now"] = now
        local_ctx["status"] = status
        return [_info_link(render_tokens(str(template), local_ctx))]

    local_ctx = dict(ctx or {})
    local_ctx["now"] = now
    local_ctx["status"] = status
    result = list(links)
    remark_template = section.get("remark_template")
    if remark_template:
        renamed = []
        for raw in result:
            details = _link_details(raw)
            if inbound_remark is not None and isinstance(details, dict):
                details = dict(details)
                details["inbound"] = inbound_remark(raw)
            name = render_tokens(str(remark_template), local_ctx, details)
            renamed.append(_replace_name(raw, name))
        result = renamed
    if section.get("show_identity_on_all_links"):
        email = str(ctx.get("email") or "")
        if email:
            result = [
                _replace_name(
                    raw,
                    (render_tokens("{{NODE}}", local_ctx, _link_details(raw)) or "") + " | " + email,
                )
                for raw in result
            ]

    order = section.get("host_order")
    if order == "name":
        result.sort(key=lambda raw: str(_link_details(raw).get("name") or _link_details(raw).get("_name") or "").casefold())
    elif order == "random" and shuffle:
        shuffled = list(result)
        shuffle(shuffled)
        result = shuffled
    if section.get("info_node"):
        result.insert(0, _info_link(render_tokens("{{TRAFFIC_LEFT}} · {{DAYS_LEFT}}", local_ctx)))
    return result
