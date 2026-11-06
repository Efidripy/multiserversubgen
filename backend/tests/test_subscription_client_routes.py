import base64
import json
import os
import sys
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.auth.service import AuthService
from routers import subscriptions as subscriptions_module
from routers.subscriptions import build_subscriptions_router
from services.db_bootstrap import init_db
from services.subscription_client_settings import default_settings
from services.subscription_tokens import ensure_tokens

EMAIL = "user@example.com"
VLESS = (
    "vless://11111111-1111-1111-1111-111111111111@node.example:443?encryption=none&security=reality"
    "&sni=sni.example&fp=chrome&pbk=PUBKEY&sid=ab&flow=xtls-rprx-vision&type=tcp#Node"
)
TROJAN = "trojan://secret@node.example:443?security=tls&sni=sni.example&type=tcp#Node"
SETTINGS_URL = "/api/v1/subscription-client-settings"


class NodeService:
    def list_nodes(self):
        return [{"id": 1, "name": "Node", "ip": "node.example"}]


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "admin.db")
    monkeypatch.setenv("SUB_MANAGER_DB", db_path)
    init_db(db_path)
    with subscriptions_module.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)",
            ("Group", "group", json.dumps([EMAIL]), json.dumps([])),
        )
        conn.commit()

    invalidators = []
    state = SimpleNamespace(links=[VLESS, TROJAN], user="admin")
    app = FastAPI()
    app.include_router(
        build_subscriptions_router(
            check_auth=lambda _request: state.user,
            db_path=db_path,
            node_service=NodeService(),
            check_subscription_rate_limit=lambda _request, _key: (True, 0),
            get_emails=lambda _nodes: [EMAIL],
            get_links_filtered=lambda _nodes, _email, _protocol=None: list(state.links),
            get_subscription_userinfo=lambda _nodes, _emails: {"upload": 1, "download": 2, "total": 3, "expire": 4},
            subscription_signing_secret="test-secret",
            invalidate_subscription_cache=lambda: [item() for item in invalidators],
            register_subscription_response_cache_invalidator=invalidators.append,
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
    response = env.client.put(SETTINGS_URL, json=settings)
    assert response.status_code == 200, response.text
    return settings


def sub(env, user_agent="", **params):
    return env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": user_agent}, params=params)


def test_untouched_panel_keeps_the_base64_response_for_every_client(env):
    expected = base64.b64encode(f"{VLESS}\n{TROJAN}".encode())
    for user_agent in ("Happ/1", "clash-verge/2", "SFA/1", "curl/8"):
        response = sub(env, user_agent)
        assert response.status_code == 200
        assert response.content == expected
        assert response.headers["content-type"].startswith("text/plain")
        assert response.headers["subscription-userinfo"] == "upload=1; download=2; total=3; expire=4"
        assert response.headers["profile-update-interval"] == "1"
        assert "profile-title" not in response.headers


def test_enabled_mihomo_rule_serves_valid_yaml_with_reality(env):
    configure(env, "mihomo")
    response = sub(env, "clash-verge/2.0")
    assert response.headers["content-type"].startswith("text/yaml")
    body = yaml.safe_load(response.text)
    vless = next(proxy for proxy in body["proxies"] if proxy["type"] == "vless")
    assert vless["reality-opts"] == {"public-key": "PUBKEY", "short-id": "ab"}
    assert vless["flow"] == "xtls-rprx-vision"
    assert "secret" in response.text
    assert sub(env, "curl/8").headers["content-type"].startswith("text/plain")


def test_singbox_rule_serves_valid_json(env):
    configure(env, "singbox")
    response = sub(env, "SFA/1.0")
    assert response.headers["content-type"].startswith("application/json")
    outbounds = json.loads(response.text)["outbounds"]
    assert {"vless", "trojan", "selector", "direct"} <= {item["type"] for item in outbounds}


def test_disabled_rule_does_not_match_and_format_query_wins(env):
    assert sub(env, "clash-verge/2.0").headers["content-type"].startswith("text/plain")
    assert sub(env, "curl/8", format="singbox").headers["content-type"].startswith("application/json")
    assert sub(env, "curl/8", format="unknown").headers["content-type"].startswith("text/plain")


def test_order_decides_which_rule_wins(env):
    settings = default_settings()
    settings["clients"] = [
        {"id": "custom-a", "name": "A", "enabled": True, "user_agent_regex": "same", "format": "singbox"},
        {"id": "custom-b", "name": "B", "enabled": True, "user_agent_regex": "same", "format": "mihomo"},
    ]
    assert env.client.put(SETTINGS_URL, json=settings).status_code == 200
    assert sub(env, "same/1").headers["content-type"].startswith("application/json")
    settings["clients"].reverse()
    assert env.client.put(SETTINGS_URL, json=settings).status_code == 200
    assert sub(env, "same/1").headers["content-type"].startswith("text/yaml")


def test_format_clash_excludes_vless(env):
    configure(env, "mihomo")
    response = sub(env, "curl/1.0", format="clash")
    assert response.headers["content-type"].startswith("text/yaml")
    assert "vless" not in response.text


def test_grouped_cache_never_crosses_clients_and_remembers_fallback(env):
    configure(env, "mihomo")
    url = f"/api/v1/sub-grouped/{env.group_token}"
    plain = env.client.get(url, headers={"User-Agent": "curl/8"})
    yaml_response = env.client.get(url, headers={"User-Agent": "mihomo/1"})
    assert plain.headers["x-subscription-cache"] == "miss"
    assert yaml_response.headers["x-subscription-cache"] == "miss"
    assert plain.headers["content-type"].startswith("text/plain")
    assert yaml_response.headers["content-type"].startswith("text/yaml")

    plain_hit = env.client.get(url, headers={"User-Agent": "curl/8"})
    yaml_hit = env.client.get(url, headers={"User-Agent": "mihomo/1"})
    assert plain_hit.headers["x-subscription-cache"] == "hit"
    assert yaml_hit.headers["x-subscription-cache"] == "hit"
    assert plain_hit.content == plain.content
    assert yaml_hit.content == yaml_response.content
    assert yaml_hit.headers["content-type"].startswith("text/yaml")

    configure(env, "mihomo")
    env.links = [VLESS]
    first = env.client.get(url, headers={"User-Agent": "clash/1"})
    hit = env.client.get(url, headers={"User-Agent": "clash/1"})
    assert first.headers["content-type"].startswith("text/yaml")
    assert hit.headers["x-subscription-cache"] == "hit"
    assert hit.headers["content-type"].startswith("text/yaml")


def test_saving_settings_invalidates_the_grouped_cache(env):
    url = f"/api/v1/sub-grouped/{env.group_token}"
    env.client.get(url, headers={"User-Agent": "mihomo/1"})
    assert env.client.get(url, headers={"User-Agent": "mihomo/1"}).headers["x-subscription-cache"] == "hit"
    configure(env, "mihomo")
    fresh = env.client.get(url, headers={"User-Agent": "mihomo/1"})
    assert fresh.headers["x-subscription-cache"] == "miss"
    assert fresh.headers["content-type"].startswith("text/yaml")


def test_xray_json_template_is_saved_through_settings_api(env):
    settings = default_settings()
    template = {
        "inbounds": [],
        "outbounds": [{"tag": "direct", "protocol": "freedom", "settings": {}}],
        "routing": {"rules": []},
    }
    settings["xray_json"].update(enabled=True, active="Custom", templates=[{"name": "Custom", "template": json.dumps(template)}])

    response = env.client.put(SETTINGS_URL, json=settings)

    assert response.status_code == 200, response.text
    saved = env.client.get(SETTINGS_URL).json()["settings"]["xray_json"]
    assert saved["active"] == "Custom"
    assert json.loads(saved["templates"][0]["template"]) == template


def test_guest_link_gets_the_client_format(env, monkeypatch):
    guest = SimpleNamespace(email_display=EMAIL)
    monkeypatch.setattr(subscriptions_module.TelegramRegistry, "resolve_guest_subscription_link", lambda _self, _token: guest)
    monkeypatch.setattr(subscriptions_module.TelegramRegistry, "safe_subscription_node_ids", lambda _self, _email: None)
    configure(env, "mihomo")
    response = env.client.get(f"/api/v1/guest-sub/{'t' * 32}", headers={"User-Agent": "mihomo/1"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/yaml")


def test_happ_headers_reach_only_happ_and_non_ascii_is_wrapped(env):
    configure(env, "happ", settings={"sub_info_text": "Привет", "hide_settings": True}, headers=[{"key": "X-Custom", "value": "безопасно\r\nInjected: 1"}])
    happ = sub(env, "Happ/3.2")
    assert happ.status_code == 200
    assert happ.headers["sub-info-text"] == "base64:" + base64.b64encode("Привет".encode()).decode()
    assert happ.headers["sub-info-color"] == "blue"
    assert happ.headers["hide-settings"] == "1"
    assert base64.b64decode(happ.headers["x-custom"].removeprefix("base64:")).decode() == "безопасноInjected: 1"
    assert "injected" not in happ.headers
    other = sub(env, "v2rayNG/1.8")
    assert "sub-info-text" not in other.headers
    assert "x-custom" not in other.headers


def test_happ_routing_link_of_several_kilobytes_is_saved_and_delivered(env):
    # Real routing links with geosite lists run 3-5 KB; the old 3 KB limit rejected them.
    routing = "happ://routing/onadd/" + base64.b64encode(b"x" * 3600).decode()
    configure(env, "happ", settings={"routing_enable": True, "routing": routing})
    response = sub(env, "Happ/3.6")
    assert response.status_code == 200
    assert response.headers["routing"] == routing


def test_incy_routing_goes_to_the_body_not_a_header(env):
    configure(env, "incy", settings={"routing_enable": True, "routing": "incy://routing/abc"})
    response = sub(env, "INCY/1")
    assert base64.b64decode(response.content).decode().endswith("\nincy://routing/abc")
    assert "routing" not in response.headers
    assert "routing-enable" not in response.headers


def test_panel_profile_overrides_environment_and_zero_interval_drops_header(env):
    settings = default_settings()
    settings["profile"].update({"title": "Панель", "update_interval_hours": 0, "support_url": "https://support.example"})
    assert env.client.put(SETTINGS_URL, json=settings).status_code == 200
    response = sub(env, "curl/8")
    assert response.headers["profile-title"] == "base64:" + base64.b64encode("Панель".encode()).decode()
    assert response.headers["support-url"] == "https://support.example"
    assert "profile-update-interval" not in response.headers


def test_custom_header_case_does_not_duplicate_profile_header(env):
    settings = default_settings()
    settings["profile"]["title"] = "Panel"
    client = next(item for item in settings["clients"] if item["id"] == "happ")
    client.update({"enabled": True, "headers": [{"key": "profile-title", "value": "Own"}]})
    assert env.client.put(SETTINGS_URL, json=settings).status_code == 200
    response = sub(env, "Happ/1")
    assert response.headers.get_list("profile-title") == ["Own"]


@pytest.mark.parametrize(
    "mutate, detail",
    [
        (lambda c: c.update(user_agent_regex="("), "user_agent_regex"),
        (lambda c: c.update(user_agent_regex="a" * 301), "user_agent_regex"),
        (lambda c: c.update(headers=[{"key": "Set-Cookie", "value": "x"}]), "headers"),
        (lambda c: c.update(headers=[{"key": "Bad Name", "value": "x"}]), "headers"),
        (lambda c: c.update(headers=[{"key": "X-Big", "value": "x" * 13000}]), "headers"),
        (lambda c: c.update(settings={"new_url": "javascript:alert(1)"}), "new_url"),
        (lambda c: c.update(settings={"routing": "https://example.com"}), "routing"),
        (lambda c: c.update(format="xml"), "format"),
    ],
)
def test_invalid_settings_are_rejected_with_the_field_name(env, mutate, detail):
    settings = default_settings()
    mutate(settings["clients"][0])
    response = env.client.put(SETTINGS_URL, json=settings)
    assert response.status_code == 422
    assert response.json()["detail"] == detail


def test_invalid_mihomo_rules_are_rejected(env):
    settings = default_settings()
    client = next(item for item in settings["clients"] if item["id"] == "mihomo")
    client["settings"] = {"enable_routing": True, "rules": "DOMAIN,example.com,NOWHERE"}
    response = env.client.put(SETTINGS_URL, json=settings)
    assert response.status_code == 422
    assert 'line 1: target "NOWHERE"' in response.json()["detail"]

    client["settings"]["rules"] = "DOMAIN,a.com,DIRECT\nexample.com"
    response = env.client.put(SETTINGS_URL, json=settings)
    assert response.status_code == 422
    assert "line 2" in response.json()["detail"]


def test_mihomo_rules_accept_real_config_syntax(env):
    settings = default_settings()
    client = next(item for item in settings["clients"] if item["id"] == "mihomo")
    client["settings"] = {
        "enable_routing": True,
        "rules": "\n".join(
            [
                "rules:",
                "  - DOMAIN-SUFFIX,ru,DIRECT",
                "  - 'GEOIP,RU,DIRECT,no-resolve'",
                "AND,((NETWORK,UDP),(DST-PORT,443)),REJECT-DROP",
                "# comment",
                "MATCH,PROXY",
            ]
        ),
    }
    response = env.client.put(SETTINGS_URL, json=settings)
    assert response.status_code == 200, response.text
    saved = next(item for item in response.json()["settings"]["clients"] if item["id"] == "mihomo")
    assert saved["settings"]["rules"].splitlines() == [
        "DOMAIN-SUFFIX,ru,DIRECT",
        "GEOIP,RU,DIRECT,no-resolve",
        "AND,((NETWORK,UDP),(DST-PORT,443)),REJECT-DROP",
        "# comment",
        "MATCH,PROXY",
    ]


def test_remote_mihomo_rule_list_is_normalized():
    from services.subscription_remote_rules import _validate_body

    assert _validate_body("mihomo", "- DOMAIN,a.com,DIRECT\n- MATCH,PROXY\n") == "DOMAIN,a.com,DIRECT\nMATCH,PROXY"


def test_builtin_rule_cannot_be_deleted_or_change_kind(env):
    settings = default_settings()
    settings["clients"] = [{"id": "happ", "name": "Renamed", "kind": "generic", "builtin": False}]
    saved = env.client.put(SETTINGS_URL, json=settings).json()["settings"]["clients"]
    happ = next(item for item in saved if item["id"] == "happ")
    assert (happ["kind"], happ["builtin"], happ["name"]) == ("happ", True, "Renamed")
    assert {"happ", "incy", "mihomo", "stash", "singbox"} <= {item["id"] for item in saved}


def test_test_endpoint_reports_match_and_profile(env):
    settings = default_settings()
    settings["profile"]["title"] = "Panel"
    next(item for item in settings["clients"] if item["id"] == "mihomo")["enabled"] = True
    env.client.put(SETTINGS_URL, json=settings)
    matched = env.client.post(f"{SETTINGS_URL}/test", json={"user_agent": "mihomo/1"}).json()
    assert (matched["matched"], matched["client_id"], matched["format"]) == (True, "mihomo", "mihomo")
    unmatched = env.client.post(f"{SETTINGS_URL}/test", json={"user_agent": "curl/8"}).json()
    assert (unmatched["matched"], unmatched["client_id"], unmatched["format"]) == (False, None, "base64")
    assert unmatched["headers"]["Profile-Title"] == "Panel"
    assert env.client.post(f"{SETTINGS_URL}/test", json={"user_agent": "x" * 513}).status_code == 422


def test_legacy_clash_settings_migrate_to_mihomo(env):
    settings = default_settings()
    settings["clients"] = [
        {
            "id": "clash",
            "name": "Clash",
            "kind": "mihomo",
            "builtin": True,
            "enabled": True,
            "format": "clash",
            "settings": {"enable_routing": True, "rules": "DOMAIN,a,DIRECT"},
            "headers": [{"key": "X-Legacy", "value": "1"}],
        },
        {
            "id": "mihomo",
            "name": "Mihomo",
            "kind": "mihomo",
            "builtin": True,
            "enabled": False,
            "user_agent_regex": r"^(?:flclash|rabbit|flowvy|murge|mihomo|prizrak-box|koala-clash|clash(?:-verge|-nyanpasu|x meta|[-.]?meta))",
            "settings": {},
            "headers": [],
        },
    ]
    saved = env.client.put(SETTINGS_URL, json=settings).json()["settings"]["clients"]
    assert "clash" not in {item["id"] for item in saved}
    mihomo = next(item for item in saved if item["id"] == "mihomo")
    assert mihomo["enabled"] is True
    assert mihomo["settings"]["rules"] == "DOMAIN,a,DIRECT"
    assert mihomo["headers"] == [{"key": "X-Legacy", "value": "1"}]
    assert mihomo["name"] == "Mihomo/Clash"


def test_clash_user_agents_match_mihomo(env):
    settings = default_settings()
    next(item for item in settings["clients"] if item["id"] == "mihomo")["enabled"] = True
    env.client.put(SETTINGS_URL, json=settings)
    for user_agent in ("clash/1", "clash.meta/1"):
        matched = env.client.post(f"{SETTINGS_URL}/test", json={"user_agent": user_agent}).json()
        assert (matched["matched"], matched["client_id"]) == (True, "mihomo")


MIHOMO_TEMPLATE = """# kept comment
x-anchors:
  dns_ru: &dns_ru
    - 77.88.8.8
  rp: &rp
    type: http
    behavior: domain
    proxy: VPN
mixed-port: 7890
tun:
  enable: true
dns:
  default-nameserver: *dns_ru
  fallback: *dns_ru
proxy-providers:
  sub:
    type: http
    url: https://${DOMAIN}/${SUB_PATH}/${SUB_ID}?provider=1
    interval: 3600
proxies:
  - name: DNS-OUT
    type: dns
proxy-groups:
  - name: VPN
    type: select
    use:
      - sub
rule-providers:
  ads: {<<: *rp, url: https://example.com/ads.mrs}
rules:
  - DST-PORT,53,DNS-OUT
  - OR,((RULE-SET,ads),(DOMAIN,a.example.com)),REJECT-DROP
  - MATCH,VPN
"""


def test_mihomo_template_is_saved_as_is(env):
    configure(env, "mihomo", settings={"enable_routing": True, "rules": MIHOMO_TEMPLATE})
    saved = next(item for item in env.client.get(SETTINGS_URL).json()["settings"]["clients"] if item["id"] == "mihomo")
    assert saved["settings"]["rules"] == MIHOMO_TEMPLATE.rstrip("\n")


@pytest.mark.parametrize(
    "rules,detail",
    [
        (MIHOMO_TEMPLATE.replace("MATCH,VPN", "MATCH,NOWHERE"), 'target "NOWHERE"'),
        (MIHOMO_TEMPLATE.replace("MATCH,VPN", "MATCH,PROXY"), 'target "PROXY"'),
        ("x-anchors:\n  a: [\n", "YAML error at line"),
        (MIHOMO_TEMPLATE + "#" * (512 * 1024), "larger than 512 KiB"),
    ],
    ids=["unknown-target", "proxy-with-provider", "broken-yaml", "too-large"],
)
def test_invalid_mihomo_template_is_rejected(env, rules, detail):
    settings = default_settings()
    client = next(item for item in settings["clients"] if item["id"] == "mihomo")
    client["settings"] = {"enable_routing": True, "rules": rules}
    response = env.client.put(SETTINGS_URL, json=settings)
    assert response.status_code == 422
    assert detail in response.json()["detail"]


def test_mihomo_template_with_provider_is_served(env):
    configure(env, "mihomo", settings={"enable_routing": True, "rules": MIHOMO_TEMPLATE})
    response = sub(env, "clash-verge/2.0")
    assert response.headers["content-type"].startswith("text/yaml")
    assert "${" not in response.text and "&id" not in response.text
    body = yaml.safe_load(response.text)
    assert "x-anchors" not in body
    assert body["proxy-providers"]["sub"]["url"] == f"https://testserver/api/v1/sub/{env.email_token}?provider=1"
    assert body["proxies"] == [{"name": "DNS-OUT", "type": "dns"}]
    assert body["proxy-groups"] == [{"name": "VPN", "type": "select", "use": ["sub"]}]
    assert body["rules"][-1] == "MATCH,VPN"
    assert body["tun"] == {"enable": True}
    assert body["dns"]["fallback"] == ["77.88.8.8"]
    assert body["rule-providers"]["ads"]["proxy"] == "VPN"

    nodes = sub(env, "clash-verge/2.0", provider="1")
    assert not nodes.text.lstrip().startswith(("#", "mixed-port"))
    assert "://" in base64.b64decode(nodes.text).decode()


def test_mihomo_template_without_provider_gets_generated_nodes(env):
    template = "mixed-port: 7890\nproxy-groups:\n  - name: VPN\n    type: select\n    proxies: [PROXY]\nrules:\n  - MATCH,VPN\n"
    configure(env, "mihomo", settings={"enable_routing": True, "rules": template})
    body = yaml.safe_load(sub(env, "clash-verge/2.0").text)
    assert any(proxy["type"] == "vless" for proxy in body["proxies"])
    assert [group["name"] for group in body["proxy-groups"]] == ["PROXY", "VPN"]
    assert body["rules"] == ["MATCH,VPN"]


def test_mihomo_template_own_proxy_group_gets_generated_nodes(env):
    template = "proxy-groups:\n  - name: PROXY\n    type: select\n    proxies: [DIRECT]\nrules:\n  - MATCH,PROXY\n"
    configure(env, "mihomo", settings={"enable_routing": True, "rules": template})
    body = yaml.safe_load(sub(env, "clash-verge/2.0").text)
    assert [group["name"] for group in body["proxy-groups"]] == ["PROXY"]
    names = [proxy["name"] for proxy in body["proxies"]]
    assert names and body["proxy-groups"][0]["proxies"] == ["DIRECT", *names]


def test_mihomo_template_needs_enable_routing(env):
    configure(env, "mihomo", settings={"enable_routing": False, "rules": MIHOMO_TEMPLATE})
    body = yaml.safe_load(sub(env, "clash-verge/2.0").text)
    assert "proxy-providers" not in body
    assert body["rules"] == ["MATCH,PROXY"]


def test_settings_api_requires_auth_and_admin_role(env):
    env.user = None
    assert env.client.get(SETTINGS_URL).status_code == 401
    assert env.client.put(SETTINGS_URL, json=default_settings()).status_code == 401
    assert env.client.post(f"{SETTINGS_URL}/test", json={"user_agent": "x"}).status_code == 401
    for method in ("GET", "PUT", "POST"):
        assert AuthService.required_role_for_request(method, SETTINGS_URL) == "admin"
    assert AuthService.required_role_for_request("POST", f"{SETTINGS_URL}/test") == "admin"


def test_xray_json_link_gives_plain_subscription_while_template_is_off(env):
    # Clients that cannot read Xray JSON must still get working links.
    response = sub(env, "v2rayNG/1.9.30", format="xray_json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert base64.b64decode(response.content).decode().startswith(("vless://", "vmess://", "trojan://", "ss://"))
