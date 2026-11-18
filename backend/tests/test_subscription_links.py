

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
