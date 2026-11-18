

def test_offline_node_ids_come_from_the_collector_snapshot(tmp_path):
    from services import subscription_links
    from services.db_bootstrap import connect, init_db

    path = str(tmp_path / "s.db")
    init_db(path)
    with connect(path) as conn:
        for node_id in (1, 2):
            conn.execute("INSERT INTO nodes(id, name, enabled, read_only) VALUES (?, ?, 1, 0)", (node_id, f"n{node_id}"))
        conn.execute("INSERT INTO node_snapshots(node_id, status_data, is_online) VALUES (1, '{}', 1)")
        conn.execute("INSERT INTO node_snapshots(node_id, status_data, is_online) VALUES (2, '{}', 0)")
    previous = subscription_links._SNAPSHOT_DB_PATH
    subscription_links._SNAPSHOT_DB_PATH = path
    try:
        assert subscription_links.get_offline_node_ids() == {2}
    finally:
        subscription_links._SNAPSHOT_DB_PATH = previous


def test_offline_node_ids_include_in_memory_timeouts(monkeypatch):
    from services import subscription_links as sl

    monkeypatch.setattr(sl, "_SNAPSHOT_DB_PATH", None)
    monkeypatch.setattr(
        sl,
        "_LIVE_SNAPSHOT",
        lambda: {"nodes": [{"node_id": 7, "available": False}, {"node_id": 8, "available": True}, {"name": "x", "available": False}]},
    )
    assert sl.get_offline_node_ids() == {7}


def test_link_metadata_survives_pruning_while_the_link_is_cached(monkeypatch):
    from services import subscription_links as sl

    monkeypatch.setattr(sl, "LINKS_CACHE_MAX_ENTRIES", 1)
    monkeypatch.setattr(sl, "_link_inbound_remarks", {})
    monkeypatch.setattr(sl, "_link_node_ids", {})
    monkeypatch.setattr(sl, "links_cache", {})
    cached, stale = "vless://a@1.1.1.1:1#a", "vless://b@2.2.2.2:2#b"
    sl.links_cache["k"] = (0.0, [cached])
    for link, node_id in ((cached, 1), (stale, 2)):
        sl._link_inbound_remarks[link] = ""
        sl._link_node_ids[link] = node_id

    sl._prune_link_metadata()

    assert sl.get_link_node_id(cached) == 1
    assert sl.get_link_node_id(stale) is None
