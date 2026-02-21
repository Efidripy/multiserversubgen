"""Tests for server_monitor.py endpoint fix and client_manager.py traffic hardening."""
import sys
import os
import json
import types
from unittest.mock import MagicMock, patch, call

import pytest

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
    """Verify that get_server_status uses the correct 3x-ui API endpoint."""

    def _build_monitor(self):
        from server_monitor import ServerMonitor
        monitor = ServerMonitor(decrypt_func=lambda x: x)
        return monitor

    def _node(self):
        return {"name": "n1", "ip": "1.2.3.4", "port": 443,
                "base_path": "", "user": "admin", "password": "pass"}

    def test_primary_endpoint_called_first(self):
        monitor = self._build_monitor()
        success_body = {
            "success": True,
            "obj": {
                "cpu": 10,
                "mem": {"current": 512, "total": 1024},
                "disk": {"current": 5, "total": 100},
                "swap": {"current": 0, "total": 0},
                "uptime": 3600,
                "loads": [0.1],
                "xray": {"state": "running", "version": "1.8", "uptime": 100},
                "netTraffic": {"sent": 1000, "recv": 2000},
            }
        }
        mock_resp = _make_response(200, success_body)

        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            sess.post.return_value = mock_resp
            mock_gs.return_value = (sess, "https://1.2.3.4:443")

            result = monitor.get_server_status(self._node())

        # Primary endpoint must be used
        sess.post.assert_called_once_with(
            "https://1.2.3.4:443/panel/api/server/status", timeout=5
        )
        assert result["available"] is True
        assert result["xray"]["running"] is True

    def test_fallback_to_old_endpoint_on_404(self):
        monitor = self._build_monitor()
        success_body = {
            "success": True,
            "obj": {
                "cpu": 5,
                "mem": {"current": 256, "total": 1024},
                "disk": {"current": 10, "total": 200},
                "swap": {"current": 0, "total": 0},
                "uptime": 1800,
                "loads": [],
                "xray": {"state": "running", "version": "1.7", "uptime": 50},
                "netTraffic": {"sent": 0, "recv": 0},
            }
        }
        resp_404 = _make_response(404)
        resp_200 = _make_response(200, success_body)

        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            sess.post.side_effect = [resp_404, resp_200]
            mock_gs.return_value = (sess, "https://1.2.3.4:443")

            result = monitor.get_server_status(self._node())

        calls = sess.post.call_args_list
        assert calls[0] == call("https://1.2.3.4:443/panel/api/server/status", timeout=5)
        assert calls[1] == call("https://1.2.3.4:443/server/status", timeout=5)
        assert result["available"] is True

    def test_non_200_non_404_returns_unavailable_and_logs(self, caplog):
        import logging
        monitor = self._build_monitor()
        resp_500 = _make_response(500)
        resp_500.text = "Internal Server Error"

        with patch.object(monitor, '_get_session') as mock_gs:
            sess = MagicMock()
            sess.post.return_value = resp_500
            mock_gs.return_value = (sess, "https://1.2.3.4:443")

            with caplog.at_level(logging.WARNING, logger="sub_manager"):
                result = monitor.get_server_status(self._node())

        assert result["available"] is False
        assert "500" in result["error"]
        # Warning log should mention status code
        assert any("500" in r.message for r in caplog.records)

    def test_login_failure_returns_unavailable(self):
        monitor = self._build_monitor()
        with patch.object(monitor, '_get_session') as mock_gs:
            mock_gs.return_value = (None, None)
            result = monitor.get_server_status(self._node())
        assert result["available"] is False


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
        body = {"success": True, "obj": {"up": 100, "down": 200}}
        resp = _make_response(200, body)

        with patch.object(mgr, '_get_session') as mock_gs:
            sess = MagicMock()
            sess.get.return_value = resp
            mock_gs.return_value = (sess, "https://1.2.3.4:443")

            traffic = mgr.get_client_traffic(self._node(), "uuid1", "vless")

        assert traffic == {"up": 100, "down": 200}

    def test_list_obj_returns_empty_dict(self):
        """When 3x-ui returns a list for obj, must return {} not crash."""
        mgr = self._build_manager()
        body = {"success": True, "obj": [{"up": 100, "down": 200}]}
        resp = _make_response(200, body)

        with patch.object(mgr, '_get_session') as mock_gs:
            sess = MagicMock()
            sess.get.return_value = resp
            mock_gs.return_value = (sess, "https://1.2.3.4:443")

            traffic = mgr.get_client_traffic(self._node(), "uuid1", "trojan")

        assert traffic == {}

    def test_list_obj_does_not_break_get_traffic_stats(self):
        """get_traffic_stats must not raise AttributeError when 3x-ui returns a list for obj."""
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
                sess.get.return_value = resp
                mock_gs.return_value = (sess, "https://1.2.3.4:443")

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
            sess.get.return_value = resp
            mock_gs.return_value = (sess, "https://1.2.3.4:443")

            traffic = mgr.get_client_traffic(self._node(), "uid", "vmess")

        assert traffic == {}
