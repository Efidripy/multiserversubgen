from __future__ import annotations

import time
import uuid
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from shared.observability import begin_request, endpoint_label, finish_request, record_admission, server_timing
from shared.security import safe_request_id


def is_trusted_loopback_metrics_scrape(request: Request) -> bool:
    """Allow the local Prometheus process to scrape metrics without panel auth.

    The application is commonly reached from nginx over loopback as well, so a
    loopback peer alone is not sufficient: nginx supplies ``X-Forwarded-For``
    for public requests. Prometheus connects directly and does not send that
    header. This keeps metrics unavailable to anonymous browser traffic while
    avoiding credentials in the Prometheus configuration.
    """
    peer_host = getattr(request.client, "host", "") if request.client else ""
    return (
        request.url.path == "/metrics"
        and peer_host in {"127.0.0.1", "::1"}
        and not request.headers.get("X-Forwarded-For", "").strip()
    )


def should_audit_http_access(request: Request) -> bool:
    """Keep the durable audit trail for control-plane access, not local scrapes.

    A direct loopback ``/metrics`` scrape is a trusted, read-only Prometheus
    collection path. It still emits the usual HTTP metrics below, but writing
    every scrape through the SQLite audit queue only creates avoidable churn.
    The narrow trust predicate is shared with the authentication exception, so
    proxied or external ``/metrics`` requests remain durably audited.
    """
    return not getattr(request.state, "metrics_loopback_allowed", False)


def build_request_controls_and_audit_middleware(
    *,
    is_public_endpoint,
    check_basic_auth_header,
    check_web_session,
    get_user_role,
    verify_totp_code,
    required_role_for_request,
    has_min_role,
    read_only_mode: bool,
    invalidate_read_projections,
    http_request_count,
    http_request_latency,
    get_client_ip,
    extract_basic_auth_username,
    enqueue_audit_event,
    allowed_origins=None,
):
    configured_origins = {str(origin).rstrip("/") for origin in (allowed_origins or []) if origin}

    def _csrf_origin_ok(request: Request) -> bool:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"} or not request.url.path.startswith("/api/v1/"):
            return True
        origin = request.headers.get("Origin", "").strip().rstrip("/")
        referer = request.headers.get("Referer", "").strip()
        candidate = origin or (f"{urlparse(referer).scheme}://{urlparse(referer).netloc}" if referer else "")
        if not candidate:
            return False
        if candidate in configured_origins:
            return True
        request_origin = f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
        return candidate == request_origin

    async def request_controls_and_audit_middleware(request: Request, call_next):
        request_id = safe_request_id(request.headers.get("X-Request-ID")) or uuid.uuid4().hex
        start = time.perf_counter()
        path = request.url.path
        attribution_token = begin_request(request_id, path)
        try:
            request.state.auth_user = None
            request.state.auth_role = None
            request.state.auth_mfa_ok = False
            request.state.auth_via = None
            request.state.request_id = request_id
            request.state.metrics_loopback_allowed = is_trusted_loopback_metrics_scrape(request)

            response = None

            protected_path = path.startswith("/api/v1/") or path == "/metrics"
            if protected_path and not request.state.metrics_loopback_allowed and not is_public_endpoint(path):
                auth_user = check_basic_auth_header(request.headers.get("Authorization"))
                auth_via = "basic" if auth_user else None
                if not auth_user:
                    auth_user = check_web_session(request)
                    auth_via = "session" if auth_user else None
                if not auth_user:
                    response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
                else:
                    auth_role = get_user_role(auth_user)
                    request.state.auth_user = auth_user
                    request.state.auth_role = auth_role
                    request.state.auth_via = auth_via
                    mfa_ok = auth_via == "session" or verify_totp_code(auth_user, request.headers.get("X-TOTP-Code"))
                    if not mfa_ok:
                        response = JSONResponse(status_code=401, content={"detail": "MFA required"})
                        request.state.auth_mfa_ok = False
                    else:
                        request.state.auth_mfa_ok = True

                    required_role = required_role_for_request(request.method, path)
                    if response is None and not has_min_role(auth_role, required_role):
                        response = JSONResponse(
                            status_code=403,
                            content={"detail": f"Forbidden for role '{auth_role}', requires '{required_role}'"},
                        )
                    if response is None and not _csrf_origin_ok(request):
                        response = JSONResponse(status_code=403, content={"detail": "CSRF origin check failed"})

            if response is None and read_only_mode and request.method in {"POST", "PUT", "DELETE", "PATCH"} and path.startswith("/api/v1/"):
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "Read-only mode is enabled"},
                )

            admission_outcome = "ok" if response is None else "http_4xx" if response.status_code < 500 else "http_5xx"
            record_admission(start, outcome=admission_outcome)

            if response is None:
                response = await call_next(request)

            if (
                response.status_code < 400
                and request.method in {"POST", "PUT", "DELETE", "PATCH"}
                and path.startswith("/api/v1/")
                and not getattr(request.state, "skip_read_projection_invalidation", False)
            ):
                invalidate_read_projections()

            response.headers["X-Request-ID"] = request_id
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            attribution = finish_request(attribution_token)
            attribution_token = None
            route = request.scope.get("route")
            path_label = getattr(route, "path", None) or endpoint_label(path)
            response.headers["Server-Timing"] = server_timing(duration_ms, attribution)
            http_request_count.labels(request.method, path_label, str(response.status_code)).inc()
            http_request_latency.labels(request.method, path_label).observe(duration_ms / 1000.0)
            if should_audit_http_access(request):
                audit_payload = {
                    "event": "http_access",
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": get_client_ip(request),
                    "user_hint": request.state.auth_user or extract_basic_auth_username(request.headers.get("Authorization")) or "anonymous",
                    "user_role": request.state.auth_role,
                }
                enqueue_audit_event(audit_payload)
            return response
        finally:
            if attribution_token is not None:
                finish_request(attribution_token)

    return request_controls_and_audit_middleware
