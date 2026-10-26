"""Tests for live XUI passwords used in Trojan subscription links."""

import json
import logging

import pytest

from services import subscription_links
from services.collector import SnapshotCollector
from services.snapshot_push import redact_snapshot


NODE = {"id": 1, "name": "node1", "ip": "1.2.3.4"}
EMAIL = "user@example.com"


def _make_inbound(protocol: str, inbound_id: int, *, password: str | None = None):
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
    client = {"id": f"{protocol}-client", "email": EMAIL}
    if password is not None:
        client["password"] = password
    return {
        "id": inbound_id,
        "protocol": protocol,
        "streamSettings": json.dumps(stream_settings),
        "settings": json.dumps({"clients": [client]}),
    }


def _all_inbounds(*, trojan_password: str | None = None):
    return [
        _make_inbound("vless", 1),
        _make_inbound("vmess", 2),
        _make_inbound("trojan", 3, password=trojan_password),
    ]


@pytest.fixture(autouse=True)
def _reset_subscription_state():
    subscription_links.links_cache.clear()
    subscription_links.configure_client_manager(None)
    yield
    subscription_links.links_cache.clear()
    subscription_links.configure_client_manager(None)


class _LiveClientManager:
    def __init__(self, clients):
        self.clients = clients

    def get_node_clients_strict(self, node):
        assert node == NODE
        return self.clients


def _fetch_inbounds(_node):
    return _all_inbounds()


def test_trojan_subscription_uses_live_xui_password(monkeypatch):
    monkeypatch.setattr(subscription_links, "fetch_inbounds", _fetch_inbounds)
    subscription_links.configure_client_manager(
        _LiveClientManager(
            [{"email": EMAIL, "password": "live-password", "inbound_ids": [3]}]
        )
    )

    links = subscription_links.get_links_filtered([NODE], EMAIL)

    assert any(link.startswith("vless://") for link in links)
    assert any(link.startswith("vmess://") for link in links)
    assert any(link.startswith("trojan://live-password@1.2.3.4:443") for link in links)
    assert all("snapshot-password" not in link for link in links)


def test_trojan_links_are_skipped_when_live_xui_read_fails(monkeypatch):
    monkeypatch.setattr(subscription_links, "fetch_inbounds", _fetch_inbounds)

    class FailingClientManager:
        def get_node_clients_strict(self, _node):
            raise RuntimeError("live-password must stay out of logs")

    subscription_links.configure_client_manager(FailingClientManager())

    links = subscription_links.get_links_filtered([NODE], EMAIL)

    assert any(link.startswith("vless://") for link in links)
    assert any(link.startswith("vmess://") for link in links)
    assert not any(link.startswith("trojan://") for link in links)


def test_trojan_links_are_skipped_without_client_manager(monkeypatch):
    monkeypatch.setattr(subscription_links, "fetch_inbounds", _fetch_inbounds)
    subscription_links.configure_client_manager(None)

    links = subscription_links.get_links_filtered([NODE], EMAIL)

    assert any(link.startswith("vless://") for link in links)
    assert any(link.startswith("vmess://") for link in links)
    assert not any(link.startswith("trojan://") for link in links)


def test_trojan_password_is_redacted_from_durable_snapshot_and_logs(
    monkeypatch, caplog
):
    secret = "live-password-never-persist"
    inbound = _make_inbound("trojan", 3, password=secret)
    inbound["streamSettings"] = json.loads(inbound["streamSettings"])
    inbound["settings"] = json.loads(inbound["settings"])
    snapshot = {
        "node_id": 1,
        "inbounds": [inbound],
        "password": secret,
    }

    redacted = redact_snapshot(snapshot)
    durable = SnapshotCollector._durable_snapshot_payload(snapshot)

    assert secret not in json.dumps(redacted)
    assert secret not in json.dumps(durable)

    monkeypatch.setattr(subscription_links, "fetch_inbounds", _fetch_inbounds)

    class FailingClientManager:
        def get_node_clients_strict(self, _node):
            raise RuntimeError(secret)

    subscription_links.configure_client_manager(FailingClientManager())
    caplog.set_level(logging.WARNING, logger="sub_manager")
    subscription_links.get_links_filtered([NODE], EMAIL)

    assert secret not in caplog.text
