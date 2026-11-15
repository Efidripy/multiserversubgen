"""Node database backups are read with a hard size cap."""
import base64
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class _Response:
    status_code = 200

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, _size):
        yield from self._chunks

    def close(self):
        self.closed = True


def _backup(response, limit=8):
    import server_monitor

    monitor = server_monitor.ServerMonitor(decrypt_func=lambda value: value)
    node = {"name": "cap-node"}
    with patch.object(monitor, "_get_session", return_value=(MagicMock(), "https://198.51.100.8")), patch(
        "server_monitor.xui_request", return_value=response
    ) as request, patch.object(server_monitor, "MAX_NODE_BACKUP_BYTES", limit):
        result = monitor.get_database_backup(node)
    assert request.call_args.kwargs["stream"] is True
    assert response.closed
    return result


def test_binary_backup_within_cap_is_returned_as_base64():
    result = _backup(_Response([b"abcd", b"efgh"]))

    assert base64.b64decode(result["backup_b64"]) == b"abcdefgh"


def test_json_wrapped_backup_is_still_supported():
    result = _backup(_Response([b'{"success": true, "obj": "QUJD"}']), limit=64)

    assert result["backup_b64"] == "QUJD"


def test_oversized_body_is_refused_while_streaming():
    result = _backup(_Response([b"abcd", b"efgh", b"i"]))

    assert result == {"error": "backup is too large"}


def test_oversized_content_length_is_refused_before_reading():
    def _must_not_read():
        raise AssertionError("body was read")
        yield b""

    result = _backup(_Response(_must_not_read(), {"Content-Length": "9"}))

    assert result == {"error": "backup is too large"}
