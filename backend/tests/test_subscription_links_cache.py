from services import subscription_links


def setup_function():
    subscription_links.links_cache.clear()


def teardown_function():
    subscription_links.links_cache.clear()


def test_links_cache_prunes_expired_entries_when_storing_a_new_key(monkeypatch):
    monkeypatch.setattr(subscription_links, "CACHE_TTL", 30)
    monkeypatch.setattr(subscription_links, "fetch_inbounds", lambda _node: [])
    subscription_links.links_cache["stale"] = (10.0, ["old-link"])
    monkeypatch.setattr(subscription_links.time, "time", lambda: 100.0)

    subscription_links.get_links_filtered([], "fresh@example.com")

    assert "stale" not in subscription_links.links_cache
    assert len(subscription_links.links_cache) == 1


def test_links_cache_evicts_oldest_entry_after_reaching_its_bound(monkeypatch):
    monkeypatch.setattr(subscription_links, "LINKS_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(subscription_links, "fetch_inbounds", lambda _node: [])
    timestamps = iter((1.0, 2.0, 3.0))
    monkeypatch.setattr(subscription_links.time, "time", lambda: next(timestamps))

    subscription_links.get_links_filtered([], "first@example.com")
    subscription_links.get_links_filtered([], "second@example.com")
    subscription_links.get_links_filtered([], "third@example.com")

    assert len(subscription_links.links_cache) == 2
    assert not any(key.startswith("first@example.com|") for key in subscription_links.links_cache)
    assert any(key.startswith("second@example.com|") for key in subscription_links.links_cache)
    assert any(key.startswith("third@example.com|") for key in subscription_links.links_cache)
