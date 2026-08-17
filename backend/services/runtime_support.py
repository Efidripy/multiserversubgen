from __future__ import annotations

import asyncio
import json
import queue
import sqlite3
import time
from typing import Dict

from services.db_bootstrap import connect
from shared.sql import delete_by_ids_query


class RedisJsonCache:
    """Best-effort Redis acceleration with a short circuit breaker."""

    def __init__(
        self,
        *,
        redis_module,
        redis_url: str,
        logger,
        socket_connect_timeout_sec: float = 0.2,
        socket_timeout_sec: float = 0.2,
        failure_cooldown_sec: float = 30.0,
        monotonic=time.monotonic,
    ) -> None:
        self.redis_module = redis_module
        self.redis_url = redis_url
        self.logger = logger
        self.socket_connect_timeout_sec = max(0.0, float(socket_connect_timeout_sec))
        self.socket_timeout_sec = max(0.0, float(socket_timeout_sec))
        self.failure_cooldown_sec = max(0.0, float(failure_cooldown_sec))
        self._monotonic = monotonic
        self._client = None
        self._disabled_until = 0.0

    def _trip(self, operation: str, exc: Exception) -> None:
        self._client = None
        self._disabled_until = self._monotonic() + self.failure_cooldown_sec
        self.logger.warning(
            "Redis %s failed; using in-memory cache for %.1fs: %s",
            operation,
            self.failure_cooldown_sec,
            exc,
        )

    def _mark_success(self) -> None:
        self._disabled_until = 0.0

    def get_client(self):
        if not self.redis_url or self.redis_module is None:
            return None
        if self._monotonic() < self._disabled_until:
            return None
        if self._client is not None:
            return self._client
        try:
            self._client = self.redis_module.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=self.socket_connect_timeout_sec,
                socket_timeout=self.socket_timeout_sec,
                retry_on_timeout=False,
            )
        except Exception as exc:
            self._trip("initialization", exc)
        return self._client

    def get_json(self, key: str):
        client = self.get_client()
        if not client:
            return None
        try:
            raw = client.get(key)
            if raw is None:
                return None
            value = json.loads(raw)
            self._mark_success()
            return value
        except Exception as exc:
            self._trip("get", exc)
            return None

    def set_json(self, key: str, value, ttl: int) -> None:
        client = self.get_client()
        if not client:
            return
        try:
            client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
            self._mark_success()
        except Exception as exc:
            self._trip("set", exc)

    def delete(self, *keys: str) -> None:
        client = self.get_client()
        if not client:
            return
        try:
            client.delete(*keys)
            self._mark_success()
        except Exception as exc:
            self._trip("delete", exc)


class AuditQueueRuntime:
    """Bounded audit buffer that keeps SQLite commits off the HTTP path."""

    def __init__(
        self,
        *,
        db_path: str,
        batch_size: int,
        idle_sleep_sec: float,
        active_sleep_sec: float,
        logger,
        memory_queue_max_size: int = 2000,
    ) -> None:
        self.db_path = db_path
        self.batch_size = max(1, int(batch_size))
        self.idle_sleep_sec = idle_sleep_sec
        self.active_sleep_sec = active_sleep_sec
        self.logger = logger
        self._memory_queue: queue.Queue[Dict] = queue.Queue(maxsize=max(1, int(memory_queue_max_size)))
        self.accepted_events = 0
        self.dropped_events = 0

    def enqueue_event(self, payload: Dict) -> bool:
        try:
            self._memory_queue.put_nowait(dict(payload))
            self.accepted_events += 1
            return True
        except queue.Full:
            self.dropped_events += 1
            self.logger.warning("Audit memory queue is full; dropping event (dropped=%s)", self.dropped_events)
            return False

    def pending_count(self) -> int:
        return self._memory_queue.qsize()

    def persist_memory_batch(self, limit: int) -> int:
        payloads = []
        for _ in range(max(1, int(limit))):
            try:
                payloads.append(self._memory_queue.get_nowait())
            except queue.Empty:
                break
        if not payloads:
            return 0

        try:
            with connect(self.db_path) as conn:
                conn.executemany(
                    "INSERT INTO audit_events (payload) VALUES (?)",
                    [(json.dumps(payload, ensure_ascii=False),) for payload in payloads],
                )
                conn.commit()
            return len(payloads)
        except Exception as exc:
            # The queue is deliberately bounded: requeuing a failed batch would
            # allow an unavailable SQLite file to grow process memory forever.
            self.dropped_events += len(payloads)
            self.logger.error("Failed to persist %s audit events: %s", len(payloads), exc)
            return 0

    def drain_batch(self, limit: int) -> int:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, payload FROM audit_events ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            if not rows:
                return 0
            ids = []
            for row in rows:
                ids.append(row["id"])
                try:
                    payload = json.loads(row["payload"])
                except Exception:
                    payload = {"event": "audit", "raw": row["payload"]}
                self.logger.info(json.dumps({"event": "audit_log", "payload": payload}, ensure_ascii=False))
            conn.execute(
                delete_by_ids_query("audit_events", "id", ids),
                ids,
            )
            conn.commit()
            return len(ids)

    def flush(self, max_batches: int = 1) -> Dict[str, int]:
        """Best-effort bounded shutdown flush; never called by HTTP handlers."""
        persisted = 0
        drained = 0
        for _ in range(max(1, int(max_batches))):
            persisted_now = self.persist_memory_batch(self.batch_size)
            drained_now = self.drain_batch(self.batch_size)
            persisted += persisted_now
            drained += drained_now
            if persisted_now == 0 and drained_now == 0:
                break
        return {
            "persisted": persisted,
            "drained": drained,
            "pending": self.pending_count(),
            "dropped": self.dropped_events,
        }

    async def worker_loop(self) -> None:
        while True:
            try:
                persisted = await asyncio.to_thread(self.persist_memory_batch, self.batch_size)
                drained = await asyncio.to_thread(self.drain_batch, self.batch_size)
                await asyncio.sleep(self.active_sleep_sec if persisted > 0 or drained > 0 else self.idle_sleep_sec)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error(f"audit worker error: {exc}")
                await asyncio.sleep(self.idle_sleep_sec)
