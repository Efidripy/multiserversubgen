import asyncio
import threading
import time

from routers.operations import _collect_backups


def test_backup_fanout_is_bounded_ordered_and_isolates_failures():
    active = 0
    peak = 0
    lock = threading.Lock()

    def fetch(node):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)
            if node["name"] == "failed":
                raise RuntimeError("transport detail must not escape")
            return {"node": node["name"], "backup_b64": node["name"]}
        finally:
            with lock:
                active -= 1

    nodes = [{"name": name} for name in ("slow", "failed", "fast", "last", "tail")]
    backups = asyncio.run(_collect_backups(nodes, fetch, max_workers=2))

    assert peak <= 2
    assert [item["node"] for item in backups] == ["slow", "failed", "fast", "last", "tail"]
    assert backups[1] == {"node": "failed", "error": "backup request failed"}
    assert backups[0]["backup_b64"] == "slow"
