"""Thread-safe, process-local health of periodic workers."""

import logging
import re
import threading
import time
from datetime import datetime, timezone

from shared.metrics_registry import worker_healthy

_lock = threading.RLock()
_workers = {}
_logger = logging.getLogger(__name__)


def _timestamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def _update(entry, now):
    healthy = (entry["consecutive_failures"] < 5 and
               now - (entry["_success_time"] if entry["_success_time"] is not None else entry["_registered_time"]) <= 3 * entry["interval_sec"])
    if healthy != entry["healthy"]:
        entry["healthy"] = healthy
        if healthy:
            _logger.info("Worker %s recovered", entry["name"])
        else:
            _logger.error("Worker %s unhealthy", entry["name"])
    return healthy


def register(name, interval_sec):
    if interval_sec <= 0:
        raise ValueError("interval_sec must be positive")
    with _lock:
        if name not in _workers:
            _workers[name] = dict(name=name, interval_sec=interval_sec, last_start_at=None,
                                  last_success_at=None, last_error_code=None,
                                  consecutive_failures=0, healthy=True,
                                  _registered_time=time.time(), _success_time=None)
            worker_healthy.labels(worker=name).set_function(lambda: _metric_value(name))
        else:
            _workers[name]["interval_sec"] = interval_sec


def _metric_value(name):
    with _lock:
        return int(_update(_workers[name], time.time()))


def mark_start(name):
    with _lock:
        now = time.time()
        _workers[name]["last_start_at"] = _timestamp(now)
        _update(_workers[name], now)


def mark_success(name):
    with _lock:
        now = time.time()
        entry = _workers[name]
        _update(entry, now)
        entry.update(last_success_at=_timestamp(now), _success_time=now,
                     consecutive_failures=0)
        _update(entry, now)


def mark_failure(name, error_code):
    with _lock:
        entry = _workers[name]
        code = str(error_code)
        entry["last_error_code"] = code if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", code) else "Error"
        entry["consecutive_failures"] += 1
        _update(entry, time.time())


def snapshot():
    with _lock:
        now = time.time()
        for entry in _workers.values():
            _update(entry, now)
        return [{key: value for key, value in entry.items() if not key.startswith("_")}
                for entry in _workers.values()]
