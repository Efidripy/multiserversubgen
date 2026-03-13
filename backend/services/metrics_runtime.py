from __future__ import annotations

import sqlite3
import time
from typing import Dict

from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest


class MetricsRuntime:
    def __init__(
        self,
        *,
        db_path: str,
        node_history_enabled: bool,
        node_history_min_interval_sec: int,
        node_history_retention_days: int,
        node_metric_labels_state: Dict[str, str],
        node_metric_labels_lock,
        history_write_state: Dict,
        history_write_lock,
        snapshot_collector,
        redis_get_client,
        redis_url: str,
        node_availability_metric,
        node_xray_running_metric,
        node_cpu_percent_metric,
        node_online_clients_metric,
        node_traffic_total_bytes_metric,
        node_poll_duration_ms_metric,
    ) -> None:
        self.db_path = db_path
        self.node_history_enabled = node_history_enabled
        self.node_history_min_interval_sec = node_history_min_interval_sec
        self.node_history_retention_days = node_history_retention_days
        self.node_metric_labels_state = node_metric_labels_state
        self.node_metric_labels_lock = node_metric_labels_lock
        self.history_write_state = history_write_state
        self.history_write_lock = history_write_lock
        self.snapshot_collector = snapshot_collector
        self.redis_get_client = redis_get_client
        self.redis_url = redis_url
        self.node_availability_metric = node_availability_metric
        self.node_xray_running_metric = node_xray_running_metric
        self.node_cpu_percent_metric = node_cpu_percent_metric
        self.node_online_clients_metric = node_online_clients_metric
        self.node_traffic_total_bytes_metric = node_traffic_total_bytes_metric
        self.node_poll_duration_ms_metric = node_poll_duration_ms_metric
        self._metrics_cache: Dict = {"payload": None, "ts": 0.0}
        self._metrics_cache_lock = None

    def set_metrics_cache_lock(self, lock) -> None:
        self._metrics_cache_lock = lock

    def remove_node_metric_labels(self, node_name: str, node_id: str) -> None:
        for metric in (
            self.node_availability_metric,
            self.node_xray_running_metric,
            self.node_cpu_percent_metric,
            self.node_online_clients_metric,
            self.node_traffic_total_bytes_metric,
            self.node_poll_duration_ms_metric,
        ):
            try:
                metric.remove(node_name, node_id)
            except (KeyError, ValueError):
                pass

    def record_node_snapshot(self, snapshot: Dict) -> None:
        node_name = str(snapshot.get("name", "unknown"))
        node_id = str(snapshot.get("node_id", "0"))

        with self.node_metric_labels_lock:
            prev_name = self.node_metric_labels_state.get(node_id)
            if prev_name and prev_name != node_name:
                self.remove_node_metric_labels(prev_name, node_id)
            self.node_metric_labels_state[node_id] = node_name

        self.node_availability_metric.labels(node_name=node_name, node_id=node_id).set(
            1 if snapshot.get("available") else 0
        )
        self.node_xray_running_metric.labels(node_name=node_name, node_id=node_id).set(
            1 if snapshot.get("xray_running") else 0
        )
        self.node_cpu_percent_metric.labels(node_name=node_name, node_id=node_id).set(
            float(snapshot.get("cpu", 0) or 0)
        )
        self.node_online_clients_metric.labels(node_name=node_name, node_id=node_id).set(
            float(snapshot.get("online_clients", 0) or 0)
        )
        self.node_traffic_total_bytes_metric.labels(node_name=node_name, node_id=node_id).set(
            float(snapshot.get("traffic_total", 0) or 0)
        )
        self.node_poll_duration_ms_metric.labels(node_name=node_name, node_id=node_id).set(
            float(snapshot.get("poll_ms", 0) or 0)
        )

        if not self.node_history_enabled:
            return

        now_ts = time.time()
        with self.history_write_lock:
            node_last = self.history_write_state["last_by_node"].get(node_id, 0.0)
            if now_ts - node_last < max(1, self.node_history_min_interval_sec):
                return
            self.history_write_state["last_by_node"][node_id] = now_ts

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO node_history (
                    ts, node_id, node_name, available, xray_running, cpu, online_clients, traffic_total, poll_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(now_ts),
                    int(snapshot.get("node_id") or 0),
                    node_name,
                    1 if snapshot.get("available") else 0,
                    1 if snapshot.get("xray_running") else 0,
                    float(snapshot.get("cpu", 0) or 0),
                    int(snapshot.get("online_clients", 0) or 0),
                    float(snapshot.get("traffic_total", 0) or 0),
                    float(snapshot.get("poll_ms", 0) or 0),
                ),
            )

            with self.history_write_lock:
                do_cleanup = now_ts - self.history_write_state["last_cleanup_ts"] >= 3600
                if do_cleanup:
                    self.history_write_state["last_cleanup_ts"] = now_ts
            if do_cleanup:
                cutoff = int(now_ts - max(1, self.node_history_retention_days) * 86400)
                conn.execute("DELETE FROM node_history WHERE ts < ?", (cutoff,))
            conn.commit()

    def render_metrics_response(self) -> Response:
        mode = self.snapshot_collector.get_mode()
        if mode == "ultra_idle":
            ttl = 60.0
        elif mode == "idle":
            ttl = 30.0
        elif mode == "warming":
            ttl = 10.0
        else:
            ttl = 15.0

        with self._metrics_cache_lock:
            now = time.time()
            if self._metrics_cache["payload"] is not None and (now - self._metrics_cache["ts"]) < ttl:
                return Response(self._metrics_cache["payload"], media_type=CONTENT_TYPE_LATEST)
            payload = generate_latest()
            self._metrics_cache["payload"] = payload
            self._metrics_cache["ts"] = now
            return Response(payload, media_type=CONTENT_TYPE_LATEST)

    def deps_health_status(self) -> Dict:
        redis_ok = False
        redis_error = None
        client = self.redis_get_client()
        if client is None:
            redis_error = "disabled_or_unavailable"
        else:
            try:
                redis_ok = bool(client.ping())
            except Exception as exc:
                redis_error = str(exc)

        return {
            "status": "ok" if self.snapshot_collector.is_running() else "degraded",
            "collector_running": self.snapshot_collector.is_running(),
            "redis": {"enabled": bool(self.redis_url), "ok": redis_ok, "error": redis_error},
        }
