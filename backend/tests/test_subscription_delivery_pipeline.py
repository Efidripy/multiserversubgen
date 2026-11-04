import base64
import json
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

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
        conn.execute("INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)", ("Group", "group", json.dumps([EMAIL]), json.dumps([])))
        conn.commit()
    state = SimpleNamespace(links=[VLESS, TROJAN], user="admin")
    app = FastAPI()
    app.include_router(build_subscriptions_router(
        check_auth=lambda _request: state.user,
        db_path=db_path,
        node_service=NodeService(),
        check_subscription_rate_limit=lambda _request, _key: (True, 0),
        get_emails=lambda _nodes: [EMAIL],
        get_links_filtered=lambda nodes, _email, _protocol=None: list(state.links) if any(node.get("name") == "Node" for node in nodes) else [],
        get_subscription_userinfo=lambda _nodes, _emails: {"upload": 1, "download": 2, "total": 3, "expire": 4},
        subscription_signing_secret="test-secret",
        invalidate_subscription_cache=lambda: None,
        logger=None,
    ))
    state.client = TestClient(app)
    state.email_token = ensure_tokens(db_path, "email", [EMAIL])[EMAIL]
    return state


def configure(env, client_id, **fields):
    settings = default_settings()
    client = next(item for item in settings["clients"] if item["id"] == client_id)
    client.update({"enabled": True, **fields})
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    return settings


def sub(env, user_agent="", **params):
    return env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": user_agent}, params=params)


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


def test_excluded_node_is_removed_before_link_generation(env):
    settings = _rules(default_settings(), [{"name": "exclude", "response": "default", "conditions": [], "modifications": {"exclude_nodes": ["Node"]}}])
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    assert sub(env, "curl/1").status_code == 404


def test_skip_device_limit_does_not_create_device_record(env):
    settings = default_settings()
    settings["devices"].update({"enabled": True, "max_devices": 1})
    settings = _rules(settings, [{"name": "skip", "response": "default", "conditions": [], "modifications": {"skip_device_limit": True}}])
    assert env.client.put("/api/v1/subscription-client-settings", json=settings).status_code == 200
    assert env.client.get(f"/api/v1/sub/{env.email_token}", headers={"User-Agent": "curl/1", "X-HWID": "ignored"}).status_code == 200
    assert env.client.get("/api/v1/subscription-client-settings/devices").json()["devices"] == []
