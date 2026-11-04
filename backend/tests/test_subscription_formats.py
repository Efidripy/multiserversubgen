import base64
import json

import yaml

from services.subscription_formats import convert_links
from services.subscription_formats import to_mihomo, to_singbox


def test_base64_and_yaml_outputs():
    links = ["vless://uuid@example.com:443?security=tls&type=tcp&sni=example.com#Node"]
    assert base64.b64decode(convert_links(links, "base64")).startswith(b"vless://")
    assert "proxies:" in convert_links(links, "mihomo")


def test_singbox_is_valid_json_and_duplicate_names_are_unique():
    links = ["trojan://pw@example.com:443?security=tls&type=tcp#Node"] * 2
    payload = json.loads(convert_links(links, "singbox"))
    tags = [item["tag"] for item in payload["outbounds"] if item.get("type") == "trojan"]
    assert tags == ["Node", "Node 2"]


def _vmess(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "vmess://" + encoded


def test_vmess_uses_add_and_port_and_skips_incomplete_links():
    body = yaml.safe_load(to_mihomo([_vmess({"ps": "V", "add": "host", "port": "443", "id": "u", "net": "tcp"})]))
    assert body["proxies"][0]["server"] == "host"
    assert body["proxies"][0]["port"] == 443
    assert to_mihomo([_vmess({"ps": "bad", "add": "", "port": "443", "id": "u"})]) == ""


def test_routing_rules_only_apply_when_enabled_and_rules_string_is_split():
    links = ["trojan://pw@example.com:443?type=tcp#Node"]
    disabled = yaml.safe_load(to_mihomo(links, enable_routing=False, rules="DOMAIN-SUFFIX,example.com,PROXY"))
    enabled = yaml.safe_load(to_mihomo(links, enable_routing=True, rules="# comment\nDOMAIN-SUFFIX,example.com,PROXY"))
    assert disabled["rules"] == ["MATCH,PROXY"]
    assert enabled["rules"] == ["DOMAIN-SUFFIX,example.com,PROXY", "MATCH,PROXY"]


def test_vmess_without_tls_and_fp_does_not_crash_and_empty_sni_is_omitted():
    payload = {"ps": "V", "add": "host", "port": "443", "id": "u", "net": "tcp", "tls": "", "fp": "chrome", "sni": ""}
    result = json.loads(to_singbox([_vmess(payload)]))
    proxy = next(item for item in result["outbounds"] if item.get("type") == "vmess")
    assert "tls" not in proxy
    assert "server_name" not in proxy


def test_base64_keeps_every_input_link_without_filtering():
    links = ["not-a-proxy", "vless://u@example.com:443"]
    assert base64.b64decode(convert_links(links, "base64")).decode() == "\n".join(links)
