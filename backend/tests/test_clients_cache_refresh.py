import asyncio
import logging
import os
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.clients_runtime import ClientsRuntime
from services.collector import SnapshotCollector
from services.live_stats_runtime import LiveStatsRuntime


def runtime(cache, manager=None, start=None, reachable=None):
    return ClientsRuntime(client_mgr=manager or SimpleNamespace(), clients_cache=cache,
                          clients_cache_ttl=60, clients_cache_stale_ttl=86400,
                          start_cache_refresh=start or (lambda *_: None),
                          filter_reachable_nodes=reachable)


@pytest.mark.parametrize('mode,threshold', [('warming', 300), ('active', 300), ('idle', 1800), ('ultra_idle', 1800)])
def test_cycle_refresh_thresholds_and_empty_cache(monkeypatch, mode, threshold):
    monkeypatch.setattr('services.clients_runtime.time.time', lambda: 10000)
    calls = []
    cache = {'ts': 10000 - threshold + 1, 'data': []}
    subject = runtime(cache, start=lambda *args: calls.append(args))
    subject.refresh_after_collector_cycle([], mode)
    assert not calls
    cache['ts'] -= 1
    subject.refresh_after_collector_cycle([], mode)
    assert len(calls) == 1
    cache['ts'] = 0
    subject.refresh_after_collector_cycle([], mode)
    assert len(calls) == 2


def test_background_retains_failed_and_skipped_then_clears_success_and_removed():
    nodes = [{'id': i} for i in (1, 2, 3, 4)]
    cache = {'ts': 1, 'data': [{'node_id': i, 'email': str(i)} for i in range(1, 6)]}
    class Manager:
        failed = {1}
        def _get_all_clients_with_status(self, nodes, email_filter=None):
            return ([{'node_id': 3, 'email': 'new'}], self.failed)
    manager = Manager()
    subject = runtime(cache, manager, lambda _, f: f(), lambda ns: [n for n in ns if n['id'] != 2])
    subject.refresh_after_collector_cycle(nodes, 'warming')
    assert {(x['node_id'], x['email']) for x in cache['data']} == {(1, '1'), (2, '2'), (3, 'new')}
    subject.invalidate()
    manager.failed = set()
    subject.get_cached_clients(nodes)
    assert {(x['node_id'], x['email']) for x in cache['data']} == {(2, '2'), (3, 'new')}


def test_shared_refresh_prevents_duplicate_workers():
    state = {'traffic': set()}
    holder = SimpleNamespace(state_lock=threading.Lock(), cache_refresh_state=state, logger=logging.getLogger(__name__))
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def work():
        calls.append(1)
        entered.set()
        release.wait(5)
        done.set()
    start = lambda key, fn: LiveStatsRuntime.start_cache_refresh(holder, key, fn)
    start('clients', work)
    assert entered.wait(5)
    start('clients', work)
    release.set()
    assert done.wait(5)
    assert calls == [1]


def test_restored_circuit_deadline_and_scheduler(monkeypatch):
    monkeypatch.setattr('services.collector.time.time', lambda: 1000.0)
    collector = SnapshotCollector(fetch_nodes=lambda: [], xui_monitor=None, ws_manager=SimpleNamespace(), db_path='unused')
    collector._load_persisted_snapshot_rows = lambda: [('id:1', {'available': False, 'circuit_open_until': 1060.0}, 999)]
    assert asyncio.run(collector.load_persisted_snapshots()) == 1
    assert collector._node_state['id:1']['next_poll'] == 1060.0
    assert collector._next_control_loop_timeout(now=1000.0) == 60.0
    assert collector._next_control_loop_timeout(now=1059.0) == 1.0


def test_first_warming_cycle_schedules_and_shutdown_does_not(monkeypatch):
    monkeypatch.setattr('services.collector.time.time', lambda: 10000.0)
    monkeypatch.setattr('services.clients_runtime.time.time', lambda: 10000.0)
    calls = []
    subject = runtime({'ts': 9600, 'data': []}, start=lambda *args: calls.append(args))
    collector = SnapshotCollector(fetch_nodes=lambda: [], xui_monitor=None,
                                  ws_manager=SimpleNamespace(active_connections=[object()]))
    collector.on_cycle_completed = subject.refresh_after_collector_cycle
    async def poll(*args, **kwargs):
        return []
    async def wait(*args, **kwargs):
        collector._running = False
    monkeypatch.setattr(collector, '_poll_due_nodes', poll)
    monkeypatch.setattr(collector, '_wait_for_scheduler_wake', wait)
    collector._running = True
    asyncio.run(collector._run())
    assert collector._mode.value == 'warming'
    assert len(calls) == 1

    async def stop_during_poll(*args, **kwargs):
        collector._running = False
        return []
    monkeypatch.setattr(collector, '_poll_due_nodes', stop_during_poll)
    collector._running = True
    asyncio.run(collector._run())
    assert len(calls) == 1


def test_manager_distinguishes_empty_response_from_failure(monkeypatch):
    from client_manager import ClientManager
    manager = ClientManager.__new__(ClientManager)
    monkeypatch.setattr(manager, '_get_session', lambda node: (object(), '') if node['id'] == 1 else (None, ''))
    monkeypatch.setattr(manager, '_probe_v3', lambda *_: ('supported', []))
    clients, failed = manager._get_all_clients_with_status([{'id': 1}, {'id': 2}])
    assert clients == []
    assert failed == {2}
