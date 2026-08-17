from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_clients_routes_offload_sync_panel_and_storage_calls():
    source = (REPO / "backend/routers/clients.py").read_text(encoding="utf-8")

    assert "from fastapi.concurrency import run_in_threadpool" in source
    assert "async def _run" in source
    assert "await _run(client_mgr.batch_add_clients" in source
    assert "await _run(client_mgr.get_online_clients" in source
    assert "await _run(enrich_clients_with_notes" in source


def test_subscriptions_routes_are_fastapi_sync_worker_handlers():
    source = (REPO / "backend/routers/subscriptions.py").read_text(encoding="utf-8")

    assert "FastAPI runs sync route" in source
    assert "def get_sub(" in source
    assert "def get_sub_grouped(" in source
    assert "async def get_sub(" not in source
    assert "async def get_sub_grouped(" not in source


def test_sqlite_and_monitoring_http_routes_use_fastapi_worker_handlers():
    nodes = (REPO / "backend/routers/nodes.py").read_text(encoding="utf-8")
    monitoring = (REPO / "backend/routers/monitoring.py").read_text(encoding="utf-8")

    assert "FastAPI run the complete transaction in its worker thread pool" in nodes
    assert "def add_node(" in nodes
    assert "def update_node(" in nodes
    assert "def delete_node(" in nodes
    assert "async def add_node(" not in nodes
    assert "dispatches sync endpoints through its worker thread pool" in monitoring
    assert "def monitoring_stack(" in monitoring
    assert "async def monitoring_stack(" not in monitoring
