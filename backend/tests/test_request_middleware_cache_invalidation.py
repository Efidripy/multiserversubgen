import os
import sys

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.main_facades import build_cache_facade
from core.request_middleware import build_request_controls_and_audit_middleware


class _MetricValue:
    def inc(self):
        pass

    def observe(self, _value):
        pass


class _Metric:
    def labels(self, *_args):
        return _MetricValue()


def test_cache_facade_invalidates_each_read_projection_runtime():
    class Runtime:
        def __init__(self):
            self.calls = 0

        def invalidate(self):
            self.calls += 1

    live_stats, clients, inbounds = Runtime(), Runtime(), Runtime()
    facade = build_cache_facade(
        live_stats_runtime=live_stats,
        clients_runtime=clients,
        inbounds_runtime=inbounds,
        audit_runtime=object(),
    )

    facade[1]()

    assert (live_stats.calls, clients.calls, inbounds.calls) == (1, 1, 1)


def test_successful_mutation_invalidates_read_projections_once():
    invalidations = []
    app = FastAPI()
    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda _path: False,
            check_basic_auth_header=lambda _header: "admin",
            check_web_session=lambda _request: None,
            get_user_role=lambda _user: "admin",
            verify_totp_code=lambda _user, _code: True,
            required_role_for_request=lambda _method, _path: "admin",
            has_min_role=lambda _actual, _required: True,
            read_only_mode=False,
            invalidate_read_projections=lambda: invalidations.append("read-projections"),
            http_request_count=_Metric(),
            http_request_latency=_Metric(),
            get_client_ip=lambda _request: "127.0.0.1",
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=lambda _event: None,
            allowed_origins=["http://testserver"],
        )
    )

    @app.post("/api/v1/mutate")
    def mutate():
        return {"success": True}

    @app.post("/api/v1/rejected")
    def rejected():
        return Response(status_code=400)

    client = TestClient(app)
    headers = {"Origin": "http://testserver"}
    assert client.post("/api/v1/mutate", headers=headers).status_code == 200
    assert client.post("/api/v1/rejected", headers=headers).status_code == 400
    assert invalidations == ["read-projections"]
