"""Prometheus metrics helpers.

Thin wrappers around ``prometheus_client`` that:

* Provide a consistent naming convention (``sub_manager_*``).
* Allow callers to use the same interface whether or not
  ``prometheus_client`` is installed (graceful no-op fallback).
* Expose a :func:`get_registry` helper for test isolation.

Usage::

    from shared.metrics import Counter, Histogram, Gauge

    request_count = Counter(
        "http_requests_total",
        "Total HTTP requests",
        labels=["method", "path", "status"],
    )
    request_count.labels(method="GET", path="/api/v1/nodes", status="200").inc()

    latency = Histogram(
        "http_request_duration_seconds",
        "Request latency",
        labels=["method", "path"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
    )
    with latency.labels(method="GET", path="/api/v1/nodes").time():
        ...
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)

_PREFIX = "sub_manager"


# ---------------------------------------------------------------------------
# Try to import prometheus_client; fall back to no-ops
# ---------------------------------------------------------------------------

try:
    from prometheus_client import (  # type: ignore[import-untyped]
        Counter as _PrometheusCounter,
        Gauge as _PrometheusGauge,
        Histogram as _PrometheusHistogram,
        REGISTRY as _REGISTRY,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.warning("shared.metrics: prometheus_client not installed – metrics disabled")


# ---------------------------------------------------------------------------
# Public metric classes
# ---------------------------------------------------------------------------

class _NoOpMetric:
    """Returned by :class:`Counter` / :class:`Gauge` / :class:`Histogram` when
    Prometheus is not available."""

    def labels(self, **_: Any) -> "_NoOpMetric":
        return self

    def inc(self, *_: Any, **__: Any) -> None:
        pass

    def dec(self, *_: Any, **__: Any) -> None:
        pass

    def set(self, *_: Any, **__: Any) -> None:
        pass

    def observe(self, *_: Any, **__: Any) -> None:
        pass

    def __enter__(self) -> "_NoOpMetric":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def time(self) -> "_NoOpMetric":
        return self


def _full_name(name: str) -> str:
    if name.startswith(_PREFIX):
        return name
    return f"{_PREFIX}_{name}"


class Counter:
    """Prometheus Counter wrapper."""

    def __init__(
        self,
        name: str,
        documentation: str,
        *,
        labels: Optional[List[str]] = None,
    ) -> None:
        self._metric: Any
        if _PROMETHEUS_AVAILABLE:
            try:
                self._metric = _PrometheusCounter(
                    _full_name(name),
                    documentation,
                    labels or [],
                )
            except ValueError:
                # Already registered (e.g. in tests)
                from prometheus_client import REGISTRY  # type: ignore[import-untyped]
                self._metric = REGISTRY._names_to_collectors.get(_full_name(name), _NoOpMetric())
        else:
            self._metric = _NoOpMetric()

    def labels(self, **kwargs: Any) -> Any:
        return self._metric.labels(**kwargs) if kwargs else self._metric

    def inc(self, amount: float = 1) -> None:
        self._metric.inc(amount)


class Gauge:
    """Prometheus Gauge wrapper."""

    def __init__(
        self,
        name: str,
        documentation: str,
        *,
        labels: Optional[List[str]] = None,
    ) -> None:
        self._metric: Any
        if _PROMETHEUS_AVAILABLE:
            try:
                self._metric = _PrometheusGauge(
                    _full_name(name),
                    documentation,
                    labels or [],
                )
            except ValueError:
                from prometheus_client import REGISTRY  # type: ignore[import-untyped]
                self._metric = REGISTRY._names_to_collectors.get(_full_name(name), _NoOpMetric())
        else:
            self._metric = _NoOpMetric()

    def labels(self, **kwargs: Any) -> Any:
        return self._metric.labels(**kwargs) if kwargs else self._metric

    def set(self, value: float) -> None:
        self._metric.set(value)

    def inc(self, amount: float = 1) -> None:
        self._metric.inc(amount)

    def dec(self, amount: float = 1) -> None:
        self._metric.dec(amount)


class Histogram:
    """Prometheus Histogram wrapper."""

    DEFAULT_BUCKETS = (
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
    )

    def __init__(
        self,
        name: str,
        documentation: str,
        *,
        labels: Optional[List[str]] = None,
        buckets: Optional[Sequence[float]] = None,
    ) -> None:
        self._metric: Any
        if _PROMETHEUS_AVAILABLE:
            try:
                self._metric = _PrometheusHistogram(
                    _full_name(name),
                    documentation,
                    labels or [],
                    buckets=buckets or self.DEFAULT_BUCKETS,
                )
            except ValueError:
                from prometheus_client import REGISTRY  # type: ignore[import-untyped]
                self._metric = REGISTRY._names_to_collectors.get(_full_name(name), _NoOpMetric())
        else:
            self._metric = _NoOpMetric()

    def labels(self, **kwargs: Any) -> Any:
        return self._metric.labels(**kwargs) if kwargs else self._metric

    def observe(self, value: float) -> None:
        self._metric.observe(value)

    def time(self) -> Any:
        return self._metric.time()
