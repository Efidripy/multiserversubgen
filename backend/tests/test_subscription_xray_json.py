import copy
import base64
import json

import pytest

from services.subscription_xray_json import (
    DEFAULT_XRAY_TEMPLATE,
    to_xray_json,
    validate_xray_json_section,
)

LINKS = [
    "vless://u1@node1.example.test:443?type=tcp#Node-A",
    "vless://u2@node2.example.test:443?type=tcp#Node-B",
]


def _vmess_link(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "vmess://" + encoded


def test_default_template_when_enabled():
    configs = json.loads(to_xray_json(LINKS, {"enabled": True}))
    assert len(configs) == 2
    assert [config["remarks"] for config in configs] == ["Node-A", "Node-B"]
    assert configs[0]["dns"]["servers"] == ["1.1.1.1", "1.0.0.1"]
    assert configs[0]["routing"]["rules"] == [
        {"type": "field", "protocol": ["bittorrent"], "outboundTag": "direct"}
    ]


def test_proxy_skeleton_applies_mux_sockopt_and_finalmask_without_template_proxy():
    template = {
        "outbounds": [
            {
                "tag": "proxy",
                "mux": {"enabled": True},
                "streamSettings": {"sockopt": {"tcpFastOpen": True}, "finalmask": {"udp": {}}},
            },
            {"tag": "direct", "protocol": "freedom"},
        ]
    }
    original = copy.deepcopy(template)
    config = json.loads(to_xray_json([LINKS[0]], {"enabled": True, "active": "Custom", "templates": [{"name": "Custom", "template": json.dumps(template)}]}))
    proxy = config["outbounds"][0]
    assert proxy["tag"] == "proxy"
    assert proxy["mux"] == {"enabled": True}
    assert proxy["streamSettings"]["sockopt"] == {"tcpFastOpen": True}
    assert proxy["streamSettings"]["finalmask"] == {"udp": {}}
    assert all(item["tag"] != "proxy" for item in config["outbounds"][1:])
    assert template == original


def test_balancer_mode_uses_one_config_and_defaults():
    template = {
        "routing": {"balancers": [{"tag": "best", "strategy": {"type": "leastPing"}}]},
        "outbounds": [{"tag": "direct", "protocol": "freedom"}],
    }
    config = json.loads(to_xray_json(LINKS, {"enabled": True, "active": "Custom", "templates": [{"name": "Custom", "template": json.dumps(template)}]}))
    assert config["remarks"] == "best"
    assert [item["tag"] for item in config["outbounds"][:2]] == ["proxy-1", "proxy-2"]
    assert config["routing"]["balancers"][0]["selector"] == ["proxy-"]
    assert config["routing"]["rules"][-1] == {
        "type": "field", "network": "tcp,udp", "balancerTag": "best"
    }
    assert config["observatory"]["subjectSelector"] == ["proxy-"]


def test_balancer_observatory_is_not_added_when_template_has_one():
    template = {
        "observatory": {"subjectSelector": ["custom"]},
        "routing": {"balancers": [{"tag": "best", "strategy": {"type": "leastLoad"}}]},
    }
    config = json.loads(to_xray_json([LINKS[0]], {"enabled": True, "active": "Custom", "templates": [{"name": "Custom", "template": json.dumps(template)}]}))
    assert config["observatory"] == {"subjectSelector": ["custom"]}


@pytest.mark.parametrize("template", [
    "not-json", [], {"inbounds": ["bad"]}, {"outbounds": {}},
    {"routing": []}, {"routing": {"rules": ["bad"]}},
    {"routing": {"balancers": [{"tag": "b", "strategy": {"type": "bad"}}]}},
])
def test_invalid_templates_raise_template(template):
    with pytest.raises(ValueError, match="templates"):
        validate_xray_json_section({"templates": [{"name": "Custom", "template": template if isinstance(template, str) else json.dumps(template)}]})


def test_old_keys_are_ignored_and_empty_template_gets_default():
    from services.subscription_client_settings import validate_settings

    settings = validate_settings({
        "xray_json": {"template": "", "mux": "{bad", "dns": "", "balancers": "[]"},
        "clients": [],
    })
    section = settings["xray_json"]
    assert section == {"always_array": False, "enabled": False, "active": "Default", "templates": []}


def test_always_array_controls_single_config_shape():
    link = [LINKS[0]]
    assert isinstance(json.loads(to_xray_json(link, {"enabled": False, "always_array": False})), dict)
    assert isinstance(json.loads(to_xray_json(link, {"enabled": False, "always_array": True})), list)


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


def test_disabled_is_minimal_and_has_no_dns():
    config = json.loads(to_xray_json([LINKS[0]], {"enabled": False}))
    assert "dns" not in config
    assert config["log"] == {"loglevel": "warning"}
    assert config["routing"] == {"domainStrategy": "AsIs", "rules": [{"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}]}
    assert [outbound["tag"] for outbound in config["outbounds"]] == ["proxy", "direct", "block"]
    assert "mux" not in config["outbounds"][0]
    assert "finalmask" not in config["outbounds"][0]["streamSettings"]


@pytest.mark.parametrize("legacy", ["", json.dumps(DEFAULT_XRAY_TEMPLATE, sort_keys=True)])
def test_legacy_default_is_disabled(legacy):
    from services.subscription_client_settings import validate_settings
    section = validate_settings({"xray_json": {"template": legacy, "routing": "bad", "rules": "bad", "final_mask": "bad", "observatory": "bad"}})["xray_json"]
    assert section == {"always_array": False, "enabled": False, "active": "Default", "templates": []}


def test_legacy_custom_is_migrated():
    from services.subscription_client_settings import validate_settings
    template = json.dumps({"dns": {"servers": ["example.test"]}})
    section = validate_settings({"xray_json": {"template": template}})["xray_json"]
    assert section == {"always_array": False, "enabled": True, "active": "Custom", "templates": [{"name": "Custom", "template": template}]}
    assert json.loads(to_xray_json([LINKS[0]], section))["dns"]["servers"] == ["example.test"]


@pytest.mark.parametrize("templates", [
    [{"name": "One", "template": "{}"}, {"name": "one", "template": "{}"}],
    [{"name": "Default", "template": "{}"}],
    [{"name": "  ", "template": "{}"}],
    [{"name": "A", "template": "not-json"}],
])
def test_invalid_template_lists(templates):
    with pytest.raises(ValueError, match="templates"):
        validate_xray_json_section({"templates": templates})


def test_unknown_active_rejected():
    with pytest.raises(ValueError, match="active"):
        validate_xray_json_section({"active": "missing", "templates": []})

def test_every_generated_routing_rule_has_a_condition():
    # Xray-core rejects a rule without conditions ("this rule has no effective fields").
    link = "vless://11111111-1111-1111-1111-111111111111@example.test:443?type=tcp&security=tls&sni=example.test#one"
    conditions = {"domain", "ip", "port", "sourcePort", "network", "source", "user", "inboundTag", "protocol", "attrs", "process"}
    for section in ({}, {"enabled": True, "active": "Custom", "templates": [{"name": "Custom", "template": "{}"}]}):
        config = json.loads(to_xray_json([link], section))
        for rule in config["routing"]["rules"]:
            assert conditions & set(rule), rule
