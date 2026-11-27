import json
from unittest.mock import MagicMock, patch
from client_manager import ClientManager, trojan_public_identifier
from modules.auth.service import AuthService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.clients import build_clients_router


def response(status, data=None):
    result = MagicMock(status_code=status)
    result.json.return_value = data or {}
    return result


def test_v2_replacement_preserves_other_clients_and_removes_key():
    manager = ClientManager(decrypt_func=lambda value: value)
    first = {"id": "one", "email": "one", "comment": "old"}
    second = {"id": "two", "email": "two", "unknown": 7}
    inbound = {"id": 1, "settings": json.dumps({"clients": [first, second], "other": True})}
    replies = [response(404), response(200, {"success": True, "obj": [inbound]}),
               response(200, {"success": True})]
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")), \
            patch("client_manager.xui_request", side_effect=replies) as request:
        assert manager.replace_client_record({}, 1, "one", first, {"id": "one", "email": "one"}) == "ok"
    settings = json.loads(request.call_args.kwargs["json"]["settings"])
    assert settings == {"clients": [{"id": "one", "email": "one"}, second], "other": True}


def test_conflict_and_read_only_do_not_write():
    manager = ClientManager(decrypt_func=lambda value: value)
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")), \
            patch("client_manager.xui_request", return_value=response(200, {
                "success": True, "obj": [{"id": "one", "email": "one"}],
            })) as request:
        assert manager.replace_client_record({}, 1, "one", {}, {}) == "conflict"
        assert request.call_count == 1
        assert manager.replace_client_record({"read_only": True}, 1, "one", {}, {}) == "read_only"
        assert request.call_count == 1


def test_record_routes_require_admin():
    for method in ("GET", "PUT"):
        assert AuthService.required_role_for_request(method, "/api/v1/clients/one/record") == "admin"


def test_v3_replacement_ignores_telemetry_and_uses_old_email_and_new_uuid():
    manager = ClientManager(decrypt_func=lambda value: value)
    expected = {"id": 42, "uuid": "old", "email": "old@example.test", "comment": "remove",
                "traffic": {"up": 1}, "updatedAt": 1, "inboundIds": [1, 2]}
    current = {**expected, "traffic": {"up": 20}, "updatedAt": 2}
    value = {**expected, "uuid": "new", "email": "new@example.test"}
    del value["comment"]
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")), \
            patch("client_manager.xui_request", side_effect=[response(200, {"success": True, "obj": [current]}),
                                                              response(200, {"success": True})]) as request:
        assert manager.replace_client_record({}, 1, "old", expected, value) == "ok"
    assert request.call_args.args[2].endswith("/clients/update/old%40example.test")
    assert request.call_args.kwargs["json"] == {"id": "new", "email": "new@example.test"}


def test_v3_missing_uuid_never_sends_database_id():
    manager = ClientManager(decrypt_func=lambda value: value)
    current = {"id": 42, "uuid": "", "email": "one", "comment": "old"}
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")), \
            patch("client_manager.xui_request", side_effect=[response(200, {"success": True, "obj": [current]}),
                                                              response(200, {"success": True})]) as request:
        assert manager.replace_client_record({}, 1, "one", current, {**current, "comment": "new"}) == "ok"
    assert "id" not in request.call_args.kwargs["json"]
    assert "id" not in manager._v3_update_payload(current, {})


def test_v2_password_client_replacement_is_scoped_to_inbound():
    manager = ClientManager(decrypt_func=lambda value: value)
    client = {"email": "same", "password": "secret", "comment": "old"}
    inbounds = [{"id": number, "settings": json.dumps({"clients": [client]})} for number in (1, 2)]
    identifier = trojan_public_identifier(10, 2, "same")
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")), \
            patch("client_manager.xui_request", side_effect=[response(404), response(200, {"success": True, "obj": inbounds}),
                                                              response(200, {"success": True})]) as request:
        assert manager.replace_client_record({"id": 10}, 2, identifier, client,
                                             {"email": "renamed", "password": "new"}) == "ok"
    assert request.call_args.args[2].endswith("/inbounds/update/2")
    assert json.loads(request.call_args.kwargs["json"]["settings"])["clients"] == [{"email": "renamed", "password": "new"}]


def test_v3_replacement_keeps_fields_partial_updates_do_not_know():
    manager = ClientManager(decrypt_func=lambda value: value)
    current = {"id": 7, "uuid": "u", "email": "one", "limitHwid": 2, "trafficReset": "daily", "custom": 1}
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")),             patch("client_manager.xui_request", side_effect=[response(200, {"success": True, "obj": [current]}),
                                                              response(200, {"success": True})]) as request:
        assert manager.replace_client_record({}, 1, "u", current, {**current, "comment": "new"}) == "ok"
    assert request.call_args.kwargs["json"] == {
        "id": "u", "email": "one", "limitHwid": 2, "trafficReset": "daily", "custom": 1, "comment": "new"}


def test_v3_update_preserves_reset_and_forwarded_ports_only_when_present():
    fields = {"resetDay": 4, "resetWeekday": 2, "resetMax": 9, "forwardedPorts": [80, 443]}
    assert ClientManager._v3_update_payload({"uuid": "u", **fields}, {"email": "new"}) == {
        "id": "u", "email": "new", **fields,
    }
    assert ClientManager._v3_update_payload({"uuid": "u"}, {}) == {"id": "u"}


def test_v3_record_route_returns_inbound_protocol_and_survives_lookup_failure():
    manager = ClientManager(decrypt_func=lambda value: value)
    node = {"id": 1, "name": "node"}
    value = {"id": 5, "uuid": "u", "email": "one", "inboundIds": [17]}
    app = FastAPI()
    app.include_router(build_clients_router(
        check_auth=lambda request: True, client_mgr=manager, db_path="unused",
        get_cached_clients=lambda *args: [], node_service=MagicMock(),
        get_node_or_404=lambda node_id: node, invalidate_live_stats_cache=lambda: None,
        invalidate_subscription_cache=lambda: None, ws_manager=MagicMock(),
    ))
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel")), \
            patch("client_manager.xui_request", return_value=response(200, {"success": True, "obj": [value]})), \
            patch.object(manager, "_fetch_inbounds_from_node") as fetch:
        fetch.return_value = [{"id": 16, "protocol": "trojan"}, {"id": 17, "protocol": "vless"}]
        client = TestClient(app)
        result = client.get("/api/v1/clients/u/record?node_id=1&inbound_id=17")
        assert result.json() == {"value": value, "protocol": "vless"}
        fetch.side_effect = RuntimeError("unavailable")
        result = client.get("/api/v1/clients/u/record?node_id=1&inbound_id=17")
        assert result.status_code == 200
        assert result.json() == {"value": value, "protocol": ""}
