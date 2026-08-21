"""Regression contract for editing an existing x-ui node connection."""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from threading import Lock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers import nodes as nodes_router
from routers.nodes import build_nodes_router
from services.db_bootstrap import connect, init_db


class _SnapshotCollectorStub:
    def force_poll_all(self):
        raise AssertionError("node editing must not poll a remote panel")

    def get_mode(self):
        return "test"

    def is_running(self):
        return False


class _WsManagerStub:
    active_connections: list[object] = []


@pytest.fixture
def node_client(tmp_path, monkeypatch):
    """A real nodes router backed by an isolated SQLite database."""
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO nodes (
                id, name, panel_url, username, user, password,
                ip, port, base_path, access_path, scheme
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "edge-1",
                "https://old.example.test:443/old-panel",
                "root",
                "root",
                "encrypted:old-password",
                "old.example.test",
                "443",
                "old-panel",
                "old-panel",
                "https",
            ),
        )

    # URL parsing and persistence are under test; DNS egress policy is covered
    # independently and must not make this contract depend on external DNS.
    monkeypatch.setattr(nodes_router, "validate_outbound_url", lambda _url: (True, ""))
    monkeypatch.setattr(nodes_router, "invalidate_auth_method_cache", lambda *_args: None)
    monkeypatch.setattr(nodes_router, "invalidate_session_cache", lambda *_args: None)

    app = FastAPI()
    app.include_router(
        build_nodes_router(
            check_auth=lambda _request: "admin",
            node_service=object(),
            get_node_or_404=lambda _node_id: None,
            db_path=db_path,
            encrypt=lambda value: f"encrypted:{value}",
            requests_verify=True,
            login_panel=lambda *_args: False,
            xui_request=lambda *_args, **_kwargs: None,
            invalidate_subscription_cache=lambda: None,
            remove_node_metric_labels=lambda *_args: None,
            node_metric_labels_lock=Lock(),
            node_metric_labels_state={},
            snapshot_collector=_SnapshotCollectorStub(),
            ws_manager=_WsManagerStub(),
            logger=logging.getLogger(__name__),
        )
    )
    return TestClient(app), db_path


def _node_row(db_path: str) -> dict[str, object]:
    with connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM nodes WHERE id = 1").fetchone()
    return dict(row)


def test_node_edit_updates_panel_url_and_password_without_overwriting_username(node_client):
    client, db_path = node_client

    response = client.put(
        "/api/v1/nodes/1",
        json={
            "url": "https://edge.example.test:8443/new-panel/",
            "password": "new-password",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    stored = _node_row(db_path)
    assert stored["panel_url"] == "https://edge.example.test:8443/new-panel"
    assert stored["ip"] == "edge.example.test"
    assert stored["port"] == "8443"
    assert stored["base_path"] == "new-panel"
    assert stored["access_path"] == "new-panel"
    assert stored["scheme"] == "https"
    assert stored["password"] == "encrypted:new-password"
    assert stored["username"] == "root"
    assert stored["user"] == "root"


def test_node_edit_allows_password_only_and_preserves_username(node_client):
    client, db_path = node_client

    response = client.put("/api/v1/nodes/1", json={"password": "rotated-password"})

    assert response.status_code == 200
    stored = _node_row(db_path)
    assert stored["password"] == "encrypted:rotated-password"
    assert stored["username"] == "root"
    assert stored["user"] == "root"


@pytest.mark.parametrize(
    "payload",
    [
        {"password": ""},
        {"bearer_token": ""},
        {"bearer_token": "token-value", "user": "root"},
        {"bearer_token": "token-value", "password": "new-password"},
    ],
)
def test_node_edit_rejects_empty_or_conflicting_auth_fields(node_client, payload):
    client, db_path = node_client
    before = _node_row(db_path)

    response = client.put("/api/v1/nodes/1", json=payload)

    assert response.status_code == 400
    assert _node_row(db_path) == before
