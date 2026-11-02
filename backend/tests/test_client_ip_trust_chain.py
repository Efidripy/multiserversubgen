"""The client address comes from the hop nginx appended, never from the client."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.request_middleware import build_request_controls_and_audit_middleware
from services.request_runtime import RequestRuntime

REPO = Path(__file__).resolve().parents[2]
get_client_ip = RequestRuntime.get_client_ip


def _request(peer: str, forwarded_for: str = ""):
    return SimpleNamespace(
        headers={"X-Forwarded-For": forwarded_for} if forwarded_for else {},
        client=SimpleNamespace(host=peer),
    )


def test_last_hop_wins_over_client_supplied_values():
    assert get_client_ip(_request("127.0.0.1", "198.51.100.7")) == "198.51.100.7"
    assert get_client_ip(_request("127.0.0.1", "1.2.3.4, 198.51.100.7")) == "198.51.100.7"
    assert get_client_ip(_request("::1", "1.2.3.4,2001:db8::1")) == "2001:db8::1"


def test_nginx_without_realip_stays_loopback_instead_of_trusting_the_header():
    assert get_client_ip(_request("127.0.0.1", "1.2.3.4, 127.0.0.1")) == "127.0.0.1"


def test_header_is_ignored_from_a_non_loopback_peer():
    assert get_client_ip(_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


def test_no_usable_hop_falls_back_to_the_peer():
    assert get_client_ip(_request("127.0.0.1")) == "127.0.0.1"
    assert get_client_ip(_request("127.0.0.1", "1.2.3.4, ")) == "127.0.0.1"
    assert get_client_ip(SimpleNamespace(headers={}, client=None)) == "unknown"


def _noop_metric():
    return SimpleNamespace(
        labels=lambda *_args: SimpleNamespace(inc=lambda: None, observe=lambda _value: None)
    )


def _client(audit_events=None):
    app = FastAPI()
    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda _path: False,
            check_basic_auth_header=lambda header: "admin" if header == "Basic good" else None,
            check_web_session=lambda _request: None,
            get_user_role=lambda _user: "admin",
            verify_totp_code=lambda _user, _code: True,
            required_role_for_request=lambda _method, _path: "admin",
            has_min_role=lambda _actual, _required: True,
            read_only_mode=False,
            invalidate_read_projections=lambda: None,
            http_request_count=_noop_metric(),
            http_request_latency=_noop_metric(),
            get_client_ip=get_client_ip,
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=(audit_events if audit_events is not None else []).append,
        )
    )

    @app.get("/api/v1/nodes")
    def nodes():
        return []

    @app.post("/api/v1/nodes")
    def create_node():
        return {}

    @app.get("/metrics")
    def metrics():
        return {}

    return TestClient(app, client=("127.0.0.1", 40000))


def _bad_login(client, forwarded_for):
    return client.get(
        "/api/v1/nodes",
        headers={"Authorization": "Basic bad", "X-Forwarded-For": forwarded_for},
    )


def test_rotating_a_spoofed_header_does_not_reset_the_failed_auth_limit():
    client = _client()
    for attempt in range(10):
        assert _bad_login(client, f"10.9.8.{attempt}, 198.51.100.7").status_code == 401
    assert _bad_login(client, "10.9.8.200, 198.51.100.7").status_code == 429


def test_failed_auth_limit_of_one_client_does_not_block_another():
    client = _client()
    for _attempt in range(10):
        _bad_login(client, "198.51.100.7")
    assert _bad_login(client, "198.51.100.7").status_code == 429
    assert _bad_login(client, "198.51.100.8").status_code == 401


def test_audit_records_the_network_of_the_real_client():
    audit_events = []
    _bad_login(_client(audit_events), "10.9.8.7, 198.51.100.7")
    assert audit_events[0]["client_ip"] == "198.51.100.0/24"


def test_metrics_loopback_gate_still_requires_a_missing_forwarded_header():
    client = _client()
    assert client.get("/metrics").status_code == 200
    assert client.get("/metrics", headers={"X-Forwarded-For": "198.51.100.7"}).status_code == 401


def test_csrf_origin_uses_the_scheme_stated_by_nginx():
    client = _client()
    good = {"Authorization": "Basic good", "Origin": "https://testserver"}
    assert client.post("/api/v1/nodes", headers=good).status_code == 403
    assert (
        client.post("/api/v1/nodes", headers={**good, "X-Forwarded-Proto": "https"}).status_code
        == 200
    )
    external = TestClient(client.app, client=("203.0.113.9", 40000))
    assert (
        external.post("/api/v1/nodes", headers={**good, "X-Forwarded-Proto": "https"}).status_code
        == 403
    )


def test_every_launch_path_and_nginx_generator_keeps_the_trust_chain():
    unit = (REPO / "systemd/sub-manager.service").read_text(encoding="utf-8")
    assert "--no-proxy-headers" in unit
    assert "proxy_headers=False" in (REPO / "backend/main.py").read_text(encoding="utf-8")

    for script in ("install.sh", "update.sh"):
        text = (REPO / "scripts/installer" / script).read_text(encoding="utf-8")
        assert "set_real_ip_from 127.0.0.1;" in text
        assert "real_ip_header proxy_protocol;" in text
