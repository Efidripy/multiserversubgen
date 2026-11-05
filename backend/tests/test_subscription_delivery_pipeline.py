import base64
import json
import os
import sys
import urllib.parse
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.auth.service import AuthService  # noqa: E402
from routers import subscriptions as subscriptions_module  # noqa: E402
from routers.subscriptions import build_subscriptions_router  # noqa: E402
from services.db_bootstrap import init_db  # noqa: E402
from services.subscription_client_settings import default_settings  # noqa: E402
from services.subscription_tokens import ensure_tokens  # noqa: E402

EMAIL = "user@example.com"
VLESS = "vless://11111111-1111-1111-1111-111111111111@node.example:443?encryption=none&type=tcp#Node"
TROJAN = "trojan://secret@node.example:443?security=tls&type=tcp#Node"


class NodeService:
    def list_nodes(self):
        return [{"id": 1, "name": "Node", "ip": "node.example"}]


@pytest.fixture
def env(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with subscriptions_module.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)",
            ("Group", "group", json.dumps([EMAIL]), ""),
        )
        conn.commit()
    state = SimpleNamespace(links=[VLESS, TROJAN], user="admin", db_path=db_path)
    app = FastAPI()
    app.include_router(
        build_subscriptions_router(
            check_auth=lambda _request: state.user,
            db_path=db_path,
            node_service=NodeService(),
            check_subscription_rate_limit=lambda _request, _key: (True, 0),
            get_emails=lambda _nodes: [EMAIL],
            get_links_filtered=lambda nodes, _email, _protocol=None: (
                list(state.links) if any(node.get("name") == "Node" for node in nodes) else []
            ),
            get_subscription_userinfo=lambda _nodes, _emails: getattr(
                state, "userinfo", {"upload": 1, "download": 2, "total": 3, "expire": 4}
            ),
            subscription_signing_secret="test-secret",
            invalidate_subscription_cache=lambda: None,
            logger=None,
        )
    )
    state.client = TestClient(app)
    state.email_token = ensure_tokens(db_path, "email", [EMAIL])[EMAIL]
    state.group_token = ensure_tokens(db_path, "group", ["group"])["group"]
    return state


def configure(env, client_id, **fields):
    settings = default_settings()
    client = next(item for item in settings["clients"] if item["id"] == client_id)
    client.update({"enabled": True, **fields})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    return settings


def sub(env, user_agent="", **params):
    return env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": user_agent}, params=params)


def sub_grouped(env, user_agent="", **params):
    return env.client.get(f"/api/v1/sub-grouped/{env.group_token}", headers={"User-Agent": user_agent}, params=params)


def _rules(settings, rules):
    settings["response_rules"]["rules"] = json.dumps(rules)
    return settings


@pytest.mark.parametrize("response,status", [("block", 403), ("not_found", 404), ("unavailable", 451)])
def test_response_rule_statuses_are_applied_before_delivery(env, response, status):
    settings = _rules(default_settings(), [{"name": response, "response": response, "conditions": []}])
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    result = sub(env, "curl/1")
    assert result.status_code == status


def test_query_format_has_priority_over_response_rule(env):
    settings = _rules(default_settings(), [{"name": "yaml", "response": "mihomo", "conditions": []}])
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    result = sub(env, "curl/1", format="singbox")
    assert result.headers["content-type"].startswith("application/json")


def test_xray_json_query_and_client_format_are_json(env):
    result = sub(env, "curl/1", format="xray_json")
    assert result.status_code == 200
    payload = json.loads(result.text)
    assert (payload[0] if isinstance(payload, list) else payload)["outbounds"]
    configure(env, "singbox", format="xray_json")
    result = sub(env, "SFA/1")
    assert result.headers["content-type"].startswith("application/json")


def test_encode_false_returns_plain_subscription_text(env):
    settings = default_settings()
    settings["content"]["encode"] = False
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    result = sub(env, "curl/1")
    assert result.content.startswith(b"vless://")


def test_test_endpoint_returns_rule_and_response_without_legacy_alias(env):
    settings = _rules(default_settings(), [{"name": "r", "response": "mihomo", "conditions": []}])
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    result = env.client.post(
        "/api/v1/subscription-client-settings/test",
        json={"user_agent": "curl/1", "headers": {"X-Test": "yes"}},
    )
    assert result.status_code == 200
    assert result.json()["rule"] == "r"
    assert result.json()["response"] == "mihomo"
    assert "rule_name" not in result.json()


def test_devices_api_requires_auth_and_hides_hwid(env):
    env.user = None
    assert env.client.get("/api/v1/subscription-client-settings/devices").status_code == 401
    env.user = "admin"
    result = env.client.get("/api/v1/subscription-client-settings/devices")
    assert result.status_code == 200
    assert all("hwid_hash" not in item for item in result.json()["devices"])


def test_devices_api_returns_app_field_and_hides_hwid(env):
    env.user = "admin"
    settings = default_settings()
    settings["devices"].update({"enabled": True, "max_devices": 5})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    # 1. Device with Happ User-Agent
    r1 = env.client.get(
        f"/api/v1/sub/{env.email_token}",
        headers={"User-Agent": "Happ/3.6.1 (iPhone 15; iOS 18.0)", "X-HWID": "hwid-happ"},
    )
    assert r1.status_code == 200

    # 2. Device with curl User-Agent (unknown client)
    r2 = env.client.get(
        f"/api/v1/sub/{env.email_token}",
        headers={"User-Agent": "curl/8.1.2", "X-HWID": "hwid-curl"},
    )
    assert r2.status_code == 200

    # 3. Device with empty User-Agent
    r3 = env.client.get(
        f"/api/v1/sub/{env.email_token}",
        headers={"User-Agent": "", "X-HWID": "hwid-empty"},
    )
    assert r3.status_code == 200

    res = env.client.get("/api/v1/subscription-client-settings/devices")
    assert res.status_code == 200
    devices = res.json()["devices"]
    assert len(devices) >= 3

    # Check app and user_agent fields, and verify HWID is never returned
    dev_happ = next(d for d in devices if d.get("user_agent") == "Happ/3.6.1 (iPhone 15; iOS 18.0)")
    assert dev_happ["app"] == "Happ"

    dev_curl = next(d for d in devices if d.get("user_agent") == "curl/8.1.2")
    assert dev_curl["app"] == "curl"

    dev_empty = next(d for d in devices if d.get("user_agent") == "")
    assert dev_empty["app"] == ""

    for d in devices:
        assert "hwid" not in d
        assert "hwid_hash" not in d
        assert "app" in d
        assert "user_agent" in d


def test_devices_api_returns_max_devices_when_enabled_and_disabled(env):
    env.user = "admin"
    settings = default_settings()

    # Enabled with limit
    settings["devices"].update({"enabled": True, "max_devices": 3})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res = env.client.get("/api/v1/subscription-client-settings/devices")
    assert res.status_code == 200
    assert res.json()["max_devices"] == 3

    # Disabled -> returns 0 even though max_devices is 3 in settings
    settings["devices"]["enabled"] = False
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_disabled = env.client.get("/api/v1/subscription-client-settings/devices")
    assert res_disabled.status_code == 200
    assert res_disabled.json()["max_devices"] == 0


def test_default_delivery_bytes_remain_base64(env):
    result = sub(env, "curl/1")
    assert result.content == base64.b64encode((env.links[0] + "\n" + env.links[1]).encode())


def test_html_accept_returns_csp_page_and_happ_client_stays_subscription(env):
    settings = default_settings()
    settings["page"]["enabled"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    page = sub(env, "curl/1", html="1")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "content-security-policy" in page.headers
    assert sub(env, "Happ/1").headers["content-type"].startswith("text/plain")


def test_page_subscription_url_is_public_address_behind_nginx(env):
    settings = default_settings()
    settings["page"]["enabled"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    env.client.app.root_path = "/panel"
    page = env.client.get(
        f"/api/v1/sub/{env.email_token}",
        headers={"Host": "panel.example", "X-Forwarded-Proto": "https", "User-Agent": "curl/1"},
        params={"html": "1"},
    )
    assert page.status_code == 200
    assert f"https://panel.example/panel/api/v1/sub/{env.email_token}" in page.text


def test_excluded_node_is_removed_before_link_generation(env):
    settings = _rules(
        default_settings(),
        [{"name": "exclude", "response": "default", "conditions": [], "modifications": {"exclude_nodes": ["Node"]}}],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    assert sub(env, "curl/1").status_code == 404


def test_skip_device_limit_does_not_create_device_record(env):
    settings = default_settings()
    settings["devices"].update({"enabled": True, "max_devices": 1})
    settings = _rules(
        settings,
        [{"name": "skip", "response": "default", "conditions": [], "modifications": {"skip_device_limit": True}}],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    assert (
        env.client.get(
            f"/api/v1/sub/{env.email_token}",
            headers={"User-Agent": "curl/1", "X-HWID": "ignored"},
        ).status_code
        == 200
    )
    assert env.client.get("/api/v1/subscription-client-settings/devices").json()["devices"] == []


# 1. Отказ правила (block) и отказ устройства не увеличивают счётчик в таблице stats: и в /sub, и в /sub-grouped.
def test_stats_not_incremented_on_block_rule_or_device_failure(env):
    env.userinfo = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    res_init = sub(env, "curl/1")
    assert res_init.status_code == 200
    with subscriptions_module.connect(env.db_path) as conn:
        count_base = conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0]
    assert count_base >= 1

    # Block rule in /sub
    settings = _rules(
        default_settings(),
        [{"name": "block", "response": "block", "conditions": [{"header": "User-Agent", "op": "contains", "value": "block-ua"}]}],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_block = sub(env, "block-ua")
    assert res_block.status_code == 403
    with subscriptions_module.connect(env.db_path) as conn:
        assert conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0] == count_base

    # Device rejection in /sub
    settings = default_settings()
    settings["devices"].update({"enabled": True, "max_devices": 1})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_dev1 = env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": "curl/1", "X-HWID": "dev-sub-1"})
    assert res_dev1.status_code == 200
    with subscriptions_module.connect(env.db_path) as conn:
        count_after_dev1 = conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0]
    assert count_after_dev1 == count_base + 1

    res_dev2 = env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": "curl/1", "X-HWID": "dev-sub-2"})
    assert res_dev2.status_code == 404
    with subscriptions_module.connect(env.db_path) as conn:
        assert conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0] == count_after_dev1

    # Block rule in /sub-grouped
    settings["devices"]["enabled"] = False
    settings = _rules(
        settings,
        [{"name": "block", "response": "block", "conditions": [{"header": "User-Agent", "op": "contains", "value": "block-ua"}]}],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_grp_block = sub_grouped(env, "block-ua")
    assert res_grp_block.status_code == 403
    with subscriptions_module.connect(env.db_path) as conn:
        assert conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0] == count_after_dev1

    # Device rejection in /sub-grouped
    settings["response_rules"]["rules"] = "[]"
    settings["devices"]["enabled"] = True
    settings["devices"]["max_devices"] = 1
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_grp_dev1 = env.client.get(
        f"/api/v1/sub-grouped/{env.group_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "dev-grp-1"},
    )
    assert res_grp_dev1.status_code == 200
    with subscriptions_module.connect(env.db_path) as conn:
        count_after_grp_dev1 = conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0]
    assert count_after_grp_dev1 == count_after_dev1 + 1

    res_grp_dev2 = env.client.get(
        f"/api/v1/sub-grouped/{env.group_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "dev-grp-2"},
    )
    assert res_grp_dev2.status_code == 404
    with subscriptions_module.connect(env.db_path) as conn:
        assert conn.execute("SELECT count FROM stats WHERE email = ?", (EMAIL,)).fetchone()[0] == count_after_grp_dev1


# 2. Лимит устройств: новое устройство сверх лимита → 404 с X-Hwid-Max-Devices-Reached; известное проходит; то же при попадании в кэш sub-grouped (X-Subscription-Cache: hit).
def test_device_limit_blocks_new_device_and_passes_known_on_sub_and_sub_grouped_cache(env):
    settings = default_settings()
    settings["devices"].update({"enabled": True, "max_devices": 1})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    # /sub
    res_new1 = env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": "curl/1", "X-HWID": "hwid-known"})
    assert res_new1.status_code == 200
    res_limit = env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": "curl/1", "X-HWID": "hwid-unknown"})
    assert res_limit.status_code == 404
    assert res_limit.headers.get("x-hwid-max-devices-reached") == "true"
    res_known = env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": "curl/1", "X-HWID": "hwid-known"})
    assert res_known.status_code == 200

    # /sub-grouped
    res_g_miss = env.client.get(
        f"/api/v1/sub-grouped/{env.group_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "hwid-g-known"},
    )
    assert res_g_miss.status_code == 200
    assert res_g_miss.headers.get("x-subscription-cache") == "miss"

    res_g_hit = env.client.get(
        f"/api/v1/sub-grouped/{env.group_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "hwid-g-known"},
    )
    assert res_g_hit.status_code == 200
    assert res_g_hit.headers.get("x-subscription-cache") == "hit"

    res_g_limit = env.client.get(
        f"/api/v1/sub-grouped/{env.group_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "hwid-g-unknown"},
    )
    assert res_g_limit.status_code == 404
    assert res_g_limit.headers.get("x-hwid-max-devices-reached") == "true"

    res_g_hit2 = env.client.get(
        f"/api/v1/sub-grouped/{env.group_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "hwid-g-known"},
    )
    assert res_g_hit2.status_code == 200
    assert res_g_hit2.headers.get("x-subscription-cache") == "hit"


# 3. Правило меняет формат (mihomo → разбираемый YAML); ?format= важнее правила; кэш sub-grouped не отдаёт ответ одного правила другому.
def test_rule_changes_format_and_query_overrides_and_cache_isolated_between_rules(env):
    settings = _rules(
        default_settings(),
        [
            {"name": "rule-mihomo", "response": "mihomo", "conditions": [{"header": "X-Client", "op": "equals", "value": "r1"}]},
            {"name": "rule-singbox", "response": "singbox", "conditions": [{"header": "X-Client", "op": "equals", "value": "r2"}]},
        ],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    # 1. Rule changes format (mihomo -> parsed YAML)
    res_yaml = env.client.get(f"/api/v1/sub-grouped/{env.group_token}", headers={"X-Client": "r1"})
    assert res_yaml.status_code == 200
    doc = yaml.safe_load(res_yaml.text)
    assert isinstance(doc, dict)
    assert "proxies" in doc
    assert res_yaml.headers.get("x-subscription-cache") == "miss"

    # 2. ?format= takes precedence over rule
    res_override = env.client.get(f"/api/v1/sub-grouped/{env.group_token}?format=singbox", headers={"X-Client": "r1"})
    assert res_override.status_code == 200
    doc_json = json.loads(res_override.text)
    assert "outbounds" in doc_json

    # 3. Cache of sub-grouped does not give rule1's response to rule2
    res_yaml_hit = env.client.get(f"/api/v1/sub-grouped/{env.group_token}", headers={"X-Client": "r1"})
    assert res_yaml_hit.status_code == 200
    assert res_yaml_hit.headers.get("x-subscription-cache") == "hit"
    assert "proxies" in yaml.safe_load(res_yaml_hit.text)

    res_singbox_miss = env.client.get(f"/api/v1/sub-grouped/{env.group_token}", headers={"X-Client": "r2"})
    assert res_singbox_miss.status_code == 200
    assert res_singbox_miss.headers.get("x-subscription-cache") == "miss"
    assert "outbounds" in json.loads(res_singbox_miss.text)


# 4. Страница: ?html=1 → text/html с CSP; при выключенной секции ?html=1 не даёт страницу; ответ правила page при выключенной секции даёт обычный ответ; profile_mode custom → 302 на profile_url; страница и отказы не попадают в кэш sub-grouped.
def test_html_delivery_restrictions_custom_redirect_and_cache_exclusion(env):
    # 1. ?html=1 -> text/html with CSP
    settings = default_settings()
    settings["page"]["enabled"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    page_res = sub(env, "curl/1", html="1")
    assert page_res.status_code == 200
    assert page_res.headers["content-type"].startswith("text/html")
    assert "content-security-policy" in page_res.headers
    assert 'lang="en"' in sub(env, "curl/1", html="1", lang="en").text
    assert 'lang="ru"' in sub(env, "curl/1", html="1", lang="ru").text
    filtered_page = sub(env, "curl/1", html="1", protocol="vless", lang="ru").text
    assert 'href="?protocol=vless&amp;html=1&amp;lang=en"' in filtered_page
    assert "protocol%3Dvless" in filtered_page
    assert "lang%3D" not in filtered_page and "html%3D" not in filtered_page

    # 2. When page section disabled, ?html=1 does not give page
    settings["page"]["enabled"] = False
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    plain_res = sub(env, "curl/1", html="1")
    assert plain_res.status_code == 200
    assert not plain_res.headers["content-type"].startswith("text/html")

    # 3. Rule response 'page' when section disabled gives ordinary response
    settings = _rules(settings, [{"name": "page-resp", "response": "page", "conditions": []}])
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    rule_page_disabled = sub(env, "curl/1")
    assert rule_page_disabled.status_code == 200
    assert not rule_page_disabled.headers["content-type"].startswith("text/html")

    # 4. profile_mode custom -> 302 on profile_url
    settings = default_settings()
    settings["page"]["enabled"] = True
    settings["page"]["profile_mode"] = "custom"
    settings["page"]["profile_url"] = "https://custom.example.com/profile"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    redirect_res = env.client.get(f"/api/v1/sub/{env.email_token}?html=1", follow_redirects=False)
    assert redirect_res.status_code == 302
    assert redirect_res.headers["location"] == "https://custom.example.com/profile"

    # 5. Page and rejections do not get cached in sub-grouped
    settings["page"]["profile_mode"] = "builtin"
    settings["page"]["profile_url"] = ""
    settings["page"]["enabled"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    g_page1 = env.client.get(f"/api/v1/sub-grouped/{env.group_token}?html=1")
    assert g_page1.status_code == 200
    assert g_page1.headers["content-type"].startswith("text/html")
    g_page2 = env.client.get(f"/api/v1/sub-grouped/{env.group_token}?html=1")
    assert g_page2.headers.get("x-subscription-cache") != "hit"

    # Rejections not cached in sub-grouped
    settings["page"]["enabled"] = False
    settings = _rules(
        settings,
        [{"name": "block-rule", "response": "block", "conditions": [{"header": "X-Block", "op": "exists"}]}],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    g_block = env.client.get(f"/api/v1/sub-grouped/{env.group_token}", headers={"X-Block": "1"})
    assert g_block.status_code == 403
    g_normal = env.client.get(f"/api/v1/sub-grouped/{env.group_token}")
    assert g_normal.status_code == 200
    assert g_normal.headers.get("x-subscription-cache") == "miss"


# 5. encryption.happ_links включён: на странице есть happ://crypt5/; выключен: нет.
def test_encryption_happ_links_toggle_on_page(env):
    settings = default_settings()
    settings["page"]["enabled"] = True
    settings["encryption"]["happ_links"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_on = sub(env, "curl/1", html="1")
    assert res_on.status_code == 200
    assert "happ://crypt5/" in res_on.text

    settings["encryption"]["happ_links"] = False
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_off = sub(env, "curl/1", html="1")
    assert res_off.status_code == 200
    assert "happ://crypt5/" not in res_off.text


# 6. remark_template меняет имя в ссылке; {{SUB_ID}} не содержит токен из URL; remark_template правила перекрывает секцию.
def test_remark_template_replaces_name_sub_id_hides_raw_token_and_rule_overrides(env):
    env.userinfo = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    settings = default_settings()
    settings["content"]["remark_template"] = "Custom-{{NODE}}-{{SUB_ID}}"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    res = sub(env, "curl/1")
    assert res.status_code == 200
    decoded = base64.b64decode(res.content).decode()
    assert "#Custom-Node-" in decoded
    assert env.email_token not in decoded

    settings = _rules(
        settings,
        [
            {
                "name": "override-remark",
                "response": "default",
                "conditions": [{"header": "X-Override", "op": "exists"}],
                "modifications": {"remark_template": "Rule-{{NODE}}"},
            }
        ],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    res_override = env.client.get(f"/api/v1/sub/{env.email_token}", headers={"X-Override": "1"})
    assert res_override.status_code == 200
    decoded_override = base64.b64decode(res_override.content).decode()
    assert "#Rule-Node" in decoded_override


# 7. expired_template при истёкшем сроке заменяет весь список одной ссылкой; depleted_template при исчерпанном трафике; info_node первым в base64.
def test_expired_and_depleted_templates_replace_list_and_info_node_placed_first(env):
    settings = default_settings()
    settings["content"]["expired_template"] = "Expired: {{EXPIRE_DATE}}"
    settings["content"]["depleted_template"] = "Depleted: {{TRAFFIC_USED}}"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    # 1. Expired
    env.userinfo = {"upload": 10, "download": 10, "total": 1000, "expire": 10}
    res_exp = sub(env, "curl/1")
    assert res_exp.status_code == 200
    lines_exp = base64.b64decode(res_exp.content).decode().strip().split("\n")
    assert len(lines_exp) == 1
    assert lines_exp[0].startswith("vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1")
    assert "Expired:" in urllib.parse.unquote(lines_exp[0])

    # 2. Depleted
    env.userinfo = {"upload": 600, "download": 500, "total": 1000, "expire": 0}
    res_dep = sub(env, "curl/1")
    assert res_dep.status_code == 200
    lines_dep = base64.b64decode(res_dep.content).decode().strip().split("\n")
    assert len(lines_dep) == 1
    assert lines_dep[0].startswith("vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1")
    assert "Depleted:" in urllib.parse.unquote(lines_dep[0])

    # 3. info_node first in base64
    env.userinfo = {"upload": 10, "download": 10, "total": 1000, "expire": 0}
    settings["content"]["info_node"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_info = sub(env, "curl/1")
    assert res_info.status_code == 200
    lines_info = base64.b64decode(res_info.content).decode().strip().split("\n")
    assert len(lines_info) == len(env.links) + 1
    assert lines_info[0].startswith("vless://00000000-0000-0000-0000-000000000000@127.0.0.1:1")
    assert lines_info[1] == env.links[0]
    assert lines_info[2] == env.links[1]


def test_sub_grouped_cache_bypassed_when_expired_template_status_changes(env):
    settings = default_settings()
    settings["content"]["expired_template"] = "Expired: {{EXPIRE_DATE}}"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    env.userinfo = {"upload": 0, "download": 0, "total": 1000, "expire": 0}
    active = sub_grouped(env, "curl/1")
    assert active.status_code == 200
    assert active.headers.get("x-subscription-cache") == "miss"

    env.userinfo = {"upload": 0, "download": 0, "total": 1000, "expire": 10}
    expired = sub_grouped(env, "curl/1")
    assert expired.status_code == 200
    assert expired.headers.get("x-subscription-cache") == "miss"
    decoded = base64.b64decode(expired.content).decode()
    assert "Expired:" in urllib.parse.unquote(decoded)


def test_sub_grouped_cache_bypassed_when_depleted_template_status_changes(env):
    settings = default_settings()
    settings["content"]["depleted_template"] = "Depleted: {{TRAFFIC_USED}}"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    env.userinfo = {"upload": 0, "download": 0, "total": 1000, "expire": 0}
    active = sub_grouped(env, "curl/1")
    assert active.status_code == 200
    assert active.headers.get("x-subscription-cache") == "miss"

    env.userinfo = {"upload": 600, "download": 500, "total": 1000, "expire": 0}
    depleted = sub_grouped(env, "curl/1")
    assert depleted.status_code == 200
    assert depleted.headers.get("x-subscription-cache") == "miss"
    decoded = base64.b64decode(depleted.content).decode()
    assert "Depleted:" in urllib.parse.unquote(decoded)


def test_sub_grouped_cache_bypassed_when_remark_template_uses_traffic(env):
    settings = default_settings()
    settings["content"]["remark_template"] = "Node-{{TRAFFIC_USED}}"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    env.userinfo = {"upload": 1, "download": 2, "total": 1000, "expire": 0}
    first = sub_grouped(env, "curl/1")
    assert first.status_code == 200
    assert first.headers.get("x-subscription-cache") == "miss"
    first_decoded = base64.b64decode(first.content).decode()
    assert "Node-3%20B" in first_decoded

    env.userinfo = {"upload": 5, "download": 7, "total": 1000, "expire": 0}
    second = sub_grouped(env, "curl/1")
    assert second.status_code == 200
    assert second.headers.get("x-subscription-cache") == "miss"
    second_decoded = base64.b64decode(second.content).decode()
    assert "Node-12%20B" in second_decoded
    assert second_decoded != first_decoded


def test_sub_grouped_cache_hit_without_status_dependent_content(env):
    env.userinfo = {"upload": 0, "download": 0, "total": 1000, "expire": 0}
    first = sub_grouped(env, "curl/1")
    assert first.status_code == 200
    assert first.headers.get("x-subscription-cache") == "miss"

    second = sub_grouped(env, "curl/1")
    assert second.status_code == 200
    assert second.headers.get("x-subscription-cache") == "hit"


# 8. host_order=random вызывает random.shuffle (подмена через monkeypatch на функцию, переворачивающую список); host_order=name сортирует.
def test_host_order_random_calls_shuffle_and_name_sorts_alphabetically(env, monkeypatch):
    env.userinfo = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    link_zulu = "vless://11111111-1111-1111-1111-111111111111@node.example:443?type=tcp#Zulu"
    link_alpha = "trojan://secret@node.example:443?security=tls&type=tcp#Alpha"
    env.links = [link_zulu, link_alpha]

    # host_order = name
    settings = default_settings()
    settings["content"]["host_order"] = "name"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_name = sub(env, "curl/1")
    lines_name = base64.b64decode(res_name.content).decode().strip().split("\n")
    assert "#Alpha" in lines_name[0]
    assert "#Zulu" in lines_name[1]

    # host_order = random calls random.shuffle
    monkeypatch.setattr(subscriptions_module.random, "shuffle", lambda lst: lst.reverse())
    link_first = "vless://11111111-1111-1111-1111-111111111111@node.example:443?type=tcp#First"
    link_second = "trojan://secret@node.example:443?security=tls&type=tcp#Second"
    env.links = [link_first, link_second]
    settings["content"]["host_order"] = "random"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_rand = sub(env, "curl/1")
    lines_rand = base64.b64decode(res_rand.content).decode().strip().split("\n")
    assert "#Second" in lines_rand[0]
    assert "#First" in lines_rand[1]


# 9. encode=false: и при обычном ответе, и при откате на base64 с 0 прокси (формат clash и только vless).
def test_encode_false_returns_plain_text_for_normal_and_clash_vless_fallback(env):
    env.userinfo = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    settings = default_settings()
    settings["content"]["encode"] = False
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    # Normal base64 format with encode=false
    res_norm = sub(env, "curl/1")
    assert res_norm.status_code == 200
    assert res_norm.content.startswith(b"vless://")
    assert res_norm.headers["content-type"].startswith("text/plain")

    # Fallback to base64 with 0 proxies (format=clash and only vless)
    env.links = [VLESS]
    res_clash = sub(env, "curl/1", format="clash")
    assert res_clash.status_code == 200
    assert res_clash.content.startswith(b"vless://")
    assert res_clash.headers["content-type"].startswith("text/plain")


# 10. Токены в Profile-Title при промахе и при попадании в кэш sub-grouped.
def test_profile_title_renders_tokens_on_sub_grouped_cache_miss_and_hit(env):
    env.userinfo = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    settings = default_settings()
    settings["profile"]["title"] = "VPN-{{EMAIL}}-{{SUB_ID}}"
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    res_miss = sub_grouped(env, "curl/1")
    assert res_miss.status_code == 200
    assert res_miss.headers.get("x-subscription-cache") == "miss"
    title_miss = res_miss.headers.get("profile-title")
    assert "VPN-group-" in title_miss
    assert "{{EMAIL}}" not in title_miss
    assert "{{SUB_ID}}" not in title_miss

    res_hit = sub_grouped(env, "curl/1")
    assert res_hit.status_code == 200
    assert res_hit.headers.get("x-subscription-cache") == "hit"
    title_hit = res_hit.headers.get("profile-title")
    assert title_hit == title_miss


# 11. Правила по URL: значение, заранее записанное в таблицу subscription_remote_rules, попадает в заголовок Routing у Happ, в тело у Incy, в rules у Mihomo строками; YAML сливается с rule-providers; dns из YAML появляется только при remote_rules.use_remote_dns; сетевых запросов нет.
def test_remote_rules_delivered_to_happ_routing_incy_body_and_mihomo_yaml(env, monkeypatch):
    env.userinfo = {"upload": 0, "download": 0, "total": 0, "expire": 0}
    happ_url = "https://remote-rules.internal/happ"
    happ_body = "happ://routing/onadd/test-happ-routing"
    incy_url = "https://remote-rules.internal/incy"
    incy_body = "incy_custom_routing_text"
    mihomo_lines_url = "https://remote-rules.internal/mihomo-lines"
    mihomo_lines_body = "DOMAIN,remote.internal,DIRECT\nGEOIP,CN,DIRECT"
    mihomo_yaml_url = "https://remote-rules.internal/mihomo-yaml"
    mihomo_yaml_body = (
        "rules:\n"
        "  - DOMAIN,yaml.internal,DIRECT\n"
        "rule-providers:\n"
        "  remote-provider:\n"
        "    type: http\n"
        "dns:\n"
        "  enable: true\n"
    )

    with subscriptions_module.connect(env.db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS subscription_remote_rules (url TEXT PRIMARY KEY, body TEXT, fetched_at REAL, last_error TEXT, attempted_at REAL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO subscription_remote_rules (url, body, fetched_at) VALUES (?, ?, ?)",
            (happ_url, happ_body, 1000.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO subscription_remote_rules (url, body, fetched_at) VALUES (?, ?, ?)",
            (incy_url, incy_body, 1000.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO subscription_remote_rules (url, body, fetched_at) VALUES (?, ?, ?)",
            (mihomo_lines_url, mihomo_lines_body, 1000.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO subscription_remote_rules (url, body, fetched_at) VALUES (?, ?, ?)",
            (mihomo_yaml_url, mihomo_yaml_body, 1000.0),
        )
        conn.commit()

    # Network guard: no network requests during delivery
    def _forbid_network(*args, **kwargs):
        raise RuntimeError("No network requests allowed during delivery")

    monkeypatch.setattr("urllib.request.urlopen", _forbid_network)

    settings = default_settings()
    incy_client = next(c for c in settings["clients"] if c["id"] == "incy")
    incy_client["enabled"] = True
    incy_client["settings"]["routing_url"] = incy_url

    mihomo_client = next(c for c in settings["clients"] if c["id"] == "mihomo")
    mihomo_client["enabled"] = True
    mihomo_client["settings"]["rules_url"] = mihomo_lines_url

    happ_client = next(c for c in settings["clients"] if c["id"] == "happ")
    happ_client["enabled"] = True
    happ_client["settings"]["routing_url"] = happ_url
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    # Incy: body contains routing
    res_incy = sub(env, "Incy/1")
    assert res_incy.status_code == 200
    decoded_incy = base64.b64decode(res_incy.content).decode()
    assert incy_body in decoded_incy

    # Mihomo: string rules
    res_mihomo = sub(env, "ClashMeta/1")
    assert res_mihomo.status_code == 200
    doc_lines = yaml.safe_load(res_mihomo.text)
    assert "DOMAIN,remote.internal,DIRECT" in doc_lines["rules"]
    assert "GEOIP,CN,DIRECT" in doc_lines["rules"]

    # Mihomo: YAML merge with rule-providers and DNS conditional on remote_rules.use_remote_dns
    mihomo_client["settings"]["rules_url"] = mihomo_yaml_url
    settings["remote_rules"]["use_remote_dns"] = False
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_no_dns = sub(env, "ClashMeta/1")
    doc_no_dns = yaml.safe_load(res_no_dns.text)
    assert "remote-provider" in doc_no_dns.get("rule-providers", {})
    assert "DOMAIN,yaml.internal,DIRECT" in doc_no_dns.get("rules", [])
    assert "dns" not in doc_no_dns

    settings["remote_rules"]["use_remote_dns"] = True
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_dns = sub(env, "ClashMeta/1")
    doc_dns = yaml.safe_load(res_dns.text)
    assert "remote-provider" in doc_dns.get("rule-providers", {})
    assert "DOMAIN,yaml.internal,DIRECT" in doc_dns.get("rules", [])
    assert "dns" in doc_dns
    assert doc_dns["dns"].get("enable") is True

    # Happ: routing header
    res_happ = sub(env, "Happ/1")
    assert res_happ.status_code == 200
    assert res_happ.headers.get("Routing") == happ_body


# 12. CRLF и кириллица в заголовке правила: нет 500, CRLF не попал в значение, кириллица как base64:.
def test_rule_header_crlf_stripped_and_cyrillic_base64_encoded(env):
    settings = _rules(
        default_settings(),
        [
            {
                "name": "crlf-and-cyrillic",
                "response": "default",
                "conditions": [],
                "modifications": {
                    "headers": [
                        {"key": "X-Clean-CRLF", "value": "test\r\nvalue"},
                        {"key": "X-Cyrillic", "value": "Привет"},
                    ],
                },
            }
        ],
    )
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200

    res = sub(env, "curl/1")
    assert res.status_code == 200
    val_crlf = res.headers.get("x-clean-crlf")
    assert val_crlf == "testvalue"
    assert "\r" not in val_crlf and "\n" not in val_crlf

    val_cyr = res.headers.get("x-cyrillic")
    assert val_cyr is not None
    assert val_cyr.startswith("base64:")
    assert base64.b64decode(val_cyr.split(":", 1)[1]).decode("utf-8") == "Привет"


# 13. PUT 422: кривые response_rules.rules, balancers с неверной стратегией, page.theme_dir с "../x".
def test_put_settings_422_on_malformed_rules_balancers_and_path_traversal(env):
    # 1. Malformed response_rules.rules
    s1 = default_settings()
    s1["response_rules"]["rules"] = "invalid-json"
    assert env.client.put("/api/v1/subscription-client-settings", json=s1).status_code == 422

    # 2. balancers with invalid strategy
    s2 = default_settings()
    s2["xray_json"]["balancers"] = json.dumps([{"tag": "b1", "selector": ["proxy-"], "strategy": {"type": "invalidStrategy"}}])
    assert env.client.put("/api/v1/subscription-client-settings", json=s2).status_code == 422

    # 3. legacy page.theme_dir is ignored and dropped
    s3 = default_settings()
    s3["page"]["theme_dir"] = "../x"
    response = env.client.put("/api/v1/subscription-client-settings", json=s3)
    assert response.status_code == 200
    assert "theme_dir" not in response.json()["settings"]["page"]


# 14. Роль: required_role_for_request для GET и DELETE /api/v1/subscription-client-settings/devices возвращает admin; 401 без авторизации на DELETE; удаление устройства работает, повторное 404.
def test_subscription_devices_rbac_and_deletion(env):
    assert AuthService.required_role_for_request("GET", "/api/v1/subscription-client-settings/devices") == "admin"
    assert AuthService.required_role_for_request("DELETE", "/api/v1/subscription-client-settings/devices") == "admin"
    assert AuthService.required_role_for_request("DELETE", "/api/v1/subscription-client-settings/devices/1") == "admin"

    # 401 without authorization on DELETE
    env.user = None
    assert env.client.delete("/api/v1/subscription-client-settings/devices/1").status_code == 401
    env.user = "admin"

    # Register a device
    settings = default_settings()
    settings["devices"].update({"enabled": True, "max_devices": 2})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    res_reg = env.client.get(
        f"/api/v1/sub/{env.email_token}",
        headers={"User-Agent": "curl/1", "X-HWID": "hwid-del-test"},
    )
    assert res_reg.status_code == 200

    devices = env.client.get("/api/v1/subscription-client-settings/devices").json()["devices"]
    assert len(devices) == 1
    device_id = devices[0]["id"]

    # Deletion works
    res_del = env.client.delete(f"/api/v1/subscription-client-settings/devices/{device_id}")
    assert res_del.status_code == 200
    assert res_del.json() == {"status": "success"}

    # Repeated deletion -> 404
    res_del_again = env.client.delete(f"/api/v1/subscription-client-settings/devices/{device_id}")
    assert res_del_again.status_code == 404
