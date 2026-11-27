import json
import sqlite3
import threading
import time

import pytest
from cryptography.fernet import Fernet

from crypto import decrypt_password, encrypt_password
from services.clients_runtime import ClientsRuntime


class Manager:
    def __init__(self, clients):
        self.clients = clients

    def get_all_clients(self, nodes, email_filter=None):
        return self.clients


def make_runtime(path, key, clients=None, refresh=None):
    fernet = Fernet(key)
    return ClientsRuntime(
        client_mgr=Manager(clients or []), clients_cache={}, clients_cache_ttl=60,
        clients_cache_stale_ttl=300, start_cache_refresh=refresh or (lambda name, fn: None),
        db_path=str(path), encrypt=lambda value: encrypt_password(value, fernet),
        decrypt=lambda value: decrypt_password(value, fernet),
    )


def test_restart_encrypted_and_filters_removed_nodes(tmp_path):
    path = tmp_path / 'admin.db'
    key = Fernet.generate_key()
    clients = [dict(node_id=1, id='secret-uuid', password='secret-password', email='secret-email'),
               dict(node_id=2, id='removed-client')]
    first = make_runtime(path, key, clients)
    first.get_cached_clients([{'id': 1}, {'id': 2}])
    ts = first.clients_cache['ts']
    raw = path.read_bytes()
    assert all(value not in raw for value in (b'secret-uuid', b'secret-password', b'secret-email'))
    second = make_runtime(path, key)
    assert second.clients_cache['ts'] == ts
    assert second.get_cached_clients([{'id': 1}]) == clients[:1]


@pytest.mark.parametrize('case', ['expired', 'wrong_key', 'corrupt', 'bad_json'])
def test_bad_snapshots_are_ignored(tmp_path, case):
    path = tmp_path / 'admin.db'
    key = Fernet.generate_key()
    runtime = make_runtime(path, key, [{'node_id': 1}])
    runtime.get_cached_clients([{'id': 1}])
    with sqlite3.connect(path) as db:
        if case == 'expired':
            db.execute('UPDATE clients_cache_snapshot SET ts = ?', (time.time() - 301,))
        elif case == 'corrupt':
            db.execute("UPDATE clients_cache_snapshot SET data = 'garbage'")
        elif case == 'bad_json':
            db.execute('UPDATE clients_cache_snapshot SET data = ?',
                       (encrypt_password(json.dumps([123]), Fernet(key)),))
    if case == 'wrong_key':
        key = Fernet.generate_key()
    assert not make_runtime(path, key).clients_cache.get('data')


def test_invalidation_blocks_late_refresh(tmp_path):
    path = tmp_path / 'admin.db'
    key = Fernet.generate_key()
    entered, release = threading.Event(), threading.Event()
    runtime = make_runtime(path, key, [{'node_id': 1}])
    runtime.get_cached_clients([{'id': 1}])
    generation = runtime._snapshot_cache()[2]

    def late_refresh():
        entered.set()
        release.wait(5)
        runtime._store_cache([{'node_id': 1}], generation)

    worker = threading.Thread(target=late_refresh)
    worker.start()
    assert entered.wait(5)
    runtime.invalidate()
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM clients_cache_snapshot').fetchone()[0] == 0
    assert not make_runtime(path, key).clients_cache.get('data')


def test_database_error_does_not_break_request(tmp_path):
    runtime = make_runtime(tmp_path / 'missing' / 'admin.db', Fernet.generate_key(),
                           [{'node_id': 1}])
    assert runtime.get_cached_clients([{'id': 1}]) == [{'node_id': 1}]
    runtime.invalidate()


def test_inbound_columns_survive_offline_node_and_restart(tmp_path):
    path = tmp_path / 'admin.db'
    key = Fernet.generate_key()
    row = {'node_id': 1, 'inbound_id': 7, 'protocol': ''}
    metadata = {'7': {'protocol': 'vless', 'network': 'tcp'}}
    runtime = make_runtime(path, key)
    runtime.get_inbound_metadata = lambda node_id: metadata
    runtime._store_cache([dict(row)], 0)
    metadata = {}  # node went offline: the collector has no inbounds for it
    runtime._store_cache([dict(row)], 0)
    restored = make_runtime(path, key).clients_cache['data'][0]
    assert (restored['protocol'], restored['network']) == ('vless', 'tcp')
