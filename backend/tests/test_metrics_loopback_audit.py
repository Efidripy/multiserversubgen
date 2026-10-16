from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.request_middleware import build_request_controls_and_audit_middleware


class _MetricValue:
    def inc(self):
        pass

    def observe(self, _value):
        pass


class _Metric:
    def __init__(self):
        self.labels_calls = []

    def labels(self, *_args):
        self.labels_calls.append(_args)
        return _MetricValue()


def _app(audit_events):
    app = FastAPI()
    count_metric, latency_metric = _Metric(), _Metric()
    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda _path: False,
            check_basic_auth_header=lambda header: (
                "admin" if header == "Basic admin" else None
            ),
            check_web_session=lambda _request: None,
            get_user_role=lambda _user: "admin",
            verify_totp_code=lambda _user, _code: True,
            required_role_for_request=lambda _method, _path: "admin",
            has_min_role=lambda _actual, _required: True,
            read_only_mode=False,
            invalidate_read_projections=lambda: None,
            http_request_count=count_metric,
            http_request_latency=latency_metric,
            get_client_ip=lambda request: request.client.host,
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=audit_events.append,
        )
    )

    @app.get("/metrics")
    def metrics():
        return {"ok": True}

    @app.get("/api/v1/nodes")
    def nodes():
        return {"nodes": []}

    return app, count_metric, latency_metric


def test_trusted_loopback_metrics_scrape_skips_durable_audit_but_keeps_other_access():
    audit_events = []
    app, count_metric, latency_metric = _app(audit_events)

    direct_loopback = TestClient(app, client=("127.0.0.1", 39090))
    assert direct_loopback.get("/metrics").status_code == 200
    assert audit_events == []
    assert count_metric.labels_calls == [("GET", "/metrics", "200")]
    assert latency_metric.labels_calls == [("GET", "/metrics")]

    proxied_loopback = TestClient(app, client=("127.0.0.1", 39091))
    assert (
        proxied_loopback.get(
            "/metrics",
            headers={
                "Authorization": "Basic admin",
                "X-Forwarded-For": "198.51.100.42",
            },
        ).status_code
        == 200
    )

    external = TestClient(app, client=("198.51.100.42", 39092))
    assert (
        external.get("/metrics", headers={"Authorization": "Basic admin"}).status_code
        == 200
    )

    assert (
        direct_loopback.get(
            "/api/v1/nodes", headers={"Authorization": "Basic admin"}
        ).status_code
        == 200
    )
    assert [(event["path"], event["client_ip"]) for event in audit_events] == [
        ("/metrics", "127.0.0.1"),
        ("/metrics", "198.51.100.42"),
        ("/api/v1/nodes", "127.0.0.1"),
    ]
