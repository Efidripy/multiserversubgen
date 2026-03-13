from __future__ import annotations

import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse


def build_request_controls_and_audit_middleware(
    *,
    is_public_endpoint,
    check_basic_auth_header,
    get_user_role,
    verify_totp_code,
    required_role_for_request,
    has_min_role,
    read_only_mode: bool,
    invalidate_live_stats_cache,
    http_request_count,
    http_request_latency,
    get_client_ip,
    extract_basic_auth_username,
    enqueue_audit_event,
):
    async def request_controls_and_audit_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        path = request.url.path

        request.state.auth_user = None
        request.state.auth_role = None
        request.state.auth_mfa_ok = False

        response = None

        if path.startswith("/api/v1/") and not is_public_endpoint(path):
            auth_user = check_basic_auth_header(request.headers.get("Authorization"))
            if not auth_user:
                response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            else:
                auth_role = get_user_role(auth_user)
                request.state.auth_user = auth_user
                request.state.auth_role = auth_role
                mfa_code = request.headers.get("X-TOTP-Code")
                if not verify_totp_code(auth_user, mfa_code):
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

        if response is None and read_only_mode and request.method in {"POST", "PUT", "DELETE", "PATCH"} and path.startswith("/api/v1/"):
            response = JSONResponse(
                status_code=403,
                content={"detail": "Read-only mode is enabled"},
            )
        elif response is None:
            response = await call_next(request)

        if (
            response.status_code < 400
            and request.method in {"POST", "PUT", "DELETE", "PATCH"}
            and path.startswith("/api/v1/")
        ):
            invalidate_live_stats_cache()

        response.headers["X-Request-ID"] = request_id
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        path_label = path if path.startswith("/api/v1/") else path
        http_request_count.labels(request.method, path_label, str(response.status_code)).inc()
        http_request_latency.labels(request.method, path_label).observe(duration_ms / 1000.0)
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

    return request_controls_and_audit_middleware
