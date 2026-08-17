import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from routers.operations import build_operations_router
from services import client_notes, runtime_support
from services.client_notes import enrich_clients_with_notes
from services.db_bootstrap import connect, init_db
from services.runtime_support import AuditQueueRuntime, RedisJsonCache
from services.clients_runtime import ClientsRuntime
from services.inbounds_runtime import InboundsRuntime


def test_audit_enqueue_is_memory_only_and_bounded(monkeypatch, tmp_path):
    runtime = AuditQueueRuntime(
        db_path=str(tmp_path / "admin.db"),
        batch_size=2,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        memory_queue_max_size=1,
        logger=logging.getLogger("test.audit"),
    )

    def fail_connect(*_args, **_kwargs):
        raise AssertionError("HTTP enqueue must not open SQLite")

    monkeypatch.setattr(runtime_support, "connect", fail_connect)
    assert runtime.enqueue_event({"request_id": "one"}) is True
    assert runtime.enqueue_event({"request_id": "two"}) is False
    assert runtime.pending_count() == 1
    assert runtime.dropped_events == 1


def test_audit_worker_batches_persistence_and_drains_legacy_rows(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    runtime = AuditQueueRuntime(
        db_path=db_path,
        batch_size=10,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        logger=logging.getLogger("test.audit"),
    )

    assert runtime.enqueue_event({"request_id": "one"})
    assert runtime.enqueue_event({"request_id": "two"})
    assert runtime.persist_memory_batch(10) == 2
    assert runtime.drain_batch(10) == 2
    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0


def test_redis_cache_trips_circuit_after_connect_failure():
    clock = [0.0]
    calls = []

    class BrokenRedis:
        @staticmethod
        def from_url(*args, **kwargs):
            calls.append((args, kwargs))
            raise OSError("redis unavailable")

    class RedisModule:
        Redis = BrokenRedis

    cache = RedisJsonCache(
        redis_module=RedisModule,
        redis_url="redis://127.0.0.1:6379/0",
        logger=logging.getLogger("test.redis"),
        failure_cooldown_sec=30,
        monotonic=lambda: clock[0],
    )

    assert cache.get_json("clients") is None
    assert len(calls) == 1
    assert calls[0][1]["socket_connect_timeout"] == 0.2
    assert calls[0][1]["socket_timeout"] == 0.2
    assert cache.get_json("clients") is None
    assert len(calls) == 1
    clock[0] = 31
    assert cache.get_json("clients") is None
    assert len(calls) == 2


def test_clients_and_inbounds_cold_cache_misses_are_single_flight():
    started = Event()
    release = Event()

    class ClientManager:
        calls = 0

        def get_all_clients(self, _nodes, email_filter=None):
            self.calls += 1
            started.set()
            release.wait(timeout=2)
            return [{"email": "one@example.test"}]

    client_manager = ClientManager()
    clients_runtime = ClientsRuntime(
        client_mgr=client_manager,
        clients_cache={"ts": 0.0, "data": []},
        clients_cache_ttl=60,
        clients_cache_stale_ttl=300,
        start_cache_refresh=lambda *_args, **_kwargs: None,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(clients_runtime.get_cached_clients, [])
        assert started.wait(timeout=1)
        second = executor.submit(clients_runtime.get_cached_clients, [])
        release.set()
        assert first.result(timeout=2) == second.result(timeout=2)
    assert client_manager.calls == 1

    class InboundManager:
        calls = 0

        def get_all_inbounds(self, _nodes):
            self.calls += 1
            return [{"id": 1}]

    inbound_manager = InboundManager()
    inbounds_runtime = InboundsRuntime(
        inbound_mgr=inbound_manager,
        inbounds_cache={"ts": 0.0, "data": []},
        start_cache_refresh=lambda *_args, **_kwargs: None,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: inbounds_runtime.get_cached_inbounds([]), range(2)))
    assert results == [[{"id": 1}], [{"id": 1}]]
    assert inbound_manager.calls == 1


def test_client_notes_query_only_matches_requested_identities(monkeypatch, tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO client_notes (node_id, inbound_id, client_identifier, email, notes) VALUES (?, ?, ?, ?, ?)",
            (1, 11, "wanted", "wanted@example.test", "wanted note"),
        )
        conn.execute(
            "INSERT INTO client_notes (node_id, inbound_id, client_identifier, email, notes) VALUES (?, ?, ?, ?, ?)",
            (2, 22, "unrelated", "other@example.test", "must not be returned"),
        )

    statements = []
    original_connect = client_notes.connect

    def traced_connect(path):
        connection = original_connect(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(client_notes, "connect", traced_connect)
    enriched = enrich_clients_with_notes(
        db_path,
        [{"id": "wanted", "node_id": 1, "inbound_id": 11}],
    )

    assert enriched[0]["notes"] == "wanted note"
    select = next(statement for statement in statements if "SELECT node_id" in statement)
    assert "WHERE (node_id" in select
    assert "unrelated" not in select


def test_fleet_history_is_one_bounded_route(tmp_path):
    db_path = str(tmp_path / "admin.db")
    init_db(db_path)
    now = int(time.time())
    with connect(db_path) as conn:
        history_rows = [
            (now - offset, node_id, node_name, 1, 1, cpu, online, traffic + offset, 5)
            for node_id, node_name, cpu, online, traffic in ((1, "alpha", 10, 2, 1000), (2, "beta", 20, 4, 2000))
            for offset in range(1, 102)
        ]
        conn.executemany(
            """
            INSERT INTO node_history (ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            history_rows,
        )

    class NodeService:
        def list_nodes(self):
            return []

    class SnapshotCollector:
        def latest_snapshot(self):
            return {}

    app = FastAPI()
    app.include_router(
        build_operations_router(
            check_auth=lambda _request: "admin",
            db_path=db_path,
            node_service=NodeService(),
            client_mgr=object(),
            server_monitor=object(),
            get_node_or_404=lambda _node_id: {},
            snapshot_collector=SnapshotCollector(),
        )
    )
    response = TestClient(app).get("/api/v1/history/nodes?since_sec=999999&limit_per_node=100")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 200
    assert {point["node_id"] for point in payload["points"]} == {1, 2}
    assert {point["ts"] for point in payload["points"]} == set(range(now - 100, now))
