"""Client-manager compatibility decisions must not confuse outages with v2."""
from unittest.mock import MagicMock, patch


def _node():
    return {
        "name": "contract-node", "ip": "198.51.100.8", "port": "443",
        "scheme": "https", "base_path": "", "user": "admin", "password": "pass",
    }


def _response(status_code, payload=None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload or {}
    return response


def test_v3_list_timeout_or_http_failure_does_not_downgrade_node_to_v2():
    from client_manager import ClientManager
    from xui_session import get_node_api_version, invalidate_node_api_version

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    invalidate_node_api_version(base_url)
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.get_all_clients([_node()]) == []

    assert request.call_count == 1
    assert request.call_args.args[2].endswith("/panel/api/clients/list")
    assert get_node_api_version(base_url) is None


def test_v3_list_404_selects_legacy_projection():
    from client_manager import ClientManager
    from xui_session import get_node_api_version, invalidate_node_api_version

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    invalidate_node_api_version(base_url)
    legacy = {
        "success": True,
        "obj": [{"id": 1, "settings": '{"clients":[{"id":"id-1","email":"legacy@example.test"}]}' }],
    }
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", side_effect=[_response(404), _response(200, legacy)]
    ) as request:
        clients = manager.get_all_clients([_node()])

    assert [call.args[2].split("/panel/api/")[-1] for call in request.call_args_list] == ["clients/list", "inbounds/list"]
    assert clients[0]["email"] == "legacy@example.test"
    assert get_node_api_version(base_url) == "v2"
    invalidate_node_api_version(base_url)


def test_v3_update_reads_full_record_then_scopes_the_mutation_to_the_inbound():
    from client_manager import ClientManager
    from xui_session import invalidate_node_api_version, set_node_api_version

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    set_node_api_version(base_url, "v3")
    existing = {
        "uuid": "client-uuid",
        "email": "old@example.test",
        "password": "preserved-panel-secret",
        "security": "auto",
        "flow": "xtls-rprx-vision",
        "totalGB": 10,
        "expiryTime": 123456789,
        "enable": True,
        "limitIp": 2,
        "reverse": '{"enabled":true}',
        "allowedIPs": '["10.0.0.2/32"]',
    }
    listed = _response(200, {"success": True, "obj": [existing]})
    updated = _response(200, {"success": True})
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", side_effect=[listed, updated]
    ) as request:
        assert manager.update_client(
            _node(),
            inbound_id=17,
            client_uuid="client-uuid",
            updates={"email": "renamed@example.test", "totalGB": 99},
        ) is True

    list_call, update_call = request.call_args_list
    assert list_call.args[1:] == ("GET", f"{base_url}/panel/api/clients/list")
    assert update_call.args[1:] == (
        "POST",
        f"{base_url}/panel/api/clients/update/old%40example.test?inboundIds=17",
    )
    payload = update_call.kwargs["json"]
    assert payload["id"] == "client-uuid"
    assert payload["email"] == "renamed@example.test"
    assert payload["totalGB"] == 99
    assert payload["password"] == "preserved-panel-secret"
    assert payload["expiryTime"] == 123456789
    assert payload["reverse"] == {"enabled": True}
    assert payload["allowedIPs"] == ["10.0.0.2/32"]
    invalidate_node_api_version(base_url)


def test_v3_update_does_not_write_when_the_read_contract_fails():
    from client_manager import ClientManager
    from xui_session import invalidate_node_api_version, set_node_api_version

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    set_node_api_version(base_url, "v3")
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.update_client(
            _node(), inbound_id=17, client_uuid="client-uuid", updates={"enable": False}
        ) is False

    assert request.call_count == 1
    assert request.call_args.args[1:] == ("GET", f"{base_url}/panel/api/clients/list")
    invalidate_node_api_version(base_url)
