import copy
import json

import pytest

from inbound_manager import InboundManager
from modules.auth.service import AuthService


class Response:
    status_code = 200

    def __init__(self, obj=None):
        self.obj = obj

    def json(self):
        return {"success": True, "obj": self.obj}


def test_replace_preserves_clients_and_deletes_keys(monkeypatch):
    current = {
        "id": 1, "remark": "old", "enable": True, "listen": "", "port": 443, "protocol": "vless",
        "settings": json.dumps({"clients": [{"id": "client"}], "old": 1, "keep": 2}),
        "streamSettings": json.dumps({"network": "tcp", "remove": 1}), "sniffing": "{}", "panelField": 7,
    }
    manager = InboundManager(lambda x: x)
    sent = []
    monkeypatch.setattr(manager, "_edit_session", lambda node: (object(), "http://node"))
    monkeypatch.setattr(manager, "_edit_read", lambda session, url, inbound_id: copy.deepcopy(current))
    monkeypatch.setattr(manager, "_xui_success", lambda response: True)
    monkeypatch.setattr("inbound_manager.xui_request", lambda *args, **kwargs: sent.append(kwargs["json"]) or Response())
    expected = manager.read_edit_config({}, 1)
    value = copy.deepcopy(expected)
    value["remark"] = "new"
    del value["settings"]["old"]
    del value["streamSettings"]["remove"]
    value["settings"]["clients"] = [{"id": "attacker"}]
    assert manager.replace_edit_config({}, 1, value, expected)
    payload = sent[0]
    assert json.loads(payload["settings"]) == {"clients": [{"id": "client"}], "keep": 2}
    assert json.loads(payload["streamSettings"]) == {"network": "tcp"}
    assert payload["remark"] == "new" and payload["panelField"] == 7
    with pytest.raises(RuntimeError):
        manager.replace_edit_config({}, 1, value, {**expected, "remark": "stale"})
    assert len(sent) == 1
    with pytest.raises(PermissionError):
        manager.replace_edit_config({"read_only": True}, 1, value, expected)
    assert len(sent) == 1


def test_config_routes_are_admin_only():
    for method in ("GET", "PUT"):
        assert AuthService.required_role_for_request(method, "/api/v1/inbounds/2/1/config") == "admin"


def test_config_conflict_response():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.inbounds import build_inbounds_router

    class Manager:
        def replace_edit_config(self, node, inbound_id, value, expected):
            raise RuntimeError("conflict")

    app = FastAPI()
    app.include_router(build_inbounds_router(
        check_auth=lambda request: "admin", inbound_mgr=Manager(), get_cached_inbounds=None,
        get_cached_slim_inbounds=None, get_cached_inbound_options=None, node_service=None,
        get_node_or_404=lambda node_id: {"id": node_id}, invalidate_subscription_cache=lambda: None,
        invalidate_live_stats_cache=lambda: None, ws_manager=None,
    ))
    config = {"settings": {}, "streamSettings": {}, "sniffing": {}}
    response = TestClient(app).put('/api/v1/inbounds/2/1/config', json={"value": config, "expected": config})
    assert response.status_code == 409


def test_optional_edit_fields_follow_node_presence(monkeypatch):
    current = {"settings": "{}", "streamSettings": "{}", "sniffing": "{}", "total": 1073741824, "tag": "old"}
    manager = InboundManager(lambda x: x)
    sent = []
    monkeypatch.setattr(manager, "_edit_session", lambda node: (object(), "http://node"))
    monkeypatch.setattr(manager, "_edit_read", lambda session, url, inbound_id: copy.deepcopy(current))
    monkeypatch.setattr(manager, "_xui_success", lambda response: True)
    monkeypatch.setattr("inbound_manager.xui_request", lambda *args, **kwargs: sent.append(kwargs["json"]) or Response())
    expected = manager.read_edit_config({}, 1)
    assert expected["total"] == 1073741824 and expected["tag"] == "old"
    assert "expiryTime" not in expected
    value = {**expected, "tag": "new", "expiryTime": 123}
    assert manager.replace_edit_config({}, 1, value, expected)
    assert sent[0]["tag"] == "new" and sent[0]["total"] == 1073741824
    assert "expiryTime" not in sent[0]
