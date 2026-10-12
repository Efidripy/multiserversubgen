"""Run the OBS-001 browser waterfall fixture on loopback only.

This is not an application server and it never loads MSSG runtime settings,
nodes, credentials, or external URLs.  It exists solely to make the browser
baseline reproducible against a temporary SQLite database and zero fake-node
calls.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from core.request_middleware import build_request_controls_and_audit_middleware  # noqa: E402
from services.db_bootstrap import connect  # noqa: E402
from shared.observability import record_cache  # noqa: E402


_ALLOWED_PATHS = {
    "/",
    "/favicon.ico",
    "/api/v1/dashboard/overview",
    "/api/v1/telegram/node-policies",
    "/baseline-report",
}
_LOOPBACK_CLIENTS = {"127.0.0.1", "::1", "testclient"}
_LOOPBACK_CSP = "default-src 'self'; connect-src 'self'; img-src 'none'; style-src 'self'; script-src 'unsafe-inline'"


def _scenario(request: Request) -> str:
    value = request.headers.get("X-OBS-Scenario", "").strip().lower()
    return value if value in {"cold", "warm"} else "other"


class _MetricValue:
    def inc(self) -> None:
        pass

    def observe(self, _value: float) -> None:
        pass


class _Metric:
    def labels(self, *_args: object) -> _MetricValue:
        return _MetricValue()


def build_fixture_app(db_path: str) -> FastAPI:
    app = FastAPI()
    app.state.fake_node_calls = 0
    app.state.policy_cache_warm = False
    app.state.policy_reads = []
    app.state.unexpected_fixture_requests = []

    @app.middleware("http")
    async def loopback_fixture_guard(request: Request, call_next):
        peer_host = getattr(request.client, "host", "") if request.client else ""
        if peer_host not in _LOOPBACK_CLIENTS:
            return HTMLResponse(status_code=403, content="loopback fixture only")
        if request.url.path not in _ALLOWED_PATHS:
            app.state.unexpected_fixture_requests.append(request.url.path)
        return await call_next(request)

    app.middleware("http")(
        build_request_controls_and_audit_middleware(
            is_public_endpoint=lambda _path: True,
            check_basic_auth_header=lambda _header: None,
            check_web_session=lambda _request: None,
            get_user_role=lambda _user: "viewer",
            verify_totp_code=lambda _user, _code: True,
            required_role_for_request=lambda _method, _path: "viewer",
            has_min_role=lambda _actual, _required: True,
            read_only_mode=True,
            invalidate_read_projections=lambda: None,
            http_request_count=_Metric(),
            http_request_latency=_Metric(),
            get_client_ip=lambda _request: "127.0.0.1",
            extract_basic_auth_username=lambda _header: None,
            enqueue_audit_event=lambda _event: None,
            allowed_origins=[],
        )
    )

    @app.get("/", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return HTMLResponse(
            """<!doctype html><title>OBS-001 local baseline</title>
<main><h1>OBS-001 local baseline</h1><output id=state>loading</output></main>
<script>
const scenario = new URLSearchParams(window.location.search).get('scenario') || 'other';
Promise.all([
  fetch('/api/v1/dashboard/overview', {headers: {'X-Request-ID': `fixture-dashboard-${scenario}`, 'X-OBS-Scenario': scenario}}),
  fetch('/api/v1/telegram/node-policies', {headers: {'X-Request-ID': `fixture-policy-${scenario}`, 'X-OBS-Scenario': scenario}}),
]).then(async responses => {
  const payloads = await Promise.all(responses.map(response => response.json()));
  document.querySelector('#state').textContent = JSON.stringify(payloads);
}).catch(error => { document.querySelector('#state').textContent = `error:${error.name}`; });
</script>""",
            headers={"Content-Security-Policy": _LOOPBACK_CSP},
        )

    @app.get("/favicon.ico")
    def favicon() -> HTMLResponse:
        return HTMLResponse(status_code=204)

    @app.get("/api/v1/dashboard/overview")
    def dashboard(request: Request) -> dict:
        record_cache("snapshot")
        return {
            "source": "fixture_snapshot",
            "fake_node_calls": request.app.state.fake_node_calls,
        }

    @app.get("/api/v1/telegram/node-policies")
    def policies(request: Request) -> dict:
        with connect(db_path) as conn:
            row = conn.execute(
                "SELECT value FROM fixture_policy WHERE id = 1"
            ).fetchone()
        source = "memory_fresh" if app.state.policy_cache_warm else "memory_miss"
        app.state.policy_cache_warm = True
        app.state.policy_reads.append(
            {"scenario": _scenario(request), "cache_source": source}
        )
        record_cache(source)
        return {
            "items": [{"policy": row[0]}],
            "cache_source": source,
            "fake_node_calls": app.state.fake_node_calls,
        }

    @app.get("/baseline-report")
    def report() -> dict:
        return {
            "fake_node_calls": app.state.fake_node_calls,
            "policy_reads": app.state.policy_reads,
            "unexpected_fixture_requests": app.state.unexpected_fixture_requests,
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the loopback-only OBS-001 browser fixture"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="mssg-obs001-") as directory:
        db_path = str(Path(directory) / "fixture.db")
        with connect(db_path) as conn:
            conn.execute(
                "CREATE TABLE fixture_policy (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO fixture_policy(id, value) VALUES (1, 'fixture-only')"
            )
        uvicorn.run(
            build_fixture_app(db_path),
            host="127.0.0.1",
            port=args.port,
            log_level="warning",
        )


if __name__ == "__main__":
    main()
