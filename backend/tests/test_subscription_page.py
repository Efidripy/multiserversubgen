"""Tests for subscription_page module conforming to Stage 2 Contract Section E."""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import quote

import pytest

from services.subscription_page import (
    page_headers,
    render_page,
    validate_page_section,
    wants_page,
)


def test_validate_page_section_valid_cases():
    validate_page_section({})
    validate_page_section({"enabled": True})
    validate_page_section({"enabled": False, "brand_title": "My Service"})
    validate_page_section({"theme_dir": ""})
    validate_page_section({"theme_dir": "theme-1_dark"})
    validate_page_section({"profile_mode": ""})
    validate_page_section({"profile_mode": "builtin"})
    validate_page_section({
        "profile_mode": "custom",
        "profile_url": "https://example.com/profile",
    })
    validate_page_section({
        "profile_mode": "custom",
        "profile_url": "http://custom.local:8080/path?key=val",
    })


def test_validate_page_section_theme_dir_mask():
    for bad in ("../bad", "theme/dir", "theme space", "theme!", "a" * 65):
        with pytest.raises(ValueError) as exc:
            validate_page_section({"theme_dir": bad})
        assert str(exc.value) == "theme_dir"

    with pytest.raises(ValueError) as exc:
        validate_page_section({"theme_dir": 123})
    assert str(exc.value) == "theme_dir"


def test_validate_page_section_profile_mode_and_url():
    with pytest.raises(ValueError) as exc:
        validate_page_section({"profile_mode": "other"})
    assert str(exc.value) == "profile_mode"

    # custom requires http(s) profile_url
    with pytest.raises(ValueError) as exc:
        validate_page_section({"profile_mode": "custom", "profile_url": ""})
    assert str(exc.value) == "profile_url"

    with pytest.raises(ValueError) as exc:
        validate_page_section({"profile_mode": "custom"})
    assert str(exc.value) == "profile_url"

    with pytest.raises(ValueError) as exc:
        validate_page_section({
            "profile_mode": "custom",
            "profile_url": "ftp://example.com/file",
        })
    assert str(exc.value) == "profile_url"

    with pytest.raises(ValueError) as exc:
        validate_page_section({
            "profile_mode": "custom",
            "profile_url": "tg://resolve?domain=test",
        })
    assert str(exc.value) == "profile_url"

    # Non-custom mode with invalid url format
    with pytest.raises(ValueError) as exc:
        validate_page_section({"profile_mode": "builtin", "profile_url": "not-a-url"})
    assert str(exc.value) == "profile_url"


def test_validate_page_section_types():
    with pytest.raises(ValueError) as exc:
        validate_page_section("not a dict")  # type: ignore[arg-type]
    assert str(exc.value) == "page"

    with pytest.raises(ValueError) as exc:
        validate_page_section({"enabled": "true"})
    assert str(exc.value) == "enabled"

    with pytest.raises(ValueError) as exc:
        validate_page_section({"brand_title": 123})
    assert str(exc.value) == "brand_title"


def test_page_headers_exact_specification():
    headers = page_headers("test-nonce-12345")
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"] == "no-store"

    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "img-src data:" in csp
    assert "style-src 'nonce-test-nonce-12345'" in csp
    assert "script-src 'nonce-test-nonce-12345'" in csp
    assert "base-uri 'none'" in csp
    assert "form-action 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_wants_page_disabled_section():
    # Section disabled always returns False
    assert not wants_page({"Accept": "text/html"}, "?html=1", {}, client_matched=True)
    assert not wants_page({"Accept": "text/html"}, "?html=1", {"enabled": False}, client_matched=True)
    assert not wants_page({"Accept": "text/html"}, "?view=html", {"enabled": False}, client_matched=False)
    assert not wants_page({"Accept": "text/html"}, "", {"enabled": False}, client_matched=False)


def test_wants_page_query_overrides():
    section = {"enabled": True}
    # ?html=1 forces page regardless of client match
    assert wants_page({}, "?html=1", section, client_matched=True)
    assert wants_page({}, "html=1&other=val", section, client_matched=False)
    assert wants_page({}, {"html": "1"}, section, client_matched=True)
    assert wants_page({}, {"html": 1}, section, client_matched=False)

    # ?view=html forces page regardless of client match
    assert wants_page({}, "?view=html", section, client_matched=True)
    assert wants_page({}, "?view=HTML", section, client_matched=False)
    assert wants_page({}, {"view": "html"}, section, client_matched=True)


def test_wants_page_unmatched_client_and_accept_header():
    section = {"enabled": True}

    # client_matched=False, no format, Accept contains text/html -> True
    headers = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    assert wants_page(headers, "", section, client_matched=False)
    assert wants_page(headers, {}, section, client_matched=False)

    # Case-insensitive headers and list of tuples
    assert wants_page({"accept": "text/html"}, "", section, client_matched=False)
    assert wants_page([("Accept", "text/html")], "", section, client_matched=False)

    # Format parameter present -> False
    assert not wants_page(headers, "?format=base64", section, client_matched=False)
    assert not wants_page(headers, {"format": "clash"}, section, client_matched=False)

    # Empty format parameter -> behaves as no format requested
    assert wants_page(headers, "?format=", section, client_matched=False)

    # Accept does not contain text/html -> False
    assert not wants_page({"Accept": "application/json"}, "", section, client_matched=False)
    assert not wants_page({"Accept": "*/*"}, "", section, client_matched=False)
    assert not wants_page({}, "", section, client_matched=False)

    # client_matched=True without explicit html/view query -> False
    assert not wants_page(headers, "", section, client_matched=True)


def test_render_page_title_resolution():
    sub_url = "https://vpn.example.com/sub/token123"

    # 1. brand_title takes precedence
    html1 = render_page(
        {},
        {"brand_title": "Brand VPN"},
        profile={"title": "Profile VPN"},
        sub_url=sub_url,
        links=[],
    )
    assert "<title>Brand VPN</title>" in html1
    assert "<h1>Brand VPN</h1>" in html1

    # 2. profile.title takes precedence if brand_title is empty
    html2 = render_page(
        {},
        {"brand_title": ""},
        profile={"title": "Profile VPN"},
        sub_url=sub_url,
        links=[],
    )
    assert "<title>Profile VPN</title>" in html2
    assert "<h1>Profile VPN</h1>" in html2

    # 3. Default "Subscription" when both empty
    html3 = render_page(
        {},
        {},
        profile={},
        sub_url=sub_url,
        links=[],
    )
    assert "<title>Subscription</title>" in html3
    assert "<h1>Subscription</h1>" in html3

    # XSS in title is escaped
    html_xss = render_page(
        {},
        {"brand_title": "<script>alert(1)</script>"},
        profile={},
        sub_url=sub_url,
        links=[],
    )
    assert "<script>alert(1)</script>" not in html_xss
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_xss


def test_render_page_traffic_progress_and_expiry():
    ctx = {
        "upload": 512 * 1024 * 1024,
        "download": 1024 * 1024 * 1024,  # total used = 1.5 GB
        "total": 10 * 1024 * 1024 * 1024,  # total = 10 GB
        "expire": 1900000000,
        "now": 1800000000,
        "lang": "en",
    }
    rendered = render_page(
        ctx,
        {},
        profile={},
        sub_url="https://vpn.example.com/sub/token",
        links=[],
    )
    assert "1.5 GB" in rendered
    assert "10 GB" in rendered
    assert 'data-width="15.0%"' in rendered

    # Unlimited traffic & zero expire
    ctx_unlimited = {
        "upload": 100 * 1024 * 1024,
        "download": 200 * 1024 * 1024,
        "total": 0,
        "expire": 0,
    }
    rendered_unlimited = render_page(
        ctx_unlimited,
        {},
        profile={},
        sub_url="https://vpn.example.com/sub/token",
        links=[],
    )
    assert "300 MB" in rendered_unlimited
    assert "∞" in rendered_unlimited


def test_render_page_statuses():
    # Active
    active_ctx = {
        "upload": 10,
        "download": 10,
        "total": 100,
        "expire": 2000,
        "now": 1000,
        "lang": "ru",
    }
    active_html = render_page(active_ctx, {}, profile={}, sub_url="https://example.com", links=[])
    assert "status-active" in active_html
    assert "Активна" in active_html

    # Expired
    expired_ctx = {
        "upload": 10,
        "download": 10,
        "total": 100,
        "expire": 1000,
        "now": 2000,
        "lang": "ru",
    }
    expired_html = render_page(expired_ctx, {}, profile={}, sub_url="https://example.com", links=[])
    assert "status-expired" in expired_html
    assert "Истекла" in expired_html

    # Depleted
    depleted_ctx = {
        "upload": 50,
        "download": 50,
        "total": 100,
        "expire": 3000,
        "now": 2000,
        "lang": "ru",
    }
    depleted_html = render_page(depleted_ctx, {}, profile={}, sub_url="https://example.com", links=[])
    assert "status-depleted" in depleted_html
    assert "Лимит исчерпан" in depleted_html


def test_render_page_import_buttons():
    sub_url = "https://vpn.example.com/sub/tok?test=1&foo=bar"

    html = render_page(
        {},
        {},
        profile={"title": "My Config"},
        sub_url=sub_url,
        links=[],
    )
    escaped_sub = quote(sub_url, safe="")
    assert 'href="happ://add/https://vpn.example.com/sub/tok?test=1&amp;foo=bar"' in html
    assert 'href="incy://import/https://vpn.example.com/sub/tok?test=1&amp;foo=bar"' in html
    assert f'href="clash://install-config?url={escaped_sub}"' in html
    assert f'href="sing-box://import-remote-profile?url={escaped_sub}#My%20Config"' in html
    assert f'href="v2rayng://install-config?url={escaped_sub}"' in html

    # With custom happ_link
    custom_happ = "happ://crypt5/abc123xyz"
    html_custom_happ = render_page(
        {},
        {},
        profile={},
        sub_url=sub_url,
        links=[],
        happ_link=custom_happ,
    )
    assert f'href="{custom_happ}"' in html_custom_happ


def test_render_page_links_list_and_copy():
    # vmess encoded
    vmess_dict = {"v": "2", "ps": "Vmess Frankfurt", "add": "1.2.3.4", "port": "443"}
    vmess_b64 = base64.b64encode(json.dumps(vmess_dict).encode()).decode()
    vmess_link = f"vmess://{vmess_b64}"

    vless_link = "vless://uuid-1@1.1.1.1:443?security=reality#NL%20Server"
    trojan_link = "trojan://pass@2.2.2.2:443#Trojan%20US"

    links = [vless_link, trojan_link, vmess_link]
    html = render_page(
        {},
        {},
        profile={},
        sub_url="https://vpn.example.com/sub",
        links=links,
    )

    assert "NL Server" in html
    assert "VLESS" in html
    assert "Trojan US" in html
    assert "TROJAN" in html
    assert "Vmess Frankfurt" in html
    assert "VMESS" in html

    # Verify data-copy attribute contains exact link
    for link in links:
        assert f'data-copy="{link}"' in html


def test_render_page_security_offline_and_data_attributes():
    nonce = "safe-random-nonce-xyz"
    sub_url = "https://vpn.example.com/sub/token"
    qr_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="

    html = render_page(
        {},
        {},
        profile={},
        sub_url=sub_url,
        links=[],
        qr_data_url=qr_data,
        nonce=nonce,
    )

    # Style and Script have nonce
    assert f'<style nonce="{nonce}">' in html
    assert f'<script nonce="{nonce}">' in html

    # QR image rendered with data URL
    assert f'<img src="{qr_data}"' in html

    # Script tag does NOT interpolate user data directly
    script_part = html.split("<script")[1].split("</script>")[0]
    assert sub_url not in script_part
    assert "getAttribute('data-copy')" in script_part

    # Offline check: no external CDN scripts, stylesheets or web fonts
    assert "http://" not in html.split("<style")[0]
    assert "https://" not in html.split("<style")[0]


def test_render_page_theme_replacements(tmp_path):
    themes_root = str(tmp_path / "themes")
    theme_dir_path = os.path.join(themes_root, "custom_dark")
    os.makedirs(theme_dir_path, exist_ok=True)

    template = (
        "<html><head><style nonce=\"{{NONCE}}\"></style></head>"
        "<body>{{TITLE}}|{{SUB_URL}}|{{USED}}|{{TOTAL}}|{{EXPIRE}}|{{STATUS}}|{{QR}}|"
        "{{LINKS_HTML}}|{{IMPORT_BUTTONS_HTML}}</body></html>"
    )
    with open(os.path.join(theme_dir_path, "page.html"), "w", encoding="utf-8") as f:
        f.write(template)

    ctx = {
        "upload": 1024 * 1024,
        "download": 2 * 1024 * 1024,
        "total": 100 * 1024 * 1024,
        "expire": 1762281600,
        "now": 1700000000,
    }
    rendered = render_page(
        ctx,
        {"theme_dir": "custom_dark"},
        profile={"title": "Custom Title"},
        sub_url="https://vpn.example.com/sub/tok",
        links=["vless://test#Node%201"],
        qr_data_url="data:image/png;base64,123",
        themes_root=themes_root,
        nonce="my-nonce",
    )

    assert "Custom Title" in rendered
    assert "https://vpn.example.com/sub/tok" in rendered
    assert "3 MB" in rendered
    assert "100 MB" in rendered
    assert "active" in rendered
    assert "data:image/png;base64,123" in rendered
    assert "my-nonce" in rendered
    assert 'class="links-list"' in rendered
    assert 'class="import-buttons"' in rendered


def test_render_page_theme_fallbacks(tmp_path):
    themes_root = str(tmp_path / "themes")
    os.makedirs(themes_root, exist_ok=True)

    # 1. Missing themes_root
    h1 = render_page({}, {"theme_dir": "any"}, profile={}, sub_url="https://sub", links=[], themes_root=None)
    assert "<!DOCTYPE html>" in h1

    # 2. Non-existent theme_dir
    h2 = render_page({}, {"theme_dir": "non_existent"}, profile={}, sub_url="https://sub", links=[], themes_root=themes_root)
    assert "<!DOCTYPE html>" in h2

    # 3. Missing page.html inside theme_dir
    empty_theme = os.path.join(themes_root, "empty_theme")
    os.makedirs(empty_theme, exist_ok=True)
    h3 = render_page({}, {"theme_dir": "empty_theme"}, profile={}, sub_url="https://sub", links=[], themes_root=themes_root)
    assert "<!DOCTYPE html>" in h3

    # 4. File too large (> 256 KB)
    huge_theme = os.path.join(themes_root, "huge_theme")
    os.makedirs(huge_theme, exist_ok=True)
    with open(os.path.join(huge_theme, "page.html"), "w", encoding="utf-8") as f:
        f.write("A" * (257 * 1024))
    h4 = render_page({}, {"theme_dir": "huge_theme"}, profile={}, sub_url="https://sub", links=[], themes_root=themes_root)
    assert "<!DOCTYPE html>" in h4

    # 5. Invalid theme_dir regex (traversal attempt)
    h5 = render_page({}, {"theme_dir": "../evil"}, profile={}, sub_url="https://sub", links=[], themes_root=themes_root)
    assert "<!DOCTYPE html>" in h5

    # 6. Symlink escaping themes_root
    outside_dir = str(tmp_path / "outside")
    os.makedirs(outside_dir, exist_ok=True)
    with open(os.path.join(outside_dir, "page.html"), "w", encoding="utf-8") as f:
        f.write("OUTSIDE PAGE")
    symlink_target = os.path.join(themes_root, "sym_theme")
    try:
        os.symlink(outside_dir, symlink_target)
        h6 = render_page({}, {"theme_dir": "sym_theme"}, profile={}, sub_url="https://sub", links=[], themes_root=themes_root)
        assert "<!DOCTYPE html>" in h6
        assert "OUTSIDE PAGE" not in h6
    except (OSError, NotImplementedError):
        pass


def test_render_page_localization_russian_and_english():
    ctx_ru = {"lang": "ru"}
    html_ru = render_page(ctx_ru, {}, profile={}, sub_url="https://vpn/sub", links=[])
    assert 'lang="ru"' in html_ru
    assert "Использовано" in html_ru
    assert "Всего" in html_ru
    assert "Срок действия" in html_ru
    assert "Адрес подписки" in html_ru
    assert "Копировать" in html_ru
    assert "Список узлов" in html_ru

    ctx_en = {"lang": "en"}
    html_en = render_page(ctx_en, {}, profile={}, sub_url="https://vpn/sub", links=[])
    assert 'lang="en"' in html_en
    assert "Used" in html_en
    assert "Total" in html_en
    assert "Expires" in html_en
    assert "Subscription URL" in html_en
    assert "Copy" in html_en
    assert "Server Nodes" in html_en


def test_render_page_empty_links_message():
    html_empty = render_page({}, {}, profile={}, sub_url="https://vpn/sub", links=[])
    assert "Список узлов пуст" in html_empty
    assert "links-empty" in html_empty

    html_empty_en = render_page({"lang": "en"}, {}, profile={}, sub_url="https://vpn/sub", links=[])
    assert "No nodes available" in html_empty_en


def test_render_page_node_parsing_formats():
    # shadowsocks without fragment
    ss_link = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@1.2.3.4:8388"
    html = render_page({}, {}, profile={}, sub_url="https://sub", links=[ss_link])
    assert "SS #1" in html
    assert "SS" in html


def test_render_page_expire_timestamp_in_milliseconds():
    # Timestamp in milliseconds (> 1e11)
    ms_timestamp = 1762281600000
    ctx = {"expire": ms_timestamp}
    html = render_page(ctx, {}, profile={}, sub_url="https://sub", links=[])
    assert "2025-11-04" in html


def test_builtin_page_has_no_inline_style_attributes_blocked_by_csp():
    page = render_page(
        {"upload": 1, "download": 1, "total": 4, "expire": 0},
        {},
        profile={},
        sub_url="https://example.com/s",
        links=[],
        nonce="n",
    )
    assert ' style="' not in page
    assert 'data-width="50.0%"' in page


def test_theme_substitution_does_not_expand_tokens_inside_values(tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "page.html").write_text("{{TITLE}}|{{NONCE}}", encoding="utf-8")
    page = render_page(
        {},
        {"theme_dir": "t", "brand_title": "{{NONCE}}"},
        profile={},
        sub_url="https://example.com/s",
        links=[],
        themes_root=str(tmp_path),
        nonce="secret-nonce",
    )
    assert page == "{{NONCE}}|secret-nonce"
