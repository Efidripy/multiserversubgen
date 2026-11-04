import io
import threading
import time

import pytest
import yaml

import services.subscription_remote_rules as remote_rules
from services.subscription_remote_rules import (
    RemoteRulesRefresher,
    RemoteRulesStore,
    collect_urls,
    fetch_remote,
    merge_remote_clash,
    refresh_due,
    resolve_client_settings,
)


class Response:
    def __init__(self, body, status=200):
        self.status = status
        self.body = io.BytesIO(body if isinstance(body, bytes) else body.encode())

    def read(self, size=-1):
        return self.body.read(size)

    def close(self):
        return None


class Opener:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
        self.calls = 0

    def open(self, request, timeout=10):
        self.calls += 1
        return Response(self.body, self.status)


def test_fetch_rejects_private_loopback_and_unsafe_urls_without_opening():
    opener = Opener("happ://x")
    for url in (
        "http://127.0.0.1/rules",
        "http://10.0.0.1/rules",
        "https://user:pass@example.com/rules",
        "ftp://example.com/rules",
    ):
        with pytest.raises(ValueError):
            fetch_remote(url, opener=opener)
    assert opener.calls == 0


def test_fetch_rejects_redirect_and_stops_at_one_megabyte():
    with pytest.raises(RuntimeError, match="redirect"):
        fetch_remote("https://example.com/rules", opener=Opener("", 302))
    with pytest.raises(RuntimeError, match="too_large"):
        fetch_remote("https://example.com/rules", opener=Opener(b"x" * (1024 * 1024 + 1)))


def test_fetch_uses_validated_pinned_address(monkeypatch):
    seen = {}

    class PinnedResponse:
        status_code = 200

        def iter_content(self, size):
            seen["size"] = size
            yield b"happ://pinned"

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(
        remote_rules,
        "validate_and_resolve_outbound_url",
        lambda url, **kwargs: (True, "", "203.0.113.10"),
    )
    monkeypatch.setattr(
        remote_rules,
        "_get_pinned",
        lambda url, **kwargs: (seen.update(kwargs=kwargs, url=url) or PinnedResponse()),
    )
    assert fetch_remote("https://example.com/rules") == "happ://pinned"
    assert seen["kwargs"]["pinned_address"] == "203.0.113.10"
    assert seen["kwargs"]["stream"] is True
    assert seen["closed"] is True


def test_store_failure_preserves_body_and_records_attempt(tmp_path):
    url = "https://example.com/rules"
    store = RemoteRulesStore(str(tmp_path / "rules.db"))
    assert store.refresh(url, "happ", opener=Opener("happ://routing/onadd/x"), now=10)
    assert not store.refresh(url, "happ", opener=Opener("bad"), now=20)
    assert store.get(url) == "happ://routing/onadd/x"
    assert store.status(url) == {"fetched_at": 10.0, "attempted_at": 20.0, "last_error": "body"}
    assert RemoteRulesStore(str(tmp_path / "rules.db")).get(url) == "happ://routing/onadd/x"


@pytest.mark.parametrize(
    ("kind", "body", "valid"),
    [
        ("happ", "happ://x", True),
        ("happ", "bad", False),
        ("incy", "routing", True),
        ("incy", "  ", False),
        ("mihomo", "DOMAIN,x,DIRECT", True),
        ("mihomo", "rules:\n  - DOMAIN,x,DIRECT\n", True),
        ("mihomo", "not yaml: [", False),
    ],
)
def test_store_validates_each_kind(tmp_path, kind, body, valid):
    store = RemoteRulesStore(str(tmp_path / "rules.db"))
    assert store.refresh(f"https://example.com/{kind}", kind, opener=Opener(body), now=1) is valid


def test_collect_urls_refresh_due_attempted_and_disabled(tmp_path):
    settings = {
        "remote_rules": {"refresh_minutes": 1, "user_agent": "agent"},
        "clients": [
            {"enabled": True, "kind": "happ", "settings": {"routing_url": "https://example.com/a"}},
            {"enabled": True, "kind": "mihomo", "settings": {"rules_url": "https://example.com/b"}},
            {"enabled": False, "kind": "incy", "settings": {"routing_url": "https://example.com/c"}},
        ],
    }
    assert collect_urls(settings) == {"https://example.com/a": "happ", "https://example.com/b": "mihomo"}
    store = RemoteRulesStore(str(tmp_path / "rules.db"))
    class Multi:
        def open(self, request, timeout=10):
            return Response("happ://x" if request.full_url.endswith("/a") else "rules:\n  - DOMAIN,x,DIRECT\n")

    assert refresh_due(store, settings, now=100, opener=Multi()) == 2
    assert refresh_due(store, settings, now=120, opener=Multi()) == 0
    failed_settings = {
        "remote_rules": {"refresh_minutes": 1},
        "clients": [{"enabled": True, "kind": "happ", "settings": {"routing_url": "https://example.com/f"}}],
    }
    failed = Opener("bad")
    assert refresh_due(store, failed_settings, now=200, opener=failed) == 0
    assert refresh_due(store, failed_settings, now=220, opener=failed) == 0
    assert failed.calls == 1
    assert refresh_due(store, {**settings, "remote_rules": {"refresh_minutes": 0}}, now=1000, opener=Multi()) == 0


def test_resolve_settings_and_missing_value():
    class FakeStore:
        def __init__(self, value):
            self.value = value

        def get(self, url):
            return self.value

    assert resolve_client_settings(FakeStore(None), {"kind": "happ", "settings": {"x": 1}}) == {"x": 1}
    happ = resolve_client_settings(
        FakeStore("happ://x"), {"kind": "happ", "settings": {"routing_url": "https://example.com/a"}}
    )
    assert happ["routing_enable"] is True
    mihomo_lines = resolve_client_settings(
        FakeStore("DOMAIN,x,DIRECT"), {"kind": "mihomo", "settings": {"rules_url": "https://example.com/a"}}
    )
    assert mihomo_lines["rules"] == "DOMAIN,x,DIRECT" and mihomo_lines["enable_routing"] is True
    document = "rules:\n  - DOMAIN,x,DIRECT\n"
    mihomo_yaml = resolve_client_settings(
        FakeStore(document), {"kind": "mihomo", "settings": {"rules_url": "https://example.com/a"}}
    )
    assert mihomo_yaml["remote_document"] == document and mihomo_yaml["enable_routing"] is True


def test_merge_remote_clash_replaces_rules_and_filters_groups():
    base = {
        "proxies": [{"name": "A"}],
        "proxy-groups": [{"name": "PROXY", "proxies": ["A"]}],
        "rules": ["DOMAIN,old,DIRECT", "MATCH,DIRECT"],
    }
    remote = yaml.safe_dump(
        {
            "rules": ["DOMAIN,new,DIRECT", "MATCH,REJECT"],
            "proxy-groups": [
                {"name": "X", "proxies": ["A", "missing", "DIRECT"]},
                {"name": "PROXY", "proxies": ["missing"]},
            ],
            "dns": {"enable": True},
            "sniffer": {"enable": True},
        }
    )
    merge_remote_clash(base, remote, allow_client_config=False)
    assert base["rules"] == ["DOMAIN,new,DIRECT", "MATCH,PROXY"]
    assert base["proxy-groups"][-1]["proxies"] == ["A", "DIRECT"]
    assert base["proxy-groups"][0]["name"] == "PROXY"
    assert "dns" not in base and "sniffer" not in base
    merge_remote_clash(base, remote, allow_client_config=True)
    assert base["dns"]["enable"] and base["sniffer"]["enable"]


def test_refresher_starts_and_stops(tmp_path):
    refresher = RemoteRulesRefresher(str(tmp_path / "rules.db"), lambda: {"clients": []}, tick_seconds=0.01)
    refresher.start()
    time.sleep(0.03)
    assert refresher._thread is not None and refresher._thread.is_alive()
    refresher.stop()
    assert refresher._thread is None


def test_concurrent_refreshes_are_safe(tmp_path):
    store = RemoteRulesStore(str(tmp_path / "rules.db"))
    errors = []

    def run():
        try:
            store.refresh("https://example.com/a", "happ", opener=Opener("happ://x"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and store.get("https://example.com/a") == "happ://x"
