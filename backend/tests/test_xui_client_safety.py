"""Safety contracts for the dormant reusable XUI transport client."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _client():
    from integrations.xui.client import XUIClient

    client = XUIClient(url="https://panel.example.test", username="admin", password="secret", base_path="hidden")
    client._session = MagicMock()
    return client


def test_client_uses_base_path_for_requests():
    client = _client()
    with patch("xui_session.xui_request", return_value=MagicMock()) as request:
        client.request("GET", "/panel/api/clients/list")
    assert request.call_args.args[2] == "https://panel.example.test/hidden/panel/api/clients/list"


def test_client_does_not_replay_ambiguous_post():
    client = _client()
    with patch("xui_session.xui_request", side_effect=RuntimeError("network break")) as request:
        with pytest.raises(RuntimeError, match="outcome is ambiguous"):
            client.request("POST", "/panel/api/clients/add", json={"client": {}})
    request.assert_called_once()
