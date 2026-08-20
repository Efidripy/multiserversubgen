import base64
import hashlib
import hmac
import os
import sys
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.subscriptions import build_subscriptions_router
from services.db_bootstrap import connect, init_db
from services.subscription_tokens import ensure_tokens, regenerate_token


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
