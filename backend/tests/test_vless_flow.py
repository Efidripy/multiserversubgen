"""Tests for VLESS flow parameter in subscription link generation."""
import json
import sys
import os
from unittest.mock import patch

import pytest

import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", tempfile.mkdtemp())
import main
from services import subscription_links as subscription_links_service


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
        subscription_links_service.links_cache.clear()

    def test_reality_with_flow_includes_flow_param(self):
        inbound = _make_inbound("reality", flow="xtls-rprx-vision")
        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "&flow=xtls-rprx-vision&" in links[0]

    def test_tls_with_flow_includes_flow_param(self):
        inbound = _make_inbound("tls", flow="xtls-rprx-vision")
        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "&flow=xtls-rprx-vision&" in links[0]

    def test_reality_without_flow_omits_flow_param(self):
        inbound = _make_inbound("reality", flow="")
        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "flow" not in links[0]

    def test_tls_without_flow_omits_flow_param(self):
        inbound = _make_inbound("tls", flow="")
        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "flow" not in links[0]

    def test_reality_flow_udp443_included(self):
        inbound = _make_inbound("reality", flow="xtls-rprx-vision-udp443")
        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
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
        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")
        assert len(links) == 1
        assert "flow" not in links[0]

    def test_reality_nested_fingerprint_is_used(self):
        inbound = _make_inbound("reality")
        stream_settings = json.loads(inbound["streamSettings"])
        stream_settings["realitySettings"].pop("fingerprint", None)
        stream_settings["realitySettings"]["settings"]["fingerprint"] = "qq"
        inbound["streamSettings"] = json.dumps(stream_settings)

        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")

        assert len(links) == 1
        assert "&fp=qq&" in links[0]

    @pytest.mark.parametrize(
        "fingerprint",
        [
            "chrome",
            "firefox",
            "qq",
            "safari",
            "ios",
            "android",
            "esdge",
            "360",
            "random",
            "randomized",
        ],
    )
    def test_reality_nested_fingerprint_values_are_preserved(self, fingerprint):
        inbound = _make_inbound("reality")
        stream_settings = json.loads(inbound["streamSettings"])
        stream_settings["realitySettings"].pop("fingerprint", None)
        stream_settings["realitySettings"]["settings"]["fingerprint"] = fingerprint
        inbound["streamSettings"] = json.dumps(stream_settings)

        with patch("services.subscription_links.fetch_inbounds", return_value=[inbound]):
            links = main.get_links_filtered(_nodes(), "user@example.com")

        assert len(links) == 1
        assert f"&fp={fingerprint}&" in links[0]


def test_links_are_generated_from_persisted_node_snapshot(tmp_path):
    from services.db_bootstrap import connect, init_db

    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    inbound = _make_inbound("reality", flow="xtls-rprx-vision")
    snapshot = {
        "name": "node1",
        "node_id": 1,
        "available": True,
        "inbounds": [inbound],
    }

    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO nodes (id, name, ip, port, user, password)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "node1", "1.2.3.4", "443", "root", "encrypted"),
        )
        conn.execute(
            """
            INSERT INTO node_snapshots (node_id, status_data, is_online)
            VALUES (?, ?, ?)
            """,
            (1, json.dumps(snapshot), 1),
        )
        conn.commit()

    subscription_links_service.configure_snapshot_db(db_path)
    subscription_links_service.invalidate_subscription_cache()
    try:
        links = subscription_links_service.get_links_filtered(
            [{"id": 1, "name": "node1", "ip": "1.2.3.4"}],
            "user@example.com",
        )
    finally:
        subscription_links_service.configure_snapshot_db(main.DB_PATH)
        subscription_links_service.invalidate_subscription_cache()

    assert len(links) == 1
    assert links[0].startswith("vless://client-uuid@1.2.3.4:443")
    assert "&flow=xtls-rprx-vision&" in links[0]
