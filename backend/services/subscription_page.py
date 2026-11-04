"""Browser subscription page service conforming to Stage 2 Contract Section E."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import html
import json
import os
import re
import time
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, quote, unquote

_THEME_DIR_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_THEME_FILE_SIZE = 256 * 1024  # 256 KB


def validate_page_section(section: dict[str, Any]) -> None:
    """Validate 'page' configuration section.

    Raises ValueError(<field_name>) on invalid input.
    """
    if not isinstance(section, dict):
        raise ValueError("page")

    theme_dir = section.get("theme_dir")
    if theme_dir is not None:
        if not isinstance(theme_dir, str):
            raise ValueError("theme_dir")
        if theme_dir and not _THEME_DIR_PATTERN.fullmatch(theme_dir):
            raise ValueError("theme_dir")

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
            f'</div>'
            f'<button type="button" class="btn btn-sm copy-btn" data-copy="{escaped_link}">{escaped_copy}</button>'
            f'</li>'
        )
    parts.append("</ul>")
    return "\n".join(parts)


def _load_theme_template(themes_root: str | None, theme_dir: str | None) -> str | None:
    if not themes_root or not theme_dir or not isinstance(theme_dir, str):
        return None
    theme_dir_clean = theme_dir.strip()
    if not _THEME_DIR_PATTERN.fullmatch(theme_dir_clean):
        return None
    try:
        real_root = os.path.realpath(themes_root)
        if not os.path.isdir(real_root):
            return None
        target_dir = os.path.realpath(os.path.join(real_root, theme_dir_clean))
        common = os.path.commonpath([real_root, target_dir])
        if common != real_root or target_dir == real_root:
            return None
        page_file = os.path.realpath(os.path.join(target_dir, "page.html"))
        common_file = os.path.commonpath([target_dir, page_file])
        if common_file != target_dir:
            return None
        if not os.path.isfile(page_file):
            return None
        if os.path.getsize(page_file) > _MAX_THEME_FILE_SIZE:
            return None
        with open(page_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def render_page(
    ctx: dict[str, Any],
    section: dict[str, Any],
    *,
    profile: dict[str, Any],
    sub_url: str,
    links: list[str],
    qr_data_url: str = "",
    happ_link: str = "",
    themes_root: str | None = None,
    nonce: str = "",
) -> str:
    """Render the subscription page HTML."""
    # 1. Resolve title: brand_title -> profile.title -> "Subscription"
    title = ""
    if section and isinstance(section, dict):
        title = str(section.get("brand_title") or "").strip()
    if not title and profile and isinstance(profile, dict):
        title = str(profile.get("title") or "").strip()
    if not title:
        title = "Subscription"

    # 2. Status & Traffic & Dates
    status = _calculate_status(ctx)
    upload = int(ctx.get("upload", 0) or 0)
    download = int(ctx.get("download", 0) or 0)
    total = int(ctx.get("total", 0) or 0)
    used = upload + download
    used_str = _format_bytes(used)
    total_str = "∞" if total <= 0 else _format_bytes(total)
    expire_str = _format_expire(ctx.get("expire"))

    if total > 0:
        used_percent = min(100.0, max(0.0, (used / total) * 100.0))
    else:
        used_percent = 0.0

    # 3. Localization
    is_en = str(ctx.get("lang") or "ru").strip().lower().startswith("en")
    lang_code = "en" if is_en else "ru"
    labels = {
        "used": "Used" if is_en else "Использовано",
        "total": "Total" if is_en else "Всего",
        "remaining": "Remaining" if is_en else "Осталось",
        "expire": "Expires" if is_en else "Срок действия",
        "status": "Status" if is_en else "Статус",
        "status_active": "Active" if is_en else "Активна",
        "status_expired": "Expired" if is_en else "Истекла",
        "status_depleted": "Traffic depleted" if is_en else "Лимит исчерпан",
        "sub_url": "Subscription URL" if is_en else "Адрес подписки",
        "copy": "Copy" if is_en else "Копировать",
        "copied": "Copied!" if is_en else "Скопировано!",
        "qr": "QR Code" if is_en else "QR-код",
        "import_apps": "Import to App" if is_en else "Импорт в приложение",
        "nodes": "Server Nodes" if is_en else "Список узлов",
        "no_nodes": "No nodes available" if is_en else "Список узлов пуст",
    }
    status_label = labels.get(f"status_{status}", status)

    # 4. Render components
    import_buttons_html = _render_import_buttons(sub_url, title, happ_link=happ_link)
    links_html = _render_links_html(links, labels["copy"], labels["no_nodes"])

    # 5. Check theme
    theme_template = _load_theme_template(themes_root, section.get("theme_dir") if section else None)
    if theme_template is not None:
        replacements = {
            "{{TITLE}}": html.escape(title),
            "{{SUB_URL}}": html.escape(sub_url),
            "{{USED}}": html.escape(used_str),
            "{{TOTAL}}": html.escape(total_str),
            "{{EXPIRE}}": html.escape(expire_str),
            "{{STATUS}}": html.escape(status),
            "{{QR}}": html.escape(qr_data_url),
            "{{NONCE}}": html.escape(nonce),
            "{{LINKS_HTML}}": links_html,
            "{{IMPORT_BUTTONS_HTML}}": import_buttons_html,
        }
        # One pass, so a token inside a substituted value is never expanded.
        pattern = "|".join(re.escape(token) for token in replacements)
        return re.sub(pattern, lambda match: replacements[match.group(0)], theme_template)

    # 6. Built-in responsive HTML page
    escaped_title = html.escape(title)
    escaped_sub_url = html.escape(sub_url, quote=True)
    escaped_nonce = html.escape(nonce, quote=True)
    escaped_qr = html.escape(qr_data_url, quote=True)
    escaped_status_label = html.escape(status_label)
    escaped_copied = html.escape(labels["copied"], quote=True)

    if qr_data_url:
        qr_section = (
            f'<div class="card qr-card">'
            f'<div class="card-title">{html.escape(labels["qr"])}</div>'
            f'<div class="qr-box"><img src="{escaped_qr}" alt="QR Code" class="qr-img"></div>'
            f'</div>'
        )
    else:
        qr_section = ""

    return f"""<!DOCTYPE html>
<html lang="{lang_code}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escaped_title}</title>
  <style nonce="{escaped_nonce}">
    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    :root {{
      --bg: #f5f6f8;
      --card-bg: #ffffff;
      --text: #1a1a1a;
      --text-muted: #6e6e73;
      --border: #e5e5ea;
      --primary: #007aff;
      --primary-hover: #0056b3;
      --progress-bg: #e5e5ea;
      --progress-fill: #007aff;
      --badge-active-bg: #e8f5e9;
      --badge-active-color: #2e7d32;
      --badge-expired-bg: #ffebee;
      --badge-expired-color: #c62828;
      --badge-depleted-bg: #fff3e0;
      --badge-depleted-color: #ef6c00;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #121212;
        --card-bg: #1e1e1e;
        --text: #f5f5f7;
        --text-muted: #8e8e93;
        --border: #2c2c2e;
        --primary: #0a84ff;
        --primary-hover: #409cff;
        --progress-bg: #2c2c2e;
        --progress-fill: #0a84ff;
        --badge-active-bg: #1b3820;
        --badge-active-color: #81c784;
        --badge-expired-bg: #3e1b1b;
        --badge-expired-color: #e57373;
        --badge-depleted-bg: #3e2e1b;
        --badge-depleted-color: #ffb74d;
      }}
    }}
    html, body {{
      min-width: 320px;
      overflow-x: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .container {{
      max-width: 580px;
      margin: 0 auto;
      padding: 16px;
      width: 100%;
    }}
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 20px;
    }}
    .header h1 {{
      font-size: 22px;
      font-weight: 700;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .status-badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .status-active {{
      background: var(--badge-active-bg);
      color: var(--badge-active-color);
    }}
    .status-expired {{
      background: var(--badge-expired-bg);
      color: var(--badge-expired-color);
    }}
    .status-depleted {{
      background: var(--badge-depleted-bg);
      color: var(--badge-depleted-color);
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
      word-break: break-word;
      overflow-wrap: anywhere;
    }}
    .card-title {{
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      margin-bottom: 12px;
      letter-spacing: 0.5px;
    }}
    .stats-row {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 8px;
    }}
    .stats-main {{
      font-size: 20px;
      font-weight: 700;
    }}
    .stats-total {{
      font-size: 14px;
      color: var(--text-muted);
    }}
    .progress-bar {{
      height: 8px;
      background: var(--progress-bg);
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 12px;
    }}
    .progress-fill {{
      height: 100%;
      background: var(--progress-fill);
      border-radius: 4px;
      transition: width 0.3s ease;
    }}
    .meta-row {{
      display: flex;
      justify-content: space-between;
      font-size: 13px;
      color: var(--text-muted);
    }}
    .sub-url-box {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .sub-url-input {{
      flex: 1;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--text);
      font-size: 13px;
      font-family: monospace;
      min-width: 0;
      word-break: break-all;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 8px 16px;
      font-size: 14px;
      font-weight: 500;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--card-bg);
      color: var(--text);
      cursor: pointer;
      text-decoration: none;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
    }}
    .btn:hover {{
      border-color: var(--primary);
      color: var(--primary);
    }}
    .btn-primary {{
      background: var(--primary);
      color: #fff;
      border-color: var(--primary);
    }}
    .btn-primary:hover {{
      background: var(--primary-hover);
      border-color: var(--primary-hover);
      color: #fff;
    }}
    .btn-sm {{
      padding: 4px 10px;
      font-size: 12px;
    }}
    .btn.copied {{
      background: #2e7d32;
      border-color: #2e7d32;
      color: #fff;
    }}
    .qr-box {{
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 12px;
    }}
    .qr-img {{
      max-width: 200px;
      max-height: 200px;
      width: 100%;
      height: auto;
      object-fit: contain;
      border-radius: 8px;
    }}
    .import-buttons {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .import-btn {{
      flex: 1 1 calc(50% - 8px);
      min-width: 120px;
      text-align: center;
    }}
    .links-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .link-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--card-bg);
      gap: 8px;
    }}
    .link-info {{
      display: flex;
      flex-direction: column;
      min-width: 0;
      flex: 1;
    }}
    .link-name {{
      font-size: 14px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .link-proto {{
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
    }}
    .links-empty {{
      color: var(--text-muted);
      font-size: 14px;
      text-align: center;
      padding: 16px;
    }}
  </style>
</head>
<body data-copied-text="{escaped_copied}">
  <div class="container">
    <div class="header">
      <h1>{escaped_title}</h1>
      <span class="status-badge status-{status}">{escaped_status_label}</span>
    </div>

    <div class="card stats-card">
      <div class="card-title">{html.escape(labels["used"])}</div>
      <div class="stats-row">
        <span class="stats-main">{html.escape(used_str)}</span>
        <span class="stats-total">{html.escape(labels["total"])}: {html.escape(total_str)}</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" data-width="{used_percent:.1f}%"></div>
      </div>
      <div class="meta-row">
        <span>{html.escape(labels["expire"])}: {html.escape(expire_str)}</span>
      </div>
    </div>

    <div class="card sub-url-card">
      <div class="card-title">{html.escape(labels["sub_url"])}</div>
      <div class="sub-url-box">
        <input type="text" readonly class="sub-url-input" value="{escaped_sub_url}" spellcheck="false">
        <button type="button" class="btn btn-primary" data-copy="{escaped_sub_url}">{html.escape(labels["copy"])}</button>
      </div>
    </div>

    {qr_section}

    <div class="card import-card">
      <div class="card-title">{html.escape(labels["import_apps"])}</div>
      {import_buttons_html}
    </div>

    <div class="card nodes-card">
      <div class="card-title">{html.escape(labels["nodes"])}</div>
      {links_html}
    </div>
  </div>

  <script nonce="{escaped_nonce}">
    (function() {{
      document.querySelectorAll('[data-width]').forEach(function(el) {{
        el.style.width = el.getAttribute('data-width');
      }});
      document.addEventListener('click', function(e) {{
        var btn = e.target.closest('[data-copy]');
        if (!btn) return;
        var text = btn.getAttribute('data-copy');
        if (!text) return;
        var orig = btn.getAttribute('data-orig-text') || btn.textContent;
        btn.setAttribute('data-orig-text', orig);
        var copiedText = document.body.getAttribute('data-copied-text');
        function feedback() {{
          btn.textContent = copiedText;
          btn.classList.add('copied');
          setTimeout(function() {{
            btn.textContent = orig;
            btn.classList.remove('copied');
          }}, 1500);
        }}
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          navigator.clipboard.writeText(text).then(feedback).catch(function() {{
            fallbackCopy(text, feedback);
          }});
        }} else {{
          fallbackCopy(text, feedback);
        }}
      }});
      function fallbackCopy(text, cb) {{
        try {{
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.focus();
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          if (cb) cb();
        }} catch (err) {{}}
      }}
    }})();
  </script>
</body>
</html>
"""
