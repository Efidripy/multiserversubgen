"""Ограниченная opt-in атрибуция запроса для OBS-001.

Модуль passive: он не меняет response, cache, SQLite query или node request.
Все labels — маленькие allow-list enum; request id и внешние значения не
попадают ни в labels, ни в Server-Timing.
"""

from __future__ import annotations

import os
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict

from prometheus_client import Counter, Histogram


_current: ContextVar["RequestAttribution | None"] = ContextVar(
    "request_attribution", default=None
)
_ENDPOINTS = {
    "/api/v1/dashboard/overview": "dashboard_overview",
    "/api/v1/telegram/node-policies": "telegram_node_policies",
    "/api/v1/nodes": "nodes",
}
_PREFIX_ENDPOINTS = (
    ("/api/v1/traffic", "traffic"),
    ("/api/v1/clients", "clients"),
    ("/api/v1/inbounds", "inbounds"),
)
_CACHE_SOURCES = {
    "memory_fresh",
    "memory_stale",
    "memory_miss",
    "redis",
    "snapshot",
    "none",
    "other",
}
_OPERATIONS = {
    "admission",
    "cache_lookup",
    "sqlite_read",
    "sqlite_write",
    "sqlite_pragma",
    "sqlite_other",
    "xui_auth",
    "xui_inbounds",
    "xui_clients",
    "xui_client_traffic",
    "xui_other",
    "other",
}
_OUTCOMES = {"ok", "http_4xx", "http_5xx", "locked", "error", "other"}
_COMPONENTS = {"admission", "cache", "sqlite", "node_rpc"}

_event_total = Counter(
    "sub_manager_observability_attribution_events_total",
    "Opt-in bounded request-attribution events",
    ["endpoint", "component", "operation", "outcome", "cache_source"],
)
_event_duration = Histogram(
    "sub_manager_observability_attribution_duration_seconds",
    "Opt-in bounded request-attribution duration",
    ["endpoint", "component", "operation", "outcome"],
)


def attribution_enabled() -> bool:
    return os.getenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def endpoint_label(path: str) -> str:
    """Return only a fixed endpoint class; never use an untrusted path."""
    if path in _ENDPOINTS:
        return _ENDPOINTS[path]
    for prefix, label in _PREFIX_ENDPOINTS:
        if path.startswith(prefix):
            return label
    return "other"


def _bounded(value: object, allowed: set[str]) -> str:
    value = str(value or "other")
    return value if value in allowed else "other"


def cache_source_label(value: object) -> str:
    return _bounded(value if value else "none", _CACHE_SOURCES)


def operation_label(value: object) -> str:
    return _bounded(value, _OPERATIONS)


def outcome_label(value: object) -> str:
    return _bounded(value, _OUTCOMES)


@dataclass
class RequestAttribution:
    """Request-local aggregate. Component timings can overlap by design."""

    request_id: str
    endpoint: str
    phase_ms: Dict[str, float] = field(default_factory=dict)
    cache_sources: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def add(
        self,
        *,
        component: str,
        operation: str,
        outcome: str,
        duration_seconds: float,
        cache_source: str,
    ) -> None:
        component = component if component in _COMPONENTS else "other"
        operation = operation_label(operation)
        outcome = outcome_label(outcome)
        cache_source = cache_source_label(cache_source)
        duration = max(0.0, float(duration_seconds or 0.0))
        # Metrics must be strictly observational. A collector failure may not
        # affect a customer request or the in-memory attribution snapshot.
        try:
            _event_total.labels(
                self.endpoint, component, operation, outcome, cache_source
            ).inc()
            if duration:
                _event_duration.labels(
                    self.endpoint, component, operation, outcome
                ).observe(duration)
        except Exception:
            pass
        with self._lock:
            self.phase_ms[component] = (
                self.phase_ms.get(component, 0.0) + duration * 1000.0
            )
            if component == "cache":
                self.cache_sources.add(cache_source)


def begin_request(request_id: str, path: str) -> Token | None:
    if not attribution_enabled():
        return None
    try:
        return _current.set(
            RequestAttribution(request_id=request_id, endpoint=endpoint_label(path))
        )
    except Exception:
        return None


def finish_request(token: Token | None) -> RequestAttribution | None:
    if token is None:
        return None
    try:
        attribution = _current.get()
        _current.reset(token)
        return attribution
    except Exception:
        return None


def record_admission(started_at: float, *, outcome: str = "ok") -> None:
    _record("admission", "admission", outcome, started_at, "none")


def record_cache(source: str, *, started_at: float | None = None) -> None:
    """Record cache source/count; duration is only supplied when measured."""
    _record("cache", "cache_lookup", "ok", started_at, source)


def record_sqlite(statement: str, *, started_at: float, outcome: str) -> None:
    """Measure one ``Connection.execute`` call, not fetch/commit or lock wait."""
    verb = str(statement or "").lstrip().split(None, 1)[0].upper() if statement else ""
    operation = {
        "SELECT": "sqlite_read",
        "EXPLAIN": "sqlite_read",
        "INSERT": "sqlite_write",
        "UPDATE": "sqlite_write",
        "DELETE": "sqlite_write",
        "PRAGMA": "sqlite_pragma",
    }.get(verb, "sqlite_other")
    _record("sqlite", operation, outcome, started_at, "none")


def record_node_rpc(url: str, *, method: str, started_at: float, outcome: str) -> None:
    """Classify an XUI attempt locally without exporting the URL or method."""
    try:
        path = str(url or "").split("?", 1)[0]
        if (
            "csrf-token" in path
            or path.endswith("/login")
            or path.endswith("/panel/login")
        ):
            operation = "xui_auth"
        elif "/clients/traffic/" in path or "getClientTraffics" in path:
            operation = "xui_client_traffic"
        elif "/clients/" in path:
            operation = "xui_clients"
        elif "/inbounds" in path:
            operation = "xui_inbounds"
        else:
            operation = "xui_other"
        _record("node_rpc", operation, outcome, started_at, "none")
    except Exception:
        # Attribute collection must not alter the original XUI error path.
        return


def server_timing(
    app_duration_ms: float, attribution: RequestAttribution | None
) -> str:
    """Build a privacy-safe timing header with a conservative remainder.

    Component durations are aggregates and may overlap. ``unaccounted`` is a
    lower-bound remainder after their sum, not proof of a worker/lock wait.
    """
    app_ms = max(0.0, float(app_duration_ms or 0.0))
    values = [f"app;dur={app_ms:.2f}"]
    if attribution is None:
        return values[0]
    accounted_ms = 0.0
    for component in ("admission", "sqlite", "node_rpc"):
        duration = max(0.0, attribution.phase_ms.get(component, 0.0))
        accounted_ms += duration
        if duration:
            values.append(f"{component};dur={duration:.2f}")
    if attribution.cache_sources:
        source = (
            next(iter(attribution.cache_sources))
            if len(attribution.cache_sources) == 1
            else "multiple"
        )
        values.append(f'cache;desc="{source}"')
    values.append(f"unaccounted;dur={max(0.0, app_ms - accounted_ms):.2f}")
    return ", ".join(values)


def _record(
    component: str,
    operation: str,
    outcome: str,
    started_at: float | None,
    cache_source: str,
) -> None:
    try:
        attribution = _current.get()
        if attribution is None:
            return
        started = time.perf_counter() if started_at is None else started_at
        attribution.add(
            component=component,
            operation=operation,
            outcome=outcome,
            duration_seconds=time.perf_counter() - started,
            cache_source=cache_source,
        )
    except Exception:
        # Never change a product request if instrumentation itself malfunctions.
        return
