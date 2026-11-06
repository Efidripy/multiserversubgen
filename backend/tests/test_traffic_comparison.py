import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers.operations import build_operations_router


def test_traffic_comparison_buckets_reset_empty_and_auth(tmp_path, monkeypatch):
    db = tmp_path / 'history.db'
    now = 2_000_000
    monkeypatch.setattr('routers.operations.time.time', lambda: now)
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE node_history (ts INTEGER, node_id INTEGER, traffic_total INTEGER)')
        conn.execute('CREATE TABLE traffic_stats_snapshots (group_by TEXT, bucket_kind TEXT, snapshot_ts INTEGER, stats_json TEXT)')
    app = FastAPI()
    app.include_router(build_operations_router(check_auth=lambda request: request.headers.get('authorization'), db_path=str(db), node_service=None, client_mgr=None, server_monitor=None, get_node_or_404=None, snapshot_collector=None))
    client = TestClient(app)
    assert client.get('/api/v1/traffic/comparison').status_code == 401
    assert client.get('/api/v1/traffic/comparison?range=bad', headers={'Authorization': 'test'}).status_code == 400
    headers = {'Authorization': 'test'}
    empty = client.get('/api/v1/traffic/comparison', headers=headers).json()
    assert len(empty['series_current']) == 24
    assert empty['totals']['current'] == 0
    with sqlite3.connect(db) as conn:
        conn.executemany('INSERT INTO node_history VALUES (?, ?, ?)', [(now - 172900, 1, 100), (now - 172700, 1, 110), (now - 86500, 1, 120), (now - 80000, 1, 10), (now - 100, 1, 25)])
    data = client.get('/api/v1/traffic/comparison', headers=headers).json()
    assert data['totals'] == {'current': 25, 'previous': 10}
    assert sum(x['value'] for x in data['series_current']) == 25
    assert len(client.get('/api/v1/traffic/comparison?range=7d', headers=headers).json()['series_current']) == 7
    assert len(client.get('/api/v1/traffic/comparison?range=30d', headers=headers).json()['series_current']) == 30


def test_service_aggregation_alignment_filter_and_incomplete_history(tmp_path):
    from services.traffic_comparison import load_comparison

    db = tmp_path / 'history.db'
    now = 2_000_000
    end = (now // 3600 + 1) * 3600
    start = end - 48 * 3600
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE node_history (ts INTEGER, node_id INTEGER, traffic_total INTEGER)')
        conn.execute('CREATE TABLE traffic_stats_snapshots (group_by TEXT, bucket_kind TEXT, snapshot_ts INTEGER, stats_json TEXT)')
        conn.executemany('INSERT INTO node_history VALUES (?, ?, ?)', [
            (start - 1, 1, 100), (start + 10, 1, 110),
            (start + 23 * 3600, 1, 120), (start + 24 * 3600, 1, 130),
            (start + 25 * 3600, 1, 5), (start + 25 * 3600 + 10, 1, 9),
            (start + 25 * 3600, 2, 500), (start + 26 * 3600, 2, 900),
        ])
    data = load_comparison(str(db), '24h', 1, now)
    assert data['previous_available'] is True
    assert data['totals'] == {'current': 19, 'previous': 20}
    assert all(p['ts'] % 3600 == 0 for p in data['series_current'])
    assert load_comparison(str(db), '24h', 2, now)['previous_available'] is False
    assert all(p['ts'] % 86400 == 0 for p in load_comparison(str(db), '7d', 1, now)['series_current'])
