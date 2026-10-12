from __future__ import annotations

import asyncio
import os
import sys
import time
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.request_middleware import build_request_controls_and_audit_middleware
from services.db_bootstrap import connect
import shared.observability as observability
from shared.observability import (
    RequestAttribution,
    begin_request,
    cache_source_label,
    finish_request,
    record_cache,
    record_node_rpc,
    server_timing,
)
import xui_session
import core.request_middleware as request_middleware


FIXTURE_PATH = (
    Path(__file__).parents[2] / "scripts" / "observability_browser_fixture.py"
)
_fixture_spec = importlib.util.spec_from_file_location("obs001_fixture", FIXTURE_PATH)
assert _fixture_spec is not None and _fixture_spec.loader is not None
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
build_fixture_app = _fixture_module.build_fixture_app


class _MetricValue:
    def inc(self):
        pass

    def observe(self, _value):
        pass


class _Metric:
    def labels(self, *_args):
        return _MetricValue()


class _RecordedMetric(_Metric):
    def __init__(self):
        self.labels_calls = []

    def labels(self, *args):
        self.labels_calls.append(args)
        return _MetricValue()


def _middleware():
    return build_request_controls_and_audit_middleware(
        is_public_endpoint=lambda _path: False,
        check_basic_auth_header=lambda _header: "admin",
        check_web_session=lambda _request: None,
        get_user_role=lambda _user: "admin",
        verify_totp_code=lambda _user, _code: True,
        required_role_for_request=lambda _method, _path: "admin",
        has_min_role=lambda _actual, _required: True,
        read_only_mode=False,
        invalidate_read_projections=lambda: None,
        http_request_count=_Metric(),
        http_request_latency=_Metric(),
        get_client_ip=lambda _request: "127.0.0.1",
        extract_basic_auth_username=lambda _header: None,
        enqueue_audit_event=lambda _event: None,
        allowed_origins=["http://testserver"],
    )


def test_attribution_bounds_untrusted_label_values(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "true")
    token = begin_request("safe-request-id", "/api/v1/telegram/node-policies")
    record_cache("alice@example.test?token=secret")
    record_node_rpc(
        "https://node.example.test/panel/api/inbounds/list?token=secret",
        method="GET",
        started_at=time.perf_counter(),
        outcome="ok",
    )
    attribution = finish_request(token)

    assert attribution is not None
    assert attribution.endpoint == "telegram_node_policies"
    assert attribution.cache_sources == {"other"}
    assert cache_source_label("alice@example.test") == "other"
    timing = server_timing(1.0, attribution)
    assert "example.test" not in timing
    assert "secret" not in timing
    assert "node_rpc" in timing


def test_middleware_attributes_request_sqlite_and_cache_without_changing_result(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "true")
    db_path = str(tmp_path / "fixture.db")
    with connect(db_path) as conn:
        conn.execute("CREATE TABLE fixture (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO fixture(value) VALUES (?)", ("safe",))

    app = FastAPI()
    app.middleware("http")(_middleware())

    @app.get("/api/v1/telegram/node-policies")
    def policies(request: Request):
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM fixture WHERE id = ?", (1,)
            ).fetchone()
        record_cache("memory_fresh")
        return {"value": row[0], "request_id": request.state.request_id}

    response = TestClient(app).get(
        "/api/v1/telegram/node-policies", headers={"X-Request-ID": "fixture-req-001"}
    )

    assert response.status_code == 200
    assert response.json() == {"value": "safe", "request_id": "fixture-req-001"}
    assert response.headers["X-Request-ID"] == "fixture-req-001"
    assert "admission;dur=" in response.headers["Server-Timing"]
    assert "sqlite;dur=" in response.headers["Server-Timing"]
    assert 'cache;desc="memory_fresh"' in response.headers["Server-Timing"]
    assert db_path not in response.headers["Server-Timing"]


def test_attribution_is_default_off(monkeypatch):
    monkeypatch.delenv("OBSERVABILITY_ATTRIBUTION_ENABLED", raising=False)
    token = begin_request("fixture-request", "/api/v1/telegram/node-policies")
    record_cache("memory_fresh")
    assert finish_request(token) is None
    assert server_timing(1.0, None) == "app;dur=1.00"


def test_xui_hook_records_a_fake_fixture_only(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "true")

    class _Response:
        status_code = 200

    monkeypatch.setattr(
        xui_session,
        "validate_and_resolve_outbound_url",
        lambda _url: (True, None, "127.0.0.1"),
    )
    monkeypatch.setattr(
        xui_session, "_pinned_session_request", lambda *_args, **_kwargs: _Response()
    )

    token = begin_request("fixture-rpc", "/api/v1/traffic/stats")
    response = xui_session.xui_request(
        object(), "GET", "https://fixture.example.test/panel/api/inbounds/list"
    )
    attribution = finish_request(token)

    assert response.status_code == 200
    assert attribution is not None
    assert attribution.phase_ms["node_rpc"] >= 0


def test_unmatched_paths_use_a_bounded_http_metric_label():
    count_metric, latency_metric = _RecordedMetric(), _RecordedMetric()
    app = FastAPI()
    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda _path: True,
            check_basic_auth_header=lambda _header: None,
            check_web_session=lambda _request: None,
            get_user_role=lambda _user: "viewer",
            verify_totp_code=lambda _user, _code: True,
            required_role_for_request=lambda _method, _path: "viewer",
            has_min_role=lambda _actual, _required: True,
            read_only_mode=False,
            invalidate_read_projections=lambda: None,
            http_request_count=count_metric,
            http_request_latency=latency_metric,
            get_client_ip=lambda _request: "127.0.0.1",
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=lambda _event: None,
        )
    )

    response = TestClient(app).get("/api/v1/not-a-route/alice@example.test")

    assert response.status_code == 404
    assert count_metric.labels_calls == [("GET", "other", "404")]
    assert latency_metric.labels_calls == [("GET", "other")]


def test_browser_fixture_proves_loopback_cold_warm_contract(tmp_path):
    db_path = str(tmp_path / "fixture.db")
    with connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE fixture_policy (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO fixture_policy(id, value) VALUES (1, 'fixture-only')")

    client = TestClient(build_fixture_app(db_path))
    page = client.get("/")
    assert page.status_code == 200
    assert (
        page.headers["Content-Security-Policy"]
        == "default-src 'self'; connect-src 'self'; img-src 'none'; style-src 'self'; script-src 'unsafe-inline'"
    )
    cold_response = client.get(
        "/api/v1/telegram/node-policies", headers={"X-OBS-Scenario": "cold"}
    )
    assert cold_response.status_code == 200
    assert cold_response.json()["cache_source"] == "memory_miss"
    warm_response = client.get(
        "/api/v1/telegram/node-policies", headers={"X-OBS-Scenario": "warm"}
    )
    assert warm_response.status_code == 200
    assert warm_response.json()["cache_source"] == "memory_fresh"

    report = client.get("/baseline-report").json()
    assert report == {
        "fake_node_calls": 0,
        "policy_reads": [
            {"scenario": "cold", "cache_source": "memory_miss"},
            {"scenario": "warm", "cache_source": "memory_fresh"},
        ],
        "unexpected_fixture_requests": [],
    }


def test_request_exception_resets_the_attribution_context(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "true")
    finishes = []
    original_finish = request_middleware.finish_request
    monkeypatch.setattr(
        request_middleware,
        "finish_request",
        lambda token: finishes.append(token) or original_finish(token),
    )
    app = FastAPI()
    app.middleware("http")(_middleware())

    @app.get("/api/v1/fail")
    def fail():
        raise RuntimeError("fixture failure")

    with pytest.raises(RuntimeError, match="fixture failure"):
        TestClient(app).get("/api/v1/fail")

    assert len(finishes) == 1


def test_concurrent_attribution_contexts_do_not_cross_contaminate(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "true")

    async def trace(path, cache_source):
        token = begin_request(f"fixture-{cache_source}", path)
        await asyncio.sleep(0)
        record_cache(cache_source)
        return finish_request(token)

    async def collect():
        return await asyncio.gather(
            trace("/api/v1/dashboard/overview", "snapshot"),
            trace("/api/v1/telegram/node-policies", "memory_miss"),
        )

    dashboard, policies = asyncio.run(collect())

    assert dashboard is not None and dashboard.cache_sources == {"snapshot"}
    assert policies is not None and policies.cache_sources == {"memory_miss"}


class _FailingMetric:
    def labels(self, *_args):
        raise RuntimeError("synthetic metric failure")


def test_metric_failure_does_not_change_response_or_attribution_cleanup(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY_ATTRIBUTION_ENABLED", "true")
    monkeypatch.setattr(observability, "_event_total", _FailingMetric())
    app = FastAPI()
    app.middleware("http")(_middleware())

    @app.get("/api/v1/dashboard/overview")
    def overview():
        record_cache("snapshot")
        return {"status": "fixture-ok"}

    response = TestClient(app).get("/api/v1/dashboard/overview")

    assert response.status_code == 200
    assert response.json() == {"status": "fixture-ok"}
    assert "unaccounted;dur=" in response.headers["Server-Timing"]
    assert finish_request(None) is None


def test_unaccounted_is_only_a_conservative_remainder():
    attribution = RequestAttribution(
        request_id="fixture", endpoint="dashboard_overview"
    )
    attribution.phase_ms["sqlite"] = 4.0
    assert "unaccounted;dur=6.00" in server_timing(10.0, attribution)

    # Overlapping component aggregates can exceed wall-clock app duration.
    # The header must not turn that into an invented negative wait duration.
    attribution.phase_ms["node_rpc"] = 20.0
    assert "unaccounted;dur=0.00" in server_timing(10.0, attribution)
