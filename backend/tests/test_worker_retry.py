import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import worker_health
from core.lifecycle_work import LifecycleWorkAdmissionClosed


@pytest.mark.parametrize(
    ("loop_name", "constructor"),
    [
        ("_telegram_provisioning_worker_loop", "TelegramScheduleWorker"),
        ("_telegram_existing_discovery_worker_loop", "TelegramExistingDiscoveryWorker"),
        ("_telegram_outbox_worker_loop", "TelegramOutboxWorker"),
        ("_telegram_retention_worker_loop", "TelegramRetentionService"),
        ("_telegram_reminder_worker_loop", "TelegramReminderService"),
    ],
)
def test_telegram_worker_retries_exception(loop_name, constructor, caplog, monkeypatch):
    failures = []
    original_failure = worker_health.mark_failure

    def record_failure(name, code):
        failures.append((name, code))
        original_failure(name, code)

    monkeypatch.setattr(worker_health, "mark_failure", record_failure)
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    node = next(item for item in ast.parse(source).body if getattr(item, "name", None) == loop_name)
    namespace = {
        "LifecycleWorkAdmissionClosed": LifecycleWorkAdmissionClosed,
        "worker_health": worker_health,
        "logger": logging.getLogger(__name__),
        "SETTINGS": SimpleNamespace(telegram=SimpleNamespace(
            primary_admin_id=0, local_proxy_url="", provisioning_worker_interval_sec=5,
            outbox_worker_interval_sec=5, retention_worker_interval_sec=5,
            reminder_worker_interval_sec=5,
        )),
        "DB_PATH": "test", "client_mgr": None, "node_service": SimpleNamespace(
            get_node=None, list_nodes=None,
        ),
        "telegram_token_provider": SimpleNamespace(get_token=None),
        "os": SimpleNamespace(getpid=lambda: 1),
        "live_stats_runtime": None,
    }
    constructors = [
        "ClientManagerProvisioningPort", "TelegramProvisioningWorker", "TelegramLifecycleWorker",
        "TelegramScheduleWorker", "TelegramRegistry", "TelegramExistingDiscoveryWorker",
        "ClientManagerLegacyDiscovery", "TelegramOutboxWorker", "TelegramApiOutboxPort",
        "TelegramApiTransport", "TelegramRetentionService", "TelegramReminderService",
    ]
    for name in constructors:
        namespace[name] = lambda *args, **kwargs: SimpleNamespace(run_once=lambda: None)
    assert constructor in namespace
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec"), namespace)

    class Tracker:
        accepting = True
        calls = 0

        async def run(self, label, function):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("private detail")
            return SimpleNamespace(processed=False)

        async def wait_or_stop(self, delay):
            return self.calls < 2

    tracker = Tracker()
    with caplog.at_level(logging.WARNING):
        asyncio.run(namespace[loop_name](tracker))
    assert tracker.calls >= 2
    assert len(failures) == 1
    assert failures[0][1] == "RuntimeError"
    assert "private detail" not in caplog.text
    name = {
        "_telegram_provisioning_worker_loop": "telegram.provisioning",
        "_telegram_existing_discovery_worker_loop": "telegram.existing_discovery",
        "_telegram_outbox_worker_loop": "telegram.outbox",
        "_telegram_retention_worker_loop": "telegram.retention",
        "_telegram_reminder_worker_loop": "telegram.reminder",
    }[loop_name]
    record = next(item for item in worker_health.snapshot() if item["name"] == name)
    assert record["last_success_at"] is not None
    assert record["consecutive_failures"] == 0
