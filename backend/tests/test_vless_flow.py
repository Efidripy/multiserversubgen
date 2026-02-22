"""Tests for VLESS flow parameter in subscription link generation."""
import json
import sys
import os
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", "/tmp")
import main


def _make_inbound(security, flow=""):
    """Build a minimal inbound dict for a VLESS client with given security and flow."""
    stream_settings = {
        "security": security,
        "network": "tcp",
        "realitySettings": {
            "serverNames": ["example.com"],
            "shortIds": ["abc123"],
            "fingerprint": "chrome",
            "settings": {"publicKey": "pubkey123"},
        },
        "tlsSettings": {"serverNames": ["example.com"]},
    }
    settings = {
        "clients": [
            {
                "id": "client-uuid",
                "email": "user@example.com",
                "flow": flow,
            }
        ]
    }
    return {
        "protocol": "vless",
        "streamSettings": json.dumps(stream_settings),
        "settings": json.dumps(settings),
    }


def _nodes():
    return [{"name": "node1", "ip": "1.2.3.4"}]


class TestVlessFlowParameter:
    def setup_method(self):
        # Clear link cache before each test to avoid cache hits
        main.links_cache.clear()

    def test_reality_with_flow_includes_flow_param(self):
        inbound = _make_inbound("reality", flow="xtls-rprx-vision")
        with patch("main.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "&flow=xtls-rprx-vision&" in links[0]

    def test_tls_with_flow_includes_flow_param(self):
        inbound = _make_inbound("tls", flow="xtls-rprx-vision")
        with patch("main.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "&flow=xtls-rprx-vision&" in links[0]

    def test_reality_without_flow_omits_flow_param(self):
        inbound = _make_inbound("reality", flow="")
        with patch("main.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "flow" not in links[0]

    def test_tls_without_flow_omits_flow_param(self):
        inbound = _make_inbound("tls", flow="")
        with patch("main.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "flow" not in links[0]

    def test_reality_flow_udp443_included(self):
        inbound = _make_inbound("reality", flow="xtls-rprx-vision-udp443")
        with patch("main.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "&flow=xtls-rprx-vision-udp443&" in links[0]

    def test_inbound_missing_flow_field_omits_flow_param(self):
        """Client dict without any 'flow' key should not produce flow param."""
        stream_settings = {
            "security": "reality",
            "network": "tcp",
            "realitySettings": {
                "serverNames": ["example.com"],
                "shortIds": ["abc123"],
                "fingerprint": "chrome",
                "settings": {"publicKey": "pubkey123"},
            },
        }
        settings = {
            "clients": [{"id": "client-uuid", "email": "user@example.com"}]
        }
        inbound = {
            "protocol": "vless",
            "streamSettings": json.dumps(stream_settings),
            "settings": json.dumps(settings),
        }
        with patch("main.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "flow" not in links[0]
