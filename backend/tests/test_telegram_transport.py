from __future__ import annotations

import os
import sys
from urllib.error import HTTPError
from urllib.request import Request

import pytest
import requests


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import init_db
from services.telegram_registry import TelegramRegistry, VersionConflictError
from services.telegram_transport import (
    TelegramApiTransport,
    TelegramTransportError,
    build_local_proxy_url,
    validate_local_proxy_url,
)


def test_transport_preference_defaults_to_direct_and_uses_optimistic_versioning(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)

    initial = registry.get_transport_preference()
    assert initial.mode == "direct"
    assert initial.row_version == 1

    changed = registry.set_transport_preference(
        mode="local_proxy",
        expected_row_version=initial.row_version,
        updated_by="admin",
        proxy_host="127.0.0.1",
        proxy_port=1081,
    )
    assert (changed.mode, changed.proxy_host, changed.proxy_port, changed.row_version, changed.updated_by) == (
        "local_proxy", "127.0.0.1", 1081, 2, "admin"
    )
    with pytest.raises(VersionConflictError):
        registry.set_transport_preference(mode="direct", expected_row_version=1, updated_by="other")


@pytest.mark.parametrize(
    "raw_value",
    [
        "https://127.0.0.1:1081",
        "http://example.test:1081",
        "http://127.0.0.1",
        "http://user@127.0.0.1:1081",
        "http://:password@127.0.0.1:1081",
        "http://127.0.0.1:1081/path",
    ],
)
def test_local_proxy_url_rejects_non_loopback_or_credentialed_values(raw_value):
    with pytest.raises(ValueError):
        validate_local_proxy_url(raw_value)


def test_local_proxy_mode_fails_closed_without_a_runtime_proxy(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    preference = registry.get_transport_preference()
    registry.set_transport_preference(
        mode="local_proxy",
        expected_row_version=preference.row_version,
        updated_by="admin",
        proxy_host="127.0.0.1",
        proxy_port=1081,
    )
    transport = TelegramApiTransport(db_path=db_path, local_proxy_url="")

    assert transport.status().configured is True
    assert transport.status().reachable is False
    with pytest.raises(TelegramTransportError, match="unavailable"):
        transport.open(Request("https://api.telegram.org/"), timeout=0.01)


def test_local_proxy_url_accepts_loopback_http_connect_endpoint():
    assert validate_local_proxy_url("http://127.0.0.1:1081/") == "http://127.0.0.1:1081"
    assert validate_local_proxy_url("http://user:password@127.0.0.1:1081") == "http://user:password@127.0.0.1:1081"


def test_panel_proxy_endpoint_accepts_only_loopback_ip_and_port():
    assert build_local_proxy_url("127.0.0.1", 1081) == "http://127.0.0.1:1081"
    assert build_local_proxy_url("::1", 1081) == "http://[::1]:1081"
    with pytest.raises(ValueError, match="loopback"):
        build_local_proxy_url("192.0.2.10", 1081)
    with pytest.raises(ValueError, match="loopback"):
        build_local_proxy_url("127.0.0.1", 0)


def test_transport_open_raises_http_error_with_response_body_without_network(tmp_path, monkeypatch):
    db_path = str(tmp_path / "http-error.db")
    init_db(db_path)
    transport = TelegramApiTransport(db_path=db_path, local_proxy_url="")
    response = requests.Response()
    response.status_code = 400
    response.reason = "Bad Request"
    response.headers = {"Content-Type": "text/plain"}
    response._content = b"bad payload"
    response.close = lambda: None

    monkeypatch.setattr(requests.Session, "request", lambda *_args, **_kwargs: response)

    with pytest.raises(HTTPError) as raised:
        transport.open(Request("https://api.telegram.org/botsecret-token/sendMessage"), timeout=3)

    assert raised.value.code == 400
    assert raised.value.read() == b"bad payload"


def _assert_transport_error_hides_token(tmp_path, monkeypatch, request_error):
    db_path = str(tmp_path / "network-error.db")
    init_db(db_path)
    transport = TelegramApiTransport(db_path=db_path, local_proxy_url="")
    token = "secret-token-value"

    def fail_request(*_args, **_kwargs):
        raise request_error(f"request failed for https://api.telegram.org/bot{token}/getUpdates")

    monkeypatch.setattr(requests.Session, "request", fail_request)

    with pytest.raises(Exception) as raised:
        transport.open(Request(f"https://api.telegram.org/bot{token}/getUpdates"), timeout=3)

    values = []
    current = raised.value
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.extend((str(current), repr(current)))
        current = current.__cause__ or current.__context__
    assert token not in "\n".join(values)


def test_transport_open_hides_token_from_network_error_and_exception_chain(tmp_path, monkeypatch):
    _assert_transport_error_hides_token(tmp_path, monkeypatch, requests.exceptions.ConnectionError)


def test_transport_open_hides_token_from_timeout_and_exception_chain(tmp_path, monkeypatch):
    _assert_transport_error_hides_token(tmp_path, monkeypatch, requests.exceptions.Timeout)


def test_transport_reuses_session_for_same_route_and_replaces_it_when_proxy_changes(tmp_path, monkeypatch):
    db_path = str(tmp_path / "session-reuse.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    transport = TelegramApiTransport(db_path=db_path, local_proxy_url="")
    response = requests.Response()
    response.status_code = 200
    response._content = b"{}"
    response.close = lambda: None
    session_ids = []

    def fake_request(self, *_args, **_kwargs):
        session_ids.append(id(self))
        return response

    monkeypatch.setattr(requests.Session, "request", fake_request)
    request = Request("https://api.telegram.org/botsecret-token/getUpdates")

    with transport.open(request, timeout=3):
        pass
    with transport.open(request, timeout=3):
        pass
    initial = registry.get_transport_preference()
    registry.set_transport_preference(
        mode="local_proxy",
        expected_row_version=initial.row_version,
        updated_by="test",
        proxy_host="127.0.0.1",
        proxy_port=1081,
    )
    monkeypatch.setattr(transport, "_is_local_proxy_reachable", lambda _proxy: True)
    with transport.open(request, timeout=3):
        pass
    changed = registry.get_transport_preference()
    registry.set_transport_preference(
        mode="local_proxy",
        expected_row_version=changed.row_version,
        updated_by="test",
        proxy_host="127.0.0.1",
        proxy_port=1082,
    )
    with transport.open(request, timeout=3):
        pass

    assert session_ids[0] == session_ids[1]
    assert session_ids[2] != session_ids[1]
    assert session_ids[3] != session_ids[2]
