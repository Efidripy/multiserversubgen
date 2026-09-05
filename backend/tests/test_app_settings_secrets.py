import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.app_settings import load_app_settings


def _parse_mfa_users(_: str) -> dict[str, str]:
    return {}


def test_runtime_requires_provisioned_secrets_when_hardened(monkeypatch):
    monkeypatch.setenv("REQUIRE_PERSISTENT_SECRETS", "true")
    monkeypatch.delenv("WS_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_SIGNING_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="WS_AUTH_SECRET"):
        load_app_settings(parse_mfa_users=_parse_mfa_users)


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


def test_development_keeps_explicit_ephemeral_fallback(monkeypatch):
    monkeypatch.delenv("REQUIRE_PERSISTENT_SECRETS", raising=False)
    monkeypatch.delenv("WS_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SUBSCRIPTION_SIGNING_SECRET", raising=False)

    settings = load_app_settings(parse_mfa_users=_parse_mfa_users)

    assert len(settings.ws_auth_secret) == 64
    assert len(settings.subscription_signing_secret) == 64


def test_telegram_is_disabled_by_default_and_does_not_need_runtime_secrets(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_ENABLED", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_PRIMARY_ADMIN_ID", raising=False)

    settings = load_app_settings(parse_mfa_users=_parse_mfa_users)

    assert settings.telegram.enabled is False
    assert settings.telegram.bot_token == ""
    assert settings.telegram.primary_admin_id is None


@pytest.mark.parametrize(
    ("token", "admin_id", "expected"),
    [
        ("", "123", "TELEGRAM_BOT_TOKEN"),
        ("test-token", "", "TELEGRAM_PRIMARY_ADMIN_ID"),
        ("test-token", "not-a-number", "positive 64-bit integer"),
        ("test-token", "0", "positive 64-bit integer"),
    ],
)
def test_enabled_telegram_fails_closed_without_valid_runtime_configuration(monkeypatch, token, admin_id, expected):
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_PRIMARY_ADMIN_ID", admin_id)

    with pytest.raises(RuntimeError, match=expected):
        load_app_settings(parse_mfa_users=_parse_mfa_users)


def test_enabled_telegram_accepts_only_runtime_provided_identity(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-runtime-token")
    monkeypatch.setenv("TELEGRAM_PRIMARY_ADMIN_ID", "108100140")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PATH_SUFFIX", "test-path-suffix")
    monkeypatch.setenv("TELEGRAM_PUBLIC_BASE_URL", "https://bot.example.test")

    settings = load_app_settings(parse_mfa_users=_parse_mfa_users)

    assert settings.telegram.enabled is True
    assert settings.telegram.primary_admin_id == 108100140
    assert settings.telegram.mode == "webhook"
    assert settings.telegram.introduction_max_chars == 700
    assert settings.telegram.provisioning_worker_enabled is False


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("TELEGRAM_WEBHOOK_SECRET", "", "TELEGRAM_WEBHOOK_SECRET"),
        ("TELEGRAM_WEBHOOK_PATH_SUFFIX", "", "TELEGRAM_WEBHOOK_PATH_SUFFIX"),
        ("TELEGRAM_PUBLIC_BASE_URL", "http://bot.example.test", "HTTPS origin"),
        ("TELEGRAM_INTRODUCTION_MAX_CHARS", "701", "TELEGRAM_INTRODUCTION_MAX_CHARS"),
    ],
)
def test_enabled_telegram_rejects_incomplete_webhook_configuration(monkeypatch, name, value, expected):
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-runtime-token")
    monkeypatch.setenv("TELEGRAM_PRIMARY_ADMIN_ID", "108100140")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PATH_SUFFIX", "test-path-suffix")
    monkeypatch.setenv("TELEGRAM_PUBLIC_BASE_URL", "https://bot.example.test")
    monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=expected):
        load_app_settings(parse_mfa_users=_parse_mfa_users)


def test_provisioning_worker_requires_explicit_remote_write_switch(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-runtime-token")
    monkeypatch.setenv("TELEGRAM_PRIMARY_ADMIN_ID", "108100140")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_PATH_SUFFIX", "test-path-suffix")
    monkeypatch.setenv("TELEGRAM_PUBLIC_BASE_URL", "https://bot.example.test")
    monkeypatch.setenv("TELEGRAM_PROVISIONING_WORKER_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_PROVISIONING_ALLOW_REMOTE_WRITES", raising=False)

    with pytest.raises(RuntimeError, match="ALLOW_REMOTE_WRITES"):
        load_app_settings(parse_mfa_users=_parse_mfa_users)

    monkeypatch.setenv("TELEGRAM_PROVISIONING_ALLOW_REMOTE_WRITES", "true")
    settings = load_app_settings(parse_mfa_users=_parse_mfa_users)
    assert settings.telegram.provisioning_worker_enabled is True
