from __future__ import annotations

import os
import sys
from urllib.request import Request

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.db_bootstrap import init_db
from services.telegram_registry import TelegramRegistry, VersionConflictError
from services.telegram_transport import TelegramApiTransport, TelegramTransportError, validate_local_proxy_url


def test_transport_preference_defaults_to_direct_and_uses_optimistic_versioning(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)

    initial = registry.get_transport_preference()
    assert initial.mode == "direct"
    assert initial.row_version == 1

    changed = registry.set_transport_preference(
        mode="local_proxy", expected_row_version=initial.row_version, updated_by="admin"
    )
    assert (changed.mode, changed.row_version, changed.updated_by) == ("local_proxy", 2, "admin")
    with pytest.raises(VersionConflictError):
        registry.set_transport_preference(mode="direct", expected_row_version=1, updated_by="other")


@pytest.mark.parametrize(
    "raw_value",
    [
        "https://127.0.0.1:1081",
        "http://example.test:1081",
        "http://127.0.0.1",
        "http://user@127.0.0.1:1081",
        "http://:password@127.0.0.1:1081",
        "http://127.0.0.1:1081/path",
    ],
)
def test_local_proxy_url_rejects_non_loopback_or_credentialed_values(raw_value):
    with pytest.raises(ValueError):
        validate_local_proxy_url(raw_value)


def test_local_proxy_mode_fails_closed_without_a_runtime_proxy(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    registry = TelegramRegistry(db_path)
    preference = registry.get_transport_preference()
    registry.set_transport_preference(
        mode="local_proxy", expected_row_version=preference.row_version, updated_by="admin"
    )
    transport = TelegramApiTransport(db_path=db_path, local_proxy_url="")

    assert transport.status().configured is False
    assert transport.status().reachable is False
    with pytest.raises(TelegramTransportError, match="unavailable"):
        transport.open(Request("https://api.telegram.org/"), timeout=0.01)


def test_local_proxy_url_accepts_loopback_http_connect_endpoint():
    assert validate_local_proxy_url("http://127.0.0.1:1081/") == "http://127.0.0.1:1081"
    assert validate_local_proxy_url("http://user:password@127.0.0.1:1081") == "http://user:password@127.0.0.1:1081"
