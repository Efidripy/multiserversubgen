import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.app_settings import load_app_settings
from core.config import Settings


def _parse_mfa_users(_: str) -> dict[str, str]:
    return {}


def test_runtime_requires_provisioned_secrets_when_hardened(monkeypatch):
    monkeypatch.setenv("REQUIRE_PERSISTENT_SECRETS", "true")
    monkeypatch.delenv("WS_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_SIGNING_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="WS_AUTH_SECRET"):
        load_app_settings(parse_mfa_users=_parse_mfa_users)
    with pytest.raises(RuntimeError, match="WS_AUTH_SECRET"):
        Settings()


def test_runtime_uses_provisioned_secrets_stably(monkeypatch):
    monkeypatch.setenv("REQUIRE_PERSISTENT_SECRETS", "true")
    monkeypatch.setenv("WS_AUTH_SECRET", "ws-secret-for-test")
    monkeypatch.setenv("SUBSCRIPTION_SIGNING_SECRET", "subscription-secret-for-test")

    first = load_app_settings(parse_mfa_users=_parse_mfa_users)
    second = load_app_settings(parse_mfa_users=_parse_mfa_users)

    assert first.ws_auth_secret == second.ws_auth_secret == "ws-secret-for-test"
    assert (
        first.subscription_signing_secret
        == second.subscription_signing_secret
        == "subscription-secret-for-test"
    )
    assert Settings().ws_auth_secret == "ws-secret-for-test"


def test_development_keeps_explicit_ephemeral_fallback(monkeypatch):
    monkeypatch.delenv("REQUIRE_PERSISTENT_SECRETS", raising=False)
    monkeypatch.delenv("WS_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_SIGNING_SECRET", raising=False)

    settings = load_app_settings(parse_mfa_users=_parse_mfa_users)

    assert len(settings.ws_auth_secret) == 64
    assert len(settings.subscription_signing_secret) == 64
