"""Client-manager compatibility decisions must not confuse outages with v2."""
import json
import os
import sys
from unittest.mock import MagicMock, call, patch


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


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

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.get_all_clients([_node()]) == []

    assert request.call_count == 1
    assert request.call_args.args[2].endswith("/panel/api/clients/list")


def test_v3_list_404_selects_legacy_projection():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
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
    # A v3 route absence is operation-specific; no node-wide v2 downgrade.


def test_strict_node_read_rejects_v3_failure_instead_of_treating_it_as_empty():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ):
        try:
            manager.get_node_clients_strict(_node())
        except RuntimeError as exc:
            assert "unavailable" in str(exc)
        else:
            raise AssertionError("strict provisioning read must reject an uncertain empty result")


def test_strict_node_read_accepts_verified_legacy_empty_or_client_projection():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    legacy = {
        "success": True,
        "obj": [{"id": 1, "settings": '{"clients":[{"id":"id-1","email":"legacy@example.test","subId":"s-1","flow":"xtls-rprx-vision"}]}' }],
    }
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", side_effect=[_response(404), _response(200, legacy)]
    ):
        clients = manager.get_node_clients_strict(_node())

    assert clients == [{
        "id": "id-1", "email": "legacy@example.test", "enable": True,
        "expiryTime": 0, "totalGB": 0, "subId": "s-1", "flow": "xtls-rprx-vision",
        "inbound_id": 1, "inbound_ids": [1],
    }]


def test_strict_inbound_contract_requires_enabled_vless_tls_or_reality():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    response_payload = {
        "success": True,
        "obj": [{"id": 1, "enable": True, "protocol": "vless", "streamSettings": '{"security":"reality"}'}],
    }
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(200, response_payload)
    ):
        assert manager.inbound_supports_telegram_contract_strict(_node(), 1) is True

    response_payload["obj"][0]["streamSettings"] = '{"security":"none"}'
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(200, response_payload)
    ):
        assert manager.inbound_supports_telegram_contract_strict(_node(), 1) is False


def test_v3_paged_clients_uses_exact_query_and_strips_full_client_fields():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    paged = {
        "success": True,
        "obj": {
            "items": [{
                "uuid": "must-not-leak-into-slim-row",
                "password": "must-not-leak",
                "flow": "xtls-rprx-vision",
                "email": "alice@example.test",
                "subId": "sub-1",
                "enable": True,
                "totalGB": 100,
                "inboundIds": [3],
                "traffic": {"up": 4, "down": 5},
            }],
            "total": 1,
            "filtered": 1,
            "page": 2,
            "pageSize": 10,
            "summary": {"total": 1, "online": ["alice@example.test"]},
        },
    }
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(200, paged)
    ) as request:
        result = manager.get_node_clients_paged(
            _node(), page=2, page_size=10, search="alice", status_filter="active", protocol="vless"
        )

    assert request.call_args.args[1:] == ("GET", f"{base_url}/panel/api/clients/list/paged")
    assert request.call_args.kwargs["params"] == {
        "page": 2, "pageSize": 10, "search": "alice", "filter": "active",
        "protocol": "vless", "sort": "email", "order": "ascend",
    }
    assert result["detail_level"] == "slim"
    assert result["source"] == "v3_paged"
    assert result["items"] == [{
        "email": "alice@example.test", "subId": "sub-1", "enable": True,
        "totalGB": 100, "expiryTime": 0, "limitIp": 0, "reset": 0,
        "inboundIds": [3], "traffic": {"up": 4, "down": 5, "total": 9, "enable": True},
        "createdAt": 0, "updatedAt": 0,
    }]


def test_v3_paged_clients_reauthenticates_before_legacy_projection():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    legacy = {"items": [], "total": 0, "filtered": 0, "page": 1, "pageSize": 25, "summary": {}}
    with patch.object(
        manager, "_get_session", side_effect=[(MagicMock(), base_url), (MagicMock(), base_url)]
    ) as sessions, patch(
        "client_manager.xui_request", side_effect=[_response(404), _response(405)]
    ) as request, patch.object(manager, "_legacy_paged_clients", return_value=legacy) as fallback:
        result = manager.get_node_clients_paged(_node())

    assert request.call_count == 2
    assert all(call.args[2].endswith("/panel/api/clients/list/paged") for call in request.call_args_list)
    assert sessions.call_args_list[1].kwargs == {"force_reauth": True}
    fallback.assert_called_once()
    assert result["source"] == "legacy_projection"


def test_v3_paged_clients_5xx_is_terminal_and_never_reads_legacy():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel.example.test")), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request, patch.object(manager, "_legacy_paged_clients") as fallback:
        assert manager.get_node_clients_paged(_node()) is None

    request.assert_called_once()
    fallback.assert_not_called()


def test_v3_paged_clients_malformed_response_is_terminal_and_never_reads_legacy():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    malformed = _response(200)
    malformed.json.side_effect = ValueError("not json")
    with patch.object(manager, "_get_session", return_value=(MagicMock(), "https://panel.example.test")), patch(
        "client_manager.xui_request", return_value=malformed
    ) as request, patch.object(manager, "_legacy_paged_clients") as fallback:
        assert manager.get_node_clients_paged(_node()) is None

    request.assert_called_once()
    fallback.assert_not_called()


def test_v3_update_reads_full_record_without_undocumented_inbound_query():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
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
    assert update_call.args[1:] == ("POST", f"{base_url}/panel/api/clients/update/old%40example.test")
    payload = update_call.kwargs["json"]
    assert payload["id"] == "client-uuid"
    assert payload["email"] == "renamed@example.test"
    assert payload["totalGB"] == 99
    assert payload["password"] == "preserved-panel-secret"
    assert payload["expiryTime"] == 123456789
    assert payload["reverse"] == {"enabled": True}
    assert payload["allowedIPs"] == ["10.0.0.2/32"]
def test_v3_update_does_not_write_when_the_read_contract_fails():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.update_client(
            _node(), inbound_id=17, client_uuid="client-uuid", updates={"enable": False}
        ) is False

    assert request.call_count == 1
    assert request.call_args.args[1:] == ("GET", f"{base_url}/panel/api/clients/list")


def test_v3_reset_client_traffic_uses_documented_encoded_email_route():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(200, {"success": True})
    ) as request:
        assert manager.reset_client_traffic(_node(), inbound_id=17, client_email="first+name@example.test") is True

    assert request.call_args.args[1:] == (
        "POST", f"{base_url}/panel/api/clients/resetTraffic/first%2Bname%40example.test"
    )
    assert request.call_args.kwargs == {}


def test_v3_reset_client_traffic_uses_v2_only_when_modern_route_is_absent():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", side_effect=[_response(404), _response(404), _response(200, {"success": True})]
    ) as request:
        assert manager.reset_client_traffic(_node(), inbound_id=17, client_email="user@example.test") is True

    modern_call, reauth_modern_call, legacy_call = request.call_args_list
    assert modern_call.args[1:] == ("POST", f"{base_url}/panel/api/clients/resetTraffic/user%40example.test")
    assert reauth_modern_call.args[1:] == modern_call.args[1:]
    assert legacy_call.args[1:] == ("POST", f"{base_url}/panel/api/inbounds/resetClientTraffic/user%40example.test")
    assert legacy_call.kwargs["json"] == {"id": 17, "email": "user@example.test"}


def test_v3_reset_client_traffic_does_not_downgrade_on_reachable_route_failure():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.reset_client_traffic(_node(), inbound_id=17, client_email="user@example.test") is False

    assert request.call_count == 1
    assert request.call_args.args[1:] == (
        "POST", f"{base_url}/panel/api/clients/resetTraffic/user%40example.test"
    )


def test_v3_bulk_reset_uses_documented_bulk_route_on_success():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    emails = ["first@example.test", "second@example.test"]
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(200, {"success": True})
    ) as request:
        assert manager.bulk_reset_traffic([_node()], emails) == {
            "successful": 2,
            "failed": 0,
            "total": 2,
        }

    assert request.call_count == 1
    assert request.call_args.args[1:] == ("POST", f"{base_url}/panel/api/clients/bulkResetTraffic")
    assert request.call_args.kwargs == {"json": {"emails": emails}}


def test_v3_bulk_reset_does_not_retry_a_reachable_failure_through_another_route():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.bulk_reset_traffic([_node()], ["first@example.test", "second@example.test"]) == {
            "successful": 0,
            "failed": 2,
            "total": 2,
        }

    assert request.call_count == 1
    assert request.call_args.args[1:] == ("POST", f"{base_url}/panel/api/clients/bulkResetTraffic")


def test_v3_bulk_reset_rejects_a_non_success_payload_without_a_retry():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(200, {"success": False})
    ) as request:
        assert manager.bulk_reset_traffic([_node()], ["first@example.test"]) == {
            "successful": 0,
            "failed": 1,
            "total": 1,
        }

    assert request.call_count == 1
    assert request.call_args.args[1:] == ("POST", f"{base_url}/panel/api/clients/bulkResetTraffic")


def test_v3_bulk_reset_uses_single_v3_route_only_after_bulk_route_is_absent():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    emails = ["first+name@example.test", "second@example.test"]
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request",
        side_effect=[_response(404), _response(200, {"success": True}), _response(200, {"success": True})],
    ) as request:
        assert manager.bulk_reset_traffic([_node()], emails) == {
            "successful": 2,
            "failed": 0,
            "total": 2,
        }

    bulk_call, first_single_call, second_single_call = request.call_args_list
    assert bulk_call.args[1:] == ("POST", f"{base_url}/panel/api/clients/bulkResetTraffic")
    assert first_single_call.args[1:] == (
        "POST", f"{base_url}/panel/api/clients/resetTraffic/first%2Bname%40example.test"
    )
    assert second_single_call.args[1:] == (
        "POST", f"{base_url}/panel/api/clients/resetTraffic/second%40example.test"
    )


def test_v3_bulk_reset_never_guesses_a_legacy_inbound_request_when_single_route_is_absent():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", side_effect=[_response(405), _response(404)]
    ) as request:
        assert manager.bulk_reset_traffic([_node()], ["first@example.test"]) == {
            "successful": 0,
            "failed": 1,
            "total": 1,
        }

    assert [call.args[2] for call in request.call_args_list] == [
        f"{base_url}/panel/api/clients/bulkResetTraffic",
        f"{base_url}/panel/api/clients/resetTraffic/first%40example.test",
    ]


def test_v3_delete_resolves_uuid_to_current_encoded_email_before_write():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    listed = _response(200, {"success": True, "obj": [{"uuid": "client-uuid", "email": "old+name@example.test"}]})
    deleted = _response(200, {"success": True})
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", side_effect=[listed, deleted]
    ) as request:
        assert manager.delete_client(_node(), inbound_id=17, client_uuid="client-uuid") is True

    list_call, delete_call = request.call_args_list
    assert list_call.args[1:] == ("GET", f"{base_url}/panel/api/clients/list")
    assert delete_call.args[1:] == ("POST", f"{base_url}/panel/api/clients/del/old%2Bname%40example.test?keepTraffic=0")


def test_v3_delete_does_not_write_when_uuid_resolution_fails():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.delete_client(_node(), inbound_id=17, client_uuid="client-uuid") is False

    assert request.call_count == 1
    assert request.call_args.args[1:] == ("GET", f"{base_url}/panel/api/clients/list")


def test_v3_write_404_requires_reauth_before_one_legacy_write():
    """An expired session must not turn a first v3 404 into an immediate v2 write."""
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request",
        side_effect=[_response(404), _response(404), _response(200, {"success": True})],
    ) as request:
        assert manager.add_client(_node(), 17, {"id": "uuid", "email": "user@example.test"}) is True

    assert [entry.args[2] for entry in request.call_args_list] == [
        f"{base_url}/panel/api/clients/add",
        f"{base_url}/panel/api/clients/add",
        f"{base_url}/panel/api/inbounds/addClient",
    ]


def test_v3_write_reachable_error_never_calls_legacy_write():
    from client_manager import ClientManager

    manager = ClientManager(decrypt_func=lambda value: value)
    base_url = "https://198.51.100.8:443"
    with patch.object(manager, "_get_session", return_value=(MagicMock(), base_url)), patch(
        "client_manager.xui_request", return_value=_response(503)
    ) as request:
        assert manager.add_client(_node(), 17, {"id": "uuid", "email": "user@example.test"}) is False

    request.assert_called_once()
    assert request.call_args.args[2] == f"{base_url}/panel/api/clients/add"


def test_v3_client_mapping_keeps_client_fields_and_bytes_separate_from_quota():
    from client_manager import ClientManager

    mapped = ClientManager(decrypt_func=lambda value: value)._map_v3_client(
        {
            "id": 71,
            "uuid": "client-uuid",
            "email": "user@example.test",
            "limitIp": 3,
            "security": "aes-128-gcm",
            "subId": "subscription-id",
            "reset": 7,
            "group": "paid",
            "totalGB": 20 * 1024 ** 3,
            "traffic": {"up": 10, "down": 20, "total": 30},
        },
        {"id": 1, "name": "node"},
    )
    assert mapped["security"] == "aes-128-gcm"
    assert mapped["limitIp"] == 3
    assert mapped["totalGB"] == 20 * 1024 ** 3
    assert mapped["traffic_total"] == 30
    assert mapped["subId"] == "subscription-id"


class TestClientV3Contracts:
    base_url = "https://panel.example.test"

    @staticmethod
    def node():
        return {"name": "node-1", "ip": "panel.example.test", "port": 443, "read_only": False}

    @staticmethod
    def manager():
        from client_manager import ClientManager
        return ClientManager(decrypt_func=lambda value: value)

    def test_add_uses_v3_first(self):
        manager = self.manager()
        session = MagicMock()
        config = {"email": "alice@example.test", "enable": True}
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch.object(manager, "_add_client_v3", return_value=True) as modern_add,
        ):
            assert manager.add_client(self.node(), 7, config) is True

        # v3 is always tried before a compatibility fallback.
        modern_add.assert_called_once_with(session, self.base_url, email="alice@example.test", inbound_ids=[7], config=config)

    def test_client_links_treats_405_as_route_absence_without_json_parse(self):
        manager = self.manager()
        session = MagicMock()
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", return_value=_response(405)) as request,
        ):
            assert manager.get_client_links(self.node(), "name/tag?#") == []

        request.assert_called_once_with(
            session,
            "GET",
            f"{self.base_url}/panel/api/clients/links/name%2Ftag%3F%23",
        )

    def test_bulk_delete_503_never_replays_legacy_mutation(self):
        manager = self.manager()
        session = MagicMock()
        with (
            patch.object(manager, "get_all_clients", return_value=[{"email": "alice"}]),
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", return_value=_response(503)) as request,
            patch.object(manager, "delete_client") as legacy_delete,
        ):
            result = manager.batch_delete_clients([self.node()])

        assert request.call_count == 1
        legacy_delete.assert_not_called()
        assert result["results"][0]["deleted_count"] == 0
        assert "fallback skipped" in result["results"][0]["errors"][0]

    def test_bulk_delete_405_reauth_confirms_absence_before_legacy_fallback(self):
        manager = self.manager()
        session = MagicMock()
        fresh_session = MagicMock()
        client = {"email": "alice", "id": "legacy-id", "inbound_id": 2}
        with (
            patch.object(manager, "get_all_clients", return_value=[client]),
            patch.object(
                manager,
                "_get_session",
                side_effect=[(session, self.base_url), (fresh_session, self.base_url)],
            ),
            patch("client_manager.xui_request", side_effect=[_response(405), _response(405)]) as request,
            patch.object(manager, "delete_client", return_value=True) as legacy_delete,
        ):
            result = manager.batch_delete_clients([self.node()])

        assert request.call_count == 2
        assert request.call_args_list[1].args[:2] == (fresh_session, "POST")
        legacy_delete.assert_called_once_with(self.node(), 2, "legacy-id")
        assert result["results"][0]["deleted_count"] == 1

    def test_bulk_delete_405_then_503_never_replays_legacy_mutation(self):
        manager = self.manager()
        session = MagicMock()
        fresh_session = MagicMock()
        client = {"email": "alice", "id": "legacy-id", "inbound_id": 2}
        with (
            patch.object(manager, "get_all_clients", return_value=[client]),
            patch.object(
                manager,
                "_get_session",
                side_effect=[(session, self.base_url), (fresh_session, self.base_url)],
            ),
            patch("client_manager.xui_request", side_effect=[_response(405), _response(503)]) as request,
            patch.object(manager, "delete_client") as legacy_delete,
        ):
            result = manager.batch_delete_clients([self.node()])

        assert request.call_count == 2
        legacy_delete.assert_not_called()
        assert result["results"][0]["deleted_count"] == 0
        assert "fallback skipped" in result["results"][0]["errors"][0]

    def test_del_depleted_success_false_never_falls_back(self):
        manager = self.manager()
        with (
            patch.object(manager, "_get_session", return_value=(MagicMock(), self.base_url)),
            patch("client_manager.xui_request", return_value=_response(200, {"success": False})),
            patch.object(manager, "batch_delete_clients") as legacy_delete,
        ):
            result = manager.del_depleted([self.node()])

        legacy_delete.assert_not_called()
        assert result["results"][0]["deleted"] == 0
        assert result["results"][0]["error"] == "v3 delDepleted failed"

    def test_bulk_adjust_malformed_response_never_falls_back(self):
        manager = self.manager()
        with (
            patch.object(manager, "_get_session", return_value=(MagicMock(), self.base_url)),
            patch("client_manager.xui_request", return_value=_response(200, {"success": True, "obj": []})),
            patch.object(manager, "get_all_clients") as legacy_clients,
        ):
            result = manager.bulk_adjust([self.node()], ["alice"], add_days=1)

        legacy_clients.assert_not_called()
        assert result["results"][0]["adjusted"] == 0
        assert result["results"][0]["error"] == "v3 bulkAdjust malformed response"

    def test_v3_traffic_resolves_uuid_to_encoded_email(self):
        manager = self.manager()
        session = MagicMock()
        listed = _response(200, {"success": True, "obj": [{"uuid": "uuid-1", "email": "name+tag/one?#"}]})
        traffic = _response(200, {"success": True, "obj": {"up": 1, "down": 2}})
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", side_effect=[listed, traffic]) as request,
        ):
            result = manager.get_client_traffic(self.node(), "uuid-1", "vless")

        assert result == {"up": 1, "down": 2}
        assert request.call_args_list[1] == call(
            session, "GET", f"{self.base_url}/panel/api/clients/traffic/name%2Btag%2Fone%3F%23"
        )

    def test_v3_traffic_identity_503_does_not_issue_second_read(self):
        manager = self.manager()
        with (
            patch.object(manager, "_get_session", return_value=(MagicMock(), self.base_url)),
            patch("client_manager.xui_request", return_value=_response(503)) as request,
        ):
            assert manager.get_client_traffic(self.node(), "uuid-1", "vless") == {}
        assert request.call_count == 1

    def test_v3_traffic_email_uses_direct_encoded_read_without_client_list(self):
        manager = self.manager()
        session = MagicMock()
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch(
                "client_manager.xui_request",
                return_value=_response(200, {"success": True, "obj": {"up": 1, "down": 2}}),
            ) as request,
        ):
            assert manager.get_client_traffic(self.node(), "name+tag/one?#@example.test", "vless") == {"up": 1, "down": 2}

        request.assert_called_once_with(
            session,
            "GET",
            f"{self.base_url}/panel/api/clients/traffic/name%2Btag%2Fone%3F%23%40example.test",
        )

    def test_depleted_batch_uses_email_for_v3_then_uuid_for_v2_traffic_fallback(self):
        manager = self.manager()
        session = MagicMock()
        client = {
            "email": "alice@example.test",
            "id": "uuid-123",
            "inbound_id": 2,
            "protocol": "vless",
            "totalGB": 1,
        }
        with (
            patch.object(manager, "get_all_clients", return_value=[client]),
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch(
                "client_manager.xui_request",
                side_effect=[
                    _response(404),
                    _response(200, {"success": True, "obj": {"up": 2 * 1024 ** 3, "down": 0}}),
                    _response(405),
                    _response(405),
                ],
            ) as request,
            patch.object(manager, "delete_client", return_value=True) as legacy_delete,
        ):
            result = manager.batch_delete_clients([self.node()], depleted_only=True)

        assert request.call_args_list[:2] == [
            call(session, "GET", f"{self.base_url}/panel/api/clients/traffic/alice%40example.test"),
            call(session, "GET", f"{self.base_url}/panel/api/inbounds/getClientTrafficsById/uuid-123"),
        ]
        legacy_delete.assert_called_once_with(self.node(), 2, "uuid-123")
        assert result["results"][0]["deleted_count"] == 1

    def test_ip_dto_keeps_legacy_strings_and_exposes_details(self):
        manager = self.manager()
        session = MagicMock()
        response = _response(200, {"success": True, "obj": [
            {"ip": "203.0.113.1", "time": 123, "node": "edge-a"},
            "198.51.100.2",
        ]})
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", return_value=response) as request,
        ):
            result = manager.get_client_ips(self.node(), "name/tag?#")

        assert result == {
            "ips": ["203.0.113.1", "198.51.100.2"],
            "ip_details": [{"ip": "203.0.113.1", "time": 123, "node": "edge-a"}],
        }
        assert request.call_args == call(session, "POST", f"{self.base_url}/panel/api/clients/ips/name%2Ftag%3F%23")

    def test_last_online_filters_locally_without_ignored_remote_body(self):
        manager = self.manager()
        session = MagicMock()
        response = _response(200, {"success": True, "obj": {"alice": 1, "bob": 2}})
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", return_value=response) as request,
        ):
            result = manager.get_last_online(self.node(), ["bob"])

        assert result == {"data": {"bob": 2}}
        request.assert_called_once_with(session, "POST", f"{self.base_url}/panel/api/clients/lastOnline")

    def test_add_client_preserves_supported_v3_fields_and_405_is_only_fallback(self):
        manager = self.manager()
        session = MagicMock()
        config = {
            "id": "uuid-1", "enable": False, "totalGB": 1024, "expiryTime": 99,
            "flow": "none", "subId": "sub-1", "group": "team-a", "comment": "note",
            "reset": 3, "password": "protocol-password", "security": "auto",
            "reverse": {"enabled": True, "tag": "reverse-a"}, "auth": "hy2-auth",
            "privateKey": "private", "publicKey": "public", "allowedIPs": ["0.0.0.0/0"],
            "preSharedKey": "psk", "keepAlive": 20, "secret": "tuic-secret", "adTag": "ad-tag",
        }
        with patch("client_manager.xui_request", return_value=_response(200, {"success": True})) as request:
            assert manager._add_client_v3(session, self.base_url, "alice", [1], config) is True
        payload = request.call_args.kwargs["json"]["client"]
        for field in (
            "id", "flow", "subId", "group", "comment", "reset", "password", "security",
            "reverse", "auth", "privateKey", "publicKey", "allowedIPs", "preSharedKey",
            "keepAlive", "secret", "adTag",
        ):
            assert payload[field] == config[field]
        assert payload["flow"] == "none"

        with patch("client_manager.xui_request", return_value=_response(405)):
            assert manager._add_client_v3(session, self.base_url, "alice", [1], config) is None
        with patch("client_manager.xui_request", return_value=_response(200, {"success": False})):
            assert manager._add_client_v3(session, self.base_url, "alice", [1], config) is False

    def test_special_path_segments_remain_one_segment(self):
        manager = self.manager()
        session = MagicMock()
        success = _response(200, {"success": True, "obj": []})
        identifier = "name+part/one?#"
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", return_value=success) as request,
        ):
            assert manager.attach_client(self.node(), identifier, [2]) is True
            assert manager.detach_client(self.node(), identifier, [2]) is True
            assert manager.get_group_emails(self.node(), identifier) == {"emails": []}
            assert manager.get_sub_links(self.node(), identifier) == []

        encoded = "name%2Bpart%2Fone%3F%23"
        assert request.call_args_list == [
            call(session, "POST", f"{self.base_url}/panel/api/clients/{encoded}/attach", json={"inboundIds": [2]}),
            call(session, "POST", f"{self.base_url}/panel/api/clients/{encoded}/detach", json={"inboundIds": [2]}),
            call(session, "GET", f"{self.base_url}/panel/api/clients/groups/{encoded}/emails"),
            call(session, "GET", f"{self.base_url}/panel/api/clients/subLinks/{encoded}"),
        ]

    def test_legacy_update_client_encodes_opaque_identifier(self):
        manager = self.manager()
        session = MagicMock()
        identifier = "uuid/with?#"
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", side_effect=[_response(404), _response(404), _response(200, {"success": True})]) as request,
        ):
            assert manager.update_client(self.node(), 3, identifier, {"enable": False}) is True

        assert request.call_args == call(
            session,
            "POST",
            f"{self.base_url}/panel/api/inbounds/updateClient/uuid%2Fwith%3F%23",
            json={"id": 3, "settings": json.dumps({"clients": [{"id": identifier, "enable": False}]})},
        )

    def test_reset_all_traffic_uses_documented_global_and_per_inbound_routes(self):
        manager = self.manager()
        session = MagicMock()
        success = _response(200, {"success": True})
        with (
            patch.object(manager, "_get_session", return_value=(session, self.base_url)),
            patch("client_manager.xui_request", return_value=success) as request,
        ):
            assert manager.reset_all_traffic([self.node()])["results"][0]["reset_count"] == 1
            assert manager.reset_all_traffic([self.node()], inbound_id=7)["results"][0]["reset_count"] == 1

        assert request.call_args_list == [
            call(session, "POST", f"{self.base_url}/panel/api/inbounds/resetAllTraffics"),
            call(session, "POST", f"{self.base_url}/panel/api/inbounds/7/resetTraffic"),
        ]
