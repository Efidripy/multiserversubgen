from __future__ import annotations

import os
import sys

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.request_middleware import (
    build_request_controls_and_audit_middleware,
    is_session_first_protected_get,
    is_trusted_loopback_metrics_scrape,
)


class _MetricValue:
    def inc(self):
        pass

    def observe(self, _value):
        pass


class _Metric:
    def labels(self, *_args):
        return _MetricValue()


def _app(*, mfa_ok: bool = True, required_role: str = "viewer"):
    calls = {"basic": [], "session": 0, "mfa": 0}
    app = FastAPI()

    def check_basic(header):
        calls["basic"].append(header)
        return "basic-admin" if header == "Basic stale" else None

    def check_session(request):
        calls["session"] += 1
        return (
            "session-viewer" if request.cookies.get("web-session") == "valid" else None
        )

    def verify_mfa(_user, _code):
        calls["mfa"] += 1
        return mfa_ok

    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda _path: False,
            check_basic_auth_header=check_basic,
            check_web_session=check_session,
            get_user_role=lambda user: (
                "viewer" if user == "session-viewer" else "admin"
            ),
            verify_totp_code=verify_mfa,
            required_role_for_request=lambda _method, _path: required_role,
            has_min_role=lambda actual, required: (
                actual == "admin" or actual == required
            ),
            read_only_mode=False,
            invalidate_read_projections=lambda: None,
            http_request_count=_Metric(),
            http_request_latency=_Metric(),
            get_client_ip=lambda _request: "127.0.0.1",
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=lambda _event: None,
            allowed_origins=["http://testserver"],
        )
    )

    @app.api_route(
        "/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
    )
    async def protected_projection(request: Request, path: str):
        return {
            "path": path,
            "via": request.state.auth_via,
            "user": request.state.auth_user,
        }

    return TestClient(app), calls


_PROTECTED_GET_PATHS = (
    "/api/v1/dashboard/overview",
    "/api/v1/emails",
    "/api/v1/subscription-groups",
    "/api/v1/backup/all",
    "/api/v1/nodes/42/api-tokens",
    "/api/v1/nodes/42/xray-config",
    "/api/v1/telegram/requests",
    "/api/v1/unclassified-read",
)


@pytest.mark.parametrize("path", _PROTECTED_GET_PATHS)
def test_session_first_read_skips_basic_when_a_valid_session_already_exists(path):
    client, calls = _app()

    response = client.get(
        path,
        headers={"Authorization": "Basic stale", "Cookie": "web-session=valid"},
    )

    assert response.status_code == 200
    assert response.json()["via"] == "session"
    assert response.json()["user"] == "session-viewer"
    assert calls == {"basic": [], "session": 1, "mfa": 0}


@pytest.mark.parametrize(
    "path",
    ("/api/v1/dashboard/overview", "/api/v1/telegram/node-policies"),
)
def test_session_first_read_keeps_basic_for_clients_without_a_session(path):
    client, calls = _app()

    response = client.get(path, headers={"Authorization": "Basic stale"})

    assert response.status_code == 200
    assert response.json()["via"] == "basic"
    assert calls == {"basic": ["Basic stale"], "session": 1, "mfa": 1}


@pytest.mark.parametrize(
    "path",
    ("/api/v1/traffic/stats", "/api/v1/telegram/node-policies"),
)
def test_invalid_session_falls_back_to_basic_for_a_session_first_read(path):
    client, calls = _app()

    response = client.get(
        path,
        headers={"Authorization": "Basic stale", "Cookie": "web-session=invalid"},
    )

    assert response.status_code == 200
    assert response.json()["via"] == "basic"
    assert calls == {"basic": ["Basic stale"], "session": 1, "mfa": 1}


@pytest.mark.parametrize("path", ("/api/v1/inbounds", "/api/v1/inbounds/stats"))
@pytest.mark.parametrize("cookie", (None, "web-session=invalid"))
def test_inbounds_session_first_reads_fall_back_to_basic_without_a_valid_session(
    path, cookie
):
    client, calls = _app()
    headers = {"Authorization": "Basic stale"}
    if cookie:
        headers["Cookie"] = cookie

    response = client.get(path, headers=headers)

    assert response.status_code == 200
    assert response.json()["via"] == "basic"
    assert calls == {"basic": ["Basic stale"], "session": 1, "mfa": 1}


def test_protected_get_guard_is_method_bounded():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/api/v1/any-protected-read",
            "raw_path": b"/api/v1/any-protected-read",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1234),
            "server": ("testserver", 443),
        }
    )

    assert is_session_first_protected_get(request) is True
    request.scope["method"] = "POST"
    assert is_session_first_protected_get(request) is False


def test_sensitive_admin_get_still_requires_the_session_identity_role():
    client, calls = _app(required_role="admin")

    response = client.get(
        "/api/v1/telegram/requests",
        headers={"Authorization": "Basic stale", "Cookie": "web-session=valid"},
    )

    assert response.status_code == 403
    assert calls == {"basic": [], "session": 1, "mfa": 0}


def test_protected_get_without_credentials_returns_401_after_both_auth_methods():
    client, calls = _app()

    response = client.get("/api/v1/backup/all")

    assert response.status_code == 401
    assert calls == {"basic": [None], "session": 1, "mfa": 0}


def test_public_get_does_not_attempt_session_or_basic_authentication():
    calls = {"basic": 0, "session": 0}
    app = FastAPI()
    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda path: path == "/api/v1/auth/mfa-status",
            check_basic_auth_header=lambda _header: calls.__setitem__(
                "basic", calls["basic"] + 1
            ),
            check_web_session=lambda _request: calls.__setitem__(
                "session", calls["session"] + 1
            ),
            get_user_role=lambda _user: "viewer",
            verify_totp_code=lambda _user, _code: True,
            required_role_for_request=lambda _method, _path: "viewer",
            has_min_role=lambda _actual, _required: True,
            read_only_mode=False,
            invalidate_read_projections=lambda: None,
            http_request_count=_Metric(),
            http_request_latency=_Metric(),
            get_client_ip=lambda _request: "127.0.0.1",
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=lambda _event: None,
        )
    )

    @app.get("/api/v1/auth/mfa-status")
    async def public_status():
        return {"enabled": True}

    response = TestClient(app).get("/api/v1/auth/mfa-status")

    assert response.status_code == 200
    assert calls == {"basic": 0, "session": 0}


def test_trusted_loopback_metrics_predicate_remains_narrow():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/metrics",
            "raw_path": b"/metrics",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }
    )

    assert is_trusted_loopback_metrics_scrape(request) is True
    proxied_request = Request(
        {
            **request.scope,
            "headers": [(b"x-forwarded-for", b"203.0.113.1")],
        }
    )
    assert is_trusted_loopback_metrics_scrape(proxied_request) is False


def test_mutation_keeps_basic_first_and_its_csrf_gate():
    client, calls = _app()

    response = client.post(
        "/api/v1/nodes",
        headers={
            "Authorization": "Basic stale",
            "Cookie": "web-session=valid",
            "Origin": "https://evil.invalid",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF origin check failed"}
    assert calls == {"basic": ["Basic stale"], "session": 0, "mfa": 1}


def test_session_first_read_still_applies_rbac_to_the_session_identity():
    client, calls = _app(required_role="admin")

    response = client.get(
        "/api/v1/dashboard/overview",
        headers={"Authorization": "Basic stale", "Cookie": "web-session=valid"},
    )

    assert response.status_code == 403
    assert calls == {"basic": [], "session": 1, "mfa": 0}


def test_session_bootstrap_post_remains_basic_first_and_requires_mfa():
    client, calls = _app(mfa_ok=False)

    response = client.post(
        "/api/v1/auth/session",
        headers={
            "Authorization": "Basic stale",
            "Cookie": "web-session=valid",
            "Origin": "http://testserver",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "MFA required"}
    assert calls == {"basic": ["Basic stale"], "session": 0, "mfa": 1}
