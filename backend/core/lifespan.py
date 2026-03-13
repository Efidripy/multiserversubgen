from contextlib import asynccontextmanager


def build_lifespan(
    *,
    sync_node_history_names_with_nodes,
    audit_worker_loop,
    snapshot_collector,
    adguard_collector_loop,
    asyncio_module,
):
    state = {"audit_worker_task": None, "adguard_collector_task": None}

    @asynccontextmanager
    async def lifespan(app):
        await asyncio_module.to_thread(sync_node_history_names_with_nodes)
        state["audit_worker_task"] = asyncio_module.create_task(audit_worker_loop())
        await snapshot_collector.start()
        state["adguard_collector_task"] = asyncio_module.create_task(adguard_collector_loop())
        try:
            yield
        finally:
            if state["audit_worker_task"]:
                state["audit_worker_task"].cancel()
                try:
                    await state["audit_worker_task"]
                except asyncio_module.CancelledError:
                    pass
                state["audit_worker_task"] = None
            if state["adguard_collector_task"]:
                state["adguard_collector_task"].cancel()
                try:
                    await state["adguard_collector_task"]
                except asyncio_module.CancelledError:
                    pass
                state["adguard_collector_task"] = None
            await snapshot_collector.stop()

    return lifespan
