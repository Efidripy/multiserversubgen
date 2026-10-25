import hashlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from client_manager import ClientManager, trojan_public_identifier
from routers.clients import build_clients_router
from services.db_bootstrap import init_db


def _response(status_code, payload=None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload or {}
    return response


def test_clients_get_hides_trojan_password_and_supplies_opaque_id(tmp_path):
    password = "trojan-panel-password"
    node = {"id": 1, "name": "alpha", "ip": "127.0.0.1"}
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
                "email": "trojan@example.test",
                "node_id": 1,
                "node_name": "alpha",
                "inbound_id": 17,
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
    assert client["id"] == f"trojan:{hashlib.sha256(password.encode()).hexdigest()[:16]}"


def test_legacy_trojan_opaque_id_resolves_to_panel_password_for_update():
    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    password = "trojan-panel-password"
    opaque_id = trojan_public_identifier(password)
    legacy_inbounds = _response(200, {
        "success": True,
        "obj": [{
            "id": 17,
            "settings": json.dumps({"clients": [{"password": password, "email": "trojan@example.test"}]}),
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
            {"name": "alpha"}, 17, opaque_id, {"enable": False},
        ) is True

    write = request.call_args_list[-1]
    assert write.args[2] == f"{base_url}/panel/api/inbounds/updateClient/{password}"
    payload = write.kwargs["json"]
    assert json.loads(payload["settings"])["clients"] == [{"id": password, "enable": False}]
