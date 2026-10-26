import json
import os
import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from client_manager import ClientManager, trojan_public_identifier
from routers.clients import build_clients_router, dashboard_safe_client
from services.db_bootstrap import init_db


def _response(status_code, payload=None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload or {}
    return response


def test_clients_get_hides_trojan_password_and_supplies_opaque_id(tmp_path):
    """Password is stripped from GET response; stable opaque id is added instead."""
    node_id = 1
    inbound_id = 17
    email = "trojan@example.test"
    password = "trojan-panel-password"
    node = {"id": node_id, "name": "alpha", "ip": "127.0.0.1"}
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    app = FastAPI()
    app.include_router(
        build_clients_router(
            check_auth=lambda _request: "admin",
            client_mgr=MagicMock(),
            db_path=db_path,
            get_cached_clients=lambda _nodes, email_filter=None: [{
                "id": "",
                "password": password,
                "email": email,
                "node_id": node_id,
                "node_name": "alpha",
                "inbound_id": inbound_id,
                "protocol": "trojan",
            }],
            node_service=MagicMock(list_nodes=lambda: [node]),
            get_node_or_404=lambda _node_id: node,
            invalidate_live_stats_cache=lambda: None,
            invalidate_subscription_cache=lambda: None,
            ws_manager=MagicMock(),
        )
    )

    response = TestClient(app).get("/api/v1/clients")

    assert response.status_code == 200
    client = response.json()["clients"][0]
    assert "password" not in client
    expected_id = trojan_public_identifier(node_id, inbound_id, email)
    assert client["id"] == expected_id
    assert password not in client["id"]


def test_trojan_opaque_id_is_stable_across_password_changes():
    """Changing the password must not change the opaque id."""
    node_id = 5
    inbound_id = 42
    email = "user@example.test"

    id_before = trojan_public_identifier(node_id, inbound_id, email)
    id_after = trojan_public_identifier(node_id, inbound_id, email)
    assert id_before == id_after
    assert id_before.startswith("trojan:")
    assert len(id_before) == len("trojan:") + 16


def test_trojan_opaque_id_differs_per_inbound():
    """Same email in different inbounds produces different opaque ids."""
    node_id = 1
    email = "shared@example.test"
    id_inbound_17 = trojan_public_identifier(node_id, 17, email)
    id_inbound_42 = trojan_public_identifier(node_id, 42, email)
    assert id_inbound_17 != id_inbound_42


def test_trojan_opaque_id_differs_per_node():
    """Same email+inbound on different nodes produces different opaque ids."""
    inbound_id = 17
    email = "shared@example.test"
    id_node_1 = trojan_public_identifier(1, inbound_id, email)
    id_node_2 = trojan_public_identifier(2, inbound_id, email)
    assert id_node_1 != id_node_2


def test_legacy_trojan_opaque_id_resolves_to_panel_password_for_update():
    """update_client resolves the opaque Trojan id to the panel password for v2 APIs."""
    manager = ClientManager(decrypt_func=lambda value: value)
    node_id = 1
    inbound_id = 17
    email = "trojan@example.test"
    password = "trojan-panel-password"
    base_url = "https://198.51.100.8:443"
    opaque_id = trojan_public_identifier(node_id, inbound_id, email)
    # The legacy panel lists clients inside inbound settings without node_id.
    legacy_inbounds = _response(200, {
        "success": True,
        "obj": [{
            "id": inbound_id,
            "settings": json.dumps({"clients": [{"password": password, "email": email}]}),
        }],
    })

    with (
        patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)),
        patch(
            "client_manager.xui_request",
            side_effect=[
                _response(404),  # initial v3 update probe
                _response(404),  # probe after re-auth confirms legacy API
                legacy_inbounds,
                _response(200, {"success": True}),
            ],
        ) as request,
    ):
        assert manager.update_client(
            {"name": "alpha", "id": node_id}, inbound_id, opaque_id, {"enable": False},
        ) is True

    write = request.call_args_list[-1]
    assert write.args[2] == f"{base_url}/panel/api/inbounds/updateClient/{password}"
    payload = write.kwargs["json"]
    assert json.loads(payload["settings"])["clients"] == [{"id": password, "enable": False}]


def test_dashboard_safe_client_assigns_opaque_id_without_protocol_field():
    """A v3 client with a password but no id/uuid gets an opaque id regardless of protocol."""
    client = {
        "id": "",
        "email": "trojan-v3@example.test",
        "node_id": 3,
        "inbound_id": 99,
        "password": "some-trojan-secret",
        # protocol is intentionally absent (as in _map_v3_client for some panels)
    }
    safe = dashboard_safe_client(client)

    assert "password" not in safe
    assert safe["id"] == trojan_public_identifier(3, 99, "trojan-v3@example.test")
    assert safe["id"].startswith("trojan:")


def test_dashboard_safe_client_preserves_existing_uuid_id():
    """A client with a real uuid/id must keep it and must not get an opaque id."""
    client = {
        "id": "real-uuid-1234",
        "email": "user@example.test",
        "node_id": 1,
        "inbound_id": 17,
        "password": "some-password",
        "protocol": "trojan",
    }
    safe = dashboard_safe_client(client)

    assert safe["id"] == "real-uuid-1234"
    assert "password" not in safe
