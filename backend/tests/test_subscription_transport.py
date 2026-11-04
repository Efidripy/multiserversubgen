import base64
import json

import yaml

from services import subscription_links
from services.subscription_formats import to_mihomo, to_singbox


def _node_inbound(network):
    settings = {"network": network, "security": "tls", f"{network}Settings": {"path": "/a b", "host": "host name"}}
    if network == "grpc":
        settings = {"network": network, "security": "tls", "grpcSettings": {"serviceName": "svc", "multiMode": True}}
    return {"protocol": "vless", "remark": "Inbound", "streamSettings": settings, "settings": {"clients": [{"email": "u@example.com", "id": "uuid"}]}}


def test_transport_parameters_are_added_and_remark_is_remembered(monkeypatch):
    subscription_links.links_cache.clear()
    subscription_links._link_inbound_remarks.clear()
    monkeypatch.setattr(subscription_links, "fetch_inbounds", lambda _node: [_node_inbound("ws")])
    links = subscription_links.get_links_filtered([{"name": "Node", "ip": "127.0.0.1"}], "u@example.com")
    assert "path=%2Fa%20b" in links[0] and "host=host%20name" in links[0]
    assert subscription_links.get_link_inbound_remark(links[0]) == "Inbound"


def test_grpc_mode_and_format_transport_fields():
    subscription_links.links_cache.clear()
    raw = "vless://uuid@example.com:443?security=tls&type=grpc&serviceName=svc&mode=multi#Node"
    import yaml
    mihomo = yaml.safe_load(to_mihomo([raw]))["proxies"][0]
    assert mihomo["grpc-opts"]["grpc-service-name"] == "svc"
    payload = json.loads(to_singbox([raw]))
    assert payload["outbounds"][1]["transport"]["service_name"] == "svc"


def test_vmess_transport_fields_are_json_values():
    payload = {"v": "2", "ps": "Node", "add": "host", "port": "443", "id": "uuid", "net": "ws", "path": "/x", "host": "h"}
    link = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
    decoded = json.loads(base64.b64decode(link.split("//", 1)[1]))
    assert decoded["path"] == "/x" and decoded["host"] == "h"


def test_singbox_skips_xhttp_but_keeps_supported_transports():
    links = [
        "vless://x@example.com:443?security=tls&type=xhttp&path=%2Fx#XHTTP",
        "vless://u@example.com:443?security=tls&type=ws&path=%2Fw#WS",
    ]
    payload = json.loads(to_singbox(links))
    tags = [item["tag"] for item in payload["outbounds"] if item.get("server_port")]
    assert tags == ["WS"]


def test_information_proxy_is_last_in_default_groups():
    links = [
        "vless://u@example.com:443?security=tls&type=tcp#Node",
        "vless://0@127.0.0.1:1?security=none&type=tcp#Info",
    ]
    mihomo = yaml.safe_load(to_mihomo(links))
    assert [p["name"] for p in mihomo["proxies"]] == ["Node", "Info"]
    assert mihomo["proxy-groups"][0]["proxies"][:2] == ["Node", "Info"]
    singbox = json.loads(to_singbox(links))
    outbounds = [item for item in singbox["outbounds"] if item.get("server_port")]
    assert [item["tag"] for item in outbounds] == ["Node", "Info"]
    assert singbox["outbounds"][0]["outbounds"] == ["Node", "Info"]
