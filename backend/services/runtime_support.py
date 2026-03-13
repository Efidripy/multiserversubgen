from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Dict


class RedisJsonCache:
    def __init__(self, *, redis_module, redis_url: str, logger) -> None:
        self.redis_module = redis_module
        self.redis_url = redis_url
        self.logger = logger
        self._client = None

    def get_client(self):
        if not self.redis_url or self.redis_module is None:
            return None
        if self._client is not None:
            return self._client
        try:
            self._client = self.redis_module.Redis.from_url(self.redis_url, decode_responses=True)
        except Exception as exc:
            self.logger.warning(f"Failed to initialize redis client: {exc}")
            self._client = None
        return self._client

    def get_json(self, key: str):
        client = self.get_client()
        if not client:
            return None
        try:
            raw = client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            self.logger.warning(f"Redis get failed for {key}: {exc}")
            return None

    def set_json(self, key: str, value, ttl: int) -> None:
        client = self.get_client()
        if not client:
            return
        try:
            client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:
            self.logger.warning(f"Redis set failed for {key}: {exc}")

    def delete(self, *keys: str) -> None:
        client = self.get_client()
        if not client:
            return
        try:
            client.delete(*keys)
        except Exception as exc:
            self.logger.warning(f"Redis delete failed: {exc}")


class AuditQueueRuntime:
    def __init__(self, *, db_path: str, batch_size: int, idle_sleep_sec: float, active_sleep_sec: float, logger) -> None:
        self.db_path = db_path
        self.batch_size = batch_size
        self.idle_sleep_sec = idle_sleep_sec
        self.active_sleep_sec = active_sleep_sec
        self.logger = logger

    def enqueue_event(self, payload: Dict) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO audit_events (payload) VALUES (?)",
                    (json.dumps(payload, ensure_ascii=False),),
                )
                conn.commit()
        except Exception as exc:
            self.logger.warning(f"Failed to enqueue audit event: {exc}")

    def drain_batch(self, limit: int) -> int:
        with sqlite3.connect(self.db_path) as conn:
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
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM audit_events WHERE id IN ({placeholders})", ids)
            conn.commit()
            return len(ids)

    async def worker_loop(self) -> None:
        while True:
            try:
                drained = await asyncio.to_thread(self.drain_batch, self.batch_size)
                await asyncio.sleep(self.active_sleep_sec if drained > 0 else self.idle_sleep_sec)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.error(f"audit worker error: {exc}")
                await asyncio.sleep(self.idle_sleep_sec)
