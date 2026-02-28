"""Tests for RBAC role mapping and required-role policy."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", "/tmp")
import main


def test_get_user_role_from_lists(monkeypatch):
    monkeypatch.setattr(main, "ROLE_VIEWERS", {"viewer1"})
    monkeypatch.setattr(main, "ROLE_OPERATORS", {"operator1"})

    assert main.get_user_role("viewer1") == "viewer"
    assert main.get_user_role("operator1") == "operator"
    assert main.get_user_role("admin1") == "admin"


def test_has_min_role():
    assert main.has_min_role("admin", "viewer") is True
    assert main.has_min_role("operator", "viewer") is True
    assert main.has_min_role("viewer", "operator") is False


def test_required_role_policy():
    assert main._required_role_for_request("GET", "/api/v1/nodes") == "viewer"
    assert main._required_role_for_request("POST", "/api/v1/nodes") == "operator"
    assert main._required_role_for_request("DELETE", "/api/v1/nodes/1") == "admin"
    assert main._required_role_for_request("POST", "/api/v1/servers/1/restart-xray") == "admin"
