import json
from unittest.mock import MagicMock, patch
from client_manager import ClientManager
from modules.auth.service import AuthService


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
