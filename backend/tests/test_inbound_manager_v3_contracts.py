"""Mock-only contracts for current 3x-ui inbound lifecycle operations."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _response(status_code=200, body=None, *, json_error=False):
    response = MagicMock()
    response.status_code = status_code
    response.text = json.dumps(body) if body is not None else ""
    if json_error:
        response.json.side_effect = ValueError("malformed response")
    else:
        response.json.return_value = body
    return response


class TestInboundManagerV3Contracts:
    def _manager(self):
        from inbound_manager import InboundManager

        return InboundManager(decrypt_func=lambda value: value)

    @staticmethod
    def _node():
        return {
            "name": "v3-node",
            "ip": "203.0.113.15",
            "port": 443,
            "scheme": "https",
            "base_path": "panel-prefix",
            "user": "admin",
            "password": "not-a-secret",
        }

    @pytest.mark.parametrize(
        ("operation", "expected_path"),
        [
            ("add", "/panel/api/inbounds/add"),
            ("delete", "/panel/api/inbounds/del/41"),
            ("reset", "/panel/api/inbounds/41/resetTraffic"),
            ("delete_clients", "/panel/api/inbounds/41/delAllClients"),
        ],
    )
    def test_v3_lifecycle_uses_documented_routes(self, operation, expected_path):
        manager = self._manager()
        response_body = {"success": True, "obj": {"deleted": 3}}

        with patch("inbound_manager.login_panel", return_value=True), patch(
            "inbound_manager.xui_request", return_value=_response(body=response_body)
        ) as request:
            if operation == "add":
                result = manager.add_inbound(self._node(), {"protocol": "vless", "port": 443})
            elif operation == "delete":
                result = manager.delete_inbound(self._node(), 41)
            elif operation == "reset":
                result = manager.reset_inbound_traffic(self._node(), 41)
            else:
                result = manager.del_all_inbound_clients(self._node(), 41)

        request.assert_called_once()
        assert request.call_args.args[2].endswith(expected_path)
        assert result == ({"deleted": 3} if operation == "delete_clients" else True)

    def test_update_deep_merges_current_v3_payload_without_dropping_unknown_fields(self):
        manager = self._manager()
        current = {
            "id": 41,
            "protocol": "vless",
            "remark": "old",
            "futureInboundField": {"retained": True},
            "settings": json.dumps(
                {
                    "clients": [],
                    "decryption": "none",
                    "futureSettings": {"keep": True},
                }
            ),
            "streamSettings": json.dumps(
                {
                    "network": "xhttp",
                    "security": "reality",
                    "xhttpSettings": {"path": "/old", "mode": "auto", "futureXhttp": "keep"},
                    "realitySettings": {"serverNames": ["example.test"], "futureReality": "keep"},
                }
            ),
            "sniffing": {"enabled": True, "destOverride": ["http"], "futureSniffing": "keep"},
            "allocate": {"strategy": "always", "futureAllocate": "keep"},
        }
        updates = {
            "remark": "new",
            "settings": {"decryption": "aes-128-gcm"},
            "streamSettings": {"xhttpSettings": {"path": "/new"}},
            "sniffing": {"enabled": False},
            "allocate": {"strategy": "random"},
        }

        with patch("inbound_manager.login_panel", return_value=True), patch.object(
            manager, "_fetch_inbounds_from_node", return_value=[current]
        ), patch("inbound_manager.xui_request", return_value=_response(body={"success": True})) as request:
            assert manager.update_inbound(self._node(), 41, updates) is True

        request.assert_called_once()
        assert request.call_args.args[2].endswith("/panel/api/inbounds/update/41")
        payload = request.call_args.kwargs["json"]
        assert payload["remark"] == "new"
        assert payload["futureInboundField"] == {"retained": True}

        settings = json.loads(payload["settings"])
        stream = json.loads(payload["streamSettings"])
        assert settings["decryption"] == "aes-128-gcm"
        assert settings["futureSettings"] == {"keep": True}
        assert stream["xhttpSettings"] == {"path": "/new", "mode": "auto", "futureXhttp": "keep"}
        assert stream["realitySettings"] == {"serverNames": ["example.test"], "futureReality": "keep"}
        assert payload["sniffing"] == {"enabled": False, "destOverride": ["http"], "futureSniffing": "keep"}
        assert payload["allocate"] == {"strategy": "random", "futureAllocate": "keep"}

    def test_update_does_not_write_when_current_inbound_read_failed(self):
        manager = self._manager()
        with patch("inbound_manager.login_panel", return_value=True), patch.object(
            manager, "_fetch_inbounds_from_node", return_value=[]
        ), patch("inbound_manager.xui_request") as request:
            assert manager.update_inbound(self._node(), 41, {"remark": "new"}) is False

        request.assert_not_called()

    def test_list_projection_keeps_listen_and_sniffing_in_panel_shape(self):
        manager = self._manager()
        source_sniffing = '{"enabled":true,"destOverride":["http"],"futureSniffing":"keep"}'
        source = {
            "id": 41,
            "protocol": "vless",
            "port": 443,
            "remark": "reality",
            "enable": True,
            "listen": "127.0.0.1",
            "settings": {"clients": []},
            "streamSettings": {"network": "tcp", "security": "reality"},
            "sniffing": source_sniffing,
        }

        with patch.object(manager, "_fetch_inbounds_from_node", return_value=[source]):
            rows = manager.get_all_inbounds([self._node()])

        assert rows[0]["listen"] == "127.0.0.1"
        # v3 panels may return JSON text here; preserve it for the UI rather
        # than converting an edit into a lossy default object.
        assert rows[0]["sniffing"] == source_sniffing

    def test_clone_keeps_full_v3_config_without_server_owned_fields_or_shared_state(self):
        manager = self._manager()
        source = {
            "id": 41,
            "protocol": "vless",
            "port": 443,
            "remark": "source",
            "enable": False,
            "listen": "127.0.0.1",
            "settings": json.dumps({"clients": [{"id": "client-1"}], "decryption": "none", "future": {"keep": True}}),
            "streamSettings": {"network": "xhttp", "future": {"values": ["source"]}},
            "sniffing": '{"enabled":true,"futureSniffing":"keep"}',
            "allocate": {"strategy": "always"},
            "subSortIndex": 7,
            "trafficReset": "monthly",
            "trafficResetDay": 3,
            "total": 1234,
            "expiryTime": 5678,
            "shareAddrStrategy": "custom",
            "tag": "in-443-xhttp",
            "nodeId": 9,
            "originNodeGuid": "node-guid",
            "fallbackParent": {"masterId": 3},
            "clientStats": [{"email": "client-1"}],
            "up": 100,
            "down": 200,
            "lastTrafficResetTime": 300,
        }
        captured = []

        def add_and_mutate_target_payload(node, payload):
            captured.append(payload)
            payload["streamSettings"]["future"]["values"].append(node["name"])
            return True

        targets = [
            {**self._node(), "name": "target-a"},
            {**self._node(), "name": "target-b"},
        ]
        with patch.object(manager, "_fetch_inbounds_from_node", return_value=[source]), patch.object(
            manager, "add_inbound", side_effect=add_and_mutate_target_payload
        ):
            result = manager.clone_inbound(
                self._node(),
                41,
                targets,
                {"remark": "clone", "port": 8443},
            )

        assert [row["success"] for row in result["results"]] == [True, True]
        assert source["streamSettings"]["future"]["values"] == ["source"]
        assert captured[0]["streamSettings"]["future"]["values"] == ["source", "target-a"]
        assert captured[1]["streamSettings"]["future"]["values"] == ["source", "target-b"]
        for payload in captured:
            assert payload["remark"] == "clone"
            assert payload["port"] == 8443
            assert payload["enable"] is False
            assert payload["listen"] == "127.0.0.1"
            assert payload["sniffing"] == source["sniffing"]
            assert json.loads(payload["settings"]) == {
                "clients": [],
                "decryption": "none",
                "future": {"keep": True},
            }
            for server_owned in (
                "id", "tag", "nodeId", "originNodeGuid", "fallbackParent",
                "clientStats", "up", "down", "lastTrafficResetTime",
            ):
                assert server_owned not in payload

    @pytest.mark.parametrize(
        "response",
        [
            _response(status_code=503, body={"success": False}),
            _response(status_code=200, body={"success": False}),
            _response(status_code=200, json_error=True),
        ],
    )
    def test_set_enable_never_replays_a_reachable_modern_failure(self, response):
        manager = self._manager()
        with patch("inbound_manager.login_panel", return_value=True), patch(
            "inbound_manager.xui_request", return_value=response
        ) as request, patch.object(manager, "update_inbound") as fallback:
            assert manager.set_inbound_enable(self._node(), 41, False) is False

        request.assert_called_once()
        assert request.call_args.args[2].endswith("/panel/api/inbounds/setEnable/41")
        fallback.assert_not_called()

    @pytest.mark.parametrize("status_code", [404, 405])
    def test_set_enable_allows_full_update_fallback_only_when_route_is_absent(self, status_code):
        manager = self._manager()
        with patch("inbound_manager.login_panel", return_value=True), patch(
            "inbound_manager.xui_request", return_value=_response(status_code=status_code, body={"success": False})
        ), patch.object(manager, "update_inbound", return_value=True) as fallback:
            assert manager.set_inbound_enable(self._node(), 41, False) is True

        fallback.assert_called_once_with(self._node(), 41, {"enable": False})
