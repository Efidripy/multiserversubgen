import json
import sqlite3
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers.operations import build_operations_router
from services.traffic_comparison import load_comparison

DAY = 86400


def database(tmp_path):
    db = tmp_path / 'history.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE traffic_stats_snapshots (group_by TEXT, bucket_kind TEXT, snapshot_ts INTEGER, stats_json TEXT)')
    return db


def save(db, group, ts, data, kind='day'):
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO traffic_stats_snapshots VALUES (?, ?, ?, ?)', (group, kind, ts, json.dumps(data)))


def test_sixty_daily_snapshots_and_node_filter(tmp_path):
    db = database(tmp_path)
    for day in range(60):
        save(db, 'inbound', day * DAY, {'node:1:inbound:1': {'total': day * 10},
                                         'node:2:inbound:1': {'total': day * 20}})
    data = load_comparison(str(db), '30d', 1, 59 * DAY)
    assert data['previous_available'] is True
    assert data['history_days'] >= 59
    assert data['totals'] == {'current': 300, 'previous': 290}
    assert load_comparison(str(db), '30d', None, 59 * DAY)['totals']['current'] == 900



def test_recent_node_uses_its_own_history(tmp_path):
    db = database(tmp_path)
    for day in range(60):
        data = {'node:1:inbound:1': {'total': day * 10}}
        if day >= 50:
            data['node:2:inbound:1'] = {'total': (day - 50) * 20}
        save(db, 'inbound', day * DAY, data)

    node = load_comparison(str(db), '30d', 2, 59 * DAY)
    assert node['previous_available'] is False
    assert node['history_days'] == 9
    assert node['totals']['previous'] is None
    assert node['series_previous'] == []

    fleet = load_comparison(str(db), '30d', None, 59 * DAY)
    assert fleet['previous_available'] is True
    assert fleet['history_days'] == 59
    assert fleet['totals'] == {'current': 480, 'previous': 290}


def test_missing_inbound_reset_noise_and_missing_day(tmp_path):
    db = database(tmp_path)
    tb, gb = 1024 ** 4, 1024 ** 3
    readings = [
        {'node:1:inbound:1': 10 * tb, 'node:1:inbound:2': 100},
        {'node:1:inbound:2': 110},
        {'node:1:inbound:1': 10 * tb + 20, 'node:1:inbound:2': 120},
        {'node:1:inbound:1': gb, 'node:1:inbound:2': 115},
        {'node:1:inbound:1': gb + 5, 'node:1:inbound:2': 125},
    ]
    for day, reading in enumerate(readings):
        save(db, 'inbound', day * DAY, {key: {'total': value} for key, value in reading.items()})
    save(db, 'inbound', 6 * DAY, {'node:1:inbound:1': {'total': gb + 15}, 'node:1:inbound:2': {'total': 135}})
    data = load_comparison(str(db), '7d', None, 6 * DAY)
    values = [point['value'] for point in data['series_current']]
    assert values == [0, 10, 10, gb, 15, 0, 20]
    assert data['totals']['current'] == gb + 55


def test_system_clients_excluded_from_rankings_but_in_totals(tmp_path, monkeypatch):
    db = database(tmp_path)
    for day in range(15):
        save(db, 'inbound', day * DAY, {'node:1:inbound:1': {'total': day * 100}})
        save(db, 'client', day * DAY, {' YT-OUT ': {'total': day * 80}, 'user': {'total': day * 20}})
    class Collector:
        def latest_snapshot(self):
            return {'nodes': [{'system_client_emails': ['yt-out']}]}
    monkeypatch.setattr('routers.operations.time.time', lambda: 14 * DAY)
    app = FastAPI()
    app.include_router(build_operations_router(check_auth=lambda request: request.headers.get('authorization'), db_path=str(db), node_service=None, client_mgr=None, server_monitor=None, get_node_or_404=None, snapshot_collector=Collector()))
    client = TestClient(app)
    assert client.get('/api/v1/traffic/comparison').status_code == 401
    assert client.get('/api/v1/traffic/comparison?range=bad', headers={'Authorization': 'yes'}).status_code == 400
    data = client.get('/api/v1/traffic/comparison?range=7d', headers={'Authorization': 'yes'}).json()
    assert data['totals'] == {'current': 700, 'previous': 700}
    assert [item['email'] for item in data['top_clients']] == ['user']
    assert [item['email'] for item in data['top_growth']] == ['user']


def test_hour_snapshots_and_empty_history(tmp_path):
    db = database(tmp_path)
    empty = load_comparison(str(db), '24h', None, 5000)
    assert empty['totals'] == {'current': 0, 'previous': None}
    save(db, 'inbound', 3600, {'node:1:inbound:1': {'total': 10}}, 'hour')
    save(db, 'inbound', 7200, {'node:1:inbound:1': {'total': 25}}, 'hour')
    data = load_comparison(str(db), '24h', None, 7200)
    assert data['totals']['current'] == 15
