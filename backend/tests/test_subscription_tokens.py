import base64
import hashlib
import hmac
import os
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.subscriptions import build_subscriptions_router
from services.db_bootstrap import connect, init_db
from services.subscription_tokens import ensure_tokens, regenerate_token
from services.telegram_access import TelegramSubscriptionAccessGate, resolve_effective_access
from services.telegram_registry import TelegramRegistry


class _Nodes:
    def list_nodes(self):
        return [{"id": 1, "name": "node1"}]


def _build_app(db_path, emails):
    app = FastAPI()

    def get_links(_nodes, email, _protocol=None):
        return [f"vless://{email}@node1"]

    app.include_router(
        build_subscriptions_router(
            check_auth=lambda _request: "admin",
            db_path=db_path,
            node_service=_Nodes(),
            check_subscription_rate_limit=lambda _request, _key: (True, 0),
            get_emails=lambda _nodes: list(emails),
            get_links_filtered=get_links,
            subscription_signing_secret="test-subscription-secret",
            invalidate_subscription_cache=lambda: None,
            logger=None,
        )
    )
    return app


def test_token_is_stable_and_manual_rotation_is_explicit(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)

    first = ensure_tokens(db_path, "email", ["D632-IOS"])["D632-IOS"]
    second = ensure_tokens(db_path, "email", ["D632-IOS"])["D632-IOS"]
    assert first == second

    rotated = regenerate_token(db_path, "email", "D632-IOS")
    assert rotated and rotated != first
    assert ensure_tokens(db_path, "email", ["D632-IOS"])["D632-IOS"] == rotated


def test_legacy_named_link_redirects_to_stable_token(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    client = TestClient(_build_app(db_path, ["D632-IOS"]))

    response = client.get("/api/v1/sub/D632-IOS", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("./")
    new_token = location.removeprefix("./")
    assert new_token and "." not in new_token

    stable = client.get(f"/api/v1/sub/{new_token}")
    assert stable.status_code == 200
    assert base64.b64decode(stable.text).decode() == "vless://D632-IOS@node1"

    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT token FROM subscription_tokens WHERE kind = 'email' AND identifier = 'D632-IOS'"
        ).fetchone()
    assert row[0] == new_token


def test_emails_endpoint_returns_only_stable_tokens(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    client = TestClient(_build_app(db_path, ["D632-IOS", "D700-ANDROID"]))

    response = client.get("/api/v1/emails")
    payload = response.json()
    assert set(payload["subscription_tokens"]) == {"D632-IOS", "D700-ANDROID"}
    assert all("." not in token for token in payload["subscription_tokens"].values())


def test_expired_secret_hmac_format_migrates_by_known_identifier(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    client = TestClient(_build_app(db_path, ["D632-IOS"]))

    payload = base64.urlsafe_b64encode(
        f"email|D632-IOS|{int(time.time()) + 3600}".encode()
    ).decode().rstrip("=")
    # Simulate an HMAC URL from a previous process whose ephemeral secret is gone.
    signature = hmac.new(b"old-process-secret", payload.encode(), hashlib.sha256).hexdigest()
    response = client.get(f"/api/v1/sub/{payload}.{signature}", follow_redirects=False)

    assert response.status_code == 302
    assert "." not in response.headers["location"].removeprefix("./")


@pytest.mark.parametrize(
    ("access_status", "customer_status", "blocked_from_status", "expected"),
    [
        ("approved", "active", None, ("active", True, True, False)),
        ("approved", "suspended", None, ("suspended", False, False, True)),
        ("approved", "delete_partial", None, ("revoking", False, False, False)),
        ("approved", "conflict", None, ("unavailable", False, False, False)),
        ("blocked", "active", "approved", ("blocked", False, True, False)),
        ("blocked", "active", "pending", ("blocked", False, False, False)),
    ],
)
def test_effective_access_is_explicit_and_fail_closed(
    access_status, customer_status, blocked_from_status, expected
):
    decision = resolve_effective_access(
        access_status=access_status,
        customer_id=7,
        email_display="safe-user",
        customer_status=customer_status,
        blocked_from_status=blocked_from_status,
    )

    assert (
        decision.state,
        decision.can_receive_subscription,
        decision.can_use_public_subscription,
        decision.can_submit_appeal,
    ) == expected


def test_public_subscription_is_denied_when_a_linked_telegram_customer_is_suspended(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=42, chat_id=42, username="linked", first_name="Linked", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="linked-user",
        origin="telegram",
        email_source="telegram_username",
        public_code="linked-user",
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'approved' "
            "WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )

    client = TestClient(_build_app(db_path, ["linked-user"]))
    token = ensure_tokens(db_path, "email", ["linked-user"])["linked-user"]

    assert client.get(f"/api/v1/sub/{token}").status_code == 200
    with connect(db_path) as conn:
        conn.execute("UPDATE customers SET status = 'suspended' WHERE id = ?", (customer_id,))

    denied = client.get(f"/api/v1/sub/{token}")
    assert denied.status_code == 404
    assert denied.text == "Not found"
    assert TelegramSubscriptionAccessGate(db_path).can_serve_email("linked-user") is False


def test_bot_block_after_approval_does_not_revoke_an_existing_public_subscription(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    identity = registry.get_or_create_identity(
        telegram_user_id=43, chat_id=43, username="blocked", first_name="Blocked", last_name=None
    )
    customer_id = registry.create_customer(
        email_display="blocked-user",
        origin="telegram",
        email_source="telegram_username",
        public_code="blocked-user",
    )
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE telegram_identities SET customer_id = ?, access_status = 'blocked', "
            "blocked_from_status = 'approved' WHERE telegram_user_id = ?",
            (customer_id, identity.telegram_user_id),
        )

    client = TestClient(_build_app(db_path, ["blocked-user"]))
    token = ensure_tokens(db_path, "email", ["blocked-user"])["blocked-user"]

    assert TelegramSubscriptionAccessGate(db_path).can_serve_email("blocked-user") is True
    assert client.get(f"/api/v1/sub/{token}").status_code == 200
