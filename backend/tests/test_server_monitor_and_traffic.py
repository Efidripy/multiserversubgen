"""Tests for server_monitor.py endpoint fix and client_manager.py traffic hardening."""
import sys
import os
import json
from unittest.mock import MagicMock, patch, call


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code, body=None, url=None):
    """Create a minimal mock response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = url or ""
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.return_value = {}
        resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# server_monitor – endpoint selection
# ---------------------------------------------------------------------------

class TestServerMonitorEndpoint:
    """The legacy facade must delegate to the canonical v3 GET adapter."""

    def _build_monitor(self):
        from server_monitor import ServerMonitor
        monitor = ServerMonitor(decrypt_func=lambda x: x)
        return monitor

    def _node(self):
        return {"name": "n1", "ip": "1.2.3.4", "port": 443,
                "base_path": "", "user": "admin", "password": "pass"}

    def test_status_facade_delegates_to_three_xui_monitor(self):
        monitor = self._build_monitor()
        expected = {"node": "n1", "available": True, "source": "three-x-ui"}
        with patch("server_monitor.ThreeXUIMonitor.get_server_status", return_value=expected) as delegated:
            result = monitor.get_server_status(self._node())

        delegated.assert_called_once_with(self._node())
        assert result is expected


# ---------------------------------------------------------------------------
# client_manager – get_client_traffic hardening
# ---------------------------------------------------------------------------

class TestGetClientTrafficHardening:
    """Verify that get_client_traffic never returns a non-dict."""

    def _build_manager(self):
        from client_manager import ClientManager
        return ClientManager(decrypt_func=lambda x: x)

    def _node(self):
        return {"name": "n1", "ip": "1.2.3.4", "port": 443,
                "base_path": "", "user": "admin", "password": "pass"}

    def test_normal_dict_obj_returned(self):
        mgr = self._build_manager()
        listed = _make_response(200, {"success": True, "obj": [{"uuid": "uuid1", "email": "user@example.test"}]})
        traffic_response = _make_response(200, {"success": True, "obj": {"up": 100, "down": 200}})

        with patch.object(mgr, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("client_manager.xui_request", side_effect=[listed, traffic_response]):
                traffic = mgr.get_client_traffic(self._node(), "uuid1", "vless")

        assert traffic == {"up": 100, "down": 200}

    def test_get_session_preserves_panel_url_path_for_session_pool(self):
        mgr = self._build_manager()
        node = {
            **self._node(),
            "panel_url": "https://panel.example.test/secret-path",
            "ip": "panel.example.test",
            "base_path": "",
        }
        session = MagicMock()
        captured = {}

        def fake_get_authenticated_session(**kwargs):
            captured.update(kwargs)
            return {
                "ok": True,
                "session": session,
                "base_url": kwargs["base_url"],
                "cached": False,
            }

        with patch("client_manager.get_authenticated_session", side_effect=fake_get_authenticated_session):
            result_session, base_url = mgr._get_session(node)

        assert result_session is session
        assert base_url == "https://panel.example.test/secret-path"
        assert captured["node_key"] == "panel.example.test:443:secret-path"
        assert captured["base_url"] == "https://panel.example.test/secret-path"

    def test_list_obj_returns_empty_dict(self):
        """When node panel returns a list for obj, must return {} not crash."""
        mgr = self._build_manager()
        body = {"success": True, "obj": [{"up": 100, "down": 200}]}
        resp = _make_response(200, body)

        with patch.object(mgr, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("client_manager.xui_request", return_value=resp):
                traffic = mgr.get_client_traffic(self._node(), "uuid1", "trojan")

        assert traffic == {}

    def test_list_obj_does_not_break_get_traffic_stats(self):
        """get_traffic_stats must not raise AttributeError when node panel returns a list for obj."""
        mgr = self._build_manager()

        inbound = {
            "id": 1, "remark": "ib1", "protocol": "vless",
            "settings": json.dumps({"clients": [{"id": "uid1", "email": "u@t.com"}]})
        }

        # API response with obj as list (unexpected but real-world case)
        list_body = {"success": True, "obj": [{"up": 100, "down": 200}]}
        resp = _make_response(200, list_body)

        with patch.object(mgr, '_fetch_inbounds_from_node', return_value=[inbound]):
            with patch.object(mgr, '_get_session') as mock_gs:
                sess = MagicMock()
                mock_gs.return_value = (sess, "https://1.2.3.4:443")
                with patch("client_manager.xui_request", return_value=resp):
                    result = mgr.get_traffic_stats([self._node()])

        assert "stats" in result
        # Client entry should have zeroed traffic (list obj treated as empty)
        assert result["stats"].get("u@t.com", {}).get("up", 0) == 0

    def test_none_obj_returns_empty_dict(self):
        """obj=null in response must return {}."""
        mgr = self._build_manager()
        body = {"success": True, "obj": None}
        resp = _make_response(200, body)

        with patch.object(mgr, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("client_manager.xui_request", return_value=resp):
                traffic = mgr.get_client_traffic(self._node(), "uid", "vmess")

        assert traffic == {}


class TestTrafficStatsFastPath:
    """Verify get_traffic_stats uses clientStats from inbounds/list when available."""

    def _build_manager(self):
        from client_manager import ClientManager
        return ClientManager(decrypt_func=lambda x: x)

    def _node(self):
        return {"name": "n1", "ip": "1.2.3.4", "port": 443,
                "base_path": "", "user": "admin", "password": "pass"}

    def test_client_stats_aggregated_without_per_client_calls(self):
        mgr = self._build_manager()
        inbounds = [{
            "id": 1,
            "remark": "ib1",
            "protocol": "vless",
            "clientStats": [
                {"email": "a@test.com", "up": 100, "down": 200},
                {"email": "b@test.com", "up": 50, "down": 25},
            ],
        }]

        with patch.object(mgr, "_fetch_inbounds_from_node", return_value=inbounds):
            with patch.object(mgr, "get_client_traffic") as mock_get_client_traffic:
                result = mgr.get_traffic_stats([self._node()], group_by="client")

        mock_get_client_traffic.assert_not_called()
        assert result["stats"]["a@test.com"]["total"] == 300
        assert result["stats"]["b@test.com"]["total"] == 75


# ---------------------------------------------------------------------------
# ThreeXUIMonitor – new class with GET-based server status
# ---------------------------------------------------------------------------

class TestThreeXUIMonitor:
    """Verify ThreeXUIMonitor uses correct HTTP methods per 3x-UI API v26.2.6."""

    def _build_monitor(self):
        from server_monitor import ThreeXUIMonitor
        return ThreeXUIMonitor(decrypt_func=lambda x: x)

    def _node(self):
        return {"name": "n1", "ip": "1.2.3.4", "port": 443,
                "base_path": "", "user": "admin", "password": "pass"}

    def test_get_server_status_uses_get(self):
        monitor = self._build_monitor()
        body = {
            "success": True,
            "obj": {
                "cpu": 15,
                "mem": {"current": 512, "total": 2048},
                "disk": {"current": 10, "total": 100},
                "swap": {"current": 0, "total": 0},
                "uptime": 7200,
                "loads": [0.5, 0.4, 0.3],
                "xray": {"state": "running", "version": "1.8.10", "uptime": 200},
                "netTraffic": {"sent": 5000, "recv": 10000},
            }
        }
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)) as mock_xui:
                result = monitor.get_server_status(self._node())

        mock_xui.assert_called_once_with(sess, "GET", "https://1.2.3.4:443/panel/api/server/status")
        assert result["available"] is True
        assert result["xray"]["running"] is True
        assert result["xray"]["version"] == "1.8.10"
        assert result["system"]["cpu"] == 15

    def test_get_server_status_normalizes_telemetry_aliases(self):
        monitor = self._build_monitor()
        body = {
            "success": True,
            "obj": {
                "cpuPercent": "17.5%",
                "memory": {"used": "256", "total": "1024"},
                "storage": {"used": "10", "total": "100"},
                "uptime": "3600",
                "loadavg": "0.10 0.20 0.30",
                "network": {"tx": "5000", "rx": "10000"},
                "xray": {"running": True, "version": "1.8.10", "upTime": "200"},
                "panelVersion": "2.6.0",
            },
        }
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.get_server_status(self._node())

        assert result["available"] is True
        assert result["system"]["cpu"] == 17.5
        assert result["system"]["mem"]["current"] == 256.0
        assert result["system"]["mem"]["total"] == 1024.0
        assert result["system"]["mem"]["percent"] == 25.0
        assert result["system"]["disk"]["percent"] == 10.0
        assert result["system"]["loads"] == [0.1, 0.2, 0.3]
        assert result["network"]["upload"] == 5000.0
        assert result["network"]["download"] == 10000.0
        assert result["xray"]["running"] is True
        assert result["xray"]["uptime"] == 200.0
        assert result["panel_version"] == "2.6.0"

    def test_get_server_status_normalizes_v3_net_io(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": {"netIO": {"up": 123, "down": 456}, "xray": {"state": "running"}}}
        with patch.object(monitor, "_get_session", return_value=(MagicMock(), "https://1.2.3.4:443")), patch(
            "server_monitor.xui_request", return_value=_make_response(200, body)
        ):
            result = monitor.get_server_status(self._node())
        assert result["network"] == {"upload": 123.0, "download": 456.0}

    def test_get_session_preserves_panel_url_path_for_session_pool(self):
        monitor = self._build_monitor()
        node = {
            **self._node(),
            "panel_url": "https://panel.example.test/secret-path",
            "ip": "panel.example.test",
            "base_path": "",
        }
        session = MagicMock()
        captured = {}

        def fake_get_authenticated_session(**kwargs):
            captured.update(kwargs)
            return {
                "ok": True,
                "session": session,
                "base_url": kwargs["base_url"],
                "cached": False,
            }

        with patch("server_monitor.get_authenticated_session", side_effect=fake_get_authenticated_session):
            result_session, base_url, login_result = monitor._get_session(node)

        assert result_session is session
        assert base_url == "https://panel.example.test/secret-path"
        assert login_result["ok"] is True
        assert captured["node_key"] == "panel.example.test:443:secret-path"
        assert captured["base_url"] == "https://panel.example.test/secret-path"

    def test_get_server_status_login_failure(self):
        monitor = self._build_monitor()
        with patch.object(monitor, '_get_session') as mock_gs:
            mock_gs.return_value = (None, None)
            result = monitor.get_server_status(self._node())
        assert result["available"] is False

    def test_get_inbounds_uses_get(self):
        monitor = self._build_monitor()
        inbounds = [{"id": 1, "remark": "test", "protocol": "vless", "up": 100, "down": 200}]
        body = {"success": True, "obj": inbounds}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)) as mock_xui:
                result = monitor.get_inbounds(self._node())

        mock_xui.assert_called_once_with(sess, "GET", "https://1.2.3.4:443/panel/api/inbounds/list")
        assert result["available"] is True
        assert len(result["inbounds"]) == 1

    def test_get_inbounds_preserves_base_url_prefix(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": []}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://panel.example.test/secret-path")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)) as mock_xui:
                result = monitor.get_inbounds(self._node())

        mock_xui.assert_called_once_with(
            sess,
            "GET",
            "https://panel.example.test/secret-path/panel/api/inbounds/list",
        )
        assert result["available"] is True

    def test_get_inbounds_normalizes_reality_security(self):
        monitor = self._build_monitor()
        inbounds = [
            {
                "id": 1,
                "remark": "reality",
                "protocol": "vless",
                "streamSettings": json.dumps({"security": "reality", "network": "tcp"}),
                "settings": json.dumps({"clients": []}),
            }
        ]
        body = {"success": True, "obj": inbounds}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.get_inbounds(self._node())

        inbound = result["inbounds"][0]
        assert inbound["streamSettings"]["security"] == "reality"
        assert inbound["security"] == "reality"
        assert inbound["is_reality"] is True

    def test_get_inbounds_reauths_once_on_401(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": [{"id": 1, "remark": "test", "protocol": "vless", "up": 100, "down": 200}]}
        responses = [
            _make_response(401, {"detail": "Unauthorized"}, url="https://1.2.3.4:443/panel/api/inbounds/list"),
            _make_response(200, body),
        ]
        with patch.object(monitor, "_get_session") as mock_gs:
            sess1 = MagicMock(name="session1")
            sess2 = MagicMock(name="session2")

            def _fake_get_session(node, force_reauth=False):
                return (sess2 if force_reauth else sess1, "https://1.2.3.4:443", {"ok": True, "reason": "ok", "error": ""})

            mock_gs.side_effect = _fake_get_session
            with patch.object(monitor, "_invalidate_cached_session") as mock_invalidate:
                with patch("server_monitor.xui_request", side_effect=responses) as mock_xui:
                    result = monitor.get_inbounds(self._node())

        assert result["available"] is True
        assert len(result["inbounds"]) == 1
        assert mock_gs.call_args_list[0] == call(self._node())
        assert mock_gs.call_args_list[1] == call(self._node(), force_reauth=True)
        assert mock_invalidate.called
        assert mock_xui.call_args_list[0] == call(sess1, "GET", "https://1.2.3.4:443/panel/api/inbounds/list")
        assert mock_xui.call_args_list[1] == call(sess2, "GET", "https://1.2.3.4:443/panel/api/inbounds/list")

    def test_get_inbounds_reauths_once_on_panel_api_404(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": [{"id": 1, "remark": "test", "protocol": "vless", "up": 100, "down": 200}]}
        responses = [
            _make_response(404, {"detail": "Not Found"}, url="https://1.2.3.4:443/panel/api/inbounds/list"),
            _make_response(200, body, url="https://1.2.3.4:443/panel/api/inbounds/list"),
        ]
        with patch.object(monitor, "_get_session") as mock_gs:
            sess1 = MagicMock(name="session1")
            sess2 = MagicMock(name="session2")

            def _fake_get_session(node, force_reauth=False):
                return (sess2 if force_reauth else sess1, "https://1.2.3.4:443", {"ok": True, "reason": "ok", "error": ""})

            mock_gs.side_effect = _fake_get_session
            with patch.object(monitor, "_invalidate_cached_session") as mock_invalidate:
                with patch("server_monitor.xui_request", side_effect=responses) as mock_xui:
                    result = monitor.get_inbounds(self._node())

        assert result["available"] is True
        assert len(result["inbounds"]) == 1
        assert mock_gs.call_args_list[0] == call(self._node())
        assert mock_gs.call_args_list[1] == call(self._node(), force_reauth=True)
        assert mock_invalidate.called
        assert mock_xui.call_args_list[0] == call(sess1, "GET", "https://1.2.3.4:443/panel/api/inbounds/list")
        assert mock_xui.call_args_list[1] == call(sess2, "GET", "https://1.2.3.4:443/panel/api/inbounds/list")

    def test_get_online_clients_treats_login_redirect_as_auth_failure(self):
        monitor = self._build_monitor()
        login_page = _make_response(200, None, url="https://1.2.3.4:443/login")
        login_page.headers = {"content-type": "text/html; charset=utf-8"}
        login_page.text = "<html><form><input name='username'><input type='password'></form></html>"
        body = {"success": True, "obj": ["user@a.com", "user@b.com"]}
        with patch.object(monitor, "_get_session") as mock_gs:
            sess1 = MagicMock(name="session1")
            sess2 = MagicMock(name="session2")

            def _fake_get_session(node, force_reauth=False):
                return (sess2 if force_reauth else sess1, "https://1.2.3.4:443", {"ok": True, "reason": "ok", "error": ""})

            mock_gs.side_effect = _fake_get_session
            with patch.object(monitor, "_invalidate_cached_session") as mock_invalidate:
                with patch("server_monitor.xui_request", side_effect=[login_page, _make_response(200, body)]) as mock_xui:
                    result = monitor.get_online_clients(self._node())

        assert result["available"] is True
        assert result["online_clients"] == ["user@a.com", "user@b.com"]
        assert mock_gs.call_args_list[0] == call(self._node())
        assert mock_gs.call_args_list[1] == call(self._node(), force_reauth=True)
        assert mock_invalidate.called
        assert mock_xui.call_args_list[0] == call(sess1, "POST", "https://1.2.3.4:443/panel/api/clients/onlines")
        assert mock_xui.call_args_list[1] == call(sess2, "POST", "https://1.2.3.4:443/panel/api/clients/onlines")

    def test_get_traffic_aggregates_inbounds(self):
        monitor = self._build_monitor()
        inbounds = [
            {"id": 1, "remark": "ib1", "protocol": "vless", "up": 1000, "down": 2000},
            {"id": 2, "remark": "ib2", "protocol": "trojan", "up": 500, "down": 800},
        ]
        body = {"success": True, "obj": inbounds}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.get_traffic(self._node())

        assert result["available"] is True
        assert len(result["traffic"]) == 2
        assert result["traffic"][0]["total"] == 3000
        assert result["traffic"][1]["total"] == 1300

    def test_get_online_clients_prefers_modern_clients_endpoint(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": ["user@a.com", "user@b.com"]}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)) as mock_xui:
                result = monitor.get_online_clients(self._node())

        mock_xui.assert_called_once_with(sess, "POST", "https://1.2.3.4:443/panel/api/clients/onlines")
        assert result["available"] is True
        assert result["online_clients"] == ["user@a.com", "user@b.com"]

    def test_get_online_clients_falls_back_to_legacy_inbounds_endpoint(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": ["user@a.com"]}
        unavailable = _make_response(404, {"success": False})
        available = _make_response(200, body)
        successful_login = {"ok": True, "reason": "ok", "error": ""}
        with patch.object(
            monitor,
            "_request_with_reauth",
            side_effect=[
                (unavailable, "https://1.2.3.4:443", successful_login),
                (available, "https://1.2.3.4:443", successful_login),
            ],
        ) as request:
            result = monitor.get_online_clients(self._node())

        assert result["available"] is True
        assert result["online_clients"] == ["user@a.com"]
        assert [call.args[2] for call in request.call_args_list] == [
            "/panel/api/clients/onlines",
            "/panel/api/inbounds/onlines",
        ]

    def test_online_capability_cache_skips_repeat_probe_of_missing_modern_route(self):
        from xui_session import invalidate_node_capabilities, make_node_key_for_node

        node = self._node()
        invalidate_node_capabilities(make_node_key_for_node(node))
        modern_missing = _make_response(404, {"success": False})
        legacy_available = _make_response(200, {"success": True, "obj": ["user@a.com"]})
        ok = {"ok": True, "reason": "ok", "error": ""}
        monitor = self._build_monitor()
        with patch.object(
            monitor,
            "_request_with_reauth",
            side_effect=[
                (modern_missing, "https://1.2.3.4:443", ok),
                (legacy_available, "https://1.2.3.4:443", ok),
                (legacy_available, "https://1.2.3.4:443", ok),
            ],
        ) as request:
            assert monitor.get_online_clients(node)["available"] is True
            assert monitor.get_online_clients(node)["available"] is True

        assert [call.args[2] for call in request.call_args_list] == [
            "/panel/api/clients/onlines",
            "/panel/api/inbounds/onlines",
            "/panel/api/inbounds/onlines",
        ]
        invalidate_node_capabilities(make_node_key_for_node(node))

    def test_get_client_traffic_prefers_modern_clients_endpoint(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": {"up": 123, "down": 456, "enable": True, "expiryTime": 0}}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)) as mock_xui:
                result = monitor.get_client_traffic(self._node(), "user@test.com")

        mock_xui.assert_called_once_with(
            sess, "GET", "https://1.2.3.4:443/panel/api/clients/traffic/user%40test.com"
        )
        assert result["available"] is True
        assert result["upload"] == 123
        assert result["download"] == 456
        assert result["total"] == 579

    def test_get_client_traffic_non_dict_obj_returns_unavailable(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": None}
        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            mock_gs.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.get_client_traffic(self._node(), "user@test.com")

        assert result["available"] is True
        assert result["upload"] == 0


# ---------------------------------------------------------------------------
# New ClientManager methods (Round 16 fix)
# ---------------------------------------------------------------------------

class TestClientManagerNewMethods:
    """Tests for IP tracking, groups, and attach/detach methods."""

    def _make_manager(self):
        from client_manager import ClientManager
        return ClientManager(decrypt_func=lambda x: x)

    def _node(self):
        return {"name": "test", "ip": "1.2.3.4", "port": "443",
                "scheme": "https", "base_path": "", "user": "admin",
                "password": "pass", "read_only": False}

    def test_get_client_ips_success(self):
        mgr = self._make_manager()
        body = {"success": True, "obj": "1.2.3.4\n5.6.7.8\n"}
        with patch.object(mgr, '_get_session') as mock_gs:
            mock_gs.return_value = (MagicMock(), "https://1.2.3.4:443")
            with patch("client_manager.xui_request", return_value=_make_response(200, body)):
                result = mgr.get_client_ips(self._node(), "user@test.com")
        assert result["ips"] == ["1.2.3.4", "5.6.7.8"]

    def test_get_client_ips_login_failure(self):
        mgr = self._make_manager()
        with patch.object(mgr, '_get_session', return_value=(None, None)):
            result = mgr.get_client_ips(self._node(), "user@test.com")
        assert result == {"ips": []}

    def test_clear_client_ips_success(self):
        mgr = self._make_manager()
        body = {"success": True}
        with patch.object(mgr, '_get_session') as mock_gs:
            mock_gs.return_value = (MagicMock(), "https://1.2.3.4:443")
            with patch("client_manager.xui_request", return_value=_make_response(200, body)):
                result = mgr.clear_client_ips(self._node(), "user@test.com")
        assert result is True

    def test_get_last_online_success(self):
        mgr = self._make_manager()
        body = {"success": True, "obj": {"user@test.com": "2026-01-01T12:00:00"}}
        with patch.object(mgr, '_get_session') as mock_gs:
            mock_gs.return_value = (MagicMock(), "https://1.2.3.4:443")
            with patch("client_manager.xui_request", return_value=_make_response(200, body)):
                result = mgr.get_last_online(self._node(), ["user@test.com"])
        assert result["data"] == {"user@test.com": "2026-01-01T12:00:00"}

    def test_get_client_groups_success(self):
        mgr = self._make_manager()
        body = {"success": True, "obj": ["group1", "group2"]}
        with patch.object(mgr, '_get_session') as mock_gs:
            mock_gs.return_value = (MagicMock(), "https://1.2.3.4:443")
            with patch("client_manager.xui_request", return_value=_make_response(200, body)):
                result = mgr.get_client_groups(self._node())
        assert result == {"groups": ["group1", "group2"]}

    def test_attach_client_read_only_node(self):
        mgr = self._make_manager()
        node = {**self._node(), "read_only": True}
        result = mgr.attach_client(node, "user@test.com", [1, 2])
        assert result is False

    def test_bulk_reset_traffic_read_only(self):
        mgr = self._make_manager()
        node = {**self._node(), "read_only": True}
        result = mgr.bulk_reset_traffic([node], ["user@test.com"])
        assert result["successful"] == 0

    def test_get_sub_links_login_failure(self):
        mgr = self._make_manager()
        with patch.object(mgr, '_get_session', return_value=(None, None)):
            result = mgr.get_sub_links(self._node(), "abc123")
        assert result == []


# ---------------------------------------------------------------------------
# New ServerMonitor methods (Rounds 2, 5)
# ---------------------------------------------------------------------------

class TestServerMonitorNewMethods:
    """Tests for stop_xray, generate_mldsa65, get_panel_update_info, get_xray_observatory."""

    def _build_monitor(self):
        from server_monitor import ServerMonitor
        return ServerMonitor(decrypt_func=lambda x: x)

    def _node(self):
        return {"name": "n1", "ip": "1.2.3.4", "port": 443,
                "base_path": "", "user": "admin", "password": "pass"}

    def test_stop_xray_success(self):
        monitor = self._build_monitor()
        body = {"success": True}
        with patch.object(monitor, '_get_session') as mock_get_session:
            sess = MagicMock()
            mock_get_session.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.stop_xray(self._node())
        assert result is True

    def test_stop_xray_login_failure(self):
        monitor = self._build_monitor()
        with patch.object(monitor, '_get_session') as mock_get_session:
            mock_get_session.return_value = (None, None)
            result = monitor.stop_xray(self._node())
        assert result is False

    def test_generate_mldsa65_success(self):
        monitor = self._build_monitor()
        body = {"success": True, "obj": {"privateKey": "priv", "publicKey": "pub"}}
        with patch.object(monitor, '_get_session') as mock_get_session:
            sess = MagicMock()
            mock_get_session.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.generate_mldsa65(self._node())
        assert result.get("privateKey") == "priv"

    def test_generate_mldsa65_login_failure(self):
        monitor = self._build_monitor()
        with patch.object(monitor, '_get_session') as mock_get_session:
            mock_get_session.return_value = (None, None)
            result = monitor.generate_mldsa65(self._node())
        assert "error" in result

    def test_get_panel_update_info_success(self):
        monitor = self._build_monitor()
        obj = {"currentVersion": "2.3.7", "latestVersion": "2.4.0", "isUpdatable": True}
        body = {"success": True, "obj": obj}
        with patch.object(monitor, '_get_session') as mock_get_session:
            sess = MagicMock()
            mock_get_session.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.get_panel_update_info(self._node())
        # Returns {"node": ..., "update_info": obj}
        assert result.get("update_info", {}).get("currentVersion") == "2.3.7"
        assert "error" not in result

    def test_get_xray_observatory_success(self):
        monitor = self._build_monitor()
        obj = {"status": [{"OutboundTag": "proxy", "Alive": True, "Delay": 120}]}
        body = {"success": True, "obj": obj}
        with patch.object(monitor, '_get_session') as mock_get_session:
            sess = MagicMock()
            mock_get_session.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(200, body)):
                result = monitor.get_xray_observatory(self._node())
        # Returns {"node": ..., "observatory": obj}
        assert result.get("observatory", {}).get("status") is not None
        assert "error" not in result

    def test_get_xray_metrics_http_error(self):
        monitor = self._build_monitor()
        with patch.object(monitor, '_get_session') as mock_get_session:
            sess = MagicMock()
            mock_get_session.return_value = (sess, "https://1.2.3.4:443")
            with patch("server_monitor.xui_request", return_value=_make_response(500, {})):
                result = monitor.get_xray_metrics(self._node())
        assert "error" in result


# ---------------------------------------------------------------------------
# InboundManager unit tests
# ---------------------------------------------------------------------------

class TestInboundManagerMethods:
    """Unit tests for InboundManager read-only guards and key methods."""

    def _make_manager(self):
        from inbound_manager import InboundManager
        return InboundManager(decrypt_func=lambda x: x)

    def _node(self, read_only=False):
        return {"name": "n1", "ip": "1.2.3.4", "port": "443",
                "scheme": "https", "base_path": "", "user": "admin",
                "password": "pass", "read_only": read_only}

    def test_add_inbound_read_only_returns_false(self):
        result = self._make_manager().add_inbound(self._node(read_only=True), {"protocol": "vless"})
        assert result is False

    def test_delete_inbound_read_only_returns_false(self):
        result = self._make_manager().delete_inbound(self._node(read_only=True), 1)
        assert result is False

    def test_reset_inbound_traffic_read_only_returns_false(self):
        result = self._make_manager().reset_inbound_traffic(self._node(read_only=True), 1)
        assert result is False

    def test_set_inbound_enable_read_only_returns_false(self):
        result = self._make_manager().set_inbound_enable(self._node(read_only=True), 1, True)
        assert result is False

    def test_update_inbound_read_only_returns_false(self):
        result = self._make_manager().update_inbound(self._node(read_only=True), 1, {"remark": "x"})
        assert result is False

    def test_del_all_inbound_clients_read_only_returns_error(self):
        result = self._make_manager().del_all_inbound_clients(self._node(read_only=True), 1)
        assert "error" in result

    def test_reset_inbound_traffic_login_failure(self):
        # InboundManager creates its own session; if login_panel returns False, method returns False
        mgr = self._make_manager()
        with patch("inbound_manager.login_panel", return_value=False):
            result = mgr.reset_inbound_traffic(self._node(), 42)
        assert result is False

    def test_set_inbound_enable_login_failure(self):
        mgr = self._make_manager()
        with patch("inbound_manager.login_panel", return_value=False):
            result = mgr.set_inbound_enable(self._node(), 1, False)
        assert result is False

    def test_get_all_inbounds_empty_on_error(self):
        mgr = self._make_manager()
        with patch("inbound_manager.login_panel", return_value=False):
            result = mgr.get_all_inbounds([self._node()])
        assert result == []
