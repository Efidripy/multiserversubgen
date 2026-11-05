from __future__ import annotations

import base64
import json

import pytest

from services.subscription_xray_json import to_xray_json, validate_xray_json_section


def _vmess_link(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "vmess://" + encoded


def test_empty_links_or_no_proxies_returns_empty_string():
    assert to_xray_json([], {}) == ""
    assert to_xray_json(["invalid-url", "http://example.com"], {}) == ""
    assert to_xray_json(None, {}) == ""


def test_single_proxy_without_balancers_object_vs_array():
    link = "vless://11111111-2222-3333-4444-555555555555@node1.test:443?security=tls&sni=node1.test&type=tcp#Node-1"
    # always_array=False -> JSON object
    res_obj = to_xray_json([link], {"always_array": False})
    parsed_obj = json.loads(res_obj)
    assert isinstance(parsed_obj, dict)
    assert parsed_obj["remarks"] == "Node-1"

    # always_array=True -> JSON array with 1 item
    res_arr = to_xray_json([link], {"always_array": True})
    parsed_arr = json.loads(res_arr)
    assert isinstance(parsed_arr, list)
    assert len(parsed_arr) == 1
    assert parsed_arr[0]["remarks"] == "Node-1"


def test_multiple_proxies_without_balancers_returns_array_of_configs():
    links = [
        "vless://u1@node1.test:443?type=tcp#NodeA",
        "trojan://pw2@node2.test:443?type=tcp#NodeB",
    ]
    # always_array=False with multiple proxies -> returns array of configs
    res = to_xray_json(links, {})
    configs = json.loads(res)
    assert isinstance(configs, list)
    assert len(configs) == 2
    assert configs[0]["remarks"] == "NodeA"
    assert configs[1]["remarks"] == "NodeB"

    # Each config has its own proxy outbound with tag "proxy"
    for cfg in configs:
        outbound_tags = [ob["tag"] for ob in cfg["outbounds"]]
        assert outbound_tags == ["proxy", "direct", "block"]


def test_template_inserts_each_node_and_preserves_template_sections():
    links = [
        "vless://u1@node1.example.test:443?type=tcp#Node-A",
        "trojan://pw2@node2.example.test:443?type=tcp#Node-B",
    ]
    template = {
        "dns": {"servers": ["template.example.test"]},
        "inbounds": [{"tag": "custom-in", "protocol": "socks"}],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {}},
            {"tag": "proxy", "protocol": "old", "settings": {}},
            {"tag": "block", "protocol": "blackhole", "settings": {}},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [{"type": "field", "outboundTag": "direct"}],
        },
        "other": {"keep": True},
    }
    original = json.loads(json.dumps(template))
    section = {
        "template": template,
        "dns": json.dumps({"servers": ["ignored.example.test"]}),
        "routing": json.dumps({"domainStrategy": "AsIs"}),
        "rules": json.dumps([{"type": "field", "outboundTag": "block"}]),
        "observatory": json.dumps({"probeUrl": "https://ignored.example.test"}),
        "balancers": json.dumps([{"tag": "ignored", "strategy": {"type": "random"}}]),
        "mux": {"enabled": True},
        "final_mask": {"udp": {"header": "mptcp"}},
    }

    configs = json.loads(to_xray_json(links, section))

    assert [config["remarks"] for config in configs] == ["Node-A", "Node-B"]
    for config in configs:
        assert [outbound["tag"] for outbound in config["outbounds"]] == ["proxy", "direct", "block"]
        assert config["outbounds"][0]["mux"] == {"enabled": True}
        assert config["outbounds"][0]["streamSettings"]["finalmask"] == {"udp": {"header": "mptcp"}}
        assert config["dns"] == template["dns"]
        assert config["routing"] == template["routing"]
        assert config["inbounds"] == template["inbounds"]
        assert config["other"] == template["other"]
    assert template == original


def test_template_without_outbounds_and_inbounds_gets_defaults():
    link = "vless://u@example.test:443?type=tcp#Node"
    config = json.loads(to_xray_json([link], {"template": {"log": {"loglevel": "debug"}}}))

    assert [outbound["tag"] for outbound in config["outbounds"]] == ["proxy", "direct", "block"]
    assert [inbound["tag"] for inbound in config["inbounds"]] == ["socks", "http"]
    assert config["routing"] == {
        "domainStrategy": "AsIs",
        "rules": [{"type": "field", "outboundTag": "proxy"}],
    }
    assert config["log"] == {"loglevel": "debug"}


@pytest.mark.parametrize(
    "template",
    [
        "not json",
        "[]",
        {"inbounds": [{} , "bad"]},
        {"outbounds": {}},
        {"routing": []},
    ],
)
def test_invalid_xray_template_is_rejected(template):
    with pytest.raises(ValueError, match="template"):
        validate_xray_json_section({"template": template})


def test_empty_template_keeps_existing_output():
    link = "vless://u@example.test:443?type=tcp#Node"
    assert to_xray_json([link], {"template": ""}) == to_xray_json([link], {})


def test_config_structure_log_inbounds_and_system_outbounds():
    link = "vless://uuid@node.test:443?type=tcp#TestNode"
    res = to_xray_json([link], {})
    cfg = json.loads(res)

    assert cfg["log"] == {"loglevel": "warning"}

    inbounds = cfg["inbounds"]
    assert len(inbounds) == 2
    socks_ib = next(ib for ib in inbounds if ib["tag"] == "socks")
    http_ib = next(ib for ib in inbounds if ib["tag"] == "http")

    assert socks_ib["port"] == 10808
    assert socks_ib["listen"] == "127.0.0.1"
    assert socks_ib["protocol"] == "socks"
    assert socks_ib["settings"] == {"auth": "noauth", "udp": True}
    assert socks_ib["sniffing"] == {"enabled": True, "destOverride": ["http", "tls"]}

    assert http_ib["port"] == 10809
    assert http_ib["listen"] == "127.0.0.1"
    assert http_ib["protocol"] == "http"
    assert http_ib["settings"] == {"allowTransparent": False}
    assert http_ib["sniffing"] == {"enabled": True, "destOverride": ["http", "tls"]}

    outbounds = cfg["outbounds"]
    direct_ob = next(ob for ob in outbounds if ob["tag"] == "direct")
    block_ob = next(ob for ob in outbounds if ob["tag"] == "block")
    assert direct_ob == {"tag": "direct", "protocol": "freedom", "settings": {}}
    assert block_ob == {"tag": "block", "protocol": "blackhole", "settings": {}}


def test_vless_outbound_with_reality_and_flow():
    link = (
        "vless://00000000-0000-0000-0000-000000000000@server.net:8443"
        "?type=tcp&security=reality&sni=sni.net&fp=chrome&pbk=pubkey123&sid=sid456&flow=xtls-rprx-vision"
        "#VLESS-Reality"
    )
    res = to_xray_json([link], {})
    cfg = json.loads(res)
    ob = cfg["outbounds"][0]

    assert ob["tag"] == "proxy"
    assert ob["protocol"] == "vless"
    assert ob["settings"] == {
        "vnext": [
            {
                "address": "server.net",
                "port": 8443,
                "users": [
                    {
                        "id": "00000000-0000-0000-0000-000000000000",
                        "encryption": "none",
                        "flow": "xtls-rprx-vision",
                    }
                ],
            }
        ]
    }
    assert ob["streamSettings"]["network"] == "tcp"
    assert ob["streamSettings"]["security"] == "reality"
    assert ob["streamSettings"]["realitySettings"] == {
        "serverName": "sni.net",
        "fingerprint": "chrome",
        "publicKey": "pubkey123",
        "shortId": "sid456",
    }


def test_vmess_outbound_with_tls():
    payload = {
        "v": "2",
        "ps": "VMess-TLS",
        "add": "vmess.net",
        "port": "443",
        "id": "vmess-uuid",
        "aid": "0",
        "scy": "auto",
        "net": "tcp",
        "type": "none",
        "host": "",
        "path": "",
        "tls": "tls",
        "sni": "sni.vmess.net",
        "fp": "firefox",
    }
    link = _vmess_link(payload)
    res = to_xray_json([link], {})
    cfg = json.loads(res)
    ob = cfg["outbounds"][0]

    assert ob["tag"] == "proxy"
    assert ob["protocol"] == "vmess"
    assert ob["settings"] == {
        "vnext": [
            {
                "address": "vmess.net",
                "port": 443,
                "users": [
                    {
                        "id": "vmess-uuid",
                        "security": "auto",
                    }
                ],
            }
        ]
    }
    assert ob["streamSettings"]["network"] == "tcp"
    assert ob["streamSettings"]["security"] == "tls"
    assert ob["streamSettings"]["tlsSettings"] == {
        "serverName": "sni.vmess.net",
        "fingerprint": "firefox",
    }


def test_trojan_outbound_settings():
    link = "trojan://secretpw@trojan.net:443?type=tcp&sni=trojan.net&fp=safari#Trojan-Node"
    res = to_xray_json([link], {})
    cfg = json.loads(res)
    ob = cfg["outbounds"][0]

    assert ob["tag"] == "proxy"
    assert ob["protocol"] == "trojan"
    assert ob["settings"] == {
        "servers": [
            {
                "address": "trojan.net",
                "port": 443,
                "password": "secretpw",
            }
        ]
    }
    assert ob["streamSettings"]["security"] == "tls"
    assert ob["streamSettings"]["tlsSettings"] == {
        "serverName": "trojan.net",
        "fingerprint": "safari",
    }


def test_transports_ws_grpc_httpupgrade_xhttp_h2():
    # WebSocket
    ws_link = "vless://u@srv:443?type=ws&path=%2Fwebsocket&host=ws.domain#WS"
    cfg_ws = json.loads(to_xray_json([ws_link], {}))
    ss_ws = cfg_ws["outbounds"][0]["streamSettings"]
    assert ss_ws["network"] == "ws"
    assert ss_ws["wsSettings"] == {
        "path": "/websocket",
        "headers": {"Host": "ws.domain"},
    }

    # gRPC with mode=multi
    grpc_multi = "vless://u@srv:443?type=grpc&serviceName=my-grpc&mode=multi#GRPC-Multi"
    cfg_gm = json.loads(to_xray_json([grpc_multi], {}))
    ss_gm = cfg_gm["outbounds"][0]["streamSettings"]
    assert ss_gm["network"] == "grpc"
    assert ss_gm["grpcSettings"] == {
        "serviceName": "my-grpc",
        "multiMode": True,
    }

    # gRPC gun mode
    grpc_gun = "vless://u@srv:443?type=grpc&serviceName=my-gun&mode=gun#GRPC-Gun"
    cfg_gg = json.loads(to_xray_json([grpc_gun], {}))
    ss_gg = cfg_gg["outbounds"][0]["streamSettings"]
    assert ss_gg["grpcSettings"]["multiMode"] is False

    # httpupgrade
    upgrade_link = "vless://u@srv:443?type=httpupgrade&path=%2Fup&host=up.domain#Upgrade"
    cfg_up = json.loads(to_xray_json([upgrade_link], {}))
    ss_up = cfg_up["outbounds"][0]["streamSettings"]
    assert ss_up["network"] == "httpupgrade"
    assert ss_up["httpupgradeSettings"] == {
        "path": "/up",
        "host": "up.domain",
    }

    # xhttp
    xhttp_link = "vless://u@srv:443?type=xhttp&path=%2Fxhttp&host=x.domain&mode=packet-up#XHTTP"
    cfg_x = json.loads(to_xray_json([xhttp_link], {}))
    ss_x = cfg_x["outbounds"][0]["streamSettings"]
    assert ss_x["network"] == "xhttp"
    assert ss_x["xhttpSettings"] == {
        "path": "/xhttp",
        "host": "x.domain",
        "mode": "packet-up",
    }

    # h2 / http
    h2_link = "vless://u@srv:443?type=h2&path=%2Fh2path&host=h2.domain#H2"
    cfg_h2 = json.loads(to_xray_json([h2_link], {}))
    ss_h2 = cfg_h2["outbounds"][0]["streamSettings"]
    assert ss_h2["network"] == "http"
    assert ss_h2["httpSettings"] == {
        "path": "/h2path",
        "host": ["h2.domain"],
    }


def test_mux_copied_to_every_proxy_outbound_only():
    links = [
        "vless://u1@node1.test:443?type=tcp#Node1",
        "trojan://pw2@node2.test:443?type=tcp#Node2",
    ]
    mux = {"enabled": True, "concurrency": 8, "xudpConcurrency": 16}
    section = {"mux": json.dumps(mux)}
    configs = json.loads(to_xray_json(links, section))
    for cfg in configs:
        proxy_ob = cfg["outbounds"][0]
        assert proxy_ob["mux"] == mux
        direct_ob = cfg["outbounds"][1]
        assert "mux" not in direct_ob
        block_ob = cfg["outbounds"][2]
        assert "mux" not in block_ob


def test_final_mask_in_stream_settings():
    link = "vless://u@srv:443?type=tcp#Node"
    final_mask = {"udp": {"header": "mptcp"}}
    cfg = json.loads(to_xray_json([link], {"final_mask": json.dumps(final_mask)}))
    assert cfg["outbounds"][0]["streamSettings"]["finalmask"] == final_mask


def test_dns_inclusion_and_omission():
    link = "vless://u@srv:443?type=tcp#Node"
    # When dns not in section, config has no "dns" key
    cfg_nodns = json.loads(to_xray_json([link], {}))
    assert "dns" not in cfg_nodns

    # When dns provided in section
    dns_payload = {"servers": ["1.1.1.1", "8.8.8.8"]}
    cfg_dns = json.loads(to_xray_json([link], {"dns": json.dumps(dns_payload)}))
    assert cfg_dns["dns"] == dns_payload


def test_routing_rules_precedence_and_overlay():
    link = "vless://u@srv:443?type=tcp#Node"
    user_rules = [
        {"type": "field", "outboundTag": "direct", "domain": ["domain:example.com"]},
        {"type": "field", "outboundTag": "block", "ip": ["geoip:private"]},
    ]
    routing_overlay = {
        "domainStrategy": "IPIfNonMatch",
        "domainMatcher": "mph",
    }
    section = {
        "rules": json.dumps(user_rules),
        "routing": json.dumps(routing_overlay),
    }
    cfg = json.loads(to_xray_json([link], section))
    routing = cfg["routing"]

    assert routing["domainStrategy"] == "IPIfNonMatch"
    assert routing["domainMatcher"] == "mph"

    rules = routing["rules"]
    assert len(rules) == 3
    assert rules[0] == user_rules[0]
    assert rules[1] == user_rules[1]
    # Fallback rule goes to proxy
    assert rules[2] == {"type": "field", "outboundTag": "proxy"}


def test_balancers_merges_all_proxies_into_single_config():
    links = [
        "vless://u1@node1.test:443?type=tcp#Node-A",
        "vless://u2@node2.test:443?type=tcp#Node-B",
        "vless://u3@node3.test:443?type=tcp#Node-C",
    ]
    balancers = [
        {
            "tag": "balancer-all",
            "selector": ["proxy-"],
            "strategy": {"type": "roundRobin"},
        }
    ]
    section = {
        "balancers": json.dumps(balancers),
        "always_array": False,
    }
    res = to_xray_json(links, section)
    cfg = json.loads(res)

    assert isinstance(cfg, dict)
    assert cfg["remarks"] == "balancer-all"

    outbound_tags = [ob["tag"] for ob in cfg["outbounds"]]
    assert outbound_tags == ["proxy-1", "proxy-2", "proxy-3", "direct", "block"]

    routing = cfg["routing"]
    assert routing["balancers"] == balancers
    assert routing["rules"][-1] == {"type": "field", "balancerTag": "balancer-all"}
    # roundRobin does not trigger automatic observatory
    assert "observatory" not in cfg


def test_balancers_with_always_array_returns_array():
    links = ["vless://u1@node1.test:443?type=tcp#Node1"]
    balancers = [{"tag": "b1", "strategy": {"type": "random"}}]
    section = {
        "balancers": json.dumps(balancers),
        "always_array": True,
    }
    res = to_xray_json(links, section)
    parsed = json.loads(res)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["remarks"] == "b1"


def test_balancers_least_ping_least_load_adds_observatory():
    links = [
        "vless://u1@node1.test:443?type=tcp#N1",
        "vless://u2@node2.test:443?type=tcp#N2",
    ]
    balancers = [
        {"tag": "b1", "selector": ["proxy-1"], "strategy": {"type": "leastPing"}},
        {"tag": "b2", "selector": ["proxy-2"], "strategy": {"type": "leastLoad"}},
    ]
    section = {"balancers": json.dumps(balancers)}
    cfg = json.loads(to_xray_json(links, section))

    assert "observatory" in cfg
    assert cfg["observatory"] == {
        "subjectSelector": ["proxy-1", "proxy-2"],
        "probeUrl": "https://www.gstatic.com/generate_204",
        "probeInterval": "5m",
    }


def test_balancers_custom_observatory_from_section():
    links = ["vless://u1@node1.test:443?type=tcp#N1"]
    balancers = [{"tag": "b1", "selector": ["proxy-"], "strategy": {"type": "leastPing"}}]
    custom_obs = {
        "subjectSelector": ["custom-proxy"],
        "probeUrl": "https://cp.cloudflare.com",
        "probeInterval": "1m",
    }
    section = {
        "balancers": json.dumps(balancers),
        "observatory": json.dumps(custom_obs),
    }
    cfg = json.loads(to_xray_json(links, section))
    assert cfg["observatory"] == custom_obs


def test_validate_xray_json_section_valid_inputs():
    # Empty section
    validate_xray_json_section({})
    # Empty strings for all fields
    validate_xray_json_section({
        "always_array": False,
        "template": "",
        "mux": "",
        "dns": "",
        "routing": "",
        "rules": "",
        "final_mask": "",
        "observatory": "",
        "balancers": "",
    })
    # Valid JSON strings
    validate_xray_json_section({
        "always_array": True,
        "template": json.dumps({"inbounds": [], "outbounds": [], "routing": {}}),
        "mux": '{"enabled": true}',
        "dns": '{"servers": ["1.1.1.1"]}',
        "routing": '{"domainStrategy": "AsIs"}',
        "rules": '[{"type": "field"}]',
        "final_mask": '{"udp": {}}',
        "observatory": '{"probeUrl": "https://test.com"}',
        "balancers": '[{"tag": "b1", "selector": ["p1"], "strategy": {"type": "leastPing"}}]',
    })
    # Valid parsed dicts/lists
    validate_xray_json_section({
        "mux": {"enabled": True},
        "rules": [{"type": "field"}],
        "balancers": [{"tag": "b1", "strategy": {"type": "random"}}],
    })


def test_validate_xray_json_section_non_dict_section():
    with pytest.raises(ValueError, match="section"):
        validate_xray_json_section("not a dict")  # type: ignore


def test_validate_xray_json_section_always_array():
    with pytest.raises(ValueError, match="always_array"):
        validate_xray_json_section({"always_array": "yes"})


def test_validate_xray_json_section_object_fields_must_be_objects():
    for field in ["mux", "dns", "routing", "final_mask", "observatory"]:
        # Invalid JSON
        with pytest.raises(ValueError, match=field):
            validate_xray_json_section({field: "not json"})
        # Array instead of object
        with pytest.raises(ValueError, match=field):
            validate_xray_json_section({field: '["array", "not", "object"]'})
        # Scalar instead of object
        with pytest.raises(ValueError, match=field):
            validate_xray_json_section({field: "123"})


def test_validate_xray_json_section_rules_must_be_array_of_objects():
    # Invalid JSON
    with pytest.raises(ValueError, match="rules"):
        validate_xray_json_section({"rules": "invalid"})
    # Object instead of array
    with pytest.raises(ValueError, match="rules"):
        validate_xray_json_section({"rules": '{"type": "field"}'})
    # Array of non-dicts
    with pytest.raises(ValueError, match="rules"):
        validate_xray_json_section({"rules": '["string-item"]'})


def test_validate_xray_json_section_balancers_rules():
    # Invalid JSON
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": "bad json"})
    # Object instead of array
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": "{}"})
    # Item not dict
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": '["string"]'})
    # Missing or empty tag
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": '[{"strategy": {"type": "random"}}]'})
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": '[{"tag": "   ", "strategy": {"type": "random"}}]'})
    # Duplicate tag
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({
            "balancers": json.dumps([
                {"tag": "b1", "strategy": {"type": "random"}},
                {"tag": "b1", "strategy": {"type": "roundRobin"}},
            ])
        })
    # Selector not a list
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({
            "balancers": json.dumps([
                {"tag": "b1", "selector": "not-list", "strategy": {"type": "random"}}
            ])
        })
    # Missing or invalid strategy
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": '[{"tag": "b1"}]'})
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({"balancers": '[{"tag": "b1", "strategy": "not-dict"}]'})
    with pytest.raises(ValueError, match="balancers"):
        validate_xray_json_section({
            "balancers": json.dumps([
                {"tag": "b1", "strategy": {"type": "unsupportedStrategy"}}
            ])
        })


def test_balancer_without_selector_uses_all_proxies():
    links = ["trojan://secret@example.com:443?security=tls&sni=example.com&type=tcp#one"]
    section = {"balancers": json.dumps([{"tag": "auto", "strategy": {"type": "random"}}])}
    config = json.loads(to_xray_json(links, section))
    assert config["routing"]["balancers"][0]["selector"] == ["proxy-"]
    assert config["routing"]["rules"][-1]["balancerTag"] == "auto"
