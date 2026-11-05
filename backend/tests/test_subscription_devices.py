from __future__ import annotations

import base64
import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from services.subscription_devices import (
    check_device,
    delete_device,
    device_status,
    list_devices,
)
from services.subscription_client_settings import default_settings, device_app_name
from services.db_bootstrap import connect


def _section(**overrides):
    value = {
        "enabled": True,
        "max_devices": 2,
        "block_unsupported": False,
        "limit_announce": "",
    }
    value.update(overrides)
    return value


def test_disabled_section_is_noop(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    result = check_device(path, "alice", {"X-HWID": "a"}, {"enabled": False}, now=1)
    assert result.allowed is True
    assert result.headers == {}
    assert not (tmp_path / "devices.sqlite").exists()


def test_unsupported_hwid_and_blocking(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    allowed = check_device(path, "alice", {}, _section(), now=1)
    assert allowed.allowed is True
    assert allowed.headers["X-Hwid-Active"] == "true"
    assert allowed.headers["X-Hwid-Not-Supported"] == "true"
    assert "X-Hwid-Limit" not in allowed.headers
    assert list_devices(path) == []

    blocked = check_device(path, "alice", {"X-HWID": "x" * 257}, _section(block_unsupported=True), now=2)
    assert blocked.allowed is False
    assert blocked.headers["X-Hwid-Not-Supported"] == "true"
    assert list_devices(path) == []


def test_registration_metadata_hash_and_known_device_update(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    first = check_device(
        path,
        "alice",
        {
            "X-HWID": "phone-1",
            "X-Device-OS": "Android\n" + "x" * 80,
            "X-Ver-OS": "14",
            "X-Device-Model": "Pixel",
        },
        _section(max_devices=1),
        now=10,
    )
    assert first.allowed is True
    # Max 1 is now taken, yet this request succeeded: no "limit reached" signal.
    assert "X-Hwid-Limit" not in first.headers
    assert "X-Hwid-Max-Devices-Reached" not in first.headers
    second = check_device(
        path,
        "alice",
        {"x-hwid": "phone-1", "X-Device-OS": "iOS", "X-Ver-OS": "17", "X-Device-Model": "iPhone"},
        _section(max_devices=1),
        now=20,
    )
    assert second.allowed is True
    devices = list_devices(path, subject="alice")
    assert len(devices) == 1
    assert devices[0]["first_seen"] == 10
    assert devices[0]["last_seen"] == 20
    assert devices[0]["device_os"] == "iOS"
    assert "hwid" not in {key.lower() for key in devices[0]}
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT hwid_hash FROM subscription_devices").fetchone()
    assert row[0] == hashlib.sha256(b"alice\0phone-1").hexdigest()


def test_hwid_boundary_and_metadata_sanitising(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    hwid = "h" * 256
    result = check_device(
        path,
        "alice",
        {"X-HWID": hwid, "X-Device-OS": "a\x00b\n" + "x" * 100},
        _section(max_devices=1),
        now=1,
    )
    assert result.allowed is True
    row = list_devices(path)[0]
    assert row["device_os"] == "ab" + "x" * 62

    oversized = check_device(path, "bob", {"X-HWID": "h" * 257}, _section(max_devices=1), now=2)
    assert oversized.headers["X-Hwid-Not-Supported"] == "true"
    assert list_devices(path, subject="bob") == []


def test_limit_refusal_announce_and_unlimited_mode(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    check_device(path, "alice", {"X-HWID": "a"}, _section(max_devices=1), now=1)
    refused = check_device(
        path,
        "alice",
        {"X-HWID": "b"},
        _section(max_devices=1, limit_announce="Лимит"),
        now=2,
    )
    assert refused.allowed is False
    assert refused.headers["X-Hwid-Max-Devices-Reached"] == "true"
    assert refused.headers["X-Hwid-Limit"] == "true"
    assert refused.headers["Announce"] == "base64:" + base64.b64encode("Лимит".encode()).decode()

    unlimited_path = str(tmp_path / "unlimited.sqlite")
    for value in ("a", "b", "c"):
        assert check_device(unlimited_path, "alice", {"X-HWID": value}, _section(max_devices=0), now=1).allowed
    assert device_status(unlimited_path, "alice", _section(max_devices=0)) == {
        "count": 3,
        "max_devices": 0,
        "reached": False,
    }

    lowered = check_device(path, "alice", {"X-HWID": "a"}, _section(max_devices=0), now=3)
    assert lowered.allowed is True


def test_status_listing_limit_and_delete(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    for index in range(3):
        check_device(path, "alice", {"X-HWID": str(index)}, _section(max_devices=0), now=index)
    check_device(path, "bob", {"X-HWID": "b"}, _section(max_devices=0), now=4)
    assert len(list_devices(path, subject="alice", limit=2)) == 2
    assert device_status(path, "alice", _section(max_devices=2))["reached"] is True
    assert delete_device(path, 2) is True
    assert delete_device(path, 2) is False
    assert len(list_devices(path, subject="alice")) == 2


def test_concurrent_new_devices_never_exceed_limit(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    section = _section(max_devices=2)
    with connect(path) as conn:
        conn.execute(
            """CREATE TABLE subscription_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                hwid_hash TEXT NOT NULL,
                device_os TEXT NOT NULL DEFAULT '',
                os_version TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                UNIQUE(subject, hwid_hash)
            )"""
        )
        conn.commit()

    def register(index):
        return check_device(path, "alice", {"X-HWID": f"device-{index}"}, section, now=index)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(pool.map(register, range(8)))
    assert sum(decision.allowed for decision in decisions) == 2
    assert device_status(path, "alice", section)["count"] == 2


def test_list_devices_ceiling_raised_to_5000(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    with connect(path) as conn:
        conn.execute(
            """CREATE TABLE subscription_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                hwid_hash TEXT NOT NULL,
                device_os TEXT NOT NULL DEFAULT '',
                os_version TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                UNIQUE(subject, hwid_hash)
            )"""
        )
        conn.executemany(
            "INSERT INTO subscription_devices (subject, hwid_hash, first_seen, last_seen) VALUES (?, ?, 1, 1)",
            [(f"sub-{i}", f"hash-{i}") for i in range(250)],
        )
    # Default limit is 200
    assert len(list_devices(path)) == 200
    # Ceiling raised beyond 200 up to 5000
    assert len(list_devices(path, limit=300)) == 250


def test_migration_of_old_table_preserves_data(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    # Old table schema without user_agent column
    with connect(path) as conn:
        conn.execute(
            """CREATE TABLE subscription_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                hwid_hash TEXT NOT NULL,
                device_os TEXT NOT NULL DEFAULT '',
                os_version TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                UNIQUE(subject, hwid_hash)
            )"""
        )
        conn.execute(
            """INSERT INTO subscription_devices
               (subject, hwid_hash, device_os, os_version, model, first_seen, last_seen)
               VALUES ('alice', 'old-hash', 'iOS', '17.0', 'iPhone 15', 10, 20)"""
        )
        conn.commit()

    # list_devices on old table without user_agent column must not fail
    devices = list_devices(path)
    assert len(devices) == 1
    assert devices[0]["subject"] == "alice"
    assert devices[0]["device_os"] == "iOS"
    assert devices[0]["user_agent"] == ""

    # check_device migrates the table (via _ensure_table)
    result = check_device(
        path,
        "bob",
        {"X-HWID": "bob-phone", "User-Agent": "Happ/3.6.1"},
        _section(max_devices=5),
        now=30,
    )
    assert result.allowed is True

    # Existing alice record is preserved and bob record has user_agent
    migrated = list_devices(path)
    assert len(migrated) == 2
    alice = next(d for d in migrated if d["subject"] == "alice")
    bob = next(d for d in migrated if d["subject"] == "bob")
    assert alice["device_os"] == "iOS"
    assert alice["model"] == "iPhone 15"
    assert alice["user_agent"] == ""
    assert bob["user_agent"] == "Happ/3.6.1"


def test_user_agent_recording_and_non_overwriting_on_empty_update(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    # 1. Insert with User-Agent
    res1 = check_device(
        path,
        "alice",
        {"X-HWID": "hwid-1", "User-Agent": "Happ/3.6.1 (iPhone 15; iOS 18.0)"},
        _section(max_devices=2),
        now=10,
    )
    assert res1.allowed is True
    devs = list_devices(path, subject="alice")
    assert len(devs) == 1
    assert devs[0]["user_agent"] == "Happ/3.6.1 (iPhone 15; iOS 18.0)"

    # 2. Update with empty User-Agent: saved user_agent must NOT be overwritten
    res2 = check_device(
        path,
        "alice",
        {"X-HWID": "hwid-1", "User-Agent": ""},
        _section(max_devices=2),
        now=20,
    )
    assert res2.allowed is True
    devs2 = list_devices(path, subject="alice")
    assert devs2[0]["user_agent"] == "Happ/3.6.1 (iPhone 15; iOS 18.0)"
    assert devs2[0]["last_seen"] == 20

    # 3. Update without User-Agent header at all
    res3 = check_device(
        path,
        "alice",
        {"X-HWID": "hwid-1"},
        _section(max_devices=2),
        now=30,
    )
    assert res3.allowed is True
    devs3 = list_devices(path, subject="alice")
    assert devs3[0]["user_agent"] == "Happ/3.6.1 (iPhone 15; iOS 18.0)"

    # 4. Update with a new non-empty User-Agent: updates the value
    res4 = check_device(
        path,
        "alice",
        {"X-HWID": "hwid-1", "User-Agent": "ClashMeta/v1.18.1"},
        _section(max_devices=2),
        now=40,
    )
    assert res4.allowed is True
    devs4 = list_devices(path, subject="alice")
    assert devs4[0]["user_agent"] == "ClashMeta/v1.18.1"


def test_device_app_name_resolution():
    settings = default_settings()
    # Built-in clients are disabled by default
    assert all(not c["enabled"] for c in settings["clients"])

    # Disabled built-in clients still match
    assert device_app_name(settings, "Happ/3.6.1 (iPhone)") == "Happ"
    assert device_app_name(settings, "ClashMeta/v1.18.1") == "Mihomo/Clash"
    assert device_app_name(settings, "Flclash/0.14.0") == "Mihomo/Clash"
    assert device_app_name(settings, "sing-box 1.9.0") == "sing-box"
    assert device_app_name(settings, "Stash/2.6.2") == "Stash"
    assert device_app_name(settings, "Incy/1.0.0") == "Incy"

    # Unknown User-Agent -> first token before '/' or ' '
    assert device_app_name(settings, "curl/8.1.2") == "curl"
    assert device_app_name(settings, "CustomApp 2.0") == "CustomApp"
    assert device_app_name(settings, "StandaloneApp") == "StandaloneApp"
    assert device_app_name(settings, "foo/bar baz") == "foo"

    # Empty User-Agent -> empty string
    assert device_app_name(settings, "") == ""
    assert device_app_name(settings, None) == ""
    assert device_app_name(settings, "   ") == ""
    assert device_app_name({}, "") == ""
