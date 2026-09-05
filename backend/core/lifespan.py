from contextlib import asynccontextmanager


def build_lifespan(
    *,
    sync_node_history_names_with_nodes,
    backfill_traffic_history_snapshots=None,
    audit_worker_loop,
    audit_flush=None,
    snapshot_collector,
    adguard_collector_loop,
    asyncio_module,
    telegram_provisioning_worker_loop=None,
    telegram_outbox_worker_loop=None,
    telegram_retention_worker_loop=None,
):
    state = {
        "audit_worker_task": None,
        "adguard_collector_task": None,
        "telegram_provisioning_worker_task": None,
        "telegram_outbox_worker_task": None,
        "telegram_retention_worker_task": None,
    }

    @asynccontextmanager
    async def lifespan(app):
        await asyncio_module.to_thread(sync_node_history_names_with_nodes)
        if backfill_traffic_history_snapshots is not None:
            await asyncio_module.to_thread(backfill_traffic_history_snapshots)
        state["audit_worker_task"] = asyncio_module.create_task(audit_worker_loop())
        await snapshot_collector.start()
        state["adguard_collector_task"] = asyncio_module.create_task(adguard_collector_loop())
        if telegram_provisioning_worker_loop is not None:
            state["telegram_provisioning_worker_task"] = asyncio_module.create_task(
                telegram_provisioning_worker_loop()
            )
        if telegram_outbox_worker_loop is not None:
            state["telegram_outbox_worker_task"] = asyncio_module.create_task(telegram_outbox_worker_loop())
        if telegram_retention_worker_loop is not None:
            state["telegram_retention_worker_task"] = asyncio_module.create_task(telegram_retention_worker_loop())
        try:
            yield
        finally:
            if state["telegram_retention_worker_task"]:
                state["telegram_retention_worker_task"].cancel()
                try:
                    await state["telegram_retention_worker_task"]
                except asyncio_module.CancelledError:
                    pass
                state["telegram_retention_worker_task"] = None
            if state["telegram_outbox_worker_task"]:
                state["telegram_outbox_worker_task"].cancel()
                try:
                    await state["telegram_outbox_worker_task"]
                except asyncio_module.CancelledError:
                    pass
                state["telegram_outbox_worker_task"] = None
            if state["telegram_provisioning_worker_task"]:
                state["telegram_provisioning_worker_task"].cancel()
                try:
                    await state["telegram_provisioning_worker_task"]
                except asyncio_module.CancelledError:
                    pass
                state["telegram_provisioning_worker_task"] = None
            if state["audit_worker_task"]:
                state["audit_worker_task"].cancel()
                try:
                    await state["audit_worker_task"]
                except asyncio_module.CancelledError:
                    pass
                state["audit_worker_task"] = None
            if audit_flush is not None:
                await asyncio_module.to_thread(audit_flush)
            if state["adguard_collector_task"]:
                state["adguard_collector_task"].cancel()
                try:
                    await state["adguard_collector_task"]
                except asyncio_module.CancelledError:
                    pass
                state["adguard_collector_task"] = None
            await snapshot_collector.stop()

    return lifespan
