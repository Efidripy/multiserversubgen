import base64
import json
import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.subscriptions import build_subscriptions_router
from services.db_bootstrap import init_db
from services.subscription_links import get_subscription_userinfo
from services.subscription_tokens import ensure_tokens


def test_userinfo_aggregates_nodes_and_deduplicates_inbounds(monkeypatch):
    node_inbounds = {
        "one": [
            {
                "settings": {"clients": [{"email": "User@Example.com", "totalGB": 100, "expiryTime": -1}]},
                "clientStats": [{"email": "User@Example.com", "up": 10, "down": 20}],
            },
            {
                "settings": {"clients": [{"email": "user@example.com", "totalGB": 999, "expiryTime": 0}]},
                "clientStats": [{"email": "user@example.com", "up": 999, "down": 999}],
            },
        ],
        "two": [
            {
                "settings": {"clients": [{"email": "USER@EXAMPLE.COM", "totalGB": 200, "expiryTime": 2500}]},
                "clientStats": [{"email": "user@example.com", "up": 3, "down": 4}],
            }
        ],
    }
    monkeypatch.setattr(
        "services.subscription_links.fetch_inbounds",
        lambda node: node_inbounds[node["name"]],
    )

    result = get_subscription_userinfo(
        [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}],
        ["uSeR@eXaMpLe.CoM"],
    )

    assert result == {"upload": 13, "download": 24, "total": 300, "expire": 2}


def test_userinfo_unlimited_quota_wins_and_expiry_ignores_nonpositive(monkeypatch):
    monkeypatch.setattr(
        "services.subscription_links.fetch_inbounds",
        lambda _node: [
            {
                "settings": {
                    "clients": [
                        {"email": "user@example.com", "totalGB": 50, "expiryTime": -1000},
                        {"email": "other@example.com", "totalGB": 0, "expiryTime": 0},
                    ]
                },
                "clientStats": [],
            }
        ],
    )

    assert get_subscription_userinfo([{"id": 1, "name": "node"}], ["USER@EXAMPLE.COM"]) == {
        "upload": 0,
        "download": 0,
        "total": 50,
        "expire": 0,
    }
    assert get_subscription_userinfo([{"id": 1, "name": "node"}], ["other@example.com"]) == {
        "upload": 0,
        "download": 0,
        "total": 0,
        "expire": 0,
    }


def test_userinfo_without_matching_data_is_none(monkeypatch):
    monkeypatch.setattr("services.subscription_links.fetch_inbounds", lambda _node: [])
    assert get_subscription_userinfo([{"id": 1, "name": "node"}], ["missing@example.com"]) is None


def _build_subscription_app(
    tmp_path,
    *,
    userinfo=None,
    interval=12,
    title="",
    grouped=False,
):
    db_path = str(tmp_path / "subscriptions.db")
    init_db(db_path)
    if grouped:
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO subscription_groups (name, identifier, email_patterns, node_filters) VALUES (?, ?, ?, ?)",
                ("Group", "group", json.dumps(["user@example.com"]), json.dumps([])),
            )
            conn.commit()

    nodes = [{"id": 1, "name": "node1", "ip": "127.0.0.1"}]

    class NodeService:
        def list_nodes(self):
            return list(nodes)

    app = FastAPI()
    app.include_router(
        build_subscriptions_router(
            check_auth=lambda _request: "admin",
            db_path=db_path,
            node_service=NodeService(),
            check_subscription_rate_limit=lambda _request, _key: (True, 0),
            get_emails=lambda _nodes: ["user@example.com"],
            get_links_filtered=lambda _nodes, email, _protocol=None: [f"vless://{email}@node1"],
            get_subscription_userinfo=lambda _nodes, _emails: userinfo,
            subscription_profile_update_interval_hours=interval,
            subscription_profile_title=title,
            subscription_signing_secret="test-secret",
            invalidate_subscription_cache=lambda: None,
            logger=None,
        )
    )
    token_kind = "group" if grouped else "email"
    identifier = "group" if grouped else "user@example.com"
    token = ensure_tokens(db_path, token_kind, [identifier])[identifier]
    return TestClient(app), token


def test_sub_route_returns_userinfo_and_profile_headers(tmp_path):
    client, token = _build_subscription_app(
        tmp_path,
        userinfo={"upload": 1, "download": 2, "total": 3, "expire": 4},
        title="Профиль\r\n",
    )

    response = client.get(f"/api/v1/sub/{token}")

    assert response.status_code == 200
    assert response.headers["subscription-userinfo"] == "upload=1; download=2; total=3; expire=4"
    assert response.headers["profile-update-interval"] == "12"
    assert response.headers["profile-title"] == "base64:" + base64.b64encode("Профиль".encode()).decode()


def test_profile_interval_zero_omits_header_and_ascii_title_is_preserved(tmp_path):
    client, token = _build_subscription_app(
        tmp_path,
        userinfo={"upload": 1, "download": 2, "total": 3, "expire": 4},
        interval=0,
        title="My Profile\r\n",
    )

    response = client.get(f"/api/v1/sub/{token}")

    assert response.status_code == 200
    assert "profile-update-interval" not in response.headers
    assert response.headers["profile-title"] == "My Profile"


def test_no_userinfo_data_omits_subscription_header(tmp_path):
    client, token = _build_subscription_app(tmp_path, userinfo=None)
    response = client.get(f"/api/v1/sub/{token}")
    assert response.status_code == 200
    assert "subscription-userinfo" not in response.headers


def test_grouped_cache_hit_keeps_subscription_userinfo(tmp_path):
    info = {"upload": 10, "download": 20, "total": 30, "expire": 40}
    client, token = _build_subscription_app(tmp_path, userinfo=info, grouped=True)

    first = client.get(f"/api/v1/sub-grouped/{token}")
    second = client.get(f"/api/v1/sub-grouped/{token}")

    assert first.status_code == second.status_code == 200
    assert first.headers["x-subscription-cache"] == "miss"
    assert second.headers["x-subscription-cache"] == "hit"
    assert first.headers["subscription-userinfo"] == second.headers["subscription-userinfo"]
    assert second.headers["subscription-userinfo"] == "upload=10; download=20; total=30; expire=40"
