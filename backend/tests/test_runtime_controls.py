"""Tests for runtime controls (auth parsing and sub rate limiting)."""
import base64
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("PROJECT_DIR", "/tmp")
import main


def _basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _dummy_request(ip: str = "127.0.0.1", forwarded_for: str = ""):
    return SimpleNamespace(
        headers={"X-Forwarded-For": forwarded_for} if forwarded_for else {},
        client=SimpleNamespace(host=ip),
    )


def test_extract_basic_auth_username():
    assert main.extract_basic_auth_username(_basic_header("alice", "pw")) == "alice"
    assert main.extract_basic_auth_username("Bearer token") is None
    assert main.extract_basic_auth_username(None) is None


def test_subscription_rate_limit_blocks_after_threshold(monkeypatch):
    monkeypatch.setattr(main, "SUB_RATE_LIMIT_COUNT", 2)
    monkeypatch.setattr(main, "SUB_RATE_LIMIT_WINDOW_SEC", 60)
    main.subscription_rate_state.clear()

    req = _dummy_request(ip="10.0.0.5")
    assert main._check_subscription_rate_limit(req, "sub:test@example.com")[0] is True
    assert main._check_subscription_rate_limit(req, "sub:test@example.com")[0] is True
    allowed, retry_after = main._check_subscription_rate_limit(req, "sub:test@example.com")
    assert allowed is False
    assert retry_after >= 1
