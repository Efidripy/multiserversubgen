"""Mock-only v3.6 server-operations contracts for ServerMonitor."""
import os
import sys
from unittest.mock import MagicMock, call, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.server_ops import build_server_ops_router
from server_monitor import ServerMonitor


def _response(status_code, body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {} if body is None else body
    return response


def _node(read_only=False):
    return {
        "name": "node-1",
        "ip": "127.0.0.1",
        "port": 443,
        "base_path": "",
        "user": "admin",
        "password": "password",
        "read_only": read_only,
    }


class TestServerMonitorV3OpsContracts:
    def _monitor(self):
        return ServerMonitor(decrypt_func=lambda value: value)

    def test_status_facade_delegates_to_current_monitor(self):
        monitor = self._monitor()
        expected = {"node": "node-1", "available": True, "status": "online"}
        with patch("server_monitor.ThreeXUIMonitor.get_server_status", return_value=expected) as status:
            assert monitor.get_server_status(_node()) == expected
        status.assert_called_once_with(_node())

    def test_get_xray_config_uses_documented_get_route_and_preserves_string_obj(self):
        monitor = self._monitor()
        session = MagicMock()
        body = {"success": True, "obj": '{"inbounds":[]}' }
        with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
            with patch("server_monitor.xui_request", return_value=_response(200, body)) as request:
                assert monitor.get_xray_config(_node()) == body
        request.assert_called_once_with(session, "GET", "https://panel.test/panel/api/server/getConfigJson")

    def test_current_token_and_outbound_routes(self):
        monitor = self._monitor()
        session = MagicMock()
        list_body = {"success": True, "obj": [{"id": 1, "name": "ops", "enabled": True}]}
        token_body = {"success": True, "obj": {"id": 2, "name": "new", "token": "ephemeral"}}
        outbound_body = {"success": True, "obj": [{"tag": "proxy", "up": 1, "down": 2}]}
        success = _response(200, {"success": True})
        with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
            with patch(
                "server_monitor.xui_request",
                side_effect=[
                    _response(200, list_body),
                    _response(200, token_body),
                    success,
                    success,
                    _response(200, outbound_body),
                ],
            ) as request:
                assert monitor.get_api_tokens(_node())["tokens"] == list_body["obj"]
                assert monitor.create_api_token(_node(), "new") == token_body["obj"]
                assert monitor.delete_api_token(_node(), 2) is True
                assert monitor.set_api_token_enabled(_node(), 2, False) is True
                assert monitor.get_outbounds_traffic(_node())["outbounds"] == outbound_body["obj"]

        assert request.call_args_list == [
            call(session, "GET", "https://panel.test/panel/api/setting/apiTokens"),
            call(session, "POST", "https://panel.test/panel/api/setting/apiTokens/create", json={"name": "new"}),
            call(session, "POST", "https://panel.test/panel/api/setting/apiTokens/delete/2"),
            call(
                session,
                "POST",
                "https://panel.test/panel/api/setting/apiTokens/setEnabled/2",
                json={"enabled": False},
            ),
            call(session, "GET", "https://panel.test/panel/api/xray/getOutboundsTraffic"),
        ]

    def test_token_and_telegram_mutations_do_not_escape_read_only_node(self):
        monitor = self._monitor()
        with patch.object(monitor, "_get_session") as session:
            assert monitor.create_api_token(_node(True), "new") == {"error": "read-only"}
            assert monitor.delete_api_token(_node(True), 2) is False
            assert monitor.set_api_token_enabled(_node(True), 2, False) is False
            assert monitor.backup_to_telegram(_node(True)) == {"error": "read-only"}
        session.assert_not_called()

    def test_restart_uses_legacy_only_after_404_or_405(self):
        monitor = self._monitor()
        session = MagicMock()
        with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
            with patch(
                "server_monitor.xui_request",
                side_effect=[_response(405), _response(200, {"success": True})],
            ) as request:
                assert monitor.restart_xray(_node()) is True
        assert request.call_args_list == [
            call(session, "POST", "https://panel.test/panel/api/server/restartXrayService", timeout=15),
            call(session, "POST", "https://panel.test/server/restartXrayService", timeout=15),
        ]

    def test_restart_does_not_repeat_write_after_reachable_failure(self):
        monitor = self._monitor()
        session = MagicMock()
        for response in (_response(503, {"success": False}), _response(200, {"success": False})):
            with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
                with patch("server_monitor.xui_request", return_value=response) as request:
                    assert monitor.restart_xray(_node()) is False
            request.assert_called_once_with(
                session, "POST", "https://panel.test/panel/api/server/restartXrayService", timeout=15
            )

    def test_import_does_not_repeat_write_after_reachable_failure(self):
        monitor = self._monitor()
        session = MagicMock()
        with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
            with patch("server_monitor.xui_request", return_value=_response(503, {"success": False})) as request:
                assert monitor.import_database_backup(_node(), "U1FMaXRlIGZvcm1hdCAzAA==") is False
        request.assert_called_once()
        assert request.call_args.args[:3] == (session, "POST", "https://panel.test/panel/api/server/importDB")

    def test_server_logs_accepts_405_as_route_absence(self):
        monitor = self._monitor()
        session = MagicMock()
        with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
            with patch(
                "server_monitor.xui_request",
                side_effect=[_response(405), _response(200, {"success": True, "obj": "line"})],
            ) as request:
                assert monitor.get_server_logs(_node(), count=10)["logs"] == ["line"]
        assert request.call_args_list == [
            call(session, "POST", "https://panel.test/panel/api/server/logs/10", json={"level": "info", "syslog": False}, timeout=15),
            call(session, "POST", "https://panel.test/panel/api/server/logs", json={"count": 10, "level": "info", "syslog": False}),
        ]

    def test_invalid_history_parameters_do_not_open_a_node_session(self):
        monitor = self._monitor()
        with patch.object(monitor, "_get_session") as session:
            result = monitor.get_server_history(_node(), "disk", "5m")
        assert result == {"node": "node-1", "error": "invalid history bucket", "data": []}
        session.assert_not_called()

    def test_history_uses_documented_default_bucket(self):
        monitor = self._monitor()
        session = MagicMock()
        body = {"success": True, "obj": []}
        with patch.object(monitor, "_get_session", return_value=(session, "https://panel.test")):
            with patch("server_monitor.xui_request", return_value=_response(200, body)) as request:
                assert monitor.get_server_history(_node(), "cpu")["data"] == []
        request.assert_called_once_with(
            session, "GET", "https://panel.test/panel/api/server/history/cpu/360"
        )


class TestServerOpsRouterContracts:
    def _client(self, monitor):
        app = FastAPI()
        app.include_router(
            build_server_ops_router(
                check_auth=lambda _request: {"username": "admin"},
                xui_monitor=MagicMock(),
                server_monitor=monitor,
                get_node_or_404=lambda _node_id: _node(),
            )
        )
        return TestClient(app)

    def test_invalid_history_is_rejected_before_node_lookup_or_monitor_call(self):
        monitor = MagicMock()
        response = self._client(monitor).get("/api/v1/nodes/1/server-history/disk?bucket=300")
        assert response.status_code == 400
        monitor.get_server_history.assert_not_called()

    def test_token_create_response_is_not_cacheable(self):
        monitor = MagicMock()
        monitor.create_api_token.return_value = {"id": 2, "name": "new", "token": "ephemeral"}
        response = self._client(monitor).post("/api/v1/nodes/1/api-tokens", json={"name": "new"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"id": 2, "name": "new", "token": "ephemeral"}
