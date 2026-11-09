import json
import sqlite3
import sys
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.live_stats_runtime import LiveStatsRuntime

DAY = 86400


def runtime(tmp_path):
    db = tmp_path / "samples.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE traffic_samples (node_id TEXT, ts INTEGER, tier TEXT, inbounds_json TEXT, clients_json TEXT, PRIMARY KEY(node_id, tier, ts)) WITHOUT ROWID")
    obj = LiveStatsRuntime(client_mgr=None, db_path=str(db), traffic_stats_cache={}, cache_refresh_state={},
                           state_lock=Lock(), redis_get_json=None, redis_set_json=None, redis_delete=None,
                           traffic_stats_cache_ttl=0, traffic_stats_stale_ttl=0, logger=None)
    return obj, db


def test_record_per_node_and_interval(tmp_path):
    obj, db = runtime(tmp_path)
    node = {"node_id": 1, "available": True, "inbounds_available": True,
            "inbounds": [{"id": 2, "up": 3, "down": 4, "clientStats": [{"email": "x", "up": 5, "down": 6}]}]}
    snapshot = {"nodes": [node, {"node_id": 2, "available": False, "inbounds_available": True}]}
    for ts in (1000, 1500, 1560, 2099, 2100):
        obj.record_traffic_samples(snapshot, ts)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT node_id, ts, inbounds_json, clients_json FROM traffic_samples ORDER BY ts").fetchall()
    assert [(row[0], row[1]) for row in rows] == [("1", 1000), ("1", 1560), ("1", 2100)]
    assert json.loads(rows[0][2]) == {"node:1:inbound:2": 7}
    assert json.loads(rows[0][3]) == {"x": 11}
    assert obj._ROLLING_SNAPSHOT_CONFIG["day"]["ttl_seconds"] == 730 * DAY


def test_compaction_and_expiry(tmp_path):
    obj, db = runtime(tmp_path)
    now = 800 * DAY
    with sqlite3.connect(db) as conn:
        for ts, tier in [(now - 4 * DAY, "raw"), (now - 4 * DAY + 600, "raw"),
                         (now - 61 * DAY, "hour"), (now - 61 * DAY + 3600, "hour"),
                         (now - 731 * DAY, "day")]:
            conn.execute("INSERT INTO traffic_samples VALUES ('1', ?, ?, '{}', '{}')", (ts, tier))
    obj.record_traffic_samples({}, now)
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT ts, tier FROM traffic_samples ORDER BY ts").fetchall()
    assert rows == [(now - 61 * DAY, "day"), (now - 4 * DAY, "hour")]
