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
