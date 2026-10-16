from contextlib import asynccontextmanager

from core.lifecycle_work import LifecycleWorkTracker


def build_lifespan(
    *,
    sync_node_history_names_with_nodes,
    backfill_traffic_history_snapshots=None,
    audit_worker_loop,
    audit_flush=None,
    audit_close_admission=None,
    snapshot_collector,
    adguard_collector_loop,
    asyncio_module,
    telegram_existing_discovery_worker_loop=None,
    telegram_provisioning_worker_loop=None,
    telegram_outbox_worker_loop=None,
    telegram_retention_worker_loop=None,
    telegram_reminder_worker_loop=None,
    telegram_polling_worker_loop=None,
):
    """Build the one production lifespan with explicit blocking-work ownership."""

    @asynccontextmanager
    async def lifespan(app):
        del app
        worker_tracker = LifecycleWorkTracker(asyncio_module=asyncio_module)
        await worker_tracker.run(
            "startup.sync_node_history", sync_node_history_names_with_nodes
        )
        if backfill_traffic_history_snapshots is not None:
            await worker_tracker.run(
                "startup.backfill_traffic_history", backfill_traffic_history_snapshots
            )

        await snapshot_collector.start(worker_tracker)
        worker_loops = [
            audit_worker_loop,
            adguard_collector_loop,
            telegram_existing_discovery_worker_loop,
            telegram_provisioning_worker_loop,
            telegram_outbox_worker_loop,
            telegram_retention_worker_loop,
            telegram_reminder_worker_loop,
            telegram_polling_worker_loop,
        ]
        tasks = [
            asyncio_module.create_task(loop(worker_tracker))
            for loop in worker_loops
            if loop is not None
        ]
        try:
            yield
        finally:
            if audit_close_admission is not None:
                audit_close_admission()
            worker_tracker.close_admission()

            # Do not cancel tasks: cancelling an asyncio.to_thread awaiter
            # leaves its blocking call alive. Every loop exits through the
            # tracker, and terminal shutdown waits for its actual completion.
            if tasks:
                await asyncio_module.gather(*tasks, return_exceptions=True)
            await snapshot_collector.stop()
            if audit_flush is not None:
                await worker_tracker.run_shutdown("shutdown.audit_flush", audit_flush)
            await worker_tracker.drain()

    return lifespan
