import asyncio
import logging
import sys
from threading import Event
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.lifecycle_work import LifecycleWorkAdmissionClosed, LifecycleWorkTracker
from core.lifespan import build_lifespan
from services.adguard_runtime import AdGuardRuntime
from services.collector import SnapshotCollector
from services.runtime_support import AuditQueueRuntime


def test_tracker_keeps_cancelled_awaiter_owned_until_blocking_thread_exits():
    async def exercise():
        entered = Event()
        release = Event()
        tracker = LifecycleWorkTracker()

        def blocking_call():
            entered.set()
            release.wait(timeout=2)
            return "finished"

        waiter = asyncio.create_task(tracker.run("test.blocking", blocking_call))
        await asyncio.to_thread(entered.wait, 1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert tracker.inflight_count == 1
        tracker.close_admission()
        drain = asyncio.create_task(tracker.drain())
        await asyncio.sleep(0)
        assert not drain.done()
        release.set()
        await drain
        assert tracker.inflight_count == 0
        with pytest.raises(LifecycleWorkAdmissionClosed):
            await tracker.run("test.after_close", lambda: None)

    asyncio.run(exercise())


def test_lifespan_waits_for_registered_work_before_terminal_shutdown_and_closes_audit_admission():
    async def exercise():
        started = Event()
        release = Event()
        events = []

        class Collector:
            async def start(self, worker_tracker):
                self.worker_tracker = worker_tracker
                events.append("collector-start")

            async def stop(self):
                events.append("collector-stop")

        async def blocking_loop(worker_tracker):
            def blocking_call():
                started.set()
                release.wait(timeout=2)
                events.append("blocking-finished")

            await worker_tracker.run("test.blocking_loop", blocking_call)

        def close_audit_admission():
            events.append("audit-close")

        def flush_audit():
            events.append("audit-flush")

        lifespan = build_lifespan(
            sync_node_history_names_with_nodes=lambda: events.append("startup"),
            audit_worker_loop=blocking_loop,
            audit_flush=flush_audit,
            audit_close_admission=close_audit_admission,
            snapshot_collector=Collector(),
            adguard_collector_loop=lambda _tracker: asyncio.sleep(0),
            asyncio_module=asyncio,
        )

        context = lifespan(None)
        await context.__aenter__()
        await asyncio.to_thread(started.wait, 1)
        close_task = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.sleep(0)
        assert not close_task.done()
        assert events[-1] == "audit-close"
        release.set()
        await close_task
        assert (
            events.index("blocking-finished")
            < events.index("collector-stop")
            < events.index("audit-flush")
        )

    asyncio.run(exercise())


def test_audit_runtime_refuses_new_events_after_shutdown_admission_closes(tmp_path):
    runtime = AuditQueueRuntime(
        db_path=str(tmp_path / "admin.db"),
        batch_size=1,
        idle_sleep_sec=1,
        active_sleep_sec=0.1,
        logger=logging.getLogger("test.audit.shutdown"),
    )
    assert runtime.enqueue_event({"request_id": "before"}) is True
    runtime.close_admission()
    assert runtime.enqueue_event({"request_id": "after"}) is False
    assert runtime.pending_count() == 1


def test_adguard_collector_refuses_second_blocking_operation_after_admission_closes():
    async def exercise():
        tracker = LifecycleWorkTracker()
        calls = []

        class Monitor:
            def collect_source(self, source):
                calls.append(("collect", source["id"]))
                tracker.close_admission()
                return {"source_id": source["id"], "available": True}

        runtime = AdGuardRuntime(
            db_path="unused.db",
            requests_verify=True,
            collect_interval_sec=20,
            latest_state={},
            latest_lock=__import__("threading").Lock(),
            adguard_monitor=Monitor(),
            source_available_metric=None,
            dns_queries_total_metric=None,
            dns_blocked_total_metric=None,
            dns_block_rate_metric=None,
            dns_latency_ms_metric=None,
            dns_cache_hit_ratio_metric=None,
            dns_upstream_errors_metric=None,
            logger=logging.getLogger("test.adguard.shutdown"),
        )
        runtime.list_enabled_sources_raw = lambda: [{"id": 1}]
        runtime.record_snapshot = lambda _snapshot: calls.append(("record", 1))

        with pytest.raises(LifecycleWorkAdmissionClosed):
            await runtime.collect_once(tracker)
        assert calls == [("collect", 1)]
        await tracker.drain()

    asyncio.run(exercise())


def test_snapshot_collector_does_not_start_node_mutation_after_shutdown_closes_admission():
    async def exercise():
        entered_fetch = Event()
        release_fetch = Event()
        polled = []
        tracker = LifecycleWorkTracker()

        def fetch_nodes():
            entered_fetch.set()
            release_fetch.wait(timeout=2)
            return [{"id": 1, "name": "alpha"}]

        class Monitor:
            def get_server_status(self, _node):
                polled.append("status")
                return {"available": False}

        collector = SnapshotCollector(
            fetch_nodes=fetch_nodes,
            xui_monitor=Monitor(),
            ws_manager=object(),
            base_interval_sec=60,
        )
        await collector.start(tracker)
        await asyncio.to_thread(entered_fetch.wait, 1)
        tracker.close_admission()
        release_fetch.set()
        await collector.stop()
        await tracker.drain()
        assert polled == []

    asyncio.run(exercise())
