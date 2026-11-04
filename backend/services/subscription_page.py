"""Browser subscription page service conforming to Stage 2 Contract Section E."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import html
import json
import re
import time
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, quote, unquote


def validate_page_section(section: dict[str, Any]) -> None:
    """Validate 'page' configuration section.

    Raises ValueError(<field_name>) on invalid input.
    """
    if not isinstance(section, dict):
        raise ValueError("page")

    theme = section.get("theme")
    if theme is not None:
        if not isinstance(theme, str):
            raise ValueError("theme")
        if theme and theme not in {"remnawave", "3xui"}:
            raise ValueError("theme")

    profile_mode = section.get("profile_mode")
    if profile_mode is not None:
        if not isinstance(profile_mode, str):
            raise ValueError("profile_mode")
        if profile_mode and profile_mode not in {"builtin", "custom"}:
            raise ValueError("profile_mode")
        if profile_mode == "custom":
            profile_url = section.get("profile_url")
            if not isinstance(profile_url, str) or not profile_url:
                raise ValueError("profile_url")
            if not re.fullmatch(r"^https?://[^\s]+", profile_url, re.IGNORECASE):
                raise ValueError("profile_url")
            if any(ord(c) < 32 or ord(c) == 127 for c in profile_url):
                raise ValueError("profile_url")

    profile_url = section.get("profile_url")
    if profile_url is not None and profile_url != "":
        if not isinstance(profile_url, str):
            raise ValueError("profile_url")
        if not re.fullmatch(r"^https?://[^\s]+", profile_url, re.IGNORECASE):
            raise ValueError("profile_url")
        if any(ord(c) < 32 or ord(c) == 127 for c in profile_url):
            raise ValueError("profile_url")

    enabled = section.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("enabled")

    brand_title = section.get("brand_title")
    if brand_title is not None and not isinstance(brand_title, str):
        raise ValueError("brand_title")


def page_headers(nonce: str) -> dict[str, str]:
    """Return security and caching headers for the subscription HTML page."""
    nonce_val = str(nonce or "")
    return {
        "Content-Security-Policy": (
            f"default-src 'none'; img-src data:; style-src 'nonce-{nonce_val}'; "
            f"script-src 'nonce-{nonce_val}'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }


def _get_header(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    name_lower = name.lower()
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if str(k).lower() == name_lower:
                return str(v)
    elif isinstance(headers, (list, tuple)):
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                if str(item[0]).lower() == name_lower:
                    return str(item[1])
    return ""


def _parse_query(query: Any) -> dict[str, list[str]]:
    if not query:
        return {}
    if isinstance(query, str):
        cleaned = query.lstrip("?")
        pairs = parse_qsl(cleaned, keep_blank_values=True)
        res: dict[str, list[str]] = {}
        for k, v in pairs:
            res.setdefault(k.lower(), []).append(v)
        return res
    if isinstance(query, Mapping):
        res = {}
        for k, v in query.items():
            k_lower = str(k).lower()
            if isinstance(v, (list, tuple)):
                res[k_lower] = [str(x) for x in v if x is not None]
            elif v is not None:
                res[k_lower] = [str(v)]
            else:
                res[k_lower] = []
        return res
    if isinstance(query, Sequence):
        res = {}
        for item in query:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                k_lower = str(item[0]).lower()
                val = str(item[1]) if item[1] is not None else ""
                res.setdefault(k_lower, []).append(val)
        return res
    return {}


def wants_page(
    headers: Any,
    query: Any,
    section: dict[str, Any],
    *,
    client_matched: bool,
) -> bool:
    """Determine whether to serve the HTML subscription page.

    - Section disabled -> False.
    - True if ?html=1 or ?view=html.
    - If client_matched is False, ?format= is absent, and Accept contains text/html -> True.
    - Otherwise -> False.
    """
    if not isinstance(section, dict) or not section.get("enabled", False):
        return False

    parsed_query = _parse_query(query)

    # Check ?html=1 or ?view=html
    html_vals = parsed_query.get("html", [])
    if "1" in html_vals:
        return True

    view_vals = [v.lower() for v in parsed_query.get("view", [])]
    if "html" in view_vals:
        return True

    # If client not matched, format not specified, and Accept contains text/html
    if not client_matched:
        format_vals = parsed_query.get("format", [])
        has_format = any(bool(v.strip()) for v in format_vals)
        if not has_format:
            accept = _get_header(headers, "accept").lower()
            if "text/html" in accept:
                return True

    return False


def _format_bytes(num_bytes: int | float) -> str:
    val = float(max(0, num_bytes))
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_idx = 0
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(val)} B"
    formatted = f"{val:.1f}"
    if formatted.endswith(".0"):
        formatted = formatted[:-2]
    return f"{formatted} {units[unit_idx]}"


def _calculate_status(ctx: dict[str, Any], now: float | None = None) -> str:
    if "status" in ctx and ctx["status"] in {"active", "expired", "depleted"}:
        return str(ctx["status"])
    if now is None:
        now = float(ctx.get("now", 0) or time.time())
    expire = float(ctx.get("expire", 0) or 0)
    if expire > 1e11:
        expire /= 1000.0
    if expire > 0 and now > expire:
        return "expired"
    upload = int(ctx.get("upload", 0) or 0)
    download = int(ctx.get("download", 0) or 0)
    total = int(ctx.get("total", 0) or 0)
    used = upload + download
    if total > 0 and used >= total:
        return "depleted"
    return "active"


def _format_expire(expire: Any) -> str:
    if not expire:
        return "∞"
    try:
        exp_float = float(expire)
        if exp_float <= 0:
            return "∞"
        if exp_float > 1e11:
            exp_float /= 1000.0
        return datetime.fromtimestamp(exp_float, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return str(expire)


def _link_name_and_proto(link: str, index: int) -> tuple[str, str]:
    proto = "NODE"
    if "://" in link:
        proto_part = link.split("://", 1)[0].upper()
        if proto_part:
            proto = proto_part

    name = ""
    if "#" in link:
        frag = link.split("#", 1)[1]
        name = unquote(frag).strip()

    if not name and link.startswith("vmess://"):
        try:
            b64_part = link[len("vmess://") :]
            b64_part += "=" * (-len(b64_part) % 4)
            raw = base64.b64decode(b64_part).decode("utf-8")
            data = json.loads(raw)
            if "ps" in data and str(data["ps"]).strip():
                name = str(data["ps"]).strip()
        except Exception:
            pass

    if not name:
        name = f"{proto} #{index + 1}"

    return name, proto


def _render_import_buttons(sub_url: str, title: str, happ_link: str = "") -> str:
    quoted_sub = quote(sub_url, safe="")
    quoted_title = quote(title, safe="")
    happ_url = happ_link if happ_link else f"happ://add/{sub_url}"
    incy_url = f"incy://import/{sub_url}"
    clash_url = f"clash://install-config?url={quoted_sub}"
    singbox_url = f"sing-box://import-remote-profile?url={quoted_sub}#{quoted_title}"
    v2rayng_url = f"v2rayng://install-config?url={quoted_sub}"

    apps = [
        ("Happ", happ_url),
        ("Incy", incy_url),
        ("Clash", clash_url),
        ("sing-box", singbox_url),
        ("v2rayNG", v2rayng_url),
    ]
    parts = ['<div class="import-buttons">']
    for name, url in apps:
        escaped_url = html.escape(url, quote=True)
        escaped_name = html.escape(name)
        parts.append(
            f'  <a href="{escaped_url}" class="btn import-btn" role="button">{escaped_name}</a>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def _render_links_html(links: list[str], copy_label: str, empty_label: str) -> str:
    if not links:
        return f'<div class="links-empty">{html.escape(empty_label)}</div>'
    parts = ['<ul class="links-list">']
    for idx, link in enumerate(links):
        name, proto = _link_name_and_proto(link, idx)
        escaped_name = html.escape(name)
        escaped_proto = html.escape(proto)
        escaped_link = html.escape(link, quote=True)
        escaped_copy = html.escape(copy_label)
        parts.append(
            f'  <li class="link-item">'
            f'<div class="link-info">'
            f'<span class="link-name">{escaped_name}</span>'
            f'<span class="link-proto">{escaped_proto}</span>'
            f"</div>"
            f'<button type="button" class="btn btn-sm copy-btn" data-copy="{escaped_link}">{escaped_copy}</button>'
            f"</li>"
        )
    parts.append("</ul>")
    return "\n".join(parts)


def render_page(
    ctx: dict[str, Any],
    section: dict[str, Any],
    *,
    profile: dict[str, Any],
    sub_url: str,
    links: list[str],
    qr_data_url: str = "",
    happ_link: str = "",
    nonce: str = "",
) -> str:
    """Render one of the built-in subscription page themes."""
    from services.subscription_page_themes import render_theme

    title = (
        str(
            (section or {}).get("brand_title")
            or (profile or {}).get("title")
            or "Subscription"
        ).strip()
        or "Subscription"
    )
    status = _calculate_status(ctx)
    upload_present = "upload" in ctx
    download_present = "download" in ctx
    upload = int(ctx.get("upload", 0) or 0)
    download = int(ctx.get("download", 0) or 0)
    total = int(ctx.get("total", 0) or 0)
    used = upload + download
    used_str = _format_bytes(used) if upload_present or download_present else "—"
    total_str = "∞" if total <= 0 else _format_bytes(total)
    expire_str = _format_expire(ctx.get("expire"))
    if total > 0:
        percent = min(100.0, max(0.0, used / total * 100.0))
    else:
        percent = 0.0
    is_en = str(ctx.get("lang") or "ru").strip().lower().startswith("en")
    lang = "en" if is_en else "ru"
    labels = {
        "copy": "Copy" if is_en else "Копировать",
        "copied": "Copied" if is_en else "Скопировано",
        "qr": "QR Code" if is_en else "QR-код",
        "qr_hint": "Scan in your VPN app"
        if is_en
        else "Отсканируйте код в VPN-приложении",
        "close": "Close" if is_en else "Закрыть",
        "install": "Installation" if is_en else "Установка",
        "download": "Download" if is_en else "Скачать",
        "add": "Add subscription" if is_en else "Добавить подписку",
        "add_button": "Open" if is_en else "Открыть",
        "manual": "If it was not added, use the link button in the header."
        if is_en
        else "Если подписка не добавилась, используйте кнопку ссылки в шапке.",
        "connect": "Connect and enable the profile."
        if is_en
        else "Включите профиль и подключитесь.",
        "username": "Username" if is_en else "Имя пользователя",
        "status": "Status" if is_en else "Статус",
        "expire": "Expires" if is_en else "Срок действия",
        "traffic": "Traffic" if is_en else "Трафик",
        "used": "Used" if is_en else "Использовано",
        "total": "Total" if is_en else "Всего",
        "remaining": "Days left" if is_en else "Дней осталось",
        "downloaded": "Downloaded" if is_en else "Скачано",
        "uploaded": "Uploaded" if is_en else "Отправлено",
        "subscription": "Subscription" if is_en else "Подписка",
        "applications": "Applications" if is_en else "Приложения",
        "configurations": "Configurations" if is_en else "Конфигурации",
        "nodes": "Nodes" if is_en else "Узлы",
        "info_title": "Subscription information" if is_en else "Информация о подписке",
        "no_nodes": "No nodes available (Server Nodes)"
        if is_en
        else "Список узлов пуст",
        "update": "Auto-update" if is_en else "Автообновление",
        "hours": "hours" if is_en else "ч",
    }
    status_label = {
        "active": labels["status"] if is_en else "Активна",
        "expired": "Expired" if is_en else "Истекла",
        "depleted": "Traffic depleted" if is_en else "Лимит исчерпан",
    }[status]
    username = ctx.get("username") or ctx.get("user") or ctx.get("email") or title
    support_url = str((profile or {}).get("support_url") or "")
    announce = str((profile or {}).get("announce") or "")
    apps = [
        ("Happ", happ_link or f"happ://add/{sub_url}", "https://www.happ.su/", True),
        ("Incy", f"incy://import/{sub_url}", "", False),
        (
            "Clash",
            f"clash://install-config?url={quote(sub_url, safe='')}",
            "https://github.com/chen08209/FlClash/releases",
            True,
        ),
        (
            "sing-box",
            f"sing-box://import-remote-profile?url={quote(sub_url, safe='')}#{quote(title, safe='')}",
            "https://github.com/SagerNet/sing-box/releases",
            True,
        ),
        (
            "v2rayNG",
            f"v2rayng://install-config?url={quote(sub_url, safe='')}",
            "https://github.com/2dust/v2rayNG/releases",
            True,
        ),
    ]
    node_data = []
    for index, link in enumerate(links):
        name, proto = _link_name_and_proto(link, index)
        node_data.append((name, proto, link))
    remaining = "—"
    if ctx.get("expire"):
        try:
            exp = float(ctx.get("expire") or 0)
            exp = exp / 1000 if exp > 1e11 else exp
            remaining = str(
                max(0, int((exp - float(ctx.get("now", time.time()))) // 86400))
            )
        except (TypeError, ValueError, OverflowError):
            pass
    data = {
        "nonce": nonce,
        "lang": lang,
        "title": title,
        "status": status,
        "status_label": status_label,
        "status_label_name": labels["status"],
        "sub_url": sub_url,
        "qr_data_url": qr_data_url,
        "support_url": support_url,
        "announce": announce,
        "username": username,
        "expire": expire_str,
        "used": used_str,
        "total": total_str,
        "download": _format_bytes(download) if download_present else "—",
        "upload": _format_bytes(upload) if upload_present else "—",
        "percent": f"{percent:.0f}%" if total > 0 else "∞",
        "percent_decimal": f"{percent:.1f}%",
        "ring_offset": f"{301.6 * (1 - percent / 100):.1f}",
        "remaining": remaining,
        "identifier": ctx.get("sub_id") or ctx.get("email") or "",
        "apps": apps,
        "links": node_data,
        "happ_link": happ_link,
        "update_interval": (profile or {}).get("update_interval_hours"),
        "copy_label": labels["copy"],
        "copied_label": labels["copied"],
        "qr_label": labels["qr"],
        "qr_hint": labels["qr_hint"],
        "close_label": labels["close"],
        "install_title": labels["install"],
        "install_download_label": labels["download"],
        "install_label": labels["install"],
        "add_label": labels["add"],
        "add_button": labels["add_button"],
        "manual_label": labels["manual"],
        "connect_label": labels["connect"],
        "username_label": labels["username"],
        "expire_label": labels["expire"],
        "traffic_label": labels["traffic"],
        "used_label": labels["used"],
        "remaining_label": labels["remaining"],
        "download_label": labels["downloaded"],
        "upload_label": labels["uploaded"],
        "total_label": labels["total"],
        "sub_url_label": "Subscription URL" if is_en else "Адрес подписки",
        "sub_tab": labels["subscription"],
        "apps_tab": labels["applications"],
        "nodes_tab": labels["configurations"],
        "no_nodes": labels["no_nodes"],
        "update_label": labels["update"],
        "hours_label": labels["hours"],
        "info_title": labels["info_title"],
    }
    theme = str((section or {}).get("theme") or "remnawave").strip()
    if theme not in {"remnawave", "3xui"}:
        theme = "remnawave"
    return render_theme(theme, data)
