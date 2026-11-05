"""Tests for subscription_page module conforming to Stage 2 Contract Section E."""

from __future__ import annotations

import base64
import json
from pathlib import Path
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
    validate_page_section({"theme": ""})
    validate_page_section({"theme": "3xui"})
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


def test_validate_page_section_theme_mask():
    for bad in ("../bad", "theme/dir", "theme space", "theme!", "a" * 65):
        with pytest.raises(ValueError) as exc:
            validate_page_section({"theme": bad})
        assert str(exc.value) == "theme"

    with pytest.raises(ValueError) as exc:
        validate_page_section({"theme": 123})
    assert str(exc.value) == "theme"


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
    assert f'href="flclashx://install-config?url={escaped_sub}"' in html
    assert f'&amp;url={escaped_sub}"' in html
    assert "{{" not in html

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
    # The encrypted link replaces the plain one everywhere, not only on the button.
    assert 'href="happ://add/' not in html_custom_happ
    html_3xui = render_page(
        {},
        {"theme": "3xui"},
        profile={},
        sub_url=sub_url,
        links=[],
        happ_link=custom_happ,
    )
    assert f'href="{custom_happ}"' in html_3xui
    assert 'href="happ://add/' not in html_3xui


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
        {"theme": "3xui"},
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


def test_render_page_localization_russian_and_english():
    html_ru = render_page({"lang": "ru"}, {}, profile={}, sub_url="https://vpn/sub", links=[])
    assert 'lang="ru"' in html_ru
    for label in ("Установка", "Статус", "Срок действия", "Копировать", "Добавить подписку"):
        assert label in html_ru

    html_en = render_page({"lang": "en"}, {}, profile={}, sub_url="https://vpn/sub", links=[])
    assert 'lang="en"' in html_en
    for label in ("Installation", "Status", "Expires", "Copy", "Add Subscription"):
        assert label in html_en
    assert "Добавить подписку" not in html_en


def test_pages_offer_language_switch_and_multi_row_app_tabs():
    for theme in ("remnawave", "3xui"):
        page = render_page({"lang": "en"}, {"theme": theme}, profile={}, sub_url="https://vpn/sub", links=[])
        assert 'href="?html=1&amp;lang=ru" data-lang="ru">RU</a>' in page
        assert 'href="?html=1&amp;lang=en" data-lang="en" class="active"' in page
    query = [("protocol", "vless"), ("nodes", "a,b"), ("view", "html"), ("lang", "en"), ("x", '"><script>')]
    page = render_page({}, {}, profile={}, sub_url="https://vpn/sub", links=[], query=query)
    assert 'href="?protocol=vless&amp;nodes=a%2Cb&amp;x=%22%3E%3Cscript%3E&amp;html=1&amp;lang=en"' in page
    assert "repeat(auto-fill,minmax(126px,1fr))" in page
    assert ".app-tabs{display:flex" not in page


def test_3xui_format_links_keep_subscription_filters():
    page = render_page({}, {"theme": "3xui"}, profile={}, sub_url="https://vpn/sub?protocol=vless", links=[])
    assert 'data-copy="https://vpn/sub?protocol=vless&amp;format=clash"' in page
    page = render_page({}, {"theme": "3xui"}, profile={}, sub_url="https://vpn/sub", links=[])
    assert 'data-copy="https://vpn/sub?format=clash"' in page


def test_catalog_lists_main_apps_first():
    path = Path(__file__).parents[1] / "services" / "subscription_page_apps.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))["platforms"]
    names = {key: [app["name"] for app in platform["apps"]] for key, platform in catalog.items()}
    assert names["android"][:4] == ["Happ", "Incy", "v2rayNG", "V2Box"]
    assert names["androidTV"][:2] == ["Happ", "v2rayNG"]
    assert names["windows"][:2] == ["Happ", "v2rayN"]
    assert names["macos"][:2] == ["Happ", "v2rayN"]
    assert names["linux"][0] == "v2rayN"


def test_remnawave_page_does_not_list_nodes():
    link = "vless://uuid-1@1.1.1.1:443#NL%20Server"
    html = render_page({}, {}, profile={}, sub_url="https://vpn/sub", links=[link])
    assert "uuid-1" not in html
    assert "NL Server" not in html


def test_3xui_page_has_no_3x_badge():
    html = render_page({}, {"theme": "3xui"}, profile={}, sub_url="https://vpn/sub", links=[])
    assert 'class="logo"' not in html
    assert ">3X<" not in html


def test_3xui_page_empty_links_message():
    section = {"theme": "3xui"}
    html_ru = render_page({}, section, profile={}, sub_url="https://vpn/sub", links=[])
    assert "Список узлов пуст" in html_ru
    html_en = render_page({"lang": "en"}, section, profile={}, sub_url="https://vpn/sub", links=[])
    assert "No nodes available" in html_en


def test_render_page_node_parsing_formats():
    # shadowsocks without fragment
    ss_link = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@1.2.3.4:8388"
    html = render_page({}, {"theme": "3xui"}, profile={}, sub_url="https://sub", links=[ss_link])
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


def test_builtin_themes_security_and_fallback():
    for theme in ("remnawave", "3xui", "unknown"):
        page = render_page(
            {"email": '<img src=x onerror=1>', "upload": 1, "download": 2, "total": 10},
            {"theme": theme, "brand_title": '<script>alert(1)</script>'},
            profile={}, sub_url="https://example.com/sub", links=["vless://x#<bad>"], nonce="preview",
        )
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert ' style="' not in page
        assert " onerror=\"" not in page
        assert "<style nonce=\"preview\">" in page
        assert "<script nonce=\"preview\">" in page
        assert "<script>alert" not in page


def test_3xui_apps_tab_shows_app_names():
    html = render_page({}, {"theme": "3xui"}, profile={}, sub_url="https://vpn/sub", links=[])
    assert '<span>Happ</span>' in html


def test_active_status_label_is_translated():
    for theme in ("remnawave", "3xui"):
        section = {"theme": theme}
        html_en = render_page({"lang": "en"}, section, profile={}, sub_url="https://vpn/sub", links=[])
        assert ">Active<" in html_en
        html_ru = render_page({"lang": "ru"}, section, profile={}, sub_url="https://vpn/sub", links=[])
        assert ">Активна<" in html_ru
