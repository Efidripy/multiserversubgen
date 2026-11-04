from services.subscription_content import apply_content, render_tokens, subscription_status


def test_tokens_and_status_are_rendered():
    ctx = {"email": "user@example.com", "sub_id": "sid", "upload": 512, "download": 512, "total": 2048, "expire": 2000}
    assert subscription_status(ctx, 1000) == "active"
    rendered = render_tokens("{{EMAIL}} {{USERNAME}} {{TRAFFIC_USED}} {{TRAFFIC_LEFT}}", {**ctx, "now": 1000})
    assert rendered == "user@example.com user 1 KB 1 KB"


def test_unknown_tokens_survive_and_link_tokens_are_available():
    ctx = {"email": "user@example.com", "expire": 0}
    assert render_tokens("{{NODE}}/{{PROTOCOL}}/{{UNKNOWN}}", ctx, {"name": "Node", "kind": "vless"}) == "Node/vless/{{UNKNOWN}}"


def test_default_section_returns_same_list_object():
    links = ["vless://u@host:443?type=tcp#Node"]
    assert apply_content(links, {}, {"email": "user@example.com"}, now=1000) is links


def test_remark_identity_and_info_node():
    links = ["vless://u@host:443?type=tcp#Node"]
    result = apply_content(
        links,
        {"remark_template": "{{NODE}}-{{USERNAME}}", "show_identity_on_all_links": True, "info_node": True},
        {"email": "user@example.com", "total": 0, "expire": 0},
        now=1000,
    )
    assert len(result) == 2
    assert "Node-user%20%7C%20user%40example.com" in result[1]


def test_expired_template_replaces_all_links_with_info_link():
    result = apply_content(
        ["vless://u@host:443?type=tcp#Node"],
        {"expired_template": "Expired {{EMAIL}}"},
        {"email": "user@example.com", "expire": 10},
        now=10,
    )
    assert len(result) == 1
    assert "Expired%20user%40example.com" in result[0]


def test_vmess_node_token_uses_node_suffix_without_email_duplication():
    import base64
    import json

    payload = {"ps": "user@example.com (Node)", "add": "host", "port": 443, "id": "u", "net": "tcp"}
    link = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
    assert render_tokens("{{NODE}} {{EMAIL}}", {"email": "user@example.com"}, link) == "Node user@example.com"


def test_vmess_reality_name_and_protocol_fallback_to_link():
    import base64
    import json

    payload = {
        "ps": "user@example.com (Reality)",
        "add": "host",
        "port": 443,
        "id": "u",
        "net": "tcp",
        "pbk": "public-key",
    }
    link = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
    assert render_tokens("{{NODE}}/{{PROTOCOL}}", {"email": "user@example.com"}, link) == "Reality/vmess"
