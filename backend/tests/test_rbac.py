"""Tests for RBAC role mapping and required-role policy."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", "/tmp")
import main


def test_get_user_role_from_lists(monkeypatch):
    monkeypatch.setattr(main, "ROLE_OPERATORS", {"operator1"})
    monkeypatch.setattr(main, "ROLE_ADMINS", {"admin1"})
    monkeypatch.setattr(main, "ROLE_OWNERS", {"owner1"})

    assert main.get_user_role("operator1") == "operator"
    assert main.get_user_role("admin1") == "admin"
    assert main.get_user_role("owner1") == "admin"
    assert main.get_user_role("unknown") == "viewer"


def test_has_min_role():
    assert main.has_min_role("admin", "viewer") is True
    assert main.has_min_role("operator", "viewer") is True
    assert main.has_min_role("viewer", "operator") is False


def test_required_role_policy():
    assert main._required_role_for_request("GET", "/api/v1/nodes") == "viewer"
    assert main._required_role_for_request("POST", "/api/v1/nodes") == "operator"
    assert main._required_role_for_request("DELETE", "/api/v1/nodes/1") == "admin"
    assert main._required_role_for_request("POST", "/api/v1/servers/1/restart-xray") == "admin"
    assert main._required_role_for_request("POST", "/api/v1/nodes/1/stop-xray") == "admin"
    assert main._required_role_for_request("POST", "/api/v1/inbounds/1/1/del-all-clients") == "admin"
    assert main._required_role_for_request("GET", "/api/v1/nodes/1/server-logs") == "admin"
    assert main._required_role_for_request("POST", "/api/v1/subscription-tokens/email/D632-IOS/regenerate") == "admin"
    assert main._required_role_for_request("GET", "/api/v1/telegram/node-policies") == "admin"
    assert main._required_role_for_request("PUT", "/api/v1/telegram/node-policies/1") == "admin"
    assert main._required_role_for_request("GET", "/api/v1/users") == "admin"
    assert main._required_role_for_request("PUT", "/api/v1/users/alice/role") == "admin"


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/api/v1/clients/del-depleted"),
        ("POST", "/api/v1/clients/bulk-reset-traffic"),
        ("GET", "/api/v1/clients/customer@example.test/links"),
        ("GET", "/api/v1/clients/sub-links/sub-123"),
    ),
)
def test_sensitive_client_routes_are_admin_only(method, path):
    required_role = main._required_role_for_request(method, path)

    assert required_role == "admin"
    assert main.has_min_role("viewer", required_role) is False
    assert main.has_min_role("operator", required_role) is False
    assert main.has_min_role("admin", required_role) is True


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/inbounds",
        "/api/v1/inbounds/",
        "/api/v1/nodes/7/inbounds",
        "/api/v1/nodes/7/clients",
        "/api/v1/clients",
        "/api/v1/clients/paged",
        "/api/v1/clients/search",
        "/api/v1/clients/depleted",
        "/api/v1/clients/expired",
        "/api/v1/clients/find-by-ip",
        "/api/v1/snapshots/latest",
    ),
)
def test_credential_bearing_reads_require_operator(path):
    required_role = main._required_role_for_request("GET", path)

    assert required_role == "operator"
    assert main.has_min_role("viewer", required_role) is False


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/inbounds/slim",
        "/api/v1/inbounds/options",
        "/api/v1/inbounds/stats",
        "/api/v1/clients/count",
        "/api/v1/clients/online",
        "/api/v1/clients/presence",
        "/api/v1/dashboard/summary",
        "/api/v1/nodes",
    ),
)
def test_credential_free_reads_stay_viewer(path):
    assert main._required_role_for_request("GET", path) == "viewer"


def test_snapshot_delta_channel_requires_operator():
    from routers.realtime import CHANNEL_MIN_ROLES

    assert CHANNEL_MIN_ROLES["snapshot_delta"] == "operator"


def test_review_hardened_routes_require_admin():
    for method, path in (
        ("POST", "/api/v1/subscription-groups"),
        ("PUT", "/api/v1/subscription-groups/1"),
        ("PUT", "/api/v1/nodes/1"),
        ("GET", "/api/v1/servers/1/logs"),
    ):
        assert main._required_role_for_request(method, path) == "admin", (method, path)
