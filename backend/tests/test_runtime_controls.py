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


def test_traffic_stats_cache_hit(monkeypatch):
    calls = {"n": 0}

    class DummyMgr:
        def get_traffic_stats(self, nodes, group_by):
            calls["n"] += 1
            return {"stats": {"x": {"up": 1, "down": 2, "total": 3, "count": 1}}, "group_by": group_by}

    monkeypatch.setattr(main, "client_mgr", DummyMgr())
    monkeypatch.setattr(main, "TRAFFIC_STATS_CACHE_TTL", 60)
    main.traffic_stats_cache.clear()

    nodes = [{"name": "n1"}]
    first = main.get_cached_traffic_stats(nodes, "client")
    second = main.get_cached_traffic_stats(nodes, "client")

    assert first["stats"]["x"]["total"] == 3
    assert second["stats"]["x"]["total"] == 3
    assert calls["n"] == 1
